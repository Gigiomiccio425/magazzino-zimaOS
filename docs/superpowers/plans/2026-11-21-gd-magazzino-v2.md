# GD Magazzino 2.0 — Piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare GD Magazzino dalla v1.1.1 alla v2.0.0 definitiva (gestionale + centro di comando, firma operatori, webhook Discord) senza perdere né alterare i dati esistenti.

**Architecture:** Evoluzione dell'app attuale: FastAPI + Jinja2 server-rendered + JS vanilla + SQLite, un solo processo uvicorn. Schema gestito da migrazioni numerate su `PRAGMA user_version` con backup automatico prima. Ogni scrittura passa da CSRF + firma operatore + audit log a catena di hash. Unica automazione: consegna webhook (outbox) e backup.

**Tech Stack:** Python 3.12, FastAPI 0.162.0, Starlette 1.10.0, uvicorn 0.54.0, SQLAlchemy 2.0.57, Jinja2 3.1.6, python-multipart 0.0.33, itsdangerous 2.2.0, httpx 0.28.1, webauthn 3.0.1, segno 1.6.6, Pillow 13.0.0, markdown-it-py 4.2.0, pytest 9.2.0; JS: barcode-detector 3.2.3 (IIFE ponyfill) + zxing-wasm 3.1.6 (reader wasm), vendorizzati.

**Spec:** `docs/superpowers/specs/2026-11-21-gd-magazzino-v2-design.md`

## Global Constraints

- Python 3.12. Versioni esatte come in Tech Stack (dipendenze transitive risolte da `uv pip compile --exclude-newer 2026-11-07`).
- Starlette 1.x: niente `on_event`, `@app.route`, `@app.exception_handler`, `@app.middleware`; usare `lifespan`, `add_middleware`, `exception_handlers=`. `TemplateResponse(request, name, context)`.
- Migrazioni: mai `DROP`, mai `RENAME` di colonne esistenti; tutte le migrazioni pendenti in **una sola transazione**; backup pre-migrazione in `/data/backups/pre-migrazione/`, ultimi 10.
- Dati in `DATA_DIR` (`/data`): `magazzino.db`, `.secret_key`, `backups/`, `uploads/`, `tmp/`.
- Nessuna CDN, nessuna chiamata di rete in uscita tranne la consegna dei webhook.
- Nessuna automazione crea o modifica dati: solo backup (pre-migrazione, giornaliero 03:00, 14 conservati) e consegna webhook. Cestino allegati svuotato solo a mano.
- Ogni rotta di scrittura: CSRF + `require_signer(...)` + `audit.record(...)`. Soft delete (`deleted_at`) per componenti, macchine, posizioni, servizi.
- Testi UI in italiano; stile costruttivista (token in `static/css/style.css`); nessun `alert()`/`confirm()` nativo.
- CSP: `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'`. Niente script inline nei template.
- Discord: `allowed_mentions` = `{"parse": []}` sempre; ruolo solo per SEV1 se configurato.
- Date salvate UTC naive; mostrate in ora locale (`TZ`, default `Europe/Rome`).
- Firma: sessione default 10 min (`signature_window_min`, 0–60), token azione critica monouso 120 s, blocco dopo 5 password errate per 15 min, password ≥ 6 caratteri.
- Asset tag: componenti `C-%06d`, macchine `M-%03d`, posizioni `L-%04d`, derivati dall'id.
- Comandi locali (Windows): `.venv/Scripts/python -m pytest ...`. In CI: `python -m pytest`.

## Review Focus

- Accesso da `http://umbrel.local` o da un dominio dove l'operatore non ha passkey: deve vedere "Nessuna impronta registrata per questo indirizzo: usa la password" — test `test_auth_begin_without_credential_for_rp` (Task 8).
- Attributi storici in testo libero ("1TB", "16") nei filtri numerici: i valori non numerici non devono comparire nei risultati — test `test_numeric_filter_skips_non_numeric_legacy` (Task 15).
- Firma scaduta tra il controllo e l'invio del form: risposta 428 JSON, il form si reinvia dopo la firma senza perdere dati — test `test_fetch_write_without_signer_gets_428` (Task 7).
- Ripristino di un backup di versione vecchia (file `.db` v1.1.1): deve essere migrato, non rifiutato — test `test_restore_v111_db_runs_migrations` (Task 12).
- Nomi operatore uguali a meno di maiuscole/spazi ("Dany", " dany "): stesso operatore — test `test_operator_names_case_and_space_insensitive` (Task 7).

---

## Struttura file (decisa qui)

```
app/
  main.py              create_app(data_dir=None, *, start_worker=True) -> FastAPI ; lifespan
  config.py            Settings + load_settings()
  version.py           APP_VERSION = "2.0.0"
  timeutil.py          utcnow(), to_local(), parse_local_input(), format_local_input()
  database.py          Base, make_engine(), get_db()
  deps.py              templates, render(), flash(), redirect(), is_fetch()
  core/csrf.py         get_csrf_token(), verify_csrf()
  core/headers.py      SecurityHeadersMiddleware
  migrations/runner.py Migration, MIGRATIONS, LATEST_VERSION, run_migrations(), snapshot_db(), MigrationError
  migrations/m0001_baseline.py, m0002_schema_v2.py, m0003_backfill_seed.py
  models/__init__.py   riesporta tutto
  models/constants.py  dizionari di stati/etichette
  models/inventory.py, verification.py, ops.py, notify.py, security.py, system.py
  services/            audit, signing, webauthn_svc, settings_store, backup, events, discord,
                       outbox, inventory, component_form, component_query, locations, qr,
                       uploads, links, markdown, testing, csv_io, search, dashboard
  worker.py            Worker
  routers/             (un file per area, vedi task)
templates/             base.html, partials/, pagine per area
static/css/style.css, static/js/{app,sign,scanner,palette,bulk,attrs}.js,
static/vendor/barcode-detector/ponyfill.min.js, static/vendor/zxing/zxing_reader.wasm,
static/pwa/{manifest.webmanifest,sw.js,icon-192.png,icon-512.png,icon-maskable-512.png}
tests/conftest.py, tests/helpers.py, tests/fixtures/v111.py, tests/test_*.py
```

Costanti (`app/models/constants.py`), codice → etichetta:
- `STATUSES`: stock A magazzino · to_test Da testare · tested_ok Testato OK · in_use In uso · reserved Riservato · repair In riparazione · rma In RMA · faulty Guasto · retired Dismesso · sold Venduto
- `TRACKING`: serial A seriale · quantity A quantità
- `LOCATION_KINDS`: stanza, scaffale, ripiano, box, cassetto, altro
- `FIELD_TYPES`: text, number, choice, bool, date
- `SEVERITIES`: SEV1 Critico · SEV2 Alto · SEV3 Medio · SEV4 Basso
- `INCIDENT_STATUSES`: open Aperto · investigating In analisi · identified Identificato · monitoring Monitoraggio · resolved Risolto
- `SERVICE_STATUSES`: operational Operativo · degraded Degradato · partial_outage Disservizio parziale · major_outage Disservizio grave · maintenance Manutenzione
- `CHANGE_TYPES`: release Rilascio · update Aggiornamento · fix Fix · debug Debug · feature Funzione · config Configurazione · rollback Rollback · note Nota
- `MODULE_KINDS`: web App web · app_pc App PC · app_android App Android · app_ios App iOS · bot Bot · api API · worker Worker · db Database · altro Altro
- `MAINTENANCE_STATUSES`: scheduled Programmata · in_progress In corso · completed Completata · cancelled Annullata
- `PROBLEM_STATUSES`: open Aperto · workaround Workaround · resolved Risolto
- `TEST_RESULTS`: pass OK · fail Fallito · partial Parziale · inconclusive Non concluso
- `PROJECT_STATUSES`: draft Bozza · building In costruzione · done Completata · cancelled Annullata
- `EVENTS`: incident.opened, incident.updated, incident.resolved, maintenance.scheduled, maintenance.started, maintenance.completed, maintenance.cancelled, change.published, service.status_changed, stock.low, test.failed, audit.completed, webhook.test

Contratto dati evento (usato da Task 13 e da chi emette): `{"title": str, "description": str|None, "url_path": str|None, "fields": [[nome, valore], ...], "severity": "SEV1".."SEV4"|None, "status_label": str|None, "operator": str|None, "resolved": bool}`.

---

### Task 1: Base tecnica, dipendenze nuove, password rimossa

**Files:**
- Modify: `requirements.txt`, `Dockerfile`, `app/config.py`, `app/database.py`, `app/main.py`, `app/deps.py`, `app/routers/*.py` (firma `TemplateResponse`, `db.get`), `.gitignore`
- Create: `requirements-dev.txt`, `pytest.ini`, `.gitattributes`, `app/version.py`, `app/timeutil.py`, `tests/conftest.py`, `tests/helpers.py`, `tests/test_app_basics.py`
- Delete: `templates/login.html`; `app/routers/auth.py` ridotto a redirect

**Interfaces:**
- Produces: `Settings(data_dir: Path, app_name: str, secret_key: str, public_base_url: str, webauthn_rp_id: str | None)` con proprietà `db_path`, `backups_dir`, `uploads_dir`, `tmp_dir`; `load_settings(data_dir=None) -> Settings`; `make_engine(db_path) -> Engine` (WAL, `foreign_keys=ON`, `busy_timeout=5000`); `get_db(request) -> Iterator[Session]` legato a `request.app.state.engine`; `create_app(data_dir=None, *, start_worker=True) -> FastAPI` con `app.state.settings`, `app.state.engine`; `render(request, name, ctx=None, status_code=200)`; `flash(request, msg, category="success")`; `is_fetch(request) -> bool` (header `X-Requested-With: fetch`); `redirect(request, url) -> Response` (JSON `{"redirect": url}` se fetch, altrimenti 303); `utcnow() -> datetime` naive UTC.
- Fixture test: `data_dir`, `app`, `client` (TestClient in context manager), `db`.

- [ ] **Step 1:** `uv venv --python 3.12 .venv` e installa `requirements.txt` (pin Tech Stack) + `requirements-dev.txt` (`pytest==9.2.0`). `.gitattributes`: `* text=auto`, `*.png *.wasm *.db *.zip binary`.
- [ ] **Step 2: test che falliscono** in `tests/test_app_basics.py`:

```python
def test_health_ok(client):
    assert client.get("/health").json() == {"status": "ok"}

def test_no_login_required(client):
    assert client.get("/", follow_redirects=False).status_code == 200

def test_login_redirects_home(client):
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"

@pytest.mark.parametrize("path", ["/", "/components", "/components/new", "/machines", "/machines/new", "/movements"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200

def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_NAME", "TEST"); monkeypatch.setenv("PUBLIC_BASE_URL", "https://x.y/")
    s = load_settings(tmp_path)
    assert s.app_name == "TEST" and s.public_base_url == "https://x.y" and s.db_path == tmp_path / "magazzino.db"
```
- [ ] **Step 3:** `.venv/Scripts/python -m pytest tests/test_app_basics.py -q` → FAIL.
- [ ] **Step 4:** Implementa. Lifespan in questo task: `Base.metadata.create_all` + seed categorie (provvisorio, sostituito in Task 2). Rimuovi `require_login`, `APP_PASSWORD`; `/login` e `/logout` → 303 a `/`. Dockerfile: `CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]`; rimuovi `ProxyHeadersMiddleware` dal codice.
- [ ] **Step 5:** test → PASS.
- [ ] **Step 6:** commit `feat: base tecnica v2, dipendenze aggiornate, login applicativo rimosso`.

### Task 2: Runner migrazioni + baseline + fixture v1.1.1

**Files:**
- Create: `app/migrations/__init__.py`, `app/migrations/runner.py`, `app/migrations/m0001_baseline.py`, `tests/fixtures/v111.py`, `tests/test_migrations_runner.py`
- Modify: `app/main.py` (lifespan chiama `run_migrations`, niente più `create_all`)

**Interfaces:**
- Produces: `Migration(version: int, name: str, apply: Callable[[sqlite3.Connection], None])`; `MIGRATIONS: list[Migration]`; `LATEST_VERSION: int`; `MigrationReport(from_version: int, to_version: int, backup_path: Path | None)`; `run_migrations(db_path: Path, backups_dir: Path) -> MigrationReport`; `snapshot_db(src: Path, dest: Path) -> Path` (API backup sqlite3); `rotate(directory: Path, keep: int, pattern: str = "*.db") -> list[Path]` (ritorna i rimossi); `MigrationError(Exception)`; helper `add_column(conn, table, ddl)` idempotente via `PRAGMA table_info`.
- `tests/fixtures/v111.py`: `build_v111_db(path: Path) -> None` — copia verbatim dei modelli v1.1.1 (proprio `declarative_base`) + `create_all` + dati: macchine "Server Umbrel" (server, "Rack") e "PC Gaming"; componenti: RAM "Corsair 16GB" (in_use su macchina 1, serial "RAM-001", attributi `{"Capacita (GB)": "16", "Tipo": "DDR4", "Velocita (MHz)": "3200"}`), GPU "RTX 3060" (stock, "Scaffale A", serial "GPU-XYZ", `{"VRAM (GB)": "12", "Chipset": "GA106"}`), Cavo "HDMI 2m" (quantity 30, "Box cavi", `{"Lunghezza": "2 m"}`), SSD "Samsung 970" (faulty, "Scaffale A", `{"Capacita (GB)": "1TB"}`); un movimento per componente + uno `moved`; 13 categorie predefinite.

Regole runner: file assente → crea e applica senza backup. File presente con `user_version < LATEST_VERSION` → `PRAGMA integrity_check` == "ok" (altrimenti `MigrationError`) → backup `pre-migrazione/v{da}-a-v{a}-{sha8}-{AAAAMMGG-HHMMSS}.db` saltato se esiste già un file `v{da}-a-v{a}-{sha8}-*` → `BEGIN IMMEDIATE` → tutte le migrazioni pendenti → `PRAGMA user_version = LATEST` → `COMMIT`; qualsiasi errore → `ROLLBACK` + `MigrationError` → `rotate(..., keep=10)`. Baseline: `CREATE TABLE IF NOT EXISTS` identici allo schema v1.1.1.

- [ ] **Step 1: test che falliscono:**

```python
def test_fresh_install(tmp_path):
    r = run_migrations(tmp_path / "m.db", tmp_path / "b")
    assert (r.from_version, r.to_version, r.backup_path) == (0, LATEST_VERSION, None)

def test_v111_backed_up_then_migrated(tmp_path):
    db = tmp_path / "m.db"; build_v111_db(db)
    r = run_migrations(db, tmp_path / "b")
    assert r.from_version == 0 and r.backup_path.name.startswith(f"v0-a-v{LATEST_VERSION}-")
    assert sqlite3.connect(r.backup_path).execute("select count(*) from components").fetchone()[0] == 4

def test_second_run_noop(tmp_path): ...  # seconda run: backup_path None, 1 solo file in pre-migrazione

def test_failed_migration_rolls_back_and_no_duplicate_backup(tmp_path, monkeypatch):
    # aggiunge Migration(LATEST+1, "boom", apply che crea tabella poi raise)
    # due run -> MigrationError entrambe; user_version invariato; tabella "boom" assente; 1 solo backup

def test_corrupt_file_refused(tmp_path):  # file con byte casuali -> MigrationError, nessun backup

def test_rotate_keeps_newest(tmp_path):  # 12 file con mtime crescente -> restano i 10 più recenti

def test_app_fails_to_start_on_migration_error(tmp_path):  # db corrotto -> TestClient(create_app(tmp_path)) solleva
```
- [ ] **Step 2:** run → FAIL. **Step 3:** implementa. **Step 4:** run → PASS (anche Task 1).
- [ ] **Step 5:** commit `feat: migrazioni versionate con backup pre-migrazione`.

### Task 3: Schema v2 (m0002) + modelli ORM a pacchetto

**Files:**
- Create: `app/migrations/m0002_schema_v2.py`, `app/models/{__init__,constants,inventory,verification,ops,notify,security,system}.py`, `tests/test_schema.py`
- Delete: `app/models.py` (sostituito dal pacchetto; `from ..models import X` continua a funzionare)

**Interfaces:**
- Produces classi ORM (nomi tabella tra parentesi): `Component(components)`, `Machine(machines)`, `Movement(movements)`, `Category(categories)`, `CategoryField(category_fields)`, `Location(locations)`, `Tag(tags)` + tabella `component_tags`, `Attachment(attachments)`, `InventoryAudit(audits)`, `InventoryAuditItem(audit_items)`, `Project(projects)`, `ProjectItem(project_items)`, `TestTemplate(test_templates)`, `TestRun(test_runs)`, `Service(services)`, `ServiceModule(service_modules)`, `Change(changes)`, `Link(links)`, `Incident(incidents)` + `incident_services`, `IncidentUpdate(incident_updates)`, `Problem(problems)` + `problem_services`, `problem_incidents`, `Maintenance(maintenances)` + `maintenance_services`, `Webhook(webhooks)`, `OutboxItem(outbox)`, `Operator(operators)`, `OperatorCredential(operator_credentials)`, `Signature(signatures)`, `AuditLog(audit_log)`, `Setting(settings)`.
- Colonne: esattamente quelle della spec §6.1–6.2, più: `operators.name_key` (unico, casefold), `locations.last_audit_at`, `project_items.prev_status`, `components.reserved` non serve (prenotazioni in `project_items`). Unicità di `asset_tag` via `CREATE UNIQUE INDEX ... WHERE asset_tag IS NOT NULL`. Prezzi in centesimi (int).

- [ ] **Step 1: test che falliscono:**

```python
def test_schema_matches_models_fresh(tmp_path): ...   # ogni colonna di Base.metadata esiste in PRAGMA table_info
def test_schema_matches_models_from_v111(tmp_path): ...
def test_v111_columns_preserved(tmp_path): ...        # nomi colonne v1.1.1 ⊆ colonne dopo migrazione, per ogni tabella
def test_v111_values_identical(tmp_path): ...         # select delle colonne originali prima/dopo: righe identiche
```
- [ ] **Step 2–4:** FAIL → implementa → PASS.
- [ ] **Step 5:** commit `feat: schema v2 e modelli`.

### Task 4: Backfill e seed (m0003)

**Files:**
- Create: `app/migrations/m0003_backfill_seed.py`, `tests/test_backfill.py`
- Modify: `app/main.py` (rimuovi seed categorie dal lifespan)

Contenuto: asset tag per componenti/macchine esistenti; `tracking` = `quantity` se `quantity > 1` altrimenti `serial`; `unit` = `pz`; una `location` di primo livello (kind `altro`, tag `L-%04d`) per ogni testo distinto non vuoto in `components.location` (trim), con `location_id` impostato, testo intatto; categorie predefinite inserite se mancanti; `category_fields` predefiniti con `key` = etichette storiche di `static/js/app.js` (RAM, SSD, HDD, CPU, GPU, Scheda madre, Alimentatore, Scheda di rete, Ventola) + Cavo (`Tipo` choice HDMI/DisplayPort/USB-C/USB-A/Ethernet/SATA/Alimentazione/PCIe power/Audio/Altro, `Connettore A`, `Connettore B`, `Lunghezza (m)` number m, `Standard/versione`, `Colore`) + GPU estesa (`Tipo memoria`, `Connettori alimentazione`, `Uscite video`, `Lunghezza (mm)`); `test_templates` predefiniti della spec §10 (GPU, RAM, SSD, HDD, CPU, Alimentatore, Cavo, Scheda di rete, Ventola); `settings` default `signature_window_min=10`, `audit_interval_days=180`, `public_base_url=""`.

- [ ] **Step 1: test che falliscono:**

```python
def test_asset_tags(migrated_v111): assert tags == ["C-000001", "C-000002", "C-000003", "C-000004"] and mtags == ["M-001", "M-002"]
def test_tracking(migrated_v111): assert tracking_by_name["HDMI 2m"] == "quantity" and tracking_by_name["RTX 3060"] == "serial"
def test_locations_from_text(migrated_v111):
    # "Scaffale A" una sola location usata da GPU e SSD; "Box cavi"; RAM senza location; components.location invariata
def test_category_fields_seeded(migrated_v111):  # RAM ha key "Capacita (GB)" type number; Cavo ha "Lunghezza (m)" unit "m"
def test_test_templates_seeded(migrated_v111):    # >= 9; GPU contiene campo con key "temp_max" e max numerico
def test_attributes_untouched(migrated_v111):     # JSON attributes identico al fixture
def test_fresh_install_has_categories_and_templates(tmp_path): ...
```
(`migrated_v111` fixture in `conftest.py`: build + run_migrations, ritorna path.)
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: backfill asset tag, posizioni, template`.

### Task 5: CSRF, header sicurezza, base accessibile, primitive JS, date locali

**Files:**
- Create: `app/core/csrf.py`, `app/core/headers.py`, `templates/partials/macros.html`, `tests/test_security_base.py`
- Modify: `app/main.py`, `app/deps.py` (filtro `dt` → ora locale, globali `csrf_field`, `APP_VERSION`), `templates/base.html` (skip link, `<main id="main">`, `aria-live="polite"` sui flash, nav raggruppata con `aria-current`, burger `aria-expanded`/`aria-controls`, `<meta name="csrf-token">`, versione nel footer), tutti i form esistenti (`{{ csrf_field() }}`), `static/js/app.js`, `static/js/scanner.js`

**Interfaces:**
- Produces: `get_csrf_token(request) -> str` (in `session["csrf"]`, `secrets.token_urlsafe(32)`); `verify_csrf(request)` dipendenza async applicata a tutti i router (metodi non GET/HEAD/OPTIONS; campo form `csrf_token` o header `X-CSRF-Token`; errore → 403, JSON `{"error": "csrf"}` se fetch); `SecurityHeadersMiddleware` ASGI puro con gli header dei Global Constraints + `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Permissions-Policy: camera=(self)`.
- JS `window.MAG`: `MAG.csrf() -> string`; `MAG.fetchJSON(url, {method, body}) -> Promise<{status, data}>` (aggiunge `X-CSRF-Token` e `X-Requested-With: fetch`); `MAG.toast(msg, kind)`; `MAG.confirm(msg, {danger}) -> Promise<boolean>` su `<dialog>`; `MAG.submitForm(form) -> Promise` (fetch `FormData`, segue `{"redirect"}`).
- Macro Jinja in `partials/macros.html`: `field(label, name, value, type="text", help=None, error=None, attrs={})`, `select(label, name, options, value)`, `status_tag(code)`, `empty(msg)`.

- [ ] **Step 1: test che falliscono:**

```python
def test_post_without_csrf_403(client): assert client.post("/machines/new", data={"name": "X"}).status_code == 403
def test_post_with_csrf_field_passes_csrf(client): ...      # status != 403
def test_csrf_header_accepted(client): ...
def test_security_headers(client):
    h = client.get("/").headers
    assert "default-src 'self'" in h["content-security-policy"] and "'wasm-unsafe-eval'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "same-origin"
def test_dt_filter_local(monkeypatch):  # TZ Europe/Rome: datetime(2026,7,1,10,0) -> "01/07/2026 12:00"
def test_base_accessibility_markers(client):
    html = client.get("/").text
    assert 'href="#main"' in html and 'id="main"' in html and 'aria-live="polite"' in html
def test_no_native_dialogs_in_js():  # nessun "alert(" / "confirm(" / "prompt(" in static/js/*.js
```
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: CSRF, header di sicurezza, base accessibile`.

### Task 6: Audit log con catena di hash

**Files:** Create `app/services/audit.py`, `app/routers/audit_log.py`, `templates/audit_log.html`, `tests/test_audit.py`

**Interfaces:**
- Produces: `GENESIS = "0" * 64`; `snapshot(obj, fields: Sequence[str]) -> dict`; `changed(before: dict, after: dict) -> tuple[dict, dict]` (solo chiavi cambiate); `record(db, *, entity_type: str, entity_id: int | None, action: str, before: dict | None = None, after: dict | None = None, signer: SignerInfo | None = None, actor_type: str = "operator") -> AuditLog` (flush, non commit); `verify_chain(db) -> ChainReport(ok: bool, checked: int, first_bad_id: int | None)`.
- Hash: `sha256(prev_hash + json.dumps(riga, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))` con riga = ts (isoformat microsecondi), actor_type, operator_id, signature_id, entity_type, entity_id, action, before, after, prev_hash.
- Pagine: `GET /audit` (filtri entità/operatore, 100 per pagina), `GET /audit/verify`.

- [ ] **Step 1: test:** `test_record_links_hashes` (2 righe: seconda.prev_hash == prima.hash), `test_changed_only_diff`, `test_verify_chain_ok_and_detects_tamper` (UPDATE raw di `after` su riga 2 → `first_bad_id == 2`), `test_audit_page_lists`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: audit log a catena di hash`.

### Task 7: Operatori, firma con password, sessione, azioni critiche

**Files:**
- Create: `app/services/signing.py`, `app/routers/sign.py`, `templates/partials/sign_dialog.html`, `static/js/sign.js`, `tests/test_signing.py`
- Modify: `app/main.py` (handler `SignatureRequired`), `templates/base.html` (dialog + barra "Firmato: NOME · N min · Esci")

**Interfaces:**
- Produces: `SignerInfo(operator_id: int, operator_name: str, is_admin: bool, signature_id: int, expires_at: float)`; `SignatureRequired(critical: bool)`; `hash_password(pw) -> str` (formato `scrypt$16384$8$1$<salt b64>$<hash b64>`, dklen 32); `verify_password(pw, stored) -> bool`; `normalize_name(name) -> tuple[str, str]` (display con spazi compressi, key casefold); `action_hash(method, path) -> str`; `current_signer(request, db) -> SignerInfo | None` (operatore ancora attivo); `start_signing_session(request, db, operator, signature) -> SignerInfo`; `issue_action_token(request, signature_id, action) -> str`; `consume_action_token(request, token, action) -> int | None`; `require_signer(critical: bool = False)` → dipendenza FastAPI che ritorna `SignerInfo` (accetta sessione valida, oppure campo/header `sig_token` valido per `action_hash(request.method, request.url.path)`; critica accetta solo il token); `create_signature(db, request, operator, method, purpose=None, rp_id=None) -> Signature`.
- Handler `SignatureRequired`: fetch → 428 JSON `{"error": "signature_required", "critical": bool}`; altrimenti flash "Firma richiesta: abilita JavaScript" + redirect al Referer o `/`.
- Rotte: `GET /sign/state` → `{"signed": bool, "operator": str|None, "expires_in": int}`; `GET /sign/operators` → `[{"id","name","has_password","passkey_here"}]`; `POST /sign/password` JSON `{"operator_id"?: int, "new_name"?: str, "password": str, "action"?: "POST /path"}` → `{"ok": true, "operator": str, "action_token"?: str}`; `POST /sign/logout`. Errori: 409 nome esistente, 422 password corta/mancante, 401 password errata, 423 bloccato.
- Primo operatore creato `is_admin=True`. `signature_window_min` letto da `settings_store` (Task 11; fino ad allora default 10 da `Setting` se presente, altrimenti 10).
- `sign.js`: intercetta `submit` di `form[method=post]:not([data-nosign])`; `data-sign="critical"` per le azioni critiche; flusso: stato → dialog (scelta operatore / nuovo nome / password) → `MAG.submitForm` con `sig_token` se critica; su 428 riapre il dialog e reinvia lo stesso `FormData`.

- [ ] **Step 1: test** (rotta di prova registrata nel test: `POST /_t/write` con `require_signer()` e `POST /_t/critical` con `require_signer(True)`):

```python
def test_password_hash_roundtrip(): h = hash_password("segreto1"); assert h.startswith("scrypt$") and verify_password("segreto1", h) and not verify_password("x", h)
def test_first_operator_is_admin(client): ...           # Gigio admin, Dany no
def test_operator_names_case_and_space_insensitive(client):  # " dany " poi "Dany" -> 409
def test_password_too_short(client): ...                 # "12345" -> 422
def test_new_operator_requires_method(client): ...       # senza password -> 422
def test_lock_after_5_failures(client): ...              # 5 errate, poi giusta -> 423
def test_fetch_write_without_signer_gets_428(client):
    r = client.post("/_t/write", headers={"X-Requested-With": "fetch", "X-CSRF-Token": csrf})
    assert r.status_code == 428 and r.json() == {"error": "signature_required", "critical": False}
def test_plain_form_without_signer_redirects(client): ...
def test_session_window(client, monkeypatch): ...        # ok subito, 428 dopo 11 minuti (time.time patchato)
def test_window_zero_needs_token_each_time(client): ...
def test_critical_token_single_use_and_bound(client): ...# token per "POST /_t/critical": ok 1 volta; riuso 428; token per altra azione 428; dopo 121 s 428
def test_disabled_operator_session_rejected(client): ...
```
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** verifica nel browser (uvicorn locale + Playwright): crea operatore, salva una macchina, dialog accessibile da tastiera, `Esc` chiude.
- [ ] **Step 6:** commit `feat: operatori e firma con password`.

### Task 8: Passkey / impronta (WebAuthn)

**Files:** Create `app/services/webauthn_svc.py`, `tests/test_webauthn.py`; Modify `app/routers/sign.py`, `static/js/sign.js`

**Interfaces:**
- Produces: `origin_and_rp_id(request, settings) -> tuple[str, str]` (origin = header `Origin` o `scheme://host`; rp_id = `settings.webauthn_rp_id` o hostname dell'origin); `registration_options(rp_id, rp_name, user_id: bytes, user_name: str, exclude: list[bytes]) -> tuple[str, bytes]`; `verify_registration(credential_json: str, challenge: bytes, origin: str, rp_id: str) -> RegisteredCredential(credential_id: bytes, public_key: bytes, sign_count: int, transports: list[str])`; `authentication_options(rp_id, allow: list[bytes]) -> tuple[str, bytes]`; `verify_authentication(credential_json, challenge, origin, rp_id, public_key, sign_count) -> int`. Tutte su `webauthn` 3.0.1 (`generate_registration_options`, `verify_registration_response`, `generate_authentication_options`, `verify_authentication_response`, `options_to_json`), `user_verification` REQUIRED, attestazione none.
- Rotte: `POST /sign/passkey/register/begin` `{"new_name"?: str}` (oppure operatore = firmatario corrente per aggiungere una passkey); `.../register/finish` `{"credential": {...}, "password"?: str, "label"?: str, "action"?: str}`; `POST /sign/passkey/auth/begin` `{"operator_id": int, "action"?: str}`; `.../auth/finish` `{"credential": {...}}`. Challenge in `session["webauthn"]` = `{challenge, origin, rp_id, kind, name|operator_id, action, exp}`, monouso, 120 s.
- Nessuna credenziale per quell'rp_id → 409 `{"error": "no_passkey_here", "message": "Nessuna impronta registrata per questo indirizzo: usa la password"}`.
- `sign.js`: mostra "Impronta / passkey" solo se `window.isSecureContext && window.PublicKeyCredential`; conversioni base64url ↔ ArrayBuffer.

- [ ] **Step 1: test** (verifica libreria sostituita con monkeypatch su `webauthn_svc.verify_registration`/`verify_authentication`): `test_register_begin_uses_origin_host` (Origin `https://mag.example` → `rp.id == "mag.example"`), `test_env_rp_id_overrides`, `test_register_finish_creates_operator_and_credential`, `test_auth_begin_without_credential_for_rp`, `test_auth_finish_updates_sign_count_and_session`, `test_challenge_single_use`.
- [ ] **Step 2–4:** FAIL → implementa → PASS.
- [ ] **Step 5:** verifica nel browser con autenticatore virtuale Chromium (CDP `WebAuthn.addVirtualAuthenticator`, `isUserVerified: true`) su `http://localhost`.
- [ ] **Step 6:** commit `feat: firma con passkey/impronta`.

### Task 9: Gestione operatori e profilo

**Files:** Create `app/routers/operators.py`, `templates/operators_list.html`, `templates/operator_profile.html`, `tests/test_operators.py`

Rotte: `GET /operators`; `POST /operators/{id}/disable|enable|reset-password|remove-passkeys|toggle-admin` (admin, critiche); `GET /profile`; `POST /profile/password` (critica); aggiunta passkey dal profilo via Task 8. Vietato disattivare o declassare l'ultimo admin attivo (409).

- [ ] **Step 1: test:** `test_admin_disables_operator`, `test_non_admin_forbidden` (403), `test_reset_password`, `test_remove_passkeys`, `test_last_admin_protected`, `test_change_own_password_requires_critical`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: gestione operatori`.

### Task 10: Firma + audit + soft delete su componenti e macchine, cestino

**Files:** Modify `app/routers/components.py`, `app/routers/machines.py`, `app/routers/dashboard.py`, template relativi; Create `app/services/inventory.py`, `app/routers/trash.py`, `templates/trash.html`, `tests/test_inventory_signed.py`

**Interfaces:**
- Produces in `services/inventory.py`: `make_tag(prefix: str, id: int) -> str` (`C` 6 cifre, `M` 3, `L` 4); `normalize_assignment(machine_id, status) -> tuple[int | None, str]` (regole v1.1.1: macchina + stock → in_use; nessuna macchina + in_use → stock); `soft_delete(db, obj, signer)`; `restore(db, obj, signer)`; `purge(db, obj, signer)`; `alive(query, Model)` filtro `deleted_at IS NULL`.
- Tutte le scritture: `require_signer()`; elimina → soft delete; `/trash` elenca e ripristina (firma normale), elimina definitivamente (critica). Macchina eliminata → componenti a magazzino con movimenti (`operator_id`, `signature_id`). Duplica: nuovo `asset_tag`, seriale e codice oggetto vuoti.

- [ ] **Step 1: test:** `test_create_component_signed_and_audited` (created_by, audit con signature_id, movimento con operator_id), `test_edit_audits_only_changes`, `test_delete_is_soft_and_hidden` (non in lista/dashboard, sì in `/trash`), `test_restore`, `test_purge_requires_critical`, `test_machine_delete_returns_components_with_movements`, `test_duplicate_resets_unique_fields`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: firma, audit e cestino su componenti e macchine`.

### Task 11: Impostazioni

**Files:** Create `app/services/settings_store.py`, `app/routers/settings.py`, `templates/settings.html`, `tests/test_settings.py`

**Interfaces:** `DEFAULTS = {"signature_window_min": 10, "audit_interval_days": 180, "public_base_url": ""}`; `get_setting(db, key)`; `set_setting(db, key, value)`; `base_url(request, db) -> str` (impostazione → env `PUBLIC_BASE_URL` → `request.base_url`, senza `/` finale). `POST /settings` critica; `public_base_url` vuoto o URL `http(s)://` valido; finestra 0–60; intervallo inventario 1–3650.

- [ ] **Step 1: test:** `test_defaults`, `test_update_requires_critical`, `test_invalid_values_rejected`, `test_base_url_precedence`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: impostazioni`.

### Task 12: Backup, ripristino, worker

**Files:** Create `app/services/backup.py`, `app/worker.py`, `app/routers/backups.py`, `templates/backups.html`, `tests/test_backup.py`; Modify `app/main.py` (avvio worker se `start_worker`)

**Interfaces:**
- Produces: `daily_backup(settings, now_local: datetime) -> Path | None` (crea `giornalieri/AAAA-MM-GG.db` se ora ≥ 03:00 e non esiste; rotazione 14); `export_zip(settings) -> Path` (in `tmp/`: `magazzino.db` snapshot, `uploads/**`, `manifest.json` `{"app_version","schema_version","created_at"}`); `list_backups(settings) -> list[BackupInfo(path, kind, size, created_at)]`; `validate_backup(path) -> BackupCheck(ok: bool, reason: str | None, schema_version: int | None)` (zip o .db; rifiuta nomi con `..` o assoluti; `integrity_check`; tabelle `components, machines, movements, categories`); `restore_backup(app, source: Path) -> RestoreReport(pre_restore_path: Path, from_schema: int, to_schema: int)` (snapshot attuale in `backups/pre-ripristino/`, `engine.dispose()`, sostituisce db e uploads, `run_migrations`, nuovo engine in `app.state.engine`).
- `Worker(app)`, `async run(stop: asyncio.Event)`: ogni 60 s `daily_backup`; il job outbox si aggiunge in Task 13.
- Rotte: `GET /backups`, `GET /backups/export` (download zip), `GET /backups/{nome}/download`, `POST /backups/restore` (upload o nome; critica).

- [ ] **Step 1: test:** `test_daily_backup_once_per_day`, `test_daily_rotation_14`, `test_export_zip_contents`, `test_validate_rejects_bad_inputs` (non sqlite, zip traversal, tabelle mancanti), `test_restore_zip_replaces_and_keeps_pre_restore`, `test_restore_v111_db_runs_migrations`, `test_restore_invalid_leaves_data_untouched`, `test_restore_requires_critical`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: backup, ripristino e worker`.

### Task 13: Eventi, webhook, payload Discord, outbox

**Files:** Create `app/services/events.py`, `app/services/discord.py`, `app/services/outbox.py`, `app/routers/webhooks.py`, `templates/webhooks_list.html`, `templates/webhook_form.html`, `templates/webhooks_log.html`, `templates/partials/notify_checkbox.html`, `tests/test_webhooks.py`; Modify `app/worker.py`, `app/main.py` (`app.state.http = httpx.AsyncClient(timeout=10)`)

**Interfaces:**
- `discord.is_valid_discord_url(url) -> bool` (regex `^https://(discord\.com|discordapp\.com|ptb\.discord\.com|canary\.discord\.com)/api/webhooks/\d+/[\w-]+$`); `discord.build_payload(event, data, *, base_url, app_name, mention_role_id=None, username=None, avatar_url=None) -> dict` — embed: titolo `[SEVn] titolo` per incidenti, altrimenti `Etichetta evento: titolo`; colori SEV1 `0xE2231A`, SEV2 `0xF07F13`, SEV3 `0xF4C20D`, SEV4 `0x8A8A8A`, `resolved`/completata `0x2E7D32`, test fallito `0xE2231A`, default `0x111111`; limiti titolo 256, descrizione 4096, 25 campi, nome campo 256, valore 1024, troncamento con `…`; `url` solo se `base_url`; `allowed_mentions={"parse": []}` (+ `"roles": [id]` e `content "<@&id>"` solo per `incident.opened` SEV1 con ruolo); footer `app_name`; timestamp ISO `Z`.
- `discord.build_generic_payload(event, data, app_name) -> dict` = `{"event","app","sent_at","data"}`.
- `events.emit(db, event, data, *, base_url, severity=None, service_ids=(), notify=True) -> int` (accoda un `OutboxItem` per webhook attivo che corrisponde: evento selezionato, gravità ≥ minima se presente, filtro servizi); `events.default_notify(db, event, severity=None, service_ids=()) -> bool`.
- `outbox.BACKOFF_SECONDS = (10, 30, 60, 300, 900, 1800, 3600, 7200)`; `async deliver_due(engine, client, now=None) -> int`; `async deliver_one(db, item, client, now) -> None`: 2xx → sent; 429 → `retry_after` (JSON o header) senza contare il tentativo; altri 4xx → dead; 5xx/errore rete → backoff, dead dopo 8.
- Worker: `deliver_due` ogni 5 s; una volta al giorno elimina outbox `sent` più vecchi di 30 giorni.
- Rotte: `/webhooks` CRUD (create/edit/delete critiche, URL mascherato in lista), `POST /webhooks/{id}/test` (firma normale, consegna immediata), `GET /webhooks/log`.
- Macro `notify_checkbox(event, checked)` = casella "Pubblica su Discord".

- [ ] **Step 1: test** (httpx `MockTransport`): `test_discord_url_validation`, `test_payload_no_mentions_by_default`, `test_payload_role_only_sev1_opened`, `test_payload_truncates_limits` (emoji + 5000 caratteri), `test_emit_matches_rules` (evento, gravità, servizi), `test_emit_notify_false_enqueues_nothing`, `test_deliver_success`, `test_deliver_429_retry_after`, `test_deliver_4xx_dead`, `test_deliver_5xx_backoff_then_dead`, `test_webhook_create_requires_critical`, `test_send_test`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: webhook Discord con outbox`.

### Task 14: Posizioni ad albero

**Files:** Create `app/services/locations.py`, `app/routers/locations.py`, `templates/locations_list.html`, `templates/location_detail.html`, `templates/location_form.html`, `tests/test_locations.py`; Modify `app/routers/machines.py` + form macchina (`location_id`, `hostname`, `ip_address`, `os`)

**Interfaces:** `location_path(loc) -> str` (separatore ` › `); `descendant_ids(db, loc_id) -> list[int]`; `would_cycle(db, loc_id, new_parent_id) -> bool`; `location_options(db) -> list[tuple[int, str]]` (per select, ordinati per path).

- [ ] **Step 1: test:** `test_nested_path` ("Garage › Scaffale A › Box 3"), `test_tag_assigned`, `test_cycle_refused`, `test_delete_nonempty_refused`, `test_detail_includes_children_items`, `test_machine_location_saved`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: posizioni ad albero`.

### Task 15: Componente v2 — tipi, scorte, acquisto, stati, tag, campi tipizzati, filtri

**Files:** Create `app/services/component_form.py`, `app/services/component_query.py`, `static/js/attrs.js`, `tests/test_components_v2.py`; Modify `app/routers/components.py`, `app/services/inventory.py`, `templates/component_form.html`, `templates/component_detail.html`, `templates/components_list.html`

**Interfaces:**
- `parse_price(text) -> int | None` ("12,50"→1250, "1.234,56"→123456, "12.5"→1250, ""→None, "abc"→`ValueError`).
- `ComponentData` dataclass (tutti i campi della spec §6.1 + `tags: list[str]`, `attributes: dict`); `parse_component_form(form, fields: list[CategoryField]) -> ComponentData` (campi tipizzati con nome `cf_<field_id>`, numeri salvati come int/float, attributi liberi `attr_key`/`attr_value` mantenuti); `apply_component_data(comp, data) -> None`.
- `inventory.adjust_quantity(db, comp, delta: int, reason: str, signer, base_url) -> Movement` (`ValueError` se `tracking != "quantity"` o risultato < 0; emette `stock.low` solo quando passa da ≥ `min_stock` a < `min_stock`); `inventory.available_quantity(db, comp) -> int` (quantità − prenotazioni di progetti attivi).
- `build_component_query(db, params: Mapping[str, str], fields: list[CategoryField]) -> Select`: `q` (nome, codice, modello, produttore, seriale, asset tag), `category`, `status`, `machine`, `location` (con discendenti), `tag`, `tracking`, `low_stock=1`; per campo filtrabile numerico `f<id>_min`/`f<id>_max` con `json_type(attributes, '$."<key>"') IN ('integer','real')` OPPURE testo che rispetta `GLOB '[0-9]*'` e nessun carattere non numerico; scelta `f<id>=valore`. Chiavi con `"` vietate.
- Rotte nuove: `POST /components/{id}/qty` (`delta`, `reason`, notify).

- [ ] **Step 1: test:** `test_parse_price`, `test_create_quantity_item`, `test_adjust_quantity_movement_and_stock_low_once`, `test_adjust_negative_refused`, `test_typed_number_saved_as_number`, `test_legacy_attributes_kept_on_edit`, `test_numeric_filter_skips_non_numeric_legacy` (fixture v111 migrato: `Capacita (GB) >= 8` → RAM sì, SSD "1TB" no), `test_choice_filter`, `test_tags_and_tag_filter`, `test_new_statuses_labels`, `test_purchase_and_warranty_saved`, `test_deleted_excluded_from_filters`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** verifica browser form su mobile (375 px). **Step 6:** commit `feat: componenti v2`.

### Task 16: Gestione campi per categoria

**Files:** Create `app/routers/categories.py`, `templates/categories.html`, `templates/category_fields.html`, `tests/test_category_fields.py`

Rotte: `GET /categories`, `GET/POST /categories/{id}/fields` (aggiungi, modifica etichetta/unità/scelte/ordine/filtrabile, disattiva). `key` = etichetta alla creazione, poi immutabile.

- [ ] **Step 1: test:** `test_add_field_key_from_label`, `test_rename_keeps_key`, `test_key_with_quote_refused`, `test_order_saved`, `test_requires_signer`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: campi per categoria`.

### Task 17: QR, risoluzione scansioni, etichette

**Files:** Create `app/services/qr.py`, `app/routers/qr.py`, `templates/labels.html`, `tests/test_qr.py`

**Interfaces:** `TAG_RE = r"^[CML]-\d{3,}$"`; `qr_svg(data: str, scale: int = 4) -> str` (segno, errore `m`, scuro `#111111`); `tag_url(base_url, tag) -> str` = `{base}/q/{tag}`; `resolve_tag(db, tag) -> str | None`; `resolve_scan(db, value) -> dict` → `{"url": ...}` (URL con `/q/TAG`, tag nudo, seriale o codice oggetto esatto univoco, esclusi cancellati) oppure `{"search": "/components?q=..."}`.
Rotte: `GET /q/{tag}` (302 o 404), `GET /qr/{tag}.svg` (`image/svg+xml`), `GET /scan/resolve?v=`, `GET /labels?components=1,2&locations=3&format=small|medium|a4` (25×25 mm, 50×25 mm, A4 70×37 mm 3×8; `@page`; posizione = tutto il contenuto incluse sottoposizioni). Pulsante "Etichetta" su schede componente, posizione, macchina.

- [ ] **Step 1: test:** `test_q_redirects` (C/L/M), `test_q_unknown_404`, `test_qr_svg_response`, `test_tag_url`, `test_scan_resolve_cases`, `test_scan_ignores_deleted`, `test_labels_formats`, `test_labels_location_includes_children`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: QR ed etichette`.

### Task 18: Allegati e foto

**Files:** Create `app/services/uploads.py`, `app/routers/attachments.py`, `templates/partials/attachments.html`, `tests/test_uploads.py`

**Interfaces:** `MAX_BYTES = 25 * 1024 * 1024`; `detect_kind(head: bytes, filename: str) -> tuple[str, str] | None` (magic bytes: JPEG, PNG, WEBP, GIF, `%PDF-`; testo UTF-8 senza NUL per `.txt .log .json .csv`; SVG/HTML mai); `save_upload(settings, db, upload, entity_type, entity_id, signer) -> Attachment` (immagini: `ImageOps.exif_transpose`, risalvate senza EXIF, miniatura WEBP 400 px `<uuid>_thumb.webp`); `trash_attachment(settings, db, att, signer)` (sposta in `uploads/.cestino/`); `UploadRejected(status: int, message: str)` (413 dimensione, 415 tipo).
Rotte: `POST /attachments` (`entity_type`, `entity_id`, file multipli), `GET /attachments/{id}` (`nosniff`, `inline` per immagini/pdf, `attachment` per il resto), `GET /attachments/{id}/thumb`, `POST /attachments/{id}/delete`, `POST /attachments/trash/empty` (critica). Input con `accept` e `capture="environment"` per le foto.

- [ ] **Step 1: test:** `test_jpeg_exif_gps_removed_and_thumb`, `test_orientation_applied`, `test_fake_jpeg_rejected_415`, `test_svg_rejected`, `test_too_large_413`, `test_served_headers`, `test_trash_moves_file`, `test_empty_trash_critical`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: allegati e foto`.

### Task 19: Scanner con fallback iOS e modalità a raffica

**Files:** Create `static/vendor/barcode-detector/ponyfill.min.js` (+ `LICENSE`), `static/vendor/zxing/zxing_reader.wasm` (+ `LICENSE`), `tests/test_scanner_assets.py`; Modify `static/js/scanner.js`, `templates/base.html`, `app/main.py` (mime `application/wasm`)

Sorgenti: `barcode-detector@3.2.3/dist/iife/ponyfill.min.js`, `zxing-wasm@3.1.6/dist/reader/zxing_reader.wasm` (scaricati una volta e committati). `scanner.js`: `BarcodeDetector` nativo, altrimenti `window.BarcodeDetectionAPI.BarcodeDetector` dopo `prepareZXingModule({overrides: {locateFile: (p, pre) => p.endsWith(".wasm") ? "/static/vendor/zxing/" + p : pre + p}})`; ogni lettura passa da `/scan/resolve`; modalità a raffica: lista letti, vibrazione, anti-doppione 2 s, azioni finali (seleziona per modifica di massa, aggiungi a inventario aperto). Messaggi in dialog, non `alert`.

- [ ] **Step 1: test:** `test_vendor_files_present` (wasm inizia con `b"\0asm"`), `test_wasm_mime` (`application/wasm`), `test_own_js_no_cdn` (nessun `jsdelivr|unpkg|fastly` in `static/js/*.js`).
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** verifica browser (Chromium con fotocamera finta `--use-fake-device-for-media-stream` o input manuale). **Step 6:** commit `feat: scanner offline con modalità a raffica`.

### Task 20: Modifica di massa e CSV

**Files:** Create `app/services/csv_io.py`, `static/js/bulk.js`, `templates/import_preview.html`, `tests/test_bulk_csv.py`; Modify `app/routers/components.py`, `templates/components_list.html`

**Interfaces:** `export_components_csv(db) -> str` (UTF-8 con BOM, separatore `;`, colonne: asset_tag, object_code, name, category, tracking, model, manufacturer, serial_number, quantity, unit, min_stock, status, location_path, machine, supplier, purchase_date, purchase_price, currency, warranty_until, invoice_ref, tags, notes, poi `attr:<key>` ordinate); `plan_import(db, text) -> ImportPlan(rows: list[ImportRow(line: int, action: Literal["create","update","unchanged","error"], match: str | None, data: dict, errors: list[str])])` (corrispondenza per asset_tag, poi seriale); `apply_import(db, plan, signer) -> ImportResult(created: int, updated: int)` (crea posizioni mancanti dal path).
Rotte: `POST /components/bulk` (`ids`, `action` ∈ move_location, move_machine, set_status, add_tag), `POST /components/bulk/delete` (critica), `GET /components/export.csv`, `POST /components/import` (anteprima, file salvato in `tmp/import-<uuid>.csv` legato alla sessione), `POST /components/import/apply`.

- [ ] **Step 1: test:** `test_bulk_move_location_with_movements`, `test_bulk_status`, `test_bulk_add_tag`, `test_bulk_delete_critical`, `test_export_bom_and_separator`, `test_import_plan_actions`, `test_import_apply_creates_locations`, `test_export_import_roundtrip_unchanged`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: modifica di massa e CSV`.

### Task 21: Registro test e modelli di test

**Files:** Create `app/services/testing.py`, `app/routers/tests_log.py`, `templates/test_templates.html`, `templates/test_template_form.html`, `templates/test_run_form.html`, `templates/test_queue.html`, `tests/test_testing.py`; Modify `templates/component_detail.html`

**Interfaces:** campo modello `{key, label, type, unit, min, max, choices, pass_value}`; `suggest_result(fields: list[dict], values: dict) -> str | None` (numero fuori min/max → fail; bool diverso da `pass_value` → fail; almeno una regola valutata e tutte ok → pass; nessuna regola → None).
Rotte: CRUD modelli, `GET/POST /components/{id}/tests/new` (esito, valori, checklist, strumento, note, allegati, casella "Imposta stato a …" proposta ma non spuntata d'ufficio, notify per `test.failed`), `GET /tests/queue` (stato `to_test`). Aggiorna `last_test_at`/`last_test_result`; stato cambiato solo se l'operatore spunta la casella.

- [ ] **Step 1: test:** `test_suggest_result_rules`, `test_run_updates_last_test`, `test_status_changes_only_when_checked`, `test_failed_emits_when_notify`, `test_queue_lists_to_test`, `test_template_crud`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: registro test`.

### Task 22: Inventario fisico

**Files:** Create `app/routers/audits.py`, `templates/audits_list.html`, `templates/audit_run.html`, `tests/test_physical_audit.py`

Rotte: `POST /audits/new` (`location_id`, `include_children`), `GET /audits/{id}`, `POST /audits/{id}/scan` (JSON `{value}` → `{"state", "component"}`), `POST /audits/{id}/items/{item_id}/move-here`, `POST /audits/{id}/finish` (mancanti, `last_audit_at` su componenti trovati e posizione, `summary`, `audit.completed` se notify), `GET /audits/overdue` (posizioni mai verificate o oltre `audit_interval_days`).

- [ ] **Step 1: test:** `test_start_expected_includes_children`, `test_scan_found`, `test_scan_unexpected`, `test_move_here`, `test_finish_marks_missing_and_dates`, `test_overdue_locations`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: inventario fisico`.

### Task 23: Progetti / build

**Files:** Create `app/routers/projects.py`, `templates/projects_list.html`, `templates/project_detail.html`, `tests/test_projects.py`

Regole: aggiunta pezzo seriale → `prev_status` salvato, stato `reserved`; pezzo a quantità → prenotazione `qty` ≤ `available_quantity`; annulla → stati ripristinati; completa → seriali montati sulla macchina obiettivo (`in_use`) + `adjust_quantity(-qty, "Build <nome>")` per le scorte, movimenti firmati.

- [ ] **Step 1: test:** `test_reserve_serial_and_cancel_restores`, `test_reserve_quantity_reduces_available`, `test_over_reservation_refused`, `test_complete_build`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: progetti e build`.

### Task 24: Servizi, moduli, changelog, link

**Files:** Create `app/services/links.py`, `app/services/markdown.py`, `app/routers/services.py`, `app/routers/changes.py`, `templates/services_list.html`, `templates/service_detail.html`, `templates/service_form.html`, `templates/module_form.html`, `templates/changes_list.html`, `templates/change_form.html`, `templates/partials/links.html`, `tests/test_services.py`

**Interfaces:** `is_safe_url(url) -> bool` (solo `http`/`https`); `parse_link(url) -> LinkInfo(kind, owner, repo, ref)` per `github.com/{o}/{r}/commit/{sha}`, `/pull/{n}`, `/issues/{n}`, `/releases/tag/{tag}`, `/{o}/{r}` (anche `.git` e `/` finale), altrimenti `altro`; nessuna chiamata di rete. `render_markdown(text) -> Markup` (markdown-it-py `commonmark`, `html=False`, link `rel="noopener noreferrer"`), filtro Jinja `md`.
Servizi: slug unico dal nome, macchina, URL, runbook (avviso fisso "Non inserire password"), stato manuale (cambio → `service.status_changed` se notify). Moduli: tipo, versione, repo. Changelog: tipo, versione, titolo, corpo, data, link multipli (URL + titolo), allegati, casella "Aggiorna versione del modulo", notify per `change.published`.

- [ ] **Step 1: test:** `test_parse_link_cases`, `test_javascript_url_refused`, `test_service_slug_unique`, `test_change_with_links_updates_module_version_when_checked`, `test_change_published_event`, `test_status_change_event`, `test_markdown_escapes_html`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: servizi e changelog`.

### Task 25: Incidenti e problemi noti

**Files:** Create `app/routers/incidents.py`, `app/routers/problems.py`, `templates/incidents_list.html`, `templates/incident_detail.html`, `templates/incident_form.html`, `templates/problems_list.html`, `templates/problem_form.html`, `tests/test_incidents.py`

Apertura: titolo, gravità, servizi, riepilogo, inizio (`datetime-local` → UTC), per ogni servizio select "nuovo stato" (vuoto = invariato), notify `incident.opened`. Aggiornamenti: stato + messaggio + notify (`incident.updated`; con stato `resolved` → `resolved_at` e `incident.resolved`). Causa e post-mortem markdown. Problemi: descrizione, workaround, stato, servizi, incidenti collegati.

- [ ] **Step 1: test:** `test_open_incident_changes_service_status_only_when_chosen`, `test_update_transition_event`, `test_resolve_sets_resolved_at_and_event`, `test_postmortem_html_escaped`, `test_problem_links`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: incidenti e problemi noti`.

### Task 26: Manutenzioni e pagina di stato

**Files:** Create `app/routers/maintenance.py`, `app/routers/status.py`, `templates/maintenance_list.html`, `templates/maintenance_form.html`, `templates/status.html`, `tests/test_maintenance_status.py`

Manutenzioni: programma (notify `maintenance.scheduled`), "Avvia"/"Completa"/"Annulla" manuali con proposta stato servizi e notify; in ritardo = solo evidenziate. `/status`: servizi + stato, incidenti attivi, manutenzioni, storico incidenti 30 giorni.

- [ ] **Step 1: test:** `test_transitions_manual_only` (il worker non cambia stato), `test_overdue_flag`, `test_events`, `test_status_page_content`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: manutenzioni e pagina di stato`.

### Task 27: Ricerca globale Ctrl+K

**Files:** Create `app/services/search.py`, `app/routers/search.py`, `templates/search.html`, `templates/partials/palette.html`, `static/js/palette.js`, `tests/test_search.py`

**Interfaces:** `global_search(db, q, limit=6) -> list[SearchGroup(label: str, items: list[SearchHit(title, subtitle, url)])]` su componenti, posizioni, macchine, servizi, incidenti, changelog, operatori; esclusi cancellati; `q` < 2 caratteri → lista vuota. `GET /search.json?q=`, `GET /search?q=` (senza JS). Palette: `Ctrl+K`/`Cmd+K`, frecce, `Invio`, `Esc`, ruoli ARIA combobox/listbox.

- [ ] **Step 1: test:** `test_groups`, `test_excludes_deleted`, `test_min_length`, `test_page_without_js`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: ricerca globale`.

### Task 28: Dashboard centro di comando

**Files:** Create `app/services/dashboard.py`, `tests/test_dashboard.py`; Modify `app/routers/dashboard.py`, `templates/dashboard.html`

**Interfaces:** `command_center(db, now) -> dict` con chiavi `services_by_status`, `open_incidents_by_severity`, `upcoming_maintenance` (7 giorni), `low_stock`, `to_test_count`, `warranty_expiring` (30 giorni), `overdue_locations`, `inventory_value_cents`, `recent_activity` (ultime 10 righe audit), `stats` (contatori v1 senza cancellati).

- [ ] **Step 1: test:** `test_sections_with_data`, `test_empty_db`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** commit `feat: dashboard centro di comando`.

### Task 29: Design system, tema scuro, mobile, PWA

**Files:** Modify `static/css/style.css`, `templates/base.html`; Create `templates/partials/bottom_nav.html`, `templates/offline.html`, `static/pwa/*`, `scripts/make_icons.py`, `tests/test_ui_pwa.py`

Contenuto: token `:root` + tema scuro (`prefers-color-scheme` + `[data-theme]`, interruttore salvato in `localStorage`), `--red-dark` per testo piccolo su carta, focus visibile 3 px, target ≥ 44 px, `prefers-reduced-motion`, tabelle → schede sotto 780 px, barra in basso (Home · Cerca · Scan · Incidenti · Menu). PWA: `/manifest.webmanifest` (`application/manifest+json`, `theme_color #111111`, icone 192/512/maskable da `scripts/make_icons.py`, rombo rosso su nero), `/sw.js` servito dalla radice (cache-first `/static`, network-first pagine, fallback `/offline`), `<link rel="manifest" crossorigin="use-credentials">`.

- [ ] **Step 1: test:** `test_contrast_pairs` (legge i token da `style.css`; coppie testo/sfondo dichiarate nel test ≥ 4.5:1, testi grandi ≥ 3:1), `test_manifest`, `test_sw_root_scope`, `test_offline_page`, `test_bottom_nav_present`.
- [ ] **Step 2–4:** FAIL → implementa → PASS. **Step 5:** verifica browser a 375 px e 1280 px, tema chiaro e scuro, screenshot. **Step 6:** commit `feat: design system, tema scuro, PWA`.

### Task 30: Documentazione, compose, CI

**Files:** Modify `README.md`, `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example`, `.github/workflows/docker-publish.yml`; Create `CHANGELOG.md`

- Compose standalone e dev: immagine `:2.0.0`, niente `APP_PASSWORD`, `PUBLIC_BASE_URL` e `WEBAUTHN_RP_ID` facoltative, avviso "senza password: tenere dietro un proxy con autenticazione".
- CI: job `test` (setup-python 3.12, `pip install -r requirements.txt -r requirements-dev.txt`, `python -m pytest -q`); job `build` con `needs: test`.
- README: funzioni v2, firma operatori, backup/ripristino, Umbrel (login Umbrel obbligatorio), aggiornamento dalla 1.1.1.
- [ ] **Step 1:** `.venv/Scripts/python -m pytest -q` → tutti verdi. **Step 2:** commit `docs: README, compose e CI per v2.0.0`.

### Task 31: Rilascio e aggiornamento su Umbrel (chiedere conferma all'utente prima di push e update)

- [ ] **Step 1:** suite completa verde; revisione finale del branch.
- [ ] **Step 2:** merge `dev/v2` → `main`, tag `v2.0.0`, push; verifica job CI verde e immagine `ghcr.io/gigiomiccio425/magazzino-zimaos:2.0.0` pubblica.
- [ ] **Step 3:** repo `Gigio-dany-appstore`: `g-d-app-store-gd-magazzino/docker-compose.yml` come spec §15 (immagine `2.0.0`, `PROXY_AUTH_ADD: "true"`, niente `APP_PASSWORD`), `umbrel-app.yml` `version: "2.0.0"` + `releaseNotes`; commit e push.
- [ ] **Step 4:** Umbrel MCP: copia `/Apps/g-d-app-store-gd-magazzino/data` in `/Home/Backups/magazzino/2026-xx-xx-pre-v2.0.0/`.
- [ ] **Step 5:** aggiorna l'app (`update_app`), controlla log: migrazione `v0 → v3`, backup pre-migrazione creato, `/health` 200.
- [ ] **Step 6:** verifica nel browser via HTTPS: login Umbrel richiesto, dati v1.1.1 presenti, prima firma con impronta, scansione QR, webhook di test su Discord.
