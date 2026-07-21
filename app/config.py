"""Configurazione app: legge variabili ambiente, gestisce chiave segreta persistente."""
import os
import secrets

# Directory dati (DB + chiave). In Docker montata su volume /data.
DATA_DIR = os.environ.get("DATA_DIR", "./data")

# Password unica per il login (impostata via .env). Default insicuro solo per test.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "admin")

# Nome mostrato nell'interfaccia
APP_NAME = os.environ.get("APP_NAME", "MAGAZZINO")


def get_secret_key() -> str:
    """Chiave per firmare i cookie di sessione.

    Priorita: variabile SECRET_KEY -> file persistente -> generata nuova.
    Persistere la chiave evita che gli utenti vengano sloggati ad ogni riavvio.
    """
    key = os.environ.get("SECRET_KEY")
    if key:
        return key

    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, ".secret_key")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            saved = f.read().strip()
            if saved:
                return saved

    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    return key
