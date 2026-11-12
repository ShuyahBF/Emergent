"""Lots 374 / 375 — API des automations vocales sur Alexa : rappels programmés, rendez-vous qui approchent, messages WhatsApp reçus
(voir services/rappels_vocaux.py). Accessible à l'administrateur ET au Superviseur.

  GET    /api/admin/rappels-vocaux             liste (en attente d'abord) + état d'Alexa
  POST   /api/admin/rappels-vocaux             crée une règle {declencheur, texte, quand (GMT) + repetition | minutes_avant}
  PUT    /api/admin/rappels-vocaux/{id}        active / désactive {actif}
  POST   /api/admin/rappels-vocaux/{id}/tester annonce la phrase de la règle maintenant (avec des exemples)
  DELETE /api/admin/rappels-vocaux/{id}        supprime une règle
  POST   /api/admin/rappels-vocaux/tester      annonce immédiatement une phrase (essai d'Alexa)
Réservé aux administrateurs et superviseurs.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Body, Depends, HTTPException

from services import rappels_vocaux as rv
from services.alexa import alexa_annoncer


def setup_rappels_vocaux_routes(app, db, get_current_user):
    api = app

    def _admin(user: dict) -> None:
        if (user or {}).get("role") not in ("admin", "superviseur"):
            raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")

    @api.get("/admin/rappels-vocaux", tags=["Rappels vocaux"])
    async def lister_rappels(user: dict = Depends(get_current_user)):
        _admin(user)
        reglages = await db.settings.find_one({"_id": "global"}, {"_id": 0, "alexa_enabled": 1, "alexa_webhook_url": 1}) or {}
        pret = bool(reglages.get("alexa_enabled")) and str(reglages.get("alexa_webhook_url") or "").startswith(("http://", "https://"))
        return {"alexa_pret": pret, "repetitions": rv.REPETITIONS, "declencheurs": rv.DECLENCHEURS, "jetons": rv.JETONS,
                "minutes_avant_max": rv.MINUTES_AVANT_MAX, "texte_max": rv.TEXTE_MAX, "rappels": await rv.lister(db)}

    @api.post("/admin/rappels-vocaux", tags=["Rappels vocaux"])
    async def programmer_rappel(donnees: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _admin(user)
        try:
            return await rv.ajouter(db, donnees, auteur=str(user.get("email") or user.get("id") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @api.put("/admin/rappels-vocaux/{rappel_id}", tags=["Rappels vocaux"])
    async def activer_rappel(rappel_id: str, donnees: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        _admin(user)
        if "actif" not in donnees:
            raise HTTPException(status_code=422, detail="Champ « actif » requis")
        if not await rv.basculer(db, rappel_id, bool(donnees["actif"])):
            raise HTTPException(status_code=404, detail="Règle introuvable")
        return {"ok": True}

    @api.post("/admin/rappels-vocaux/{rappel_id}/tester", tags=["Rappels vocaux"])
    async def tester_regle(rappel_id: str, user: dict = Depends(get_current_user)):
        _admin(user)
        try:
            ok, motif, phrase = await rv.tester(db, rappel_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Règle introuvable")
        if not ok:
            raise HTTPException(status_code=502, detail=motif)
        return {"ok": True, "phrase": phrase}

    @api.delete("/admin/rappels-vocaux/{rappel_id}", tags=["Rappels vocaux"])
    async def supprimer_rappel(rappel_id: str, user: dict = Depends(get_current_user)):
        _admin(user)
        if not await rv.supprimer(db, rappel_id):
            raise HTTPException(status_code=404, detail="Rappel introuvable")
        return {"ok": True}

    @api.post("/admin/rappels-vocaux/tester", tags=["Rappels vocaux"])
    async def tester_alexa(donnees: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_user)):
        _admin(user)
        texte = " ".join(str(donnees.get("texte") or "Ceci est un test du rappel vocal de SAWALI.").split())[: rv.TEXTE_MAX]
        ok, motif = await alexa_annoncer(db, texte)
        if not ok:
            raise HTTPException(status_code=502, detail=motif)
        return {"ok": True}
