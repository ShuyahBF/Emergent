"""Lot 75 — Carrousel WhatsApp : image d'une carte générée par l'IA (aperçu, puis « Utiliser cette image »).
IA simulée (aucun appel OpenAI), MongoDB simulé, stockage des fichiers simulé."""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import ia_client  # noqa: E402
import routes.carrousel_whatsapp as cw  # noqa: E402

BASE = "https://sawalismartsystems.com"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100
USERS = {
    "cli_ia": {"id": "cli_ia", "role": "client", "features": {"whatsapp": True, "whatsapp_carrousel": True, "ai_image_gen": True}},
    "cli_sans": {"id": "cli_sans", "role": "client", "features": {"whatsapp": True, "whatsapp_carrousel": True}},
    "admin": {"id": "admin", "role": "admin"},
}


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_carrousel_ia"]
    prompts, fichiers = [], []

    class FausseIA:
        async def generate_images(self, prompt, model="gpt-image-1", number_of_images=1, quality="low"):
            prompts.append((prompt, model, quality))
            return [PNG]
    monkeypatch.setattr(ia_client, "OpenAIImageGeneration", FausseIA)

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

    async def creds(tenant_id):
        return {"access_token": "t", "phone_number_id": "1", "source": "global"}

    async def enregistrer(db_, *, data, kind, tenant_id, ext, content_type, original_filename, user_id):
        fichiers.append({"data": data, "tenant_id": tenant_id, "ext": ext})
        return {"url": f"/api/files/carrousel/{len(fichiers)}.{ext}"}

    api = APIRouter(prefix="/api")
    cw.attach_carrousel_whatsapp_routes(
        api=api, db=db, get_current_user=get_user, get_current_admin=get_admin, fonction_active=fonction_active,
        visible_client_ids=rien, wa_send_template=rien, resolve_wa_credentials=creds,
        base_publique=lambda: BASE, save_and_log=enregistrer)
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        yield client, db, prompts, fichiers


def h(uid):
    return {"X-User": uid}


def test_prompt_contient_description_titre_et_consigne():
    p = cw.prompt_image_carte("  une tablette   avec un formulaire ", "Formulaires")
    assert p.startswith("une tablette avec un formulaire.") and "« Formulaires »" in p and "aucun texte" in p
    assert "Sujet de la carte" not in cw.prompt_image_carte("un sondage", "")


def test_generer_puis_utiliser_l_image(env):
    client, db, prompts, fichiers = env
    r = client.post("/api/me/whatsapp/carrousel/images/ia", json={"prompt": "une tablette avec un formulaire", "titre": "Formulaires"}, headers=h("cli_ia"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["apercu"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert prompts[0][1] == "gpt-image-1" and "Formulaires" in prompts[0][0]
    assert fichiers == []                                         # rien d'enregistré avant « Utiliser cette image »
    r2 = client.post(f"/api/me/whatsapp/carrousel/images/ia/{d['apercu_id']}/retenir", headers=h("cli_ia"))
    assert r2.status_code == 200 and r2.json()["url"] == f"{BASE}/api/files/carrousel/1.png"
    assert fichiers[0]["data"] == PNG and fichiers[0]["tenant_id"] == "cli_ia"
    assert cw.image_acceptee(r2.json()["url"])                    # adresse acceptée par Meta pour la carte
    # Double clic : même adresse, pas de second fichier
    r3 = client.post(f"/api/me/whatsapp/carrousel/images/ia/{d['apercu_id']}/retenir", headers=h("cli_ia"))
    assert r3.json()["url"] == r2.json()["url"] and len(fichiers) == 1


def test_fonction_ia_non_activee_refusee(env):
    client, *_ = env
    r = client.post("/api/me/whatsapp/carrousel/images/ia", json={"prompt": "un sondage"}, headers=h("cli_sans"))
    assert r.status_code == 403 and "IA" in r.json()["detail"]
    assert client.get("/api/me/whatsapp/carrousel", headers=h("cli_sans")).json()["ia_images"] is False
    assert client.get("/api/me/whatsapp/carrousel", headers=h("cli_ia")).json()["ia_images"] is True


def test_apercu_d_un_autre_compte_introuvable(env):
    client, *_ = env
    d = client.post("/api/admin/whatsapp/carrousel/images/ia", json={"prompt": "un sondage"}, headers=h("admin")).json()
    r = client.post(f"/api/me/whatsapp/carrousel/images/ia/{d['apercu_id']}/retenir", headers=h("cli_ia"))
    assert r.status_code == 404


def test_limite_par_heure(env):
    client, db, *_ = env
    client.portal.call(db.settings.insert_one, {"_id": "global", "carrousel_ia_par_heure": 2})
    for _ in range(2):
        assert client.post("/api/admin/whatsapp/carrousel/images/ia", json={"prompt": "un sondage"}, headers=h("admin")).status_code == 200
    r = client.post("/api/admin/whatsapp/carrousel/images/ia", json={"prompt": "un sondage"}, headers=h("admin"))
    assert r.status_code == 429 and "2 images" in r.json()["detail"]
