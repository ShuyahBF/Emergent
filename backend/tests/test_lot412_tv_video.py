"""Lot 412 — vidéos en streaming sur les écrans TV : ordres de la télécommande, adresse signée, Range, droits."""
import asyncio

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from routes import tv_video as tv
from routes.ecran_tv import empreinte

SECRET = "secret-de-la-tele-0123456789"
CONTENU = bytes(range(256)) * 40                      # 10 240 octets de « vidéo »


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def banc(monkeypatch):
    base = AsyncMongoMockClient()["test_tv_412"]
    _run(base.settings.insert_one({"_id": "global", "tv_ecrans": [
        {"id": "ecran-ok", "nom": "Salle d'attente", "empreinte": empreinte(SECRET), "modules": {"video": True}},
        {"id": "ecran-sans", "nom": "Hall", "empreinte": empreinte("autre-secret-0123456789"), "modules": {"hall": True}}]}))
    _run(base.media_library.insert_many([
        {"id": "v1", "kind": "video", "title": "Présentation", "size": len(CONTENU), "content_type": "video/mp4", "storage_path": "sawali/v1.mp4", "created_at": "2026-11-15"},
        {"id": "pdf", "kind": "pdf", "title": "Brochure", "size": 10, "storage_path": "sawali/b.pdf"},
        {"id": "supprimee", "kind": "video", "title": "Ancienne", "size": 5, "storage_path": "x", "is_deleted": True}]))

    def ouvrir(chemin, debut, fin):                    # remplace la lecture R2
        assert chemin == "sawali/v1.mp4"
        return iter([CONTENU[debut:fin + 1]])
    monkeypatch.setattr(tv, "_ouvrir_plage", ouvrir)

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "admin@test"}
    app, api = FastAPI(), APIRouter(prefix="/api")
    tv.setup_tv_video_routes(db=base, api=api, get_current_admin=admin)
    app.include_router(api)
    return TestClient(app), base


ADM, TELE = {"x-admin": "1"}, {"x-tv-secret": SECRET}


def test_range_en_tete():
    assert tv.lire_en_tete_range(None, 100) is None
    assert tv.lire_en_tete_range("bytes=0-9", 100) == (0, 9)
    assert tv.lire_en_tete_range("bytes=90-", 100) == (90, 99)
    assert tv.lire_en_tete_range("bytes=-10", 100) == (90, 99)
    assert tv.lire_en_tete_range("bytes=50-500", 100) == (50, 99)
    for faux in ("bytes=100-", "bytes=9-3", "bytes=-", "octets=1-2", "bytes=-0"):
        with pytest.raises(ValueError):
            tv.lire_en_tete_range(faux, 100)


def test_ordres_numerotes_et_lus_par_la_tele(banc):
    c, _ = banc
    assert c.get("/api/tv/video/commande?seq=0", headers=TELE).json() == {"seq": 0, "commande": None}
    r = c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-ok", "action": "lire", "video_id": "v1"})
    assert r.status_code == 200 and r.json()["seq"] == 1
    d = c.get("/api/tv/video/commande?seq=0", headers=TELE).json()
    assert d["seq"] == 1 and d["commande"]["action"] == "lire" and d["commande"]["titre"] == "Présentation" and d["commande"]["url"].startswith("/api/tv/video/flux/v1?e=ecran-ok&x=")
    assert c.get("/api/tv/video/commande?seq=1", headers=TELE).json()["commande"] is None            # déjà vu
    c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-ok", "action": "avancer", "delta": 30})
    d = c.get("/api/tv/video/commande?seq=1", headers=TELE).json()
    assert d["seq"] == 2 and d["commande"] == {**d["commande"], "action": "avancer", "delta": 30}


def test_validations_et_droits(banc):
    c, _ = banc
    assert c.post("/api/admin/tv/video/commande", json={"ecran_id": "ecran-ok", "action": "stop"}).status_code == 403          # pas administrateur
    assert c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-ok", "action": "danser"}).status_code == 422
    assert c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "inconnu", "action": "stop"}).status_code == 404
    assert c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-sans", "action": "stop"}).status_code == 409    # « Vidéos » non coché
    assert c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-ok", "action": "lire", "video_id": "pdf"}).status_code == 404   # pas une vidéo
    assert c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-ok", "action": "lire", "video_id": "supprimee"}).status_code == 404
    assert c.get("/api/tv/video/commande?seq=0").status_code == 401                                                              # télé inconnue
    assert c.get("/api/tv/video/commande?seq=0", headers={"x-tv-secret": "autre-secret-0123456789"}).status_code == 403          # écran sans « Vidéos »


def test_flux_signe_avec_range(banc):
    c, _ = banc
    c.post("/api/admin/tv/video/commande", headers=ADM, json={"ecran_id": "ecran-ok", "action": "lire", "video_id": "v1"})
    url = c.get("/api/tv/video/commande?seq=0", headers=TELE).json()["commande"]["url"]
    r = c.get(url)
    assert r.status_code == 200 and r.content == CONTENU and r.headers["accept-ranges"] == "bytes" and r.headers["content-type"].startswith("video/mp4")
    r = c.get(url, headers={"range": "bytes=100-199"})
    assert r.status_code == 206 and r.content == CONTENU[100:200] and r.headers["content-range"] == f"bytes 100-199/{len(CONTENU)}" and r.headers["content-length"] == "100"
    assert c.get(url, headers={"range": "bytes=-50"}).content == CONTENU[-50:]
    assert c.get(url, headers={"range": f"bytes={len(CONTENU)}-"}).status_code == 416
    # adresse falsifiée, mauvais écran ou autre vidéo : refus
    assert c.get(url.replace("e=ecran-ok", "e=ecran-sans")).status_code == 403
    assert c.get(url.replace("/v1?", "/pdf?")).status_code == 403
    assert c.get(url[:-3] + "000").status_code == 403


def test_adresse_expiree(banc):
    c, _ = banc
    passe = 1_000_000_000
    assert c.get(f"/api/tv/video/flux/v1?e=ecran-ok&x={passe}&s={tv.signer('ecran-ok', 'v1', passe)}").status_code == 403


def test_etat_renvoye_par_la_tele_et_vu_par_la_telecommande(banc):
    c, _ = banc
    assert c.post("/api/tv/video/etat", headers=TELE, json={"lecture": "lecture", "video_id": "v1", "position": 12.5, "duree": 300}).status_code == 200
    e = c.get("/api/admin/tv/video/etat/ecran-ok", headers=ADM).json()["etat"]
    assert e["lecture"] == "lecture" and e["position"] == 12.5 and e["duree"] == 300
    ecrans = c.get("/api/admin/tv/video/ecrans", headers=ADM).json()["ecrans"]
    assert [x["id"] for x in ecrans] == ["ecran-ok"] and ecrans[0]["en_ligne"] is True            # seul l'écran avec « Vidéos » est proposé
    assert [v["id"] for v in c.get("/api/admin/tv/video/videos", headers=ADM).json()["videos"]] == ["v1"]


# ---------- Écran « vidéos seules » : le client n'est pas exigé ----------
def _app_ecrans():
    from routes.ecran_tv import setup_ecran_tv_routes
    base = AsyncMongoMockClient()["test_tv_412_sans_client"]
    _run(base.users.insert_one({"id": "cli-1", "company": "Clinique A"}))

    async def admin(request: Request):
        if request.headers.get("x-admin") != "1":
            raise HTTPException(status_code=403, detail="admin requis")
        return {"email": "admin@test"}
    api = APIRouter(prefix="/api")
    setup_ecran_tv_routes(db=base, api=api, get_current_admin=admin)
    app = FastAPI(); app.include_router(api)
    return TestClient(app), base


def _code(c, secret):
    return c.post("/api/tv/appairage", json={"secret": secret}).json()["code"]


def test_ecran_videos_seules_sans_client():
    c, _ = _app_ecrans()
    # sans client, un contenu qui lit les données d'un client est refusé (messagerie, support par défaut ; hall)
    assert c.post("/api/admin/tv/appairer", headers=ADM, json={"code": _code(c, "secret-un-0123456789abcdef"), "nom": "A"}).status_code == 422
    assert c.post("/api/admin/tv/appairer", headers=ADM, json={"code": _code(c, "secret-deux-0123456789abcd"), "nom": "A", "modules": {"hall": True, "video": True}}).status_code == 422
    # vidéos seules : accepté sans client
    secret = "secret-trois-0123456789abc"
    r = c.post("/api/admin/tv/appairer", headers=ADM, json={"code": _code(c, secret), "nom": "Salle", "modules": {"video": True}})
    assert r.status_code == 200 and r.json()["ecran"]["client_id"] == "" and r.json()["ecran"]["modules"]["video"] is True
    # le flux de la télé ne plante pas sans client et annonce le contenu « video »
    f = c.get("/api/tv/flux", headers={"x-tv-secret": secret})
    assert f.status_code == 200 and f.json()["ecran"]["modules"]["video"] is True and "messages" not in f.json()
    # ajouter la messagerie plus tard exige un client
    ecran_id = r.json()["ecran"]["id"]
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", headers=ADM, json={"modules": {"video": True, "messagerie": True}}).status_code == 422
    assert c.put(f"/api/admin/tv/ecrans/{ecran_id}", headers=ADM, json={"client_id": "cli-1", "modules": {"video": True, "messagerie": True}}).status_code == 200
    # avec client : comportement inchangé
    assert c.post("/api/admin/tv/appairer", headers=ADM, json={"code": _code(c, "secret-quatre-0123456789ab"), "nom": "B", "client_id": "cli-1"}).status_code == 200


def test_en_ligne_depuis_l_interrogation_des_ordres_meme_sans_lecture(banc):
    """La télé interroge les ordres toutes les 2 s : c'est son signe de vie, même quand rien n'est en lecture."""
    c, _ = banc
    assert c.get("/api/admin/tv/video/ecrans", headers=ADM).json()["ecrans"][0]["en_ligne"] is False
    assert c.get("/api/admin/tv/video/etat/ecran-ok", headers=ADM).json()["en_ligne"] is False
    c.get("/api/tv/video/commande?seq=0", headers=TELE)
    assert c.get("/api/admin/tv/video/ecrans", headers=ADM).json()["ecrans"][0]["en_ligne"] is True
    assert c.get("/api/admin/tv/video/etat/ecran-ok", headers=ADM).json()["en_ligne"] is True


def test_signe_de_vie_ancien_n_est_plus_en_ligne(banc):
    c, base = banc
    _run(base.settings.update_one({"_id": "tv-video:ecran-ok"}, {"$set": {"vu": "2020-01-01T00:00:00+00:00"}}, upsert=True))
    assert c.get("/api/admin/tv/video/etat/ecran-ok", headers=ADM).json()["en_ligne"] is False
