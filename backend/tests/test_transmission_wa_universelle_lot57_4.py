"""Lot 57.4 — Transmission WA Universelle Liluvine, protocole v2 : clé propre à
chaque plateforme (X-Emetteur), idempotence (« id »), quotas, modèle à 3 variables,
et routes d'administration des émetteurs (clé renvoyée une seule fois)."""
import asyncio
import hashlib
import hmac
import json
import time

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from routes.liluvine_emetteurs import make_liluvine_emetteurs_router
from routes.liluvine_send_webhook import attach_liluvine_send_webhook_routes


def _boucle():
    return asyncio.get_event_loop()


def _app(modele=""):
    """Application de test : webhook + routes admin, base simulée, faux envois WhatsApp."""
    db = mongomock_motor.AsyncMongoMockClient()["test_lot57_4"]
    envois = []

    async def faux_texte(numero, texte):
        envois.append(("texte", numero, texte))
        return {"ok": True, "message_id": f"wamid.{len(envois)}"}

    async def faux_modele(numero, nom, langue, composants):
        envois.append(("modele", numero, nom, langue, composants))
        return {"ok": True, "message_id": f"wamid.{len(envois)}"}

    async def admin():
        return {"email": "admin@sawali.test"}

    api = APIRouter(prefix="/api")
    attach_liluvine_send_webhook_routes(api=api, db=db, wa_send_text=faux_texte, wa_send_template=faux_modele)
    api.include_router(make_liluvine_emetteurs_router(db=db, get_current_admin=admin))
    app = FastAPI()
    app.include_router(api)
    _boucle().run_until_complete(db.settings.insert_one({"_id": "global", "liluvine_transmission_modele": modele}))
    return TestClient(app), db, envois


def _envoyer(client, emetteur, cle, corps):
    """Requête signée comme le fait une plateforme émettrice."""
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return client.post("/api/webhook/liluvine-send", content=brut, headers={
        "Content-Type": "application/json", "X-Emetteur": emetteur, "X-Timestamp": ts, "X-Signature": sig})


def test_cle_par_plateforme_et_administration():
    client, db, envois = _app()
    r = client.post("/api/admin/liluvine-emetteurs", json={"code": "ster", "nom": "Ster", "quota_jour": 10})
    cle = r.json()["cle"]
    assert len(cle) >= 60
    # La liste ne renvoie jamais la clé
    liste = client.get("/api/admin/liluvine-emetteurs").json()["emetteurs"]
    assert liste[0]["code"] == "ster" and "secret" not in liste[0] and cle not in json.dumps(liste)
    # Envoi signé avec la bonne clé -> texte libre préfixé par le nom de l'émetteur
    r = _envoyer(client, "ster", cle, {"id": "a1", "to": "+22670000001", "message": "Bonjour"})
    assert r.status_code == 200, r.text
    assert envois[-1][0] == "texte" and envois[-1][2].startswith("📨 Ster — ")
    # Mauvaise clé, émetteur inconnu, émetteur désactivé
    assert _envoyer(client, "ster", "fausse", {"id": "a2", "to": "+22670000001", "message": "x"}).status_code == 401
    assert _envoyer(client, "inconnu", cle, {"id": "a3", "to": "+22670000001", "message": "x"}).status_code == 401
    client.patch("/api/admin/liluvine-emetteurs/ster", json={"actif": False})
    assert _envoyer(client, "ster", cle, {"id": "a4", "to": "+22670000001", "message": "x"}).status_code == 401
    client.patch("/api/admin/liluvine-emetteurs/ster", json={"actif": True})
    # Régénération : l'ancienne clé ne marche plus
    nouvelle = client.post("/api/admin/liluvine-emetteurs/ster/regenerer").json()["cle"]
    assert _envoyer(client, "ster", cle, {"id": "a5", "to": "+22670000001", "message": "x"}).status_code == 401
    assert _envoyer(client, "ster", nouvelle, {"id": "a6", "to": "+22670000001", "message": "x"}).status_code == 200


def test_idempotence_et_quotas():
    client, db, envois = _app()
    cle = client.post("/api/admin/liluvine-emetteurs", json={"code": "adlyn", "nom": "adLyn", "quota_jour": 3}).json()["cle"]
    r1 = _envoyer(client, "adlyn", cle, {"id": "m1", "to": "+22670000002", "message": "Un"})
    r2 = _envoyer(client, "adlyn", cle, {"id": "m1", "to": "+22670000002", "message": "Un"})
    assert r1.status_code == r2.status_code == 200
    assert r2.json()["doublon"] is True and len(envois) == 1          # pas de second envoi
    _envoyer(client, "adlyn", cle, {"id": "m2", "to": "+22670000003", "message": "Deux"})
    _envoyer(client, "adlyn", cle, {"id": "m3", "to": "+22670000004", "message": "Trois"})
    assert _envoyer(client, "adlyn", cle, {"id": "m4", "to": "+22670000005", "message": "Quatre"}).status_code == 429
    # Journal sans le texte des messages
    lignes = client.get("/api/admin/liluvine-transmissions").json()["transmissions"]
    assert len(lignes) == 3 and "Trois" not in json.dumps(lignes)


def test_modele_trois_variables():
    client, db, envois = _app(modele="transmission_universelle")
    cle = client.post("/api/admin/liluvine-emetteurs", json={"code": "albarka", "nom": "Cabinet ALBARKA"}).json()["cle"]
    r = _envoyer(client, "albarka", cle, {"id": "t1", "to": "+22670000006", "message": "Votre rendez-vous"})
    assert r.status_code == 200 and r.json()["mode"] == "modele"
    _, numero, nom, langue, composants = envois[-1]
    valeurs = [p["text"] for p in composants[0]["parameters"]]
    assert nom == "transmission_universelle" and langue == "fr"
    assert valeurs[1] == "Cabinet ALBARKA" and valeurs[2] == "Votre rendez-vous" and "/" in valeurs[0]
    # Message trop long pour le modèle -> 422
    assert _envoyer(client, "albarka", cle, {"id": "t2", "to": "+22670000006", "message": "x" * 901}).status_code == 422
    # « to » obligatoire en mode émetteur
    assert _envoyer(client, "albarka", cle, {"id": "t3", "message": "x"}).status_code == 422
