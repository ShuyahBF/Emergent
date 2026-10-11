"""Lot 109 — alerte WhatsApp au propriétaire à chaque connexion / visite sur une plateforme.
Signature obligatoire, robots ignorés, anti-répétition, plafond, message interactif (fenêtre de 24 h) ou modèle Meta,
redirection « Visiter le site ». MongoDB simulé, API Meta simulée.
Lancer : cd backend && python -m pytest tests/test_lot109_alertes_connexions.py -q
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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.alertes_connexions as ac  # noqa: E402
import routes.appel_proprietaire as ap  # noqa: E402


def signe(cle: str, corps: dict, code: str = "zandgo") -> tuple:
    """Corps brut + en-têtes signés comme le fait la plateforme."""
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return brut.encode(), {"Content-Type": "application/json", "X-Emetteur": code, "X-Timestamp": ts, "X-Signature": sig}


@pytest.fixture
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["sawali_cnx"]
    envoyes = []

    async def faux_graph(s, numero_id, chemin, corps):   # API Meta simulée
        envoyes.append(corps)
        return {"ok": True, "donnees": {"messages": [{"id": "wamid.1"}]}, "erreur": None}

    fenetre = {"ouverte": False}

    async def fausse_fenetre(db_, proprio, numero_id, maintenant):
        return fenetre["ouverte"]

    monkeypatch.setattr(ap, "_graph_post", faux_graph)
    monkeypatch.setattr(ap, "fenetre_24h_ouverte", fausse_fenetre)
    monkeypatch.setattr(ap, "ligne_appelante", lambda s, cfg: ("PNID", "principal"))

    async def utilisateur():
        return {"id": "a1", "role": "admin", "name": "Admin"}

    api = APIRouter(prefix="/api")
    ac.setup_alertes_connexions_routes(api=api, db=db, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app).__enter__()
    client.portal.call(db.liluvine_emetteurs.insert_many, [
        {"code": "zandgo", "nom": "ZandGo", "secret": "cle-zg", "actif": True},
        {"code": "adlyn", "nom": "adLyn", "secret": "cle-ad", "actif": True, "url_site": "https://adlynservice.com"}])
    client.portal.call(lambda: db.settings.update_one({"_id": "global"}, {"$set": {
        "appel_proprio_numeros": "22670000009", "wa_access_token": "x"}}, upsert=True))
    yield client, db, envoyes, fenetre
    client.__exit__(None, None, None)


def attendre(client, db, n_attendus: int, envoyes: list):
    """Laisse la tâche d'envoi en arrière-plan se terminer."""
    for _ in range(50):
        if len(envoyes) >= n_attendus:
            break
        client.portal.call(asyncio.sleep, 0.02)


CONNEXION = {"type": "connexion", "ip": "154.66.1.2", "utilisateur": "Awa Ouédraogo", "telephone": "22670123456",
             "role": "client", "url_site": "https://zandgo.shop", "page": "/compte",
             "agent": "Mozilla/5.0 (Linux; Android 14) Chrome/129"}


def test_fonctions_pures():
    assert ac.telephone_lisible("22670123456") == "+226 70 12 34 56"
    assert ac.qui({"utilisateur": "Awa", "telephone": "22670123456", "role": "client"}) == "Awa (+226 70 12 34 56)"
    assert ac.qui({}) == "Visiteur non connecté"
    assert ac.est_robot("Googlebot/2.1") and ac.est_robot("facebookexternalhit/1.1") and not ac.est_robot("Mozilla/5.0 Chrome")
    assert ac.url_valide("javascript:alert(1)") is None and ac.url_valide("https://zandgo.shop/") == "https://zandgo.shop"
    quand = datetime(2026, 10, 11, 1, 35, tzinfo=timezone.utc)
    texte = ac.texte_alerte("ZandGo", CONNEXION, quand)
    assert "ZandGo" in texte and "11/10/2026 01:35" in texte and "154.66.1.2" in texte and "Awa" in texte
    d = ac.definition_modele()
    assert d["name"] == ac.MODELE and d["components"][2]["buttons"][0]["text"] == "Visiter le site"


def test_signature_obligatoire(env):
    client, *_ = env
    brut, entetes = signe("mauvaise", CONNEXION)
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).status_code == 401


def test_connexion_modele_puis_repetition(env):
    client, db, envoyes, fenetre = env
    brut, entetes = signe("cle-zg", CONNEXION)
    r = client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()
    assert r == {"ok": True, "alerte": True, "raison": None}
    attendre(client, db, 1, envoyes)
    # Fenêtre fermée : modèle Meta, 4 variables + suffixe du bouton = code de la plateforme
    m = envoyes[0]
    assert m["type"] == "template" and m["to"] == "22670000009" and m["template"]["name"] == ac.MODELE
    assert m["template"]["components"][1]["parameters"][0]["text"] == "zandgo"
    # L'adresse du site est mémorisée et sert au bouton « Visiter le site »
    em = client.portal.call(db.liluvine_emetteurs.find_one, {"code": "zandgo"})
    assert em["url_site"] == "https://zandgo.shop"
    rd = client.get("/api/visiter/zandgo", follow_redirects=False)
    assert rd.status_code == 302 and rd.headers["location"] == "https://zandgo.shop"
    # Même personne dans les 30 minutes : pas de deuxième alerte
    brut, entetes = signe("cle-zg", CONNEXION)
    r2 = client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()
    assert r2["alerte"] is False and "déjà signalé" in r2["raison"]


def test_fenetre_ouverte_message_interactif(env):
    client, db, envoyes, fenetre = env
    fenetre["ouverte"] = True
    brut, entetes = signe("cle-ad", {"type": "visite", "ip": "41.2.3.4", "visiteur": "v-1", "page": "/",
                                     "agent": "Mozilla/5.0 Safari"}, code="adlyn")
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["alerte"] is True
    attendre(client, db, 1, envoyes)
    m = envoyes[0]
    assert m["type"] == "interactive" and m["interactive"]["type"] == "cta_url"
    assert m["interactive"]["action"]["parameters"] == {"display_text": "Visiter le site", "url": "https://adlynservice.com"}
    assert "Visiteur non connecté" in m["interactive"]["body"]["text"]


def test_robots_reglages_et_plafond(env):
    client, db, envoyes, _ = env
    # Robot : ignoré
    brut, entetes = signe("cle-zg", {**CONNEXION, "agent": "Googlebot/2.1"})
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["raison"] == "robot"
    # Visites anonymes désactivées
    client.put("/api/admin/alertes-connexions/reglages", json={"alerte_cnx_visites": False, "alerte_cnx_plafond_jour": 1})
    brut, entetes = signe("cle-zg", {"type": "visite", "ip": "1.1.1.1", "agent": "Mozilla"})
    assert "visite" in client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["raison"]
    # Plafond de 1 par jour : la 1re connexion part, la 2e (autre personne) est bloquée
    brut, entetes = signe("cle-zg", CONNEXION)
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["alerte"] is True
    brut, entetes = signe("cle-zg", {**CONNEXION, "telephone": "22676000000", "utilisateur": "Ali"})
    assert "plafond" in client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["raison"]
    # Rubrique : journal et compteurs
    d = client.get("/api/admin/alertes-connexions").json()
    assert d["reglages"]["visites"] is False and d["destinataires"] == ["+226 70 00 00 09"]
    assert len(d["dernieres"]) == 4 and d["compteurs_24h"]["zandgo"]["recues"] == 4


def test_redirection_site_inconnu(env):
    client, *_ = env
    assert client.get("/api/visiter/inconnu", follow_redirects=False).status_code == 404


def test_modele_ne_commence_ni_ne_finit_par_une_variable():
    """Lot 109.1 — règle Meta : « Les variables ne peuvent pas se trouver au début ou à la fin du modèle »."""
    corps = ac.definition_modele()["components"][0]["text"].strip()
    assert not corps.startswith("{{") and not corps.endswith("}}")


def test_exclusions_sans_ip(env):
    """Lot 109.3 — l'IP change (mobile, Wi-Fi) : exclusion par compte (numéro), par mes numéros, par appareil."""
    client, db, envoyes, _ = env
    # Mes propres numéros (destinataires des alertes) sont exclus d'office
    brut, entetes = signe("cle-zg", {**CONNEXION, "telephone": "22670000009", "utilisateur": "Moi"})
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["raison"] == "compte exclu"
    # Visite anonyme d'un appareil, puis « Ne plus m'alerter » sur cette ligne → appareil exclu, quelle que soit l'IP
    visite = {"type": "visite", "ip": "41.1.1.1", "visiteur": "v-moi", "agent": "Mozilla/5.0 Chrome"}
    brut, entetes = signe("cle-zg", visite)
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["alerte"] is True
    ligne = client.portal.call(db.alertes_connexions.find_one, {"visiteur": "v-moi"})
    r = client.post("/api/admin/alertes-connexions/ignorer", json={"id": ligne["id"]}).json()
    assert r["exclu"] == "appareil"
    brut, entetes = signe("cle-zg", {**visite, "ip": "102.9.9.9"})   # autre IP, même appareil
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["raison"] == "appareil exclu"
    # Sur une autre plateforme, le même identifiant n'est pas exclu (identifiant propre à chaque site)
    brut, entetes = signe("cle-ad", visite, code="adlyn")
    assert client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes).json()["alerte"] is True
    # Connexion d'un compte → « Ne plus m'alerter » exclut son numéro
    brut, entetes = signe("cle-zg", CONNEXION)
    client.post("/api/webhook/plateforme-connexion", content=brut, headers=entetes)
    ligne = client.portal.call(db.alertes_connexions.find_one, {"telephone": "22670123456"})
    assert client.post("/api/admin/alertes-connexions/ignorer", json={"id": ligne["id"]}).json()["exclu"] == "compte"
    assert ac.compte_exclu({"telephone": "+226 70 12 34 56"}, ["22670123456"])
    # Retrait d'un appareil exclu
    d = client.delete("/api/admin/alertes-connexions/appareils/v-moi").json()
    assert d["appareils_exclus"] == []
