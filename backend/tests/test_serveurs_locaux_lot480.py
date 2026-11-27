"""Lot 480 — serveurs locaux remontés par Loois : contrôle des adresses, secret de passerelle (un seul par client, régénérable), ticket local et session signés par clés dérivées,
statut de l'appareil avec adresses locales, droits administrateur. Aucun accès réseau (Mongo simulé)."""
import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot480")

import jwt
import mongomock_motor
import pytest

import appareils_android as aa
import serveurs_locaux as sl


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_adresses_privees_seulement_et_validation():
    assert sl.adresse_privee("192.168.1.10") and sl.adresse_privee("10.0.0.5") and sl.adresse_privee("172.20.3.4")
    assert not sl.adresse_privee("8.8.8.8") and not sl.adresse_privee("127.0.0.1") and not sl.adresse_privee("169.254.1.1") and not sl.adresse_privee("fe80::1") and not sl.adresse_privee("n'importe quoi")
    ok, err = sl.valider_infos({"serveur_hfsql": "jSHUYAH:4900", "ips_locales": ["192.168.1.10", "8.8.8.8", "192.168.1.10", "10.0.0.7"], "port_passerelle": 8750, "zone": "docx=CMC", "base": "myAurora-CMC", "version": "1.2"})
    assert err == "" and ok["ips"] == ["192.168.1.10", "10.0.0.7"] and ok["port"] == 8750 and ok["serveur_hfsql"] == "jSHUYAH:4900"        # publique et doublon écartées
    for mauvais in ({"ips_locales": ["8.8.8.8"], "port_passerelle": 8750}, {"ips_locales": ["10.0.0.1"], "port_passerelle": 80}, {"ips_locales": ["10.0.0.1"], "port_passerelle": "x"},
                    {"ips_locales": ["10.0.0.1"], "port_passerelle": 8750, "serveur_hfsql": "a b; DROP"}, {"ips_locales": ["10.0.0.1"], "port_passerelle": 8750, "base": "x y/z"}, "pas un objet"):
        assert sl.valider_infos(mauvais)[1] != ""


def test_cles_derivees_tickets_et_sessions():
    # les clés dérivées sont celles que calcule la passerelle (SHA-256 d'une étiquette et du secret)
    import hashlib
    assert sl.cle_ticket("S") == hashlib.sha256(b"loois-android-ticket|S").hexdigest() and sl.cle_session("S") == hashlib.sha256(b"loois-android-session|S").hexdigest()
    t = sl.creer_ticket("S", "a1", "CMC", "docx=CMC", "myAurora-CMC")
    d = sl.lire_ticket("S", t)
    assert d["aid"] == "a1" and d["client"] == "CMC" and d["zone"] == "docx=CMC" and d["base"] == "myAurora-CMC"
    assert sl.lire_ticket("AUTRE", t) is None and sl.lire_ticket("S", "xx") is None
    assert sl.lire_session("S", t) is None and sl.lire_ticket("S", sl.creer_session("S", "a1", "awa", "", {"caisse": True})) is None      # un ticket n'est pas une session, et inversement
    s = sl.creer_session("S", "a1", "awa", "LABO", {"caisse": True})
    assert sl.lire_session("S", s)["login"] == "awa" and sl.lire_session("S", s)["d"] == {"caisse": True}
    vieux = sl.creer_ticket("S", "a1", "CMC", "z", "b", maintenant=datetime.now(timezone.utc) - timedelta(hours=73))
    assert sl.lire_ticket("S", vieux) is None                                                                                      # expiré après 72 h
    assert jwt.get_unverified_header(t)["alg"] == "HS256"


def test_urls_locales_recentes_sans_doublon():
    maintenant = datetime.now(timezone.utc)
    doc = {"machines": {
        "PC1": {"poste": "PC1", "ips": ["192.168.1.10"], "port": 8750, "vu_le": (maintenant - timedelta(hours=1)).isoformat(), "serveur_hfsql": "SRV:4900"},
        "PC2": {"poste": "PC2", "ips": ["192.168.1.10", "10.0.0.9"], "port": 8750, "vu_le": maintenant.isoformat()},
        "VIEUX": {"poste": "VIEUX", "ips": ["192.168.9.9"], "port": 8750, "vu_le": (maintenant - timedelta(days=8)).isoformat()}}}
    urls = sl.urls_locales(doc, maintenant)
    assert [u["url"] for u in urls] == ["http://192.168.1.10:8750", "http://10.0.0.9:8750"] and urls[0]["poste"] == "PC2"               # la plus récente d'abord ; machine de 8 jours écartée


def construire_banc():
    """Banc d'essai (application FastAPI, Mongo simulé) : utilisé par les tests et par le script qui produit les exemples de réponses de l'application Android."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.appareils_android as ra
    import routes.serveurs_locaux as rs
    ra._limites.clear(); rs._signaux.clear()
    db = mongomock_motor.AsyncMongoMockClient()["test_lot480"]
    etat = {"user": {"id": "u1", "role": "admin"}, "cle_ok": True}

    async def utilisateur():
        return etat["user"]

    async def identifier(db_, cle):
        return {"type": "client", "code": "CMC"} if cle == "LK-bonne" else ({"type": "commune"} if cle == "commune" else None)
    app = FastAPI()
    api = APIRouter(prefix="/api")
    ra.setup_appareils_android_routes(db=db, api=api, get_current_user=utilisateur)
    rs.setup_serveurs_locaux_routes(db=db, api=api, get_current_user=utilisateur, identifier_cle=identifier)
    app.include_router(api)
    return TestClient(app), etat, db


@pytest.fixture()
def banc():
    return construire_banc()


H = {"X-Loois-Cle": "LK-bonne", "X-Loois-Poste": "PC-CMC-1", "X-Loois-Base": "CMC"}
INFOS = {"serveur_hfsql": "jSHUYAH:4900", "ips_locales": ["192.168.1.10"], "port_passerelle": 8750, "zone": "docx=CMC", "base": "myAurora-CMC", "version": "1.0"}


def test_signalement_du_service_secret_unique_et_refus(banc):
    c, _, db = banc
    assert c.post("/api/loois/serveur-local", json=INFOS).status_code == 401                                                     # sans clé
    assert c.post("/api/loois/serveur-local", json=INFOS, headers={**H, "X-Loois-Cle": "commune"}).status_code == 401           # clé commune refusée : seule une clé client identifie un établissement
    assert c.post("/api/loois/serveur-local", json={**INFOS, "ips_locales": ["8.8.8.8"]}, headers=H).status_code == 422
    r = c.post("/api/loois/serveur-local", json=INFOS, headers=H)
    assert r.status_code == 200
    secret = r.json()["secret_passerelle"]
    assert len(secret) > 30 and r.json()["ticket_ttl_h"] == 72 and r.json()["client"] == "CMC"
    # une 2e machine du même client reçoit le MÊME secret ; le secret n'est pas stocké en clair
    r2 = c.post("/api/loois/serveur-local", json={**INFOS, "ips_locales": ["192.168.1.11"]}, headers={**H, "X-Loois-Poste": "PC-CMC-2"})
    assert r2.json()["secret_passerelle"] == secret
    assert secret not in str(run(db.loois_reglages.find_one({"id": "serveurs_locaux"})))
    # l'administrateur voit les machines et les adresses, jamais le secret
    liste = c.get("/api/admin/serveurs-locaux")
    assert liste.status_code == 200 and secret not in liste.text
    cmc = liste.json()["clients"][0]
    assert cmc["client"] == "CMC" and cmc["secret_defini"] is True and len(cmc["machines"]) == 2 and {u["url"] for u in cmc["urls"]} == {"http://192.168.1.10:8750", "http://192.168.1.11:8750"}


def test_statut_de_l_appareil_donne_adresses_et_ticket_verifiable_hors_ligne(banc):
    c, etat, db = banc
    secret = c.post("/api/loois/serveur-local", json=INFOS, headers=H).json()["secret_passerelle"]
    d = c.post("/api/android/appareil/enregistrer", json={"android_id": "ANDROID-ID-123456", "modele": "Tab", "version_app": "1.0"}).json()
    entetes = {"Authorization": f"Bearer {d['jeton']}"}
    # appareil interdit : ni adresse ni ticket
    s = c.post("/api/android/appareil/statut", json={}, headers=entetes).json()
    assert s["autorise"] is False and s["serveurs_locaux"] == [] and s["ticket_local"] == ""
    c.put(f"/api/admin/android-appareils/{d['appareil_id']}", json={"etat": "autorise", "zone": "docx=CMC", "base": "myAurora-CMC", "client_code": "CMC", "nom_utilisateur": "Awa"})
    s = c.post("/api/android/appareil/statut", json={}, headers=entetes).json()
    assert s["autorise"] is True and s["serveurs_locaux"][0]["url"] == "http://192.168.1.10:8750" and s["serveurs_locaux"][0]["poste"] == "PC-CMC-1" and s["ticket_local_h"] == 72
    t = sl.lire_ticket(secret, s["ticket_local"])                                                                                # la passerelle, qui connaît le secret, le vérifie sans Internet
    assert t["aid"] == d["appareil_id"] and t["client"] == "CMC" and t["zone"] == "docx=CMC" and t["base"] == "myAurora-CMC"
    # nouveau secret : l'ancien ticket ne vaut plus rien
    assert c.post("/api/admin/serveurs-locaux/CMC/regenerer").status_code == 200
    assert sl.lire_ticket(secret, s["ticket_local"]) is not None                                                                  # (ancien secret connu du seul test)
    nouveau = run(sl.secret_client(db, "CMC"))
    assert nouveau != secret and sl.lire_ticket(nouveau, s["ticket_local"]) is None


def test_droits_et_regeneration_inconnue(banc):
    c, etat, _ = banc
    c.post("/api/loois/serveur-local", json=INFOS, headers=H)
    etat["user"] = {"id": "u2", "role": "client"}
    assert c.get("/api/admin/serveurs-locaux").status_code == 403 and c.post("/api/admin/serveurs-locaux/CMC/regenerer").status_code == 403
    etat["user"] = {"id": "u1", "role": "admin"}
    assert c.post("/api/admin/serveurs-locaux/INCONNU/regenerer").status_code == 404
