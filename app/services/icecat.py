"""Scheda tecnica da Icecat (catalogo aperto), solo su richiesta dell'operatore.

Si inviano a Icecat soltanto marca e sigla del prodotto, con il nome utente gratuito impostato nelle
Impostazioni. Il risultato è una proposta: l'operatore decide cosa copiare nel modulo.
"""
import re

import httpx

API = "https://live.icecat.biz/api"
MAX_SPECS = 40


def _val(node, *path, default=""):
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node not in (None, "") else default


def parse(payload: dict) -> dict | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    info = data.get("GeneralInfo") or {}
    specs = []
    for group in data.get("FeaturesGroups") or []:
        gname = _val(group, "FeatureGroup", "Name", "Value")
        for feat in group.get("Features") or []:
            name = _val(feat, "Feature", "Name", "Value")
            value = feat.get("PresentationValue") or feat.get("Value") or ""
            if name and value:
                specs.append({"group": str(gname)[:80], "name": str(name)[:80], "value": str(value)[:160]})
            if len(specs) >= MAX_SPECS:
                break
        if len(specs) >= MAX_SPECS:
            break
    title = info.get("Title") or " ".join(x for x in [info.get("Brand"), info.get("ProductName")] if x)
    desc = _val(info, "Description", "LongDesc") or _val(info, "SummaryDescription", "ShortSummaryDescription")
    return {
        "title": str(title or "")[:200], "brand": str(info.get("Brand") or "")[:120],
        "part": str(info.get("BrandPartCode") or "")[:120],
        "description": re.sub(r"<[^>]+>", " ", str(desc or ""))[:1500].strip(),
        "image": str(_val(data, "Image", "HighPic") or _val(data, "Image", "Pic500x500") or "")[:500],
        "icecat_id": str(info.get("IcecatId") or ""),
        "specs": specs,
    }


async def lookup(http: httpx.AsyncClient, username: str, brand: str, part: str, lang: str = "it") -> dict:
    """{"found": {...}} oppure {"error": codice, "message": testo}."""
    if not username:
        return {"error": "not_configured",
                "message": "Inserisci il nome utente Icecat (account gratuito) nelle Impostazioni."}
    if not brand or not part:
        return {"error": "missing", "message": "Servono marca (produttore) e sigla (codice oggetto o modello)."}
    params = {"UserName": username, "Language": lang, "Brand": brand, "ProductCode": part}
    try:
        r = await http.get(API, params=params, timeout=12)
    except httpx.HTTPError:
        return {"error": "network", "message": "Icecat non raggiungibile: il server è collegato a internet?"}
    if r.status_code in (401, 403):
        return {"error": "auth", "message": "Icecat ha rifiutato il nome utente: controllalo nelle Impostazioni."}
    if r.status_code == 404:
        return {"error": "not_found", "message": "Prodotto non presente su Icecat."}
    try:
        found = parse(r.json())
    except ValueError:
        found = None
    if r.status_code != 200 or not found or not found["title"]:
        return {"error": "not_found", "message": "Prodotto non presente su Icecat (o dati non disponibili)."}
    return {"found": found}
