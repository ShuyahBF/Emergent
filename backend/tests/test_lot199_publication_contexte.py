# Lot 199 — Liluvine reçoit le type et le titre de la publication de SAWALI à laquelle le client répond.
import asyncio
from datetime import datetime, timezone

from mongomock_motor import AsyncMongoMockClient

from routes import wa_publication_contexte as pc


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def _db():
    return AsyncMongoMockClient()["t"]


def test_sondage_cite():
    db = _db()
    _run(db.wa_surveys.insert_one({"id": "s1", "title": "Evaluation Loois", "description": "Votre avis",
                                   "questions": [{"label": "Note globale ?"}, {"label": "Un commentaire ?"}]}))
    _run(db.wa_survey_invites.insert_one({"id": "i1", "survey_id": "s1", "message_id": "wamid.S"}))
    ctx = _run(pc.contexte_reponse(db, {"reply_to_message_id": "wamid.S", "phone_digits": "22677001214"}))
    assert ctx["type"] == "sondage" and ctx["titre"] == "Evaluation Loois" and "Note globale" in ctx["resume"] and ctx["cite"]


def test_formulaire_et_carrousel_et_plateforme():
    db = _db()
    _run(db.forms.insert_one({"id": "f1", "title": "Inscription stage", "description": "Dossier à remplir"}))
    _run(db.form_envois.insert_one({"id": "e1", "form_id": "f1", "destinataires": [{"message_id": "wamid.F"}]}))
    _run(db.carrousel_campagnes.insert_one({"id": "c1", "message": "Promo octobre", "destinataires": [{"message_id": "wamid.C"}],
                                            "cartes": [{"titre": "Paracétamol", "texte": "500 FCFA"}]}))
    _run(db.liluvine_transmissions.insert_one({"message_id": "wamid.P", "emetteur": "adlyn", "mode": "modele"}))
    assert _run(pc.contexte_par_wamid(db, "wamid.F"))["titre"] == "Inscription stage"
    c = _run(pc.contexte_par_wamid(db, "wamid.C"))
    assert c["type"] == "carrousel WhatsApp" and "Paracétamol" in c["resume"]
    assert _run(pc.contexte_par_wamid(db, "wamid.P"))["titre"] == "adlyn"


def test_sans_citation_derniere_publication_recente_seulement():
    db = _db()
    maintenant = datetime.now(timezone.utc).isoformat()
    _run(db.whatsapp_messages.insert_many([
        {"direction": "outbound", "phone_digits": "22677001214", "template_name": "rdv_confirmation", "message_id": "wamid.R",
         "template_rendered_body": "Confirmez votre rendez-vous de demain", "created_at": maintenant},
        {"direction": "outbound", "phone_digits": "22670000000", "template_name": "autre", "message_id": "wamid.X", "created_at": maintenant},
        {"direction": "outbound", "phone_digits": "22677001214", "template_name": "vieux", "message_id": "wamid.V",
         "created_at": "2020-01-01T00:00:00+00:00"}]))
    ctx = _run(pc.contexte_reponse(db, {"phone_digits": "22677001214"}))
    assert ctx["titre"] == "rdv_confirmation" and ctx["cite"] is False
    assert _run(pc.contexte_reponse(db, {"phone_digits": "22699999999"})) is None


def test_texte_de_consigne():
    assert pc.texte_contexte(None) == ""
    t = pc.texte_contexte({"type": "sondage", "titre": "Evaluation Loois", "resume": "Votre avis", "cite": True})
    assert "sondage « Evaluation Loois »" in t and "simple clic de bouton" in t and "n'invente rien" in t
    assert "ignore ce contexte" in pc.texte_contexte({"type": "sondage", "titre": "x", "cite": False})
