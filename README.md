# GD MAGAZZINO 2.0 — Magazzino hardware e centro di comando self-hosted

Inventario di componenti e hardware (schede video, cavi, RAM, dischi…) e centro di comando per
i servizi del server: changelog, incidenti, manutenzioni, avvisi Discord. Ogni modifica è firmata
dall'operatore che la fa, con impronta/passkey o password.

Design **costruttivista** (nero / carta / rosso). Stack: **FastAPI + SQLite + Jinja2 + JS vanilla**,
un solo container Docker. Pensato per **Umbrel** e **ZimaOS**.

---

## Funzioni

**Magazzino**
- Articoli **a seriale** (una GPU = una scheda) o **a quantità** (cavi, viti) con scorta minima.
- **Posizioni ad albero** (stanza › scaffale › box) e **QR** su ogni prodotto, posizione e macchina:
  la fotocamera del telefono apre direttamente la scheda. Etichette stampabili 25×25, 50×25, A4.
- **Campi per categoria** (VRAM, capacità, lunghezza cavo…) con filtri numerici e a scelta.
- Foto e allegati (i metadati GPS vengono rimossi), acquisto e garanzia, tag, stati estesi
  (da testare, testato OK, in RMA, venduto…).
- Scanner con fotocamera (anche iPhone), **scansione a raffica**, modifica di massa, import/export CSV.
- **Progetti/build**: prenoti i pezzi, alla fine vengono montati e le scorte scalate.
- **Cestino**: niente viene cancellato per errore.

**Verifica**
- **Registro test** con modelli per categoria (stress GPU, MemTest, SMART, tester alimentatore…).
- **Inventari fisici**: scansioni una posizione e vedi trovati, mancanti, fuori posto.

**Centro di comando** (tutto inserito a mano)
- Servizi e moduli (app web, app PC, app Android/iOS, bot, API) con versione.
- Changelog con link GitHub (commit, PR, issue, release riconosciuti dall'URL).
- Incidenti SEV1–SEV4 con cronologia e post-mortem, problemi noti, manutenzioni, pagina di stato.
- **Avvisi Discord**: partono solo quando spunti "Pubblica su Discord". Nessun `@everyone`.

**Sicurezza e tracciabilità**
- Operatori con nome: alla prima firma registri **impronta/passkey** e/o **password**.
  L'impronta funziona solo in HTTPS e vale per l'indirizzo dove l'hai registrata.
- Dopo una firma il dispositivo resta firmato per 10 minuti (regolabile). Eliminazioni,
  ripristini, impostazioni e webhook chiedono sempre una firma nuova.
- **Audit log** di ogni modifica con catena di hash e verifica di integrità.

---

## Installazione su Umbrel

L'app è nell'app store personale **Gigio-dany-appstore** (`GD Magazzino`). Il login Umbrel è
obbligatorio davanti all'app: la v2 non ha più una password propria.

Dati: `/Apps/g-d-app-store-gd-magazzino/data` (database, allegati, backup).

## Installazione standalone (ZimaOS / Docker)

```yaml
services:
  magazzino:
    image: ghcr.io/gigiomiccio425/magazzino-zimaos:2.0.0
    ports: ["8086:8000"]
    environment:
      - TZ=Europe/Rome
      - DATA_DIR=/data
    volumes:
      - /DATA/AppData/magazzino:/data
    restart: unless-stopped
```

> **Attenzione:** senza password propria l'app va tenuta dietro un proxy con autenticazione
> (login Umbrel, Authelia, Tailscale…). Non esporla direttamente su internet.

## Variabili d'ambiente

| Variabile         | Default       | Descrizione |
|-------------------|---------------|-------------|
| `APP_NAME`        | `MAGAZZINO`   | Nome mostrato nell'interfaccia. |
| `TZ`              | `Europe/Rome` | Fuso orario. |
| `DATA_DIR`        | `/data`       | Cartella dati nel container. |
| `SECRET_KEY`      | *(auto)*      | Firma dei cookie; vuoto = generata e salvata in `data`. |
| `PUBLIC_BASE_URL` | *(vuoto)*     | URL nei QR e nei link Discord (anche da Impostazioni). |
| `WEBAUTHN_RP_ID`  | *(vuoto)*     | Dominio fisso per le passkey; vuoto = dominio della richiesta. |

`APP_PASSWORD` non è più usata.

---

## Aggiornare dalla 1.1.x

1. (Consigliato) copia la cartella dati.
2. Aggiorna l'app (Umbrel: aggiorna dall'app store; standalone: cambia il tag in `:2.0.0` e ricrea).
3. All'avvio l'app fa un backup in `data/backups/pre-migrazione/` e aggiorna il database.
   Se qualcosa va storto il database resta com'era e l'app non parte.
4. Alla prima modifica ti chiede il nome: il primo operatore diventa amministratore.

## Backup e ripristino

- Automatici: prima di ogni aggiornamento (ultimi 10) e ogni notte alle 03:00 (ultimi 14).
- **Sistema › Backup**: scarica uno zip completo (database + allegati) o ripristina un backup.
  Il ripristino salva prima lo stato attuale in `backups/pre-ripristino/`.

## Sviluppo

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest                       # Windows: .venv\Scripts\python
.venv/bin/python -m uvicorn app.main:create_app --factory --reload
```

Struttura: `app/` (FastAPI: `routers/`, `services/`, `models/`, `migrations/`), `templates/`,
`static/` (CSS, JS, scanner offline in `static/vendor/`, PWA), `tests/`.

Rilascio: `git tag -a vX.Y.Z && git push origin vX.Y.Z` → GitHub Actions esegue i test e
pubblica `ghcr.io/gigiomiccio425/magazzino-zimaos:X.Y.Z`.
