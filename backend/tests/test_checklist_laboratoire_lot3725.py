"""Lot 372.5 — Checklist laboratoire : numérotation calculée, formulaire public, création par modèle, réponses sans blocs d'information."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes import checklist_laboratoire as cl  # noqa: E402
from routes import formulaire_automates as fa  # noqa: E402


def test_la_numerotation_est_calculee_unique_et_stable():
    champs = cl.champs_numerotes()
    nums = [c["numero"] for c in champs]
    assert len(nums) == len(set(nums)) and len(nums) > 50
    assert all(re.fullmatch(r"\d+\.\d+\.\d+[a-z]?", n) for n in nums)
    ids = {c["numero"]: c for c in champs}
    # champ unique : pas de lettre ; plusieurs champs dans une question : a, b…
    assert ids["1.1.1"]["label"] == "Mise à jour de Loois"
    assert ids["2.1.1a"]["label"] == "Numéro du dossier" and ids["2.1.1b"]["label"] == "Fichier CSV exporté" and ids["2.1.1b"]["type"] == "file"
    assert ids["2.5.1"]["type"] == "file" and ids["2.7.1"]["type"] == "table"
    assert ids["6.7.1a"]["type"] == "file" and "SPIN" in ids["6.7.1a"]["titre_question"] + cl.SECTIONS[5]["points"][6]["titre"]
    assert "2.1.1c" not in ids


def test_les_references_croisees_du_texte_pointent_vers_les_bons_points():
    # « point 3.1 » (section 4) = Mindray ; « voir 6.7 » (SPIN 200E) = documentation du SPIN
    assert cl.SECTIONS[2]["points"][0]["titre"].startswith("Mindray")
    assert "SPIN 200E" in cl.SECTIONS[5]["points"][4]["titre"] and "6.7" in cl.SECTIONS[5]["points"][4]["consigne"]
    assert cl.SECTIONS[5]["points"][6]["titre"] == "Documentation du SPIN 200E"


def test_le_texte_ne_cite_ni_claude_ni_conversation():
    texte = repr(cl.SECTIONS) + cl.DESCRIPTION
    for interdit in ("Claude", "conversation", "chat", "IA "):
        assert interdit.lower() not in texte.lower().replace("fichier", ""), interdit


def test_les_pages_du_formulaire_portent_les_numeros_et_les_blocs_d_information():
    pages = cl.pages_formulaire()
    assert [p["title"][:2] for p in pages] == ["1.", "2.", "3.", "4.", "5.", "6.", "7."]
    champs = [f for p in pages for f in p["fields"]]
    ids = [f["id"] for f in champs]
    assert len(ids) == len(set(ids))
    assert any(f["type"] == "info" and f["label"].startswith("2.1 ") for f in champs)
    saisie = [f for f in champs if f["type"] != "info"]
    assert all(re.match(r"\d+\.\d+\.\d+[a-z]? — ", f["label"]) for f in saisie)
    assert not any(f["required"] for f in champs)                                  # rien d'obligatoire : on remplit au fur et à mesure
    table = next(f for f in saisie if f["type"] == "table")
    assert [c["label"] for c in table["columns"]] == ["Examen dans Biolog", "Automate", "Code ou n° de test sur l'automate"]


@pytest.fixture()
def client(tmp_path):
    db = mongomock_motor.AsyncMongoMockClient()["t3725"]
    app = FastAPI(); api = APIRouter(prefix="/api")

    async def utilisateur(x_role: str = Header(default="")):
        if not x_role:
            raise HTTPException(status_code=401, detail="Non connecté")
        return {"id": "u1", "role": x_role, "email": "a@b.test", "full_name": "Admin", "client_code": "SAW"}

    async def active(compte, cle):
        return True

    fa.attach_formulaire_automates_routes(api, db=db, helpers={
        "get_current_user": utilisateur, "_uuid": lambda: __import__("uuid").uuid4().hex, "_now": lambda: "2026-11-06T10:00:00", "public_base_url": lambda r: "https://sawali.test",
        "client_ip": lambda r: "1.2.3.4", "upload_dir": tmp_path, "fonction_active_pour_compte": active})
    app.include_router(api)
    c = TestClient(app); c.db = db
    return c


ADMIN = {"X-Role": "admin"}


def test_creation_par_modele_et_les_deux_modeles_coexistent(client):
    a = client.post("/api/admin/formulaire-automates", json={"organisation": "Clinique X"}, headers=ADMIN).json()
    b = client.post("/api/admin/formulaire-automates", json={"organisation": "Clinique X", "modele": "laboratoire"}, headers=ADMIN)
    assert b.status_code == 200, b.text
    b = b.json()
    assert (a["modele"], b["modele"]) == ("automate", "laboratoire")
    assert b["title"] == "Checklist laboratoire — Clinique X" and a["title"].startswith("Spécifications de votre automate")
    # le même modèle ne peut pas être créé deux fois pour la même clinique
    assert client.post("/api/admin/formulaire-automates", json={"organisation": "clinique x", "modele": "laboratoire"}, headers=ADMIN).status_code == 409
    assert {f["modele"] for f in client.get("/api/admin/formulaire-automates", headers=ADMIN).json()["formulaires"]} == {"automate", "laboratoire"}
    # le formulaire public expose les pages numérotées
    pub = client.get(f"/api/public/forms/{b['id']}/identite").json()
    assert pub["modele"] == "laboratoire" and pub["organisation"] == "Clinique X"
    # un modèle inconnu retombe sur « automate »
    c = client.post("/api/admin/formulaire-automates", json={"organisation": "Clinique Y", "modele": "inconnu"}, headers=ADMIN).json()
    assert c["modele"] == "automate"


def test_les_reponses_et_le_csv_ignorent_les_blocs_d_information(client):
    import asyncio
    b = client.post("/api/admin/formulaire-automates", json={"organisation": "Clinique Z", "modele": "laboratoire"}, headers=ADMIN).json()
    asyncio.new_event_loop().run_until_complete(client.db.form_submissions.insert_one({
        "id": "s1", "form_id": b["id"], "created_at": "2026-11-06T11:00:00", "user_label": "BADINI Awa",
        "data": {"q_1_2_1": "192.168.1.10", "q_2_1_1a": "D-123", "q_7_1_1a": "BADINI Awa"}}))
    j = client.get(f"/api/admin/formulaire-automates/{b['id']}/reponses", headers=ADMIN).json()
    assert all(not c["label"][0].isdigit() or " — " in c["label"] for c in j["champs"])
    assert not any(c["id"].startswith("i_") for c in j["champs"])
    assert j["reponses"][0]["valeurs"]["q_2_1_1a"] == "D-123"
    csv = client.get(f"/api/admin/formulaire-automates/{b['id']}/reponses?format=csv", headers=ADMIN).text
    assert "1.2.1 — Adresse IP du PC" in csv and "192.168.1.10" in csv and "D-123" in csv
