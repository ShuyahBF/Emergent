"""Lot 57.5 — Transmission WA Universelle Liluvine, protocole v3 : médias et documents,
retours vers la plateforme (réponses, statuts), STOP / REPRENDRE, alertes e-mail."""
import asyncio
import base64
import hashlib
import hmac
import json
import time

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import routes.liluvine_relais as relais
from routes.liluvine_emetteurs import make_liluvine_emetteurs_router
from routes.liluvine_send_webhook import attach_liluvine_send_webhook_routes

PDF = b"%PDF-1.4 essai"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _app(direct_ok=True, modele_media=""):
    """Application de test complète : webhook, fichiers, admin ; faux envois WhatsApp."""
    db = mongomock_motor.AsyncMongoMockClient()["test_lot57_5"]
    envois = []

    async def faux_texte(numero, texte, *a, **k):
        envois.append(("texte", numero, texte))
        return {"ok": True, "message_id": f"wamid.{len(envois)}"}

    async def faux_modele(numero, nom, langue, composants):
        envois.append(("modele", numero, nom, composants))
        return {"ok": True, "message_id": f"wamid.{len(envois)}"}

    async def faux_media(numero, type_media, *, public_url, caption=None, filename=None):
        envois.append(("media", numero, type_media, public_url, filename))
        return {"ok": direct_ok, "message_id": f"wamid.{len(envois)}" if direct_ok else None,
                "error": None if direct_ok else "(#131047) Re-engagement message"}

    async def admin():
        return {"email": "admin@sawali.test"}

    api = APIRouter(prefix="/api")
    attach_liluvine_send_webhook_routes(api=api, db=db, wa_send_text=faux_texte, wa_send_template=faux_modele,
                                        wa_send_media=faux_media)
    relais.attach_liluvine_fichiers_route(api=api, db=db)
    api.include_router(make_liluvine_emetteurs_router(db=db, get_current_admin=admin))
    app = FastAPI()
    app.include_router(api)
    _run(db.settings.insert_one({"_id": "global", "public_base_url": "https://sawali.test",
                                 "liluvine_transmission_modele_media": modele_media,
                                 "liluvine_transmission_email_alerte": "alerte@test.bf"}))
    client = TestClient(app)
    cle = client.post("/api/admin/liluvine-emetteurs", json={
        "code": "ster", "nom": "Ster", "url_retour": "https://ster.test/api/webhooks/liluvine-retour"}).json()["cle"]
    return client, db, envois, cle


def _envoyer(client, cle, corps, emetteur="ster"):
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return client.post("/api/webhook/liluvine-send", content=brut, headers={
        "Content-Type": "application/json", "X-Emetteur": emetteur, "X-Timestamp": ts, "X-Signature": sig})


def _media():
    return {"type": "document", "contenu_base64": base64.b64encode(PDF).decode(), "nom_fichier": "facture.pdf",
            "mime": "application/pdf"}


def test_document_direct_et_lien_public():
    client, db, envois, cle = _app(direct_ok=True)
    r = _envoyer(client, cle, {"id": "d1", "to": "+22670000001", "message": "Votre facture", "media": _media()})
    assert r.status_code == 200, r.text
    assert r.json()["media_mode"] == "direct"
    lien = envois[-1][3]
    assert lien.startswith("https://sawali.test/api/liluvine/fichier/") and envois[-1][4] == "facture.pdf"
    # Le lien public sert bien le fichier
    fichier = client.get(lien.replace("https://sawali.test", ""))
    assert fichier.status_code == 200 and fichier.content == PDF


def test_document_hors_fenetre_modele_media_puis_lien():
    # Média direct refusé (hors 24 h) + modèle média configuré -> modèle avec en-tête document
    client, db, envois, cle = _app(direct_ok=False, modele_media="transmission_document")
    r = _envoyer(client, cle, {"id": "d2", "to": "+22670000002", "message": "Compte rendu", "media": _media()})
    assert r.json()["media_mode"] == "modele"
    entete = envois[-1][3][0]
    assert envois[-1][2] == "transmission_document" and entete["type"] == "header"
    # Sans modèle média -> texte avec lien de téléchargement
    client2, _, envois2, cle2 = _app(direct_ok=False)
    r = _envoyer(client2, cle2, {"id": "d3", "to": "+22670000003", "message": "Compte rendu", "media": _media()})
    assert r.json()["media_mode"] == "lien" and "📎 facture.pdf : https://sawali.test/api/liluvine/fichier/" in envois2[-1][2]


def test_media_refuses():
    client, _, _, cle = _app()
    url_http = {"type": "document", "url": "http://exemple.bf/a.pdf"}
    assert _envoyer(client, cle, {"id": "x1", "to": "+22670000004", "message": "m", "media": url_http}).status_code == 422
    interne = {"type": "image", "url": "https://127.0.0.1/a.png"}
    assert _envoyer(client, cle, {"id": "x2", "to": "+22670000004", "message": "m", "media": interne}).status_code == 422
    gros = {"type": "document", "contenu_base64": base64.b64encode(b"0" * (10 * 1024 * 1024 + 1)).decode()}
    assert _envoyer(client, cle, {"id": "x3", "to": "+22670000004", "message": "m", "media": gros}).status_code == 422


def test_reponse_relayee_stop_reprendre_et_statut(monkeypatch):
    client, db, envois, cle = _app()
    retours = []

    async def faux_retour(db_, emetteur, corps):
        retours.append(corps)
        return True
    monkeypatch.setattr(relais, "_poster_retour", faux_retour)
    r = _envoyer(client, cle, {"id": "m1", "to": "+22670000005", "message": "RDV demain"})
    mid = r.json()["message_id"]

    async def scenario():
        # Statut « lu » renvoyé à la plateforme avec l'id d'origine
        await relais.mettre_a_jour_statut(db, mid, "read")
        await asyncio.sleep(0)
        # Lot 83 : message libre (sans « Répondre ») -> reste à SAWALI, rien n'est relayé
        libre = await relais.traiter_message_entrant(db, de="22670000005", type_message="text", texte="Autre sujet",
                                                     send_text=None)
        assert libre == {"traite": False}
        # Réponse citée du client -> relayée (Liluvine ne répond pas)
        rep = await relais.traiter_message_entrant(db, de="22670000005", type_message="text", texte="Je confirme",
                                                   cite_message_id=mid, send_text=None)
        await asyncio.sleep(0)
        # STOP -> désinscription + confirmation au client
        confirmations = []

        async def envoi(numero, texte):
            confirmations.append(texte)
        stop = await relais.traiter_message_entrant(db, de="22670000005", type_message="text", texte="STOP",
                                                    send_text=envoi)
        await asyncio.sleep(0)
        return rep, stop, confirmations
    rep, stop, confirmations = _run(scenario())
    assert rep["action"] == "reponse_relayee" and stop["action"] == "desinscription"
    types = [c["type"] for c in retours]
    assert types == ["statut", "reponse", "desinscription"]
    assert retours[0]["id"] == "m1" and retours[0]["statut"] == "read" and retours[1]["id_origine"] == "m1"
    assert "REPRENDRE" in confirmations[0]
    # Envoi refusé après STOP (409), puis REPRENDRE -> de nouveau possible
    assert _envoyer(client, cle, {"id": "m2", "to": "+22670000005", "message": "x"}).status_code == 409
    _run(relais.traiter_message_entrant(db, de="22670000005", type_message="text", texte="Reprendre", send_text=None))
    assert _envoyer(client, cle, {"id": "m3", "to": "+22670000005", "message": "x"}).status_code == 200


def test_alerte_email_apres_serie_de_signatures_refusees(monkeypatch):
    client, db, _, cle = _app()
    mails = []

    async def faux_mail(dest, sujet, html, texte=""):
        mails.append((dest, sujet))
        return True
    import email_service
    monkeypatch.setattr(email_service, "send_email", faux_mail)
    for i in range(6):
        assert _envoyer(client, "mauvaise-cle", {"id": f"s{i}", "to": "+22670000006", "message": "x"}).status_code == 401
    assert len(mails) == 1 and mails[0][0] == "alerte@test.bf" and "ster" in mails[0][1]
