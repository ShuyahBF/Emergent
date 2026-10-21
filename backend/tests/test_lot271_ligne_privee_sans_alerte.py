"""Lot 271 — un WhatsApp reçu sur une ligne PRIVÉE ne déclenche aucune alerte (Alexa, relais, appel propriétaire)."""
import asyncio

import mongomock_motor

from routes import numeros_wa

LIGNE_PRIVEE = "555000111"
REGLAGES = {"_id": "global", "wa_phone_number_id": "100200300",
            "wa_numeros": [{"id": LIGNE_PRIVEE, "libelle": "ALBARKA", "privee": True},
                           {"id": "999888777", "libelle": "Liluvine VIP", "vip": True}]}


def _resultat(numero_recu):
    """Appelle ligne_recue_privee comme le webhook : numéro reçu mémorisé le temps du traitement."""
    async def _go():
        db = mongomock_motor.AsyncMongoMockClient()["test_lot271"]
        await db.settings.insert_one(dict(REGLAGES))
        jeton = numeros_wa.definir_numero_recu(numero_recu)
        try:
            return await numeros_wa.ligne_recue_privee(db)
        finally:
            numeros_wa.retablir_numero_recu(jeton)
    return asyncio.new_event_loop().run_until_complete(_go())


def test_message_sur_ligne_privee_est_detecte():
    assert _resultat(LIGNE_PRIVEE) is True          # → pas d'alerte


def test_message_sur_autre_ligne_reste_alerte_comme_avant():
    assert _resultat("100200300") is False          # ligne principale de SAWALI
    assert _resultat("999888777") is False          # ligne VIP non privée


def test_hors_webhook_ou_ligne_inconnue_rien_ne_change():
    assert _resultat(None) is False
    assert _resultat("000") is False
