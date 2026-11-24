"""Helper per i test HTTP."""
import re


def get_csrf(client) -> str:
    html = client.get("/").text
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else ""


FETCH = {"X-Requested-With": "fetch"}


def sign_new(client, name="Tester", password="segreto1", action=None):
    """Crea un operatore nuovo e firma (sessione attiva). Ritorna la risposta JSON."""
    body = {"new_name": name, "password": password}
    if action:
        body["action"] = action
    return client.post("/sign/password", json=body, headers=FETCH).json()


def sign_as(client, operator_id, password="segreto1", action=None):
    body = {"operator_id": operator_id, "password": password}
    if action:
        body["action"] = action
    return client.post("/sign/password", json=body, headers=FETCH).json()


def critical_post(client, path, operator_id, data=None, password="segreto1"):
    """POST firmato con token di azione critica."""
    token = sign_as(client, operator_id, password, action=f"POST {path}")["action_token"]
    return client.post(path, data=data or {}, headers={**FETCH, "X-Sig-Token": token})
