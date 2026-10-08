# liluvine_partage.py — Lot 73 : « pour tout ce qui a trait à Liluvine, permettre à l'admin de définir, dans les
# Paramètres, ce qu'il partage avec un superviseur précis (ex. support@sawalismartsystems.com) ».
#
# Réglage : settings.global.liluvine_partage = { "<e-mail du superviseur>": ["agenda", "alertes", …] }
#   - superviseur ABSENT du réglage : rien ne change pour lui (il voit tout, comme avant) ;
#   - superviseur PRÉSENT : il ne voit que les éléments cochés (liste vide = rien de Liluvine).
# L'administrateur voit toujours tout. Le menu du portail suit ce réglage (/me/liluvine-partage) et l'agenda
# (pages + alertes d'appels) le contrôle aussi côté serveur.
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from fastapi import Body, Depends, HTTPException

# Éléments de Liluvine partageables (clé → libellé affiché dans les Paramètres)
ELEMENTS = {
    "agenda": "Agenda d'appels de Liluvine",
    "alertes": "Notifications « Liluvine appelle … »",
    "pro": "Liluvine PRO (assistant IA)",
    "historique": "Liluvine PRO — Historique",
    "bloques": "Messages WhatsApp bloqués (barrière anti-rafale)",   # lot 79.6
}


def est_admin(user: Dict[str, Any]) -> bool:
    """Administrateur (compte ou utilisateur suivi « Administrateur »)."""
    return user.get("role") in ("admin", "super_admin") or user.get("tracked_role") == "Administrateur"


def est_superviseur(user: Dict[str, Any]) -> bool:
    """Superviseur (compte ou utilisateur suivi « Superviseur »)."""
    return not est_admin(user) and (user.get("role") == "superviseur" or user.get("tracked_role") == "Superviseur")


def _config(s: Dict[str, Any]) -> Dict[str, List[str]]:
    """Réglage nettoyé : e-mails en minuscules, seules les clés connues."""
    brut = s.get("liluvine_partage") if isinstance(s.get("liluvine_partage"), dict) else {}
    return {str(k).strip().lower(): [c for c in (v or []) if c in ELEMENTS] for k, v in brut.items() if str(k).strip()}


def elements_partages(s: Dict[str, Any], user: Dict[str, Any]) -> Optional[Set[str]]:
    """Éléments de Liluvine visibles par cet utilisateur ; None = aucune restriction (tout, comme avant)."""
    if not est_superviseur(user):
        return None
    cles = _config(s).get(str(user.get("email") or "").strip().lower())
    return None if cles is None else set(cles)


async def verifier_element(db, user: Dict[str, Any], cle: str) -> None:
    """Lève 403 si l'élément de Liluvine n'est pas partagé avec ce superviseur."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    autorises = elements_partages(s, user)
    if autorises is not None and cle not in autorises:
        raise HTTPException(status_code=403, detail=f"« {ELEMENTS[cle]} » n'est pas partagé avec votre compte "
                                                    "(Paramètres → Liluvine — partage avec les superviseurs)")


async def lister_superviseurs(db) -> List[Dict[str, str]]:
    """Comptes superviseurs et utilisateurs suivis « Superviseur » (e-mail + nom), sans doublon."""
    vus: Dict[str, Dict[str, str]] = {}
    async for u in db.users.find({"role": "superviseur"}, {"_id": 0, "email": 1, "full_name": 1}):
        if u.get("email"):
            vus[u["email"].lower()] = {"email": u["email"].lower(), "nom": u.get("full_name") or u["email"]}
    async for t in db.tracked_users.find({"role": "Superviseur"}, {"_id": 0, "email": 1, "name": 1}):
        if t.get("email") and t["email"].lower() not in vus:
            vus[t["email"].lower()] = {"email": t["email"].lower(), "nom": t.get("name") or t["email"]}
    return sorted(vus.values(), key=lambda x: x["nom"].lower())


def setup_liluvine_partage_routes(*, db, api, get_current_user) -> None:
    """Routes : lecture pour le portail (/me), lecture et modification pour l'administrateur (/admin)."""

    @api.get("/me/liluvine-partage", tags=["Liluvine — partage"])
    async def mon_partage(user: dict = Depends(get_current_user)):
        """Ce que le portail doit afficher dans le menu Liluvine pour l'utilisateur connecté."""
        s = await db.settings.find_one({"_id": "global"}) or {}
        autorises = elements_partages(s, user)
        return {"restreint": autorises is not None,
                "elements": sorted(ELEMENTS) if autorises is None else sorted(autorises)}

    @api.get("/admin/liluvine-partage", tags=["Liluvine — partage"])
    async def lire(user: dict = Depends(get_current_user)):
        """Superviseurs connus et ce qui est partagé avec chacun (rubrique des Paramètres)."""
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        s = await db.settings.find_one({"_id": "global"}) or {}
        config = _config(s)
        superviseurs = await lister_superviseurs(db)
        # Un e-mail réglé à la main mais sans compte connu reste affiché
        for email in config:
            if not any(x["email"] == email for x in superviseurs):
                superviseurs.append({"email": email, "nom": email + " (compte introuvable)"})
        return {"elements": ELEMENTS,
                "superviseurs": [{**x, "partage": config.get(x["email"])} for x in superviseurs]}

    @api.put("/admin/liluvine-partage", tags=["Liluvine — partage"])
    async def ecrire(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """{email, elements: [...]} restreint ce superviseur ; {email, elements: null} lui rend tout (par défaut)."""
        if not est_admin(user):
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        email = str((payload or {}).get("email") or "").strip().lower()
        if "@" not in email or len(email) > 200:
            raise HTTPException(status_code=422, detail="Adresse e-mail du superviseur invalide")
        elements = (payload or {}).get("elements")
        s = await db.settings.find_one({"_id": "global"}) or {}
        config = _config(s)
        if elements is None:
            config.pop(email, None)
        else:
            if not isinstance(elements, list) or any(e not in ELEMENTS for e in elements):
                raise HTTPException(status_code=422, detail="Élément de Liluvine inconnu")
            config[email] = sorted(set(elements))
        await db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_partage": config}}, upsert=True)
        return {"ok": True, "email": email, "partage": config.get(email)}
