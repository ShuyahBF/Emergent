"""Lot 292 — Suivi des conversations liées aux rappels de RDV (Centre de Messagerie → onglet « Suivi des RDV »).

Pour un compte (le code client du RDV, ex. CMCO), liste les patients à qui un rappel a été envoyé récemment, avec leur fil de
discussion WhatsApp (rappel, réponses du patient, réponse automatique de Liluvine). Lecture seule, réservée aux
administrateurs et superviseurs.

Rapprochement patient ↔ messages : par les 8 derniers chiffres du numéro (un numéro peut être stocké avec ou sans indicatif).
Performances (règle 7) : une agrégation pour les comptes, UNE lecture des RDV et UNE lecture des messages pour la liste (jamais une
lecture par patient), regroupement en mémoire.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Query

from routes.planning_report_rdv import est_demande_report, meme_numero
from routes.planning_report_rdv import chiffres as _chiffres

logger = logging.getLogger("sawali.planning_suivi_rdv")

JOURS_CHOIX = (1, 3, 7, 14, 30)      # périodes proposées dans la liste déroulante de l'écran
MAX_PATIENTS = 150                   # fils renvoyés au plus
MAX_MESSAGES_FIL = 200


def derniers8(valeur: Any) -> str:
    """Clé de rapprochement d'un numéro : ses 8 derniers chiffres (vide si numéro trop court)."""
    c = _chiffres(valeur)
    return c[-8:] if len(c) >= 8 else ""


def variantes_numero(valeur: Any, indicatif: str = "226") -> List[str]:
    """Écritures possibles du même numéro dans `phone_digits` : complet, avec indicatif, sans indicatif."""
    c = _chiffres(valeur)
    d8 = derniers8(valeur)
    return sorted({v for v in (c, d8, f"{indicatif}{d8}" if d8 else "") if v})


def _horodatage(iso: Any) -> Optional[datetime]:
    """Date ISO → datetime (UTC si sans fuseau) ; None si illisible."""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def forme_message(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Message du fil : sens, texte (ou type de média), date, état de remise, et s'il vient de Liluvine."""
    corps = str(doc.get("body") or "").strip()
    if not corps:
        corps = {"image": "📷 Image", "audio": "🎤 Message vocal", "voice": "🎤 Message vocal", "document": "📄 Document",
                 "video": "🎬 Vidéo"}.get(doc.get("message_type") or "", "…")
    return {"id": doc.get("id"), "sens": "entrant" if doc.get("direction") == "inbound" else "sortant", "texte": corps[:2000],
            "date": doc.get("received_at") or doc.get("sent_at") or doc.get("created_at"),
            "statut": doc.get("wa_status") or doc.get("status"),
            "liluvine": bool(doc.get("auto_reply") or doc.get("ai_generated")),
            "commande": doc.get("command")}


def resume_fil(rdv: Dict[str, Any], messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Une ligne de la liste des fils : patient, RDV, état du rappel, nombre de messages, dernier message, signaux utiles."""
    apres = [m for m in messages if (m.get("date") or "") >= (rdv.get("reminder_sent_at") or "")]
    entrants = [m for m in apres if m["sens"] == "entrant"]
    dernier = messages[-1] if messages else None
    return {"telephone": rdv.get("patient_phone"), "cle": derniers8(rdv.get("patient_phone")), "patient": rdv.get("patient"),
            "medecin": rdv.get("medecin"), "code": rdv.get("code_clinique"), "rdv": rdv.get("start_at"),
            "rappel_le": rdv.get("reminder_sent_at"), "rappel_statut": rdv.get("reminder_status"),
            "a_repondu": bool(entrants), "demande_report": any(est_demande_report(m["texte"]) for m in entrants),
            "reponse_auto_le": rdv.get("report_reponse_at"),
            "nb_messages": len(messages),
            "dernier": ({"sens": dernier["sens"], "texte": dernier["texte"][:140], "date": dernier["date"]} if dernier else None)}


def attach_planning_suivi_routes(*, api, db, get_current_user, is_admin_like: Callable[[dict], bool]):
    async def _admin(user: dict = Depends(get_current_user)) -> dict:
        if not is_admin_like(user):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")
        return user

    def _depuis(jours: int) -> str:
        if jours not in JOURS_CHOIX:
            jours = 7
        return (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()

    @api.get("/admin/planning/suivi/comptes", tags=["Admin — Suivi RDV"])
    async def suivi_comptes(user: dict = Depends(_admin)):
        """Comptes (codes client des RDV) pour lesquels des rappels ont été envoyés, avec leurs compteurs."""
        lignes = await db.planning_appointments.aggregate([
            {"$match": {"reminder_sent_at": {"$exists": True, "$ne": None}, "code_clinique": {"$nin": [None, "", "manual"]}}},
            {"$group": {"_id": "$code_clinique", "rappels": {"$sum": 1}, "dernier": {"$max": "$reminder_sent_at"}}},
            {"$sort": {"_id": 1}},
        ]).to_list(200)
        return {"comptes": [{"code": l["_id"], "rappels": l["rappels"], "dernier_rappel": l["dernier"]} for l in lignes],
                "jours_choix": list(JOURS_CHOIX)}

    @api.get("/admin/planning/suivi/fils", tags=["Admin — Suivi RDV"])
    async def suivi_fils(code: str = Query("", max_length=40), jours: int = 7, user: dict = Depends(_admin)):
        """Fils de discussion des patients rappelés dans la période (code vide = tous les comptes)."""
        depuis = _depuis(jours)
        filtre: Dict[str, Any] = {"reminder_sent_at": {"$gte": depuis}}
        if code.strip():
            filtre["code_clinique"] = {"$regex": f"^{__import__('re').escape(code.strip())}$", "$options": "i"}
        rdvs = await db.planning_appointments.find(
            filtre, {"_id": 0, "id": 1, "patient": 1, "medecin": 1, "code_clinique": 1, "patient_phone": 1, "start_at": 1,
                     "reminder_sent_at": 1, "reminder_status": 1, "report_reponse_at": 1},
        ).sort("reminder_sent_at", -1).to_list(600)
        # Un fil par patient : le rappel le plus récent de chaque numéro
        par_cle: Dict[str, Dict[str, Any]] = {}
        for r in rdvs:
            cle = derniers8(r.get("patient_phone"))
            if cle and cle not in par_cle:
                par_cle[cle] = r
        retenus = list(par_cle.values())[:MAX_PATIENTS]
        # UNE lecture des messages de tous ces numéros, regroupés ensuite en mémoire
        variantes = sorted({v for r in retenus for v in variantes_numero(r.get("patient_phone"))})
        docs = await db.whatsapp_messages.find(
            {"phone_digits": {"$in": variantes}, "created_at": {"$gte": depuis}},
            {"_id": 0, "id": 1, "direction": 1, "body": 1, "message_type": 1, "phone_digits": 1, "received_at": 1, "sent_at": 1,
             "created_at": 1, "wa_status": 1, "status": 1, "auto_reply": 1, "ai_generated": 1, "command": 1},
        ).sort("created_at", 1).to_list(5000)
        messages: Dict[str, List[Dict[str, Any]]] = {}
        for d in docs:
            messages.setdefault(derniers8(d.get("phone_digits")), []).append(forme_message(d))
        fils = [resume_fil(r, messages.get(derniers8(r.get("patient_phone")), [])) for r in retenus]
        fils.sort(key=lambda f: (f["dernier"] or {}).get("date") or f["rappel_le"] or "", reverse=True)
        return {"fils": fils, "jours": jours if jours in JOURS_CHOIX else 7, "code": code.strip()}

    @api.get("/admin/planning/suivi/fil", tags=["Admin — Suivi RDV"])
    async def suivi_fil(telephone: str = Query(..., max_length=32), jours: int = 7, user: dict = Depends(_admin)):
        """Conversation complète d'un patient (rappel inclus) : messages du patient, de Liluvine et du rappel."""
        cle = derniers8(telephone)
        if not cle:
            raise HTTPException(status_code=400, detail="Numéro invalide")
        depuis = _depuis(jours)
        docs = await db.whatsapp_messages.find(
            {"phone_digits": {"$in": variantes_numero(telephone)}, "created_at": {"$gte": depuis}},
            {"_id": 0}).sort("created_at", 1).to_list(MAX_MESSAGES_FIL)
        messages = [forme_message(d) for d in docs]
        # Rappel : si le message du rappel n'est pas dans le fil (non journalisé), on l'ajoute pour que le fil soit complet
        rdvs = await db.planning_appointments.find(
            {"reminder_sent_at": {"$gte": depuis}}, {"_id": 0, "patient_phone": 1, "patient": 1, "medecin": 1, "start_at": 1,
                                                    "reminder_sent_at": 1, "reminder_status": 1, "code_clinique": 1},
        ).sort("reminder_sent_at", 1).to_list(600)
        for r in rdvs:
            if derniers8(r.get("patient_phone")) != cle:
                continue
            quand = r["reminder_sent_at"]
            t_rappel = _horodatage(quand)
            deja = any(m["sens"] == "sortant" and _horodatage(m.get("date")) and t_rappel
                       and abs((_horodatage(m["date"]) - t_rappel).total_seconds()) < 180 for m in messages)
            if not deja:
                messages.append({"id": f"rappel-{quand}", "sens": "sortant", "date": quand, "statut": r.get("reminder_status"),
                                 "liluvine": True, "commande": "rappel_rdv", "texte": f"🔔 Rappel de RDV envoyé — {r.get('medecin') or ''}".strip()})
        messages.sort(key=lambda m: str(m.get("date") or ""))
        return {"telephone": telephone, "messages": messages[-MAX_MESSAGES_FIL:]}

    return {}
