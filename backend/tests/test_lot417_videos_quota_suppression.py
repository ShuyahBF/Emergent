"""Lot 417 — espace vidéos plafonné (« 120 Mo / 2 Go ») et suppression de vidéos choisies."""
import asyncio

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import object_storage
import storage
from routes import media_library as ml
from routes import tv_video as tv

MO = 1024 * 1024
ADM = {"x-admin": "1"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_libelles_de_taille():
    assert ml.libelle_taille(120 * MO) == "120 Mo"
    assert ml.libelle_taille(1536 * MO) == "1,5 Go"
    assert ml.libelle_taille(2048 * MO) == "2 Go"
    assert ml.libelle_taille(0) == "0 Mo"
    assert ml.libelle_taille(int(2.5 * MO)) == "2,5 Mo"


@pytest.fixture()
def banc(monkeypatch):
    base = AsyncMongoMockClient()["test_417"]
    _run(base.media_library.insert_many([
        {"id": "a", "kind": "video", "title": "A", "size": 100 * MO, "storage_path": "sawali/a.mp4", "created_at": "2026-11-01"},
        {"id": "b", "kind": "video", "title": "B", "size": 20 * MO, "storage_path": "sawali/b.mp4", "created_at": "2026-11-02"},
        {"id": "pdf", "kind": "pdf", "title": "Brochure", "size": 5 * MO, "storage_path": "sawali/p.pdf"},
        {"id": "vieille", "kind": "video", "title": "Ancienne", "size": 900 * MO, "storage_path": "sawali/v.mp4", "is_deleted": True}]))
    _run(base.settings.insert_many([
        {"_id": "tv-video:ecran-1", "seq": 3, "commande": None, "etat": {"lecture": "lecture", "video_id": "a"}},
        {"_id": "tv-video:ecran-2", "seq": 1, "commande": None, "etat": {"lecture": "lecture", "video_id": "b"}},
        {"_id": "tv-video:ecran-3", "seq": 0, "commande": None, "etat": {"lecture": "arret", "video_id": "a"}}]))
    effaces = []
    monkeypatch.setattr(storage, "storage_available", lambda: True)
    monkeypatch.setattr(storage, "delete_bytes", lambda chemin, normaliser=True: effaces.append(chemin) or 1)
    monkeypatch.setattr(object_storage, "is_enabled", lambda: False)                   # envoi en octets (pas de R2 en test)

    async def en_octets(db, *, data, **kw):
        return {"id": "o", "path": "sawali/n.mp4", "url": "/api/files/sawali/n.mp4", "size": len(data), "content_type": kw["content_type"]}

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "admin@test", "id": "u1", "role": "admin"}
    api = APIRouter(prefix="/api")
    ml.setup_media_library_routes(db=base, api=api, get_current_user=admin, save_and_log=en_octets)
    tv.setup_tv_video_routes(db=base, api=api, get_current_admin=admin)
    app = FastAPI(); app.include_router(api)
    return TestClient(app), base, effaces


def test_espace_utilise_ne_compte_que_les_videos_non_supprimees(banc):
    c, _, _ = banc
    r = c.get("/api/admin/tv/video/videos", headers=ADM).json()
    assert r["quota"] == {"utilise": 120 * MO, "max": 2048 * MO, "libelle": "120 Mo / 2 Go"}
    assert [v["id"] for v in r["videos"]] == ["b", "a"]


def test_envoi_refuse_quand_l_espace_manque(banc, monkeypatch):
    c, _, _ = banc
    monkeypatch.setenv("TV_VIDEOS_QUOTA_MO", "130")                    # 130 Mo au total, 120 déjà utilisés
    gros = c.post("/api/admin/media-library", headers=ADM, files={"file": ("n.mp4", b"\x00" * (11 * MO), "video/mp4")}, data={"title": "N"})
    assert gros.status_code == 413 and "120 Mo / 130 Mo" in gros.json()["detail"] and "11 Mo" in gros.json()["detail"]
    petit = c.post("/api/admin/media-library", headers=ADM, files={"file": ("n.mp4", b"\x00" * (9 * MO), "video/mp4")}, data={"title": "N"})
    assert petit.status_code == 200
    # un PDF n'est pas concerné par l'espace des vidéos
    assert c.post("/api/admin/media-library", headers=ADM, files={"file": ("b.pdf", b"%PDF-1.4", "application/pdf")}, data={"title": "P"}).status_code == 200


def test_suppression_de_videos_choisies(banc):
    c, base, effaces = banc
    r = c.post("/api/admin/tv/video/supprimer", headers=ADM, json={"ids": ["a", "pdf", "inconnue", "a"]})
    assert r.status_code == 200
    d = r.json()
    assert d["supprimees"] == ["a"] and {e["id"] for e in d["echecs"]} == {"pdf", "inconnue"} and d["ok"] is False
    assert effaces == ["sawali/a.mp4"]                                   # le fichier est vraiment effacé du stockage
    assert d["quota"]["libelle"] == "20 Mo / 2 Go"                       # l'espace est rendu
    assert _run(base.media_library.find_one({"id": "a"}))["is_deleted"] is True and not _run(base.media_library.find_one({"id": "b"})).get("is_deleted")
    # la télé qui lisait « a » reçoit « stop » ; celle qui lit « b » ou qui est à l'arrêt n'est pas touchée
    e1 = _run(base.settings.find_one({"_id": "tv-video:ecran-1"})); e2 = _run(base.settings.find_one({"_id": "tv-video:ecran-2"})); e3 = _run(base.settings.find_one({"_id": "tv-video:ecran-3"}))
    assert e1["seq"] == 4 and e1["commande"]["action"] == "stop" and e2["seq"] == 1 and e3["seq"] == 0


def test_suppression_demande_une_selection_et_les_droits(banc):
    c, _, _ = banc
    assert c.post("/api/admin/tv/video/supprimer", headers=ADM, json={"ids": []}).status_code == 422
    assert c.post("/api/admin/tv/video/supprimer", json={"ids": ["a"]}).status_code == 403


def test_fichier_non_efface_garde_l_entree(banc, monkeypatch):
    c, base, _ = banc
    def echec(chemin, normaliser=True):
        raise RuntimeError("R2 injoignable")
    monkeypatch.setattr(storage, "delete_bytes", echec)
    d = c.post("/api/admin/tv/video/supprimer", headers=ADM, json={"ids": ["b"]}).json()
    assert d["supprimees"] == [] and "R2 injoignable" in d["echecs"][0]["raison"]
    assert not _run(base.media_library.find_one({"id": "b"})).get("is_deleted")          # rien n'est perdu : on peut réessayer
