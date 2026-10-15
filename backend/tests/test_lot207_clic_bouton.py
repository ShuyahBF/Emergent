# Lot 207 — tout clic sur un bouton reçoit un accusé de réception immédiat, une fois toutes les 10 minutes par numéro.
import asyncio
from datetime import datetime, timedelta, timezone

from mongomock_motor import AsyncMongoMockClient

from routes import wa_clic_bouton as cb


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def _envoi(envois):
    async def envoyer(to, texte, **kw):
        envois.append((to, texte))
        return {"ok": True, "status": 200, "message_id": f"wamid.{len(envois)}"}
    return envoyer


def _clic(texte="Confirmer", **kw):
    return {"message_type": "button", "body": texte, "phone_digits": "22670163945", "from": "+22670163945",
            "wa_message_id": "wamid.IN1", "client_id": "cl1", "contact_id": "c1", **kw}


def test_texte_de_l_accuse():
    assert "« Confirmer »" in cb.texte_accuse(None, "Confirmer", None) and "{" not in cb.texte_accuse(None, "Confirmer", None)
    t = cb.texte_accuse(None, "Oui", {"cite": True, "type": "sondage", "titre": "Evaluation Loois"})
    assert "à propos de : sondage « Evaluation Loois »" in t
    # sans citation du message d'origine, aucune publication n'est affirmée
    assert "à propos de" not in cb.texte_accuse(None, "Oui", {"cite": False, "type": "sondage", "titre": "X"})
    assert cb.texte_accuse("Merci pour {bouton}{contexte}", "Ok", None) == "Merci pour Ok"


def test_clic_accuse_journalise_puis_pas_de_rafale():
    db = AsyncMongoMockClient()["t"]
    envois = []
    r = _run(cb.accuser_clic(db, inbound_doc=_clic(), wa_send_text=_envoi(envois)))
    assert r["ok"] and r["reason"] == "clic_bouton_accuse" and len(envois) == 1 and "Confirmer" in envois[0][1]
    trace = _run(db.whatsapp_messages.find_one({"ai_source": "clic_bouton"}))
    assert trace["direction"] == "outbound" and trace["contact_id"] == "c1" and trace["reply_to_message_id"] == "wamid.IN1"
    # deuxième clic 20 minutes plus tard dans la fenêtre des 10 minutes : refusé ; après 11 minutes : accusé de nouveau
    r2 = _run(cb.accuser_clic(db, inbound_doc=_clic(), wa_send_text=_envoi(envois)))
    assert r2["reason"] == "deja_accuse" and len(envois) == 1
    plus_tard = datetime.now(timezone.utc) + timedelta(minutes=11)
    r3 = _run(cb.accuser_clic(db, inbound_doc=_clic(), wa_send_text=_envoi(envois), maintenant=plus_tard))
    assert r3["ok"] and len(envois) == 2


def test_message_ordinaire_ignore_et_contexte_de_la_publication():
    db = AsyncMongoMockClient()["t"]
    envois = []
    assert _run(cb.accuser_clic(db, inbound_doc={"message_type": "text", "body": "Bonjour", "phone_digits": "22670163945"},
                                wa_send_text=_envoi(envois)))["reason"] == "pas_un_clic" and envois == []
    # clic sur le bouton d'un sondage : l'accusé le rappelle
    _run(db.wa_surveys.insert_one({"id": "s1", "title": "Evaluation Loois", "questions": []}))
    _run(db.wa_survey_invites.insert_one({"id": "i1", "survey_id": "s1", "message_id": "wamid.S"}))
    r = _run(cb.accuser_clic(db, inbound_doc=_clic(reply_to_message_id="wamid.S"), wa_send_text=_envoi(envois)))
    assert r["origine"] == "sondage" and "sondage « Evaluation Loois »" in envois[0][1]
