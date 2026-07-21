# MAGAZZINO — Inventario Hardware self-hosted

App web per tenere traccia di componenti e hardware: dove sono installati (su quale
macchina), codice oggetto, modello, produttore, seriale, stato, e attributi specifici
per tipo (es. capacita/velocita per le memorie). Storico spostamenti incluso.

Design **costruttivista**: geometrico, asimmetrico, nero / bianco / rosso.
Stack: **FastAPI + SQLite**, tutto in **un container Docker**. Pensato per **ZimaOS**.

---

## Funzioni

- **Componenti**: codice oggetto, nome, categoria, modello, produttore, seriale,
  quantita, stato (a magazzino / in uso / guasto / dismesso), posizione, note.
- **Attributi flessibili** per tipo (RAM -> capacita, tipo, velocita; SSD -> capacita,
  interfaccia; ecc.) con suggerimenti automatici per categoria.
- **Macchine / postazioni**: crea le macchine e assegna i componenti. La scheda macchina
  mostra tutto l'hardware montato.
- **Movimenti**: ogni spostamento o cambio di stato viene registrato nello storico.
- **Ricerca e filtri** per testo, categoria, stato, macchina.
- **Login** con password unica.
- **Dashboard** con statistiche e grafico per categoria.

---

## Installazione

### Passo 0 — Pubblica su GitHub (una volta sola)

1. Crea un repo su GitHub e carica il progetto:
   ```bash
   git init
   git add .
   git commit -m "Magazzino hardware"
   git branch -M main
   git remote add origin https://github.com/OWNER/REPO.git
   git push -u origin main
   ```
2. Il workflow `.github/workflows/docker-publish.yml` builda in automatico e pubblica
   l'immagine su **GHCR**: `ghcr.io/OWNER/REPO:latest`.
3. Rendi il package **pubblico** (una volta): GitHub → tab **Packages** → il package
   `REPO` → **Package settings** → **Change visibility** → **Public**.
   (Se resta privato serve `docker login ghcr.io` sul dispositivo prima del pull.)

Sostituisci ovunque `OWNER/REPO` con i tuoi (minuscolo), es. `marcovalerio/magazzino`.

### Opzione A — Solo il file compose (consigliata) ✅

Install "solo inserendo il file": nessun sorgente da copiare, nessuna build sul dispositivo.

1. Sul ZimaOS crea un file `docker-compose.yml` con questo contenuto (immagine gia su GHCR):
   ```yaml
   services:
     magazzino:
       image: ghcr.io/OWNER/REPO:latest
       container_name: magazzino
       pull_policy: always
       ports:
         - "8086:8000"
       environment:
         - APP_PASSWORD=cambiami        # CAMBIALA
         - APP_NAME=MAGAZZINO
         - TZ=Europe/Rome
         - DATA_DIR=/data
       volumes:
         - magazzino_data:/data
       restart: unless-stopped
   volumes:
     magazzino_data:
   ```
2. Avvia:
   ```bash
   docker compose up -d
   ```
3. Apri: `http://IP-ZIMA:8086`

Su **ZimaOS App Store → Import** puoi incollare direttamente questo YAML: scarica
l'immagine e parte, senza build.

### Opzione B — Un file, build da GitHub (senza registry/Actions)

Se non vuoi pubblicare l'immagine, il compose puo buildare direttamente dal repo Git.
Serve solo questo file, ma la build gira sul dispositivo (piu lenta):
```yaml
services:
  magazzino:
    build: https://github.com/OWNER/REPO.git#main
    container_name: magazzino
    ports:
      - "8086:8000"
    environment:
      - APP_PASSWORD=cambiami
    volumes:
      - magazzino_data:/data
    restart: unless-stopped
volumes:
  magazzino_data:
```
```bash
docker compose up -d --build
```

### Opzione C — Sviluppo (repo clonato, build locale)

```bash
cp .env.example .env      # cambia APP_PASSWORD
docker compose -f docker-compose.dev.yml up -d --build
```

---

## Configurazione (variabili ambiente)

| Variabile     | Default        | Descrizione                                        |
|---------------|----------------|----------------------------------------------------|
| `APP_PASSWORD`| `cambiami`     | Password di accesso. **Cambiala.**                 |
| `APP_NAME`    | `MAGAZZINO`    | Nome mostrato nell'interfaccia.                    |
| `SECRET_KEY`  | *(auto)*       | Firma cookie. Vuoto = generata e salvata in `data`.|
| `TZ`          | `Europe/Rome`  | Fuso orario.                                       |
| `DATA_DIR`    | `/data`        | Cartella dati nel container.                       |

---

## Sviluppo locale (senza Docker)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
App su `http://127.0.0.1:8000` (password default `admin` se non imposti `APP_PASSWORD`).

---

## Backup / ripristino

Tutto vive in `/data/magazzino.db` (SQLite) + `/data/.secret_key`.

**Con volume nominato** (Opzione A/B):
```bash
# Backup -> file magazzino-backup.tar.gz
docker run --rm -v magazzino_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/magazzino-backup.tar.gz -C /data .

# Ripristino
docker run --rm -v magazzino_data:/data -v "$PWD":/backup alpine \
  tar xzf /backup/magazzino-backup.tar.gz -C /data
```

**Con bind mount** (Opzione C, cartella `./data`): copia direttamente la cartella `data/`.

---

## Struttura

```
magazzino/
├── app/                 # backend FastAPI
│   ├── main.py          # app, middleware login, routing, startup
│   ├── config.py        # variabili ambiente + chiave segreta
│   ├── database.py      # SQLite + SQLAlchemy
│   ├── models.py        # Machine, Component, Movement, Category
│   ├── deps.py          # templates, flash, render
│   └── routers/         # auth, dashboard, components, machines
├── templates/           # HTML (Jinja2)
├── static/              # CSS costruttivista + JS + favicon
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
