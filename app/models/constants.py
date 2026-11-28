"""Codici e etichette (italiano) usati da modelli, form e template."""

STATUS_STOCK = "stock"
STATUS_TO_TEST = "to_test"
STATUS_TESTED_OK = "tested_ok"
STATUS_IN_USE = "in_use"
STATUS_RESERVED = "reserved"
STATUS_REPAIR = "repair"
STATUS_RMA = "rma"
STATUS_FAULTY = "faulty"
STATUS_RETIRED = "retired"
STATUS_SOLD = "sold"

STATUSES = {
    STATUS_STOCK: "A magazzino",
    STATUS_TO_TEST: "Da testare",
    STATUS_TESTED_OK: "Testato OK",
    STATUS_IN_USE: "In uso",
    STATUS_RESERVED: "Riservato",
    STATUS_REPAIR: "In riparazione",
    STATUS_RMA: "In RMA",
    STATUS_FAULTY: "Guasto",
    STATUS_RETIRED: "Dismesso",
    STATUS_SOLD: "Venduto",
}

TRACKING = {"serial": "A seriale", "quantity": "A quantità"}

LOCATION_KINDS = {
    "stanza": "Stanza", "scaffale": "Scaffale", "ripiano": "Ripiano",
    "box": "Box", "cassetto": "Cassetto", "altro": "Altro",
}

FIELD_TYPES = {"text": "Testo", "number": "Numero", "choice": "Scelta", "bool": "Sì/No", "date": "Data"}

SEVERITIES = {"SEV1": "Critico", "SEV2": "Alto", "SEV3": "Medio", "SEV4": "Basso"}

INCIDENT_STATUSES = {
    "open": "Aperto", "investigating": "In analisi", "identified": "Identificato",
    "monitoring": "Monitoraggio", "resolved": "Risolto",
}

SERVICE_STATUSES = {
    "operational": "Operativo", "degraded": "Degradato", "partial_outage": "Disservizio parziale",
    "major_outage": "Disservizio grave", "maintenance": "Manutenzione",
}

CHANGE_TYPES = {
    "release": "Rilascio", "update": "Aggiornamento", "fix": "Fix", "debug": "Debug",
    "feature": "Funzione", "config": "Configurazione", "rollback": "Rollback", "note": "Nota",
}

MODULE_KINDS = {
    "web": "App web", "app_pc": "App PC", "app_android": "App Android", "app_ios": "App iOS",
    "bot": "Bot", "api": "API", "worker": "Worker", "db": "Database", "altro": "Altro",
}

MAINTENANCE_STATUSES = {
    "scheduled": "Programmata", "in_progress": "In corso",
    "completed": "Completata", "cancelled": "Annullata",
}

PROBLEM_STATUSES = {"open": "Aperto", "workaround": "Workaround", "resolved": "Risolto"}

TEST_RESULTS = {"pass": "OK", "fail": "Fallito", "partial": "Parziale", "inconclusive": "Non concluso"}

PROJECT_STATUSES = {"draft": "Bozza", "building": "In costruzione", "done": "Completata", "cancelled": "Annullata"}

AUDIT_ITEM_STATES = {"expected": "Atteso", "found": "Trovato", "missing": "Mancante", "unexpected": "Fuori posto"}

EVENTS = {
    "incident.opened": "Incidente aperto",
    "incident.updated": "Incidente aggiornato",
    "incident.resolved": "Incidente risolto",
    "maintenance.scheduled": "Manutenzione programmata",
    "maintenance.started": "Manutenzione avviata",
    "maintenance.completed": "Manutenzione completata",
    "maintenance.cancelled": "Manutenzione annullata",
    "change.published": "Changelog",
    "service.status_changed": "Stato servizio",
    "stock.low": "Scorta bassa",
    "warranty.expiring": "Garanzia in scadenza",
    "maintenance.reminder": "Promemoria manutenzione",
    "order.received": "Ordine ricevuto",
    "test.failed": "Test fallito",
    "audit.completed": "Inventario completato",
    "webhook.test": "Test webhook",
}
