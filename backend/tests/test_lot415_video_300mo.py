"""Lot 415 — vidéos jusqu'à 300 Mo : envoi par morceaux (jamais lues d'un bloc en mémoire), plafond, autres fichiers inchangés."""
import asyncio

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import object_storage
from routes import media_library as ml


@pytest.fixture()
def banc(monkeypatch):
    base = AsyncMongoMockClient()["test_415"]
    appels = {"morceaux": [], "octets": []}

    async def par_morceaux(db, *, fileobj, size, **kw):
        lu = 0
        while True:                                     # lecture par blocs, comme boto3 upload_fileobj
            bloc = fileobj.read(64 * 1024)
            if not bloc:
                break
            lu += len(bloc)
        appels["morceaux"].append((lu, size, kw["kind"]))
        return {"id": "o1", "path": "sawali/x/v.mp4", "url": "/api/files/sawali/x/v.mp4", "size": size, "content_type": kw["content_type"]}

    async def en_octets(db, *, data, **kw):
        appels["octets"].append(len(data))
        return {"id": "o2", "path": "sawali/x/f", "url": "/api/files/sawali/x/f", "size": len(data), "content_type": kw["content_type"]}

    monkeypatch.setattr(object_storage, "is_enabled", lambda: True)
    monkeypatch.setattr(object_storage, "save_fileobj_and_log", par_morceaux)
    api = APIRouter(prefix="/api")
    ml.setup_media_library_routes(db=base, api=api, get_current_user=lambda: {"id": "u1", "role": "admin", "email": "a@t"}, save_and_log=en_octets)
    app = FastAPI(); app.include_router(api)
    return TestClient(app), base, appels


def _envoi(c, nom, contenu, type_, titre="T", **extra):
    return c.post("/api/admin/media-library", files={"file": (nom, contenu, type_)}, data={"title": titre, **extra})


def test_plafond_video_300_mo():
    assert ml.MAX_BYTES["video"] == 300 * 1024 * 1024


def test_video_envoyee_par_morceaux(banc):
    c, base, appels = banc
    r = _envoi(c, "film.mp4", b"\x00" * (3 * 1024 * 1024 + 17), "video/mp4", titre="Film")
    assert r.status_code == 200, r.text
    assert r.json()["size"] == 3 * 1024 * 1024 + 17 and appels["morceaux"] == [(3 * 1024 * 1024 + 17, 3 * 1024 * 1024 + 17, "media_library/video")] and appels["octets"] == []


def test_video_trop_grosse_et_vide_refusees(banc, monkeypatch):
    c, base, appels = banc
    monkeypatch.setitem(ml.MAX_BYTES, "video", 1024)
    r = _envoi(c, "gros.mp4", b"\x00" * 2048, "video/mp4")
    assert r.status_code == 413 and appels["morceaux"] == []
    assert _envoi(c, "vide.mp4", b"", "video/mp4").status_code == 400


def test_pdf_garde_le_chemin_en_octets(banc):
    c, base, appels = banc
    r = _envoi(c, "b.pdf", b"%PDF-1.4 petit", "application/pdf", titre="Brochure")
    assert r.status_code == 200 and appels["octets"] == [len(b"%PDF-1.4 petit")] and appels["morceaux"] == []


def test_sans_r2_la_video_prend_le_chemin_d_origine(banc, monkeypatch):
    c, base, appels = banc
    monkeypatch.setattr(object_storage, "is_enabled", lambda: False)
    r = _envoi(c, "film.mp4", b"\x00" * 5000, "video/mp4")
    assert r.status_code == 200 and appels["octets"] == [5000] and appels["morceaux"] == []
