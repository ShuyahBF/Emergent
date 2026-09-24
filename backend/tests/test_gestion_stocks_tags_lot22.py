"""Lot 22 — Tags et recherche des documents de l'Explorateur Stockage R2 :
fiche Mongo `stock_files` par fichier, tags à la saisie et après coup,
recherche dans tous les dossiers du client, droits (admin/superviseur : tout ;
Pharmacien suivi autorisé : ses propres fichiers), suggestions IA facultatives.

Tests autonomes : MongoDB simulé (mongomock-motor), R2 simulé en mémoire, IA
simulée — aucun serveur, aucune clé, aucun réseau.
Lancer : cd backend && python -m pytest tests/test_gestion_stocks_tags_lot22.py -q
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

USERS = {
    "admin": {"id": "admin", "role": "admin", "full_name": "Admin"},
    "sup": {"id": "sup", "role": "superviseur", "full_name": "Superviseur"},
    # Pharmacien suivi de la pharmacie PDP (tenant « t-pdp »), fiche tracked_users « tu-1 »
    "suivi": {"id": "suivi", "role": "client", "tracked_role": "Pharmacien", "tracked_user_id": "tu-1",
              "parent_client_id": "t-pdp", "full_name": "Pharmacien suivi"},
    # Autre Pharmacien suivi du même tenant, NON autorisé à déposer
    "lecteur": {"id": "lecteur", "role": "client", "tracked_role": "Pharmacien", "tracked_user_id": "tu-2",
                "parent_client_id": "t-pdp", "full_name": "Lecteur"},
}

# Réponse simulée de ocr_core.analyze_document
FAKE_OCR = {
    "document_type": "Facture", "summary": "Facture COPHARMED de décembre 2024 pour 12 produits.",
    "extracted_fields": {"fournisseur": "COPHARMED", "date": "2024-12-15", "montant total": 150000},
    "flags": [], "model": "claude-haiku-4-5-20251001", "cost_xof": 1.25,
}


@pytest.fixture()
def env(monkeypatch):
    objects: dict = {
        "PDP/Inventaires/ancien.xlsx": b"x" * 1000,      # fichier posé avant le lot 22
        "AUTRE/Factures/secret.pdf": b"s" * 10,          # autre client
    }
    r2 = types.ModuleType("r2_stocks_client")
    r2._bucket = lambda: "gestionstocks"
    r2.is_configured = lambda: True
    r2.list_objects = lambda prefix: [
        {"key": k, "size": len(v), "last_modified": f"2026-09-2{i % 9}T10:00:00"}
        for i, (k, v) in enumerate(objects.items()) if k.startswith(prefix) and not k.endswith("/")
    ]
    r2.list_folder_markers = lambda prefix: [k for k in objects if k.startswith(prefix) and k.endswith("/")]
    r2.put_bytes = lambda key, data, ct="application/octet-stream": objects.__setitem__(key, data)
    r2.get_bytes = lambda key: objects[key]
    r2.get_presigned_url = lambda key, expires_in=300: "https://r2/signed"
    r2.delete_object = lambda key: objects.pop(key, None)
    monkeypatch.setitem(sys.modules, "r2_stocks_client", r2)

    # IA simulée : compte les appels
    calls = []

    async def fake_analyze(data, content_type, filename, model_id=None, *, system_prompt, default_model=None):
        calls.append({"filename": filename, "model": model_id, "content_type": content_type})
        return dict(FAKE_OCR)
    import ocr_core
    monkeypatch.setattr(ocr_core, "analyze_document", fake_analyze)

    db = AsyncMongoMockClient()["sawali_test_lot22"]

    async def get_current_user(x_user: str = Header(...)):
        if x_user not in USERS:
            raise HTTPException(status_code=401)
        return USERS[x_user]

    from routes.gestion_stocks import attach_gestion_stocks_routes
    api = APIRouter(prefix="/api")
    attach_gestion_stocks_routes(api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_user)
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [
            {"id": "t-pdp", "role": "pharmacien", "company": "Pharmacie du Progrès", "client_code": "PDP"},
            {"id": "t-autre", "role": "pharmacien", "company": "Autre", "client_code": "AUTRE"},
            *[dict(u) for u in USERS.values()],
        ])
        client.portal.call(db.tracked_users.insert_many, [
            {"id": "tu-1", "client_id": "t-pdp", "role": "Pharmacien", "r2_upload_allowed": True, "r2_upload_max_mb": 5},
            {"id": "tu-2", "client_id": "t-pdp", "role": "Pharmacien"},
        ])
        yield types.SimpleNamespace(client=client, db=db, objects=objects, calls=calls)


def _h(user):
    return {"X-User": user}


def _upload(env, name="facture-dec.pdf", tags="", description="", who="suivi", folder="Factures"):
    url = (f"/api/gestion-stocks/folders/{folder}/upload" if who == "suivi"
           else f"/api/admin/gestion-stocks/PDP/{folder}/upload")
    return env.client.post(url, headers=_h(who), data={"tags": tags, "description": description},
                           files={"file": (name, b"%PDF-1.4 test", "application/pdf")})


def _files(env, folder, who="suivi"):
    params = {} if who == "suivi" or who == "lecteur" else {"client_code": "PDP"}
    return env.client.get(f"/api/gestion-stocks/folders/{folder}/files", headers=_h(who), params=params).json()["files"]


def _drain(env):
    """Attend la fin des suggestions IA lancées en arrière-plan après un dépôt."""
    from routes import gestion_stocks_tags as gt

    async def _wait():
        for _ in range(50):
            if not gt._PENDING:
                return
            await asyncio.sleep(0.01)
    env.client.portal.call(_wait)


def test_upload_with_tags_and_description(env):
    r = _upload(env, tags="Facture, facture ,  Fournisseur  COPHARMED", description="  Livraison   de décembre ")
    assert r.status_code == 200
    body = r.json()
    assert body["tags"] == ["facture", "fournisseur copharmed"]  # nettoyés, sans doublon
    assert body["description"] == "Livraison de décembre" and body["ai_tags_started"] is False
    f = next(x for x in _files(env, "Factures") if x["name"] == "facture-dec.pdf")
    assert f["tags"] == ["facture", "fournisseur copharmed"] and f["can_edit"] is True
    assert f["uploaded_by_name"] == "Pharmacien suivi"


def test_existing_files_get_a_record_and_rights(env):
    f = _files(env, "Inventaires")[0]
    assert f["name"] == "ancien.xlsx" and f["tags"] == [] and f["can_edit"] is False
    doc = env.client.portal.call(env.db.stock_files.find_one, {"key": "PDP/Inventaires/ancien.xlsx"})
    assert doc["uploaded_by"] is None and doc["client_code"] == "PDP"
    # Le Pharmacien suivi ne tague pas un fichier qu'il n'a pas déposé…
    r = env.client.put("/api/gestion-stocks/files/meta", headers=_h("suivi"),
                       json={"key": "PDP/Inventaires/ancien.xlsx", "tags": ["inventaire"]})
    assert r.status_code == 403
    # … le superviseur, si.
    r = env.client.put("/api/gestion-stocks/files/meta", headers=_h("sup"),
                       json={"key": "PDP/Inventaires/ancien.xlsx", "tags": "Inventaire, 2024", "description": "Clôture"})
    assert r.status_code == 200 and r.json()["tags"] == ["inventaire", "2024"]


def test_tracked_user_edits_own_file_only_when_allowed(env):
    _upload(env, tags="facture")
    key = "PDP/Factures/facture-dec.pdf"
    ok = env.client.put("/api/gestion-stocks/files/meta", headers=_h("suivi"), json={"key": key, "tags": ["urgent"]})
    assert ok.status_code == 200 and ok.json()["tags"] == ["urgent"]
    # Un Pharmacien suivi non autorisé à déposer voit les tags mais ne modifie rien.
    assert _files(env, "Factures", who="lecteur")[0]["can_edit"] is False
    assert env.client.put("/api/gestion-stocks/files/meta", headers=_h("lecteur"),
                          json={"key": key, "tags": ["x"]}).status_code == 403
    # Et personne ne vise un fichier hors de son tenant.
    assert env.client.put("/api/gestion-stocks/files/meta", headers=_h("suivi"),
                          json={"key": "AUTRE/Factures/secret.pdf", "tags": ["x"]}).status_code == 403


def test_search_across_folders_accents_tags_and_tenant(env):
    _upload(env, name="facture-dec.pdf", tags="facture, copharmed", description="Contrôle des prix")
    _upload(env, name="rapport.pdf", tags="rapport", folder="Rapports")
    def search(**params):
        return env.client.get("/api/gestion-stocks/search", headers=_h("suivi"), params=params).json()
    # Sans accent ni majuscule, dans la description
    assert [r["name"] for r in search(q="CONTROLE prix")["results"]] == ["facture-dec.pdf"]
    # Par tag, tous dossiers confondus
    res = search(tags="Rapport")["results"]
    assert [(r["name"], r["folder"]) for r in res] == [("rapport.pdf", "Rapports")]
    # Par nom de fichier (fichier sans tag), et jamais les fichiers d'un autre client
    assert [r["name"] for r in search(q="ancien")["results"]] == ["ancien.xlsx"]
    assert search(q="secret")["results"] == []
    # Un fichier supprimé dans Cloudflare disparaît des résultats même si sa fiche existe.
    env.objects.pop("PDP/Rapports/rapport.pdf")
    assert search(tags="rapport")["results"] == []


def test_tag_counts(env):
    _upload(env, name="a.pdf", tags="facture, copharmed")
    _upload(env, name="b.pdf", tags="facture")
    got = env.client.get("/api/gestion-stocks/tags", headers=_h("suivi")).json()
    assert got["tags"] == [{"tag": "facture", "count": 2}, {"tag": "copharmed", "count": 1}]


def test_ai_suggestions_disabled_by_default_then_on_demand(env):
    _upload(env, tags="facture")
    key = "PDP/Factures/facture-dec.pdf"
    r = env.client.post("/api/gestion-stocks/files/suggest-tags", headers=_h("suivi"), json={"key": key})
    assert r.status_code == 403 and "pas activées" in r.json()["detail"] and env.calls == []
    # L'administration active l'option pour ce client (sans toucher à l'espace alloué).
    put = env.client.put("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin"), json={"ai_tags": True})
    assert put.status_code == 200
    st = env.client.get("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin")).json()
    assert st["ai_tags"] is True and st["quota_gb"] == 2.0
    r = env.client.post("/api/gestion-stocks/files/suggest-tags", headers=_h("suivi"), json={"key": key})
    assert r.status_code == 200
    body = r.json()
    # « facture » est déjà posé : il n'est plus proposé.
    assert body["ai_suggested_tags"] == ["copharmed", "décembre 2024", "2024"]
    assert body["ai_suggested_description"].startswith("Facture COPHARMED") and body["cost_xof"] == 1.25
    assert env.calls[-1]["model"] == "claude-haiku-4-5-20251001"
    doc = env.client.portal.call(env.db.stock_files.find_one, {"key": key})
    assert doc["tags"] == ["facture"]  # jamais appliqués d'office
    assert doc["ai_cost_xof"] == 1.25


def test_ai_runs_in_background_after_upload_when_enabled(env):
    env.client.put("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin"), json={"ai_tags": True})
    r = _upload(env, name="livraison.pdf")
    assert r.json()["ai_tags_started"] is True
    _drain(env)
    f = next(x for x in _files(env, "Factures") if x["name"] == "livraison.pdf")
    assert f["ai_suggested_tags"] == ["facture", "copharmed", "décembre 2024", "2024"]
    # Un Excel n'est pas analysé (ocr_core ne le lit pas).
    r = env.client.post("/api/gestion-stocks/folders/Factures/upload", headers=_h("suivi"),
                        files={"file": ("stock.xlsx", b"PK..", "application/vnd.ms-excel")})
    assert r.json()["ai_tags_started"] is False


def test_folders_expose_ai_flag_and_delete_removes_record(env):
    assert env.client.get("/api/gestion-stocks/folders", headers=_h("suivi")).json()["ai_tags_enabled"] is False
    _upload(env, who="admin", tags="facture")
    key = "PDP/Factures/facture-dec.pdf"
    assert env.client.delete("/api/admin/gestion-stocks/file", headers=_h("admin"), params={"key": key}).status_code == 200
    assert env.client.portal.call(env.db.stock_files.find_one, {"key": key}) is None


def test_helpers():
    from routes.gestion_stocks_tags import clean_tags, norm_text, split_key, tags_from_ocr
    assert clean_tags("A, a;B\n<script>c</script>") == ["a", "b", "scriptcscript"]
    assert len(clean_tags([f"t{i}" for i in range(30)])) == 15
    assert clean_tags(["x" * 60])[0] == "x" * 40
    assert norm_text("  Contrôle   Qualité ") == "controle qualite"
    assert split_key("PDP", "PDP/INV.pdf") == {"folder": "_racine", "name": "INV.pdf"}
    assert split_key("PDP", "PDP/Archives 2024/a/b.pdf") == {"folder": "Archives 2024", "name": "a/b.pdf"}
    assert tags_from_ocr({"document_type": None, "extracted_fields": {"période": "2025-03"}}) == ["mars 2025", "2025"]
