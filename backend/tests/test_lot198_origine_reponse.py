# Lot 198 — retrouver le message auquel un client répond (envoi SAWALI ou plateforme externe).
import asyncio

from mongomock_motor import AsyncMongoMockClient

from routes.wa_origine_reponse import apercus_origines


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_envoi_sawali_par_wa_message_id_et_message_id():
    db = AsyncMongoMockClient()["t"]
    _run(db.whatsapp_messages.insert_many([
        {"id": "1", "wa_message_id": "wamid.A", "direction": "outbound", "body": "Bonjour", "created_at": "2026-10-15T08:00:00Z"},
        {"id": "2", "message_id": "wamid.B", "direction": "outbound", "template_name": "rdv_confirmation",
         "template_rendered_body": "Confirmez votre rendez-vous", "created_at": "2026-10-15T08:10:00Z"}]))
    r = _run(apercus_origines(db, ["wamid.A", "wamid.B", "wamid.Z"]))
    assert r["wamid.A"]["texte"] == "Bonjour"
    assert r["wamid.B"]["modele"] == "rdv_confirmation" and r["wamid.B"]["texte"] == "Confirmez votre rendez-vous"
    assert "wamid.Z" not in r


def test_envoi_d_une_plateforme_externe_sans_texte():
    db = AsyncMongoMockClient()["t"]
    _run(db.liluvine_transmissions.insert_one({"date": "2026-10-15T08:50:00Z", "emetteur": "adlyn", "source": "adLyn",
                                               "mode": "modele", "message_id": "wamid.P", "ok": True}))
    r = _run(apercus_origines(db, ["wamid.P"]))["wamid.P"]
    assert r["plateforme"] == "adlyn" and "modèle" in r["texte"] and r["le"] == "2026-10-15T08:50:00Z"


def test_aucun_identifiant():
    assert _run(apercus_origines(AsyncMongoMockClient()["t"], [None, ""])) == {}
