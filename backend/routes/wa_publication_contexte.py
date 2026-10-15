# wa_publication_contexte.py — Lot 199 : Liluvine sait à quelle publication de SAWALI le client répond.
#
# Toute publication envoyée par SAWALI (modèle WhatsApp, carrousel, formulaire, sondage, requête client, campagne…)
# peut déclencher une réponse libre : un clic sur un bouton, mais aussi une QUESTION pour comprendre. Avant, Liluvine
# répondait à l'aveugle (« pouvez-vous me préciser ce dont vous avez besoin ? »). Maintenant elle reçoit, dans ses
# consignes, le type et le titre de la publication (et un résumé) :
#   1. le message cité par le client (reply_to_message_id → wamid) est retrouvé dans les sources de SAWALI ;
#   2. sans citation : la dernière publication envoyée à ce numéro dans les 72 h (messages sortants à modèle / carrousel).
# Sources (collections EXISTANTES, lectures seules) : wa_survey_invites + wa_surveys (sondage), form_envois + forms
# (formulaire), carrousel_campagnes (carrousel), whatsapp_messages (modèle / message), liluvine_transmissions
# (plateforme externe : le journal ne garde pas le texte).
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

FENETRE_HEURES = 72          # sans citation : publication récente du même numéro
LONGUEUR_RESUME = 600


def _coupe(t: Any, n: int = 160) -> str:
    """Texte sur une ligne, raccourci."""
    return re.sub(r"\s+", " ", str(t or "")).strip()[:n]


def texte_contexte(ctx: Optional[Dict[str, Any]]) -> str:
    """Consigne ajoutée aux instructions de Liluvine (chaîne vide sans contexte). Fonction pure."""
    if not ctx:
        return ""
    ligne = f"{ctx.get('type', 'message')} « {ctx.get('titre') or 'sans titre'} »"
    resume = f"\nContenu : {ctx['resume']}" if ctx.get("resume") else ""
    intro = ("le client répond (message cité) à une publication envoyée par SAWALI : " if ctx.get("cite")
             else "la dernière publication envoyée par SAWALI à ce client (il y répond peut-être ; si sa question n'a aucun rapport, ignore ce contexte) : ")
    return (
        "\n\nCONTEXTE — " + intro + ligne + resume +
        "\n- Si son message est un simple clic de bouton ou un remerciement, remercie-le en une phrase, sans lui redemander ce dont il a besoin."
        "\n- S'il pose une question ou ne comprend pas, réponds-y à partir de cette publication (son objet, son contenu). "
        "Si tu n'as pas la réponse dans ce contenu, dis-le simplement et propose de transmettre à l'équipe : n'invente rien."
    )


async def _sondage(db, wamid: str) -> Optional[Dict[str, Any]]:
    inv = await db.wa_survey_invites.find_one({"message_id": wamid}, {"_id": 0, "survey_id": 1})
    if not inv:
        return None
    s = await db.wa_surveys.find_one({"id": inv.get("survey_id")}, {"_id": 0, "title": 1, "description": 1, "questions": 1}) or {}
    questions = " ; ".join(_coupe(q.get("label"), 80) for q in (s.get("questions") or [])[:6])
    return {"type": "sondage", "titre": s.get("title"),
            "resume": _coupe(f"{s.get('description') or ''} Questions : {questions}" if questions else s.get("description"), LONGUEUR_RESUME)}


async def _formulaire(db, wamid: str) -> Optional[Dict[str, Any]]:
    env = await db.form_envois.find_one({"destinataires.message_id": wamid}, {"_id": 0, "form_id": 1, "title": 1})
    if not env:
        return None
    f = await db.forms.find_one({"id": env.get("form_id")}, {"_id": 0, "pages": 0}) or {}
    return {"type": "formulaire", "titre": f.get("title") or env.get("title"), "resume": _coupe(f.get("description"), LONGUEUR_RESUME)}


async def _carrousel(db, wamid: str) -> Optional[Dict[str, Any]]:
    c = await db.carrousel_campagnes.find_one({"destinataires.message_id": wamid},
                                              {"_id": 0, "message": 1, "cartes": 1, "expediteur": 1, "url_presentation": 1})
    if not c:
        return None
    cartes = " ; ".join(_coupe(x.get("titre"), 50) + (f" ({_coupe(x.get('texte'), 60)})" if x.get("texte") else "")
                        for x in (c.get("cartes") or [])[:8])
    return {"type": "carrousel WhatsApp", "titre": _coupe(c.get("message"), 100),
            "resume": _coupe(f"Cartes : {cartes}" + (f". Présentation : {c['url_presentation']}" if c.get("url_presentation") else ""), LONGUEUR_RESUME)}


async def _message(db, wamid: str) -> Optional[Dict[str, Any]]:
    m = await db.whatsapp_messages.find_one({"$or": [{"wa_message_id": wamid}, {"message_id": wamid}], "direction": {"$ne": "inbound"}},
                                            {"_id": 0})
    if not m:
        return None
    texte = m.get("template_rendered_body") or m.get("body") or m.get("media_caption") or ""
    if m.get("template_name"):
        return {"type": "message modèle", "titre": m["template_name"], "resume": _coupe(texte, LONGUEUR_RESUME)}
    return {"type": "message WhatsApp", "titre": _coupe(texte, 80), "resume": _coupe(texte, LONGUEUR_RESUME)}


async def _plateforme(db, wamid: str) -> Optional[Dict[str, Any]]:
    t = await db.liluvine_transmissions.find_one({"message_id": wamid}, {"_id": 0, "emetteur": 1, "source": 1, "mode": 1})
    if not t:
        return None
    return {"type": "message d'une plateforme", "titre": t.get("emetteur") or t.get("source"),
            "resume": "Message automatique envoyé par cette plateforme (texte non conservé)."}


async def contexte_par_wamid(db, wamid: str) -> Optional[Dict[str, Any]]:
    """Publication d'origine d'un wamid : sondage, formulaire, carrousel (riches) puis message, puis plateforme."""
    for source in (_sondage, _formulaire, _carrousel, _message, _plateforme):
        trouve = await source(db, wamid)
        if trouve:
            return trouve
    return None


async def derniere_publication(db, phone_digits: str, maintenant: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Sans citation : dernier message de SAWALI à ce numéro (modèle ou carrousel) dans les 72 h, avec son contexte."""
    fin = (phone_digits or "")[-8:]
    if len(fin) < 8:
        return None
    limite = ((maintenant or datetime.now(timezone.utc)) - timedelta(hours=FENETRE_HEURES)).isoformat()
    m = await db.whatsapp_messages.find_one(
        {"direction": {"$ne": "inbound"}, "phone_digits": {"$regex": fin + "$"}, "created_at": {"$gte": limite},
         "$or": [{"template_name": {"$ne": None}}, {"carrousel_id": {"$ne": None}}]},
        {"_id": 0, "wa_message_id": 1, "message_id": 1}, sort=[("created_at", -1)])
    wamid = (m or {}).get("wa_message_id") or (m or {}).get("message_id")
    return await contexte_par_wamid(db, wamid) if wamid else None


async def contexte_reponse(db, inbound_doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Contexte pour une réponse entrante : message cité d'abord, sinon dernière publication récente. Jamais d'exception."""
    try:
        cite = inbound_doc.get("reply_to_message_id")
        if cite:
            ctx = await contexte_par_wamid(db, cite)
            if ctx:
                return {**ctx, "cite": True}
        ctx = await derniere_publication(db, inbound_doc.get("phone_digits") or "")
        return {**ctx, "cite": False} if ctx else None
    except Exception:  # noqa: BLE001 — le contexte est un plus, jamais bloquant
        return None
