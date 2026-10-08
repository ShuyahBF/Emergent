# audio_appel.py — Lot 69.2 : son fluide pendant les appels WhatsApp de Liluvine (lots 67 et 69).
#
# Constat du propriétaire (06/10/2026) : « la voix est de bonne qualité, mais le son est entrecoupé
# de silences ». Causes trouvées et corrigées ici :
#   1. Le serveur Render n'a qu'un processeur et UN SEUL processus qui sert aussi toute l'API et les
#      tâches planifiées. La piste audio WebRTC (une trame de 20 ms toutes les 20 ms) tournait dans la
#      même boucle asyncio : la moindre requête lente de l'API retardait les trames → trous dans le son.
#      → Toute la partie « média » (aiortc : connexion, pistes, encodage Opus) tourne désormais dans
#        une BOUCLE DÉDIÉE, sur son propre fil d'exécution (BoucleMedia), isolée du reste de l'API.
#   2. aiortc encode chaque trame Opus dans le « pool de fils » par défaut de la boucle ; dans la
#      boucle principale ce pool (5 fils sur 1 processeur) est partagé avec ~150 traitements de l'API
#      (PDF, OCR, base…) : une trame pouvait attendre son tour → trou.
#      → La boucle média a son PROPRE pool de 2 fils, réservé à l'encodage.
#   3. L'horloge de la piste utilisait time.time() (heure murale, qui peut sauter) et, après un
#      retard, envoyait toutes les trames en retard d'un coup (rafale que le téléphone jette).
#      → Horloge monotone : début + n × 20 ms ; si la boucle a pris plus de 100 ms de retard, on
#        recale l'horodatage (le téléphone comble le trou) au lieu d'envoyer une rafale.
#   4. Entre deux phrases, la lecture attendait la fin de la phrase précédente avant d'ajouter la
#      suivante (sondage toutes les 50 ms) et chaque phrase MP3 portait ses propres silences de début
#      et de fin (remplissage du codeur + silences du service de voix).
#      → UNE piste persistante avec une file PCM interne protégée par un verrou : chaque phrase est
#        ajoutée dès qu'elle est prête (aucun trou entre deux phrases), les silences de début/fin de
#        chaque phrase sont raccourcis, et la lecture d'une réponse ne démarre qu'avec au moins
#        400 ms de son d'avance (« pré-chargement ») ; après un manque, on se ré-approvisionne.
#   5. Les voix OpenAI / ElevenLabs sont demandées en PCM brut (pas de MP3 à décoder) puis converties
#      UNE fois en 48 kHz mono, hors de la boucle (fil séparé).
#
# Mesures (journal de l'appel, ligne « Qualité audio » du détail) : manques de son pendant une
# réponse, recalages d'horloge, retard maximal des boucles principale et média, délai moyen avant
# le premier son de chaque réponse.
#
# Variable d'environnement facultative : APPEL_BOUCLE_MEDIA=0 pour revenir à l'ancien fonctionnement
# (tout dans la boucle principale) — à n'utiliser qu'en cas de souci.
from __future__ import annotations

import asyncio
import concurrent.futures
import fractions
import io
import logging
import os
import threading
import time
import wave
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("sawali.audio_appel")

# Fréquence WebRTC / Opus (48 kHz), trame de 20 ms = 960 échantillons = 1 920 octets (16 bits mono)
FREQUENCE = 48000
ECHANTILLONS_TRAME = 960
OCTETS_TRAME = ECHANTILLONS_TRAME * 2
DUREE_TRAME_S = ECHANTILLONS_TRAME / FREQUENCE
# Son d'avance exigé avant de commencer une réponse (et après un manque)
PRECHARGEMENT_MS = 400
PRECHARGEMENT_APRES_MANQUE_MS = 200
# Retard au-delà duquel l'horloge de la piste est recalée (au lieu d'envoyer une rafale de trames)
RETARD_RECALAGE_S = 0.10


# ---------------------------------------------------------------------------
# Boucle média dédiée (fil d'exécution séparé)
# ---------------------------------------------------------------------------

def boucle_media_active() -> bool:
    """La boucle média dédiée est-elle utilisée ? (oui par défaut ; APPEL_BOUCLE_MEDIA=0 pour la couper)"""
    return os.environ.get("APPEL_BOUCLE_MEDIA", "1").strip().lower() not in ("0", "non", "false", "off")


class BoucleMedia:
    """Boucle asyncio qui tourne sur son propre fil : y vivent les connexions WebRTC (aiortc), les
    pistes audio et l'encodage Opus. Une requête lente de l'API ne peut donc plus retarder le son."""

    def __init__(self) -> None:
        self._boucle: Optional[asyncio.AbstractEventLoop] = None
        self._fil: Optional[threading.Thread] = None
        self._verrou = threading.Lock()

    def boucle(self) -> asyncio.AbstractEventLoop:
        """Boucle média (démarrée au premier besoin, puis gardée pour tous les appels)."""
        with self._verrou:
            if self._boucle is None or not self._fil or not self._fil.is_alive():
                pret = threading.Event()
                boucle = asyncio.new_event_loop()
                # Pool de fils RÉSERVÉ à l'encodage audio d'aiortc (jamais partagé avec l'API)
                boucle.set_default_executor(concurrent.futures.ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="sawali-media"))

                def tourner() -> None:
                    """Corps du fil : la boucle tourne indéfiniment."""
                    asyncio.set_event_loop(boucle)
                    boucle.call_soon(pret.set)
                    boucle.run_forever()

                self._fil = threading.Thread(target=tourner, name="sawali-boucle-media", daemon=True)
                self._fil.start()
                pret.wait(5)
                self._boucle = boucle
            return self._boucle


_media = BoucleMedia()


async def sur_media(fabrique: Callable[[], Awaitable[Any]]) -> Any:
    """Exécute la coroutine fabriquée par `fabrique()` DANS la boucle média et attend son résultat
    depuis la boucle de l'appelant (sans la bloquer). Sans boucle média : exécution directe."""
    if not boucle_media_active():
        return await fabrique()
    futur = asyncio.run_coroutine_threadsafe(fabrique(), _media.boucle())
    return await asyncio.wrap_future(futur)


def lancer_sur_media(fabrique: Callable[[], Awaitable[Any]]):
    """Lance une coroutine dans la boucle média sans attendre (renvoie un futur)."""
    if not boucle_media_active():
        return asyncio.ensure_future(fabrique())
    return asyncio.run_coroutine_threadsafe(fabrique(), _media.boucle())


# ---------------------------------------------------------------------------
# Sonde de retard d'une boucle asyncio (mesure du « gel » de la boucle)
# ---------------------------------------------------------------------------

class SondeBoucle:
    """Mesure le retard maximal d'une boucle : on demande à dormir 50 ms et on regarde de combien
    le réveil arrive en retard. Un retard de 200 ms = la boucle a été bloquée 200 ms."""

    def __init__(self, intervalle_s: float = 0.05) -> None:
        self.intervalle_s = intervalle_s
        self.retard_max_ms = 0.0
        self._arret = threading.Event()

    async def tourner(self) -> None:
        """Boucle de mesure (s'arrête quand arreter() est appelé)."""
        while not self._arret.is_set():
            avant = time.monotonic()
            await asyncio.sleep(self.intervalle_s)
            retard = (time.monotonic() - avant - self.intervalle_s) * 1000
            if retard > self.retard_max_ms:
                self.retard_max_ms = retard

    def arreter(self) -> None:
        """Arrête la mesure (appelable depuis n'importe quel fil)."""
        self._arret.set()


# ---------------------------------------------------------------------------
# Préparation du son : décodage + 48 kHz mono + raccourcissement des silences (hors boucle)
# ---------------------------------------------------------------------------

def wav_depuis_pcm(pcm: bytes, frequence: int) -> bytes:
    """Emballe du PCM 16 bits mono dans un WAV (aucun calcul : simple en-tête)."""
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(frequence)
        w.writeframes(pcm)
    return tampon.getvalue()


def decoder_pcm(audio: bytes) -> bytes:
    """Décode un fichier audio (WAV, MP3…) en PCM 16 bits mono 48 kHz (bibliothèque av / FFmpeg).
    Le rééchantillonneur est VIDÉ à la fin (resample(None)) pour ne perdre aucun échantillon."""
    import av
    sortie = bytearray()
    with av.open(io.BytesIO(audio)) as conteneur:
        reechantillonneur = av.AudioResampler(format="s16", layout="mono", rate=FREQUENCE)
        for trame in conteneur.decode(audio=0):
            for t in reechantillonneur.resample(trame):
                sortie += bytes(t.planes[0])[: t.samples * 2]
        for t in reechantillonneur.resample(None):
            sortie += bytes(t.planes[0])[: t.samples * 2]
    return bytes(sortie)


def rogner_silences(pcm: bytes, frequence: int = FREQUENCE, seuil: int = 250,
                    garder_debut_ms: int = 40, garder_fin_ms: int = 140) -> bytes:
    """Raccourcit les silences de début et de fin d'une phrase synthétisée (on garde un petit souffle
    naturel) : entre deux phrases, plus de long blanc. Fenêtres de 10 ms, seuil d'amplitude crête."""
    import numpy as np
    ech = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2")
    fen = max(1, frequence // 100)
    n = ech.size // fen
    if n == 0:
        return pcm
    cretes = np.abs(ech[: n * fen].astype(np.int32)).reshape(n, fen).max(axis=1)
    sonores = np.nonzero(cretes > seuil)[0]
    if sonores.size == 0:
        return pcm                                   # tout est silence : on ne touche à rien
    debut = max(0, int(sonores[0]) * fen - frequence * garder_debut_ms // 1000)
    fin = min(ech.size, (int(sonores[-1]) + 1) * fen + frequence * garder_fin_ms // 1000)
    return ech[debut:fin].tobytes()


def preparer_pcm(audio: bytes) -> bytes:
    """Son d'un service de voix → PCM 48 kHz mono prêt à jouer (décodage + silences raccourcis).
    Fonction lente : toujours appelée hors de la boucle (asyncio.to_thread)."""
    return rogner_silences(decoder_pcm(audio))


# ---------------------------------------------------------------------------
# File PCM protégée (alimentée depuis la boucle principale, lue par la boucle média)
# ---------------------------------------------------------------------------

class LecteurVoix:
    """Programme de lecture d'une piste : file PCM + règles de pré-chargement + compteurs.
    Sans aiortc (testable seul). Toutes les méthodes sont protégées par un verrou car la file est
    remplie par la boucle principale et vidée par la boucle média."""

    def __init__(self, prechargement_ms: int = PRECHARGEMENT_MS) -> None:
        self._verrou = threading.Lock()
        self._file = bytearray()
        self.prechargement = FREQUENCE * 2 * prechargement_ms // 1000
        self.prechargement_manque = FREQUENCE * 2 * PRECHARGEMENT_APRES_MANQUE_MS // 1000
        self._seuil = 0                    # son d'avance exigé avant de (re)commencer à jouer
        self._en_reponse = False           # une réponse est en cours (des phrases arrivent encore)
        self._fin_annoncee = True          # toutes les phrases de la réponse ont été ajoutées
        self._attente = False              # on attend le pré-chargement (silence volontaire)
        # Compteurs (qualité audio)
        self.trames_son = 0
        self.trames_silence = 0
        self.sous_alimentations = 0        # trames de silence insérées EN PLEINE réponse (manques)
        self.premier_son: Optional[float] = None   # instant (monotone) du 1er son de la réponse

    # --- commandes (boucle principale) ---
    def debut_reponse(self) -> None:
        """Une nouvelle réponse commence : on attendra le pré-chargement avant de jouer."""
        with self._verrou:
            self._en_reponse, self._fin_annoncee = True, False
            self._attente, self._seuil = True, self.prechargement
            self.premier_son = None

    def ajouter(self, pcm: bytes) -> None:
        """Ajoute une phrase (PCM 48 kHz mono 16 bits) À LA SUITE de la précédente, sans trou."""
        if not pcm:
            return
        with self._verrou:
            self._file.extend(pcm[: len(pcm) // 2 * 2])
            if not self._en_reponse:
                # Ajout hors réponse (lot 67, compatibilité) : on joue tout de suite
                self._en_reponse, self._fin_annoncee, self._attente = True, True, False

    def fin_reponse(self) -> None:
        """Toutes les phrases sont ajoutées : on joue même si le pré-chargement n'est pas atteint."""
        with self._verrou:
            self._fin_annoncee = True

    def arreter(self) -> None:
        """Coupe immédiatement (l'appelant a pris la parole)."""
        with self._verrou:
            self._file.clear()
            self._en_reponse, self._fin_annoncee, self._attente = False, True, False

    @property
    def en_lecture(self) -> bool:
        """Reste-t-il du son à jouer (ou une réponse en cours de fabrication) ?"""
        with self._verrou:
            return bool(self._file) or (self._en_reponse and not self._fin_annoncee)

    def octets_en_attente(self) -> int:
        """Taille de la file (octets)."""
        with self._verrou:
            return len(self._file)

    # --- lecture (boucle média, une fois toutes les 20 ms) ---
    def prochaine_trame(self) -> bytes:
        """Les 20 ms suivantes à envoyer : du son, ou du silence (jamais d'attente)."""
        with self._verrou:
            if self._attente:
                if len(self._file) >= self._seuil or self._fin_annoncee:
                    self._attente = False
                else:
                    self.trames_silence += 1
                    return b"\x00" * OCTETS_TRAME           # pré-chargement : silence volontaire
            if self._file:
                morceau = bytes(self._file[:OCTETS_TRAME]).ljust(OCTETS_TRAME, b"\x00")
                del self._file[:OCTETS_TRAME]
                self.trames_son += 1
                if self.premier_son is None:
                    self.premier_son = time.monotonic()
                return morceau
            self.trames_silence += 1
            if self._en_reponse:
                if self._fin_annoncee:
                    self._en_reponse = False                 # réponse entièrement jouée
                else:
                    # MANQUE : la phrase suivante n'est pas prête → on se ré-approvisionne un peu
                    self.sous_alimentations += 1
                    self._attente, self._seuil = True, self.prechargement_manque
            return b"\x00" * OCTETS_TRAME


class Horloge:
    """Cadence temps réel d'une piste : la trame n part à début + n × 20 ms (horloge monotone).
    Si la boucle a pris plus de 100 ms de retard, l'horodatage est recalé (pas de rafale)."""

    def __init__(self, maintenant: Callable[[], float] = time.monotonic) -> None:
        self._maintenant = maintenant
        self.debut: Optional[float] = None
        self.n = 0                          # numéro de la trame (pts = n × 960)
        self.recalages = 0

    def attente(self) -> float:
        """Passe à la trame suivante ; renvoie le temps à attendre avant de l'envoyer (secondes)."""
        t = self._maintenant()
        if self.debut is None:
            self.debut, self.n = t, 0
            return 0.0
        self.n += 1
        attente = self.debut + self.n * DUREE_TRAME_S - t
        if attente < -RETARD_RECALAGE_S:
            # Retard important (boucle bloquée) : on saute les trames perdues dans l'horodatage
            self.n += int(-attente / DUREE_TRAME_S)
            self.recalages += 1
            return 0.0
        return max(0.0, attente)

    @property
    def pts(self) -> int:
        """Horodatage RTP de la trame courante (en échantillons à 48 kHz)."""
        return self.n * ECHANTILLONS_TRAME


def construire_trame(morceau: bytes, pts: int):
    """Trame audio aiortc : 960 échantillons s16 mono 48 kHz, horodatée (time_base = 1/48000)."""
    import av
    trame = av.AudioFrame(format="s16", layout="mono", samples=ECHANTILLONS_TRAME)
    trame.planes[0].update(morceau)
    trame.pts = pts
    trame.sample_rate = FREQUENCE
    trame.time_base = fractions.Fraction(1, FREQUENCE)
    return trame


def creer_piste_voix(prechargement_ms: int = PRECHARGEMENT_MS):
    """Piste audio WebRTC PERSISTANTE de Liluvine (une seule pour tout l'appel) : silence continu,
    sauf quand on lui ajoute des phrases. À créer dans la boucle qui fera tourner la connexion."""
    from aiortc import MediaStreamTrack
    from aiortc.mediastreams import MediaStreamError

    class PisteVoix(MediaStreamTrack):
        """Une trame de 20 ms toutes les 20 ms, jamais bloquée par la synthèse vocale."""
        kind = "audio"

        def __init__(self) -> None:
            super().__init__()
            self.lecteur = LecteurVoix(prechargement_ms)
            self.horloge = Horloge()

        # Raccourcis vers le lecteur (appelables depuis la boucle principale)
        def debut_reponse(self) -> None:
            self.lecteur.debut_reponse()

        def ajouter(self, pcm: bytes) -> None:
            self.lecteur.ajouter(pcm)

        def jouer(self, pcm: bytes) -> None:
            """Compatibilité lot 69 : jouer = ajouter à la suite."""
            self.lecteur.ajouter(pcm)

        def fin_reponse(self) -> None:
            self.lecteur.fin_reponse()

        def arreter(self) -> None:
            self.lecteur.arreter()

        @property
        def en_lecture(self) -> bool:
            return self.lecteur.en_lecture

        @property
        def trames_jouees(self) -> int:
            return self.lecteur.trames_son

        def mesures(self) -> Dict[str, Any]:
            """Compteurs de qualité de la piste."""
            return {"sous_alimentations": self.lecteur.sous_alimentations,
                    "recalages": self.horloge.recalages, "trames_son": self.lecteur.trames_son}

        async def recv(self):
            if self.readyState != "live":
                raise MediaStreamError
            # Cadence temps réel (horloge monotone), puis 20 ms de son ou de silence
            attente = self.horloge.attente()
            if attente > 0:
                await asyncio.sleep(attente)
            return construire_trame(self.lecteur.prochaine_trame(), self.horloge.pts)

    return PisteVoix()


# ---------------------------------------------------------------------------
# Lot 79.7 — mesure du son RÉELLEMENT transmis pendant un appel (diagnostic « je décroche et elle ne dit rien »)
# ---------------------------------------------------------------------------
async def mesures_rtp(pc) -> dict:
    """(boucle média) Paquets audio envoyés / reçus et état de la connexion d'un appel WebRTC.
    → {"etat", "ice", "envoyes", "octets_envoyes", "recus", "octets_recus"} (jamais d'exception)."""
    mesures = {"etat": getattr(pc, "connectionState", None), "ice": getattr(pc, "iceConnectionState", None),
               "envoyes": 0, "octets_envoyes": 0, "recus": 0, "octets_recus": 0}
    try:
        rapport = await pc.getStats()
        for stat in rapport.values():
            if getattr(stat, "type", "") == "outbound-rtp":
                mesures["envoyes"] += int(getattr(stat, "packetsSent", 0) or 0)
                mesures["octets_envoyes"] += int(getattr(stat, "bytesSent", 0) or 0)
            elif getattr(stat, "type", "") == "inbound-rtp":
                mesures["recus"] += int(getattr(stat, "packetsReceived", 0) or 0)
                mesures["octets_recus"] += int(getattr(stat, "bytesReceived", 0) or 0)
    except Exception as exc:  # noqa: BLE001 — la mesure ne doit jamais gêner la fin d'appel
        mesures["erreur"] = type(exc).__name__
    return mesures


async def fermer_avec_mesures(pc, etiquette: str) -> dict:
    """(boucle média) Écrit au journal le son transmis pendant l'appel, puis ferme la connexion.
    Lecture du journal : « envoyés 0 » = le serveur n'a rien émis ; « envoyés > 0, reçus 0 » = le son part
    mais rien ne revient (réseau / TURN) ; les deux > 0 = le transport audio fonctionne."""
    mesures = await mesures_rtp(pc)
    logger.info("[appel-audio] %s : connexion=%s ice=%s · envoyés %s paquets (%s octets) · reçus %s paquets (%s octets)%s",
                etiquette, mesures["etat"], mesures["ice"], mesures["envoyes"], mesures["octets_envoyes"],
                mesures["recus"], mesures["octets_recus"],
                f" · mesure impossible ({mesures['erreur']})" if mesures.get("erreur") else "")
    try:
        await pc.close()
    except Exception:  # noqa: BLE001
        pass
    return mesures
