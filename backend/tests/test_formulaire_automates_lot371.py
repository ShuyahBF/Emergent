"""Lot 371 — Formulaire public « Spécifications de votre automate » (logo + nom de la clinique, dépôt de documents, réponses).

MongoDB simulé (mongomock_motor) ; l'utilisateur connecté est simulé par l'en-tête X-Role.
Lancer : cd backend && python -m pytest tests/test_formulaire_automates_lot371.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import formulaire_automates as fa  # noqa: E402

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


# ---------------------------------------------------------------------------------------------------- logique pure

def test_modele_ids_uniques_et_champs_essentiels():
    pages = fa.pages_modele()
    ids = [f["id"] for p in pages for f in p["fields"]]
    assert len(ids) == len(set(ids))
    for cle in ("f_fournisseur", "f_contact_email", "f_modele", "f_interface", "f_protocole", "f_tests", "f_doc_lis"):
        assert cle in ids
    types = {f["id"]: f["type"] for p in pages for f in p["fields"]}
    assert types["f_doc_lis"] == "file" and types["f_interface"] == "multiselect"
    interface = next(f for p in pages for f in p["fields"] if f["id"] == "f_interface")
    assert any("série" in o for o in interface["options"]) and "USB" in interface["options"] and any("Ethernet" in o for o in interface["options"])


def test_identite_valide_et_refus():
    ok = fa.nettoyer_identite("  Clinique   Philadelphie ", "https://x.test/a.png", " Bonjour ")
    assert ok == {"organisation": "Clinique Philadelphie", "logo_url": "https://x.test/a.png", "message": "Bonjour"}
    for mauvais in ("javascript:alert(1)", "http://x.test/a.png", "https://x.test/a b.png", 'https://x.test/"onerror=1'):
        with pytest.raises(Exception):
            fa.nettoyer_identite("Clinique", mauvais, "")
    with pytest.raises(Exception):
        fa.nettoyer_identite("   ", None, None)


def test_contenu_conforme():
    assert fa.contenu_conforme("pdf", PDF) and not fa.contenu_conforme("pdf", b"<html>")
    assert fa.contenu_conforme("png", PNG) and not fa.contenu_conforme("jpg", PNG)
    assert fa.contenu_conforme("docx", b"PK\x03\x04abc") and fa.contenu_conforme("xls", b"\xd0\xcf\x11\xe0abc")
    assert fa.contenu_conforme("txt", b"bonjour") and not fa.contenu_conforme("txt", b"a\x00b")
    assert not fa.contenu_conforme("exe", b"MZ")


def test_csv_et_lignes():
    form = {"number": "F1", "pages": [{"fields": [{"id": "a", "label": "Marque"}, {"id": "b", "label": "Doc"}, {"id": "c", "label": "Modes"}]}]}
    soum = [{"id": "s1", "created_at": "2026-11-06T10:00:00", "user_label": "Jean", "data": {
        "a": "Sun;UG", "b": {"public_url": "https://x/f.pdf", "filename": "f.pdf"}, "c": ["USB", "TCP"]}}]
    lignes = fa.lignes_reponses(form, soum)
    assert lignes[0]["documents"][0]["url"] == "https://x/f.pdf" and lignes[0]["valeurs"]["c"] == "USB; TCP"
    sortie = fa.export_csv(form, lignes)
    assert sortie.startswith("﻿") and '"Sun;UG"' in sortie and "Marque" in sortie


# ---------------------------------------------------------------------------------------------------- routes

@pytest.fixture()
def client(tmp_path):
    db = mongomock_motor.AsyncMongoMockClient()["t371"]
    app = FastAPI()
    api = APIRouter(prefix="/api")

    async def utilisateur(x_role: str = Header(default=""), x_tracked: str = Header(default="")):
        if not x_role:
            raise HTTPException(status_code=401, detail="Non connecté")
        return {"id": "u1", "role": x_role, "email": "a@b.test", "full_name": "Admin", "client_code": "SAW", "tracked_role": x_tracked, "client_id": "compte-client"}

    async def toujours_active(compte, cle):
        return True

    fa.attach_formulaire_automates_routes(api, db=db, helpers={
        "get_current_user": utilisateur, "_uuid": lambda: __import__("uuid").uuid4().hex, "_now": lambda: "2026-11-06T10:00:00",
        "public_base_url": lambda r: "https://sawali.test", "client_ip": lambda r: "1.2.3.4", "upload_dir": tmp_path,
        "fonction_active_pour_compte": toujours_active})
    app.include_router(api)
    c = TestClient(app)
    c.db = db
    return c


ADMIN = {"X-Role": "admin"}


def creer(c, nom="Clinique Philadelphie"):
    r = c.post("/api/admin/formulaire-automates", json={"organisation": nom, "message": "Merci"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_creation_reservee_admin_et_doublon(client):
    assert client.post("/api/admin/formulaire-automates", json={"organisation": "X"}).status_code == 401
    assert client.post("/api/admin/formulaire-automates", json={"organisation": "X"}, headers={"X-Role": "client"}).status_code == 403
    f = creer(client)
    assert f["lien"].startswith("https://sawali.test/f/") and f["is_public"] and f["branding"]["organisation"] == "Clinique Philadelphie"
    assert client.post("/api/admin/formulaire-automates", json={"organisation": "clinique philadelphie"}, headers=ADMIN).status_code == 409
    assert len(client.get("/api/admin/formulaire-automates", headers=ADMIN).json()["formulaires"]) == 1


def test_compte_suivi_administrateur_accepte(client):
    """Le compte support@ (rôle client, suivi « Administrateur ») doit pouvoir gérer le formulaire."""
    r = client.get("/api/admin/formulaire-automates", headers={"X-Role": "client", "X-Tracked": "Administrateur"})
    assert r.status_code == 200
    assert client.get("/api/admin/formulaire-automates", headers={"X-Role": "client", "X-Tracked": "Client"}).status_code == 403


def test_identite_publique_et_prive(client):
    f = creer(client)
    r = client.get(f"/api/public/forms/{f['id']}/identite")
    assert r.status_code == 200 and r.json()["organisation"] == "Clinique Philadelphie" and r.json()["modele"] == "automate"
    client.put(f"/api/admin/formulaire-automates/{f['id']}", json={"is_public": False}, headers=ADMIN)
    assert client.get(f"/api/public/forms/{f['id']}/identite").status_code == 404


def test_logo_et_modification(client):
    f = creer(client)
    r = client.post("/api/admin/formulaire-automates/logo", files={"file": ("logo.png", PNG, "image/png")}, headers=ADMIN)
    assert r.status_code == 200 and "/api/files/" in r.json()["logo_url"]
    m = client.put(f"/api/admin/formulaire-automates/{f['id']}", json={"logo_url": r.json()["logo_url"], "organisation": "Clinique Nouvelle"}, headers=ADMIN)
    assert m.status_code == 200 and m.json()["branding"]["logo_url"] == r.json()["logo_url"] and "Nouvelle" in m.json()["title"]
    # un faux PNG est refusé
    assert client.post("/api/admin/formulaire-automates/logo", files={"file": ("a.png", b"<svg>", "image/png")}, headers=ADMIN).status_code == 415


def test_depot_public(client):
    f = creer(client)
    url = f"/api/public/forms/{f['id']}/upload"
    ok = client.post(url, files={"file": ("manuel.pdf", PDF, "application/pdf")})
    assert ok.status_code == 200 and ok.json()["public_url"].startswith("https://sawali.test/api/files/")
    assert client.db.files.find_one is not None
    # extension interdite, faux contenu, vide
    assert client.post(url, files={"file": ("a.html", b"<html>", "text/html")}).status_code == 415
    assert client.post(url, files={"file": ("a.pdf", b"<html>", "application/pdf")}).status_code == 415
    assert client.post(url, files={"file": ("a.pdf", b"", "application/pdf")}).status_code == 400
    # formulaire inconnu
    assert client.post("/api/public/forms/inconnu/upload", files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 404


def test_limite_par_adresse(client):
    f = creer(client)
    url = f"/api/public/forms/{f['id']}/upload"
    codes = [client.post(url, files={"file": ("a.pdf", PDF, "application/pdf")}).status_code for _ in range(fa.DEPOTS_PAR_HEURE + 2)]
    assert codes[: fa.DEPOTS_PAR_HEURE] == [200] * fa.DEPOTS_PAR_HEURE and codes[-1] == 429


def test_reponses_json_et_csv(client):
    f = creer(client)
    import asyncio
    asyncio.get_event_loop().run_until_complete(client.db.form_submissions.insert_one({
        "id": "s1", "form_id": f["id"], "created_at": "2026-11-06T11:00:00", "user_label": "Jean",
        "data": {"f_fournisseur": "MedLab", "f_modele": "SPIN 200E", "f_interface": ["USB", "Wi-Fi"]}}))
    j = client.get(f"/api/admin/formulaire-automates/{f['id']}/reponses", headers=ADMIN).json()
    assert j["reponses"][0]["valeurs"]["f_modele"] == "SPIN 200E"
    c = client.get(f"/api/admin/formulaire-automates/{f['id']}/reponses?format=csv", headers=ADMIN)
    assert c.status_code == 200 and "SPIN 200E" in c.text and c.headers["content-type"].startswith("text/csv")


def test_rattache_au_compte_client(client):
    """Le formulaire porte le client_id du compte client (comme les formulaires ordinaires), pas l'identifiant personnel."""
    import asyncio
    f = creer(client)
    doc = asyncio.new_event_loop().run_until_complete(client.db.forms.find_one({"id": f["id"]}))
    assert doc["client_id"] == "compte-client" and doc["created_by_id"] == "u1"
    # le superviseur du même compte le retrouve, un autre compte non
    assert len(client.get("/api/admin/formulaire-automates", headers={"X-Role": "superviseur"}).json()["formulaires"]) == 1
