"""Helper per i test HTTP."""
import re


def get_csrf(client) -> str:
    html = client.get("/").text
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else ""
