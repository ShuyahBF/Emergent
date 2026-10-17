"""Lot 223 — LIGNE WHATSAPP PAR PLATEFORME ÉMETTRICE et LIGNES PRIVÉES.

  - une plateforme (ex. ALBARKA) peut avoir sa propre ligne de SAWALI : ses messages partent de ce numéro,
    la fenêtre de 24 h est celle de CE numéro ; ligne inconnue refusée ;
  - une ligne « privée » n'est visible de personne dans le Centre de messagerie (administrateurs compris),
    sauf accord explicite ; sans ligne privée, rien ne change.
"""
import asyncio
import hashlib
import hmac
import json
import time

import mongomock_motor
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from routes import numeros_wa
from routes.liluvine_emetteurs import make_liluvine_emetteurs_router
from routes.liluvine_send_webhook import attach_liluvine_send_webhook_routes, fenetre_ouverte

LIGNE_ALBARKA = "555000111"
REGLAGES = {"_id": "global", "wa_phone_number_id": "100200300",
            "wa_numeros": [{"id": LIGNE_ALBARKA, "libelle": "ALBARKA", "telephone": "+226 73 37 48 48", "privee": True},
                           {"id": "999888777", "libelle": "Liluvine VIP", "vip": True}]}


def _boucle():
    return asyncio.get_event_loop()


def _app():
    db = mongomock_motor.AsyncMongoMockClient()["test_lot223"]
    vues = []                                                    # ligne imposée vue pendant l'envoi

    async def faux_texte(numero, texte):
        vues.append(numeros_wa._ligne_forcee.get())
        return {"ok": True, "message_id": f"wamid.{len(vues)}"}

    async def admin():
        return {"email": "admin@sawali.test"}

    api = APIRouter(prefix="/api")
    attach_liluvine_send_webhook_routes(api=api, db=db, wa_send_text=faux_texte)
    api.include_router(make_liluvine_emetteurs_router(db=db, get_current_admin=admin))
    app = FastAPI()
    app.include_router(api)
    _boucle().run_until_complete(db.settings.insert_one(dict(REGLAGES)))
    return TestClient(app), db, vues


def _envoyer(client, code, cle, corps):
    brut = json.dumps(corps)
    ts = str(int(time.time()))
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return client.post("/api/webhook/liluvine-send", content=brut, headers={
        "Content-Type": "application/json", "X-Emetteur": code, "X-Timestamp": ts, "X-Signature": sig})


def test_plateforme_avec_ligne_dediee():
    client, db, vues = _app()
    cle = client.post("/api/admin/liluvine-emetteurs", json={"code": "albarka", "nom": "ALBARKA"}).json()["cle"]
    # Ligne inconnue refusée, ligne connue acceptée (liste des lignes renvoyée à l'écran d'administration)
    assert client.patch("/api/admin/liluvine-emetteurs/albarka", json={"ligne": "inconnue"}).status_code == 422
    assert client.patch("/api/admin/liluvine-emetteurs/albarka", json={"ligne": LIGNE_ALBARKA}).status_code == 200
    liste = client.get("/api/admin/liluvine-emetteurs").json()
    assert liste["emetteurs"][0]["ligne"] == LIGNE_ALBARKA
    assert [l["cle"] for l in liste["lignes"]] == ["principal", LIGNE_ALBARKA, "999888777"] and liste["lignes"][1]["privee"] is True
    # L'envoi part avec la ligne imposée, remise à zéro ensuite ; le journal garde la ligne
    r = _envoyer(client, "albarka", cle, {"to": "+22670000001", "message": "Votre facture est prête", "id": "m1"})
    assert r.status_code == 200 and vues == [LIGNE_ALBARKA] and numeros_wa._ligne_forcee.get() is None
    assert _boucle().run_until_complete(db.liluvine_transmissions.find_one({"id_externe": "m1"}))["ligne"] == LIGNE_ALBARKA


def test_plateforme_sans_ligne_inchangee():
    client, db, vues = _app()
    cle = client.post("/api/admin/liluvine-emetteurs", json={"code": "ster", "nom": "Ster"}).json()["cle"]
    assert _envoyer(client, "ster", cle, {"to": "+22670000002", "message": "Bonjour", "id": "m2"}).status_code == 200
    assert vues == [None]
    # Retirer la ligne (vide) remet les règles habituelles
    client.patch("/api/admin/liluvine-emetteurs/ster", json={"ligne": LIGNE_ALBARKA})
    client.patch("/api/admin/liluvine-emetteurs/ster", json={"ligne": ""})
    _envoyer(client, "ster", cle, {"to": "+22670000003", "message": "Bonjour", "id": "m3"})
    assert vues[-1] is None


def test_fenetre_24h_propre_au_numero():
    db = mongomock_motor.AsyncMongoMockClient()["test_lot223_fenetre"]
    from datetime import datetime, timezone
    maintenant = datetime.now(timezone.utc)
    _boucle().run_until_complete(db.whatsapp_messages.insert_one({
        "direction": "inbound", "created_at": maintenant.isoformat(), "phone_digits": "22670000009", "wa_numero_id": "100200300"}))
    # Écrit au numéro principal : fenêtre ouverte pour lui, pas pour la ligne d'ALBARKA
    assert _boucle().run_until_complete(fenetre_ouverte(db, "+22670000009", maintenant)) is True
    assert _boucle().run_until_complete(fenetre_ouverte(db, "+22670000009", maintenant, "100200300")) is True
    assert _boucle().run_until_complete(fenetre_ouverte(db, "+22670000009", maintenant, LIGNE_ALBARKA)) is False


def test_ligne_privee_invisible_pour_tous_sauf_accord():
    admin = {"role": "admin"}
    simple = {"role": "user"}
    # Un administrateur voyait tout : la ligne privée est maintenant exclue
    assert numeros_wa.lignes_autorisees(admin, REGLAGES) == {"principal", "999888777"}
    assert numeros_wa.lignes_autorisees(simple, REGLAGES) == {"principal", "999888777"}
    # Un utilisateur limité à certaines lignes ne reçoit jamais la ligne privée de lui-même
    assert numeros_wa.lignes_autorisees({"wa_lignes_autorisees": ["principal"]}, REGLAGES) == {"principal"}
    # Accord explicite : seul celui qui la porte la voit (administrateur compris)
    accord = {"role": "admin", "wa_lignes_autorisees": [LIGNE_ALBARKA]}
    assert numeros_wa.lignes_autorisees(accord, REGLAGES) == {"principal", "999888777", LIGNE_ALBARKA}


def test_sans_ligne_privee_rien_ne_change():
    sans = {"_id": "global", "wa_phone_number_id": "1", "wa_numeros": [{"id": "2", "libelle": "VIP", "vip": True}]}
    assert numeros_wa.lignes_autorisees({"role": "admin"}, sans) is None
    assert numeros_wa.lignes_autorisees({}, sans) is None
    assert numeros_wa.lignes_autorisees({"wa_lignes_autorisees": ["2"]}, sans) == {"2"}


def test_conversation_de_la_ligne_privee_masquee_dans_le_centre_de_messagerie():
    db = mongomock_motor.AsyncMongoMockClient()["test_lot223_centre"]
    boucle = _boucle()
    boucle.run_until_complete(db.whatsapp_messages.insert_many([
        {"direction": "inbound", "phone_digits": "22670111111", "wa_numero_id": LIGNE_ALBARKA, "created_at": "2026-10-17T10:00:00"},
        {"direction": "inbound", "phone_digits": "22670222222", "wa_numero_id": "100200300", "created_at": "2026-10-17T10:01:00"},
    ]))
    vis = boucle.run_until_complete(numeros_wa.VisibiliteLignes.charger(db, {"role": "admin"}, dict(REGLAGES)))
    assert vis.restreint is True
    assert vis.telephone_visible("+22670111111") is False          # client d'ALBARKA : masqué, même pour l'administrateur
    assert vis.telephone_visible("+22670222222") is True           # conversation de la ligne principale : visible
    accord = boucle.run_until_complete(numeros_wa.VisibiliteLignes.charger(
        db, {"role": "admin", "wa_lignes_autorisees": [LIGNE_ALBARKA]}, dict(REGLAGES)))
    assert accord.telephone_visible("+22670111111") is True
