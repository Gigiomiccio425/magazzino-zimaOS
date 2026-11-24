# Changelog

## 2.0.3 — 2026-11

- Dopo un salvataggio la pagina resta dove eri, invece di tornare in cima; i messaggi di conferma
  compaiono come avviso in basso.
- Su PC la barra laterale resta ferma e scorre per conto suo: non allunga più la pagina.
  Menu più compatto.
- Filtri dei componenti su una riga sola.
- CSS e JS con l'impronta del contenuto nell'indirizzo: dopo un aggiornamento il browser usa subito
  la versione nuova.

## 2.0.2 — 2026-11

- Servizi: nuova pagina "Importa" per creare in un colpo solo i servizi di un server (per esempio
  tutte le app di Umbrel) da un file JSON, con moduli e macchina collegata.
  I servizi già presenti non vengono modificati (al massimo collegati alla macchina se non ne hanno una),
  la macchina viene creata solo se manca, niente viene cancellato. Richiede la firma per azioni importanti.

## 2.0.1 — 2026-11

Correzioni dalla revisione della 2.0.0.
- Import CSV: una macchina inesistente ora è un errore in anteprima (prima smontava il pezzo in silenzio);
  gli attributi restano testo ("007" non diventa 7).
- Export CSV protetto dalle formule di Excel (celle che iniziano con = + - @).
- Cambio di stato di massa con la stessa regola della scheda ("In uso" solo se montato).
- Webhook gestibili solo dagli amministratori.
- Firma: un token di azione importante non si riusa neanche ripresentando un cookie vecchio; "Esci" non si annulla.
- Impronta: una credenziale sconosciuta viene sempre rifiutata.
- Date scritte male, immagini enormi e allegati verso elementi inesistenti: messaggio chiaro invece di errore 500;
  nessun file orfano se un caricamento viene rifiutato.
- Nomi operatore con accenti scritti in modi diversi riconosciuti come lo stesso operatore.
- Un database di una versione più recente dell'app viene rifiutato invece di essere aperto.

## 2.0.0 — 2026-11

Gestionale e centro di comando completo. I dati della 1.1.x vengono migrati in automatico,
con backup del database prima della migrazione.

### Accesso e sicurezza
- Rimossa la password dell'app (era rotta su Umbrel per un conflitto con la variabile `APP_PASSWORD`).
  Su Umbrel l'accesso è protetto dal login Umbrel.
- Operatori con nome: alla prima firma si registra l'impronta/passkey e/o una password.
- Ogni modifica è firmata. Le azioni importanti (eliminazioni, ripristini, impostazioni, webhook,
  operatori) chiedono sempre una firma nuova.
- Audit log di tutte le modifiche con catena di hash e pagina di verifica integrità.
- Protezione CSRF, Content-Security-Policy, nessuna risorsa da CDN.

### Magazzino
- Articoli a seriale o a quantità (scorte, scorta minima, variazioni con motivo).
- Posizioni ad albero (stanza › scaffale › box) e QR su ogni prodotto, posizione e macchina.
- Etichette stampabili (25×25, 50×25, A4).
- Campi per categoria con filtri (es. VRAM ≥ 8 GB, cavo HDMI 2 m).
- Foto e allegati (metadati GPS rimossi), dati di acquisto e garanzia, tag, stati estesi.
- Scanner con fotocamera anche su iPhone, modalità a raffica.
- Modifica di massa, import/export CSV, progetti/build con prenotazione dei pezzi, cestino.

### Verifica
- Registro test con modelli per categoria ed esito suggerito.
- Inventari fisici per posizione: trovati, mancanti, fuori posto.

### Centro di comando
- Servizi, moduli (app PC, app telefono, bot, API) con versione, changelog con link GitHub.
- Incidenti con gravità, cronologia e post-mortem; problemi noti; manutenzioni programmate.
- Pagina di stato.
- Avvisi Discord (o webhook JSON) solo quando un operatore spunta "Pubblica su Discord".

### Interfaccia
- Dashboard centro di comando, ricerca globale Ctrl+K, tema scuro, barra in basso su mobile,
  app installabile (PWA), accessibilità WCAG 2.2 AA.

### Backup
- Backup automatico prima di ogni aggiornamento e ogni notte alle 03:00 (14 conservati).
- Export zip completo e ripristino dall'interfaccia.
