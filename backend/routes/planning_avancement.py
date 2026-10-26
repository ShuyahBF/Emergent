"""Lot 309 — « Avancer / Reculer » dans les listes du jour d'un médecin (Planning).

Chaque médecin a deux listes par jour : la liste AVEC rendez-vous (classée par heure) et la liste SANS rendez-vous (classée par numéro d'ordre,
mise à jour par le secrétariat médical). Dans chaque liste, un curseur marque le patient « en consultation » :
  - les patients avant le curseur sont « fait » (terminés) ; le patient du curseur est « en_cours » ; les suivants attendent ;
  - « Avancer » termine le patient en cours et appelle le suivant ; « Reculer » rappelle le patient précédent.
L'état est gardé sur chaque RDV (champ `etat_consult` : « fait » | « en_cours » | absent) — aucune nouvelle collection.
L'écran TV du hall l'affiche (« En consultation »).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Body, Depends, HTTPException

LISTES = ("rdv", "sans_rdv")
SENS = ("avant", "arriere")


def calculer_avancement(etats: List[Optional[str]], sens: str) -> Dict[int, Optional[str]]:
    """`etats` : état actuel de chaque patient de la liste, dans l'ordre d'appel (None = en attente).
    Retourne {position: nouvel état} pour les seuls patients dont l'état change (None = redevient en attente)."""
    n = len(etats)
    en_cours = next((i for i, e in enumerate(etats) if e == "en_cours"), None)
    maj: Dict[int, Optional[str]] = {}
    if sens == "avant":
        if en_cours is not None:
            maj[en_cours] = "fait"
            debut = en_cours + 1
        else:
            debut = 0
        cible = next((i for i in range(debut, n) if etats[i] != "fait"), None)
        if cible is not None:
            maj[cible] = "en_cours"
    else:
        if en_cours is not None:
            maj[en_cours] = None                                   # le patient en cours retourne en attente
            fin = en_cours
        else:
            fin = n
        precedent = next((i for i in range(fin - 1, -1, -1) if etats[i] == "fait"), None)
        if precedent is not None:
            maj[precedent] = "en_cours"
    return maj


def attach_planning_avancement_routes(*, api, db, get_current_user, is_admin_like: Callable[[dict], bool],
                                      is_super_admin: Callable[[dict], bool], resolve_visible_client_ids):
    @api.post("/me/planning/avancer", tags=["Portail Client — Planning"])
    async def planning_avancer(corps: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Avance ou recule dans la liste du jour d'un médecin. Corps : {liste: "rdv"|"sans_rdv", sens: "avant"|"arriere", date: "AAAA-MM-JJ",
        medecin_id (administrateurs seulement)}. Un médecin n'agit que sur SES listes."""
        liste, sens = str(corps.get("liste") or ""), str(corps.get("sens") or "")
        if liste not in LISTES or sens not in SENS:
            raise HTTPException(status_code=400, detail="Paramètres invalides (liste : rdv | sans_rdv ; sens : avant | arriere)")
        try:
            jour = datetime.strptime(str(corps.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (AAAA-MM-JJ)")
        est_medecin = (user.get("tracked_role") or "") == "Médecin"
        if not est_medecin and not is_admin_like(user):
            raise HTTPException(status_code=403, detail="Réservé au médecin (ses propres listes) et aux administrateurs")
        medecin_id = user.get("id") if est_medecin else str(corps.get("medecin_id") or "")
        if not medecin_id:
            raise HTTPException(status_code=400, detail="Choisissez un médecin")
        # Rattachement du médecin : son identifiant, son e-mail (casse libre) ou son identifiant d'utilisateur suivi
        cible = await db.users.find_one({"id": medecin_id}, {"_id": 0, "id": 1, "email": 1}) or {}
        ou: List[Dict[str, Any]] = [{"medecin_id": medecin_id}]
        if cible.get("email"):
            ou.append({"medecin_email": {"$regex": f"^{re.escape(cible['email'].lower())}$", "$options": "i"}})
        tu = await db.tracked_users.find_one({"user_account_id": medecin_id}, {"_id": 0, "id": 1})
        if tu and tu.get("id"):
            ou.append({"medecin_id": tu["id"]})
        debut, fin = jour.isoformat(), (jour + timedelta(days=1)).isoformat()
        if liste == "rdv":
            jour_q: Dict[str, Any] = {"is_rdv": {"$ne": 0}, "start_at": {"$gte": debut, "$lt": fin}}
        else:
            jour_q = {"is_rdv": 0, "walk_in_list": {"$regex": f"^{jour.strftime('%y%m%d')}:"}}
        filtre: Dict[str, Any] = {"$and": [{"$or": ou}, jour_q]}
        if not est_medecin and not is_super_admin(user):
            filtre["tenant_id"] = {"$in": list(await resolve_visible_client_ids(user))}      # un administrateur reste dans son périmètre
        docs = await db.planning_appointments.find(filtre, {"_id": 0, "id": 1, "etat_consult": 1, "start_at": 1, "numero_ordre": 1, "patient": 1}).to_list(500)
        docs.sort(key=(lambda d: str(d.get("start_at") or "")) if liste == "rdv" else (lambda d: int(d.get("numero_ordre") or 0)))
        if not docs:
            raise HTTPException(status_code=404, detail="Aucun patient dans cette liste pour ce jour")
        maj = calculer_avancement([d.get("etat_consult") for d in docs], sens)
        for position, etat in maj.items():
            if etat is None:
                await db.planning_appointments.update_one({"id": docs[position]["id"]}, {"$unset": {"etat_consult": ""}})
            else:
                await db.planning_appointments.update_one({"id": docs[position]["id"]}, {"$set": {"etat_consult": etat, "etat_consult_at": datetime.now(timezone.utc).isoformat()}})
        nouveaux = [maj[i] if i in maj else d.get("etat_consult") for i, d in enumerate(docs)]
        return {"ok": True, "liste": liste, "etats": [{"id": d["id"], "etat_consult": nouveaux[i]} for i, d in enumerate(docs)]}

    return {}
