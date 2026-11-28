"""Controllo di compatibilità dei componenti montati su una macchina.

Regole semplici e spiegate, basate sulle caratteristiche già inserite (nessun dato esterno):
socket CPU/scheda madre, generazione RAM, SO-DIMM o DIMM, slot RAM, potenza dell'alimentatore.
"""
import re
from dataclasses import dataclass

from ..models import Component, Machine

# generazione RAM supportata dai socket più diffusi
SOCKET_DDR = {
    "AM5": {"DDR5"}, "AM4": {"DDR4"}, "AM3+": {"DDR3"}, "AM3": {"DDR3"}, "FM2+": {"DDR3"},
    "LGA1851": {"DDR5"}, "LGA1700": {"DDR4", "DDR5"}, "LGA1200": {"DDR4"}, "LGA1151": {"DDR4", "DDR3"},
    "LGA1150": {"DDR3"}, "LGA1155": {"DDR3"}, "LGA1156": {"DDR3"}, "LGA775": {"DDR2", "DDR3"},
    "LGA2066": {"DDR4"}, "LGA2011-3": {"DDR4"}, "LGA2011": {"DDR3"}, "AM2+": {"DDR2"}, "AM2": {"DDR2"},
}
LAPTOP_WORDS = ("laptop", "portatile", "notebook", "mini pc", "nuc", "minipc")
BASE_WATT = 100  # scheda madre, dischi, ventole


@dataclass
class Finding:
    level: str  # error | warn | ok
    message: str


def _cat(c: Component) -> str:
    return (c.category or "").strip().lower()


def _num(value) -> float | None:
    try:
        return float(str(value).replace(",", ".").split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def _socket(value) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper().replace("SOCKET", "")


def _ram_gen(c: Component) -> str | None:
    m = re.search(r"DDR(\d?)", str((c.attributes or {}).get("Tipo") or c.name).upper())
    return ("DDR" + m.group(1)) if m else None


def _is_sodimm(c: Component) -> bool:
    attrs = c.attributes or {}
    return "SO-DIMM" in f"{attrs.get('Tipo', '')} {attrs.get('Form factor', '')} {c.name}".upper()


def check(machine: Machine, parts: list[Component]) -> list[Finding]:
    out: list[Finding] = []
    cpus = [c for c in parts if _cat(c) == "cpu"]
    boards = [c for c in parts if _cat(c) == "scheda madre"]
    rams = [c for c in parts if _cat(c) == "ram"]
    gpus = [c for c in parts if _cat(c) == "gpu"]
    psus = [c for c in parts if _cat(c) == "alimentatore"]
    board = boards[0] if boards else None
    board_socket = _socket((board.attributes or {}).get("Socket")) if board else ""

    if len(boards) > 1:
        out.append(Finding("warn", f"Ci sono {len(boards)} schede madri montate sulla stessa macchina."))
    for cpu in cpus:
        sock = _socket((cpu.attributes or {}).get("Socket"))
        if board_socket and sock and sock != board_socket:
            out.append(Finding("error", f"{cpu.name}: socket {sock}, ma la scheda madre {board.name} è {board_socket}."))

    socket = board_socket or (_socket((cpus[0].attributes or {}).get("Socket")) if cpus else "")
    gens = {g for g in (_ram_gen(r) for r in rams) if g}
    if len(gens) > 1:
        out.append(Finding("error", "RAM di generazioni diverse montate insieme: " + ", ".join(sorted(gens)) + "."))
    allowed = SOCKET_DDR.get(socket)
    if allowed and gens and not gens & allowed:
        out.append(Finding("error", f"Il socket {socket} usa {' o '.join(sorted(allowed))}, ma la RAM è {', '.join(sorted(gens))}."))

    kind = f"{machine.kind or ''} {machine.name or ''}".lower()
    laptop = any(w in kind for w in LAPTOP_WORDS)
    for r in rams:
        if laptop and not _is_sodimm(r):
            out.append(Finding("warn", f"{r.name}: modulo DIMM da desktop su una macchina portatile o mini PC."))
        elif not laptop and board and _is_sodimm(r):
            out.append(Finding("warn", f"{r.name}: modulo SO-DIMM (da portatile) con una scheda madre desktop."))
    slots = _num((board.attributes or {}).get("Slot RAM")) if board else None
    modules = sum(int(_num((r.attributes or {}).get("Moduli")) or 1) * max(1, r.quantity or 1) for r in rams)
    if slots and modules > slots:
        out.append(Finding("error", f"{modules} moduli RAM ma la scheda madre ha {int(slots)} slot."))

    if psus:
        watt = _num((psus[0].attributes or {}).get("Potenza (W)"))
        need = BASE_WATT + sum(_num((c.attributes or {}).get("TDP")) or 0 for c in cpus + gpus)
        if watt and need > watt * 0.8:
            level = "error" if need > watt else "warn"
            out.append(Finding(level, f"Consumo stimato {int(need)} W su un alimentatore da {int(watt)} W "
                                      f"(consigliato restare sotto l'80%: {int(watt * 0.8)} W)."))
    elif gpus or cpus:
        out.append(Finding("warn", "Nessun alimentatore montato: impossibile controllare la potenza."))

    if not out and (cpus or rams or board):
        out.append(Finding("ok", "Nessun problema di compatibilità trovato con i dati inseriti."))
    return out
