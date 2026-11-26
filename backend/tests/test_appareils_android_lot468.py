"""Lot 468 — registre des appareils Android de « Loois mobile » : enregistrement (état interdit, jeton unique), statut (IP vue par le serveur), droits de l'administrateur,
réinitialisation du jeton, limites. Aucun accès réseau (Mongo simulé)."""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "sawali_test_lot468")

import mongomock_motor
import pytest

import appareils_android as aa


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------------------------------------------------------------------ fonctions pures
def test_nouvelle_fiche_interdite_et_jeton_non_stocke_en_clair():
    fiche, jeton = aa.nouvelle_fiche("ANDROID-ID-123456", "Samsung A54", "1.0", "41.138.1.2")
    assert fiche["etat"] == "interdit" and jeton not in str(fiche) and "ANDROID-ID-123456" not in str(fiche)      # ni jeton ni identifiant Android en clair
    assert aa.jetons_egaux(jeton, fiche["jeton_hash"]) and not aa.jetons_egaux("faux", fiche["jeton_hash"]) and not aa.jetons_egaux("", "")
    v = aa.vue_admin(fiche)
    assert "jeton_hash" not in v and "android_id_hash" not in v and v["jeton_actif"] is True and v["nouveau"] is True


def test_validation_des_modifications():
    ok, err = aa.valider_modifications({"etat": "autorise", "zone": "doc=PMT", "base": "myAizenta-PMT", "client_code": "pmt", "nom_utilisateur": "  BADINI Awa  "})
    assert err == "" and ok == {"etat": "autorise", "zone": "doc=PMT", "base": "myAizenta-PMT", "client_code": "PMT", "nom_utilisateur": "BADINI Awa"}
    for mauvais in ({"etat": "peut-etre"}, {"zone": "docx=CMC; DROP"}, {"base": "base avec espace"}, {"client_code": "a b"}):
        assert aa.valider_modifications(mauvais)[1] != ""
    assert aa.valider_modifications({"zone": ""})[0] == {"zone": ""}                                         # vide = efface
    assert aa.valider_modifications({"jeton_hash": "x", "id": "y"})[0] == {}                                   # champs non modifiables ignorés


def test_statut_refuse_ne_donne_ni_zone_ni_base():
    r = aa.reponse_statut({"etat": "interdit", "zone": "docx=CMC", "base": "myAurora-CMC", "client_code": "CMC"})
    assert r["autorise"] is False and r["zone"] == "" and r["base"] == "" and "interdit" in r["message"].lower()
    r = aa.reponse_statut({"etat": "autorise", "zone": "docx=CMC", "base": "myAurora-CMC", "client_code": "CMC", "nom_utilisateur": "Awa"})
    assert r["autorise"] is True and r["zone"] == "docx=CMC" and r["base"] == "myAurora-CMC"
    assert aa.base_de_la_zone("doc=PMT") == "myAizenta-PMT" and aa.base_de_la_zone("inconnue") == ""


# ------------------------------------------------------------------------------------------------------------------ routes
@pytest.fixture()
def client_http():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import routes.appareils_android as ra
    ra._limites.clear()
    db = mongomock_motor.AsyncMongoMockClient()["test_lot468"]
    etat = {"user": {"id": "u1", "role": "admin", "email": "a@x.bf"}}
    app = FastAPI()
    api = APIRouter(prefix="/api")

    async def utilisateur():
        return etat["user"]
    ra.setup_appareils_android_routes(db=db, api=api, get_current_user=utilisateur)
    app.include_router(api)
    return TestClient(app), etat, db, ra


def test_cycle_complet_enregistrement_autorisation_statut(client_http):
    c, etat, db, _ = client_http
    r = c.post("/api/android/appareil/enregistrer", json={"android_id": "ANDROID-ID-123456", "modele": "Tab S9", "version_app": "1.0"}, headers={"X-Forwarded-For": "41.138.1.2"})
    assert r.status_code == 200
    d = r.json()
    assert d["autorise"] is False and d["etat"] == "interdit" and len(d["jeton"]) > 30
    jeton, aid = d["jeton"], d["appareil_id"]
    # statut avant autorisation : refus poli, mais l'IP est notée
    s = c.post("/api/android/appareil/statut", json={"version_app": "1.1"}, headers={"Authorization": f"Bearer {jeton}", "X-Forwarded-For": "41.138.9.9"})
    assert s.status_code == 200 and s.json()["autorise"] is False and s.json()["zone"] == ""
    # l'administrateur voit l'appareil (sans jeton), son IP vue par le serveur, et l'autorise
    liste = c.get("/api/admin/android-appareils").json()
    assert len(liste["appareils"]) == 1 and liste["appareils"][0]["ip_derniere"] == "41.138.9.9" and liste["appareils"][0]["version_app"] == "1.1"
    assert jeton not in str(liste["appareils"][0]) and "jeton_hash" not in liste["appareils"][0] and any(z["cle"] == "doc=PMT" for z in liste["zones"])
    m = c.put(f"/api/admin/android-appareils/{aid}", json={"etat": "autorise", "zone": "doc=PMT", "base": "myAizenta-PMT", "client_code": "PMT", "nom_utilisateur": "BADINI Awa"})
    assert m.status_code == 200 and m.json()["etat"] == "autorise"
    s = c.post("/api/android/appareil/statut", json={}, headers={"Authorization": f"Bearer {jeton}"}).json()
    assert s["autorise"] is True and s["zone"] == "doc=PMT" and s["base"] == "myAizenta-PMT" and s["nom_utilisateur"] == "BADINI Awa"
    # un blocage prend effet tout de suite
    c.put(f"/api/admin/android-appareils/{aid}", json={"etat": "interdit"})
    assert c.post("/api/android/appareil/statut", json={}, headers={"Authorization": f"Bearer {jeton}"}).json()["autorise"] is False
    assert len(c.get("/api/admin/android-appareils").json()["appareils"][0]["journal"]) >= 3                  # journal des connexions


def test_jamais_de_second_jeton_sans_reinitialisation(client_http):
    c, _, _, _ = client_http
    corps = {"android_id": "ANDROID-ID-123456", "modele": "Tab", "version_app": "1.0"}
    d = c.post("/api/android/appareil/enregistrer", json=corps).json()
    assert c.post("/api/android/appareil/enregistrer", json=corps).status_code == 409                          # usurpation impossible
    assert c.post(f"/api/admin/android-appareils/{d['appareil_id']}/reinitialiser").status_code == 200
    assert c.post("/api/android/appareil/statut", json={}, headers={"Authorization": f"Bearer {d['jeton']}"}).status_code == 401   # ancien jeton mort
    d2 = c.post("/api/android/appareil/enregistrer", json=corps).json()
    assert d2["appareil_id"] == d["appareil_id"] and d2["jeton"] != d["jeton"]                                  # même fiche, nouveau jeton
    assert len(c.get("/api/admin/android-appareils").json()["appareils"]) == 1


def test_jeton_faux_ou_absent_refuse_et_limite(client_http):
    c, _, _, ra = client_http
    assert c.post("/api/android/appareil/statut", json={}).status_code == 401
    assert c.post("/api/android/appareil/statut", json={}, headers={"Authorization": "Bearer faux"}).status_code == 401
    for _ in range(25):
        c.post("/api/android/appareil/statut", json={}, headers={"Authorization": "Bearer faux"})
    assert c.post("/api/android/appareil/statut", json={}, headers={"Authorization": "Bearer faux"}).status_code == 429      # trop de jetons faux
    ra._limites.clear()
    for i in range(10):
        assert c.post("/api/android/appareil/enregistrer", json={"android_id": f"ANDROID-ID-{i:06d}"}).status_code == 200
    assert c.post("/api/android/appareil/enregistrer", json={"android_id": "ANDROID-ID-999999"}).status_code == 429       # 10 enregistrements par heure et par IP


def test_droits_administrateur_et_suppression(client_http):
    c, etat, _, _ = client_http
    d = c.post("/api/android/appareil/enregistrer", json={"android_id": "ANDROID-ID-123456"}).json()
    etat["user"] = {"id": "u2", "role": "client", "email": "c@x.bf"}
    assert c.get("/api/admin/android-appareils").status_code == 403
    assert c.put(f"/api/admin/android-appareils/{d['appareil_id']}", json={"etat": "autorise"}).status_code == 403
    assert c.delete(f"/api/admin/android-appareils/{d['appareil_id']}").status_code == 403
    etat["user"] = {"id": "u1", "role": "admin", "email": "a@x.bf"}
    assert c.put(f"/api/admin/android-appareils/{d['appareil_id']}", json={"zone": "docx=CMC; DROP"}).status_code == 422
    assert c.put("/api/admin/android-appareils/inconnu", json={"etat": "autorise"}).status_code == 404
    assert c.delete(f"/api/admin/android-appareils/{d['appareil_id']}").status_code == 200
    assert c.get("/api/admin/android-appareils").json()["appareils"] == []
    assert c.post("/api/android/appareil/statut", json={}, headers={"Authorization": f"Bearer {d['jeton']}"}).status_code == 401   # appareil supprimé : jeton mort
