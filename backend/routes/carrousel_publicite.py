"""Lot 193 — Créer une PUBLICITÉ À CARROUSEL « Click-to-WhatsApp » (compte publicitaire Meta) depuis un envoi de carrousels.

Demande du propriétaire : « branche la publicité à carrousel » — le compte publicitaire est déjà paramétré dans l'intégration
Meta (Paramètres → Intégration Meta : comptes publicitaires, Pages, jeton avec le droit ads_management).

Ce que fait SAWALI à partir d'un envoi (cartes = images, titres, textes) :
  1. campagne (objectif OUTCOME_ENGAGEMENT) → 2. ensemble de publicités (destination WHATSAPP, objectif CONVERSATIONS,
  budget journalier, pays, âges) → 3. créatif carrousel (une carte par carte, bouton « Envoyer un message WhatsApp ») →
  4. publicité. TOUT est créé EN PAUSE : aucune dépense tant que l'administrateur n'a pas activé, après confirmation.
  En cas d'échec en cours de route, ce qui a déjà été créé est supprimé (aucune campagne orpheline).
Les réponses des personnes qui cliquent arrivent sur WhatsApp, où Liluvine répond comme pour toute autre conversation.
Chaque publicité créée est consignée sur l'envoi (`carrousel_campagnes.publicites_facebook`) : aucune nouvelle collection.
Le jeton Meta reste sur le serveur. La structure de l'API de Meta est suivie d'après sa documentation ; ses messages d'erreur
sont renvoyés tels quels pour pouvoir corriger un réglage (budget minimal, droits, Page non liée à WhatsApp…).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException

logger = logging.getLogger("sawali.carrousel.publicite")

GRAPH_BASE = "https://graph.facebook.com"
DEFAULT_GRAPH_VERSION = "v20.0"
CARTES_MIN, CARTES_MAX = 2, 10          # limites d'un carrousel publicitaire Meta
# Devises sans subdivision (le budget de Meta s'exprime alors en unités entières : 1 000 XOF = 1000).
DEVISES_SANS_DECIMALES = {"XOF", "XAF", "XPF", "JPY", "KRW", "VND", "CLP", "PYG", "UGX", "RWF", "GNF", "KMF", "DJF", "BIF", "ISK"}
STATUTS = ("ACTIVE", "PAUSED")


def budget_en_unites_meta(montant: Any, devise: str) -> int:
    """Budget journalier saisi (ex. 5000 XOF, 3.5 EUR) → entier attendu par Meta (centimes pour EUR / USD…). Fonction pure."""
    try:
        v = float(str(montant).replace(",", ".").strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Budget journalier invalide")
    if v <= 0:
        raise HTTPException(status_code=422, detail="Le budget journalier doit être supérieur à zéro")
    return int(round(v if str(devise or "").upper() in DEVISES_SANS_DECIMALES else v * 100))


def ciblage(pays: Any, age_min: Any, age_max: Any) -> Dict[str, Any]:
    """Ciblage de l'ensemble de publicités : pays (codes ISO à 2 lettres séparés par des virgules) et tranche d'âge. Pure."""
    codes = [c.strip().upper() for c in (pays.split(",") if isinstance(pays, str) else (pays or [])) if str(c).strip()]
    if not codes or any(len(c) != 2 or not c.isalpha() for c in codes):
        raise HTTPException(status_code=422, detail="Pays invalide : codes à 2 lettres séparés par des virgules (ex. BF, CI)")
    try:
        a_min, a_max = int(age_min or 18), int(age_max or 65)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Âges invalides")
    if not (13 <= a_min <= a_max <= 65):
        raise HTTPException(status_code=422, detail="Âges : de 13 à 65 ans, minimum inférieur ou égal au maximum")
    return {"geo_locations": {"countries": codes}, "age_min": a_min, "age_max": a_max}


def cartes_publicitaires(cartes: List[Dict[str, Any]], remplacements: Any, lien: str) -> List[Dict[str, Any]]:
    """Cartes du créatif : image publique (remplaçable par position), titre (40 caractères), texte (90), bouton WhatsApp.
    Les cartes sans image publique sont ignorées ; 2 cartes au moins, 10 au plus. Fonction pure."""
    from routes.carrousel_facebook import images_retenues, url_publique
    sortie: List[Dict[str, Any]] = []
    rempl = list(remplacements or [])
    for i, c in enumerate(cartes or []):
        # même règle que la publication de Page : l'image de remplacement valide l'emporte
        image = images_retenues([c], [rempl[i] if i < len(rempl) else None])
        if not image:
            continue
        sortie.append({
            "link": lien, "picture": image[0],
            "name": (str((c or {}).get("titre") or "").strip() or "Découvrir")[:40],
            "description": str((c or {}).get("texte") or "").strip()[:90],
            "call_to_action": {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}},
        })
    if len(sortie) < CARTES_MIN:
        raise HTTPException(status_code=422, detail=f"Une publicité à carrousel demande au moins {CARTES_MIN} cartes avec une image publique")
    return sortie[:CARTES_MAX]


def histoire_creative(page_id: str, message: str, cartes: List[Dict[str, Any]], lien: str) -> Dict[str, Any]:
    """`object_story_spec` du créatif carrousel Click-to-WhatsApp. Fonction pure."""
    return {"page_id": page_id, "link_data": {
        "message": (message or "").strip()[:2000], "link": lien, "child_attachments": cartes,
        "multi_share_end_card": False, "multi_share_optimized": False,
        "call_to_action": {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}},
    }}


def lien_whatsapp(numero: Any) -> str:
    """Adresse d'ouverture de WhatsApp (avec le numéro si donné, sinon générique : numéro lié à la Page). Pure."""
    chiffres = "".join(ch for ch in str(numero or "") if ch.isdigit())
    return f"https://api.whatsapp.com/send?phone={chiffres}" if chiffres else "https://api.whatsapp.com/send"


def lien_gestionnaire(compte_id: str, campagne_id: str) -> str:
    """Lien d'ouverture de la campagne dans le Gestionnaire de publicités. Pure."""
    num = str(compte_id or "").replace("act_", "")
    return f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={num}&selected_campaign_ids={campagne_id}"


async def _integration(db, user: Dict[str, Any]) -> Dict[str, Any]:
    """Intégration Meta du compte de l'administrateur (jeton, Pages, comptes publicitaires)."""
    tid = user.get("client_id") or user.get("id")
    doc = await db.meta_integrations.find_one({"tenant_id": tid}, {"_id": 0})
    if not doc or not (doc.get("meta_user") or {}).get("long_lived_user_access_token"):
        raise HTTPException(status_code=400, detail="Meta n'est pas connecté pour ce compte : Paramètres → Intégration Meta, "
                                                    "avec le module Publicités (ads_management)")
    return doc


async def _version(db) -> str:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "meta_graph_version": 1}) or {}
    return (s.get("meta_graph_version") or DEFAULT_GRAPH_VERSION).strip()


async def _graph(db, chemin: str, jeton: str, donnees: Dict[str, Any]) -> Dict[str, Any]:
    """POST sur l'API de Meta ; l'erreur de Meta est renvoyée en clair (message destiné à l'utilisateur d'abord)."""
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(f"{GRAPH_BASE}/{await _version(db)}/{chemin}", data={**donnees, "access_token": jeton})
    if r.status_code >= 400:
        try:
            err = (r.json() or {}).get("error") or {}
        except Exception:  # noqa: BLE001
            err = {}
        detail = err.get("error_user_msg") or err.get("message") or r.text[:300]
        raise HTTPException(status_code=502, detail=f"Meta : {detail}" + (f" (code {err.get('code')})" if err.get("code") else ""))
    return r.json()


async def creer_publicite(db, user: Dict[str, Any], campagne: Dict[str, Any], corps: Dict[str, Any]) -> Dict[str, Any]:
    """Crée campagne + ensemble + créatif + publicité (EN PAUSE), supprime ce qui a été créé en cas d'échec, consigne la trace."""
    integ = await _integration(db, user)
    jeton = integ["meta_user"]["long_lived_user_access_token"]
    compte = next((a for a in integ.get("ads_accounts") or [] if str(a.get("id")) == str(corps.get("compte_id"))), None)
    if not compte:
        raise HTTPException(status_code=404, detail="Compte publicitaire inconnu : choisissez-en un dans la liste")
    page = next((p for p in integ.get("pages") or [] if str(p.get("page_id")) == str(corps.get("page_id"))), None)
    if not page:
        raise HTTPException(status_code=404, detail="Page inconnue : choisissez-en une dans la liste")
    devise = str(compte.get("currency") or "")
    budget = budget_en_unites_meta(corps.get("budget"), devise)
    cible = ciblage(corps.get("pays"), corps.get("age_min"), corps.get("age_max"))
    numero = "".join(ch for ch in str(corps.get("whatsapp") or "") if ch.isdigit())
    cartes = cartes_publicitaires(campagne.get("cartes") or [], corps.get("images"), lien_whatsapp(numero))
    nom = (str(corps.get("nom") or "").strip() or f"Carrousel {campagne.get('id', '')[:6]}")[:120]
    try:
        jours = int(corps.get("jours") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Durée invalide")
    objet = {"page_id": str(page["page_id"])}
    if numero:
        objet["whatsapp_phone_number"] = f"+{numero}"
    ids: Dict[str, str] = {}
    act = str(compte["id"]) if str(compte["id"]).startswith("act_") else f"act_{compte['id']}"
    try:
        ids["campagne"] = (await _graph(db, f"{act}/campaigns", jeton, {
            "name": nom, "objective": "OUTCOME_ENGAGEMENT", "status": "PAUSED", "special_ad_categories": "[]"}))["id"]
        ensemble = {
            "name": f"{nom} — ensemble", "campaign_id": ids["campagne"], "daily_budget": budget,
            "billing_event": "IMPRESSIONS", "optimization_goal": "CONVERSATIONS", "destination_type": "WHATSAPP",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "promoted_object": json.dumps(objet),
            "targeting": json.dumps(cible), "status": "PAUSED",
        }
        if jours > 0:
            ensemble["end_time"] = (datetime.now(timezone.utc) + timedelta(days=jours)).strftime("%Y-%m-%dT%H:%M:%S+0000")
        ids["ensemble"] = (await _graph(db, f"{act}/adsets", jeton, ensemble))["id"]
        ids["creatif"] = (await _graph(db, f"{act}/adcreatives", jeton, {
            "name": f"{nom} — créatif",
            "object_story_spec": json.dumps(histoire_creative(str(page["page_id"]), str(corps.get("message") or campagne.get("message") or ""),
                                                              cartes, lien_whatsapp(numero)))}))["id"]
        ids["publicite"] = (await _graph(db, f"{act}/ads", jeton, {
            "name": f"{nom} — publicité", "adset_id": ids["ensemble"], "creative": json.dumps({"creative_id": ids["creatif"]}),
            "status": "PAUSED"}))["id"]
    except HTTPException:
        if ids.get("campagne"):      # aucune campagne orpheline : la suppression emporte l'ensemble déjà créé
            try:
                await _graph(db, ids["campagne"], jeton, {"status": "DELETED"})
            except Exception:  # noqa: BLE001
                logger.warning("[publicite] nettoyage de la campagne %s impossible", ids["campagne"], exc_info=True)
        raise
    trace = {"id": uuid.uuid4().hex, "compte_id": act, "compte_nom": compte.get("name"), "page_id": str(page["page_id"]),
             "page_nom": page.get("name"), "campagne_meta": ids["campagne"], "ensemble_meta": ids["ensemble"],
             "creatif_meta": ids["creatif"], "publicite_meta": ids["publicite"], "budget_jour": budget, "devise": devise,
             "pays": cible["geo_locations"]["countries"], "nb_cartes": len(cartes), "statut": "PAUSED",
             "par": user.get("email") or user.get("id") or "admin", "le": datetime.now(timezone.utc).isoformat()}
    await db.carrousel_campagnes.update_one({"id": campagne["id"]}, {"$push": {"publicites_facebook": trace}})
    return {**trace, "gestionnaire": lien_gestionnaire(act, ids["campagne"])}


def attach_carrousel_publicite_routes(*, api, db, get_current_admin):
    """Routes d'administration : configuration, création (en pause), changement de statut, historique."""

    @api.get("/admin/carrousel/publicite/config", tags=["Admin — Carrousel WhatsApp"])
    async def config_publicite(user: dict = Depends(get_current_admin)):
        """Comptes publicitaires et Pages de l'intégration Meta (jamais de jeton)."""
        integ = await _integration(db, user)
        return {"comptes": [{"id": a.get("id"), "nom": a.get("name"), "devise": a.get("currency"), "statut": a.get("status")}
                            for a in integ.get("ads_accounts") or []],
                "pages": [{"id": p.get("page_id"), "nom": p.get("name")} for p in integ.get("pages") or []]}

    @api.get("/admin/carrousel/{cid}/publicite", tags=["Admin — Carrousel WhatsApp"])
    async def historique_publicites(cid: str, _: dict = Depends(get_current_admin)):
        c = await db.carrousel_campagnes.find_one({"id": cid}, {"_id": 0, "publicites_facebook": 1}) or {}
        return {"publicites": [{**p, "gestionnaire": lien_gestionnaire(p.get("compte_id"), p.get("campagne_meta"))}
                               for p in reversed(c.get("publicites_facebook") or [])]}

    @api.post("/admin/carrousel/{cid}/publicite", tags=["Admin — Carrousel WhatsApp"])
    async def creer(cid: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Crée la publicité à carrousel EN PAUSE : {compte_id, page_id, budget, pays, age_min, age_max, jours, whatsapp,
        nom, message, images:[url|null…]}."""
        c = await db.carrousel_campagnes.find_one({"id": cid}, {"_id": 0, "id": 1, "cartes": 1, "message": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Envoi introuvable")
        return await creer_publicite(db, user, c, corps)

    @api.post("/admin/carrousel/{cid}/publicite/statut", tags=["Admin — Carrousel WhatsApp"])
    async def statut(cid: str, corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_admin)):
        """Active ou met en pause une campagne créée depuis CET envoi : {campagne_meta, statut}. L'activation commence la dépense."""
        nouveau = str(corps.get("statut") or "").upper()
        if nouveau not in STATUTS:
            raise HTTPException(status_code=422, detail="Statut : ACTIVE ou PAUSED")
        c = await db.carrousel_campagnes.find_one({"id": cid}, {"_id": 0, "publicites_facebook": 1}) or {}
        trace = next((p for p in c.get("publicites_facebook") or [] if p.get("campagne_meta") == corps.get("campagne_meta")), None)
        if not trace:
            raise HTTPException(status_code=404, detail="Cette campagne n'a pas été créée depuis cet envoi")
        integ = await _integration(db, user)
        jeton = integ["meta_user"]["long_lived_user_access_token"]
        # la campagne, son ensemble de publicités et la publicité changent ensemble de statut
        for objet in (trace["campagne_meta"], trace["ensemble_meta"], trace["publicite_meta"]):
            await _graph(db, objet, jeton, {"status": nouveau})
        await db.carrousel_campagnes.update_one({"id": cid, "publicites_facebook.campagne_meta": trace["campagne_meta"]},
                                                {"$set": {"publicites_facebook.$.statut": nouveau}})
        return {"campagne_meta": trace["campagne_meta"], "statut": nouveau}
