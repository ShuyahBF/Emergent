"""Lot 112.1 — Transmission universelle : quand le destinataire a écrit à SAWALI depuis moins de 24 h,
le message part en TEXTE LIBRE (toujours remis dans la fenêtre) au lieu du modèle Meta ; sinon, modèle."""
from datetime import datetime, timedelta, timezone

from tests.test_transmission_wa_universelle_lot57_5 import _app, _envoyer, _run


def _message_recu(db, numero: str, il_y_a: timedelta) -> None:
    """Message WhatsApp ENTRANT du destinataire, daté de « maintenant - il_y_a »."""
    quand = (datetime.now(timezone.utc) - il_y_a).isoformat()
    _run(db.whatsapp_messages.insert_one({"direction": "inbound", "created_at": quand, "phone_digits": numero}))


def test_fenetre_ouverte_texte_libre():
    client, db, envois, cle = _app()
    _run(db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_transmission_modele": "transmission_plateformes"}}))
    _message_recu(db, "22658437050", timedelta(hours=2))
    r = _envoyer(client, cle, {"id": "f1", "to": "+22658437050", "message": "Votre panier PAN-1"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "texte" and envois[-1][0] == "texte"


def test_fenetre_fermee_modele():
    client, db, envois, cle = _app()
    _run(db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_transmission_modele": "transmission_plateformes"}}))
    _message_recu(db, "22670000077", timedelta(hours=30))     # plus de 24 h : fenêtre fermée
    r = _envoyer(client, cle, {"id": "f2", "to": "+22670000077", "message": "Votre panier PAN-2"})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "modele" and envois[-1][0] == "modele"
