# Changelog

## 2.3.0 — 2026-11

- Modelli pronti: 209 modelli fra RAM da DDR1 a DDR5 (soprattutto Kingston ValueRAM, HyperX e FURY,
  poi Corsair, Crucial, G.Skill, Samsung, SK Hynix), CPU, SSD, dischi, schede video e alimentatori. Nel nuovo
  componente si cercano per nome o sigla e compilano il modulo (caratteristiche comprese).
- Riconoscimento del modello: scansionando l'etichetta del pezzo (QR o codice a barre) la sigla viene
  riconosciuta anche dentro altro testo; se non è in elenco viene decodificata dalle regole di sigla
  delle marche principali. Dallo scanner generale, un modello non ancora in magazzino propone
  "Nuovo componente".
- Scanner: quando QR e codici a barre sono vicini lo scanner si ferma, li numera sull'immagine e fa
  scegliere quello giusto; torcia e zoom dove il telefono li supporta; risoluzione più alta; a tutto
  schermo sul telefono.
- Seriale di magazzino (es. RAM-KIN-D4-16G-0007) e codice di riferimento unico (GD-XXXX-XXXX con
  cifra di controllo) generati in automatico per ogni componente, anche per quelli già presenti;
  si trovano con la ricerca e con lo scanner.
- Tag automatici dalle specifiche alla creazione (categoria, marca, tipo, capacità, velocità, formato...).
- Telefono e tablet: menu a scomparsa fino a 1024 px con ricerca nel menu, pulsante di chiusura e
  sfondo scuro; bersagli da 48 px al tocco e campi a 16 px; barra in basso Home, Pezzi, Scansiona,
  Stampa (con il numero di etichette in coda), Menu.
- Tipi RAM da DDR a DDR5 (anche SO-DIMM) nella categoria RAM (migrazione 5: solo aggiunte).

## 2.2.0 — 2026-11

Nuovo design e zona stampa etichette.
- Stile "Banco + Etichetta": barra laterale chiara, ricerca e "Scansiona etichetta" sempre in alto,
  giallo sicurezza per le azioni principali, rosso solo per guasti e incidenti, titoli stretti,
  codici in monospace. Tema scuro e telefono aggiornati. Font Archivo e DM Mono inclusi nell'app (licenza OFL).
- Zona stampa (menu "Stampa etichette"): coda con più pezzi insieme; per ognuno si sceglie
  etichetta 70 × 37 mm, solo QR o bandiera per cavi, e il numero di copie.
- Foglio unico ottimizzato (predefinito): su carta adesiva A4 intera etichette, QR e bandiere
  finiscono insieme sullo stesso foglio, dal più grande al più piccolo, riempiendo ogni spazio
  libero con 2 mm per il taglio: meno fogli sprecati. In alternativa, fogli pretagliati per formato
  con "parti dalla casella" per riusare fogli già iniziati. Anteprima A4, linee di taglio,
  stampa di tutti i fogli in una volta (o "Salva come PDF").
- Bandiera per cavi: lato A, zona di giro e lato B con QR su entrambe le facce; la zona di giro si
  calcola dal diametro del cavo. I cavi entrano in coda già come bandiera.
- "Aggiungi alla stampa" dalla selezione multipla dei componenti e dalle schede di componenti,
  posizioni e macchine. La coda resta salvata (migrazione 4: solo una tabella nuova).
- La barra laterale resta allo stesso punto quando si cambia pagina e mostra sempre la voce aperta.
- Mobile: nelle tabelle trasformate in schede i valori tornano visibili.
- Dashboard: le etichette dell'attività recente non si allargano più a tutta la riga.

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
