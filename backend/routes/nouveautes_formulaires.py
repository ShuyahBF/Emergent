"""Lot 41 — Nouvelles données reçues sur les formulaires et les sondages.

Pour chaque utilisateur :
  - bulles de la barre latérale sur « Formulaires & Sondages » : VERTE = nouvelles
    soumissions de formulaires, BLEUE = nouvelles réponses aux sondages ;
  - à l'ouverture du module, PUCE VERTE sur chaque formulaire / sondage qui a reçu des
    données que l'utilisateur n'a pas encore consultées.

« Nouvelle » = reçue (ou modifiée par le répondant) après la dernière consultation, par cet
utilisateur, des données de ce formulaire (page Données / Stats) ou de ce sondage (page
Résultats). Point de départ : la première ouverture du portail après la mise en place
(les données plus anciennes ne sont pas signalées).

Périmètre : Admin et Superviseur → tous les formulaires et sondages ; les autres → ceux de
leur compte client, seulement si la fonction « Formulaires et Sondages » est active.

  GET  /api/me/formulaires-sondages/nouveautes   {formulaires, sondages, par_formulaire, par_sondage}
  POST /api/me/formulaires-sondages/vu           {type: formulaire|sondage, id}

Collection : fs_vus {user_id, depuis, formulaires: {id: iso}, sondages: {id: iso}}.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from fastapi import Depends
from pydantic import BaseModel, Field

CLE_FONCTION = "forms_surveys"
CHAMPS = {"formulaire": ("formulaires", "forms", "form_submissions", "form_id"),
          "sondage": ("sondages", "wa_surveys", "wa_survey_responses", "survey_id")}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


class Vu(BaseModel):
    type: Literal["formulaire", "sondage"]
    id: str = Field(..., min_length=1, max_length=100)


def attach_nouveautes_formulaires_routes(
    *, api, db, get_current_user,
    fonction_active: Optional[Callable[[dict, str], Awaitable[bool]]] = None,
    is_admin_like: Callable[[dict], bool] = lambda u: u.get("role") in ("admin", "superviseur"),
) -> Dict[str, Any]:

    def _comptes(user: dict) -> List[str]:
        return list({x for x in (user.get("parent_client_id"), user.get("client_id"), user.get("id")) if x})

    async def _etat(user: dict) -> dict:
        """Point de départ et dernières consultations ; créé à la première lecture."""
        doc = await db.fs_vus.find_one({"user_id": user["id"]}, {"_id": 0})
        if not doc:
            doc = {"user_id": user["id"], "depuis": _maintenant(), "formulaires": {}, "sondages": {}}
            await db.fs_vus.update_one({"user_id": user["id"]}, {"$setOnInsert": doc}, upsert=True)
        return doc

    async def _nouveaux(user: dict, genre: str, depuis: str, vus: Dict[str, str]) -> Dict[str, int]:
        """{id: nombre de données reçues depuis la dernière consultation} (seulement > 0)."""
        _, coll_items, coll_data, cle = CHAMPS[genre]
        q_items = {} if is_admin_like(user) else {"client_id": {"$in": _comptes(user)}}
        ids = [x["id"] async for x in db[coll_items].find(q_items, {"_id": 0, "id": 1})]
        if not ids:
            return {}
        recent = {"$or": [{"created_at": {"$gt": depuis}}, {"updated_at": {"$gt": depuis}}]}
        resultat: Dict[str, int] = {}
        async for g in db[coll_data].aggregate([
            {"$match": {cle: {"$in": ids}, **recent}},
            {"$group": {"_id": f"${cle}", "n": {"$sum": 1},
                        "dernier": {"$max": {"$ifNull": ["$updated_at", "$created_at"]}}}},
        ]):
            vu = vus.get(g["_id"])
            if not vu:
                resultat[g["_id"]] = g["n"]
            elif (g.get("dernier") or "") > vu:
                n = await db[coll_data].count_documents(
                    {cle: g["_id"], "$or": [{"created_at": {"$gt": vu}}, {"updated_at": {"$gt": vu}}]})
                if n:
                    resultat[g["_id"]] = n
        return resultat

    async def nouveautes(user: dict) -> Dict[str, Any]:
        vide = {"formulaires": 0, "sondages": 0, "par_formulaire": {}, "par_sondage": {}}
        if fonction_active is not None and not await fonction_active(user, CLE_FONCTION):
            return vide
        etat = await _etat(user)
        pf = await _nouveaux(user, "formulaire", etat["depuis"], etat.get("formulaires") or {})
        ps = await _nouveaux(user, "sondage", etat["depuis"], etat.get("sondages") or {})
        return {"formulaires": sum(pf.values()), "sondages": sum(ps.values()), "par_formulaire": pf, "par_sondage": ps}

    @api.get("/me/formulaires-sondages/nouveautes", tags=["Formulaires"])
    async def lire(user: dict = Depends(get_current_user)):
        return await nouveautes(user)

    @api.post("/me/formulaires-sondages/vu", tags=["Formulaires"])
    async def marquer_vu(data: Vu, user: dict = Depends(get_current_user)):
        """Appelé à l'ouverture des données d'un formulaire ou des résultats d'un sondage."""
        await _etat(user)
        champ = CHAMPS[data.type][0]
        await db.fs_vus.update_one({"user_id": user["id"]}, {"$set": {f"{champ}.{data.id}": _maintenant()}})
        return {"ok": True}

    return {"nouveautes": nouveautes}
