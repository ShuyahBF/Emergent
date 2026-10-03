"""Lot 55 — Dernière connexion, adresse IP et historique des connexions des utilisateurs suivis ;
blocage ou autorisation d'une IP par compte (logique dans backend/connexions_ip.py).

  GET  /api/admin/tracked-users/connexions?client_id=
       → {"items": {tracked_user_id: {derniere_connexion, ip, ip_statut, appareil, methode, compte}}}
  GET  /api/admin/tracked-users/{tu_id}/connexions?page=1&ip=
       → historique paginé (50 par page, les plus récentes d'abord, filtre par IP), IP bloquées
         et de confiance du compte, dernières actions, IP de la session de l'appelant
  POST /api/admin/tracked-users/{tu_id}/connexions/bloquer    {"ip": "...", "globale": false, "libelle": "..."}
  POST /api/admin/tracked-users/{tu_id}/connexions/autoriser  {"ip": "...", "libelle": "..."}
  GET  /api/admin/connexions/sites-bloques                    (super-admin) sites bloqués sur toute la
       plateforme : IP, libellé, auteur, date, tentatives refusées depuis
  POST /api/admin/connexions/sites-bloques/autoriser          (super-admin) {"ip": "..."}

Droits : Admin et Superviseur seulement (un client reçoit 403), pour les comptes qu'ils gèrent
déjà sur la page « Utilisateurs suivis » : l'Admin voit tous les utilisateurs suivis (même règle
que GET /admin/tracked-users) ; un Superviseur rattaché à un client ne gère que les utilisateurs
suivis de ce client. Le blocage « pour tous les comptes » est réservé au super-admin.
Garde-fous : impossible de bloquer l'IP de sa propre session en cours ; le super-admin ne peut
jamais être bloqué.
"""
from __future__ import annotations

import ipaddress
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

import connexions_ip as cip
from auth import get_current_user, get_super_admin
from ip_client import ip_reelle

router = APIRouter(tags=["Utilisateurs suivis — connexions et IP (lot 55)"])

ROLES_AUTORISES = ("admin", "superviseur")


class IpPayload(BaseModel):
    ip: str = Field(..., min_length=2, max_length=64)
    globale: bool = False
    libelle: Optional[str] = Field(None, max_length=120)   # « Libellé du site » (facultatif)


async def gestionnaire(user: dict = Depends(get_current_user)) -> dict:
    """Admin ou Superviseur (même règle d'accès que la page) ; un client reçoit 403."""
    if user.get("role") not in ROLES_AUTORISES:
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur et au superviseur")
    return user


def _perimetre(user: dict) -> Optional[set]:
    """Clients gérés : None = tous (Admin, Superviseur de la plateforme) ; sinon son client."""
    if user.get("role") == "admin":
        return None
    rattache = {v for v in (user.get("client_id"), user.get("parent_client_id")) if v}
    return (rattache | {user.get("id")}) if rattache else None


def _compte_de(tracked: dict) -> Optional[str]:
    return tracked.get("user_account_id") or tracked.get("user_id")


async def _suivi_gere(tu_id: str, user: dict) -> Dict[str, Any]:
    """Utilisateur suivi géré par l'appelant + son compte de connexion (404 sinon)."""
    b = cip._base()
    tracked = await b.tracked_users.find_one({"id": tu_id}, {"_id": 0})
    perimetre = _perimetre(user)
    if not tracked or (perimetre is not None and tracked.get("client_id") not in perimetre):
        raise HTTPException(status_code=404, detail="Utilisateur suivi introuvable")
    compte = None
    if _compte_de(tracked):
        compte = await b.users.find_one({"id": _compte_de(tracked)},
                                        {"_id": 0, "id": 1, "email": 1, "role": 1, "full_name": 1,
                                         "client_id": 1, "parent_client_id": 1})
    return {"tracked": tracked, "compte": compte}


def _ip_valide(ip: str) -> str:
    ip = (ip or "").strip()
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        raise HTTPException(status_code=400, detail="Adresse IP invalide")


@router.get("/admin/tracked-users/connexions")
async def connexions_utilisateurs_suivis(client_id: Optional[str] = None, user: dict = Depends(gestionnaire)):
    """Dernière connexion (date, IP) de chaque utilisateur suivi, avec le statut de l'IP."""
    b = cip._base()
    q: Dict[str, Any] = {"client_id": client_id} if client_id else {}
    perimetre = _perimetre(user)
    if perimetre is not None:
        q["client_id"] = client_id if client_id in perimetre else {"$in": list(perimetre)}
    suivis = await b.tracked_users.find(q, {"_id": 0, "id": 1, "user_account_id": 1, "user_id": 1}).to_list(5000)
    comptes = {t["id"]: _compte_de(t) for t in suivis}
    dernieres = await cip.dernieres_connexions([c for c in comptes.values() if c])
    statuts = await cip.statut_ips([(d.get("ip"), c) for c, d in dernieres.items()])
    items = {}
    for tid, compte in comptes.items():
        d = dernieres.get(compte) if compte else None
        items[tid] = {"compte": bool(compte), "derniere_connexion": (d or {}).get("date"), "ip": (d or {}).get("ip"),
                      "appareil": (d or {}).get("appareil"), "methode": (d or {}).get("methode"),
                      "ip_statut": (statuts.get(((d or {}).get("ip"), compte)) or {}).get("statut"),
                      "ip_libelle": (statuts.get(((d or {}).get("ip"), compte)) or {}).get("libelle"),
                      "ip_portee": (statuts.get(((d or {}).get("ip"), compte)) or {}).get("portee")}
    return {"items": items}


@router.get("/admin/tracked-users/{tu_id}/connexions")
async def historique_connexions(tu_id: str, request: Request, page: int = Query(1, ge=1),
                                ip: Optional[str] = None, user: dict = Depends(gestionnaire)):
    s = await _suivi_gere(tu_id, user)
    compte = s["compte"]
    base = {"utilisateur": {"id": tu_id, "nom": s["tracked"].get("name"), "email": s["tracked"].get("email")},
            "ip_courante": ip_reelle(request), "peut_bloquer_global": cip.est_super_admin(user)}
    if not compte:
        return {**base, "compte": None, "items": [], "total": 0, "page": 1, "pages": 1, "par_page": cip.PAR_PAGE,
                "bloquees": [], "confiance": [], "actions": []}
    hist = await cip.historique(compte["id"], page, ip)
    regles = await cip.regles_du_compte(compte["id"])
    return {**base, "compte": {"id": compte["id"], "email": compte.get("email"),
                                "super_admin": cip.est_super_admin(compte)},
            **hist, **regles, "actions": await cip.actions_recentes(compte["id"])}


@router.post("/admin/tracked-users/{tu_id}/connexions/bloquer")
async def bloquer_ip(tu_id: str, payload: IpPayload, request: Request, user: dict = Depends(gestionnaire)):
    s = await _suivi_gere(tu_id, user)
    compte = s["compte"]
    if not compte:
        raise HTTPException(status_code=404, detail="Cet utilisateur n'a pas de compte de connexion")
    ip = _ip_valide(payload.ip)
    # Garde-fous
    if cip.est_super_admin(compte):
        raise HTTPException(status_code=403, detail="Le super-administrateur ne peut jamais être bloqué.")
    ip_admin = ip_reelle(request)
    if ip_admin and ip == ip_admin:
        raise HTTPException(status_code=400,
                            detail="Impossible de bloquer l'adresse IP de votre propre session en cours.")
    if payload.globale and not cip.est_super_admin(user):
        raise HTTPException(status_code=403,
                            detail="Le blocage pour tous les comptes est réservé au super-administrateur.")
    return await cip.bloquer(ip, compte, user, ip_admin, globale=payload.globale, libelle=payload.libelle)


@router.post("/admin/tracked-users/{tu_id}/connexions/autoriser")
async def autoriser_ip(tu_id: str, payload: IpPayload, request: Request, user: dict = Depends(gestionnaire)):
    s = await _suivi_gere(tu_id, user)
    compte = s["compte"]
    if not compte:
        raise HTTPException(status_code=404, detail="Cet utilisateur n'a pas de compte de connexion")
    ip = _ip_valide(payload.ip)
    globale = await cip.blocage_global(ip)
    if globale and not cip.est_super_admin(user):
        raise HTTPException(status_code=403,
                            detail="Cette adresse est bloquée pour tous les comptes : seul le super-administrateur peut lever ce blocage.")
    return await cip.autoriser(ip, compte, user, ip_reelle(request), lever_globale=globale, libelle=payload.libelle)


@router.get("/admin/connexions/sites-bloques")
async def sites_bloques(_: dict = Depends(get_super_admin)):
    """Sites bloqués sur toute la plateforme (super-admin)."""
    return {"items": await cip.sites_bloques()}


@router.post("/admin/connexions/sites-bloques/autoriser")
async def autoriser_site(payload: IpPayload, request: Request, user: dict = Depends(get_super_admin)):
    r = await cip.lever_global(_ip_valide(payload.ip), user, ip_reelle(request))
    if not r["ok"]:
        raise HTTPException(status_code=404, detail="Ce site n'est pas bloqué sur toute la plateforme")
    return r
