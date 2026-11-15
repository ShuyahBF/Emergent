"""Lot 403 — passerelle Agenda Google par utilisateur : analyse des notes vocales, liaison, isolation entre utilisateurs, création d'événements.
Google est SIMULÉ (httpx.MockTransport) : aucun appel réseau. Lancer : cd backend && python -m pytest tests/test_lot403_agenda_passerelle.py -q -n0
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from agenda_parseur import analyser  # noqa: E402
from routes import agenda_passerelle as ag  # noqa: E402

DIMANCHE = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- analyse du texte dicté
def test_note_vocale_de_l_exemple():
    r = analyser("samedi 8h15 rdv chez le dentiste", DIMANCHE)
    assert r["titre"] == "RDV chez le dentiste" and r["debut"].startswith("2026-11-21T08:15") and r["manque"] == []
    assert r["libelle"] == "samedi 21 novembre 2026 à 08:15" and r["duree_minutes"] == 60


@pytest.mark.parametrize("texte,attendu", [
    ("demain à 14h30 réunion avec Awa", "2026-11-16T14:30"),
    ("après-demain 9 h dentiste", "2026-11-17T09:00"),
    ("le 21 novembre à midi déjeuner", "2026-11-21T12:00"),
    ("lundi 8h et demie rdv médecin", "2026-11-16T08:30"),
    ("jeudi 5h du soir coiffeur", "2026-11-19T17:00"),
    ("1er décembre 7h30 vol", "2026-12-01T07:30"),
    ("dans 2 semaines 10h contrôle", "2026-11-29T10:00"),
    ("21/11 18h45 anniversaire", "2026-11-21T18:45"),
])
def test_dates_et_heures_en_francais(texte, attendu):
    assert analyser(texte, DIMANCHE)["debut"].startswith(attendu), texte


def test_on_ne_devine_pas_en_silence():
    assert analyser("rdv chez le dentiste", DIMANCHE)["manque"] == ["date", "heure"]
    assert analyser("samedi rdv dentiste", DIMANCHE)["manque"] == ["heure"]
    assert "titre" in analyser("samedi 8h", DIMANCHE)["manque"]
    r = analyser("lundi 8h rdv pendant 45 minutes", DIMANCHE)
    assert r["duree_minutes"] == 45 and r["fin"].startswith("2026-11-16T08:45")


# ---------------------------------------------------------------- passerelle (Google simulé)
class FauxGoogle:
    """Mémoire d'événements PAR jeton d'accès : un utilisateur ne voit que les siens, comme chez Google."""
    def __init__(self):
        self.evenements = {}        # jeton d'accès -> liste
        self.revoques = []
        self.appels = []

    def traiter(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.appels.append((req.method, url))
        if url.startswith(ag.URL_JETON):
            donnees = parse_qs(req.content.decode())
            if donnees.get("grant_type") == ["authorization_code"]:
                utilisateur = "A" if donnees["code"] == ["code-A"] else "B"
                return httpx.Response(200, json={"access_token": f"acces-{utilisateur}", "refresh_token": f"refresh-{utilisateur}", "expires_in": 3600})
            if donnees["refresh_token"][0] == "refresh-retire":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "acces-" + donnees["refresh_token"][0].split("-")[1], "expires_in": 3600})
        if url.startswith(ag.URL_INFOS):
            return httpx.Response(200, json={"email": "a@gmail.com" if "acces-A" in req.headers["authorization"] else "b@gmail.com"})
        if url.startswith(ag.URL_REVOCATION):
            self.revoques.append(parse_qs(req.content.decode())["token"][0])
            return httpx.Response(200, json={})
        jeton = req.headers["authorization"].split()[1]
        liste = self.evenements.setdefault(jeton, [])
        if req.method == "POST":
            e = {**json.loads(req.content), "id": f"ev{len(liste) + 1}", "htmlLink": "https://calendar.google.com/x"}
            liste.append(e)
            return httpx.Response(200, json=e)
        if req.method == "DELETE":
            ident = url.rsplit("/", 1)[1]
            liste[:] = [e for e in liste if e["id"] != ident]
            return httpx.Response(204)
        return httpx.Response(200, json={"items": liste})


def _signer(corps: dict, code="auror", cle="cle-auror"):
    brut = json.dumps(corps).encode()
    t = str(int(time.time()))
    return brut, {"X-Emetteur": code, "X-Timestamp": t, "X-Signature": hmac.new(cle.encode(), f"{t}.{brut.decode()}".encode(), hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


@pytest.fixture()
def banc(monkeypatch):
    boucle = asyncio.new_event_loop()
    asyncio.set_event_loop(boucle)
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot403"]
    boucle.run_until_complete(db.liluvine_emetteurs.insert_one({"code": "auror", "secret": "cle-auror", "actif": True}))
    boucle.run_until_complete(db.settings.insert_one({"_id": "global", "google_client_id": "id-client", "google_client_secret": "secret-client"}))
    boucle.run_until_complete(db.settings.insert_one({"_id": "transactions-sms:config", "sources": [{"id": "tel1", "cle_hash": ag.hacher_cle("cle-tel")}]}))
    faux = FauxGoogle()
    monkeypatch.setattr(ag, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(faux.traiter)))
    ag._JETONS.clear()
    app, api = FastAPI(), APIRouter(prefix="/api")
    ag.setup_agenda_passerelle_routes(db=db, api=api, get_current_user=lambda: {"role": "admin"}, public_base_url_fn=lambda r: "https://sawali.test")
    app.include_router(api)
    yield TestClient(app), db, faux, boucle
    boucle.close()


def _appeler(c, chemin, corps, **kw):
    brut, entetes = _signer(corps, **kw)
    return c.post(f"/api/webhook/agenda/{chemin}", content=brut, headers=entetes)


def _autoriser(c, utilisateur, gmail):
    """Demande d'accès de l'utilisateur, acceptée par l'administrateur."""
    assert _appeler(c, "demander", {"utilisateur": utilisateur, "gmail": gmail}).json()["etat"] == "attente"
    ident = next(d["id"] for d in c.get("/api/admin/agenda-passerelle/etat").json()["demandes"] if d["utilisateur"] == utilisateur)
    assert c.post(f"/api/admin/agenda-passerelle/demandes/{ident}", json={"decision": "accepte"}).json()["etat"] == "accepte"


def _lier(c, utilisateur, code, gmail=None):
    _autoriser(c, utilisateur, gmail or ("a@gmail.com" if code == "code-A" else "b@gmail.com"))
    url = _appeler(c, "lier", {"utilisateur": utilisateur}).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["id-client"] and q["redirect_uri"] == ["https://sawali.test/api/agenda/retour"] and "calendar.events" in q["scope"][0] and q["access_type"] == ["offline"]
    return c.get("/api/agenda/retour", params={"code": code, "state": q["state"][0]})


def test_liaison_puis_isolation_entre_utilisateurs(banc):
    c, db, faux, boucle = banc
    assert _appeler(c, "etat", {"utilisateur": "awa"}).json()["lie"] is False
    assert "Agenda lié" in _lier(c, "awa", "code-A").text and "Agenda lié" in _lier(c, "issa", "code-B").text
    etat = _appeler(c, "etat", {"utilisateur": "awa"}).json()
    assert etat["lie"] is True and etat["email"] == "a@gmail.com" and etat["demande"] == "accepte"
    # Le jeton Google est gardé CHIFFRÉ
    doc = boucle.run_until_complete(db.settings.find_one({"_id": ag.PREFIXE_LIAISON + ag.cle_liaison("auror", "awa")}))
    assert "refresh-A" not in json.dumps(doc) and ag.dechiffrer(doc["refresh_chiffre"]) == "refresh-A"
    # Awa crée un RDV : Issa ne le voit pas
    r = _appeler(c, "creer", {"utilisateur": "awa", "titre": "RDV chez le dentiste", "debut": "2026-11-21T08:15:00+00:00"})
    assert r.status_code == 200 and r.json()["evenement"]["titre"] == "RDV chez le dentiste"
    assert [e["titre"] for e in _appeler(c, "evenements", {"utilisateur": "awa"}).json()["evenements"]] == ["RDV chez le dentiste"]
    assert _appeler(c, "evenements", {"utilisateur": "issa"}).json()["evenements"] == []
    # Un utilisateur qui n'a jamais lié son agenda reçoit 409 (et jamais l'agenda d'un autre)
    assert _appeler(c, "evenements", {"utilisateur": "inconnu"}).status_code == 409
    # Suppression : seulement dans SON agenda
    assert _appeler(c, "supprimer", {"utilisateur": "awa", "id": "ev1"}).status_code == 200
    assert _appeler(c, "evenements", {"utilisateur": "awa"}).json()["evenements"] == []


def test_authentification_obligatoire_et_par_appareil(banc):
    c, db, faux, boucle = banc
    assert c.post("/api/webhook/agenda/etat", json={"utilisateur": "awa"}).status_code == 401                    # sans signature
    brut, entetes = _signer({"utilisateur": "awa"}, cle="mauvaise-cle")
    assert c.post("/api/webhook/agenda/etat", content=brut, headers=entetes).status_code == 401                  # mauvaise clé
    assert c.post("/api/webhook/agenda/etat", json={}, headers={"X-Source": "tel1", "X-Cle": "mauvaise"}).status_code == 401
    r = c.post("/api/webhook/agenda/etat", json={}, headers={"X-Source": "tel1", "X-Cle": "cle-tel"})            # Concentration : clé d'appareil
    assert r.status_code == 200 and r.json()["lie"] is False
    assert _appeler(c, "etat", {}).status_code == 422                                                              # plateforme sans « utilisateur »


def test_consentement_a_usage_unique_et_expire(banc):
    c, db, faux, boucle = banc
    _autoriser(c, "awa", "a@gmail.com")
    url = _appeler(c, "lier", {"utilisateur": "awa"}).json()["url"]
    etat = parse_qs(urlparse(url).query)["state"][0]
    assert c.get("/api/agenda/retour", params={"code": "code-A", "state": etat}).status_code == 200
    assert c.get("/api/agenda/retour", params={"code": "code-A", "state": etat}).status_code == 400              # déjà servi
    assert c.get("/api/agenda/retour", params={"code": "x", "state": "inventé"}).status_code == 400
    url = _appeler(c, "lier", {"utilisateur": "awa", "retour": "http://pirate.test"}).json()["url"]                  # retour non autorisé : ignoré
    etat = parse_qs(urlparse(url).query)["state"][0]
    assert boucle.run_until_complete(db.settings.find_one({"_id": ag.PREFIXE_ETAT + etat}))["retour"] == ""
    url = _appeler(c, "lier", {"utilisateur": "awa", "retour": "auror://agenda"}).json()["url"]
    etat = parse_qs(urlparse(url).query)["state"][0]
    r = c.get("/api/agenda/retour", params={"code": "code-A", "state": etat}, follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "auror://agenda?agenda=ok"


def test_delier_revoque_chez_google_et_acces_retire_detecte(banc):
    c, db, faux, boucle = banc
    _lier(c, "awa", "code-A")
    assert _appeler(c, "delier", {"utilisateur": "awa"}).json()["lie"] is False
    assert faux.revoques == ["refresh-A"] and _appeler(c, "etat", {"utilisateur": "awa"}).json()["lie"] is False
    # Accès retiré par l'utilisateur chez Google : la liaison est détectée comme invalide et supprimée
    boucle.run_until_complete(db.settings.insert_one({"_id": ag.PREFIXE_LIAISON + ag.cle_liaison("auror", "zoe"), "refresh_chiffre": ag.chiffrer("refresh-retire")}))
    assert _appeler(c, "evenements", {"utilisateur": "zoe"}).status_code == 409
    assert _appeler(c, "etat", {"utilisateur": "zoe"}).json()["lie"] is False


def test_analyse_creation_validations_et_vue_admin(banc):
    c, db, faux, boucle = banc
    r = _appeler(c, "analyser", {"utilisateur": "awa", "texte": "samedi 8h15 rdv chez le dentiste", "maintenant": "2026-11-15T10:00:00Z"}).json()
    assert r["debut"].startswith("2026-11-21T08:15") and r["titre"] == "RDV chez le dentiste" and faux.appels == []          # rien envoyé à Google
    _lier(c, "awa", "code-A")
    assert _appeler(c, "creer", {"utilisateur": "awa", "titre": "", "debut": "2026-11-21T08:15:00+00:00"}).status_code == 422
    assert _appeler(c, "creer", {"utilisateur": "awa", "titre": "X", "debut": "2026-11-21T08:15:00"}).status_code == 422       # fuseau obligatoire
    assert _appeler(c, "creer", {"utilisateur": "awa", "titre": "X", "debut": "2026-11-21T08:15:00+00:00", "fin": "2026-11-21T07:00:00+00:00"}).status_code == 422
    ok = _appeler(c, "creer", {"utilisateur": "awa", "titre": "Appel", "debut": "2026-11-21T08:15:00+00:00", "rappel_minutes": 30})
    assert ok.status_code == 200 and faux.evenements["acces-A"][0]["reminders"]["overrides"][0]["minutes"] == 30
    admin = c.get("/api/admin/agenda-passerelle/etat").json()
    assert admin["total"] == 1 and admin["liaisons_par_plateforme"] == {"auror": 1} and admin["adresse_retour"] == "https://sawali.test/api/agenda/retour"
    assert "Appel" not in json.dumps(admin) and "RDV" not in json.dumps(admin)                    # aucun contenu d'agenda


def test_approbation_demande_puis_acceptation_et_bon_compte(banc):
    """Responsabiliser : pas de « Lier » sans demande acceptée ; seul le compte Google indiqué est accepté au retour (l'autre est révoqué)."""
    c, db, faux, boucle = banc
    assert _appeler(c, "lier", {"utilisateur": "awa"}).status_code == 403                                   # aucune demande
    assert _appeler(c, "demander", {"utilisateur": "awa", "gmail": "pas-un-mail"}).status_code == 422
    assert _appeler(c, "demander", {"utilisateur": "awa", "gmail": "A@Gmail.com"}).json() == {"etat": "attente", "gmail": "a@gmail.com"}
    assert _appeler(c, "lier", {"utilisateur": "awa"}).status_code == 403                                   # en attente
    assert _appeler(c, "etat", {"utilisateur": "awa"}).json()["demande"] == "attente"
    ident = c.get("/api/admin/agenda-passerelle/etat").json()["demandes"][0]["id"]
    assert c.post(f"/api/admin/agenda-passerelle/demandes/{ident}", json={"decision": "refuse"}).status_code == 200
    assert _appeler(c, "lier", {"utilisateur": "awa"}).status_code == 403                                   # refusée
    assert c.post(f"/api/admin/agenda-passerelle/demandes/inconnue", json={"decision": "accepte"}).status_code == 404
    assert c.post(f"/api/admin/agenda-passerelle/demandes/{ident}", json={"decision": "peut-etre"}).status_code == 422
    c.post(f"/api/admin/agenda-passerelle/demandes/{ident}", json={"decision": "accepte"})
    url = _appeler(c, "lier", {"utilisateur": "awa"}).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["login_hint"] == ["a@gmail.com"]
    # Mauvais compte Google (code-B = b@gmail.com) : refusé, accès révoqué, rien de gardé
    r = c.get("/api/agenda/retour", params={"code": "code-B", "state": q["state"][0]})
    assert r.status_code == 400 and "Compte non autorisé" in r.text and faux.revoques == ["refresh-B"]
    assert _appeler(c, "etat", {"utilisateur": "awa"}).json()["lie"] is False
    # Bon compte : lié
    q = parse_qs(urlparse(_appeler(c, "lier", {"utilisateur": "awa"}).json()["url"]).query)
    assert c.get("/api/agenda/retour", params={"code": "code-A", "state": q["state"][0]}).status_code == 200
    assert _appeler(c, "etat", {"utilisateur": "awa"}).json()["lie"] is True


def test_approbation_desactivable_par_l_administrateur(banc):
    c, db, faux, boucle = banc
    assert c.put("/api/admin/agenda-passerelle/approbation", json={"actif": False}).json() == {"approbation": False}
    url = _appeler(c, "lier", {"utilisateur": "awa"}).json()["url"]                                          # sans demande : permis
    q = parse_qs(urlparse(url).query)
    assert "login_hint" not in q and c.get("/api/agenda/retour", params={"code": "code-B", "state": q["state"][0]}).status_code == 200
    assert c.get("/api/admin/agenda-passerelle/etat").json()["approbation"] is False
