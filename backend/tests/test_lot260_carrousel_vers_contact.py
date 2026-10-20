"""Lot 260 — Centre de messagerie : envoi d'un carrousel ENREGISTRÉ à UN contact.

Envoi WhatsApp simulé, MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_lot260_carrousel_vers_contact.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.carrousel_whatsapp as cw  # noqa: E402

BASE = "https://sawalismartsystems.com"
USERS = {
    "cli_a": {"id": "cli_a", "role": "client", "company": "Pharmacie A", "features": {"whatsapp": True, "whatsapp_carrousel": True},
              "whatsapp_number": "+226 70 00 00 01", "email": "a@x.bf"},
    "suivi_a": {"id": "suivi_a", "role": "pharmacien", "parent_client_id": "cli_a", "client_id": "cli_a"},
    "cli_b": {"id": "cli_b", "role": "client", "company": "Pharmacie B", "features": {"whatsapp": True},
              "whatsapp_number": "+226 70 00 00 02", "email": "b@x.bf"},
    "admin": {"id": "admin", "role": "admin", "email": "admin@sawalismartsystems.com"},
}
PRODUITS = [
    {"id": "p1", "name": "DOLIPRANE 1000", "unit_price_ht": 1500, "image_url": "/api/files/prod/p1.jpg",
     "tenant_id": "cli_a", "deleted_at": None, "active": True, "is_public": True},
    {"id": "p2", "name": "EFFERALGAN", "unit_price_ht": 12500, "image_url": f"{BASE}/api/files/prod/p2.png",
     "tenant_id": "cli_a", "deleted_at": None, "active": True},
    {"id": "p3", "name": "AUTRE CLIENT", "unit_price_ht": 900, "image_url": "/api/files/prod/p3.jpg",
     "tenant_id": "cli_b", "deleted_at": None, "active": True},
]
CONTACTS = [
    {"id": "c1", "client_id": "cli_a", "name": "Awa", "whatsapp": "+226 76 11 11 11"},
    {"id": "c2", "client_id": "cli_a", "name": "Boris", "phone": "76 22 22 22"},
    {"id": "c3", "client_id": "cli_a", "name": "Awa (doublon)", "whatsapp": "22676111111"},
    {"id": "c4", "client_id": "cli_b", "name": "Chez B", "whatsapp": "+226 76 44 44 44"},
]


@pytest.fixture()
def env():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_carrousel"]
    envois = []

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
        if user["role"] == "admin":
            return True
        parent = USERS[user.get("parent_client_id") or user["id"]]
        return bool(parent.get("features", {}).get(cle))

    async def visibles(user):
        return [user.get("parent_client_id") or user["id"]]

    async def envoyer(to, nom, langue, comps, tenant_id=None):
        envois.append({"to": to, "modele": nom, "langue": langue, "composants": comps, "tenant_id": tenant_id})
        return {"ok": not to.endswith("2222"), "status": 200, "message_id": f"wamid.{len(envois)}",
                "error": None if not to.endswith("2222") else "Numéro non WhatsApp"}

    async def creds(tenant_id):
        return {"access_token": "t", "phone_number_id": "1", "source": "global", "tenant_id": None}

    api = APIRouter(prefix="/api")
    cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=fonction_active,
        visible_client_ids=visibles, wa_send_template=envoyer, resolve_wa_credentials=creds,
        base_publique=lambda: BASE)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
    client.portal.call(db.products.insert_many, [dict(p) for p in PRODUITS])
    client.portal.call(db.directory_contacts.insert_many, [dict(c) for c in CONTACTS])
    client.portal.call(db.contact_groups.insert_one, {"id": "g1", "client_id": "cli_a", "name": "Fidèles",
                                                      "contact_ids": ["c2", "c3"]})
    client.portal.call(db.settings.insert_one, {"_id": "global", "wa_carrousel_modele": "sawali_carrousel"})
    yield client, db, envois
    client.__exit__(None, None, None)


def h(uid):
    return {"X-User": uid}


CARTES = [{"source": "produit", "produit_id": "p1"}, {"source": "produit", "produit_id": "p2"}]


def _enregistrer(client, uid, nom="Promos de la semaine", cartes=CARTES, message="Nos promos"):
    r = client.post("/api/me/whatsapp/carrousel/brouillons", headers=h(uid), json={"nom": nom, "message": message, "cartes": cartes})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_envoi_d_un_carrousel_a_un_contact(env):
    client, db, envois = env
    bid = _enregistrer(client, "cli_a")
    # La liste déroulante du Centre de messagerie lit les carrousels enregistrés
    liste = client.get("/api/me/whatsapp/carrousel/brouillons", headers=h("cli_a")).json()["carrousels"]
    assert [c["nom"] for c in liste] == ["Promos de la semaine"]
    corps = {"contact_id": "c1", "carrousel_id": bid}
    # Sans accord du contact : refus clair, rien n'est envoyé
    r = client.post("/api/me/whatsapp/carrousel/envoyer-a-contact", headers=h("cli_a"), json=corps)
    assert r.status_code == 400 and "accepté" in r.json()["detail"] and envois == []
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    r = client.post("/api/me/whatsapp/carrousel/envoyer-a-contact", headers=h("cli_a"), json=corps)
    assert r.status_code == 202, r.text
    assert r.json()["destinataires"] == 1
    # Un seul message, vers CE contact, avec le texte et les cartes du carrousel choisi
    assert [e["to"] for e in envois] == ["22676111111"]
    assert envois[0]["composants"][1]["cards"][0]["components"][1]["parameters"][0]["text"] == "DOLIPRANE 1000"
    camp = client.get(f"/api/me/whatsapp/carrousel/campagnes/{r.json()['id']}", headers=h("cli_a")).json()
    assert camp["statut"] == "TERMINEE" and camp["compte"] == {"total": 1, "envoyes": 1, "echecs": 0}


def test_choix_invalides_refuses(env):
    client, db, envois = env
    bid = _enregistrer(client, "cli_a")
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    url = "/api/me/whatsapp/carrousel/envoyer-a-contact"
    # Contact d'un autre client, carrousel inconnu : introuvables
    assert client.post(url, headers=h("cli_a"), json={"contact_id": "c4", "carrousel_id": bid}).status_code == 404
    assert client.post(url, headers=h("cli_a"), json={"contact_id": "c1", "carrousel_id": "nimporte"}).status_code == 404
    # Le carrousel d'un autre client n'est pas utilisable
    client.portal.call(db.users.update_one, {"id": "cli_b"}, {"$set": {"features": {"whatsapp": True, "whatsapp_carrousel": True}}})
    USERS["cli_b"]["features"] = {"whatsapp": True, "whatsapp_carrousel": True}
    assert client.post(url, headers=h("cli_b"), json={"contact_id": "c4", "carrousel_id": bid}).status_code == 404
    # Un carrousel d'une seule carte est refusé (Meta : 2 cartes au moins)
    court = client.portal.call(db.carrousel_brouillons.insert_one, {"id": "court", "perimetre": "client", "tenant_id": "cli_a",
                               "nom": "Court", "message": "x", "cartes": CARTES[:1]})
    assert client.post(url, headers=h("cli_a"), json={"contact_id": "c1", "carrousel_id": "court"}).status_code == 400
    assert envois == []
