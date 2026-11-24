"""Payload per webhook Discord (embed) e generici (JSON). Nessuna menzione salvo ruolo per SEV1."""
import re
from urllib.parse import urlparse

from ..models import EVENTS
from ..timeutil import utcnow

DISCORD_RE = re.compile(r"^https://(discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)/api/webhooks/\d+/[\w-]+$")
SEVERITY_COLORS = {"SEV1": 0xE2231A, "SEV2": 0xF07F13, "SEV3": 0xF4C20D, "SEV4": 0x8A8A8A}
GREEN, RED, YELLOW, BLACK = 0x2E7D32, 0xE2231A, 0xF4C20D, 0x111111
GREEN_EVENTS = {"incident.resolved", "maintenance.completed"}
LIMITS = {"title": 256, "description": 4096, "fields": 25, "field_name": 256, "field_value": 1024}


def is_valid_discord_url(url: str) -> bool:
    return bool(DISCORD_RE.match((url or "").strip()))


def mask_url(url: str) -> str:
    u = urlparse(url or "")
    if is_valid_discord_url(url):
        return f"{u.netloc}/api/webhooks/…"
    return f"{u.scheme}://{u.netloc}/…" if u.netloc else "…"


def _cut(text, limit: int) -> str:
    text = str(text if text is not None else "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _color(event: str, data: dict) -> int:
    if data.get("resolved") or event in GREEN_EVENTS:
        return GREEN
    if event == "test.failed":
        return RED
    if event == "stock.low":
        return YELLOW
    return SEVERITY_COLORS.get(data.get("severity") or "", BLACK)


def _title(event: str, data: dict) -> str:
    title = data.get("title") or ""
    if event.startswith("incident.") and data.get("severity"):
        return f"[{data['severity']}] {title}"
    return f"{EVENTS.get(event, event)}: {title}"


def build_payload(event: str, data: dict, *, base_url: str, app_name: str, mention_role_id: str | None = None,
                  username: str | None = None, avatar_url: str | None = None) -> dict:
    fields = []
    if data.get("status_label"):
        fields.append(["Stato", data["status_label"]])
    fields += [list(f) for f in data.get("fields") or []]
    if data.get("operator"):
        fields.append(["Operatore", data["operator"]])
    embed = {
        "title": _cut(_title(event, data), LIMITS["title"]),
        "color": _color(event, data),
        "fields": [
            {"name": _cut(n, LIMITS["field_name"]) or "-", "value": _cut(v, LIMITS["field_value"]) or "-", "inline": True}
            for n, v in fields[: LIMITS["fields"]]
        ],
        "footer": {"text": app_name},
        "timestamp": utcnow().isoformat(timespec="seconds") + "Z",
    }
    if data.get("description"):
        embed["description"] = _cut(data["description"], LIMITS["description"])
    if base_url and data.get("url_path"):
        embed["url"] = base_url.rstrip("/") + data["url_path"]
    payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}
    if mention_role_id and event == "incident.opened" and data.get("severity") == "SEV1":
        payload["content"] = f"<@&{mention_role_id}>"
        payload["allowed_mentions"] = {"parse": [], "roles": [mention_role_id]}
    if username:
        payload["username"] = _cut(username, 80)
    if avatar_url:
        payload["avatar_url"] = avatar_url
    return payload


def build_generic_payload(event: str, data: dict, app_name: str) -> dict:
    return {"event": event, "app": app_name, "sent_at": utcnow().isoformat(timespec="seconds") + "Z", "data": data}
