# appels_wa.py — Lot 60 : appels WhatsApp (API Calling de Meta) dans le portail SAWALI.
#
# Fonctionnement (le son passe directement entre le navigateur de l'agent et Meta, en WebRTC ;
# le serveur ne fait que relayer la « négociation » SDP et tenir le journal) :
#
#   APPEL ENTRANT (le client appelle un numéro SAWALI) :
#     1. Meta envoie au webhook un évènement « connect » avec une offre SDP → appel enregistré
#        dans db.wa_appels (statut « sonne ») ;
#     2. le portail de chaque utilisateur autorisé (même entreprise + ligne autorisée) affiche
#        « Appel entrant » (interrogation toutes les 3 s) ;
#     3. « Décrocher » : le navigateur prépare sa réponse SDP (micro), le serveur l'envoie à Meta
#        (pre_accept puis accept) — le premier qui décroche prend l'appel ;
#     4. fin d'appel : évènement « terminate » (durée fournie par Meta) → journal.
#
#   APPEL SORTANT (rappeler un client) :
#     - le client doit d'abord AUTORISER les appels : demande envoyée par message WhatsApp
#       (« call_permission_request » ; au plus 1 demande / 24 h et 2 / 7 jours par client) ;
#     - « Appeler » : le navigateur crée une offre SDP, le serveur lance l'appel (action connect),
#       Meta renvoie la réponse SDP par webhook, le navigateur la récupère et le son s'établit.
#
#   Réglage côté Meta : abonner le webhook de l'application au champ « calls », puis activer
#   « Autoriser les appels vocaux » dans WhatsApp Manager (Paramètres des appels).
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import Body, Depends, HTTPException, Query

from routes.numeros_wa import (
    VisibiliteLignes, cle_de_numero, ligne_par_cle, lignes_configurees, numero_envoi, pastille,
)

logger = logging.getLogger("sawali.appels_wa")

# Un appel non décroché après ce délai n'est plus proposé (Meta raccroche vers 30 à 60 s)
SONNERIE_MAX_S = 60
# Statuts d'un appel dans db.wa_appels
STATUTS_ACTIFS = ("sonne", "decroche", "en_cours", "appel")


def _maintenant() -> str:
    """Date et heure actuelles (UTC, format ISO)."""
    return datetime.now(timezone.utc).isoformat()


def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def _iso_depuis_unix(valeur: Any) -> Optional[str]:
    """Horodatage Unix (secondes, texte ou nombre) → date ISO UTC (None si absent)."""
    try:
        return datetime.fromtimestamp(int(valeur), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


async def _contact_du_numero(db, chiffres: str) -> Optional[Dict[str, Any]]:
    """Fiche contact d'un correspondant (8 derniers chiffres du numéro)."""
    if len(chiffres) < 6:
        return None
    fin = re.escape(chiffres[-8:])
    return await db.directory_contacts.find_one(
        {"$or": [{"whatsapp": {"$regex": fin}}, {"phone": {"$regex": fin}}]},
        {"_id": 0, "id": 1, "client_id": 1, "name": 1, "wa_ligne": 1, "whatsapp": 1, "phone": 1},
    )


async def _perimetre_principal(db) -> Optional[str]:
    """Entreprise à laquelle rattacher un appel d'un inconnu (même règle que les messages :
    premier superviseur, sinon premier administrateur)."""
    u = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
    if not u:
        u = await db.users.find_one({"role": "admin", "email": {"$ne": "admin@sawalismartsystems.com"}},
                                    {"_id": 0, "id": 1})
    return (u or {}).get("id")


# ---------------------------------------------------------------------------
# Webhook Meta (champ « calls ») — appelé par POST /whatsapp/webhook
# ---------------------------------------------------------------------------

async def traiter_webhook_appels(db, valeur: Dict[str, Any]) -> int:
    """Enregistre les évènements d'appel reçus de Meta. Retourne le nombre d'évènements traités."""
    traites = 0
    numero_id = str((valeur.get("metadata") or {}).get("phone_number_id") or "").strip() or None
    noms = {c.get("wa_id"): ((c.get("profile") or {}).get("name") or "").strip()
            for c in (valeur.get("contacts") or [])}
    s = await db.settings.find_one({"_id": "global"}) or {}

    # 1. Évènements d'appel : connect (sonnerie ou réponse SDP d'un appel sortant) / terminate
    for appel in valeur.get("calls") or []:
        call_id = appel.get("id")
        if not call_id:
            continue
        traites += 1
        evenement = appel.get("event")
        sortant = appel.get("direction") == "BUSINESS_INITIATED"
        if evenement == "connect" and not sortant:
            # Appel ENTRANT : le client appelle → sonnerie dans le portail
            tel = _chiffres(appel.get("from"))
            contact = await _contact_du_numero(db, tel)
            existant = await db.wa_appels.find_one({"id": call_id}, {"_id": 1})
            if existant:
                continue   # webhook répété par Meta : déjà enregistré
            await db.wa_appels.insert_one({
                "id": call_id,
                "direction": "entrant",
                "statut": "sonne",
                "numero_id": numero_id,
                "ligne_cle": cle_de_numero(s, numero_id),
                "telephone": tel,
                "contact_id": (contact or {}).get("id"),
                "contact_nom": (contact or {}).get("name") or noms.get(appel.get("from")) or f"+{tel}",
                "client_id": (contact or {}).get("client_id") or await _perimetre_principal(db),
                "sdp_offre": (appel.get("session") or {}).get("sdp"),
                "sonne_le": _iso_depuis_unix(appel.get("timestamp")) or _maintenant(),
                "created_at": _maintenant(),
            })
        elif evenement == "connect" and sortant:
            # Appel SORTANT : le client a décroché → réponse SDP à transmettre au navigateur
            await db.wa_appels.update_one({"id": call_id}, {"$set": {
                "sdp_reponse": (appel.get("session") or {}).get("sdp"),
                "statut": "en_cours", "debut": _maintenant(), "maj": _maintenant()}})
        elif evenement == "terminate":
            # Fin d'appel : durée et heures données par Meta
            doc = await db.wa_appels.find_one({"id": call_id}, {"_id": 0, "statut": 1, "direction": 1,
                                                                "motif": 1}) or {}
            statut_meta = str(appel.get("status") or "").upper()
            duree = int(appel.get("duration") or 0)
            if doc.get("statut") == "refuse":
                statut = "refuse"                       # refusé (par l'agent ou par le client)
            elif duree > 0 or doc.get("statut") in ("en_cours", "decroche"):
                statut = "termine"                      # conversation qui a eu lieu
            elif doc.get("direction") == "sortant":
                statut = "sans_reponse"                 # le client n'a pas décroché
            else:
                statut = "manque"                       # personne n'a décroché chez SAWALI
            await db.wa_appels.update_one({"id": call_id}, {"$set": {
                "statut": statut, "duree_s": duree,
                "debut": _iso_depuis_unix(appel.get("start_time")),
                "fin": _iso_depuis_unix(appel.get("end_time")) or _maintenant(),
                "statut_meta": statut_meta, "sdp_offre": None, "maj": _maintenant()}})
            # Lot 67.1 — appel automatique de Liluvine : la durée de Meta (facturée) remplace la durée
            # mesurée dans l'historique des appels, coût recalculé avec le tarif figé de l'appel
            if doc.get("motif") == "alerte message":
                try:
                    from routes.appel_proprietaire import noter_duree_meta
                    await noter_duree_meta(db, call_id, duree)
                except Exception:  # noqa: BLE001 — l'historique ne bloque jamais le webhook
                    logger.warning("[appels_wa] historique Liluvine non mis à jour", exc_info=True)

    # 2. Statuts d'un appel SORTANT (sonnerie chez le client, accepté, refusé)
    for st in valeur.get("statuses") or []:
        if st.get("type") != "call" or not st.get("id"):
            continue
        traites += 1
        correspondance = {"RINGING": "appel", "ACCEPTED": "en_cours", "REJECTED": "refuse"}
        nouveau = correspondance.get(str(st.get("status") or "").upper())
        if nouveau:
            await db.wa_appels.update_one({"id": st["id"]}, {"$set": {"statut": nouveau, "maj": _maintenant()}})
    return traites


async def noter_reponse_permission(db, telephone: str, reponse: Dict[str, Any]) -> str:
    """Mémorise la réponse du client à une demande d'autorisation d'appel ; renvoie le texte
    à afficher dans la conversation."""
    accepte = str(reponse.get("response") or "").lower() == "accept"
    await db.wa_appels_permissions.update_one(
        {"telephone": _chiffres(telephone)},
        {"$set": {"telephone": _chiffres(telephone), "accepte": accepte,
                  "permanente": bool(reponse.get("is_permanent")),
                  "expire_le": _iso_depuis_unix(reponse.get("expiration_timestamp")),
                  "maj": _maintenant()}},
        upsert=True,
    )
    return "📞 Autorisation d'appel : " + ("acceptée" if accepte else "refusée")


# ---------------------------------------------------------------------------
# Routes du portail
# ---------------------------------------------------------------------------

def setup_appels_wa_routes(*, db, api, get_current_user, resolve_visible_client_ids: Callable,
                           graph_version: str = "v21.0") -> None:
    """Déclare les routes /me/wa-appels/* (voir l'en-tête du fichier)."""

    async def _reglages() -> Dict[str, Any]:
        return await db.settings.find_one({"_id": "global"}) or {}

    async def _graph(numero_id: str, corps: Dict[str, Any], s: Dict[str, Any],
                     chemin: str = "calls") -> Dict[str, Any]:
        """Appel à l'API Graph de Meta pour le numéro donné (jeton global du compte WhatsApp)."""
        jeton = (s.get("wa_access_token") or "").strip()
        if not jeton or not numero_id:
            raise HTTPException(status_code=503, detail="WhatsApp non configuré (jeton ou numéro manquant)")
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(f"https://graph.facebook.com/{graph_version}/{numero_id}/{chemin}",
                                    json=corps, headers={"Authorization": f"Bearer {jeton}"})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Meta injoignable : {exc}") from exc
        try:
            donnees = r.json()
        except Exception:  # noqa: BLE001
            donnees = {}
        if r.status_code >= 300:
            err = (donnees.get("error") or {}) if isinstance(donnees, dict) else {}
            message = err.get("message") or f"HTTP {r.status_code}"
            details = (err.get("error_data") or {}).get("details")
            raise HTTPException(status_code=502, detail=f"Meta : {message}" + (f" — {details}" if details else ""))
        return donnees

    async def _visible(user: dict, appel: Dict[str, Any], vis: Optional[VisibiliteLignes] = None,
                       perimetre: Optional[List[str]] = None) -> bool:
        """L'utilisateur peut-il voir cet appel ? (même entreprise + ligne autorisée)"""
        if perimetre is None:
            perimetre = await resolve_visible_client_ids(user)
        if user.get("role") != "admin" and appel.get("client_id") not in perimetre:
            return False
        if vis is None:
            vis = await VisibiliteLignes.charger(db, user)
        if not vis.restreint:
            return True
        if (appel.get("ligne_cle") or "principal") not in vis.autorisees:
            return False
        contact = None
        if appel.get("contact_id"):
            contact = await db.directory_contacts.find_one(
                {"id": appel["contact_id"]}, {"_id": 0, "client_id": 1, "wa_ligne": 1, "whatsapp": 1, "phone": 1})
        return vis.contact_visible(contact, appel.get("telephone"))

    def _public(appel: Dict[str, Any], s: Dict[str, Any]) -> Dict[str, Any]:
        """Champs d'un appel renvoyés au portail (avec la pastille de sa ligne)."""
        sortie = {k: appel.get(k) for k in (
            "id", "direction", "statut", "telephone", "contact_id", "contact_nom", "sonne_le", "debut", "fin",
            "duree_s", "decroche_par_nom", "created_at",
            # Lot 67 — alerte de Liluvine au propriétaire : motif, résultat, raison d'échec, client concerné
            "motif", "resultat", "raison", "alerte_client_nom")}
        sortie["ligne"] = pastille(ligne_par_cle(s, appel.get("ligne_cle")) or lignes_configurees(s)[0])
        return sortie

    async def _appel_visible(call_id: str, user: dict) -> Dict[str, Any]:
        """Appel demandé, s'il existe et si l'utilisateur peut le voir (sinon 404)."""
        appel = await db.wa_appels.find_one({"id": call_id}, {"_id": 0})
        if not appel or not await _visible(user, appel):
            raise HTTPException(status_code=404, detail="Appel introuvable")
        return appel

    @api.get("/me/wa-appels/en-cours", tags=["Portail Client — Appels WhatsApp"])
    async def appels_en_cours(user: dict = Depends(get_current_user)):
        """Appels qui sonnent (visibles par l'utilisateur) + son appel en cours éventuel."""
        s = await _reglages()
        limite = (datetime.now(timezone.utc) - timedelta(seconds=SONNERIE_MAX_S)).isoformat()
        perimetre = await resolve_visible_client_ids(user)
        vis = await VisibiliteLignes.charger(db, user, s)
        sonnent = []
        async for a in db.wa_appels.find({"statut": "sonne", "created_at": {"$gte": limite}}, {"_id": 0}):
            if await _visible(user, a, vis, perimetre):
                sonnent.append(_public(a, s))
        mien = await db.wa_appels.find_one(
            {"agent_id": user["id"], "statut": {"$in": list(STATUTS_ACTIFS)}}, {"_id": 0}, sort=[("created_at", -1)])
        return {"sonnent": sonnent, "mon_appel": _public(mien, s) if mien else None}

    @api.get("/me/wa-appels/non-repondus", tags=["Portail Client — Appels WhatsApp"])
    async def appels_non_repondus(jours: int = Query(7, ge=1, le=30), user: dict = Depends(get_current_user)):
        """Lot 64.2 — appels entrants manqués (visibles par l'utilisateur) des N derniers jours
        qui n'ont pas encore été « rattrapés » : aucun appel ABOUTI ensuite avec ce même numéro
        (rappel du client ou rappel par SAWALI). Sert au titre de l'onglet du navigateur."""
        s = await _reglages()
        depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
        perimetre = await resolve_visible_client_ids(user)
        vis = await VisibiliteLignes.charger(db, user, s)
        # Dernier appel abouti par numéro (8 derniers chiffres) sur la période
        aboutis: Dict[str, str] = {}
        async for a in db.wa_appels.find({"created_at": {"$gte": depuis}, "statut": {"$in": ["termine", "en_cours"]}},
                                         {"_id": 0, "telephone": 1, "created_at": 1}):
            cle = _chiffres(a.get("telephone"))[-8:]
            aboutis[cle] = max(aboutis.get(cle, ""), a.get("created_at") or "")
        # Manqués postérieurs au dernier appel abouti : un seul par numéro
        numeros = set()
        async for a in db.wa_appels.find({"direction": "entrant", "statut": "manque", "created_at": {"$gte": depuis}},
                                         {"_id": 0}).sort("created_at", -1).limit(500):
            cle = _chiffres(a.get("telephone"))[-8:]
            if cle in numeros or (a.get("created_at") or "") <= aboutis.get(cle, ""):
                continue
            if await _visible(user, a, vis, perimetre):
                numeros.add(cle)
        return {"total": len(numeros)}

    @api.get("/me/wa-appels/{call_id}/offre", tags=["Portail Client — Appels WhatsApp"])
    async def offre_appel(call_id: str, user: dict = Depends(get_current_user)):
        """Offre SDP d'un appel entrant qui sonne (pour préparer la réponse du navigateur)."""
        appel = await _appel_visible(call_id, user)
        if appel.get("statut") != "sonne" or not appel.get("sdp_offre"):
            raise HTTPException(status_code=409, detail="Cet appel ne sonne plus")
        return {"sdp": appel["sdp_offre"]}

    @api.post("/me/wa-appels/{call_id}/decrocher", tags=["Portail Client — Appels WhatsApp"])
    async def decrocher(call_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Décroche : envoie la réponse SDP du navigateur à Meta (pre_accept puis accept)."""
        sdp = str(payload.get("sdp") or "")
        if not sdp.startswith("v="):
            raise HTTPException(status_code=400, detail="Réponse SDP invalide")
        appel = await _appel_visible(call_id, user)
        # Le premier qui décroche prend l'appel (mise à jour conditionnelle)
        pris = await db.wa_appels.update_one(
            {"id": call_id, "statut": "sonne"},
            {"$set": {"statut": "decroche", "agent_id": user["id"],
                      "decroche_par_nom": user.get("full_name") or user.get("email"), "maj": _maintenant()}})
        if not getattr(pris, "modified_count", 0):
            raise HTTPException(status_code=409, detail="Appel déjà pris par un collègue ou terminé")
        s = await _reglages()
        session = {"sdp_type": "answer", "sdp": sdp}
        try:
            await _graph(appel["numero_id"], {"messaging_product": "whatsapp", "call_id": call_id,
                                              "action": "pre_accept", "session": session}, s)
            await _graph(appel["numero_id"], {"messaging_product": "whatsapp", "call_id": call_id,
                                              "action": "accept", "session": session}, s)
        except HTTPException:
            # Échec : l'appel redevient disponible pour un collègue
            await db.wa_appels.update_one({"id": call_id, "agent_id": user["id"]},
                                          {"$set": {"statut": "sonne", "agent_id": None, "decroche_par_nom": None}})
            raise
        await db.wa_appels.update_one({"id": call_id}, {"$set": {
            "statut": "en_cours", "debut": _maintenant(), "sdp_offre": None, "maj": _maintenant()}})
        return {"ok": True}

    @api.post("/me/wa-appels/{call_id}/refuser", tags=["Portail Client — Appels WhatsApp"])
    async def refuser(call_id: str, user: dict = Depends(get_current_user)):
        """Refuse un appel qui sonne."""
        appel = await _appel_visible(call_id, user)
        if appel.get("statut") != "sonne":
            raise HTTPException(status_code=409, detail="Cet appel ne sonne plus")
        await _graph(appel["numero_id"], {"messaging_product": "whatsapp", "call_id": call_id, "action": "reject"},
                     await _reglages())
        await db.wa_appels.update_one({"id": call_id}, {"$set": {
            "statut": "refuse", "refuse_par_nom": user.get("full_name") or user.get("email"),
            "sdp_offre": None, "maj": _maintenant()}})
        return {"ok": True}

    @api.post("/me/wa-appels/{call_id}/raccrocher", tags=["Portail Client — Appels WhatsApp"])
    async def raccrocher(call_id: str, user: dict = Depends(get_current_user)):
        """Termine l'appel en cours (entrant ou sortant). La durée arrive ensuite par webhook."""
        appel = await _appel_visible(call_id, user)
        if appel.get("statut") in STATUTS_ACTIFS:
            try:
                await _graph(appel["numero_id"], {"messaging_product": "whatsapp", "call_id": call_id,
                                                  "action": "terminate"}, await _reglages())
            except HTTPException as exc:
                logger.info("[appels_wa] terminate %s : %s", call_id, exc.detail)
            maj: Dict[str, Any] = {"maj": _maintenant()}
            if appel.get("statut") in ("appel", "sonne"):
                maj["statut"] = "sans_reponse" if appel.get("direction") == "sortant" else "manque"
            await db.wa_appels.update_one({"id": call_id}, {"$set": maj})
        return {"ok": True}

    @api.get("/me/wa-appels/{call_id}", tags=["Portail Client — Appels WhatsApp"])
    async def etat_appel(call_id: str, user: dict = Depends(get_current_user)):
        """État d'un appel (+ réponse SDP de Meta pour un appel sortant décroché)."""
        appel = await _appel_visible(call_id, user)
        sortie = _public(appel, await _reglages())
        if appel.get("agent_id") == user["id"]:
            sortie["sdp_reponse"] = appel.get("sdp_reponse")
        return sortie

    @api.get("/me/wa-appels", tags=["Portail Client — Appels WhatsApp"])
    async def journal(telephone: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                      user: dict = Depends(get_current_user)):
        """Journal des appels visibles par l'utilisateur (le plus récent d'abord)."""
        s = await _reglages()
        filtre: Dict[str, Any] = {}
        if telephone and len(_chiffres(telephone)) >= 6:
            filtre["telephone"] = {"$regex": re.escape(_chiffres(telephone)[-8:]) + "$"}
        perimetre = await resolve_visible_client_ids(user)
        vis = await VisibiliteLignes.charger(db, user, s)
        sortie = []
        async for a in db.wa_appels.find(filtre, {"_id": 0}).sort("created_at", -1).limit(limit * 3):
            if await _visible(user, a, vis, perimetre):
                sortie.append(_public(a, s))
            if len(sortie) >= limit:
                break
        total = sum(int(a.get("duree_s") or 0) for a in sortie)
        return {"items": sortie, "duree_totale_s": total}

    async def _verifier_destinataire(user: dict, telephone: str, contact_id: Optional[str]) -> str:
        """Contrôle d'accès avant un appel ou une demande d'autorisation ; renvoie les chiffres du numéro."""
        tel = _chiffres(telephone)
        if len(tel) < 8:
            raise HTTPException(status_code=400, detail="Numéro invalide")
        from routes.numeros_wa import exiger_telephone_visible
        await exiger_telephone_visible(db, user, tel, contact_id)
        return tel

    @api.get("/me/wa-appels-permission", tags=["Portail Client — Appels WhatsApp"])
    async def etat_permission(telephone: str, user: dict = Depends(get_current_user)):
        """Le client a-t-il autorisé les appels ? (état lu chez Meta, sinon notre dernière trace)."""
        tel = await _verifier_destinataire(user, telephone, None)
        s = await _reglages()
        numero = await numero_envoi(db, tel, s)
        jeton = (s.get("wa_access_token") or "").strip()
        etat: Dict[str, Any] = {"telephone": tel}
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get(f"https://graph.facebook.com/{graph_version}/{numero}/call_permissions",
                                   params={"user_wa_id": tel}, headers={"Authorization": f"Bearer {jeton}"})
            if r.status_code < 300:
                d = r.json() or {}
                perm = d.get("permission") or {}
                etat["statut"] = perm.get("status")            # temporary | permanent | no_permission
                etat["expire_le"] = _iso_depuis_unix(perm.get("expiration_time"))
                actions = {a.get("action_name"): bool(a.get("can_perform_action")) for a in d.get("actions") or []}
                etat["peut_demander"] = actions.get("send_call_permission_request")
                etat["peut_appeler"] = actions.get("start_call")
        except Exception as exc:  # noqa: BLE001
            logger.info("[appels_wa] état de permission illisible : %s", exc)
        if "statut" not in etat:
            trace = await db.wa_appels_permissions.find_one({"telephone": tel}, {"_id": 0}) or {}
            etat["statut"] = ("permanent" if trace.get("permanente") else "temporary") if trace.get("accepte") else "no_permission"
            etat["peut_appeler"] = bool(trace.get("accepte"))
            etat["peut_demander"] = not trace.get("accepte")
        return etat

    @api.post("/me/wa-appels-permission", tags=["Portail Client — Appels WhatsApp"])
    async def demander_permission(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Envoie au client la demande d'autorisation d'appel (message WhatsApp interactif)."""
        tel = await _verifier_destinataire(user, payload.get("telephone") or "", payload.get("contact_id"))
        s = await _reglages()
        texte = (str(payload.get("texte") or "").strip()
                 or "Bonjour, nous souhaitons vous appeler sur WhatsApp pour mieux vous aider. Acceptez-vous ?")[:1024]
        numero = await numero_envoi(db, tel, s)
        await _graph(numero, {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": tel, "type": "interactive",
            "interactive": {"type": "call_permission_request", "action": {"name": "call_permission_request"},
                            "body": {"text": texte}},
        }, s, chemin="messages")
        await db.whatsapp_messages.insert_one({
            "id": str(uuid.uuid4()), "client_id": user.get("client_id") or user["id"], "direction": "outbound",
            "to": f"+{tel}", "phone_digits": tel, "contact_id": payload.get("contact_id"),
            "body": f"📞 Demande d'autorisation d'appel : {texte}", "message_type": "call_permission_request",
            "sender_id": user["id"], "sender_label": user.get("full_name") or user.get("email"),
            "wa_numero_id": numero, "created_at": _maintenant(), "sent_at": _maintenant(),
        })
        return {"ok": True}

    @api.post("/me/wa-appels/appeler", tags=["Portail Client — Appels WhatsApp"])
    async def appeler(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Lance un appel vers le client (il doit avoir autorisé les appels) avec l'offre SDP du navigateur."""
        sdp = str(payload.get("sdp") or "")
        if not sdp.startswith("v="):
            raise HTTPException(status_code=400, detail="Offre SDP invalide")
        tel = await _verifier_destinataire(user, payload.get("telephone") or "", payload.get("contact_id"))
        s = await _reglages()
        numero = await numero_envoi(db, tel, s)
        rep = await _graph(numero, {"messaging_product": "whatsapp", "to": tel, "action": "connect",
                                    "session": {"sdp_type": "offer", "sdp": sdp}}, s)
        call_id = ((rep.get("calls") or [{}])[0] or {}).get("id")
        if not call_id:
            raise HTTPException(status_code=502, detail="Meta n'a pas renvoyé d'identifiant d'appel")
        contact = await _contact_du_numero(db, tel)
        await db.wa_appels.insert_one({
            "id": call_id, "direction": "sortant", "statut": "appel",
            "numero_id": numero, "ligne_cle": cle_de_numero(s, numero), "telephone": tel,
            "contact_id": payload.get("contact_id") or (contact or {}).get("id"),
            "contact_nom": (contact or {}).get("name") or f"+{tel}",
            "client_id": (contact or {}).get("client_id") or user.get("client_id") or user["id"],
            "agent_id": user["id"], "decroche_par_nom": user.get("full_name") or user.get("email"),
            "created_at": _maintenant(), "maj": _maintenant(),
        })
        return {"ok": True, "id": call_id}
