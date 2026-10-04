"""Lot 57.3 — « Transmission WA Universelle Liluvine » : le destinataire est
transmis dans le corps signé (« to »), repli sur le numéro par défaut, journal."""
import hashlib
import hmac
import json
import time

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from routes.liluvine_send_webhook import attach_liluvine_send_webhook_routes, normaliser_numero

SECRET = "cle-de-test"


def _client(defaut=""):
    """Petite application avec la route seule, une base simulée et un faux envoi WhatsApp."""
    db = mongomock_motor.AsyncMongoMockClient()["test_lot57_3"]
    envois = []

    async def faux_envoi(numero, texte):
        envois.append((numero, texte))
        return {"ok": True, "message_id": "wamid.1"}

    api = APIRouter(prefix="/api")
    attach_liluvine_send_webhook_routes(api=api, db=db, wa_send_text=faux_envoi)
    app = FastAPI()
    app.include_router(api)
    client = TestClient(app)
    import asyncio
    asyncio.get_event_loop().run_until_complete(db.settings.insert_one({
        "_id": "global", "liluvine_send_webhook_hmac_secret": SECRET,
        "liluvine_send_webhook_target_number": defaut}))
    return client, db, envois


def _post(client, corps, secret=SECRET):
    """Envoi signé comme le ferait une plateforme émettrice."""
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return client.post("/api/webhook/liluvine-send", content=brut,
                       headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": sig})


def test_normaliser_numero():
    assert normaliser_numero("+226 70 00 00 00") == "+22670000000"
    assert normaliser_numero("0022670000000") == "+22670000000"
    assert normaliser_numero("22670000000") == "+22670000000"
    assert normaliser_numero("abc") is None and normaliser_numero("+12") is None


def test_destinataire_dans_le_corps_et_journal():
    client, db, envois = _client()
    r = _post(client, {"to": "+226 70 11 22 33", "message": "Bonjour", "source": "ster"})
    assert r.status_code == 200, r.text
    assert r.json()["to"] == "+22670112233" and r.json()["source"] == "ster"
    assert envois == [("+22670112233", "Bonjour")]
    import asyncio
    j = asyncio.get_event_loop().run_until_complete(db.liluvine_transmissions.find_one({}))
    assert j["source"] == "ster" and j["ok"] is True and "Bonjour" not in str(j)


def test_repli_numero_par_defaut_et_erreurs():
    client, _, envois = _client(defaut="+22675000000")
    assert _post(client, {"message": "Salut"}).json()["to"] == "+22675000000"
    assert _post(client, {"to": "pas-un-numero", "message": "x"}).status_code == 422
    assert _post(client, {"to": "+22670000000", "message": "x"}, secret="mauvaise").status_code == 401
    client2, _, _ = _client(defaut="")
    assert _post(client2, {"message": "x"}).status_code == 422
