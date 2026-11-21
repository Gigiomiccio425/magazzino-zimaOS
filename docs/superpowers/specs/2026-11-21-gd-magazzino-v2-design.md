# GD Magazzino 2.0 — Documento di design

Data: 2026-11-21
Stato: in attesa di approvazione
Repo codice: `Gigiomiccio425/magazzino-zimaOS` — Repo app store Umbrel: `Gigiomiccio425/Gigio-dany-appstore`

---

## 1. Intento

GD Magazzino oggi è un inventario hardware semplice (componenti, macchine, movimenti).
Deve diventare un **gestionale e centro di comando a 360°** per il server Umbrel di casa:

- catalogare in modo rapido, accessibile e affidabile cavi, schede video e componenti nuovi;
- verificare i componenti e tenere un **registro dei test** eseguiti;
- gestire i **servizi** che girano sul server (app, bot, app PC/telefono) con changelog,
  fix, debug e link GitHub;
- aprire e seguire **incidenti** e problemi, e pubblicare avvisi su **Discord** via webhook;
- far **firmare** ogni modifica all'operatore che la esegue (impronta/passkey o password),
  con più operatori.

Il perché: oggi l'inventario è inutilizzabile (login rotto) e non copre né la verifica dei
pezzi né la gestione operativa del server. Serve un unico posto, con lo stile attuale,
dove sapere cosa c'è, dove sta, se funziona, e cosa succede sui servizi.

## 2. Obiettivi, non-obiettivi, anti-obiettivi

**Obiettivi**
- Nessun dato esistente perso o alterato: `magazzino.db` e `.secret_key` sopravvivono a ogni update.
- Accesso sbloccato: niente password applicativa, login Umbrel obbligatorio davanti.
- Tutte le 40 funzioni approvate (sezioni 8–14), consegnate in 4 release.
- QR su **ogni singolo prodotto** e su **ogni posizione** (stanza/scaffale/box).
- Più operatori: alla prima firma con un nome nuovo, l'operatore registra la propria
  impronta/passkey e/o password.
- Accessibilità WCAG 2.2 AA, uso comodo da telefono.
- Stile costruttivista invariato (nero/bianco/rosso, geometrico, ombre piene, maiuscolo bold).

**Non-obiettivi**
- Multi-tenant, utenti esterni, permessi granulari per sezione (solo operatore/admin).
- Contabilità, fatturazione, ordini fornitori.
- Uso offline con scrittura (la PWA mette in cache solo la grafica).
- Stampa diretta su stampanti di etichette specifiche (si stampa dal browser).
- Salvataggio di password/segreti dei servizi (i runbook non devono contenerli).

**Anti-obiettivi** (fallimento anche se "funziona")
- Un update che rompe o modifica i dati salvati senza backup recuperabile.
- Un'app che sembra un template generico invece dello stile attuale.
- Firma così invasiva da far smettere di registrare le modifiche.
- Una notifica Discord che tagga `@everyone` per sbaglio.

## 3. Vincoli

- Deploy: Umbrel, app store personale `Gigio-dany-appstore`, app id `g-d-app-store-gd-magazzino`.
  Immagine `ghcr.io/gigiomiccio425/magazzino-zimaos:<versione>` buildata da GitHub Actions su tag `vX.Y.Z`.
- Dati: `${APP_DATA_DIR}/data` → `/data` nel container
  (su Umbrel: `/Apps/g-d-app-store-gd-magazzino/data`). Contiene `magazzino.db` + `.secret_key`.
- Il compile del compose Umbrel usa variabili riservate: **`APP_PASSWORD` è riservata da Umbrel**
  (password generata per app). È la causa del login rotto in v1.1.1: `${APP_PASSWORD:-cambiami}`
  riceve la password di Umbrel, che non viene mai mostrata (`defaultPassword: ""`).
- Il server oggi **non è esposto a internet**. HTTPS arriva tramite reverse proxy
  (es. Tailscale serve) davanti all'app proxy Umbrel; si accede anche via `http://umbrel.local:8000`.
- WebAuthn (impronta/passkey) funziona solo in contesto sicuro (HTTPS o localhost) e la
  passkey è legata al dominio: registrata su un dominio non vale su un altro.
- Il container gira con un solo processo uvicorn (necessario per il worker interno e SQLite).
- Nessuna CDN: tutto servito in locale (funziona in LAN, CSP stretta).
- Ambiente di sviluppo: Windows, niente Python di sistema (si usa `uv`), Docker Desktop non
  sempre attivo → test con `uv run pytest`, immagine buildata in CI.

## 4. Approcci considerati

| Approccio | Pro | Contro |
|---|---|---|
| **A. Evolvere l'app attuale** (FastAPI + Jinja2 server-rendered + JS vanilla + SQLite), modulare per router | Mantiene stile, dati e pipeline di deploy; immagine piccola; zero build frontend; rischio basso | JS vanilla da organizzare bene per le parti interattive (firma, scanner, palette) |
| B. Riscrittura SPA (React/Vite) + API JSON | Interfacce molto interattive | Riscrittura totale, stile da rifare, build frontend, rischio sui tempi e sui dati; nessun vantaggio a questa scala |
| C. Integrare strumenti esistenti (Snipe-IT + Kener/Uptime Kuma) | Funzioni mature | Niente centro unico, niente firme integrate, stile perso, più container da gestire |

**Scelto: A** (scelta di Claude, l'utente ha delegato il "come"). B e C vanno contro due
obiettivi espliciti: stile invariato e dati intatti in un unico strumento.

## 5. Architettura

```
app/
  main.py            app FastAPI, lifespan (migrazioni, worker), middleware, router
  config.py          env + chiave segreta
  database.py        engine SQLite (WAL, foreign_keys=ON), sessioni
  models/            modelli ORM divisi per area (inventory, ops, security, system)
  migrations/        runner + migrazioni numerate (SQL grezzo, mai ORM)
  services/          logica di dominio: audit, signing, webauthn, qr, labels, discord,
                     outbox, healthcheck, github, backup, csv_io, search, uploads
  worker.py          scheduler asyncio interno (outbox, health check, manutenzioni,
                     polling GitHub, backup giornaliero, avvisi giornalieri, pulizia)
  routers/           dashboard, components, locations, machines, movements, audits,
                     projects, tests, services, changes, incidents, problems,
                     maintenance, status, operators, sign, webhooks, api_tokens,
                     backups, audit_log, settings, search, qr, labels, attachments, api_v1
templates/           Jinja2 (base + partial riusabili + pagine per area)
static/
  css/style.css      design system costruttivista (token chiaro/scuro)
  js/                app.js, sign.js, scanner.js, palette.js, bulk.js, attrs.js
  vendor/            polyfill BarcodeDetector (zxing-wasm) vendorizzato, con licenza
  pwa/               manifest, icone, service worker
tests/               pytest (+ fixture DB v1.1.1)
```

- **Dipendenze nuove** (versioni esatte fissate in `requirements.txt`, stabili da almeno 2 settimane):
  `httpx` (client HTTP async), `webauthn` (py_webauthn 2.x), `segno` (QR, puro Python),
  `Pillow` (miniature + rimozione EXIF), `markdown-it-py` (markdown con HTML disattivato),
  `pytest` solo per sviluppo (`requirements-dev.txt`).
- `@app.on_event("startup")` sostituito da `lifespan`.
- SQLite in modalità WAL, `foreign_keys=ON`, `busy_timeout` 5 s.
- Markdown sempre renderizzato con HTML disattivato; link `rel="noopener noreferrer"`.
- Header di sicurezza: CSP `default-src 'self'` (+ `'wasm-unsafe-eval'` per lo scanner,
  `img-src 'self' data: blob:`), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, `frame-ancestors 'self'`, `Permissions-Policy: camera=(self)`.
- **CSRF**: token per sessione in un campo nascosto in ogni form POST e in un header per le
  chiamate `fetch`; verificato da un middleware su tutti i metodi non sicuri (escluse
  `/api/v1` con token Bearer).
- Navigazione raggruppata: **Dashboard** · **Magazzino** (Componenti, Posizioni, Macchine,
  Movimenti, Inventari, Progetti) · **Verifica** (Test, Modelli test) · **Centro comando**
  (Servizi, Incidenti, Problemi noti, Manutenzioni, Changelog, Stato) · **Sistema**
  (Operatori, Webhook, API token, Backup, Audit log, Impostazioni).

## 6. Modello dati

Regola: **le tabelle esistenti non perdono né rinominano colonne**. Si aggiungono solo
colonne, tabelle e indici. I dati esistenti non vengono riscritti, tranne i backfill
indicati qui sotto (che aggiungono valori in colonne nuove).

### 6.1 Tabelle esistenti — colonne aggiunte

`components`
- `asset_tag` (unico, es. `C-000123`) — backfill per tutti i componenti esistenti, in ordine di id.
- `tracking` (`serial` | `quantity`) — backfill: `quantity` se `quantity > 1`, altrimenti `serial`.
- `min_stock` (int, null), `unit` (es. `pz`, `m`; default `pz`).
- `location_id` → `locations.id` (null) — backfill dai testi `location` esistenti (vedi 6.3).
  La colonna testo `location` resta e non viene toccata.
- `supplier`, `purchase_date`, `purchase_price` (decimale in centesimi, int), `currency` (default EUR),
  `warranty_until`, `invoice_ref`.
- `last_test_at`, `last_test_result`, `last_audit_at`.
- `deleted_at` (soft delete), `created_by` / `updated_by` → `operators.id` (null per i dati storici).

`machines`: `asset_tag` (`M-001`), `location_id`, `hostname`, `ip_address`, `os`, `deleted_at`.

`movements`: `operator_id`, `signature_id`, `qty_delta` (per articoli a quantità), `reason`.

`categories`: `icon` (facoltativo), `default_tracking`, `default_unit`.

### 6.2 Nuove tabelle (per area)

**Inventario**
- `locations` (id, asset_tag `L-0001`, name, kind: stanza/scaffale/ripiano/box/cassetto/altro,
  parent_id, notes, deleted_at). Albero illimitato; path calcolato ("Garage › Scaffale A › Box 3").
- `category_fields` (id, category_id, key, label, type: text/number/choice/bool/date, unit,
  choices JSON, required, sort_order, filterable). **`key` è immutabile e per i template
  predefiniti coincide con l'etichetta storica** (es. `"Capacita (GB)"`), così i valori già
  salvati in `components.attributes` restano validi senza riscriverli.
- `tags`, `component_tags`.
- `attachments` (id, entity_type, entity_id, filename, mime, size, path, thumb_path,
  operator_id, created_at, deleted_at).
- `audits` (inventari fisici: id, location_id, include_children, status, started_at,
  finished_at, operator_id, signature_id, summary JSON), `audit_items` (audit_id,
  component_id, state: expected/found/missing/unexpected, scanned_at).
- `projects` (build: id, name, description, status: bozza/in_costruzione/completata/annullata,
  target_machine_id), `project_items` (project_id, component_id, qty, note).

**Verifica**
- `test_templates` (id, name, category, description, fields JSON
  `[{key,label,type,unit,min,max}]`, checklist JSON, active).
- `test_runs` (id, component_id, template_id, result: pass/fail/partial/inconclusive,
  values JSON, checklist JSON, tool, notes, started_at, finished_at, operator_id, signature_id).

**Centro comando**
- `services` (id, slug, name, machine_id, description, url, status_manual, status_computed,
  runbook_md, check_type: none/http/tcp, check_target, check_interval_s, check_expect,
  check_timeout_s, deleted_at).
- `service_modules` (id, service_id, name, kind: web/app_pc/app_android/app_ios/bot/api/
  worker/db/altro, current_version, repo_url, notes).
- `service_checks` (id, service_id, ts, ok, latency_ms, detail) — conservati 30 giorni.
- `changes` (changelog: id, service_id, module_id, type: release/update/fix/debug/feature/
  config/rollback/note, version, title, body_md, occurred_at, auto, operator_id, signature_id).
- `links` (id, entity_type, entity_id, url, kind: github_commit/github_pr/github_issue/
  github_release/github_repo/altro, owner, repo, ref, meta JSON, meta_fetched_at).
- `incidents` (id, title, severity SEV1–SEV4, status: aperto/in_analisi/identificato/
  monitoraggio/risolto, started_at, resolved_at, summary, root_cause, postmortem_md,
  auto, operator_id), `incident_services`, `incident_updates` (incident_id, status, message,
  created_at, operator_id, signature_id, notified).
- `problems` (problemi noti: id, title, description_md, workaround_md, status: aperto/
  workaround/risolto), `problem_services`, `problem_incidents`.
- `maintenances` (id, title, description_md, starts_at, ends_at, status: programmata/
  in_corso/completata/annullata), `maintenance_services`.

**Notifiche e integrazioni**
- `webhooks` (id, name, kind: discord/generic, url, enabled, events JSON, min_severity,
  service_ids JSON o null = tutti, mention_role_id per SEV1, username, avatar_url).
- `outbox` (id, webhook_id, event, payload JSON, status: pending/sent/failed/dead,
  attempts, next_attempt_at, last_error, created_at, sent_at).
- `api_tokens` (id, name, prefix, token_hash, scopes: read/write, created_at, last_used_at,
  revoked_at).
- `github_cache` (url, etag, body JSON, fetched_at).

**Sicurezza e sistema**
- `operators` (id, name unico case-insensitive, is_admin, active, password_hash (scrypt),
  failed_attempts, locked_until, created_at).
- `operator_credentials` (id, operator_id, credential_id, public_key, sign_count,
  transports, rp_id, label dispositivo, created_at, last_used_at).
- `signatures` (id, operator_id, method: passkey/password, purpose, action_hash, rp_id,
  ip, user_agent, created_at).
- `audit_log` (id, ts, actor_type: operator/system/api, operator_id, api_token_id,
  signature_id, entity_type, entity_id, action, before JSON, after JSON, prev_hash, hash).
- `settings` (key, value JSON).

### 6.3 Backfill delle posizioni

Per ogni valore testo distinto non vuoto in `components.location` si crea una `location` di
primo livello con quel nome (kind `altro`), e il componente riceve il suo `location_id`.
Nessun testo viene modificato. L'utente poi riorganizza l'albero da interfaccia.

## 7. Migrazioni e sicurezza dei dati

- Versione schema in `PRAGMA user_version`. Il DB v1.1.1 ha `user_version = 0` e le tabelle
  originali: la migrazione 1 è la **baseline** (crea le tabelle originali solo se mancano, per
  le installazioni nuove) e poi si applicano le successive.
- Migrazioni = funzioni Python numerate con SQL grezzo, indipendenti dai modelli ORM
  (così modifiche future ai modelli non rompono migrazioni vecchie). Mai `DROP`, mai
  `RENAME` di colonne esistenti.
- `Base.metadata.create_all` non si usa più all'avvio: lo schema lo gestiscono solo le migrazioni.
- **Prima di ogni migrazione**: `PRAGMA integrity_check`, poi backup con l'API di backup
  SQLite in `/data/backups/pre-migrazione/v{da}-a-v{a}-{timestamp}.db`. Non si crea un
  doppione se esiste già un backup per la stessa versione di partenza e lo stesso hash del file.
  Conservati gli ultimi 10.
- Ogni migrazione gira in transazione. Se una migrazione fallisce: rollback, log chiaro,
  il file originale resta intatto, l'app non parte (exit ≠ 0). Nessun ripristino automatico
  che possa sovrascrivere dati.
- **Backup giornaliero** automatico del DB alle 03:00 in `/data/backups/giornalieri/`, 14 conservati.
- **Allegati** in `/data/uploads/AAAA/MM/<uuid>.<ext>`: file mai modificati; l'eliminazione
  sposta in `/data/uploads/.cestino/` per 30 giorni.
- **Backup manuale da interfaccia**: zip con snapshot consistente del DB + allegati + manifest
  (versione app, versione schema, data). **Ripristino**: carica zip o scegli un backup,
  verifica integrità e tabelle attese, backup automatico dello stato attuale, sostituzione,
  migrazioni. Azione critica (firma richiesta da v1.3.0).
- **Soft delete** per componenti, macchine, posizioni, servizi: "Cestino" ripristinabile.
  Eliminazione definitiva solo dal cestino, con firma.
- Prova di conservazione: i test applicano tutte le migrazioni a un DB fixture generato con
  il codice v1.1.1 e verificano che righe e valori originali siano identici.
- Prima di ogni update sul server reale, copia extra della cartella dati in
  `/Home/Backups/magazzino/<data>-pre-v<versione>/` tramite Umbrel.

## 8. Accesso, operatori e firma

### 8.1 Accesso
- Rimossi login applicativo, `APP_PASSWORD`, middleware `require_login`. `/login` reindirizza a `/`.
- Compose Umbrel: `PROXY_AUTH_ADD: "true"` (login Umbrel obbligatorio), variabile
  `APP_PASSWORD` rimossa. `SessionMiddleware` resta (flash, sessione di firma, CSRF).
- L'API `/api/v1` è raggiungibile dagli altri container Umbrel (es. n8n) sulla rete Docker
  interna, senza passare dall'app proxy, ma solo con token Bearer.

### 8.2 Operatori e prima firma
- Ogni modifica richiede un operatore firmato. Alla prima modifica dal dispositivo compare il
  pannello **"Chi firma?"**: elenco operatori esistenti + campo "Nuovo operatore".
- **Nome nuovo** → registrazione immediata, che vale anche come prima firma:
  - "Impronta / passkey" (mostrato solo se il browser supporta WebAuthn e la pagina è in HTTPS):
    passkey legata al dominio attuale, verifica utente obbligatoria (impronta, volto o PIN del dispositivo);
  - "Password" (minimo 6 caratteri, anche solo cifre), salvata con scrypt;
  - almeno uno dei due è obbligatorio, consigliati entrambi (la password serve sui domini senza HTTPS).
- **Nome esistente** → firma con passkey (se registrata per questo dominio) o password.
- Il primo operatore creato è **admin**. Gli admin possono disattivare operatori, azzerare
  password/passkey, promuovere admin (azione critica).
- Dal profilo, un operatore aggiunge altre passkey (altri telefoni/PC/domini) dopo essersi firmato.
- Blocco dopo 5 password errate: 15 minuti per quell'operatore.

### 8.3 Sessione di firma
- Dopo una firma, il dispositivo resta firmato da quell'operatore per **10 minuti**
  (configurabile 0–60; 0 = firma a ogni modifica). Barra in alto: "Firmato: NOME · 7 min · Esci".
- Le **azioni critiche** chiedono sempre una firma nuova legata all'azione: eliminazioni,
  svuotamento cestino, ripristino backup, impostazioni, webhook, operatori, token API,
  modifiche di massa con eliminazione. Per le passkey la challenge include l'hash dell'azione
  (`metodo + path + campi principali`): la firma vale solo per quell'azione, una volta, per 2 minuti.
- Lato server: dipendenza `require_signer(critical=False)` su tutte le rotte di scrittura.
  Lato client: `sign.js` intercetta i form `[data-sign]` (di default tutti i POST), controlla
  lo stato, apre il pannello se serve, poi invia il form. Se il server risponde che la firma
  è scaduta, il pannello si riapre e il form viene reinviato senza perdere i dati.
  Le scritture richiedono JavaScript attivo (browser moderni); senza JS il server rifiuta con
  un messaggio chiaro invece di salvare senza firma.
- WebAuthn: `rp_id` = hostname dell'origine della richiesta (o `WEBAUTHN_RP_ID` se impostata),
  `rp_name` = `APP_NAME`, attestazione `none`, ES256 + RS256. L'origine attesa è salvata con la
  challenge e verificata alla risposta. Challenge monouso, scadenza 2 minuti.

### 8.4 Audit log
- Ogni scrittura (UI, API, sistema) genera una riga `audit_log` con attore, firma, entità,
  azione, prima/dopo (solo campi cambiati).
- **Catena di hash**: `hash = sha256(prev_hash + json canonico della riga)`. Pagina
  "Verifica integrità" che ricalcola la catena e segnala il primo punto alterato.
- Attori non umani: `system` (health check, polling GitHub, manutenzioni automatiche),
  `api` (token, con nome del token).

## 9. Catalogo

- **Due tipi di articolo**:
  - `serial`: un record = un pezzo fisico (GPU, SSD). Seriale, QR proprio.
  - `quantity`: un record = una scorta (cavi HDMI 2 m ×30). Quantità, unità, scorta minima,
    pulsanti rapidi +/−, ogni variazione è un movimento con delta e motivo. Sotto la scorta
    minima → avviso in dashboard + evento `stock.low`.
- **Posizioni ad albero** con pagina propria (contenuto, sottoposizioni, QR, stampa etichette).
- **QR su ogni singolo prodotto** (componenti e scorte), **su ogni posizione** e su ogni macchina.
  - Contenuto: URL `{URL_BASE}/q/{asset_tag}` → la fotocamera del telefono apre la scheda
    direttamente. `URL_BASE` da impostazioni/env `PUBLIC_BASE_URL`, altrimenti l'URL della richiesta.
  - Lo scanner interno riconosce: URL `/q/...`, asset tag nudo, seriale, codice oggetto.
  - Per le scorte, la scansione apre la scheda con +/− in evidenza.
- **Etichette stampabili** (SVG da `segno`, stampa dal browser con `@page`): formati
  25×25 mm (solo QR + tag), 50×25 mm (QR + tag + nome + categoria), foglio A4 a griglia.
  Selezione da lista, da posizione (tutto il contenuto) o singola scheda.
- **Campi per categoria tipizzati** (testo, numero con unità, scelta, sì/no, data) con template
  predefiniti: RAM, SSD, HDD, CPU, GPU, Scheda madre, Alimentatore, **Cavo** (tipo, connettore A,
  connettore B, lunghezza m, standard/versione es. HDMI 2.1, colore), Scheda di rete, Ventola.
  I template predefiniti usano come `key` le etichette storiche già presenti in `app.js`.
  Filtri in lista generati dai campi filtrabili (numero: min/max; scelta: valori).
  Gli attributi liberi esistenti restano visibili e modificabili.
- **Foto e allegati** su componenti, test, incidenti, changelog: immagini (jpg/png/webp/gif),
  pdf, txt/log/json/csv. Max 25 MB. Immagini: rotazione EXIF, **rimozione metadati (GPS)**,
  miniatura 400 px. SVG e HTML non ammessi. Scatto diretto da fotocamera su telefono.
- **Acquisto e garanzia**: fornitore, data, prezzo, garanzia fino a, riferimento fattura.
  Avviso 30 giorni prima della scadenza garanzia. Valore totale magazzino in dashboard.
- **Stati**: A magazzino, Da testare, Testato OK, In uso, Riservato, In riparazione, In RMA,
  Guasto, Dismesso, Venduto. I valori esistenti (`stock`, `in_use`, `faulty`, `retired`)
  restano validi. Ogni stato ha testo + colore (mai solo colore).
- **Modifica di massa**: selezione multipla in lista (anche da scansione a raffica) →
  sposta in posizione/macchina, cambia stato, aggiungi tag, stampa etichette, elimina (critica).
- **Scanner**: `BarcodeDetector` nativo, oppure polyfill vendorizzato basato su zxing-wasm
  (iOS Safari). **Modalità a raffica**: scansioni continue con vibrazione e suono, elenco dei
  letti, azione finale (seleziona per modifica di massa, aggiungi a inventario, sposta qui).
- **Ricerca globale Ctrl+K** (e icona su mobile): componenti, posizioni, macchine, servizi,
  incidenti, changelog, operatori; navigazione da tastiera. Implementazione `LIKE` su campi
  indicizzati + attributi; FTS5 solo se diventa lenta.
- **Tag** liberi con filtro.
- **Duplica** (esistente) mantenuto e allineato: azzera seriale, codice oggetto e asset tag.
- **Import/export CSV**: export di tutti i campi + attributi appiattiti; import con anteprima,
  prova a secco, corrispondenza per asset tag o seriale (aggiorna) o nuova riga (crea).
- **Progetti/build**: prenota componenti per una build (stato Riservato o quantità prenotata),
  "Completa build" → pezzi seriali montati sulla macchina obiettivo, scorte scalate, movimenti registrati.

## 10. Verifica e test

- **Registro test** per componente: modello di test, esito (OK / Fallito / Parziale / Non concluso),
  valori misurati, checklist, strumento usato, note, allegati (screenshot, log), operatore e firma.
- **Modelli di test per categoria** (predefiniti, modificabili):
  GPU (strumento, durata min, temp max °C, artefatti, crash), RAM (MemTest86: passate, errori),
  SSD/HDD (SMART: ore accensione, settori riallocati, salute %; lettura/scrittura MB/s),
  CPU (punteggio benchmark, temp max), Alimentatore (tensioni 12 V/5 V/3,3 V),
  Cavo (continuità, segnale: risoluzione/frequenza o velocità), Scheda di rete (iperf Mbps),
  Ventola (RPM). I campi con min/max propongono l'esito; l'operatore conferma.
- Badge "Ultimo test: OK · 12/11/2026" su scheda e lista. Dopo un test OK su un pezzo "Da testare"
  si propone lo stato "Testato OK"; dopo un test fallito si propone "Guasto" ed evento `test.failed`.
- **Coda "Da testare"** in dashboard e pagina dedicata.
- **Inventario fisico**: scegli posizione (con sottoposizioni) → elenco atteso → scansioni →
  trovati / mancanti / fuori posto (con "sposta qui") → chiusura firmata, `last_audit_at` aggiornato.
  Intervallo di verifica configurabile (default 180 giorni) → elenco posizioni da verificare.

## 11. Centro di comando

- **Server → Servizi → Moduli**. Il server è una `machine` (tipo server). Un servizio (Immich,
  Jellyfin, un bot Discord…) ha moduli (app web, app PC, app Android/iOS, bot, API, worker, DB)
  con versione corrente e repo GitHub.
- **Stato servizio** (standard delle status page): Operativo, Degradato, Disservizio parziale,
  Disservizio grave, Manutenzione. Calcolato da incidenti aperti, health check e manutenzioni;
  modificabile a mano.
- **Changelog** per servizio/modulo: rilascio, aggiornamento, fix, debug, funzione, configurazione,
  rollback, nota. Corpo in markdown, link multipli, allegati. Pubblicazione opzionale su Discord.
- **Link GitHub** riconosciuti (commit, PR, issue, release, repo) con anteprima: titolo, stato
  (aperta/chiusa/unita), autore, data. API GitHub con cache di 1 ora e `ETag`; `GITHUB_TOKEN`
  facoltativo per alzare i limiti.
- **Incidenti**: gravità SEV1–SEV4, servizi colpiti, stati Aperto → In analisi → Identificato →
  Monitoraggio → Risolto, cronologia di aggiornamenti (ognuno pubblicabile su Discord), causa,
  post-mortem in markdown, collegamento a problemi noti.
- **Problemi noti**: problema ricorrente con workaround, collegato a servizi e incidenti.
- **Manutenzioni programmate**: inizio/fine, servizi coinvolti; il worker le avvia e le chiude
  all'orario e invia gli eventi.
- **Health check**: HTTP(S) (codice atteso, timeout, parola chiave facoltativa) o TCP, intervallo
  default 60 s (minimo 30 s). 3 fallimenti di fila → servizio "Disservizio grave" e **incidente
  automatico** SEV3 (uno solo aperto per servizio). 2 successi di fila → aggiornamento "Ripristinato"
  e incidente in Monitoraggio; risolto dopo 10 minuti stabili. Disponibilità 24 h / 7 g / 30 g.
  Destinazioni tipiche: nome container Docker sulla rete Umbrel o IP del server.
- **Runbook** per servizio (markdown): come riavviare, porte, dipendenze, dove sono i log.
  Avviso fisso: non inserire password.
- **Pagina di stato** `/status` in sola lettura: servizi, incidenti attivi, manutenzioni,
  barre di disponibilità 30 giorni. Resta dietro il login Umbrel (vedi 15).

## 12. Notifiche Discord (e webhook generici)

- Più webhook, ognuno con: tipo (Discord o JSON generico, per n8n), eventi scelti, gravità minima,
  servizi filtrati, ruolo da menzionare solo per SEV1, nome e avatar facoltativi.
- Eventi: `incident.opened`, `incident.updated`, `incident.resolved`, `maintenance.scheduled`,
  `maintenance.started`, `maintenance.completed`, `change.published`, `healthcheck.down`,
  `healthcheck.up`, `stock.low`, `warranty.expiring`, `test.failed`, `audit.completed`.
- Embed Discord: titolo `[SEV2] Titolo`, colore per gravità/evento nella palette costruttivista
  (SEV1 rosso `#e2231a`, SEV2 arancio, SEV3 giallo `#f4c20d`, SEV4 grigio, risolto verde scuro),
  campi Stato / Servizi / Operatore / Inizio, link alla pagina se `URL_BASE` è impostato.
- `allowed_mentions` vuoto di default: **mai `@everyone`/`@here`**; solo il ruolo configurato per SEV1.
- Invio tramite **outbox** + worker: tentativi con attesa crescente (fino a 8), rispetto di
  `429 retry_after`, stato finale "dead" visibile. Registro invii 30 giorni. Pulsante **"Invia test"**.
- URL Discord accettati solo `https://discord.com/api/webhooks/...` (o `discordapp.com`);
  mostrati mascherati in interfaccia.

## 13. Integrazioni

- **Polling release GitHub**: per ogni modulo con repo, ogni 6 ore (ETag); una release nuova crea
  una voce di changelog automatica (tipo Rilascio) e l'evento `change.published`.
- **Webhook GitHub in entrata** `/hooks/github` con firma HMAC (`X-Hub-Signature-256`): pronto ma
  utilizzabile solo quando il server sarà esposto (richiede `PROXY_AUTH_WHITELIST`); documentato.
- **API REST `/api/v1`** con token Bearer (salvati come hash, mostrati una sola volta, scope
  lettura/scrittura): componenti, posizioni, ricerca, servizi, changelog (POST), incidenti e
  aggiornamenti (POST), test (POST). Documentazione OpenAPI su `/api/docs`. Scritture registrate
  nell'audit log come attore `api`.
- **Import app da Umbrel**: vedi domanda aperta in 17.

## 14. UX, accessibilità, PWA

- Stile: stessi token, font, ombre piene, blocchi geometrici. Nuovi componenti (pannello firma,
  palette, scanner a raffica, timeline incidenti, badge stato servizio) disegnati con lo stesso linguaggio.
- **WCAG 2.2 AA**: skip link, landmark, gerarchia titoli, `<label>` su tutti i campi, errori
  collegati con `aria-describedby`, messaggi flash in `aria-live`, focus visibile ad alto contrasto,
  trappola del focus nei pannelli + `Esc`, nessun `alert()`/`confirm()` nativo (pannelli propri),
  target tocco ≥ 44 px, `prefers-reduced-motion`. Contrasto: il rosso `#e2231a` su carta per testo
  piccolo va sostituito con `--red-dark` (verifica di tutte le coppie di colori).
- Tabelle → schede su mobile. Campi con `inputmode`, `enterkeyhint`, `autocomplete="off"` su seriali.
- **Barra in basso su mobile**: Home · Cerca · **Scan** (grande, rosso) · Incidenti · Menu.
- **Tema scuro** costruttivista (nero/carta/rosso) automatico con interruttore manuale.
- **PWA installabile**: manifest (`crossorigin="use-credentials"` per il login Umbrel), icone
  192/512 maskable, service worker con cache della grafica e pagina "Offline"; nessuna scrittura offline.
- **Dashboard centro di comando**: stato servizi, incidenti aperti per gravità, manutenzioni
  imminenti, scorte basse, coda da testare, garanzie in scadenza, inventari in ritardo, valore
  magazzino, attività recente (audit log).

## 15. Deploy e release

Lavoro su branch `dev/v2`; ogni fase viene unita a `main` e taggata. Ogni release aggiorna anche
`Gigio-dany-appstore/g-d-app-store-gd-magazzino` (versione, immagine, note di rilascio).

| Release | Contenuto |
|---|---|
| **v1.2.0 — Fondamenta** | Password rimossa, login Umbrel obbligatorio, migrazioni + backup pre-migrazione, backup giornaliero, backup/ripristino da UI, soft delete, CSRF, header sicurezza, `lifespan`, prime correzioni accessibilità (niente `alert()`, focus, contrasto, skip link), test + CI |
| **v1.3.0 — Firma e tracciabilità** | Operatori, prima firma con registrazione, passkey + password, sessione di firma, azioni critiche, audit log con catena di hash |
| **v1.4.0 — Catalogo e verifica** | Sezioni 9 e 10, barra mobile, tema scuro, PWA, ricerca Ctrl+K |
| **v2.0.0 — Centro di comando** | Sezioni 11, 12, 13 |

Compose Umbrel dalla v1.2.0:
```yaml
services:
  app_proxy:
    environment:
      APP_HOST: g-d-app-store-gd-magazzino_magazzino_1
      APP_PORT: 8000
      PROXY_AUTH_ADD: "true"
  magazzino:
    image: ghcr.io/gigiomiccio425/magazzino-zimaos:1.2.0
    restart: on-failure
    environment:
      APP_NAME: MAGAZZINO
      TZ: Europe/Rome
      DATA_DIR: /data
    volumes:
      - ${APP_DATA_DIR}/data:/data
```

CI: il workflow GitHub esegue `pytest` prima di build e push; immagine pubblicata solo se i test passano.
Il `docker-compose.yml` standalone (ZimaOS) viene allineato: niente `APP_PASSWORD`, nota che
senza password l'app va tenuta dietro un proxy con autenticazione.

## 16. Strategia di test

- `pytest` + `TestClient`. Fixture DB generata con i modelli v1.1.1 e dati di esempio (componenti
  con attributi, macchine, movimenti, posizioni testo), salvata nei test.
- Migrazioni: da v1.1.1 a ogni versione → valori originali identici, backfill corretti, backup creato,
  schema allineato ai modelli ORM (ogni colonna ORM esiste nel DB).
- Firma: registrazione e firma con password; WebAuthn verificato simulando il confine della libreria;
  scadenza sessione; azioni critiche monouso; blocco dopo tentativi errati.
- Audit: catena di hash valida, alterazione rilevata.
- Discord: costruzione payload, nessuna menzione di default, tentativi e `429`.
- Health check: macchina a stati (3 fallimenti → incidente, 2 successi → monitoraggio, 10 min → risolto).
- CSV andata/ritorno, backup/ripristino, QR e risoluzione `/q/{tag}`, upload (rimozione EXIF, tipi rifiutati).
- Controllo manuale nel browser (desktop + telefono) prima di ogni release.

## 17. Decisioni prese da Claude (da controllare)

1. Approccio A (evoluzione dell'app attuale), nessuna riscrittura.
2. Ordine delle release: firma e audit **prima** di catalogo e centro comando, perché tutte le
   funzioni successive devono sapere chi ha fatto cosa.
3. Sessione di firma di 10 minuti (configurabile; 0 = firma a ogni modifica) + firma nuova per le azioni critiche.
4. Primo operatore creato = admin. Chiunque arrivi al pannello può creare un operatore nuovo
   (fiducia al primo uso); l'admin può disattivarlo.
5. Password operatore: minimo 6 caratteri, cifre ammesse.
6. Soft delete con cestino al posto delle eliminazioni definitive.
7. Pagina `/status` dietro il login Umbrel (login obbligatorio come richiesto); si può esporre in
   seguito con `PROXY_AUTH_WHITELIST`.
8. Webhook GitHub in entrata pronto ma non attivo finché il server non è esposto; il polling delle
   release copre il caso attuale.
9. QR con URL completo (`/q/{tag}`) per aprire la scheda anche dalla fotocamera di sistema.
10. Rimozione dei metadati EXIF/GPS dalle foto.
11. Nessun ripristino automatico in caso di migrazione fallita: l'app si ferma e il file resta intatto.

**Domanda aperta per l'utente — Import app da Umbrel (funzione 27).**
Dall'interno del container non si vede l'elenco delle app Umbrel. L'unico modo affidabile è dare
accesso in **sola lettura** all'API Docker tramite un piccolo proxy (`docker-socket-proxy`, solo
endpoint container). Vantaggio: elenco servizi importato da solo + stato reale dei container
(avviato/fermo/riavvii) nel centro di comando. Rischio: quell'endpoint espone anche le variabili
d'ambiente degli altri container (che possono contenere segreti). Alternativa senza rischio:
inserimento manuale dei servizi con suggerimenti. Va deciso prima della v2.0.0.

## 18. Lasciato a chi costruisce

- Versioni esatte delle dipendenze e del polyfill scanner (stabili, ≥ 2 settimane).
- Disposizione precisa delle pagine nuove, nel rispetto dello stile e della sezione 14.
- Struttura interna di `services/` e dei template parziali.
- Testi dei messaggi e delle etichette in italiano.
- Indici DB necessari per le liste e la ricerca.
