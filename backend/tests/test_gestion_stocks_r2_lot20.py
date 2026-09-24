"""Lot 20 — Explorateur R2 de Gestion de Stocks : accès superviseur, dépôt par
les utilisateurs suivis autorisés (taille max par utilisateur, 1,5 Mo par
défaut), espace alloué par tenant (2 Go par défaut) avec refus motivé.

Tests autonomes : MongoDB simulé (mongomock-motor) et R2 simulé en mémoire —
aucun serveur, aucune clé, aucun réseau.
Lancer : cd backend && python -m pytest tests/test_gestion_stocks_r2_lot20.py -q
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MB = 1024 * 1024
USERS = {
    "admin": {"id": "admin", "role": "admin", "full_name": "Admin"},
    "sup": {"id": "sup", "role": "superviseur", "full_name": "Superviseur"},
    # Pharmacien suivi de la pharmacie PDP (tenant « t-pdp »), fiche tracked_users « tu-1 »
    "suivi": {"id": "suivi", "role": "client", "tracked_role": "Pharmacien", "tracked_user_id": "tu-1",
              "parent_client_id": "t-pdp", "full_name": "Pharmacien suivi"},
    "secretaire": {"id": "sec", "role": "client", "tracked_role": "Secrétaire", "tracked_user_id": "tu-2",
                   "parent_client_id": "t-pdp"},
}


@pytest.fixture()
def env(monkeypatch):
    objects: dict = {"PDP/Inventaires/ancien.xlsx": b"x" * 1000}
    r2 = types.ModuleType("r2_stocks_client")
    r2._bucket = lambda: "gestionstocks"
    r2.is_configured = lambda: True
    r2.list_objects = lambda prefix: [
        {"key": k, "size": len(v), "last_modified": "2026-09-23T10:00:00"}
        for k, v in objects.items() if k.startswith(prefix) and not k.endswith("/")
    ]
    r2.list_folder_markers = lambda prefix: [k for k in objects if k.startswith(prefix) and k.endswith("/")]
    r2.put_bytes = lambda key, data, ct="application/octet-stream": objects.__setitem__(key, data)
    r2.get_presigned_url = lambda key, expires_in=300: "https://r2/signed"
    r2.delete_object = lambda key: objects.pop(key, None)
    monkeypatch.setitem(sys.modules, "r2_stocks_client", r2)

    db = AsyncMongoMockClient()["sawali_test"]

    async def get_current_user(x_user: str = Header(...)):
        if x_user not in USERS:
            raise HTTPException(status_code=401)
        return USERS[x_user]

    async def get_current_admin(x_user: str = Header(...)):
        raise AssertionError("le module ne doit plus utiliser get_current_admin")

    from routes.gestion_stocks import attach_gestion_stocks_routes
    api = APIRouter(prefix="/api")
    attach_gestion_stocks_routes(api=api, db=db, get_current_user=get_current_user, get_current_admin=get_current_admin)
    app = FastAPI()
    app.include_router(api)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [
            {"id": "t-pdp", "role": "pharmacien", "company": "Pharmacie du Progrès", "client_code": "PDP"},
            *[dict(u) for u in USERS.values()],
        ])
        client.portal.call(db.tracked_users.insert_many, [
            {"id": "tu-1", "client_id": "t-pdp", "name": "Pharmacien suivi", "role": "Pharmacien"},
            {"id": "tu-2", "client_id": "t-pdp", "name": "Secrétaire", "role": "Secrétaire"},
        ])
        yield types.SimpleNamespace(client=client, db=db, objects=objects)


def _h(user):
    return {"X-User": user}


def _post_tracked(env, size, folder="Inventaires", name="f.pdf"):
    return env.client.post(f"/api/gestion-stocks/folders/{folder}/upload", headers=_h("suivi"),
                           files={"file": (name, b"a" * size, "application/pdf")})


def _set_rights(env, allowed, max_mb=None, who="admin"):
    body = {"allowed": allowed}
    if max_mb is not None:
        body["max_mb"] = max_mb
    return env.client.put("/api/admin/gestion-stocks/tracked-users/tu-1/upload-rights", headers=_h(who), json=body)


def test_superviseur_has_admin_access(env):
    assert env.client.get("/api/admin/gestion-stocks/clients", headers=_h("sup")).status_code == 200
    r = env.client.post("/api/admin/gestion-stocks/PDP/Rapports/upload", headers=_h("sup"),
                        files={"file": ("r.pdf", b"z" * 10, "application/pdf")})
    assert r.status_code == 200 and "PDP/Rapports/r.pdf" in env.objects
    ctx = env.client.get("/api/gestion-stocks/context", headers=_h("sup")).json()
    assert ctx["can_upload"] is True and ctx["upload_max_mb"] == 25 and ctx["bucket"] == "gestionstocks"


def test_tracked_user_not_allowed_by_default(env):
    ctx = env.client.get("/api/gestion-stocks/context", headers=_h("suivi")).json()
    assert ctx["can_upload"] is False
    r = _post_tracked(env, 100)
    assert r.status_code == 403 and "pas autorisé" in r.json()["detail"]


def test_rights_default_1_5_mb_and_refusal_message(env):
    got = env.client.get("/api/admin/gestion-stocks/tracked-users/tu-1/upload-rights", headers=_h("admin")).json()
    assert got == {"tracked_user_id": "tu-1", "allowed": False, "max_mb": 1.5, "default_max_mb": 1.5}
    assert _set_rights(env, True).status_code == 200
    ctx = env.client.get("/api/gestion-stocks/context", headers=_h("suivi")).json()
    assert ctx["can_upload"] is True and ctx["upload_max_mb"] == 1.5
    r = _post_tracked(env, 2 * MB, name="gros.pdf")
    assert r.status_code == 413
    assert "gros.pdf" in r.json()["detail"] and "1,5 Mo" in r.json()["detail"]
    ok = _post_tracked(env, MB, name="petit.pdf")
    assert ok.status_code == 200 and ok.json()["key"] == "PDP/Inventaires/petit.pdf"


def test_rights_are_configurable_per_tracked_user(env):
    _set_rights(env, True, max_mb=3)
    assert _post_tracked(env, 2 * MB).status_code == 200
    assert _set_rights(env, True, max_mb=0).status_code == 400
    assert _set_rights(env, True, max_mb=99).status_code == 400
    # Seuls l'admin et le superviseur règlent les droits.
    assert _set_rights(env, True, who="suivi").status_code == 403


def test_other_tracked_roles_cannot_upload(env):
    r = env.client.post("/api/gestion-stocks/folders/Inventaires/upload", headers=_h("secretaire"),
                        files={"file": ("f.pdf", b"a", "application/pdf")})
    assert r.status_code == 403


def test_tenant_quota_default_2gb_and_refusal(env):
    got = env.client.get("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin")).json()
    assert got["quota_gb"] == 2.0 and got["used_bytes"] == 1000 and got["client_code"] == "PDP"
    # Espace réduit à ~1 Mo : un dépôt qui le dépasserait est refusé, avec le motif.
    assert env.client.put("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin"),
                          json={"quota_gb": 0.001}).status_code == 200
    _set_rights(env, True)
    r = _post_tracked(env, int(1.2 * MB))
    assert r.status_code == 413 and "espace de stockage insuffisant" in r.json()["detail"]
    # Même règle pour un dépôt de l'administration.
    r2 = env.client.post("/api/admin/gestion-stocks/PDP/Autres/upload", headers=_h("admin"),
                         files={"file": ("g.pdf", b"a" * int(1.2 * MB), "application/pdf")})
    assert r2.status_code == 413
    assert env.client.put("/api/admin/gestion-stocks/tenants/t-pdp/storage", headers=_h("admin"),
                          json={"quota_gb": -1}).status_code == 400


def test_storage_endpoint_scoped_to_own_tenant(env):
    st = env.client.get("/api/gestion-stocks/storage?client_code=AUTRE", headers=_h("suivi")).json()
    assert st["client_code"] == "PDP" and st["files"] == 1 and st["quota_bytes"] == 2 * 1024 ** 3
    staff = env.client.get("/api/gestion-stocks/storage?client_code=PDP", headers=_h("sup")).json()
    assert staff["used_bytes"] == 1000


def test_real_folders_and_root_files_are_listed(env):
    # Fichier déposé à la racine du code client (ex. via le tableau de bord Cloudflare)
    # et sous-dossier non standard : tous deux doivent apparaître.
    env.objects["PDP/INV DEC 2024 - PDP.pdf"] = b"p" * 500
    env.objects["PDP/Archives 2024/vieux.pdf"] = b"q" * 10
    env.objects["AUTRE/secret.pdf"] = b"s"
    got = env.client.get("/api/gestion-stocks/folders", headers=_h("suivi")).json()
    assert got["client_code"] == "PDP" and got["root_files"] == 1
    assert got["extra_folders"] == ["Archives 2024"] and got["folders"][:6][0] == "Inventaires"
    root = env.client.get("/api/gestion-stocks/folders/_racine/files", headers=_h("suivi")).json()
    assert [f["name"] for f in root["files"]] == ["INV DEC 2024 - PDP.pdf"]
    extra = env.client.get("/api/gestion-stocks/folders/Archives 2024/files", headers=_h("suivi")).json()
    assert [f["name"] for f in extra["files"]] == ["vieux.pdf"]


def test_folder_names_cannot_escape_tenant(env):
    for bad in ("..", ".cache"):
        assert env.client.get(f"/api/gestion-stocks/folders/{bad}/files", headers=_h("suivi")).status_code in (404, 405)
    # Pas de dépôt à la racine.
    _set_rights(env, True)
    r = env.client.post("/api/gestion-stocks/folders/_racine/upload", headers=_h("suivi"),
                        files={"file": ("f.pdf", b"a", "application/pdf")})
    assert r.status_code == 400


def test_standard_folders_are_created_once_in_r2(env):
    got = env.client.get("/api/gestion-stocks/folders", headers=_h("suivi")).json()
    # « Inventaires » existe déjà (un fichier dedans) : seuls les 5 autres sont créés.
    assert got["created_folders"] == ["Rapports", "Analyses", "Controle qualite", "Factures", "Autres"]
    assert "PDP/Rapports/" in env.objects and env.objects["PDP/Rapports/"] == b""
    again = env.client.get("/api/gestion-stocks/folders", headers=_h("suivi")).json()
    assert again["created_folders"] == [] and again["extra_folders"] == []
    # Les marqueurs ne sont ni des fichiers listés ni de l'espace occupé.
    assert env.client.get("/api/gestion-stocks/folders/Rapports/files", headers=_h("suivi")).json()["files"] == []
    assert env.client.get("/api/gestion-stocks/storage", headers=_h("suivi")).json()["files"] == 1
    # Un code saisi par l'administration qui ne correspond à aucun client ne crée rien.
    none = env.client.get("/api/gestion-stocks/folders?client_code=XYZ", headers=_h("admin")).json()
    assert none["created_folders"] == [] and not any(k.startswith("XYZ/") for k in env.objects)


def test_default_bucket_is_gestionstocks(monkeypatch):
    """Sans R2_STOCKS_BUCKET, le compartiment par défaut est « gestionstocks » (sans tiret)."""
    pytest.importorskip("boto3")
    monkeypatch.delitem(sys.modules, "r2_stocks_client", raising=False)
    import importlib
    real = importlib.import_module("r2_stocks_client")
    monkeypatch.delenv("R2_STOCKS_BUCKET", raising=False)
    assert real._bucket() == "gestionstocks"
    monkeypatch.setenv("R2_STOCKS_BUCKET", "autre")
    assert real._bucket() == "autre"
