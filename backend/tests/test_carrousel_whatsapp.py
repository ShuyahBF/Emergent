"""Lot 40 — Carrousel WhatsApp (portail client et administration).

Envoi WhatsApp simulé, MongoDB simulé.
Lancer : cd backend && python -m pytest tests/test_carrousel_whatsapp.py -q
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


CARTES_PRODUITS = [{"source": "produit", "produit_id": "p1"}, {"source": "produit", "produit_id": "p2"}]


def test_composants_format_meta():
    comps = cw.composants("Pharmacie A", "Promo", [
        {"image_url": f"{BASE}/a.jpg", "titre": "T1", "texte": "", "code_lien": "abc"},
        {"image_url": f"{BASE}/b.png", "titre": "T2", "texte": "1 500 FCFA", "code_lien": "def"}])
    assert comps[0]["parameters"][0]["text"] == "Pharmacie A"
    cartes = comps[1]["cards"]
    assert [c["card_index"] for c in cartes] == [0, 1]
    assert cartes[0]["components"][0]["parameters"][0]["image"]["link"] == f"{BASE}/a.jpg"
    assert cartes[0]["components"][1]["parameters"][1]["text"] == "-"   # jamais de paramètre vide
    assert cartes[1]["components"][2]["parameters"][0]["text"] == "def"
    assert cw.prix_affiche(12500) == "12 500 FCFA"
    assert cw.nom_modele("sawali_carrousel", 3) == "sawali_carrousel_3"
    assert not cw.image_acceptee(f"{BASE}/x.webp") and cw.image_acceptee(f"{BASE}/x.JPG?v=2")


def test_fonction_non_activee_refusee(env):
    client, _, _ = env
    assert client.get("/api/me/whatsapp/carrousel", headers=h("cli_b")).status_code == 403
    r = client.get("/api/me/whatsapp/carrousel", headers=h("suivi_a"))   # hérite de son client
    assert r.status_code == 200 and r.json()["pret"] is True
    assert r.json()["url_bouton_modele"] == f"{BASE}/api/public/carrousel/l/{{{{1}}}}"


def test_produits_du_client_seulement(env):
    client, _, _ = env
    produits = client.get("/api/me/whatsapp/carrousel/produits", headers=h("cli_a")).json()["produits"]
    assert [p["id"] for p in produits] == ["p1", "p2"]
    assert produits[0]["image_url"] == f"{BASE}/api/files/prod/p1.jpg" and produits[1]["prix"] == "12 500 FCFA"
    # Un produit d'un autre client est refusé dans une carte
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"), json={
        "message": "x", "cartes": [{"source": "produit", "produit_id": "p3"}, CARTES_PRODUITS[0]], "ids": ["c1"]})
    assert r.status_code == 400 and "produit introuvable" in r.json()["detail"]


def test_consentement_obligatoire_et_envoi(env):
    client, db, envois = env
    corps = {"message": "Nouveautés", "cartes": CARTES_PRODUITS, "ids": ["c1"], "groupes": ["g1"]}
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"), json=corps)
    assert r.status_code == 400 and "accepté" in r.json()["detail"]
    # Un contact d'un autre client n'est pas modifiable
    r = client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"),
                   json={"ids": ["c1", "c2", "c3", "c4"], "accepte": True})
    assert r.json()["modifies"] == 3
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"), json=corps)
    assert r.status_code == 202, r.text
    res = r.json()
    assert res["destinataires"] == 2 and res["ignores"] == 1 and res["modele"] == "sawali_carrousel_2"
    assert sorted(e["to"] for e in envois) == ["22676111111", "22676222222"]
    comps = envois[0]["composants"]
    assert comps[0]["parameters"][0]["text"] == "Pharmacie A"
    carte = comps[1]["cards"][0]["components"]
    assert carte[1]["parameters"][0]["text"] == "DOLIPRANE 1000"
    assert carte[1]["parameters"][1]["text"] == "1 500 FCFA"
    camp = client.get(f"/api/me/whatsapp/carrousel/campagnes/{res['id']}", headers=h("cli_a")).json()
    assert camp["statut"] == "TERMINEE" and camp["compte"] == {"total": 2, "envoyes": 1, "echecs": 1}
    assert {d["statut"] for d in camp["destinataires"]} == {"ENVOYE", "ECHEC"}
    assert client.portal.call(db.whatsapp_messages.count_documents, {"carrousel_id": res["id"]}) == 2
    # Le bouton compte le clic et mène à la page de présentation du produit sur le site (lot 94)
    code = camp["cartes"][0]["code_lien"]
    r = client.get(f"/api/public/carrousel/l/{code}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"{BASE}/presentation/{code}"
    liste = client.get("/api/me/whatsapp/carrousel/campagnes", headers=h("cli_a")).json()["campagnes"]
    assert liste[0]["cartes"][0]["clics"] == 1
    # L'utilisateur suivi du même client la voit ; l'administration ne la mélange pas aux siennes
    assert client.get(f"/api/me/whatsapp/carrousel/campagnes/{res['id']}", headers=h("suivi_a")).status_code == 200
    assert client.get("/api/admin/whatsapp/carrousel/campagnes", headers=h("admin")).json()["campagnes"] == []


def test_cartes_libres_verifiees(env):
    client, _, _ = env
    client.put("/api/me/whatsapp/carrousel/consentements", headers=h("cli_a"), json={"ids": ["c1"], "accepte": True})
    libre = {"source": "libre", "image_url": f"{BASE}/api/files/c/1.png", "titre": "Journée santé",
             "texte": "Samedi 9h", "lien": "https://exemple.bf/agenda"}
    mauvaise = dict(libre, image_url=f"{BASE}/api/files/c/1.webp")
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "x", "cartes": [libre, mauvaise], "ids": ["c1"]})
    assert r.status_code == 400 and "Carte 2" in r.json()["detail"]
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "x", "cartes": [libre, dict(libre, lien="pas un lien")], "ids": ["c1"]})
    assert r.status_code == 400 and "invalide" in r.json()["detail"]
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "x", "cartes": [libre], "ids": ["c1"]})
    assert r.status_code == 422   # 2 cartes au minimum
    r = client.post("/api/me/whatsapp/carrousel/envoyer", headers=h("cli_a"),
                    json={"message": "x", "cartes": [libre, CARTES_PRODUITS[1]], "ids": ["c1"]})
    assert r.status_code == 202


def test_admin_vers_clients_consentants(env):
    client, db, envois = env
    assert client.get("/api/admin/whatsapp/carrousel", headers=h("cli_a")).status_code == 403
    dest = client.get("/api/admin/whatsapp/carrousel/destinataires", headers=h("admin")).json()["contacts"]
    assert {d["id"] for d in dest} == {"cli_a", "cli_b"}   # pas l'utilisateur suivi ni l'Admin
    client.put("/api/admin/whatsapp/carrousel/consentements", headers=h("admin"), json={"ids": ["cli_a"], "accepte": True})
    r = client.put("/api/admin/whatsapp/carrousel/reglages", headers=h("admin"),
                   json={"modele": "sawali_promo", "langue": "fr"})
    assert r.status_code == 200
    r = client.post("/api/admin/whatsapp/carrousel/envoyer", headers=h("admin"), json={
        "message": "Offre", "cartes": [{"source": "produit", "produit_id": "p3"}, CARTES_PRODUITS[1]],
        "ids": ["cli_a", "cli_b"]})
    assert r.status_code == 202 and r.json()["destinataires"] == 1 and r.json()["modele"] == "sawali_promo_2"
    assert envois[-1]["to"] == "22670000001" and envois[-1]["tenant_id"] is None
    assert envois[-1]["composants"][0]["parameters"][0]["text"] == "SAWALI SMART SYSTEMS"
