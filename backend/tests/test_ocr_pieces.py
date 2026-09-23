"""Lot OCR sur Pièces — adaptateur Sawali du module commun ocr_core.

Tests autonomes : MongoDB simulé (mongomock-motor), stockage objet et appel
IA remplacés par des doublures — aucun serveur, aucune clé, aucun réseau.
Vérifie surtout le cloisonnement : une pharmacie ne voit que ses pièces et
jamais le modèle, le coût ni les évaluations ; les outils OCR sont réservés
à l'administration.

Lancer : cd backend && python -m pytest tests/test_ocr_pieces.py -q
"""
from __future__ import annotations

import io
import sys
import time
import types
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402
from PIL import Image  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ocr_core  # noqa: E402

# --- Utilisateurs de test ------------------------------------------------------
USERS = {
    "admin": {"id": "admin", "role": "admin", "full_name": "Admin Sawali"},
    "pharma_a": {"id": "pharma_a", "role": "pharmacien", "company": "Pharmacie A", "client_code": "PA"},
    "pharma_b": {"id": "pharma_b", "role": "pharmacien", "company": "Pharmacie B", "client_code": "PB"},
    # Utilisateur suivi « Pharmacien » rattaché à la pharmacie A.
    "suivi_a": {"id": "suivi_a", "role": "client", "tracked_role": "Pharmacien", "parent_client_id": "pharma_a"},
    "secretaire": {"id": "secretaire", "role": "client", "tracked_role": "Secrétaire"},
}


def _png() -> bytes:
    """Petite image PNG blanche servant de « photo de facture »."""
    b = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(b, format="PNG")
    return b.getvalue()


@pytest.fixture()
def env(monkeypatch):
    """Application FastAPI minimale avec les routes OCR sur Pièces branchées."""
    # 1) Faux stockage objet (même API que backend/object_storage.py).
    blobs: dict = {}
    fake_storage = types.ModuleType("object_storage")

    def guess_content_type(ext, fallback="application/octet-stream"):
        return {"png": "image/png", "pdf": "application/pdf"}.get(ext, fallback)

    async def save_and_log(db, *, data, kind, tenant_id, ext, content_type=None,
                           original_filename=None, user_id=None, metadata=None):
        path = f"sawali/{tenant_id}/{kind}/{len(blobs)}.{ext}"
        blobs[path] = (data, content_type)
        await db.stored_objects.insert_one({"storage_path": path, "is_deleted": False})
        return {"path": path, "size": len(data)}

    async def get_object(path):
        return blobs[path]

    async def soft_delete(db, path):
        await db.stored_objects.update_one({"storage_path": path}, {"$set": {"is_deleted": True}})
        return True

    fake_storage.guess_content_type = guess_content_type
    fake_storage.save_and_log = save_and_log
    fake_storage.get_object = get_object
    fake_storage.soft_delete = soft_delete
    monkeypatch.setitem(sys.modules, "object_storage", fake_storage)

    # 2) Faux appel IA : renvoie un résultat fixe et note le modèle demandé.
    calls: list = []

    async def fake_analyze(data, content_type, filename, model_id=None, *, system_prompt, default_model=None):
        assert "SAWALI" in system_prompt
        calls.append(model_id)
        return {"summary": "Facture fournisseur", "document_type": "Facture",
                "extracted_fields": {"numero": "F-12", "total": 150000}, "flags": [],
                "confidence": 0.9, "uncertain_fields": [], "model": model_id or "claude-sonnet-5",
                "input_mode": "images", "input_tokens": 1000, "output_tokens": 200,
                "cost_usd": 0.004, "cost_xof": 2.4, "pages_analyzed": 1, "duration_ms": 900}

    monkeypatch.setattr(ocr_core, "analyze_document", fake_analyze)

    # 3) Base simulée + authentification par en-tête X-User.
    db = AsyncMongoMockClient()["sawali_test"]

    async def get_current_user(x_user: str = Header(...)):
        if x_user not in USERS:
            raise HTTPException(status_code=401)
        return USERS[x_user]

    from routes.ocr_pieces import attach_ocr_pieces_routes
    api = APIRouter(prefix="/api")
    attach_ocr_pieces_routes(api=api, db=db, get_current_user=get_current_user)
    app = FastAPI()
    app.include_router(api)

    with TestClient(app) as client:
        # Utilisateurs insérés dans la boucle asyncio du client de test.
        client.portal.call(db.users.insert_many, [dict(u) for u in USERS.values()])
        yield types.SimpleNamespace(client=client, db=db, calls=calls, blobs=blobs)


def _h(user):
    return {"X-User": user}


def _upload(env, user, **form):
    return env.client.post("/api/ocr-pieces", headers=_h(user),
                           files={"file": ("facture.png", _png(), "image/png")}, data=form)


def _wait_analysed(env, user, piece_id):
    """L'analyse tourne en tâche de fond : on attend la fin (quelques ms)."""
    for _ in range(100):
        p = env.client.get(f"/api/ocr-pieces/{piece_id}", headers=_h(user)).json()
        if p["status"] != "en_analyse":
            return p
        time.sleep(0.02)
    raise AssertionError("analyse jamais terminée")


def test_pharmacy_upload_is_scoped_and_stripped(env):
    # La pharmacie ne peut pas imposer un autre tenant ni un modèle : ignorés.
    r = _upload(env, "pharma_a", tenant_id="pharma_b", model="claude-opus-5")
    assert r.status_code == 200, r.text
    piece = r.json()
    assert piece["tenant_id"] == "pharma_a"
    done = _wait_analysed(env, "pharma_a", piece["id"])
    assert done["status"] == "analyse" and done["summary"] == "Facture fournisseur"
    # Jamais de modèle, coût, confiance ni analyses pour une pharmacie.
    for key in ("model", "cost_xof", "confidence", "run_id", "ocr_runs"):
        assert key not in done
    assert env.calls == [ocr_core.default_model_id()]


def test_tracked_pharmacist_shares_parent_tenant(env):
    piece = _upload(env, "pharma_a").json()
    rows = env.client.get("/api/ocr-pieces", headers=_h("suivi_a")).json()
    assert [p["id"] for p in rows] == [piece["id"]]


def test_other_pharmacy_cannot_see_or_delete(env):
    piece = _upload(env, "pharma_a").json()
    assert env.client.get("/api/ocr-pieces", headers=_h("pharma_b")).json() == []
    # Le paramètre tenant_id est ignoré pour une pharmacie.
    assert env.client.get("/api/ocr-pieces?tenant_id=pharma_a", headers=_h("pharma_b")).json() == []
    for method, url in (("get", ""), ("get", "/download"), ("delete", "")):
        r = getattr(env.client, method)(f"/api/ocr-pieces/{piece['id']}{url}", headers=_h("pharma_b"))
        assert r.status_code == 403


def test_other_roles_refused(env):
    assert env.client.get("/api/ocr-pieces", headers=_h("secretaire")).status_code == 403


def test_staff_tools_refused_to_pharmacy(env):
    piece = _upload(env, "pharma_a").json()
    _wait_analysed(env, "pharma_a", piece["id"])
    for url in ("/api/ocr-pieces/ocr-models", "/api/ocr-pieces/ocr-stats", "/api/ocr-pieces/tenants"):
        assert env.client.get(url, headers=_h("pharma_a")).status_code == 403
    r = env.client.post(f"/api/ocr-pieces/{piece['id']}/reanalyze", headers=_h("pharma_a"),
                        json={"model": "claude-opus-5"})
    assert r.status_code == 403


def test_admin_flow_upload_review_reanalyze_stats(env):
    # L'admin doit choisir la pharmacie.
    assert _upload(env, "admin").status_code == 400
    assert _upload(env, "admin", tenant_id="pharma_a", model="gpt-4o").status_code == 400
    piece = _upload(env, "admin", tenant_id="pharma_a", model="claude-haiku-4-5-20251001").json()
    assert piece["tenant_label"] == "Pharmacie A" and piece["client_code"] == "PA"
    done = _wait_analysed(env, "admin", piece["id"])
    assert len(done["ocr_runs"]) == 1 and done["ocr_runs"][0]["cost_xof"] == 2.4
    run_id = done["ocr_runs"][0]["id"]

    # Évaluation 1-5 étoiles + correction d'un champ.
    assert env.client.post(f"/api/ocr-pieces/ocr-runs/{run_id}/review", headers=_h("admin"),
                           json={"rating": 6}).status_code == 422
    rv = env.client.post(f"/api/ocr-pieces/ocr-runs/{run_id}/review", headers=_h("admin"),
                         json={"rating": 4, "corrected_fields": {"total": "160000"}}).json()
    assert rv["rating"] == 4 and rv["accuracy"] == 0.5

    # Relance avec un autre modèle : deuxième analyse.
    r = env.client.post(f"/api/ocr-pieces/{piece['id']}/reanalyze", headers=_h("admin"),
                        json={"model": "claude-opus-5"})
    assert r.status_code == 200
    done = _wait_analysed(env, "admin", piece["id"])
    assert [x["model"] for x in done["ocr_runs"]] == ["claude-haiku-4-5-20251001", "claude-opus-5"]

    # Liste admin : résumé des analyses ; filtre par pharmacie.
    rows = env.client.get("/api/ocr-pieces?tenant_id=pharma_a", headers=_h("admin")).json()
    assert rows[0]["ocr_runs"][0]["rating"] == 4
    assert env.client.get("/api/ocr-pieces?tenant_id=pharma_b", headers=_h("admin")).json() == []

    # Tableau de bord.
    stats = env.client.get("/api/ocr-pieces/ocr-stats?period=all", headers=_h("admin")).json()
    assert stats["total"]["runs"] == 2
    assert env.client.get("/api/ocr-pieces/ocr-stats?period=hier", headers=_h("admin")).status_code == 400

    # Téléchargement puis suppression (fichier marqué supprimé).
    dl = env.client.get(f"/api/ocr-pieces/{piece['id']}/download", headers=_h("admin"))
    assert dl.status_code == 200 and dl.content == _png()
    assert env.client.delete(f"/api/ocr-pieces/{piece['id']}", headers=_h("admin")).status_code == 200
    assert env.client.get(f"/api/ocr-pieces/{piece['id']}", headers=_h("admin")).status_code == 404


def test_tenants_list_for_admin(env):
    rows = env.client.get("/api/ocr-pieces/tenants", headers=_h("admin")).json()
    ids = {r["id"] for r in rows}
    assert {"pharma_a", "pharma_b"} <= ids and "suivi_a" not in ids and "secretaire" not in ids


def test_bad_extension_refused(env):
    r = env.client.post("/api/ocr-pieces", headers=_h("pharma_a"),
                        files={"file": ("macro.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
