"""Lot 86.1 — requêtes des clients : images jointes (photos, captures) et lien personnel public envoyé par WhatsApp.
Lancer : cd backend && python -m pytest tests/test_lot86_1_requetes_lien_images.py -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import requetes_clients as rc  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200


def test_logique_pure():
    # Images : type et nombre contrôlés
    rc.images_valides([{"nom": "a.png", "mime": "image/png", "taille": 10}])
    with pytest.raises(ValueError):
        rc.images_valides([{"nom": "a.pdf", "mime": "application/pdf", "taille": 10}])
    with pytest.raises(ValueError):
        rc.images_valides([{"nom": "a.png", "mime": "image/png", "taille": 10}] * 7)
    with pytest.raises(ValueError):
        rc.images_valides([{"nom": "a.png", "mime": "image/png", "taille": rc.TAILLE_MAX_IMAGE + 1}])
    # Lien : adresse publique et message
    assert rc.url_lien("https://ex.com/", "abc") == "https://ex.com/requete/abc"
    assert rc.url_lien(None, "abc").startswith("https://sawalismartsystems.com/requete/")
    assert "https://ex.com/requete/abc" in rc.message_lien("AL BARKA", "https://ex.com/requete/abc")


def test_images_et_lien_personnel():
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot861"]
    boucle = asyncio.new_event_loop()
    boucle.run_until_complete(db.users.insert_one({"id": "t1", "company": "AL BARKA", "client_code": "ALBRK",
                                                   "email": "dg@albarka.bf", "whatsapp_number": "22670000000",
                                                   "role": "client"}))
    utilisateur = {"v": {"id": "u1", "parent_client_id": "t1", "role": "client", "full_name": "Agent"}}
    envois = []

    async def faux_email(to, sujet, html, texte=""):
        envois.append(("email", to, texte))
        return True

    async def faux_wa(numero, texte, tenant_id=None):
        envois.append(("wa", numero, texte))
    app, api = FastAPI(), APIRouter(prefix="/api")
    rc.setup_requetes_clients_routes(db=db, api=api, get_current_user=lambda: utilisateur["v"], send_email=faux_email,
                                     wa_send_text=faux_wa, upload_dir="/tmp", base_url="https://ex.com")
    app.include_router(api)
    c = TestClient(app)

    # Portail : requête avec deux images seulement (sans texte) → titre « Images jointes »
    r = c.post("/api/me/requetes", data={"categorie": "dysfonctionnement"},
               files=[("images", ("capture.png", PNG, "image/png")), ("images", ("photo.jpg", PNG, "image/jpeg"))])
    assert r.status_code == 200, r.text
    req = r.json()
    assert req["titre"] == "Images jointes" and len(req["images"]) == 2
    img = c.get(f"/api/requetes/{req['id']}/images/{req['images'][0]['id']}")
    assert img.status_code == 200 and img.content == PNG
    # Un fichier non image est refusé
    refus = c.post("/api/me/requetes", data={"categorie": "remarque", "titre": "x"},
                   files=[("images", ("doc.pdf", b"%PDF", "application/pdf"))])
    assert refus.status_code == 422

    # Administrateur : liste des clients, envoi du lien par WhatsApp et e-mail
    utilisateur["v"] = {"id": "adm", "role": "admin", "full_name": "SAWALI"}
    liste = c.get("/api/admin/requetes-liens").json()["clients"]
    assert liste[0]["id"] == "t1" and liste[0]["url"] is None
    envoi = c.post("/api/admin/requetes-liens", json={"tenant_id": "t1"}).json()
    assert envoi["envoye"] == {"whatsapp": True, "email": True, "mode": "texte"}   # sans modèle : message libre
    url = envoi["url"]
    assert url.startswith("https://ex.com/requete/") and any(e[0] == "wa" and url in e[2] for e in envois)
    jeton = url.rsplit("/", 1)[1]

    # Page publique (sans connexion) : suivi, dépôt avec image, image servie
    pub = c.get(f"/api/public/requetes/{jeton}").json()
    assert pub["client_nom"] == "AL BARKA" and len(pub["requetes"]) == 1
    dep = c.post(f"/api/public/requetes/{jeton}", data={"categorie": "equipement", "titre": "Imprimante", "auteur_nom": "Awa"},
                 files=[("images", ("p.png", PNG, "image/png"))])
    assert dep.status_code == 200 and dep.json()["numero"] == "REQ-ALBRK-0002" and dep.json()["origine"] == "lien"
    d = dep.json()
    assert c.get(f"/api/public/requetes/{jeton}/{d['id']}/images/{d['images'][0]['id']}").content == PNG

    # Traitée par SAWALI → le message rappelle le lien ; évaluation par le lien
    envois.clear()
    c.patch(f"/api/admin/requetes/{d['id']}", json={"etat": "terminee"})
    assert any(url in e[2] for e in envois)
    ev = c.post(f"/api/public/requetes/{jeton}/{d['id']}/evaluation", json={"note": 5, "auteur_nom": "Awa"})
    assert ev.status_code == 200 and ev.json()["evaluation"]["par"] == "Awa"

    # Client connecté : retrouve le même lien ; renouvellement puis révocation
    utilisateur["v"] = {"id": "u1", "parent_client_id": "t1", "role": "client", "full_name": "Agent"}
    assert c.get("/api/me/requetes-lien").json()["url"] == url
    utilisateur["v"] = {"id": "adm", "role": "admin", "full_name": "SAWALI"}
    nouveau = c.post("/api/admin/requetes-liens", json={"tenant_id": "t1", "renouveler": True, "envoyer": False}).json()
    assert nouveau["url"] != url and c.get(f"/api/public/requetes/{jeton}").status_code == 404
    c.delete("/api/admin/requetes-liens/t1")
    assert c.get(f"/api/public/requetes/{nouveau['url'].rsplit('/', 1)[1]}").status_code == 404
