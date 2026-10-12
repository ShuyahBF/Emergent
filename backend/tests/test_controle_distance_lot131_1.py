"""Lot 131.1 — postes « sans surveillance » (clé LKS-) : génération réservée au super-admin, identification,
révocation séparée, prise en main réservée au super-admin, accord automatique admis seulement avec la clé LKS-,
poste enregistré par son signal, liste des postes.
Lancer : cd backend && python -m pytest tests/test_controle_distance_lot131_1.py -q
"""
import asyncio

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import routes.loois_cles_clients as cles
from routes.controle_distance import creer_routeur

SUPER = {"id": "sa", "role": "admin", "email": "admin@sawalismartsystems.com", "full_name": "Super-admin"}
ADMIN = {"id": "ad", "role": "admin", "email": "autre.admin@exemple.bf", "full_name": "Autre admin"}
UTILISATEURS = {"sa": SUPER, "ad": ADMIN}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.delenv("LOOIS_CLES_PEPPER", raising=False)
    monkeypatch.delenv("LOOIS_SUPPORT_CLE", raising=False)
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "admin@sawalismartsystems.com")
    # Les comptes du support (non super-admin) peuvent prendre la main sur les postes surveillés
    monkeypatch.setattr("routes.support_loois.est_compte_support", lambda u: u.get("id") == "ad", raising=False)
    yield


def _app():
    base = AsyncMongoMockClient()["test_lot131_1"]

    async def courant(request: Request):
        u = UTILISATEURS.get(request.headers.get("x-user", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    api = APIRouter(prefix="/api")
    cles.setup_loois_cles_clients_routes(db=base, api=api, get_current_user=courant)
    api.include_router(creer_routeur(db=base, get_current_user=courant, identifier_cle=cles.identifier_cle,
                                     decode_token=lambda t: {}))
    app = FastAPI()
    app.include_router(api)
    return TestClient(app), base


def _en_tetes(cle, poste="PC-NUIT"):
    return {"x-loois-cle": cle, "x-loois-ecole": "SCF", "x-loois-poste": poste, "x-loois-utilisateur": "caisse"}


def _cles(c):
    """Crée la clé client LK- puis la clé sans surveillance LKS- du même client (par le super-admin)."""
    r = c.post("/api/admin/loois-cles-clients", json={"code": "SCF", "libelle": "SCF"}, headers={"x-user": "sa"})
    lk, fid = r.json()["cle"], r.json()["fiche"]["id"]
    # Un autre administrateur ne peut pas générer la clé sans surveillance
    assert c.post(f"/api/admin/loois-cles-clients/{fid}/sans-surveillance", headers={"x-user": "ad"}).status_code == 403
    r = c.post(f"/api/admin/loois-cles-clients/{fid}/sans-surveillance", headers={"x-user": "sa"})
    assert r.status_code == 200, r.text
    lks = r.json()["cle"]
    assert lks.startswith("LKS-") and "ss_cle_hash" not in r.json()["fiche"] and r.json()["fiche"]["ss_prefixe"] == lks[:6]
    return lk, lks, fid


def test_identification_et_revocation_separee(env):
    c, base = _app()
    lk, lks, fid = _cles(c)
    normal = _run(cles.identifier_cle(base, lk))
    ss = _run(cles.identifier_cle(base, lks))
    assert normal["code"] == ss["code"] == "SCF"
    assert normal["sans_surveillance"] is False and ss["sans_surveillance"] is True
    # La clé en clair n'est jamais en base
    assert lks not in str(_run(base.loois_cles_clients.find_one({"id": fid})))
    # Révocation de la seule clé sans surveillance : la clé normale reste valable
    c.post(f"/api/admin/loois-cles-clients/{fid}/sans-surveillance/revoquer", headers={"x-user": "sa"})
    assert _run(cles.identifier_cle(base, lks)) is None
    assert _run(cles.identifier_cle(base, lk))["code"] == "SCF"


def test_poste_sans_surveillance_reserve_au_super_admin_et_accord_automatique(env):
    c, base = _app()
    lk, lks, _ = _cles(c)
    # Le signal du poste (toutes les 5 s) enregistre sa fiche, marquée sans surveillance
    assert c.get("/api/controle-distance/poste/demande", headers=_en_tetes(lks)).json()["demande"] is None
    liste = c.get("/api/controle-distance/postes", headers={"x-user": "sa"}).json()
    poste = liste["postes"][0]
    assert poste["sans_surveillance"] is True and poste["cle_client_code"] == "SCF" and liste["super_admin"] is True
    # Un compte du support (non super-admin) ne peut pas prendre la main sur ce poste
    r = c.post("/api/controle-distance/sessions", json={"poste_id": poste["id"]}, headers={"x-user": "ad"})
    assert r.status_code == 403
    sid = c.post("/api/controle-distance/sessions", json={"poste_id": poste["id"]}, headers={"x-user": "sa"}).json()["session_id"]
    d = c.get("/api/controle-distance/poste/demande", headers=_en_tetes(lks)).json()["demande"]
    assert d["session_id"] == sid and d["sans_surveillance"] is True
    rep = c.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True, "automatique": True},
                 headers=_en_tetes(lks))
    assert rep.status_code == 200 and rep.json()["jeton"]
    doc = _run(base.controle_distance_sessions.find_one({"id": sid}))
    assert doc["sans_surveillance"] is True and doc["poste_sans_surveillance"] is True


def test_accord_automatique_refuse_avec_la_cle_normale(env):
    c, _ = _app()
    lk, _, _ = _cles(c)
    c.get("/api/controle-distance/poste/demande", headers=_en_tetes(lk, "PC-JOUR"))
    poste = c.get("/api/controle-distance/postes", headers={"x-user": "ad"}).json()["postes"][0]
    assert poste["sans_surveillance"] is False
    # Poste surveillé : le support peut demander, mais l'accord automatique est refusé (403)
    sid = c.post("/api/controle-distance/sessions", json={"poste_id": poste["id"]}, headers={"x-user": "ad"}).json()["session_id"]
    assert c.get("/api/controle-distance/poste/demande", headers=_en_tetes(lk, "PC-JOUR")).json()["demande"]["sans_surveillance"] is False
    r = c.post(f"/api/controle-distance/poste/sessions/{sid}/reponse", json={"accepte": True, "automatique": True},
               headers=_en_tetes(lk, "PC-JOUR"))
    assert r.status_code == 403
