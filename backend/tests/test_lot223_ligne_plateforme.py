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


TEXTES = []                                                      # textes envoyés par le faux WhatsApp


def _boucle():
    return asyncio.get_event_loop()


def _app():
    db = mongomock_motor.AsyncMongoMockClient()["test_lot223"]
    vues = []                                                    # ligne imposée vue pendant l'envoi

    async def faux_texte(numero, texte):
        TEXTES.append(texte)                                     # lot 248 : textes réellement envoyés
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


# ---- Lot 247 : une ligne privée n'est jamais choisie pour les envois de SAWALI (rapports, synthèses, comptes rendus…) ----

def _db_inbound(numero_id):
    db = mongomock_motor.AsyncMongoMockClient()["test_lot247"]
    from datetime import datetime, timezone
    _boucle().run_until_complete(db.whatsapp_messages.insert_one({
        "direction": "inbound", "phone_digits": "22670000001", "wa_numero_id": numero_id,
        "created_at": datetime.now(timezone.utc).isoformat()}))
    return db


def test_envoi_sawali_jamais_par_la_ligne_privee_meme_si_le_correspondant_y_a_ecrit():
    db = _db_inbound(LIGNE_ALBARKA)                  # le correspondant vient d'écrire à la ligne privée (ALBARKA)
    pid = _boucle().run_until_complete(numeros_wa.numero_envoi(db, "+22670000001", REGLAGES))
    assert pid == "100200300"                        # → ligne principale de SAWALI, pas la ligne ALBARKA


def test_envoi_sawali_suit_toujours_la_ligne_non_privee_ou_le_correspondant_a_ecrit():
    db = _db_inbound("999888777")                    # ligne VIP (non privée) : inchangé
    pid = _boucle().run_until_complete(numeros_wa.numero_envoi(db, "+22670000001", REGLAGES))
    assert pid == "999888777"


def test_ligne_privee_reste_utilisable_quand_elle_est_imposee():
    db = _db_inbound(LIGNE_ALBARKA)
    jeton = numeros_wa.definir_ligne_forcee(LIGNE_ALBARKA)           # plateforme ALBARKA ou choix explicite de l'agent
    try:
        pid = _boucle().run_until_complete(numeros_wa.numero_envoi(db, "+22670000001", REGLAGES))
    finally:
        numeros_wa.retablir_ligne_forcee(jeton)
    assert pid == LIGNE_ALBARKA


def test_visibilite_des_conversations_inchangee_par_le_lot_247():
    db = _db_inbound(LIGNE_ALBARKA)
    cle = _boucle().run_until_complete(numeros_wa.cle_ligne_conversation(db, "+22670000001", REGLAGES))
    assert cle == LIGNE_ALBARKA                      # la conversation appartient toujours à la ligne privée (masquée)


# ---- Lot 248 : sur la ligne DÉDIÉE d'une plateforme, tout message reçu lui est relayé (sans « Répondre ») -----------------

def test_ligne_dediee_relaie_toute_reponse_sans_citation(monkeypatch):
    from routes import liluvine_relais as relais
    db = mongomock_motor.AsyncMongoMockClient()["test_lot248"]
    retours = []

    async def faux_retour(db_, emetteur, corps):
        retours.append((emetteur["code"], corps))
        return True
    monkeypatch.setattr(relais, "_poster_retour", faux_retour)

    async def scenario():
        await db.settings.insert_one(dict(REGLAGES))
        await db.liluvine_emetteurs.insert_one({"code": "albarka", "nom": "ALBARKA", "actif": True,
                                                "ligne": LIGNE_ALBARKA, "url_retour": "https://albarka.test/retour"})
        # 1. message LIBRE reçu sur la ligne ALBARKA : relayé à ALBARKA, Liluvine ne répond pas
        jeton = numeros_wa.definir_numero_recu(LIGNE_ALBARKA)
        try:
            libre = await relais.traiter_message_entrant(db, de="22670000007", type_message="text", texte="Bonjour, voici ma réponse", send_text=None)
        finally:
            numeros_wa.retablir_numero_recu(jeton)
        await asyncio.sleep(0)
        # 2. même message reçu sur la ligne PRINCIPALE de SAWALI : inchangé (reste à SAWALI)
        jeton = numeros_wa.definir_numero_recu("100200300")
        try:
            principal = await relais.traiter_message_entrant(db, de="22670000007", type_message="text", texte="Bonjour", send_text=None)
        finally:
            numeros_wa.retablir_numero_recu(jeton)
        return libre, principal
    libre, principal = _boucle().run_until_complete(scenario())
    assert libre["traite"] is True and libre["action"] == "reponse_relayee"
    assert [(c, r["type"], r["texte"]) for c, r in retours] == [("albarka", "reponse", "Bonjour, voici ma réponse")]
    assert principal == {"traite": False}


def test_ligne_dediee_sans_url_de_retour_liluvine_ne_repond_pas():
    from routes import liluvine_relais as relais
    db = mongomock_motor.AsyncMongoMockClient()["test_lot248b"]

    async def scenario():
        await db.settings.insert_one(dict(REGLAGES))
        await db.liluvine_emetteurs.insert_one({"code": "albarka", "nom": "ALBARKA", "actif": True, "ligne": LIGNE_ALBARKA})
        jeton = numeros_wa.definir_numero_recu(LIGNE_ALBARKA)
        try:
            return await relais.traiter_message_entrant(db, de="22670000008", type_message="text", texte="Bonjour", send_text=None)
        finally:
            numeros_wa.retablir_numero_recu(jeton)
    r = _boucle().run_until_complete(scenario())
    assert r["traite"] is True and r["action"] == "ligne_dediee_sans_retour"


def test_ligne_dediee_pas_de_consigne_repondre_sous_le_message():
    from routes.liluvine_send_webhook import _aide_reponse
    assert _aide_reponse("ALBARKA", True, True) == ""                       # ligne propre : une simple réponse suffit
    assert "Répondre" in _aide_reponse("Ster", True, False)                 # ligne SAWALI : consigne inchangée
    assert "ne pas y répondre" in _aide_reponse("ALBARKA", False, True)     # « réponses non transmises » : inchangé


def test_ligne_dediee_message_sans_entete_ni_consigne():
    """Lot 248 : sur la ligne propre à la plateforme, le destinataire reçoit le message tel quel (pas d'en-tête « 📨 Plateforme — date »)."""
    TEXTES.clear()
    client, db, vues = _app()
    cle = client.post("/api/admin/liluvine-emetteurs", json={"code": "albarka", "nom": "ALBARKA"}).json()["cle"]
    client.patch("/api/admin/liluvine-emetteurs/albarka", json={"ligne": LIGNE_ALBARKA})
    assert _envoyer(client, "albarka", cle, {"to": "+22670000001", "message": "Votre facture est prête", "id": "m9"}).status_code == 200
    assert TEXTES == ["Votre facture est prête"]
    # Sans ligne dédiée (plateforme sur les lignes SAWALI) : l'en-tête et la consigne restent
    TEXTES.clear()
    cle2 = client.post("/api/admin/liluvine-emetteurs", json={"code": "ster", "nom": "Ster"}).json()["cle"]
    assert _envoyer(client, "ster", cle2, {"to": "+22670000002", "message": "Bonjour", "id": "m10"}).status_code == 200
    assert TEXTES[0].startswith("📨") and "Répondre" in TEXTES[0]
