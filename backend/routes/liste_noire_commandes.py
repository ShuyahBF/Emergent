# liste_noire_commandes.py — Lot 61 : liste noire des numéros interdits aux commandes « ! ».
#
# Un numéro inscrit ici ne peut plus utiliser AUCUNE commande Liluvine commençant par « ! »
# (ou « / ») : !garde, !meteo, !doc, !formulaire, !ticket, !synthese… Liluvine lui répond
# alors un message fixe, modifiable par l'administrateur (réglage global
# liluvine_commandes_bloquees_message). Pour éviter de « harceler » le numéro, ce message
# n'est renvoyé qu'une fois toutes les 10 minutes au plus.
#
# Les messages ordinaires (sans « ! ») de ce numéro restent reçus normalement.
# Administration → Paramètres → « ⛔ Liste noire des commandes « ! » ».
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import Body, Depends, HTTPException

# Message envoyé par défaut à un numéro bloqué
MESSAGE_DEFAUT = ("Désolé, les commandes Liluvine (« ! ») ne sont pas disponibles pour ce numéro. "
                  "Pour toute question, contactez SAWALI.")
# Délai minimal entre deux réponses au même numéro bloqué
INTERVALLE_REPONSE = timedelta(minutes=10)


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC)."""
    return datetime.now(timezone.utc)


def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def est_commande(texte: Optional[str]) -> bool:
    """Vrai si le texte est une commande Liluvine (commence par « ! » ou « / »)."""
    t = (texte or "").strip()
    return t.startswith("!") or t.startswith("/")


async def fiche_bloquee(db, telephone: Any) -> Optional[Dict[str, Any]]:
    """Fiche de liste noire active pour ce numéro (comparaison sur les 8 derniers chiffres), ou None."""
    chiffres = _chiffres(telephone)
    if len(chiffres) < 6:
        return None
    return await db.liluvine_commandes_bloquees.find_one(
        {"actif": True, "chiffres": {"$regex": re.escape(chiffres[-8:]) + "$"}}, {"_id": 0})


async def refuser_si_bloque(db, telephone: Any, texte: Optional[str],
                            envoyer: Optional[Callable[..., Awaitable[Any]]] = None) -> bool:
    """Si le message est une commande « ! » d'un numéro bloqué : répond le message de refus
    (au plus une fois toutes les 10 minutes) et renvoie True — la commande ne doit pas être traitée."""
    if not est_commande(texte):
        return False
    fiche = await fiche_bloquee(db, telephone)
    if not fiche:
        return False
    maintenant = _maintenant()
    derniere = fiche.get("derniere_reponse")
    deja_repondu = False
    if derniere:
        try:
            deja_repondu = maintenant - datetime.fromisoformat(derniere) < INTERVALLE_REPONSE
        except ValueError:
            deja_repondu = False
    # Compteur des tentatives (affiché dans l'administration)
    maj: Dict[str, Any] = {"derniere_tentative": maintenant.isoformat(),
                           "derniere_commande": (texte or "").strip()[:60]}
    if not deja_repondu and envoyer is not None:
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_commandes_bloquees_message": 1}) or {}
        message = (s.get("liluvine_commandes_bloquees_message") or "").strip() or MESSAGE_DEFAUT
        try:
            await envoyer(telephone, message)
            maj["derniere_reponse"] = maintenant.isoformat()
        except Exception:  # noqa: BLE001 — l'envoi échoue : la commande reste bloquée
            pass
    await db.liluvine_commandes_bloquees.update_one(
        {"chiffres": fiche["chiffres"]}, {"$set": maj, "$inc": {"tentatives": 1}})
    return True


def setup_liste_noire_commandes_routes(*, db, api, get_current_user) -> None:
    """Routes d'administration de la liste noire (administrateurs et superviseurs)."""

    def _exiger_admin(user: dict) -> None:
        """Réservé aux administrateurs et superviseurs."""
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")

    @api.get("/admin/liluvine-commandes-bloquees", tags=["Admin — Liluvine"])
    async def lister(user: dict = Depends(get_current_user)):
        """Numéros bloqués (actifs d'abord) et message de refus."""
        _exiger_admin(user)
        items = [x async for x in db.liluvine_commandes_bloquees.find({}, {"_id": 0}).sort([("actif", -1), ("le", -1)])]
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "liluvine_commandes_bloquees_message": 1}) or {}
        return {"items": items, "message": s.get("liluvine_commandes_bloquees_message") or "",
                "message_defaut": MESSAGE_DEFAUT}

    @api.post("/admin/liluvine-commandes-bloquees", tags=["Admin — Liluvine"])
    async def ajouter(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Ajoute (ou réactive) un numéro dans la liste noire."""
        _exiger_admin(user)
        chiffres = _chiffres(payload.get("telephone"))
        if len(chiffres) < 8:
            raise HTTPException(status_code=400, detail="Numéro invalide (indicatif compris, ex. +226 70 00 00 00)")
        await db.liluvine_commandes_bloquees.update_one(
            {"chiffres": chiffres},
            {"$set": {"chiffres": chiffres, "telephone": f"+{chiffres}", "actif": True,
                      "nom": str(payload.get("nom") or "").strip()[:120],
                      "motif": str(payload.get("motif") or "").strip()[:300],
                      "le": _maintenant().isoformat(), "par": user.get("full_name") or user.get("email")},
             "$setOnInsert": {"tentatives": 0}},
            upsert=True)
        return {"ok": True, "chiffres": chiffres}

    @api.delete("/admin/liluvine-commandes-bloquees/{chiffres}", tags=["Admin — Liluvine"])
    async def retirer(chiffres: str, user: dict = Depends(get_current_user)):
        """Retire un numéro de la liste noire (il retrouve l'accès aux commandes)."""
        _exiger_admin(user)
        r = await db.liluvine_commandes_bloquees.update_one(
            {"chiffres": _chiffres(chiffres)},
            {"$set": {"actif": False, "retire_le": _maintenant().isoformat(),
                      "retire_par": user.get("full_name") or user.get("email")}})
        if not getattr(r, "matched_count", 0):
            raise HTTPException(status_code=404, detail="Numéro absent de la liste noire")
        return {"ok": True}

    @api.put("/admin/liluvine-commandes-bloquees/message", tags=["Admin — Liluvine"])
    async def modifier_message(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Message que Liluvine répond aux numéros bloqués (vide = message par défaut)."""
        _exiger_admin(user)
        message = str(payload.get("message") or "").strip()[:1000]
        await db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_commandes_bloquees_message": message}},
                                     upsert=True)
        return {"ok": True}
