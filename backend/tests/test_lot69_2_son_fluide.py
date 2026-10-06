"""Lot 69.2 — son fluide pendant les appels de Liluvine et voix « accent d'Afrique de l'Ouest ».

Piste audio : cadence (horloge monotone, 960 échantillons, horodatage croissant, recalage après un gel),
silence quand rien n'est à dire, pré-chargement, continuité entre deux phrases (aucune trame de silence),
compteur de manques ; rééchantillonnage 24 kHz → 48 kHz ; silences de début/fin raccourcis ; décodage
hors de la boucle ; boucle média dédiée ; sonde de retard ; appels aux services de voix (OpenAI avec
consigne d'accent, ElevenLabs en PCM) simulés ; routes « voix ElevenLabs » et « Écouter un essai ».
Lancer : cd backend && python -m pytest tests/test_lot69_2_son_fluide.py -q
"""
from __future__ import annotations

import asyncio
import math
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routes.appel_proprietaire as ap  # noqa: E402
import routes.audio_appel as aa  # noqa: E402
import routes.liluvine_decroche as ld  # noqa: E402


def _pcm_sinus(secondes: float, taux: int = 48000, amplitude: int = 8000, frequence: int = 440) -> bytes:
    """Son sinusoïdal PCM 16 bits mono."""
    n = int(secondes * taux)
    return b"".join(struct.pack("<h", int(amplitude * math.sin(2 * math.pi * frequence * i / taux))) for i in range(n))


# ---------------------------------------------------------------------------
# Horloge de la piste
# ---------------------------------------------------------------------------

def test_horloge_monotone_cadence_et_pts():
    t = {"v": 100.0}
    h = aa.Horloge(maintenant=lambda: t["v"])
    assert h.attente() == 0.0 and h.pts == 0                 # première trame : tout de suite
    attentes, pts = [], [h.pts]
    for _ in range(5):
        attentes.append(h.attente())
        pts.append(h.pts)
        t["v"] += aa.DUREE_TRAME_S                            # la trame part à l'heure prévue
    assert all(abs(a - 0.02) < 1e-9 for a in attentes[:1])
    assert pts == [0, 960, 1920, 2880, 3840, 4800]            # +960 échantillons par trame
    assert h.recalages == 0


def test_horloge_recale_apres_un_gel_sans_rafale():
    t = {"v": 0.0}
    h = aa.Horloge(maintenant=lambda: t["v"])
    h.attente()
    t["v"] = 0.5                                              # boucle gelée 500 ms
    assert h.attente() == 0.0
    assert h.recalages == 1
    # L'horodatage a sauté jusqu'au temps réel (≈ 25 trames) : la trame suivante attend de nouveau
    assert h.pts >= 24 * 960
    assert h.attente() > 0.0


def test_horloge_petit_retard_rattrape_sans_recalage():
    t = {"v": 0.0}
    h = aa.Horloge(maintenant=lambda: t["v"])
    h.attente()
    t["v"] = 0.05                                             # 30 ms de retard : on rattrape
    assert h.attente() == 0.0 and h.recalages == 0 and h.pts == 960


# ---------------------------------------------------------------------------
# File PCM : silence, pré-chargement, continuité, manques
# ---------------------------------------------------------------------------

def test_silence_quand_rien_a_dire():
    lec = aa.LecteurVoix()
    for _ in range(10):
        assert lec.prochaine_trame() == b"\x00" * aa.OCTETS_TRAME
    assert lec.sous_alimentations == 0 and not lec.en_lecture


def test_prechargement_puis_continuite_entre_deux_phrases():
    lec = aa.LecteurVoix(prechargement_ms=400)
    lec.debut_reponse()
    phrase1 = b"\x01\x00" * 4800                              # 100 ms : moins que le pré-chargement
    lec.ajouter(phrase1)
    assert lec.prochaine_trame() == b"\x00" * aa.OCTETS_TRAME  # on attend d'avoir 400 ms d'avance
    phrase2 = b"\x02\x00" * (48000 * 2 // 5)                  # 400 ms
    lec.ajouter(phrase2)
    lec.fin_reponse()
    total = (len(phrase1) + len(phrase2)) // aa.OCTETS_TRAME
    trames = [lec.prochaine_trame() for _ in range(total)]
    # Aucune trame de silence entre la phrase 1 et la phrase 2 (concaténées dans la file)
    assert all(any(t) for t in trames)
    assert b"".join(trames) == phrase1 + phrase2
    assert lec.sous_alimentations == 0
    assert lec.prochaine_trame() == b"\x00" * aa.OCTETS_TRAME and not lec.en_lecture


def test_manque_compte_et_reapprovisionnement():
    lec = aa.LecteurVoix(prechargement_ms=0)
    lec.debut_reponse()
    lec.ajouter(b"\x01\x00" * 960)                            # une seule trame, phrase suivante en retard
    assert any(lec.prochaine_trame())
    assert lec.prochaine_trame() == b"\x00" * aa.OCTETS_TRAME  # manque en pleine réponse
    assert lec.sous_alimentations == 1
    # Après un manque, on attend 200 ms d'avance avant de reprendre
    lec.ajouter(b"\x03\x00" * 960 * 5)                        # 100 ms seulement
    assert not any(lec.prochaine_trame())
    assert lec.sous_alimentations == 1                        # attente volontaire ≠ manque
    lec.ajouter(b"\x03\x00" * 960 * 5)
    assert any(lec.prochaine_trame())


def test_fin_de_reponse_courte_jouee_sans_attendre_le_prechargement():
    lec = aa.LecteurVoix(prechargement_ms=400)
    lec.debut_reponse()
    lec.ajouter(b"\x01\x00" * 960 * 3)                        # 60 ms : réponse très courte
    lec.fin_reponse()
    assert any(lec.prochaine_trame())
    assert lec.premier_son is not None


def test_arreter_coupe_immediatement():
    lec = aa.LecteurVoix(prechargement_ms=0)
    lec.debut_reponse()
    lec.ajouter(b"\x01\x00" * 48000)
    lec.prochaine_trame()
    lec.arreter()
    assert not lec.en_lecture and lec.prochaine_trame() == b"\x00" * aa.OCTETS_TRAME


def test_file_protegee_entre_deux_fils():
    """Ajouts depuis un autre fil pendant la lecture : aucun octet perdu ni dupliqué."""
    lec = aa.LecteurVoix(prechargement_ms=0)
    lec.debut_reponse()
    morceau = b"\x05\x00" * 960

    def remplir():
        for _ in range(200):
            lec.ajouter(morceau)
    fil = threading.Thread(target=remplir)
    fil.start()
    lues = 0
    while fil.is_alive() or lec.octets_en_attente():
        if any(lec.prochaine_trame()):
            lues += 1
    fil.join()
    assert lues == 200


# ---------------------------------------------------------------------------
# Piste aiortc : trames de 20 ms, horodatées, cadencées
# ---------------------------------------------------------------------------

def test_piste_trames_960_echantillons_et_cadence():
    pytest.importorskip("aiortc")

    async def scenario():
        piste = aa.creer_piste_voix(prechargement_ms=0)
        piste.debut_reponse()
        piste.ajouter(_pcm_sinus(0.1))
        piste.fin_reponse()
        debut = time.monotonic()
        trames = [await piste.recv() for _ in range(15)]
        return trames, time.monotonic() - debut, piste
    trames, duree, piste = asyncio.run(scenario())
    assert all(t.samples == 960 and t.sample_rate == 48000 and t.format.name == "s16" for t in trames)
    assert [t.pts for t in trames] == [i * 960 for i in range(15)]
    assert str(trames[0].time_base) == "1/48000"
    assert 0.25 <= duree < 0.6                                # 14 intervalles de 20 ms ≈ 280 ms
    assert sum(1 for t in trames if any(bytes(t.planes[0]))) == 5    # 100 ms de son puis silence
    assert piste.mesures()["sous_alimentations"] == 0


# ---------------------------------------------------------------------------
# Préparation du son : 24 kHz → 48 kHz, silences raccourcis, hors de la boucle
# ---------------------------------------------------------------------------

def test_reechantillonnage_24k_vers_48k_longueur_exacte():
    pytest.importorskip("av")
    pcm24 = _pcm_sinus(1.0, taux=24000)
    pcm48 = aa.decoder_pcm(aa.wav_depuis_pcm(pcm24, 24000))
    # 1 s à 48 kHz = 96 000 octets (le rééchantillonneur est vidé : rien n'est perdu)
    assert abs(len(pcm48) - 96000) <= 2 * 64
    assert len(pcm48) % 2 == 0


def test_silences_de_debut_et_fin_raccourcis():
    pytest.importorskip("numpy")
    silence = b"\x00\x00" * 24000                             # 500 ms
    voix = _pcm_sinus(0.3)
    rogne = aa.rogner_silences(silence + voix + silence)
    # On garde 40 ms avant et 140 ms après la voix (± une fenêtre de 10 ms)
    attendu = len(voix) + (48000 * 2 * 180 // 1000)
    assert abs(len(rogne) - attendu) <= 48000 * 2 * 20 // 1000
    assert aa.rogner_silences(silence) == silence             # tout silence : inchangé


def test_decodage_hors_de_la_boucle(monkeypatch):
    """synthese_vocale prépare le son dans un autre fil que celui de la boucle."""
    fils = {}

    async def fausse_synthese(texte, s, cfg):
        return b"audio", "openai"

    def faux_preparer(audio):
        fils["preparation"] = threading.get_ident()
        return b"\x01\x00" * 960
    monkeypatch.setattr(ap, "synthetiser", fausse_synthese)
    monkeypatch.setattr(ap, "preparer_pcm", faux_preparer)

    async def scenario():
        fils["boucle"] = threading.get_ident()
        return await ld.synthese_vocale("Bonjour", {}, {})
    pcm, fournisseur = asyncio.run(scenario())
    assert fournisseur == "openai" and len(pcm) == 1920
    assert fils["preparation"] != fils["boucle"]


# ---------------------------------------------------------------------------
# Boucle média dédiée et sonde de retard
# ---------------------------------------------------------------------------

def test_boucle_media_separee_et_sonde(monkeypatch):
    monkeypatch.setenv("APPEL_BOUCLE_MEDIA", "1")

    async def ou_suis_je():
        return threading.get_ident(), threading.current_thread().name

    async def scenario():
        principal = threading.get_ident()
        fil, nom = await aa.sur_media(ou_suis_je)
        return principal, fil, nom
    principal, fil, nom = asyncio.run(scenario())
    assert fil != principal and nom == "sawali-boucle-media"

    # Sonde : un gel volontaire de 150 ms de la boucle est mesuré
    async def gel():
        sonde = aa.SondeBoucle(0.02)
        tache = asyncio.ensure_future(sonde.tourner())
        await asyncio.sleep(0.05)
        time.sleep(0.15)                                      # blocage volontaire de la boucle
        await asyncio.sleep(0.05)
        sonde.arreter()
        await tache
        return sonde.retard_max_ms
    assert asyncio.run(gel()) >= 100


def test_boucle_media_desactivable(monkeypatch):
    monkeypatch.setenv("APPEL_BOUCLE_MEDIA", "0")

    async def ici():
        return threading.get_ident()

    async def scenario():
        return threading.get_ident(), await aa.sur_media(ici)
    a, b = asyncio.run(scenario())
    assert a == b


# ---------------------------------------------------------------------------
# Voix : OpenAI (consigne d'accent, PCM), ElevenLabs (PCM, modèle flash), réglages
# ---------------------------------------------------------------------------

class _Reponse:
    def __init__(self, code=200, contenu=b"\x01\x00" * 2400, donnees=None):
        self.status_code, self.content, self._d = code, contenu, donnees or {}

    def json(self):
        return self._d


class _FauxClient:
    """Imitation d'httpx.AsyncClient : note les requêtes, renvoie les réponses prévues."""
    requetes: list = []
    reponses: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FauxClient.requetes.append(("POST", url, kw))
        return _FauxClient.reponses.pop(0) if _FauxClient.reponses else _Reponse()

    async def get(self, url, **kw):
        _FauxClient.requetes.append(("GET", url, kw))
        return _FauxClient.reponses.pop(0) if _FauxClient.reponses else _Reponse()


@pytest.fixture
def faux_http(monkeypatch):
    _FauxClient.requetes, _FauxClient.reponses = [], []
    monkeypatch.setattr(ap.httpx, "AsyncClient", _FauxClient)
    monkeypatch.setattr(ld.httpx, "AsyncClient", _FauxClient)
    return _FauxClient


def test_profil_voix_par_defaut_et_lot67():
    p = ap.profil_voix({})
    assert p == {"voix_openai": "nova", "modele_openai": "gpt-4o-mini-tts",
                 "accent": "français d'Afrique de l'Ouest, chaleureux et posé", "modele_elevenlabs": "eleven_flash_v2_5"}
    s = {"liluvine_decroche_voix_openai": "coral", "liluvine_decroche_accent": "burkinabè",
         "liluvine_decroche_voix_elevenlabs": "abcdefgh12"}
    c67 = ap.reglages(s)
    assert c67["voix_openai"] == "coral" and c67["accent"] == "burkinabè" and c67["voix_elevenlabs"] == "abcdefgh12"
    assert ld.reglages_decroche(s)["voix_openai"] == "coral"
    assert ap.profil_voix({"liluvine_decroche_voix_openai": "inconnue"})["voix_openai"] == "nova"


def test_voix_openai_pcm_avec_consigne_accent(faux_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "cle-factice")
    cfg = ap.profil_voix({"liluvine_decroche_voix_openai": "verse"})
    audio = asyncio.run(ap._voix_openai("Bonjour", {}, cfg))
    assert audio[:4] == b"RIFF"                                # PCM 24 kHz emballé en WAV
    _, url, kw = faux_http.requetes[0]
    corps = kw["json"]
    assert url.endswith("/v1/audio/speech")
    assert corps["model"] == "gpt-4o-mini-tts" and corps["voice"] == "verse" and corps["response_format"] == "pcm"
    assert "Afrique de l'Ouest" in corps["instructions"]


def test_voix_openai_repli_tts1_sans_consigne(faux_http, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "cle-factice")
    faux_http.reponses = [_Reponse(400, b""), _Reponse()]
    cfg = ap.profil_voix({"liluvine_decroche_voix_openai": "verse"})
    asyncio.run(ap._voix_openai("Bonjour", {}, cfg))
    second = faux_http.requetes[1][2]["json"]
    assert second["model"] == "tts-1" and second["voice"] == "nova" and "instructions" not in second


def test_voix_elevenlabs_pcm_flash(faux_http, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cle-factice")
    cfg = {**ap.profil_voix({}), "voix_elevenlabs": "abcdefgh12"}
    audio = asyncio.run(ap._voix_elevenlabs("Bonjour", cfg))
    assert audio[:4] == b"RIFF"
    _, url, kw = faux_http.requetes[0]
    assert url.endswith("/v1/text-to-speech/abcdefgh12")
    assert kw["params"] == {"output_format": "pcm_24000"}
    assert kw["json"]["model_id"] == "eleven_flash_v2_5" and kw["json"]["language_code"] == "fr"


def test_listes_de_voix_elevenlabs():
    compte = ld.voix_du_compte({"voices": [{"voice_id": "v1", "name": "Awa", "preview_url": "https://x/a.mp3",
                                            "labels": {"accent": "african", "gender": "female"}}]})
    assert compte[0] == {"voice_id": "v1", "nom": "Awa", "accent": "african", "genre": "female", "langue": None,
                         "description": None, "extrait": "https://x/a.mp3", "categorie": None, "source": "compte"}
    biblio = ld.voix_de_la_bibliotheque({"voices": [{"voice_id": "v2", "public_owner_id": "p9", "name": "Fatou",
                                                     "accent": "west african", "language": "fr"}]})
    assert biblio[0]["proprietaire_id"] == "p9" and biblio[0]["source"] == "bibliotheque"


def test_reglages_essai_prend_le_formulaire():
    cfg = ld.reglages_essai({"liluvine_decroche_voix_openai": "nova"},
                            {"liluvine_decroche_voix_openai": "sage", "liluvine_decroche_voix": "openai",
                             "liluvine_decroche_actif": True})
    assert cfg["voix_openai"] == "sage" and cfg["voix"] == "openai"
    assert cfg["actif"] is False                              # seuls les champs de voix sont repris


def test_routes_voix_et_essai(faux_http, monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    db = mongomock_motor.AsyncMongoMockClient()["sawali_lot69_2"]
    utilisateur = {"u": {"role": "admin", "full_name": "Admin"}}
    app, api = FastAPI(), APIRouter(prefix="/api")
    ld.setup_liluvine_decroche_routes(db=db, api=api, get_current_user=lambda: utilisateur["u"])
    app.include_router(api)
    client = TestClient(app)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "cle-factice")

    # Lecture : choix proposés
    d = client.get("/api/admin/liluvine-decroche").json()
    assert "verse" in d["choix_voix"]["openai"] and d["choix_voix"]["elevenlabs_cle"] is True
    # Enregistrement : contrôles
    assert client.put("/api/admin/liluvine-decroche", json={"liluvine_decroche_voix_openai": "x"}).status_code == 422
    assert client.put("/api/admin/liluvine-decroche", json={"liluvine_decroche_voix_elevenlabs": "a b"}).status_code == 422
    assert client.put("/api/admin/liluvine-decroche", json={
        "liluvine_decroche_voix_openai": "coral", "liluvine_decroche_accent": "accent burkinabè",
        "liluvine_decroche_modele_elevenlabs": "eleven_multilingual_v2"}).status_code == 200
    assert client.get("/api/admin/liluvine-decroche").json()["effectif"]["voix_openai"] == "coral"

    # Bibliothèque : recherche de voix françaises à accent africain (aucune → repli par mots-clés)
    faux_http.reponses = [_Reponse(donnees={"voices": []}),
                          _Reponse(donnees={"voices": [{"voice_id": "v2abcdefg", "public_owner_id": "p9abcdef",
                                                        "name": "Fatou", "accent": "african"}]})]
    r = client.get("/api/admin/liluvine-decroche/voix-elevenlabs", params={"source": "bibliotheque"}).json()
    assert r["voix"][0]["nom"] == "Fatou"
    assert faux_http.requetes[0][2]["params"]["language"] == "fr" and faux_http.requetes[0][2]["params"]["accent"] == "african"
    # Ajout au compte
    faux_http.reponses = [_Reponse(donnees={"voice_id": "nouvelle123"})]
    r = client.post("/api/admin/liluvine-decroche/voix-elevenlabs/ajouter",
                    json={"proprietaire_id": "p9abcdef", "voice_id": "v2abcdefg", "nom": "Liluvine"}).json()
    assert r["voice_id"] == "nouvelle123"
    assert faux_http.requetes[-1][1].endswith("/v1/voices/add/p9abcdef/v2abcdefg")

    # Écouter un essai : le son revient (WAV)
    async def voix(texte, s, cfg):
        assert cfg["voix_openai"] == "sage" and texte == "Bonjour test"
        return ap._wav(b"\x01\x00" * 2400, 24000), "openai"
    monkeypatch.setattr(ap, "synthetiser", voix)
    r = client.post("/api/admin/liluvine-decroche/essai-voix",
                    json={"liluvine_decroche_voix_openai": "sage", "texte": "Bonjour test"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert r.headers["x-voix-fournisseur"] == "openai"
    # Réservé aux administrateurs
    utilisateur["u"] = {"role": "client"}
    assert client.post("/api/admin/liluvine-decroche/essai-voix", json={}).status_code == 403
    assert client.get("/api/admin/liluvine-decroche/voix-elevenlabs").status_code == 403


def test_qualite_audio_resumee():
    class P:
        def mesures(self):
            return {"sous_alimentations": 2, "recalages": 1, "trames_son": 300}
    s1, s2 = aa.SondeBoucle(), aa.SondeBoucle()
    s1.retard_max_ms, s2.retard_max_ms = 812.4, 12.6
    q = ld.qualite_audio(P(), s1, s2, {"premier_son_s": [1.2, 1.8]})
    assert q["sous_alimentations"] == 2 and q["recalages"] == 1 and q["retard_boucle_max_ms"] == 812
    assert q["retard_media_max_ms"] == 13 and q["premier_son_moyen_s"] == 1.5
