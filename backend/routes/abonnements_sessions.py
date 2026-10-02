"""Lot 50 — Abonnements (grâce et coupure), sessions des comptes, date de la dernière sauvegarde.

Compte connecté (toutes ouvertes même après la coupure de l'abonnement) :
  GET    /api/me/abonnement                 état de l'abonnement du client (bandeau, écran « Renouveler »)
  GET    /api/me/sessions                   sessions ouvertes du compte (appareil, IP, ouverture, activité)
  DELETE /api/me/sessions/{sid}             fermer une autre session du compte
  POST   /api/me/activite                   activité de l'utilisateur (contrôle serveur de l'inactivité)
  GET    /api/me/derniere-sauvegarde        D : date de la dernière sauvegarde générale réussie

Super-admin SAWALI (SUPER_ADMIN_EMAIL) :
  GET    /api/admin/abonnements                         clients sous contrat : échéance, grâce, statut
  PUT    /api/admin/abonnements/reglages                {coupure_active}
  PUT    /api/admin/abonnements/{client_id}/grace       {jours}  (0 à 30)
  POST   /api/admin/abonnements/{client_id}/renouveler-grace   +3 j, 3 fois au plus par échéance
  GET    /api/admin/abonnements/journal                 actions sur la grâce (?client_id=)
  GET    /api/admin/sessions/reglages                   {max_par_compte}
  PUT    /api/admin/sessions/reglages                   {max_par_compte}  (1 à 20)
  GET    /api/admin/sessions/client/{client_id}         comptes du client et leurs sessions
  DELETE /api/admin/sessions/{sid}                      fermer une session
  POST   /api/admin/sessions/compte/{user_id}/fermer-tout

La logique est dans backend/abonnement_acces.py et backend/sessions_comptes.py.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import abonnement_acces as abo
import sessions_comptes as sess
from auth import decode_token, get_current_user, get_super_admin
from db import db

router = APIRouter(tags=["Abonnements et sessions (lot 50)"])

SUIVI_SAUVEGARDES = "sauvegardes_completes"  # lot 49 : document « etat_auto » (sauvegarde quotidienne R2)


def _jeton(request: Request) -> Dict[str, Any]:
    entete = request.headers.get("authorization") or ""
    if not entete.lower().startswith("bearer "):
        return {}
    try:
        return decode_token(entete.split(" ", 1)[1].strip())
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Compte connecté
# ---------------------------------------------------------------------------
@router.get("/me/abonnement")
async def me_abonnement(request: Request, user: dict = Depends(get_current_user)):
    return await abo.etat_pour(user, _jeton(request))


@router.get("/me/sessions")
async def me_sessions(request: Request, user: dict = Depends(get_current_user)):
    jeton = _jeton(request)
    return {"sessions": await sess.lister(user["id"], courante=jeton.get("sid")),
            "max_par_compte": await sess.max_sessions(), "session_courante": jeton.get("sid"),
            "apercu_admin": bool(jeton.get("imp"))}


@router.delete("/me/sessions/{sid}")
async def me_fermer_session(sid: str, request: Request, user: dict = Depends(get_current_user)):
    jeton = _jeton(request)
    if sid == jeton.get("sid"):
        raise HTTPException(status_code=400, detail="C'est la session de cet appareil : utilisez « Déconnexion ».")
    doc = await sess.session(sid)
    if not doc or doc.get("user_id") != user["id"] or doc.get("fermee_le"):
        raise HTTPException(status_code=404, detail="Session introuvable ou déjà fermée")
    await sess.fermer(sid, sess.MOTIF_FERMEE_UTILISATEUR, par=user)
    return {"ok": True}


@router.post("/me/activite")
async def me_activite(request: Request, user: dict = Depends(get_current_user)):
    jeton = _jeton(request)
    if jeton.get("sid") and not jeton.get("imp"):
        await sess.noter_activite(jeton["sid"])
    return {"ok": True}


@router.get("/me/derniere-sauvegarde")
async def me_derniere_sauvegarde(_: dict = Depends(get_current_user)):
    """D. Dernière sauvegarde générale réussie (sauvegarde quotidienne chiffrée vers R2, lot 49).
    Les clients SAWALI n'ont pas de sauvegarde propre : `propre` vaut toujours None."""
    doc = await db[SUIVI_SAUVEGARDES].find_one({"_id": "etat_auto"}, {"_id": 0, "derniere_reussite": 1}) or {}
    le = (doc.get("derniere_reussite") or {}).get("le")
    return {"generale": {"le": le} if le else None, "propre": None}


# ---------------------------------------------------------------------------
# Super-admin : abonnements
# ---------------------------------------------------------------------------
class ReglagesAbonnements(BaseModel):
    coupure_active: bool


class GraceIn(BaseModel):
    jours: int = Field(..., ge=abo.GRACE_MIN, le=abo.GRACE_MAX)


class ReglagesSessions(BaseModel):
    max_par_compte: int = Field(..., ge=sess.MAX_MIN, le=sess.MAX_MAX)


def _est_principal(u: dict) -> bool:
    parent = u.get("parent_client_id")
    return not parent or parent == u.get("id")


@router.get("/admin/abonnements")
async def admin_abonnements(_: dict = Depends(get_super_admin)):
    filtre = {"$or": [{"contract_billing_period": {"$nin": [None, ""]}},
                      {"contract_number": {"$nin": [None, ""]}},
                      {"last_payment_at": {"$nin": [None, ""]}}]}
    clients = [u for u in await db.users.find(filtre, {"_id": 0, "password_hash": 0}).to_list(5000)
               if _est_principal(u) and not abo.est_super_admin(u)]
    ids = [c["id"] for c in clients]
    # Comptes rattachés (utilisateurs suivis) et sessions ouvertes, par client
    rattaches = await db.users.find({"parent_client_id": {"$in": ids}}, {"_id": 0, "id": 1, "parent_client_id": 1}) \
        .to_list(50000)
    comptes: Dict[str, list] = {i: [i] for i in ids}
    for r in rattaches:
        comptes.setdefault(r["parent_client_id"], []).append(r["id"])
    tous = [u for liste in comptes.values() for u in liste]
    nb = await sess.compter_par_compte(tous) if tous else {}
    lignes = []
    for c in clients:
        etat = abo.etat_client(c)
        lignes.append({"client_id": c["id"], "nom": c.get("company") or c.get("full_name") or c.get("email"),
                       "email": c.get("email"), "account_status": c.get("account_status"),
                       "last_payment_at": c.get("last_payment_at"), "contract_signed_at": c.get("contract_signed_at"),
                       "grace_personnalisee": c.get("abonnement_grace_jours") is not None,
                       "comptes": len(comptes.get(c["id"], [])),
                       "sessions": sum(nb.get(u, 0) for u in comptes.get(c["id"], [])), **etat})
    ordre = {abo.EXPIRE: 0, abo.GRACE: 1, abo.A_JOUR: 2, abo.SANS_ECHEANCE: 3}
    lignes.sort(key=lambda x: (ordre.get(x["statut"], 9), x.get("echeance") or "9999", (x.get("nom") or "").lower()))
    return {"clients": lignes,
            "reglages": {"coupure_active": await abo.coupure_active(), "grace_defaut": abo.GRACE_DEFAUT,
                         "grace_min": abo.GRACE_MIN, "grace_max": abo.GRACE_MAX,
                         "renouvellement_jours": abo.RENOUVELLEMENT_JOURS,
                         "renouvellements_max": abo.RENOUVELLEMENTS_MAX}}


@router.put("/admin/abonnements/reglages")
async def admin_abonnements_reglages(corps: ReglagesAbonnements, adm: dict = Depends(get_super_admin)):
    avant = await abo.coupure_active()
    actif = await abo.definir_coupure(corps.coupure_active)
    if avant != actif:
        await db[abo.JOURNAL].insert_one({
            "id": uuid.uuid4().hex, "action": "COUPURE_ACTIVEE" if actif else "COUPURE_DESACTIVEE",
            "date": abo.maintenant().isoformat(), "client_id": None, "client_nom": None,
            "par": {"id": adm.get("id"), "email": adm.get("email")}})
    return {"coupure_active": actif}


@router.get("/admin/abonnements/journal")
async def admin_abonnements_journal(client_id: Optional[str] = None, _: dict = Depends(get_super_admin)):
    return {"journal": await abo.journal(client_id)}


@router.put("/admin/abonnements/{client_id}/grace")
async def admin_abonnement_grace(client_id: str, corps: GraceIn, adm: dict = Depends(get_super_admin)):
    return await abo.definir_grace(client_id, corps.jours, adm)


@router.post("/admin/abonnements/{client_id}/renouveler-grace")
async def admin_abonnement_renouveler(client_id: str, adm: dict = Depends(get_super_admin)):
    return await abo.renouveler_grace(client_id, adm)


# ---------------------------------------------------------------------------
# Super-admin : sessions
# ---------------------------------------------------------------------------
@router.get("/admin/sessions/reglages")
async def admin_sessions_reglages(_: dict = Depends(get_super_admin)):
    return {"max_par_compte": await sess.max_sessions(), "min": sess.MAX_MIN, "max": sess.MAX_MAX,
            "defaut": sess.MAX_DEFAUT}


@router.put("/admin/sessions/reglages")
async def admin_sessions_reglages_maj(corps: ReglagesSessions, adm: dict = Depends(get_super_admin)):
    n = await sess.definir_max(corps.max_par_compte)
    await db[sess.JOURNAL].insert_one({"id": uuid.uuid4().hex, "action": "REGLAGE_MAX",
                                       "date": sess._iso(), "max_par_compte": n,
                                       "par": {"id": adm.get("id"), "email": adm.get("email")}})
    return {"max_par_compte": n}


@router.get("/admin/sessions/client/{client_id}")
async def admin_sessions_client(client_id: str, _: dict = Depends(get_super_admin)):
    comptes = await db.users.find({"$or": [{"id": client_id}, {"parent_client_id": client_id}]},
                                  {"_id": 0, "id": 1, "email": 1, "full_name": 1, "role": 1, "tracked_role": 1,
                                   "account_status": 1}).to_list(2000)
    res = []
    for c in comptes:
        res.append({**c, "sessions": await sess.lister(c["id"])})
    res.sort(key=lambda c: (c["id"] != client_id, -len(c["sessions"]), (c.get("full_name") or "").lower()))
    return {"client_id": client_id, "comptes": res, "max_par_compte": await sess.max_sessions()}


@router.delete("/admin/sessions/{sid}")
async def admin_fermer_session(sid: str, adm: dict = Depends(get_super_admin)):
    if not await sess.fermer(sid, sess.MOTIF_FERMEE_ADMIN, par=adm):
        raise HTTPException(status_code=404, detail="Session introuvable ou déjà fermée")
    return {"ok": True}


@router.post("/admin/sessions/compte/{user_id}/fermer-tout")
async def admin_fermer_sessions_compte(user_id: str, request: Request, adm: dict = Depends(get_super_admin)):
    # La session de l'appareil du super-admin lui-même n'est jamais fermée par ce bouton
    n = await sess.fermer_compte(user_id, sess.MOTIF_FERMEE_ADMIN, par=adm, sauf=_jeton(request).get("sid"))
    return {"ok": True, "fermees": n}
