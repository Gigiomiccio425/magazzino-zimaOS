"""Registro test: esito suggerito dalle regole del modello (l'operatore conferma sempre)."""
import re
import unicodedata

from .component_form import parse_number


def slug_key(label: str) -> str:
    text = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")[:40] or "campo"


def parse_values(fields: list[dict], form) -> dict:
    """Valori del form (`v_<key>`): numeri come numeri, sì/no come booleani, vuoti esclusi."""
    values = {}
    for f in fields:
        raw = form.get(f"v_{f['key']}")
        if f.get("type") == "bool":
            if raw is not None and raw != "":
                values[f["key"]] = raw == "1"
            continue
        if f.get("type") == "number":
            value = parse_number(raw or "")
        else:
            value = (raw or "").strip() or None
        if value is not None:
            values[f["key"]] = value
    return values


def suggest_result(fields: list[dict], values: dict) -> str | None:
    """'fail' se un numero esce da min/max o un sì/no differisce dal valore atteso; 'pass' se tutte le
    regole valutate sono rispettate; None se nessuna regola si applica."""
    evaluated = False
    for f in fields:
        raw = values.get(f["key"])
        if f.get("type") == "number" and (f.get("min") is not None or f.get("max") is not None):
            if raw in (None, ""):
                continue
            try:
                n = float(str(raw).replace(",", "."))
            except ValueError:
                continue
            evaluated = True
            if f.get("min") is not None and n < f["min"]:
                return "fail"
            if f.get("max") is not None and n > f["max"]:
                return "fail"
        elif f.get("type") == "bool" and "pass_value" in f:
            if raw in (None, ""):
                continue  # non compilato: nessuna regola valutata
            value = raw is True or raw in ("1", 1, "true")
            evaluated = True
            if value != bool(f["pass_value"]):
                return "fail"
    return "pass" if evaluated else None


def fields_from_form(form) -> list[dict]:
    labels, types = form.getlist("field_label"), form.getlist("field_type")
    units, mins, maxs = form.getlist("field_unit"), form.getlist("field_min"), form.getlist("field_max")
    passes = form.getlist("field_pass")
    fields, seen = [], set()
    for i, label in enumerate(labels):
        label = " ".join((label or "").split())
        if not label:
            continue
        key = slug_key(label)
        while key in seen:
            key += "_"
        seen.add(key)
        ftype = types[i] if i < len(types) and types[i] in ("number", "text", "bool") else "text"
        f = {"key": key, "label": label, "type": ftype}
        if ftype == "number":
            f["unit"] = (units[i] if i < len(units) else "").strip()
            f["min"] = parse_number(mins[i]) if i < len(mins) and mins[i].strip() else None
            f["max"] = parse_number(maxs[i]) if i < len(maxs) and maxs[i].strip() else None
        if ftype == "bool":
            f["pass_value"] = (passes[i] if i < len(passes) else "") == "1"
        fields.append(f)
    return fields
