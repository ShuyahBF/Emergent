# support_loois_sondages.py — Lot 88 : sondages d'évaluation envoyés aux postes Loois depuis le Support.
#
# Demande du propriétaire (09/10/2026) :
#   « Envoyer un sondage qui s'affiche tel quel dans la fenêtre de l'utilisateur, qu'il remplit et renvoie. On affiche
#     tous les sondages commençant par "Evaluation Loois". Tant que le sondage n'a pas été répondu, plus de requête
#     possible au support. Quand il répond, Liluvine le remercie avec une phrase paramétrable par l'Admin. Le sondage,
#     répondu ou non, apparaît dans la conversation avec son statut (il peut répondre plus tard s'il l'avait manqué).
#     Le sondage est numéroté et ses réponses y font référence. La fenêtre d'évaluation sur SAWALI permet des analyses. »
#
# Principe :
#   - SONDAGES PROPOSÉS : ceux du module Sondages (wa_surveys) dont le titre commence par « Evaluation Loois »
#     (accents et casse ignorés), non clôturés.
#   - ENVOI : une invitation wa_survey_invites (canal « loois », destinataire = le poste) portant un NUMÉRO
#     « EVL-AAAA-NNNN » ; une carte « 📋 Sondage » est déposée dans le fil du poste (message avec le champ `sondage`).
#     Les réponses sont rangées dans wa_survey_responses (invite_id = l'envoi) : la page « Résultats » du sondage
#     (graphiques, entreprises, export CSV) les analyse avec les autres réponses. Jamais de relance WhatsApp.
#   - RÉPONSE : le poste lit le sondage (questions telles quelles) et renvoie ses réponses (même contrôle que la page
#     publique) ; la carte passe « ✅ Répondu » (trame `message_maj`), Liluvine remercie (phrase des Paramètres).
#     Répondre à nouveau = modifier sa réponse (même numéro).
#   - BLOCAGE : un poste qui a un sondage non répondu ne peut plus ouvrir de nouvelle demande d'assistance
#     (trame `sondage_requis` à la connexion) ; dès la réponse, la demande part normalement.
#   - ÉTAT POUR L'ICÔNE LOOIS : GET /support-loois/etat (clé du poste) indique s'il faut OUVRIR la fenêtre
#     (message du support non lu, poste hors ligne) — la zone de notification de Loois l'interroge régulièrement.
from __future__ import annotations

import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Body, Depends, HTTPException, Query, Request

from routes import support_loois_sessions as sessions
from routes.wa_surveys import validate_answers

PREFIXE_TITRE = "evaluation loois"          # titres « Evaluation Loois … » (sans accents, minuscules)
CANAL = "loois"                              # invitations envoyées dans Loois (jamais par WhatsApp)
REMERCIEMENT_DEFAUT = ("Merci pour votre évaluation (sondage {numero}) ! Vos réponses nous aident à améliorer "
                       "le support SAWALI. 🙏")


# ---------------------------------------------------------------------------
# Fonctions pures (testées sans base)
# ---------------------------------------------------------------------------
def _sans_accents(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def est_sondage_loois(titre: Optional[str]) -> bool:
    """« Évaluation Loois — fin de session » → True ; « Satisfaction clients » → False."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _sans_accents(titre or "")).split()).startswith(PREFIXE_TITRE)


def numero_envoi(annee: int, rang: int) -> str:
    """Numéro du sondage envoyé : EVL-2026-0001."""
    return f"EVL-{annee}-{int(rang):04d}"


def phrase_remerciement(modele: Optional[str], numero: str) -> str:
    """Phrase de Liluvine après la réponse ; « {numero} » remplacé par le numéro du sondage."""
    texte = (modele or "").strip() or REMERCIEMENT_DEFAUT
    return texte.replace("{numero}", numero)[:1000]


def carte(envoi: Dict[str, Any]) -> Dict[str, Any]:
    """Champ `sondage` des messages du fil (lu par Loois et par le chat SAWALI)."""
    return {"envoi_id": envoi["id"], "numero": envoi.get("numero"), "titre": envoi.get("titre"),
            "survey_id": envoi.get("survey_id"),
            "statut": "repondu" if envoi.get("answered_at") else ("annule" if envoi.get("annule") else "en_attente"),
            "repondu_le": envoi.get("answered_at")}


def trame_requis(envois: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Trame envoyée au poste bloqué : il doit répondre avant toute nouvelle demande."""
    numeros = ", ".join(e.get("numero") or "" for e in envois)
    return {"type": "sondage_requis", "sondages": [carte(e) for e in envois],
            "detail": f"Merci de répondre au sondage {numeros} avant une nouvelle demande d'assistance."}


# ---------------------------------------------------------------------------
# Accès aux données
# ---------------------------------------------------------------------------
async def en_attente(db, pid: str) -> List[Dict[str, Any]]:
    """Sondages envoyés au poste et toujours sans réponse (non annulés) : ils bloquent les nouvelles demandes."""
    return await db.wa_survey_invites.find(
        {"canal": CANAL, "contact_id": pid, "answered_at": None, "annule": {"$ne": True}}, {"_id": 0}
    ).sort("created_at", 1).to_list(20)


async def prochain_numero(db) -> str:
    """Compteur atomique annuel des sondages envoyés aux postes."""
    annee = datetime.now(timezone.utc).year
    res = await db.counters.find_one_and_update({"_id": f"sondages_loois_{annee}"}, {"$inc": {"seq": 1}},
                                                upsert=True, return_document=True)
    if res is None:
        res = await db.counters.find_one({"_id": f"sondages_loois_{annee}"})
    return numero_envoi(annee, int((res or {}).get("seq", 1)))


async def reglages(db) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "support_loois_remerciement_sondage": 1}) or {}
    return {"remerciement_sondage": s.get("support_loois_remerciement_sondage") or REMERCIEMENT_DEFAUT}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes (montées par support_loois.installer)
# ---------------------------------------------------------------------------
def installer(*, router, db, manager, equipe: Callable, poste_de_la_requete: Callable,
              enregistrer_message: Callable, message_systeme: Callable, diffuser_equipe: Callable,
              espace_id: str) -> None:
    """Routes de l'équipe (envoi, liste, annulation, réglages) et du poste (lire, répondre, état pour l'icône)."""

    async def _envoi(eid: str) -> Dict[str, Any]:
        envoi = await db.wa_survey_invites.find_one({"id": eid, "canal": CANAL}, {"_id": 0})
        if not envoi:
            raise HTTPException(status_code=404, detail="Sondage introuvable.")
        return envoi

    async def _maj_carte(envoi: Dict[str, Any]) -> None:
        """Met à jour la carte du fil (statut) et la pousse au poste et à l'équipe (trame message_maj)."""
        if not envoi.get("message_id"):
            return
        await db.internal_chat_messages.update_one({"id": envoi["message_id"]}, {"$set": {"sondage": carte(envoi)}})
        msg = await db.internal_chat_messages.find_one({"id": envoi["message_id"]}, {"_id": 0})
        if msg:
            await diffuser_equipe({"type": "message_maj", "client_id": espace_id, "message": msg},
                                  aussi=[envoi["contact_id"]])

    # ---- Équipe : sondages proposés -------------------------------------------------------------
    @router.get("/support-loois/sondages-disponibles")
    async def disponibles(user: dict = Depends(equipe)):
        """Sondages « Evaluation Loois… » du module Sondages, non clôturés (questions comptées)."""
        sortie = []
        async for s in db.wa_surveys.find({"status": {"$ne": "closed"}}, {"_id": 0, "id": 1, "title": 1, "questions": 1,
                                                                            "status": 1, "updated_at": 1}):
            if est_sondage_loois(s.get("title")):
                sortie.append({"id": s["id"], "titre": s.get("title"), "questions": len(s.get("questions") or []),
                               "statut": s.get("status")})
        sortie.sort(key=lambda x: x["titre"] or "")
        return {"sondages": sortie}

    # ---- Équipe : envoyer un sondage au poste -----------------------------------------------------
    @router.post("/support-loois/postes/{pid}/sondages")
    async def envoyer(pid: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(equipe)):
        poste = await db.support_loois_postes.find_one({"id": pid}, {"_id": 0})
        if not poste:
            raise HTTPException(status_code=404, detail="Poste Loois inconnu.")
        s = await db.wa_surveys.find_one({"id": str((payload or {}).get("survey_id") or "")}, {"_id": 0})
        if not s or not est_sondage_loois(s.get("title")):
            raise HTTPException(status_code=400, detail="Choisissez un sondage « Evaluation Loois… ».")
        if s.get("status") == "closed":
            raise HTTPException(status_code=409, detail="Ce sondage est clôturé.")
        session = await db.support_loois_sessions.find_one({"poste_id": pid}, {"_id": 0}, sort=[("demande_le", -1)]) or {}
        numero = await prochain_numero(db)
        maintenant = _maintenant()
        envoi = {
            "id": uuid.uuid4().hex, "token": secrets.token_urlsafe(9), "survey_id": s["id"], "canal": CANAL,
            "numero": numero, "titre": s.get("title"), "contact_id": pid, "poste_id": pid,
            "client_id": poste.get("client_id"), "name": poste.get("nom") or pid,
            "company": poste.get("ecole") or poste.get("cle_client_libelle") or "",
            "phone": None, "email": None, "unique_code": None,
            "session_id": session.get("id"), "ticket_number": session.get("ticket_number"),
            "status": "sent", "sent_count": 1, "opened_at": None, "answered_at": None, "campaign_ids": [],
            "envoye_par_id": user.get("id"), "envoye_par_nom": user.get("full_name") or user.get("email"),
            "created_at": maintenant, "last_sent_at": maintenant, "annule": False,
        }
        # Carte du fil (visible dans Loois et dans le chat SAWALI), puis lien carte ↔ envoi
        msg = {"id": str(uuid.uuid4()), "client_id": espace_id, "sender_id": "sawali", "sender_name": "Support SAWALI",
               "recipient_id": pid, "systeme": True, "created_at": maintenant, "read_by": ["sawali"],
               "text": f"📋 Sondage {numero} — {s.get('title')} : merci de le remplir (bouton « Répondre »).",
               "sondage": carte(envoi)}
        envoi["message_id"] = msg["id"]
        await db.wa_survey_invites.insert_one(dict(envoi))
        await enregistrer_message(pid, msg)
        return {"ok": True, "envoi": carte(envoi)}

    # ---- Équipe : liste des sondages envoyés (fenêtre d'évaluation) --------------------------------
    @router.get("/support-loois/sondages-envois")
    async def liste_envois(statut: Optional[str] = Query(None), survey_id: Optional[str] = Query(None),
                           poste_id: Optional[str] = Query(None), limit: int = Query(300, ge=1, le=2000),
                           user: dict = Depends(equipe)):
        q: Dict[str, Any] = {"canal": CANAL}
        if survey_id:
            q["survey_id"] = survey_id
        if poste_id:
            q["contact_id"] = poste_id
        if statut == "repondu":
            q["answered_at"] = {"$ne": None}
        elif statut == "en_attente":
            q.update({"answered_at": None, "annule": {"$ne": True}})
        elif statut == "annule":
            q["annule"] = True
        envois = await db.wa_survey_invites.find(q, {"_id": 0, "token": 0}).sort("created_at", -1).to_list(limit)
        reponses = {r["invite_id"]: r async for r in db.wa_survey_responses.find(
            {"invite_id": {"$in": [e["id"] for e in envois]}}, {"_id": 0})}
        sondages = {s["id"]: s async for s in db.wa_surveys.find(
            {"id": {"$in": list({e["survey_id"] for e in envois})}}, {"_id": 0, "id": 1, "questions": 1})}
        lignes = []
        for e in envois:
            r = reponses.get(e["id"]) or {}
            questions = (sondages.get(e["survey_id"]) or {}).get("questions") or []
            # Réponses lisibles « question : réponse » (fenêtre d'évaluation)
            detail = [{"question": q.get("label"), "type": q.get("type"), "reponse": (r.get("answers") or {}).get(q["id"])}
                      for q in questions if q.get("id") in (r.get("answers") or {})]
            lignes.append({**carte(e), "poste_id": e.get("contact_id"), "poste": e.get("name"), "ecole": e.get("company"),
                           "client_id": e.get("client_id"), "ticket_number": e.get("ticket_number"),
                           "envoye_le": e.get("created_at"), "envoye_par": e.get("envoye_par_nom"),
                           "revisions": r.get("revisions", 0) if r else None, "reponses": detail})
        total = len(lignes)
        repondus = sum(1 for x in lignes if x["statut"] == "repondu")
        return {"envois": lignes, "resume": {"total": total, "repondus": repondus,
                                             "en_attente": sum(1 for x in lignes if x["statut"] == "en_attente"),
                                             "taux": round(100 * repondus / total, 1) if total else None}}

    # ---- Équipe : annuler un sondage non répondu (débloque le poste) ------------------------------
    @router.post("/support-loois/sondages-envois/{eid}/annuler")
    async def annuler(eid: str, user: dict = Depends(equipe)):
        envoi = await _envoi(eid)
        if envoi.get("answered_at"):
            raise HTTPException(status_code=409, detail="Sondage déjà répondu : il ne peut plus être annulé.")
        await db.wa_survey_invites.update_one({"id": eid}, {"$set": {"annule": True, "annule_le": _maintenant(),
                                                                      "status": "skipped"}})
        await _maj_carte(await _envoi(eid))
        return {"ok": True}

    # ---- Réglages (rubrique des Paramètres) -------------------------------------------------------
    @router.get("/admin/support-loois/reglages")
    async def lire_reglages(user: dict = Depends(equipe)):
        total = await db.wa_survey_invites.count_documents({"canal": CANAL})
        repondus = await db.wa_survey_invites.count_documents({"canal": CANAL, "answered_at": {"$ne": None}})
        attente = await db.wa_survey_invites.count_documents({"canal": CANAL, "answered_at": None, "annule": {"$ne": True}})
        return {**await reglages(db), "remerciement_defaut": REMERCIEMENT_DEFAUT,
                "stats": {"envoyes": total, "repondus": repondus, "en_attente": attente}}

    @router.put("/admin/support-loois/reglages")
    async def ecrire_reglages(payload: Dict[str, Any] = Body(...), user: dict = Depends(equipe)):
        if user.get("role") not in ("admin", "super_admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur ou au superviseur.")
        texte = str((payload or {}).get("remerciement_sondage") or "").strip()[:1000]
        await db.settings.update_one({"_id": "global"}, {"$set": {"support_loois_remerciement_sondage": texte}}, upsert=True)
        return await lire_reglages(user)

    # ---- Poste : lire un sondage reçu ------------------------------------------------------------
    @router.get("/support-loois/sondages/{eid}")
    async def lire_sondage(eid: str, request: Request):
        ident = await poste_de_la_requete(request)
        envoi = await _envoi(eid)
        if envoi.get("contact_id") != ident["pid"]:
            raise HTTPException(status_code=404, detail="Sondage introuvable.")
        s = await db.wa_surveys.find_one({"id": envoi["survey_id"]}, {"_id": 0}) or {}
        r = await db.wa_survey_responses.find_one({"invite_id": eid}, {"_id": 0}) or {}
        if not envoi.get("opened_at"):
            await db.wa_survey_invites.update_one({"id": eid}, {"$set": {"opened_at": _maintenant()}})
        return {**carte(envoi), "description": s.get("description") or "", "questions": s.get("questions") or [],
                "reponses": r.get("answers") or {}, "cloture": s.get("status") == "closed"}

    # ---- Poste : répondre (ou modifier sa réponse) -----------------------------------------------
    @router.post("/support-loois/sondages/{eid}")
    async def repondre(eid: str, request: Request, payload: Dict[str, Any] = Body(...)):
        ident = await poste_de_la_requete(request)
        envoi = await _envoi(eid)
        if envoi.get("contact_id") != ident["pid"]:
            raise HTTPException(status_code=404, detail="Sondage introuvable.")
        if envoi.get("annule"):
            raise HTTPException(status_code=409, detail="Ce sondage a été annulé par le support.")
        s = await db.wa_surveys.find_one({"id": envoi["survey_id"]}, {"_id": 0}) or {}
        try:
            reponses = validate_answers(s.get("questions") or [], (payload or {}).get("answers") or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        maintenant = _maintenant()
        premiere = not envoi.get("answered_at")
        existante = await db.wa_survey_responses.find_one({"invite_id": eid}, {"_id": 0, "id": 1})
        if existante:
            await db.wa_survey_responses.update_one({"id": existante["id"]},
                                                    {"$set": {"answers": reponses, "updated_at": maintenant},
                                                     "$inc": {"revisions": 1}})
        else:
            await db.wa_survey_responses.insert_one({
                "id": uuid.uuid4().hex, "survey_id": envoi["survey_id"], "invite_id": eid, "contact_id": ident["pid"],
                "numero": envoi.get("numero"), "canal": CANAL, "answers": reponses,
                "created_at": maintenant, "updated_at": maintenant, "revisions": 0})
        await db.wa_survey_invites.update_one({"id": eid}, {"$set": {
            "answered_at": envoi.get("answered_at") or maintenant, "opened_at": envoi.get("opened_at") or maintenant}})
        envoi = await _envoi(eid)
        await _maj_carte(envoi)
        # Liluvine remercie (phrase des Paramètres), seulement à la première réponse
        if premiere:
            phrase = phrase_remerciement((await reglages(db))["remerciement_sondage"], envoi.get("numero") or "")
            await message_systeme(ident["pid"], phrase, sessions.LILUVINE_ID, sessions.LILUVINE_NOM)
        return {"ok": True, "sondage": carte(envoi), "debloque": not await en_attente(db, ident["pid"])}

    # ---- Poste : état pour l'icône de Loois (ouvrir la fenêtre ?) --------------------------------
    @router.get("/support-loois/etat")
    async def etat(request: Request):
        ident = await poste_de_la_requete(request)
        pid = ident["pid"]
        non_lus = await db.internal_chat_messages.count_documents(
            {"client_id": espace_id, "recipient_id": pid, "sender_id": {"$ne": pid}, "read_by": {"$ne": pid}})
        en_ligne = manager.is_online(pid)
        attente = await en_attente(db, pid)
        return {"poste_id": pid, "en_ligne": en_ligne, "non_lus": non_lus, "sondages_en_attente": len(attente),
                # Fenêtre fermée et message du support non lu → l'icône de Loois ouvre la conversation
                "ouvrir": bool(non_lus) and not en_ligne}
