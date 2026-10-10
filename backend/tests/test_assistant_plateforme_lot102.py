"""Lot 102 — assistant de la plateforme (ZandGo d'abord) : un client qui écrit librement après un message
d'une plateforme dotée d'une « adresse de l'assistant » reçoit la réponse de CETTE plateforme ; appel signé
avec la clé de l'émetteur ; si la plateforme ne répond pas, Liluvine garde la main comme avant."""
import hashlib
import hmac
import json

import httpx

import routes.liluvine_relais as relais
from tests.test_transmission_wa_universelle_lot57_5 import _app, _envoyer, _run


def _brancher_assistant(client, monkeypatch, reponse_http):
    """Règle l'adresse de l'assistant de « ster » (via l'admin) et remplace l'appel HTTP sortant."""
    assert client.patch("/api/admin/liluvine-emetteurs/ster",
                        json={"url_assistant": "https://zandgo.test/api/liluvine/question"}).status_code == 200
    appels = []

    class FauxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, content=None, headers=None):
            appels.append((url, content, headers))
            return reponse_http
    monkeypatch.setattr(relais.httpx, "AsyncClient", FauxClient)
    return appels


def test_reponse_de_l_assistant(monkeypatch):
    client, db, envois, cle = _app()
    req = httpx.Request("POST", "https://zandgo.test")
    appels = _brancher_assistant(client, monkeypatch, httpx.Response(
        200, json={"reponse": "Votre commande ZG-1 est en route vers le Burkina.", "intention": "commande"}, request=req))
    assert _envoyer(client, cle, {"id": "z1", "to": "+22670000011", "message": "Commande confirmée"}).status_code == 200
    reponses = []

    async def envoi(numero, texte):
        reponses.append((numero, texte))
        return {"ok": True, "message_id": "wamid.assistant"}
    r = _run(relais.traiter_message_entrant(db, de="22670000011", type_message="text",
                                            texte="Où en est ma commande ?", send_text=envoi))
    assert r["action"] == "reponse_assistant" and r["message_id"] == "wamid.assistant"
    assert reponses == [("22670000011", "Votre commande ZG-1 est en route vers le Burkina.")]
    # Appel signé avec la clé de l'émetteur, au format attendu par ZandGo
    url, brut, ent = appels[0]
    assert url == "https://zandgo.test/api/liluvine/question"
    assert json.loads(brut) == {"telephone": "22670000011", "texte": "Où en est ma commande ?"}
    attendu = hmac.new(cle.encode(), f"{ent['X-Timestamp']}.".encode() + brut, hashlib.sha256).hexdigest()
    assert ent["X-Signature"] == attendu
    journal = _run(db.liluvine_assistant_journal.find_one({}, {"_id": 0}))
    assert journal["emetteur"] == "ster" and journal["intention"] == "commande" and journal["envoye"] is True


def test_assistant_injoignable_liluvine_garde_la_main(monkeypatch):
    client, db, envois, cle = _app()
    req = httpx.Request("POST", "https://zandgo.test")
    _brancher_assistant(client, monkeypatch, httpx.Response(503, text="indisponible", request=req))
    _envoyer(client, cle, {"id": "z2", "to": "+22670000012", "message": "Commande confirmée"})

    async def envoi(numero, texte):
        raise AssertionError("aucun envoi attendu")
    r = _run(relais.traiter_message_entrant(db, de="22670000012", type_message="text", texte="Bonjour", send_text=envoi))
    assert r == {"traite": False}
    assert _run(db.liluvine_incidents.count_documents({"motif": "assistant_injoignable"})) == 1
    # Adresse invalide (http) refusée par l'admin
    assert client.patch("/api/admin/liluvine-emetteurs/ster", json={"url_assistant": "http://x.test"}).status_code == 422


def test_mot_cle_et_session_lot103(monkeypatch):
    """Lot 103 : « !ster … » joint l'assistant SANS message préalable ; la session dure 30 min ; FIN rend la main."""
    client, db, envois, cle = _app()
    req = httpx.Request("POST", "https://zandgo.test")
    appels = _brancher_assistant(client, monkeypatch, httpx.Response(200, json={"reponse": "Réponse de Ster", "intention": "aide"}, request=req))
    recus = []

    async def envoi(numero, texte):
        recus.append(texte)
        return {"ok": True, "message_id": "wamid.x"}
    # Mots proches ou sans mot-clé, hors session : non concernés
    assert relais.detecter_mot_cle("!sterilisation du materiel", [{"code": "ster", "nom": "Ster"}]) is None
    assert relais.detecter_mot_cle("Ster où est ma commande", [{"code": "ster", "nom": "Ster"}]) is None     # sans « ! »
    assert _run(relais.traiter_message_entrant(db, de="22670000021", type_message="text", texte="Bonjour", send_text=envoi)) == {"traite": False}
    # Commande « ! » (casse, ponctuation) : question transmise sans la commande
    r = _run(relais.traiter_message_entrant(db, de="22670000021", type_message="text", texte="!STER : où est ma commande ?", send_text=envoi))
    assert r["action"] == "reponse_assistant" and recus[-1] == "Réponse de Ster"
    assert json.loads(appels[-1][1])["texte"] == "où est ma commande ?"
    # Session : le message suivant, sans mot-clé, va aussi à l'assistant
    r = _run(relais.traiter_message_entrant(db, de="22670000021", type_message="text", texte="et le prix de la lampe ?", send_text=envoi))
    assert r["action"] == "reponse_assistant" and json.loads(appels[-1][1])["texte"] == "et le prix de la lampe ?"
    # Mot-clé seul : demande d'aide
    _run(relais.traiter_message_entrant(db, de="22670000022", type_message="text", texte="! ster", send_text=envoi))
    assert json.loads(appels[-1][1])["texte"] == "aide"
    # FIN : session close, Liluvine reprend la main
    r = _run(relais.traiter_message_entrant(db, de="22670000021", type_message="text", texte="fin", send_text=envoi))
    assert r["action"] == "fin_assistant" and "terminée" in recus[-1]
    assert _run(relais.traiter_message_entrant(db, de="22670000021", type_message="text", texte="Bonjour", send_text=envoi)) == {"traite": False}
    # Session expirée : plus de transmission
    _run(db.liluvine_assistant_sessions.update_one({"numero": "22670000022"}, {"$set": {"jusqu_a": "2000-01-01T00:00:00+00:00"}}))
    assert _run(relais.traiter_message_entrant(db, de="22670000022", type_message="text", texte="ma commande", send_text=envoi)) == {"traite": False}
    # STOP n'est jamais pris pour une question
    nb = len(appels)
    _run(relais.traiter_message_entrant(db, de="22670000023", type_message="text", texte="STOP", send_text=envoi))
    assert len(appels) == nb
