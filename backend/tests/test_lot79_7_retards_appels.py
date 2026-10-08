"""Lot 79.7 — retards de paiement : UN récapitulatif numéroté au propriétaire, réponse « ok 1,2,5 » pour relancer
les clients choisis ; appels de Liluvine : mesure du son transmis, ElevenLabs mis de côté après un 402.
Lancer : cd backend && python -m pytest tests/test_lot79_7_retards_appels.py -q
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import routes.appel_proprietaire as ap  # noqa: E402
import routes.retards_paiement as rp  # noqa: E402

PROPRIO = "22670000001"
REGLAGES = {"super_admin_phone": PROPRIO, "wa_access_token": "jeton-de-test", "wa_phone_number_id": "123",
            "appel_proprio_modele": "relais_messagewa_pouradmin"}


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def db():
    return mongomock_motor.AsyncMongoMockClient()["sawali_lot79_7"]


@pytest.fixture()
def envois(monkeypatch):
    """Remplace l'API Meta : chaque envoi est noté (destinataire, type, texte ou modèle)."""
    notes = []

    async def faux_post(s, numero_id, chemin, corps):
        notes.append(corps)
        return {"ok": True, "donnees": {"messages": [{"id": f"wamid.{len(notes)}"}]}, "erreur": None}
    monkeypatch.setattr(ap, "_graph_post", faux_post)
    return notes


def retard(nom, jours, tel, email=""):
    return {"id": nom.lower(), "company": nom, "days_overdue": jours, "contract_number": f"C-{jours}",
            "contract_amount": 50000, "contract_currency": "FCFA", "whatsapp_number": tel, "email": email}


RETARDS = [retard("Alpha", 12, "22670111111"), retard("Beta", 40, "22670222222"), retard("Gamma", 7, "")]


def test_lecture_de_la_reponse():
    assert rp.lire_choix("ok 1,2,5", 4) == ([1, 2], ["5"])
    assert rp.lire_choix("OK 1 et 3", 3) == ([1, 3], [])
    assert rp.lire_choix("ok tous", 3) == ([1, 2, 3], [])
    assert rp.lire_choix("Ok : 2", 3) == ([2], [])
    assert rp.lire_choix("ok merci", 3) is None          # un simple « ok merci » n'est PAS une relance
    assert rp.lire_choix("bonjour 1,2", 3) is None


def test_mode_par_defaut_et_textes():
    assert rp.mode_alertes({}) == "recap" and rp.mode_alertes({"contract_overdue_mode": "detail"}) == "detail"
    assert rp.mode_alertes({"contract_overdue_mode": "nimporte"}) == "recap"
    elements = rp.elements_recap(RETARDS)
    assert [e["nom"] for e in elements] == ["Beta", "Alpha", "Gamma"]      # du plus gros retard au plus petit
    assert "\n" not in rp.texte_recap(elements, une_ligne=True)            # modèle Meta : une seule ligne
    assert "1) Beta — 40 j" in rp.texte_recap(elements)


def test_un_seul_recapitulatif_par_jour(db, envois):
    r = lancer(rp.envoyer_recap(db, REGLAGES, RETARDS))
    assert r["envoye"] and r["whatsapp_ok"]
    assert len(envois) == 1 and envois[0]["to"] == PROPRIO
    # Fenêtre de 24 h fermée : modèle « relais » à 3 variables, liste sur une ligne
    assert envois[0]["type"] == "template"
    variables = envois[0]["template"]["components"][0]["parameters"]
    assert len(variables) == 3 and "1) Beta" in variables[1]["text"]
    # Second passage le même jour : rien n'est renvoyé
    assert lancer(rp.envoyer_recap(db, REGLAGES, RETARDS))["envoye"] is False and len(envois) == 1


def test_reponse_ok_relance_les_clients_choisis(db, envois):
    lancer(rp.envoyer_recap(db, REGLAGES, RETARDS))
    envois.clear()
    # Beta (n° 1) a écrit à SAWALI il y a 2 h : texte libre ; Alpha (n° 2) : fenêtre fermée et aucun modèle
    lancer(db.whatsapp_messages.insert_one({"direction": "inbound", "phone_digits": "22670222222",
                                            "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}))
    reponse = lancer(rp.traiter_reponse(db, REGLAGES, "+226 70 00 00 01", "ok 1,2,9"))
    assert "✅ Relance envoyée : 1 Beta" in reponse
    assert "2 Alpha (fenêtre WhatsApp de 24 h fermée" in reponse
    assert "❓ Numéro(s) inconnu(s) : 9" in reponse
    assert len(envois) == 1 and envois[0]["to"] == "22670222222" and envois[0]["type"] == "text"
    # Avec un modèle de relance déclaré, Alpha est relancé par le modèle (4 variables)
    envois.clear()
    s = {**REGLAGES, "contract_relance_wa_template": "relance_retard_paiement"}
    reponse = lancer(rp.traiter_reponse(db, s, PROPRIO, "ok 2"))
    assert "✅ Relance envoyée : 2 Alpha" in reponse
    assert envois[0]["template"]["name"] == "relance_retard_paiement"
    assert len(envois[0]["template"]["components"][0]["parameters"]) == 4
    # Journal des relances gardé dans le document de suivi
    doc = lancer(db.settings.find_one({"_id": rp.DOC_RECAP}))
    assert len(doc["relances"]) == 3


def test_seul_le_proprietaire_peut_declencher(db, envois):
    lancer(rp.envoyer_recap(db, REGLAGES, RETARDS))
    envois.clear()
    assert lancer(rp.traiter_reponse(db, REGLAGES, "22676999999", "ok 1,2")) is None   # un client qui écrit « ok 1,2 »
    assert envois == []


def test_elevenlabs_mis_de_cote_apres_402(monkeypatch):
    ap._elevenlabs_en_pause["jusqu_a"] = 0.0
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cle-de-test")

    class Reponse:
        status_code, content = 402, b""

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return Reponse()
    monkeypatch.setattr(ap.httpx, "AsyncClient", Client)
    with pytest.raises(RuntimeError):
        lancer(ap._voix_elevenlabs("Bonjour", {"voix_elevenlabs": "voix", "modele_elevenlabs": None}))
    assert ap.elevenlabs_en_pause()

    async def fausse_google(texte):
        return b"mp3"
    monkeypatch.setattr(ap, "_voix_google", fausse_google)
    audio, fournisseur = lancer(ap.synthetiser("Bonjour", {}, {"voix": "elevenlabs", "voix_elevenlabs": "voix"}))
    assert fournisseur == "google" and audio == b"mp3"
    ap._elevenlabs_en_pause["jusqu_a"] = 0.0


def test_mesures_rtp():
    from routes.audio_appel import mesures_rtp

    class Stat:
        def __init__(self, type_, **k):
            self.type = type_
            self.__dict__.update(k)

    class FauxPC:
        connectionState, iceConnectionState = "connected", "completed"

        async def getStats(self):
            return {"a": Stat("outbound-rtp", packetsSent=500, bytesSent=40000),
                    "b": Stat("inbound-rtp", packetsReceived=0, bytesReceived=0)}
    m = lancer(mesures_rtp(FauxPC()))
    assert m["envoyes"] == 500 and m["recus"] == 0 and m["etat"] == "connected"
