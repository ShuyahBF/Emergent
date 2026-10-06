"""Lot 69 — Liluvine décroche les appels WhatsApp entrants et répond avec son prompt système.

Décision (activé, ligne, exclusions, modes toujours / délai / hors heures, limite d'appels simultanés),
prise atomique (un humain qui a décroché = Liluvine s'efface), détection de parole sur du son synthétique,
assemblage du prompt, transcription et journal, routes (droits, contrôles), puis un appel complet de bout
en bout entre deux interlocuteurs WebRTC LOCAUX (aiortc) : « l'appelant » envoie sa voix, la transcription,
l'IA et la voix sont simulées, l'appelant entend Liluvine, l'appel est terminé et journalisé.
MongoDB simulé, API Graph factice : aucun appel réseau.
Lancer : cd backend && python -m pytest tests/test_lot69_liluvine_decroche.py -q
"""
from __future__ import annotations

import asyncio
import math
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import APIRouter, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routes.appel_proprietaire as ap  # noqa: E402
import routes.appels_wa as aw  # noqa: E402
import routes.liluvine_decroche as ld  # noqa: E402

APPELANT = "22670000001"
# Lundi 6 octobre 2026, 14 h 05 à Ouagadougou (UTC)
EN_JOURNEE = datetime(2026, 10, 6, 14, 5, tzinfo=timezone.utc)
LA_NUIT = datetime(2026, 10, 6, 22, 30, tzinfo=timezone.utc)
DIMANCHE = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)


def lancer(coro):
    """Exécute une coroutine dans une boucle neuve."""
    return asyncio.new_event_loop().run_until_complete(coro)


def cfg(**autres):
    """Réglages effectifs à partir de réglages bruts (décroché activé par défaut dans les tests)."""
    brut = {"liluvine_decroche_actif": True}
    brut.update({f"liluvine_decroche_{k}": v for k, v in autres.items()})
    return ld.reglages_decroche(brut)


def decider(c, **kw):
    """Décision avec des valeurs par défaut."""
    params = {"ligne_cle": "principal", "telephone": APPELANT, "contact": None, "maintenant": EN_JOURNEE, "actifs": 0}
    params.update(kw)
    return ld.decision_decroche(c, **params)


# ---------------------------------------------------------------------------
# Réglages et décision
# ---------------------------------------------------------------------------

def test_reglages_par_defaut():
    c = ld.reglages_decroche({})
    assert c["actif"] is False and c["mode"] == "delai" and c["delai_s"] == 20
    assert c["duree_max_s"] == 300 and c["silence_s"] == 20 and c["max_simultanes"] == 2
    assert c["accueil"].startswith("Bonjour, ici Liluvine") and c["resume_proprio"] and c["transfert_actif"]
    assert c["lignes"] == [] and c["jours"] == [1, 2, 3, 4, 5, 6]
    # Valeurs hors bornes ramenées dans les limites, mode inconnu → délai
    c = ld.reglages_decroche({"liluvine_decroche_delai_s": 500, "liluvine_decroche_mode": "x",
                              "liluvine_decroche_max_simultanes": 0})
    assert c["delai_s"] == 45 and c["mode"] == "delai" and c["max_simultanes"] == 1


def test_decision_desactive_ligne_exclusions():
    assert decider(ld.reglages_decroche({}))["decrocher"] is False
    c = cfg(lignes=["PN-VIP"])
    assert decider(c)["raison"] == "ligne non concernée"
    assert decider(c, ligne_cle="PN-VIP")["decrocher"] is True
    assert decider(cfg(exclus="+226 70 00 00 01"))["raison"] == "numéro exclu"
    assert "fiche contact" in decider(cfg(), contact={"liluvine_decroche": False})["raison"]


def test_decision_modes():
    # Toujours : tout de suite
    d = decider(cfg(mode="toujours"))
    assert d["decrocher"] and d["delai_s"] == 0
    # Délai : après N secondes (le portail sonne pendant ce temps)
    d = decider(cfg(mode="delai", delai_s=12))
    assert d["decrocher"] and d["delai_s"] == 12
    # Hors heures d'ouverture (08:00–18:00, lundi–samedi par défaut)
    c = cfg(mode="hors_heures")
    assert decider(c, maintenant=EN_JOURNEE)["decrocher"] is False
    assert decider(c, maintenant=LA_NUIT)["decrocher"] is True
    assert decider(c, maintenant=DIMANCHE)["decrocher"] is True
    # Plage qui passe minuit (ouverture de nuit 20:00–06:00)
    c = cfg(mode="hors_heures", ouverture_debut="20:00", ouverture_fin="06:00", jours="1,2,3,4,5,6,7")
    assert decider(c, maintenant=LA_NUIT)["decrocher"] is False
    assert decider(c, maintenant=EN_JOURNEE)["decrocher"] is True


def test_decision_limite_simultanes():
    c = cfg(mode="toujours", max_simultanes=2)
    assert decider(c, actifs=1)["decrocher"] is True
    d = decider(c, actifs=2)
    assert d["decrocher"] is False and "limite 2" in d["raison"]


# ---------------------------------------------------------------------------
# Prise de l'appel : jamais deux décrochés
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    base = mongomock_motor.AsyncMongoMockClient()["sawali_lot69"]
    lancer(base.settings.insert_one({"_id": "global", "wa_phone_number_id": "PN-STANDARD",
                                     "wa_access_token": "jeton-factice"}))
    lancer(base.users.insert_one({"id": "sawali", "role": "superviseur"}))
    return base


def _appel_qui_sonne(db, call_id="wacid.1"):
    """Webhook « connect » d'un appel entrant (lot 60)."""
    lancer(aw.traiter_webhook_appels(db, {
        "metadata": {"phone_number_id": "PN-STANDARD"},
        "calls": [{"id": call_id, "event": "connect", "from": APPELANT, "session": {"sdp": "v=0 offre"}}]}))


def test_humain_deja_decroche_liluvine_s_efface(db):
    _appel_qui_sonne(db)
    # Un agent décroche dans le portail (même mise à jour conditionnelle que le bouton « Décrocher »)
    lancer(db.wa_appels.update_one({"id": "wacid.1", "statut": "sonne"},
                                   {"$set": {"statut": "decroche", "agent_id": "u1"}}))
    assert lancer(ld.prendre_appel(db, "wacid.1")) is False
    doc = lancer(db.wa_appels.find_one({"id": "wacid.1"}))
    assert doc["agent_id"] == "u1" and doc.get("repondu_par") is None


def test_liluvine_prend_puis_humain_refuse(db):
    _appel_qui_sonne(db)
    assert lancer(ld.prendre_appel(db, "wacid.1")) is True
    doc = lancer(db.wa_appels.find_one({"id": "wacid.1"}))
    assert doc["statut"] == "decroche" and doc["repondu_par"] == "Liluvine" and doc["agent_id"] is None
    # Le bouton « Décrocher » d'un humain ne trouve plus l'appel « sonne »
    r = lancer(db.wa_appels.update_one({"id": "wacid.1", "statut": "sonne"}, {"$set": {"agent_id": "u1"}}))
    assert r.modified_count == 0
    # Une seconde tentative de Liluvine échoue aussi (pas de double décroché)
    assert lancer(ld.prendre_appel(db, "wacid.1")) is False


def test_webhook_planifie_selon_reglages(db, monkeypatch):
    lances = []

    async def faux_decrocher(db_, call_id, attendre_s=0):
        lances.append((call_id, attendre_s))
        return {}
    monkeypatch.setattr(ld, "decrocher_et_converser", faux_decrocher)
    monkeypatch.setattr(ld, "_maintenant", lambda: EN_JOURNEE)

    async def scenario():
        # Désactivé : rien n'est lancé
        await aw.traiter_webhook_appels(db, {"metadata": {"phone_number_id": "PN-STANDARD"},
                                             "calls": [{"id": "a1", "event": "connect", "from": APPELANT}]})
        await db.settings.update_one({"_id": "global"}, {"$set": {"liluvine_decroche_actif": True,
                                                                  "liluvine_decroche_delai_s": 15}})
        await aw.traiter_webhook_appels(db, {"metadata": {"phone_number_id": "PN-STANDARD"},
                                             "calls": [{"id": "a2", "event": "connect", "from": APPELANT}]})
        await asyncio.sleep(0.05)
    lancer(scenario())
    assert lances == [("a2", 15)]
    assert lancer(db.wa_appels.find_one({"id": "a2"}))["liluvine_decision"].startswith("si personne")
    ld._actifs.clear()


# ---------------------------------------------------------------------------
# Détection de parole sur du son synthétique
# ---------------------------------------------------------------------------

def _pcm(secondes, amplitude=0, frequence=300, taux=16000):
    """PCM 16 bits mono : sinus (amplitude > 0) ou silence."""
    n = int(taux * secondes)
    return b"".join(struct.pack("<h", int(amplitude * math.sin(2 * math.pi * frequence * i / taux)))
                    for i in range(n))


def test_detecteur_decoupe_les_phrases():
    d = ld.DetecteurParole()
    son = _pcm(0.5) + _pcm(1.0, 8000) + _pcm(1.0) + _pcm(0.6, 8000) + _pcm(1.0)
    phrases = []
    # Ajout par petits morceaux (comme les trames reçues de l'appel)
    for i in range(0, len(son), 1234):
        phrases += d.ajouter(son[i:i + 1234])
    assert len(phrases) == 2
    # Phrase 1 ≈ 1 s de voix + 200 ms avant + 200 ms de silence gardé
    assert 1.1 < ld.duree_pcm_s(phrases[0]) < 1.6
    assert 0.7 < ld.duree_pcm_s(phrases[1]) < 1.2
    assert d.parle is False


def test_detecteur_ignore_bruit_court_et_coupe_les_longues():
    d = ld.DetecteurParole()
    assert d.ajouter(_pcm(0.3) + _pcm(0.1, 8000) + _pcm(1.0)) == []      # clic de 100 ms : ignoré
    d = ld.DetecteurParole(max_ms=2000)
    phrases = d.ajouter(_pcm(0.2) + _pcm(3.0, 8000))
    assert len(phrases) == 1 and ld.duree_pcm_s(phrases[0]) <= 2.3      # phrase trop longue : coupée
    assert d.parle is True                                              # la suite est une nouvelle phrase


def test_wav_et_transcriptions_fantomes():
    wav = ld.wav_16k(_pcm(0.1, 1000))
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and len(wav) == 44 + 3200
    assert ld.transcription_utile("  Bonjour,   je voudrais un rendez-vous ") == "Bonjour, je voudrais un rendez-vous"
    assert ld.transcription_utile("Sous-titres réalisés par la communauté d'Amara.org") == ""
    assert ld.transcription_utile(" . ") == ""


# ---------------------------------------------------------------------------
# Prompt, réponses, journal
# ---------------------------------------------------------------------------

def test_assemblage_du_prompt_et_historique():
    p = ld.assembler_prompt("Tu es Liluvine PRO.", contact_nom="Awa Kaboré", telephone=APPELANT,
                            plateforme="Pharmacie Wend Denda", ligne={"libelle": "Liluvine VIP"},
                            connaissances="[Base] Horaires : 8 h – 18 h", consignes_ligne="Accueil VIP.")
    assert p.startswith("Tu es Liluvine PRO.")
    assert "Tu es AU TÉLÉPHONE" in p and "1 à 2 phrases" in p and "pas d'emojis" in p
    assert ld.MARQUEUR_FIN in p and ld.MARQUEUR_HUMAIN in p
    assert "Awa Kaboré (+22670000001)" in p and "Pharmacie Wend Denda" in p and "Liluvine VIP" in p
    assert "[Base] Horaires" in p and "Accueil VIP." in p
    # Option « transmettre à un humain » désactivée : pas de marqueur [HUMAIN]
    p2 = ld.assembler_prompt("Base", contact_nom=None, telephone=APPELANT, plateforme=None, ligne=None, transfert=False)
    assert ld.MARQUEUR_HUMAIN not in p2 and "inconnu" in p2
    # Historique : l'accueil est retiré (le modèle commence par l'appelant), tours fusionnés
    t = [{"qui": "liluvine", "texte": "Bonjour"}, {"qui": "appelant", "texte": "Allô"},
         {"qui": "appelant", "texte": "vous m'entendez ?"}, {"qui": "liluvine", "texte": "Oui."}]
    assert ld.historique_llm(t) == [{"role": "user", "content": "Allô vous m'entendez ?"},
                                    {"role": "assistant", "content": "Oui."}]


def test_analyse_des_reponses():
    assert ld.analyser_reponse("Avec plaisir, au revoir ! [FIN]") == ("Avec plaisir, au revoir !", "fin")
    assert ld.analyser_reponse("Un conseiller vous rappelle. [HUMAIN]")[1] == "humain"
    assert ld.analyser_reponse("Je transmets. [ESCALATE: litige]")[1] == "humain"
    texte, fin = ld.analyser_reponse("**Bonjour** 😀 voir https://sawali.bf ici")
    assert texte == "Bonjour voir ici" and fin is None
    assert ld.decouper_phrases("Oui. Nous ouvrons à 8 heures. Et nous fermons à 18 heures !") == [
        "Oui. Nous ouvrons à 8 heures.", "Et nous fermons à 18 heures !"]


def test_journal_cout_et_message_proprietaire():
    t = [{"qui": "liluvine", "texte": "Bonjour", "t": 0.4}, {"qui": "appelant", "texte": "Vos horaires ?", "t": 65}]
    assert ld.transcription_texte(t) == "[0:00] Liluvine : Bonjour\n[1:05] Appelant : Vos horaires ?"
    c = ld.estimer_cout({"stt_secondes": 60, "stt_modele": "gpt-4o-mini-transcribe",
                         "tts_caracteres": {"openai": 1000, "google": 500}, "llm_entree": 1_000_000, "llm_sortie": 0})
    assert c == {"devise": "USD", "transcription": 0.003, "voix": 0.015, "ia": 1.0, "meta": 0.0, "total": 1.018}
    m = ld.texte_resume_proprio("Awa", APPELANT, "Demande les horaires.", 95, True)
    assert m.startswith("🤖📞 Liluvine a répondu à Awa (+22670000001) — 1:35") and "humain" in m


# ---------------------------------------------------------------------------
# Routes : droits et contrôles
# ---------------------------------------------------------------------------

def test_routes_reglages_et_simulation(db, monkeypatch):
    utilisateurs = {"sup": {"id": "sawali", "role": "superviseur", "client_id": "sawali", "full_name": "Sup"},
                    "client": {"id": "x", "role": "client", "client_id": "x"}}

    async def utilisateur(request: Request):
        uid = request.headers.get("X-User")
        if uid not in utilisateurs:
            raise HTTPException(status_code=401)
        return utilisateurs[uid]

    vus = {}

    async def faux_llm(systeme, historique, texte):
        vus.update(systeme=systeme, historique=historique, texte=texte)
        return {"texte": "Nous ouvrons à huit heures. [FIN]", "entree": 10, "sortie": 5}
    monkeypatch.setattr(ld, "repondre_llm", faux_llm)

    api = APIRouter(prefix="/api")
    ld.setup_liluvine_decroche_routes(db=db, api=api, get_current_user=utilisateur)
    app = FastAPI()
    app.include_router(api)
    c = TestClient(app)
    assert c.get("/api/admin/liluvine-decroche").status_code == 401
    assert c.get("/api/admin/liluvine-decroche", headers={"X-User": "client"}).status_code == 403
    assert c.put("/api/admin/liluvine-decroche", json={}, headers={"X-User": "client"}).status_code == 403
    r = c.get("/api/admin/liluvine-decroche", headers={"X-User": "sup"}).json()
    assert r["effectif"]["actif"] is False and r["lignes"][0]["cle"] == "principal"
    assert set(r["moteur"]) >= {"disponible", "transcription", "ia", "voix", "en_cours"}
    h = {"X-User": "sup"}
    assert c.put("/api/admin/liluvine-decroche", json={"liluvine_decroche_mode": "jamais"}, headers=h).status_code == 422
    assert c.put("/api/admin/liluvine-decroche", json={"liluvine_decroche_ouverture_debut": "8h"}, headers=h).status_code == 422
    assert c.put("/api/admin/liluvine-decroche", json={"liluvine_decroche_voix": "robot"}, headers=h).status_code == 422
    assert c.put("/api/admin/liluvine-decroche", json={
        "liluvine_decroche_actif": True, "liluvine_decroche_mode": "toujours", "liluvine_decroche_lignes": ["principal"],
        "liluvine_decroche_delai_s": "25", "champ_inconnu": "x"}, headers=h).status_code == 200
    s = lancer(db.settings.find_one({"_id": "global"}))
    assert s["liluvine_decroche_actif"] is True and s["liluvine_decroche_delai_s"] == 25
    assert s["liluvine_decroche_lignes"] == ["principal"] and "champ_inconnu" not in s
    # Simulation écrite : même prompt (consigne téléphone) et marqueur de fin détecté
    assert c.post("/api/admin/liluvine-decroche/simuler", json={"texte": ""}, headers=h).status_code == 400
    r = c.post("/api/admin/liluvine-decroche/simuler", json={"texte": "Vous ouvrez à quelle heure ?"}, headers=h).json()
    assert r["reponse"] == "Nous ouvrons à huit heures." and r["fin"] == "fin"
    assert "Tu es AU TÉLÉPHONE" in vus["systeme"] and vus["texte"] == "Vous ouvrez à quelle heure ?"
    assert len(r["historique"]) == 3


# ---------------------------------------------------------------------------
# Appel complet de bout en bout (deux interlocuteurs aiortc locaux)
# ---------------------------------------------------------------------------

def _wav(secondes, amplitude=12000, frequence=440, taux=16000):
    """Petit fichier WAV (sinus) : voix simulée."""
    pcm = _pcm(secondes, amplitude, frequence, taux)
    entete = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, taux, taux * 2, 2, 16) + b"data" + struct.pack("<I", len(pcm))
    return entete + pcm


def test_appel_entrant_de_bout_en_bout(monkeypatch):
    pytest.importorskip("aiortc")
    pytest.importorskip("av")
    from aiortc import RTCPeerConnection, RTCSessionDescription

    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot69_e2e"]
    lancer(db.settings.insert_one({"_id": "global", "wa_phone_number_id": "PN-STANDARD",
                                   "wa_access_token": "jeton-factice", "liluvine_decroche_actif": True,
                                   "liluvine_decroche_mode": "toujours", "liluvine_decroche_silence_s": 8,
                                   "appel_proprio_numeros": "+226 70 99 99 99"}))
    lancer(db.users.insert_one({"id": "sawali", "role": "superviseur", "company": "SAWALI"}))
    lancer(db.directory_contacts.insert_one({"id": "c1", "client_id": "sawali", "name": "Awa Kaboré",
                                             "whatsapp": f"+{APPELANT}"}))
    monkeypatch.setattr(ap, "serveurs_ice", lambda: [])          # pas de STUN : tout reste local
    monkeypatch.setenv("OPENAI_API_KEY", "cle-factice")          # transcription « disponible » (simulée)
    ld._actifs.clear()

    # Voix, transcription, IA et résumé simulés (aucun réseau)
    voix_dites = []

    async def fausse_voix(texte, s, cfg):
        voix_dites.append(texte)
        return ap.decoder_pcm(_wav(0.5, 9000, 660)), "openai"
    monkeypatch.setattr(ld, "synthese_vocale", fausse_voix)
    transcriptions = []

    async def faux_stt(wav, s, cfg):
        transcriptions.append(len(wav))
        return "Bonjour, quels sont vos horaires ?", "gpt-4o-mini-transcribe"
    monkeypatch.setattr(ld, "transcrire", faux_stt)
    prompts = []

    async def faux_llm(systeme, historique, texte):
        prompts.append((systeme, historique, texte))
        if systeme.startswith("Tu résumes"):
            return {"texte": "Awa demande les horaires ; Liluvine a répondu 8 h – 18 h.", "entree": 50, "sortie": 20}
        return {"texte": "Nous sommes ouverts de huit heures à dix-huit heures. Bonne journée ! [FIN]",
                "entree": 900, "sortie": 30}
    monkeypatch.setattr(ld, "repondre_llm", faux_llm)
    actions, messages = [], []
    recu = {"trames": 0, "son": 0}

    async def scenario():
        appelant = RTCPeerConnection()
        # Voix de l'appelant : 1,2 s de « parole » jouée dès que l'appel est connecté
        voix_appelant = ap.creer_piste(ap.decoder_pcm(_wav(1.2)), repetitions=1, pause_s=0.1)
        appelant.addTrack(voix_appelant)

        @appelant.on("track")
        def sur_piste(piste):
            async def lire():
                while True:
                    try:
                        trame = await piste.recv()
                    except Exception:  # noqa: BLE001 — fin de l'appel
                        return
                    recu["trames"] += 1
                    if any(bytes(trame.planes[0])[:400]):
                        recu["son"] += 1
            asyncio.ensure_future(lire())

        @appelant.on("connectionstatechange")
        async def sur_etat():
            if appelant.connectionState == "connected":
                await asyncio.sleep(2.5)           # l'appelant écoute l'accueil puis parle
                voix_appelant.lecture()

        await appelant.setLocalDescription(await appelant.createOffer())

        async def faux_post(s, numero_id, chemin, corps):
            if chemin == "messages":
                messages.append(corps)
                return {"ok": True, "donnees": {"messages": [{"id": "wamid.1"}]}, "erreur": None}
            actions.append(corps.get("action"))
            if corps.get("action") == "accept":
                await appelant.setRemoteDescription(RTCSessionDescription(sdp=corps["session"]["sdp"], type="answer"))
            return {"ok": True, "donnees": {"success": True}, "erreur": None}
        monkeypatch.setattr(ap, "_graph_post", faux_post)

        # « Meta » : webhook connect avec l'offre SDP de l'appelant
        await aw.traiter_webhook_appels(db, {
            "metadata": {"phone_number_id": "PN-STANDARD"},
            "calls": [{"id": "wacid.IN", "event": "connect", "from": APPELANT,
                       "session": {"sdp_type": "offer", "sdp": appelant.localDescription.sdp}}]})
        # Attente de la fin de la tâche de Liluvine
        for _ in range(400):
            await asyncio.sleep(0.1)
            if not ld._taches:
                break
        await appelant.close()

    asyncio.run(asyncio.wait_for(scenario(), 60))
    assert actions == ["pre_accept", "accept", "terminate"], actions
    assert transcriptions, "la phrase de l'appelant n'a pas été détectée"
    assert recu["son"] > 10                                        # l'appelant a entendu Liluvine
    assert voix_dites[0].startswith("Bonjour, ici Liluvine")
    systeme, historique, texte = prompts[0]
    assert "Tu es AU TÉLÉPHONE" in systeme and "Awa Kaboré" in systeme and "SAWALI" in systeme
    assert historique == [] and texte == "Bonjour, quels sont vos horaires ?"
    doc = lancer(db.wa_appels.find_one({"id": "wacid.IN"}, {"_id": 0}))
    assert doc["repondu_par"] == "Liluvine" and doc["decroche_par_nom"] == "Liluvine" and doc["statut"] == "termine"
    j = doc["liluvine"]
    assert [t["qui"] for t in j["transcription"]] == ["liluvine", "appelant", "liluvine"]
    assert j["transcription"][2]["texte"] == "Nous sommes ouverts de huit heures à dix-huit heures. Bonne journée !"
    assert j["fin"] == "au revoir" and j["resume"].startswith("Awa demande") and j["tours"] == 1
    assert j["cout"]["meta"] == 0.0 and j["cout"]["ia"] > 0 and j["transfert_humain"] is False
    # Résumé envoyé au propriétaire sur WhatsApp
    assert messages and "Liluvine a répondu à Awa Kaboré" in messages[0]["text"]["body"]
    assert not ld._actifs
