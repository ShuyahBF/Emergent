"""Lot 314 — niveaux de service : réglages normalisés, « configuré » seulement si les trois délais sont renseignés, droits."""
import asyncio

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes.niveaux_service import MENTION_DEFAUT, normaliser_config, setup_niveaux_service_routes


def test_config_vide_n_engage_personne():
    c = normaliser_config(None)
    assert c["actif"] is False and c["configure"] is False
    assert [c["niveaux"][k]["delai"] for k in ("contrat", "standard", "express")] == ["", "", ""]      # aucun délai par défaut
    assert c["mention"] == MENTION_DEFAUT and c["niveaux"]["express"]["afficher_tarif"] is False


def test_configure_seulement_si_actif_et_trois_delais():
    brut = {"actif": True, "societe": "SAWALI SMART SYSTEMS", "niveaux": {
        "contrat": {"delai": "2 heures"}, "standard": {"delai": "24 heures"}, "express": {"delai": "30 minutes", "afficher_tarif": True}}}
    c = normaliser_config(brut)
    assert c["configure"] is True and c["niveaux"]["express"]["afficher_tarif"] is True and "tarif" not in c["niveaux"]["express"]    # le tarif vient de la fiche du client
    brut["niveaux"]["standard"]["delai"] = ""
    assert normaliser_config(brut)["configure"] is False
    brut["niveaux"]["standard"]["delai"] = "24 heures"; brut["actif"] = False
    assert normaliser_config(brut)["configure"] is False
    assert len(normaliser_config({"societe": "x" * 500})["societe"]) == 60                 # textes bornés


def _client():
    db = AsyncMongoMockClient()["test_niveaux_314"]

    async def utilisateur(request: Request):
        return {"id": "u1"}

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"id": "a1"}

    api = APIRouter(prefix="/api")
    setup_niveaux_service_routes(db=db, api=api, get_current_user=utilisateur, get_current_admin=admin)
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def test_enregistrer_puis_lire_et_droits():
    c = _client()
    corps = {"actif": True, "niveaux": {"contrat": {"delai": "2 heures"}, "standard": {"delai": "48 heures"}, "express": {"delai": "1 heure"}}}
    assert c.put("/api/admin/niveaux-service", json=corps).status_code == 403                  # réservé à l'administrateur
    r = c.put("/api/admin/niveaux-service", headers={"x-admin": "1"}, json=corps).json()
    assert r["config"]["configure"] is True
    lu = c.get("/api/me/niveaux-service").json()                                               # lecture par le portail (modale Calendrier)
    assert lu["configure"] is True and lu["niveaux"]["standard"]["delai"] == "48 heures"
    assert "configure" in c.get("/api/admin/niveaux-service", headers={"x-admin": "1"}).json()["config"]
