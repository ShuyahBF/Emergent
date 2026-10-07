"""Lot 77 — carrousels nommés (enregistrer, lister, ouvrir, dupliquer, supprimer) et statut des modèles chez Meta."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.carrousel_whatsapp as cw  # noqa: E402

USERS = {
    "cli_a": {"id": "cli_a", "role": "client", "features": {"whatsapp": True, "whatsapp_carrousel": True}},
    "cli_b": {"id": "cli_b", "role": "client", "features": {"whatsapp": True, "whatsapp_carrousel": True}},
    "admin": {"id": "admin", "role": "admin", "email": "admin@x"},
}
CARTES = [{"source": "libre", "image_url": "https://x/a.jpg", "titre": "A", "texte": "a", "lien": "https://x/a"},
          {"source": "libre", "image_url": "https://x/b.jpg", "titre": "B", "texte": "b", "lien": "https://x/b"},
          {"source": "libre", "image_url": "https://x/c.jpg", "titre": "C", "texte": "c", "lien": "https://x/c"}]


@pytest.fixture()
def client():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_carrousel_l77"]

    async def get_user(request: Request):
        u = USERS.get(request.headers.get("X-User", ""))
        if not u:
            raise HTTPException(status_code=401)
        return u

    async def get_admin(request: Request):
        u = await get_user(request)
        if u["role"] != "admin":
            raise HTTPException(status_code=403)
        return u

    async def fonction_active(user, cle):
        return user["role"] == "admin" or bool(user.get("features", {}).get(cle))

    async def rien(*a, **k):
        return {}

    async def creds(tenant_id):          # pas de WABA : statuts Meta indisponibles (écran utilisable quand même)
        return {"access_token": "", "phone_number_id": "1", "source": "global"}

    api = APIRouter(prefix="/api")
    cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=fonction_active,
        visible_client_ids=rien, wa_send_template=rien, resolve_wa_credentials=creds, base_publique=lambda: "https://s")
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as c:
        c.portal.call(db.settings.insert_one, {"_id": "global", "wa_carrousel_modele": "sawali_carrousel"})
        yield c


def h(uid):
    return {"X-User": uid}


def test_statut_selon_nombre_de_cartes():
    statuts = cw.statuts_depuis_liste("sawali_carrousel", "fr", [
        {"name": "sawali_carrousel_2", "status": "APPROVED", "language": "fr"},
        {"name": "sawali_carrousel_3", "status": "PENDING", "language": "fr"},
        {"name": "sawali_carrousel_4", "status": "APPROVED", "language": "en"},     # autre langue : ignoré
        {"name": "sawali_carrousel_promo", "status": "APPROVED", "language": "fr"},  # pas un nombre : ignoré
        {"name": "autre_2", "status": "APPROVED", "language": "fr"},
    ])
    assert statuts == {2: "APPROVED", 3: "PENDING"}
    assert cw.statut_pour_cartes(2, statuts) == "APPROVED"
    assert cw.statut_pour_cartes(3, statuts) == "PENDING"
    assert cw.statut_pour_cartes(5, statuts) == "ABSENT"
    assert cw.statut_pour_cartes(1, statuts) == "HORS_LIMITES"


def test_enregistrer_lister_modifier_dupliquer_supprimer(client):
    r = client.post("/api/me/whatsapp/carrousel/brouillons", json={"nom": "Nouveautés", "message": "Nos produits", "cartes": CARTES}, headers=h("cli_a"))
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    liste = client.get("/api/me/whatsapp/carrousel/brouillons", headers=h("cli_a")).json()
    assert [b["nom"] for b in liste["carrousels"]] == ["Nouveautés"]
    b = liste["carrousels"][0]
    assert b["nb_cartes"] == 3 and b["modele"] == "sawali_carrousel_3" and b["statut_meta"] == "ABSENT"
    assert liste["erreur_meta"]                                    # pas de WABA : message, pas de plantage
    # Modifier
    r = client.put(f"/api/me/whatsapp/carrousel/brouillons/{bid}", json={"nom": "Nouveautés oct.", "message": "M", "cartes": CARTES[:2]}, headers=h("cli_a"))
    assert r.status_code == 200
    # Dupliquer
    d = client.post(f"/api/me/whatsapp/carrousel/brouillons/{bid}/dupliquer", headers=h("cli_a")).json()
    assert d["nom"] == "Copie de Nouveautés oct." and len(d["cartes"]) == 2 and d["id"] != bid
    noms = {b["nom"] for b in client.get("/api/me/whatsapp/carrousel/brouillons", headers=h("cli_a")).json()["carrousels"]}
    assert noms == {"Nouveautés oct.", "Copie de Nouveautés oct."}
    # Supprimer
    assert client.delete(f"/api/me/whatsapp/carrousel/brouillons/{bid}", headers=h("cli_a")).status_code == 200
    assert len(client.get("/api/me/whatsapp/carrousel/brouillons", headers=h("cli_a")).json()["carrousels"]) == 1


def test_carrousels_cloisonnes_par_client_et_admin(client):
    bid = client.post("/api/me/whatsapp/carrousel/brouillons", json={"nom": "A", "cartes": CARTES}, headers=h("cli_a")).json()["id"]
    assert client.get("/api/me/whatsapp/carrousel/brouillons", headers=h("cli_b")).json()["carrousels"] == []
    assert client.post(f"/api/me/whatsapp/carrousel/brouillons/{bid}/dupliquer", headers=h("cli_b")).status_code == 404
    assert client.delete(f"/api/me/whatsapp/carrousel/brouillons/{bid}", headers=h("cli_b")).status_code == 404
    assert client.get("/api/admin/whatsapp/carrousel/brouillons", headers=h("admin")).json()["carrousels"] == []
    client.post("/api/admin/whatsapp/carrousel/brouillons", json={"nom": "Admin", "cartes": CARTES}, headers=h("admin"))
    assert [b["nom"] for b in client.get("/api/admin/whatsapp/carrousel/brouillons", headers=h("admin")).json()["carrousels"]] == ["Admin"]


def test_nom_obligatoire(client):
    r = client.post("/api/me/whatsapp/carrousel/brouillons", json={"nom": "", "cartes": []}, headers=h("cli_a"))
    assert r.status_code == 422
