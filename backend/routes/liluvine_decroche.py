# liluvine_decroche.py — Lot 69 : Liluvine décroche les appels WhatsApp et répond avec son prompt système.
#
# Principe (le SERVEUR est l'interlocuteur WebRTC, comme pour l'appel au propriétaire du lot 67) :
#   1. Meta envoie au webhook « calls » un évènement « connect » (appel ENTRANT) avec une offre SDP ;
#      le lot 60 l'inscrit dans db.wa_appels (statut « sonne ») et la sonnerie s'affiche dans le portail.
#   2. Ce module décide (réglages) si Liluvine doit décrocher :
#        - « toujours »              : tout de suite ;
#        - « délai »                 : si personne n'a décroché dans le portail après N secondes ;
#        - « hors heures d'ouverture » : tout de suite en dehors des heures d'ouverture, jamais pendant.
#      La prise de l'appel est ATOMIQUE (mise à jour conditionnelle « statut = sonne »), exactement comme
#      le bouton « Décrocher » du portail : le premier qui décroche (humain ou Liluvine) prend l'appel,
#      jamais les deux.
#   3. Moteur d'appel (tâche d'arrière-plan, le webhook n'attend jamais) :
#        réponse SDP du serveur (aiortc) → pre_accept + accept chez Meta → message d'accueil →
#        boucle de conversation :
#          son de l'appelant → détection de parole (énergie, fin de phrase après ~700 ms de silence) →
#          transcription (OpenAI) → réponse de Liluvine (même prompt système que l'auto-réponse
#          WhatsApp + consigne « tu es au téléphone ») → voix (OpenAI → ElevenLabs → Google, lot 67) →
#          lecture dans l'appel (l'appelant peut couper la parole à Liluvine).
#        Fin : durée maximale, silence prolongé, l'appelant raccroche, ou Liluvine conclut (« au revoir »)
#        ou transmet à un humain (tâche de rappel + message au propriétaire).
#   4. Journal : la ligne de l'appel (db.wa_appels) reçoit « répondu par Liluvine », la transcription
#      complète horodatée, un résumé (1 à 3 lignes) et une estimation du coût ; le résumé peut être
#      envoyé au propriétaire sur WhatsApp.
#
# Réglages (Administration → Paramètres → « 🤖📞 Liluvine décroche les appels WhatsApp ») dans
# db.settings {_id: "global"}, préfixe liluvine_decroche_ (aucun secret) — voir CHAMPS plus bas.
# Clés (variables d'environnement saisies par le propriétaire sur Render, jamais dans le code) :
#   OPENAI_API_KEY      : transcription de la voix de l'appelant (INDISPENSABLE pour converser) et voix ;
#   ANTHROPIC_API_KEY   : réponses de Liluvine (même clé que l'auto-réponse WhatsApp) ;
#   ELEVENLABS_API_KEY  : voix facultative ; APPEL_TURN_* : serveur TURN facultatif (lot 67).
# Sans clé OpenAI : Liluvine décroche, dit son accueil, explique qu'elle ne peut pas encore comprendre
# la voix sur cette ligne, crée une demande de rappel et raccroche poliment.
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import time
import uuid
import wave
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

import routes.appel_proprietaire as ap

logger = logging.getLogger("sawali.liluvine_decroche")

# Nom inscrit au journal pour un appel pris par Liluvine
NOM_LILUVINE = "Liluvine"
# Motif inscrit au journal des appels
MOTIF = "Liluvine décroche"
# Modèle de langage utilisé au téléphone (rapide) — même famille que l'auto-réponse WhatsApp
MODELE_LLM = "claude-haiku-4-5-20251001"
# Fréquence de travail de la détection de parole et de la transcription (16 kHz mono)
FREQ_ANALYSE = 16000
# Accueil par défaut
ACCUEIL_DEFAUT = "Bonjour, ici Liluvine, l'assistante de SAWALI. Comment puis-je vous aider ?"
# Modes de décroché
MODES = ("toujours", "delai", "hors_heures")
# Modèles de transcription proposés (OpenAI)
MODELES_STT = ("gpt-4o-mini-transcribe", "whisper-1")
# Marqueurs que le modèle ajoute à la fin de sa réponse (retirés avant la voix)
MARQUEUR_FIN = "[FIN]"
MARQUEUR_HUMAIN = "[HUMAIN]"

# Lot 70 — règles de style ORAL communes aux appels entrants et sortants (retour d'un vrai appel :
# Liluvine avait répondu par une liste numérotée et redit « Bonjour » après l'accueil)
STYLE_ORAL = (
    "- JAMAIS de liste, de numérotation (« 1. », « 2) »), de tirets, de puces ni d'énumération entre "
    "parenthèses : si tu proposes des choix, dis-les dans une phrase (« plutôt un rendez-vous ou le support ? »).\n"
    "- Ne salue JAMAIS une seconde fois : l'accueil (« Bonjour ») a déjà été dit, va droit au but.\n"
    "- Pose UNE seule question à la fois, en phrases courtes, puis attends la réponse.\n"
)
# Consigne ajoutée au prompt système de Liluvine pendant un appel
CONSIGNE_TELEPHONE = (
    "\n\n[IMPORTANT — Tu es AU TÉLÉPHONE (appel WhatsApp entrant)]\n"
    "- Tu parles à voix haute : réponses courtes, 1 à 2 phrases, ton chaleureux et naturel.\n"
    "- Pas de listes, pas de puces, pas d'emojis, pas de liens, pas de markdown, pas d'abréviations "
    "difficiles à prononcer ; écris les nombres comme on les dit.\n"
    + STYLE_ORAL +
    "- Si la transcription semble incomplète ou incompréhensible, demande poliment de répéter.\n"
    "- Quand la conversation est terminée (la personne dit au revoir, remercie sans autre question), "
    f"dis au revoir en une phrase et termine ta réponse par {MARQUEUR_FIN}.\n"
    "- N'invente jamais d'informations ; ne donne aucune donnée confidentielle."
)
# Consigne « transmettre à un humain » (option activée) ou repli (option désactivée)
CONSIGNE_HUMAIN = (
    "\n- Si la personne demande à parler à un humain, à un conseiller ou au responsable, ou si tu ne peux "
    "pas l'aider (litige, paiement, urgence), dis-lui qu'un conseiller va la rappeler très vite, dis au "
    f"revoir et termine ta réponse par {MARQUEUR_HUMAIN}."
)
CONSIGNE_SANS_HUMAIN = (
    "\n- Si la personne demande à parler à un humain, explique-lui gentiment qu'elle peut écrire sur ce "
    "même numéro WhatsApp ou rappeler pendant les heures d'ouverture."
)
# Phrases dites dans les cas particuliers (sans passer par le modèle)
TEXTE_SANS_STT = ("Je suis désolée, je ne peux pas encore comprendre les messages vocaux sur cette ligne. "
                  "Je préviens l'équipe, qui vous rappellera très vite. Au revoir.")
TEXTE_SILENCE = "Je ne vous entends plus. N'hésitez pas à rappeler ou à nous écrire sur WhatsApp. Au revoir."
TEXTE_DUREE_MAX = ("Le temps de cet appel est écoulé. Je transmets votre demande à l'équipe, "
                   "et vous pouvez aussi nous écrire sur WhatsApp. Au revoir.")
TEXTE_ERREUR = "Je rencontre un petit souci technique. Un conseiller va vous rappeler. Au revoir."
TEXTE_REPETER = "Pardon, je n'ai pas bien compris. Pouvez-vous répéter ?"
# Transcriptions fantômes connues (le modèle de transcription « entend » ces phrases dans le bruit)
TRANSCRIPTIONS_FANTOMES = (
    "sous-titres réalisés par la communauté d'amara.org", "sous-titrage st' 501", "merci d'avoir regardé",
    "abonnez-vous", "sous-titres par", "♪",
)

# Tarifs publics indicatifs (USD) servant à l'ESTIMATION du coût d'un appel (affichage seulement) :
# transcription à la minute, voix OpenAI pour 1 000 caractères, modèle Claude Haiku par million de jetons.
TARIF_STT_MINUTE = {"gpt-4o-mini-transcribe": 0.003, "whisper-1": 0.006}
TARIF_TTS_1000 = {"openai": 0.015, "elevenlabs": 0.18, "google": 0.0}
TARIF_LLM_MILLION = {"entree": 1.0, "sortie": 5.0}

# Appels de Liluvine en cours (réservations comprises) — limite « appels simultanés »
_actifs: set = set()
# Tâches d'arrière-plan (référence gardée, sinon Python peut les supprimer)
_taches: set = set()


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def _liste_lignes(valeur: Any) -> List[str]:
    """Lignes concernées : liste de clés (« principal » ou Phone Number ID) ; vide = toutes les lignes."""
    if isinstance(valeur, str):
        valeur = re.split(r"[,;\s]+", valeur)
    return [str(v).strip() for v in (valeur or []) if str(v).strip()]


def _jours(valeur: Any) -> List[int]:
    """Jours d'ouverture (1 = lundi … 7 = dimanche), défaut du lundi au samedi."""
    if isinstance(valeur, list):
        valeur = ",".join(str(v) for v in valeur)
    jours = sorted({int(j) for j in re.findall(r"[1-7]", str(valeur or ""))})
    return jours or [1, 2, 3, 4, 5, 6]


def reglages_decroche(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages du décroché automatique, complétés par les valeurs par défaut."""
    s = s or {}
    exclus_brut = s.get("liluvine_decroche_exclus") or ""
    if isinstance(exclus_brut, list):
        exclus_brut = ",".join(str(x) for x in exclus_brut)
    mode = str(s.get("liluvine_decroche_mode") or "delai").strip()
    stt = str(s.get("liluvine_decroche_stt_modele") or MODELES_STT[0]).strip()
    return {
        # Désactivé par défaut : le propriétaire l'active explicitement
        "actif": bool(s.get("liluvine_decroche_actif")),
        "lignes": _liste_lignes(s.get("liluvine_decroche_lignes")),
        "mode": mode if mode in MODES else "delai",
        "delai_s": ap._entier(s.get("liluvine_decroche_delai_s"), 20, 5, 45),
        "ouverture_debut": s.get("liluvine_decroche_ouverture_debut") or s.get("business_open_time") or "08:00",
        "ouverture_fin": s.get("liluvine_decroche_ouverture_fin") or s.get("business_close_time") or "18:00",
        "jours": _jours(s.get("liluvine_decroche_jours")),
        "accueil": (s.get("liluvine_decroche_accueil") or "").strip() or ACCUEIL_DEFAUT,
        "duree_max_s": ap._entier(s.get("liluvine_decroche_duree_max_min"), 5, 1, 30) * 60,
        "silence_s": ap._entier(s.get("liluvine_decroche_silence_s"), 20, 5, 120),
        "voix": (s.get("liluvine_decroche_voix") or "auto").strip() or "auto",
        "voix_elevenlabs": (s.get("liluvine_decroche_voix_elevenlabs") or s.get("appel_proprio_voix_elevenlabs")
                            or "").strip(),
        "transfert_actif": s.get("liluvine_decroche_transfert_actif") is not False,
        "resume_proprio": s.get("liluvine_decroche_resume_proprio") is not False,
        "max_simultanes": ap._entier(s.get("liluvine_decroche_max_simultanes"), 2, 1, 5),
        "coupure_parole": s.get("liluvine_decroche_coupure_parole") is not False,
        "stt_modele": stt if stt in MODELES_STT else MODELES_STT[0],
        "exclus": {ap._chiffres(x)[-8:] for x in re.split(r"[,;\n]+", exclus_brut) if len(ap._chiffres(x)) >= 8},
        "langue": "fr",
        # Lot 69.2 — voix et modèle OpenAI, consigne d'accent, modèle ElevenLabs (communs avec le lot 67)
        **ap.profil_voix(s),
    }


def pendant_ouverture(cfg: Dict[str, Any], dt: datetime) -> bool:
    """Vrai si l'instant (heure de Ouagadougou) tombe pendant les heures et jours d'ouverture."""
    d = ap._local(dt)
    if d.isoweekday() not in cfg["jours"]:
        return False
    debut = ap._heure_minutes(cfg.get("ouverture_debut"), "08:00")
    fin = ap._heure_minutes(cfg.get("ouverture_fin"), "18:00")
    m = d.hour * 60 + d.minute
    if debut == fin:
        return True                         # plage vide : considéré « toujours ouvert »
    if debut < fin:
        return debut <= m < fin
    return m >= debut or m < fin           # plage qui passe minuit


def decision_decroche(cfg: Dict[str, Any], *, ligne_cle: Optional[str], telephone: str,
                      contact: Optional[Dict[str, Any]], maintenant: datetime, actifs: int) -> Dict[str, Any]:
    """Liluvine doit-elle décrocher cet appel ? → {decrocher, delai_s, raison} (fonction pure, testée)."""
    non = lambda raison: {"decrocher": False, "delai_s": 0, "raison": raison}  # noqa: E731
    if not cfg["actif"]:
        return non("décroché automatique désactivé")
    if cfg["lignes"] and (ligne_cle or "principal") not in cfg["lignes"]:
        return non("ligne non concernée")
    if ap._chiffres(telephone)[-8:] in cfg["exclus"]:
        return non("numéro exclu")
    if (contact or {}).get("liluvine_decroche") is False:
        return non("fiche contact : Liluvine ne décroche pas")
    if actifs >= cfg["max_simultanes"]:
        return non(f"déjà {actifs} appel(s) en cours avec Liluvine (limite {cfg['max_simultanes']})")
    if cfg["mode"] == "toujours":
        return {"decrocher": True, "delai_s": 0, "raison": "mode « toujours »"}
    if cfg["mode"] == "hors_heures":
        if pendant_ouverture(cfg, maintenant):
            return non("heures d'ouverture : l'équipe répond")
        return {"decrocher": True, "delai_s": 0, "raison": "hors heures d'ouverture"}
    return {"decrocher": True, "delai_s": cfg["delai_s"],
            "raison": f"si personne ne décroche après {cfg['delai_s']} s"}


# ---------------------------------------------------------------------------
# Détection de parole (énergie) : découpe le son de l'appelant en phrases
# ---------------------------------------------------------------------------

class DetecteurParole:
    """Détection de parole par l'énergie du signal (PCM 16 bits mono 16 kHz, trames de 20 ms).

    - le seuil s'adapte au bruit de fond (moyenne glissante pendant les silences) ;
    - une phrase COMMENCE après 60 ms de son au-dessus du seuil (on garde 200 ms avant, pour ne
      pas couper la première syllabe) ;
    - elle FINIT après `silence_fin_ms` de silence (700 ms par défaut) ou au bout de `max_ms` ;
    - une phrase trop courte (toux, clic) est ignorée.
    `ajouter(pcm)` renvoie la liste des phrases terminées (octets PCM)."""

    def __init__(self, frequence: int = FREQ_ANALYSE, seuil_min: float = 450.0, facteur: float = 3.0,
                 silence_fin_ms: int = 700, parole_min_ms: int = 250, max_ms: int = 15000):
        self.frequence = frequence
        self.octets_trame = frequence // 50 * 2          # 20 ms en 16 bits
        self.seuil_min = seuil_min
        self.facteur = facteur
        self.trames_fin = max(1, silence_fin_ms // 20)
        self.trames_min = max(1, parole_min_ms // 20)
        self.trames_max = max(10, max_ms // 20)
        self.bruit = seuil_min / facteur                 # estimation initiale du bruit de fond
        self._reste = b""
        self._avant: List[bytes] = []                    # 200 ms précédant la parole
        self._phrase: List[bytes] = []
        self._voix_consecutives = 0
        self._silences = 0
        self._trames_voix = 0
        self.parle = False                               # une phrase est en cours (coupure de parole)
        self.debut_parole: Optional[float] = None        # instant (monotone) du début de la phrase

    @staticmethod
    def energie(trame: bytes) -> float:
        """Énergie (RMS) d'une trame PCM 16 bits."""
        import numpy as np
        echantillons = np.frombuffer(trame, dtype="<i2").astype(np.float64)
        if echantillons.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(echantillons * echantillons)))

    def seuil(self) -> float:
        """Seuil de parole actuel (bruit de fond × facteur, jamais sous le minimum)."""
        return max(self.seuil_min, self.bruit * self.facteur)

    def ajouter(self, pcm: bytes) -> List[bytes]:
        """Ajoute du son ; renvoie les phrases terminées."""
        phrases: List[bytes] = []
        donnees = self._reste + pcm
        n = len(donnees) // self.octets_trame * self.octets_trame
        self._reste = donnees[n:]
        for i in range(0, n, self.octets_trame):
            fin = self._trame(donnees[i:i + self.octets_trame])
            if fin:
                phrases.append(fin)
        return phrases

    def _trame(self, trame: bytes) -> Optional[bytes]:
        """Traite une trame de 20 ms ; renvoie une phrase si elle vient de se terminer."""
        e = self.energie(trame)
        voix = e > self.seuil()
        if not self.parle:
            # Silence : mise à jour du bruit de fond, mémoire des 200 ms précédentes
            if not voix:
                self.bruit = 0.95 * self.bruit + 0.05 * e
            self._avant = (self._avant + [trame])[-10:]
            self._voix_consecutives = self._voix_consecutives + 1 if voix else 0
            if self._voix_consecutives >= 3:
                self.parle = True
                self.debut_parole = time.monotonic()
                self._phrase = list(self._avant)
                self._trames_voix = self._voix_consecutives
                self._silences = 0
            return None
        # Phrase en cours
        self._phrase.append(trame)
        if voix:
            self._trames_voix += 1
            self._silences = 0
        else:
            self._silences += 1
        if self._silences >= self.trames_fin or len(self._phrase) >= self.trames_max:
            return self._terminer()
        return None

    def _terminer(self) -> Optional[bytes]:
        """Clôt la phrase en cours (ignorée si trop courte) ; garde 200 ms de silence final."""
        phrase, voix = self._phrase, self._trames_voix
        if self._silences > 10:
            phrase = phrase[: len(phrase) - (self._silences - 10)]
        self.parle, self.debut_parole = False, None
        self._phrase, self._avant = [], []
        self._voix_consecutives = self._silences = self._trames_voix = 0
        if voix < self.trames_min:
            return None
        return b"".join(phrase)


def wav_16k(pcm: bytes, frequence: int = FREQ_ANALYSE) -> bytes:
    """Emballe du PCM 16 bits mono dans un fichier WAV (envoyé au service de transcription)."""
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(frequence)
        w.writeframes(pcm)
    return tampon.getvalue()


def duree_pcm_s(pcm: bytes, frequence: int = FREQ_ANALYSE) -> float:
    """Durée (secondes) d'un PCM 16 bits mono."""
    return len(pcm) / (frequence * 2)


# ---------------------------------------------------------------------------
# Transcription (OpenAI), réponse de Liluvine (LLM), voix (lot 67)
# Fonctions isolées : remplacées par des imitations dans les tests.
# ---------------------------------------------------------------------------

def cle_openai(s: Dict[str, Any]) -> str:
    """Clé OpenAI : réglage (ancien) ou variable d'environnement OPENAI_API_KEY (même règle que la voix)."""
    return (s.get("openai_api_key") or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def transcription_utile(texte: str) -> str:
    """Nettoie une transcription ; "" si elle est vide ou « fantôme » (bruit interprété comme du texte)."""
    t = re.sub(r"\s+", " ", texte or "").strip()
    bas = t.lower()
    if len(re.sub(r"[\W_]+", "", bas)) < 2:
        return ""
    if any(f in bas for f in TRANSCRIPTIONS_FANTOMES):
        return ""
    return t


async def transcrire(wav: bytes, s: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[str, str]:
    """Transcrit une phrase de l'appelant → (texte, modèle). Lève RuntimeError si impossible."""
    cle = cle_openai(s)
    if not cle:
        raise RuntimeError("clé OpenAI absente")
    modeles = [cfg["stt_modele"]] + [m for m in MODELES_STT if m != cfg["stt_modele"]]
    erreur = ""
    async with httpx.AsyncClient(timeout=20) as http:
        for modele in modeles:
            r = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                data={"model": modele, "language": cfg.get("langue") or "fr", "response_format": "json",
                      "prompt": "Appel téléphonique en français avec SAWALI, l'assistante s'appelle Liluvine."},
                files={"file": ("phrase.wav", wav, "audio/wav")},
                headers={"Authorization": f"Bearer {cle}"})
            if r.status_code < 300:
                return str((r.json() or {}).get("text") or ""), modele
            erreur = f"OpenAI HTTP {r.status_code}"
    raise RuntimeError(erreur or "transcription impossible")


async def repondre_llm(systeme: str, historique: List[Dict[str, str]], texte: str) -> Dict[str, Any]:
    """Réponse de Liluvine (même chemin que l'auto-réponse WhatsApp : ia_client, Claude Haiku).
    Renvoie {texte, entree, sortie} (jetons consommés)."""
    from ia_client import LlmChat, UserMessage, cle_ia
    if not cle_ia("anthropic"):
        raise RuntimeError("clé ANTHROPIC_API_KEY absente")
    chat = LlmChat(session_id=f"appel-{uuid.uuid4()}", system_message=systeme,
                   initial_messages=historique).with_model("anthropic", MODELE_LLM).with_params(max_tokens=220)
    rep = await asyncio.wait_for(chat.send_message_with_tools(UserMessage(text=texte)), timeout=25)
    return {"texte": rep.content or "", "entree": rep.usage.input_tokens, "sortie": rep.usage.output_tokens}


async def resumer(transcription: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Résumé de l'appel en 1 à 3 lignes (même modèle) → {texte, entree, sortie}."""
    lignes = "\n".join(f"{'Appelant' if t['qui'] == 'appelant' else 'Liluvine'} : {t['texte']}" for t in transcription)
    systeme = ("Tu résumes un appel téléphonique reçu par Liluvine, l'assistante de SAWALI, pour l'équipe. "
               "Réponds en français, 1 à 3 lignes courtes, sans markdown : qui appelle (si connu), la demande, "
               "la réponse donnée et l'action à faire (rappel…).")
    return await repondre_llm(systeme, [], lignes[:12000])


async def synthese_vocale(texte: str, s: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[bytes, str]:
    """Voix de Liluvine (chaîne du lot 67 : OpenAI → ElevenLabs → Google) en PCM 48 kHz mono.
    Lot 69.2 : décodage, passage en 48 kHz et raccourcissement des silences dans un fil séparé
    (jamais dans la boucle) ; OpenAI et ElevenLabs livrent directement du PCM (pas de MP3)."""
    audio, fournisseur = await ap.synthetiser(texte, s, cfg)
    pcm = await asyncio.to_thread(ap.preparer_pcm, audio)
    return pcm, fournisseur


# ---------------------------------------------------------------------------
# Prompt de l'appel : prompt système de Liluvine + consigne téléphone + identité de l'appelant
# ---------------------------------------------------------------------------

def assembler_prompt(base: str, *, contact_nom: Optional[str], telephone: str, plateforme: Optional[str],
                     ligne: Optional[Dict[str, Any]], connaissances: str = "",
                     consignes_ligne: str = "", transfert: bool = True) -> str:
    """Prompt système d'un appel (fonction pure, testée)."""
    morceaux = [(base or "").strip(), CONSIGNE_TELEPHONE, CONSIGNE_HUMAIN if transfert else CONSIGNE_SANS_HUMAIN]
    if connaissances:
        morceaux.append("\n\n" + connaissances.strip())
    if contact_nom and re.fullmatch(r"\+?[\d\s().-]+", contact_nom):
        contact_nom = None                  # lot 70 : un numéro n'est pas un nom
    qui = f"\n\nAppelant : {contact_nom or 'inconnu'} (+{telephone})"
    if plateforme:
        qui += f" — plateforme / client : {plateforme}"
    if ligne:
        qui += f"\nLigne SAWALI appelée : {ligne.get('libelle')}"
    morceaux.append(qui)
    if consignes_ligne:
        morceaux.append(f"\n\n[Ligne WhatsApp « {(ligne or {}).get('libelle')} »]\n{consignes_ligne}")
    return "".join(morceaux)


def historique_llm(transcription: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Transcription → historique du modèle (user = appelant, assistant = Liluvine).
    Les tours consécutifs du même côté sont fusionnés ; l'historique commence par l'appelant."""
    sortie: List[Dict[str, str]] = []
    for t in transcription:
        role = "user" if t["qui"] == "appelant" else "assistant"
        if sortie and sortie[-1]["role"] == role:
            sortie[-1]["content"] += " " + t["texte"]
        else:
            sortie.append({"role": role, "content": t["texte"]})
    while sortie and sortie[0]["role"] != "user":
        sortie.pop(0)                     # l'accueil de Liluvine précède : le modèle commence par « user »
    return sortie


def analyser_reponse(texte: str) -> Tuple[str, Optional[str]]:
    """Retire les marqueurs de fin ([FIN], [HUMAIN], [ESCALATE: …]) et le formatage → (texte, fin)."""
    fin = None
    if MARQUEUR_HUMAIN in texte or re.search(r"\[ESCALAT", texte, re.I):
        fin = "humain"
    elif MARQUEUR_FIN in texte:
        fin = "fin"
    propre = re.sub(r"\[(FIN|HUMAIN|ESCALATE[^\]]*|ESCALATION_HUMAINE)\]", "", texte, flags=re.I)
    propre = nettoyer_pour_voix(propre)                        # lot 70 : listes, puces, numérotation
    propre = re.sub(r"[*_#`>|]+", "", propre)                 # markdown
    propre = re.sub(r"https?://\S+", "", propre)              # liens (illisibles au téléphone)
    propre = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", propre)   # emojis
    return re.sub(r"\s+", " ", propre).strip(), fin


def nettoyer_pour_voix(texte: str) -> str:
    """Lot 70 — texte prêt pour la synthèse vocale : retire la mise en forme ÉCRITE qu'une voix lirait mal
    (« 1. », « 2) », « - », « • », énumérations entre parenthèses, titres et gras markdown) ; les lignes
    sont réunies en phrases. Fonction pure, testée."""
    lignes = []
    for ligne in (texte or "").splitlines():
        ligne = re.sub(r"^\s*(?:#{1,6}\s*)?(?:\d{1,2}\s*[.)]|[a-zA-Z]\)|[-•*–—▪●◦·])\s+", "", ligne)  # marque de liste
        ligne = ligne.strip()
        if not ligne:
            continue
        # Une ligne de liste sans ponctuation finale devient une phrase (« Support technique » → « … , »)
        if lignes and not re.search(r"[.!?…:,;]$", lignes[-1]):
            lignes[-1] += ","
        lignes.append(ligne)
    propre = " ".join(lignes)
    # Numérotation EN LIGNE (« … : 1. Quel service ? 2. Votre nom ? ») : traitée seulement si « 1 » ET « 2 »
    # sont présents (un « à 18. Nous… » isolé n'est pas une liste)
    motif_num = r"(?<![\w,])\(?(\d{1,2})[.)]\s+(?=[A-ZÀ-ÖØ-Ý«\"])"
    if {"1", "2"} <= set(re.findall(motif_num, propre)):
        propre = re.sub(r"\s*" + motif_num, ", ", propre)
    propre = re.sub(r"(^|[\s:;,])[•▪●◦]\s*", r"\1", propre)                  # puces en ligne
    propre = re.sub(r"\s+[-–—]\s+(?=[A-ZÀ-Ý])", ", ", propre)                  # tiret d'énumération
    # Énumération entre parenthèses (« (rendez-vous commercial, support technique…) ») : retirée
    propre = re.sub(r"\s*\((?=[^()]*(?:,|…|\.\.\.|\betc\b))[^()]*\)", "", propre)
    propre = re.sub(r"[*_`#]+", "", propre)                                     # gras, titres, code
    # Ponctuation recollée : « ?, » → « ? », « :, » → « : », « , . » → « . », virgule de tête retirée
    propre = re.sub(r"([.!?…:;])\s*,", r"\1", propre)
    propre = re.sub(r",\s*([.!?])", r"\1", propre)
    propre = re.sub(r",\s*,", ",", propre)
    propre = re.sub(r"^\s*,\s*", "", propre)
    return re.sub(r"\s+", " ", propre).strip()


def retirer_salutation(texte: str) -> str:
    """Lot 70 — « Bonjour Awa ! Bien sûr… » → « Bien sûr… » : Liluvine ne resalue pas après l'accueil."""
    sortie = re.sub(r"^\s*(?:re)?(?:bonjour|bonsoir|salut|hello)(?:\s+(?:à vous|madame|monsieur))?"
                    r"(?:\s+[A-ZÀ-Ý][\w'-]*){0,2}\s*[,!.]+\s*", "", texte or "", flags=re.I)
    return (sortie[:1].upper() + sortie[1:]) if sortie else (texte or "")


def une_seule_question(texte: str) -> str:
    """Lot 70 — garde la réponse jusqu'à sa PREMIÈRE question (une question à la fois au téléphone)."""
    morceaux = re.split(r"(?<=\?)\s+", (texte or "").strip())
    sortie: List[str] = []
    for m in morceaux:
        sortie.append(m)
        if m.endswith("?"):
            break
    return " ".join(sortie).strip()


def style_telephone(texte: str, *, deja_salue: bool) -> str:
    """Lot 70 — réponse de l'IA mise au style oral : nettoyage, pas de seconde salutation, une question."""
    t = nettoyer_pour_voix(texte)
    if deja_salue:
        t = retirer_salutation(t) or t
    return une_seule_question(t)


def decouper_phrases(texte: str) -> List[str]:
    """Découpe une réponse en phrases (la première est dite pendant que la suivante est synthétisée)."""
    morceaux = [m.strip() for m in re.split(r"(?<=[.!?…])\s+", texte or "") if m.strip()]
    sortie: List[str] = []
    for m in morceaux:
        # Phrases très courtes regroupées avec la précédente (« Oui. » seul = trop d'appels)
        if sortie and len(sortie[-1]) < 25:
            sortie[-1] += " " + m
        else:
            sortie.append(m)
    return sortie


async def prompt_de_l_appel(db, s: Dict[str, Any], appel: Dict[str, Any]) -> str:
    """Prompt système de Liluvine pour cet appel : prompt du client (ou prompt prospects), base de
    connaissances (partie MongoDB, sans recherche sémantique pour rester rapide), consignes de la ligne."""
    from routes.liluvine_pro import DEFAULT_WA_PROSPECT_SYSTEM_PROMPT, _resolve_base_system_prompt
    from routes.liluvine_wa_autoreply import _is_prospect_sender
    from routes.numeros_wa import ligne_par_cle
    contact = None
    if appel.get("contact_id"):
        contact = await db.directory_contacts.find_one({"id": appel["contact_id"]}, {"_id": 0})
    ligne = ligne_par_cle(s, appel.get("ligne_cle"))
    prospect = await _is_prospect_sender(db, contact) or bool((ligne or {}).get("prospects"))
    if prospect:
        base = (s.get("liluvine_wa_prospect_system_prompt") or "").strip() or DEFAULT_WA_PROSPECT_SYSTEM_PROMPT
    else:
        base = await _resolve_base_system_prompt(db, appel.get("client_id") or "")
    connaissances = ""
    try:
        from routes.liluvine_kb import build_kb_context
        connaissances = await asyncio.wait_for(
            build_kb_context(db, max_chars=3000, audience="prospects" if prospect else "clients"), timeout=3)
    except Exception:  # noqa: BLE001 — l'appel continue sans base de connaissances
        connaissances = ""
    plateforme = None
    if contact and contact.get("client_id"):
        u = await db.users.find_one({"id": contact["client_id"]}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        plateforme = u.get("company") or u.get("full_name")
    consignes = "" if not ligne or ligne.get("principale") else (ligne.get("complement_prompt") or "")
    return assembler_prompt(base, contact_nom=(contact or {}).get("name") or appel.get("contact_nom"),
                            telephone=appel.get("telephone") or "", plateforme=plateforme, ligne=ligne,
                            connaissances=connaissances, consignes_ligne=consignes,
                            transfert=reglages_decroche(s)["transfert_actif"])


# ---------------------------------------------------------------------------
# Journal : transcription, coût, résumé
# ---------------------------------------------------------------------------

def tour(qui: str, texte: str, debut: float, maintenant_dt: datetime) -> Dict[str, Any]:
    """Une ligne de transcription : qui parle, texte, secondes depuis le décroché, heure."""
    return {"qui": qui, "texte": texte, "t": round(max(0.0, time.monotonic() - debut), 1),
            "heure": maintenant_dt.isoformat()}


def _mm_ss(secondes: Any) -> str:
    """Secondes → « m:ss »."""
    s = int(float(secondes or 0))
    return f"{s // 60}:{s % 60:02d}"


def transcription_texte(transcription: List[Dict[str, Any]]) -> str:
    """Transcription lisible : « [0:05] Appelant : … » (journal, message au propriétaire)."""
    return "\n".join(f"[{_mm_ss(t.get('t'))}] {'Appelant' if t.get('qui') == 'appelant' else 'Liluvine'} : {t.get('texte')}"
                     for t in transcription or [])


def estimer_cout(mesures: Dict[str, Any]) -> Dict[str, Any]:
    """Estimation du coût d'un appel (USD, tarifs publics indicatifs) ; l'appel entrant est gratuit chez Meta."""
    stt = mesures.get("stt_secondes", 0) / 60 * TARIF_STT_MINUTE.get(mesures.get("stt_modele") or "", 0.006)
    tts = sum(n / 1000 * TARIF_TTS_1000.get(f, 0.0) for f, n in (mesures.get("tts_caracteres") or {}).items())
    llm = (mesures.get("llm_entree", 0) * TARIF_LLM_MILLION["entree"]
           + mesures.get("llm_sortie", 0) * TARIF_LLM_MILLION["sortie"]) / 1_000_000
    return {"devise": "USD", "transcription": round(stt, 4), "voix": round(tts, 4), "ia": round(llm, 4),
            "meta": 0.0, "total": round(stt + tts + llm, 4)}


def texte_resume_proprio(nom: str, telephone: str, resume: str, duree_s: int, transfert: bool) -> str:
    """Message WhatsApp envoyé au propriétaire après un appel pris par Liluvine."""
    entete = f"🤖📞 Liluvine a répondu à {nom} (+{telephone}) — {_mm_ss(duree_s)}"
    if transfert:
        entete += "\n⚠️ Demande à parler à un humain : à rappeler."
    return f"{entete}\n{resume}".strip()


# ---------------------------------------------------------------------------
# Piste audio de Liluvine (lecture à la demande, interruptible)
# ---------------------------------------------------------------------------

def creer_piste_conversation():
    """Piste audio WebRTC envoyée à l'appelant (lot 69.2 : piste PERSISTANTE du module audio_appel) :
    silence continu ; debut_reponse() / ajouter(pcm) / fin_reponse() pour parler sans trou entre les
    phrases ; arreter() coupe immédiatement ; en_lecture indique s'il reste du son à jouer."""
    from routes.audio_appel import creer_piste_voix
    return creer_piste_voix()


# ---------------------------------------------------------------------------
# Moteur : décrocher puis converser
# ---------------------------------------------------------------------------

def _maintenant() -> datetime:
    """Date et heure actuelles (UTC) — même horloge que le lot 67 (simulée dans les tests)."""
    return ap._maintenant()


async def _graph_appel(s: Dict[str, Any], numero_id: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """Action d'appel chez Meta (pre_accept, accept, terminate) — via la fonction du lot 67."""
    return await ap._graph_post(s, numero_id, "calls", {"messaging_product": "whatsapp", **corps})


async def prendre_appel(db, call_id: str) -> bool:
    """Prise ATOMIQUE de l'appel par Liluvine (même règle que le bouton « Décrocher » du portail) :
    réussit seulement si l'appel sonne encore (personne n'a décroché, l'appelant n'a pas raccroché)."""
    pris = await db.wa_appels.update_one(
        {"id": call_id, "statut": "sonne"},
        {"$set": {"statut": "decroche", "agent_id": None, "decroche_par_nom": NOM_LILUVINE,
                  "repondu_par": NOM_LILUVINE, "auto": True, "motif": MOTIF, "maj": _maintenant().isoformat()}})
    return bool(getattr(pris, "modified_count", 0))


async def _rendre_appel(db, call_id: str) -> None:
    """Échec avant l'accept : l'appel redevient disponible pour un humain du portail."""
    await db.wa_appels.update_one({"id": call_id, "statut": "decroche", "repondu_par": NOM_LILUVINE},
                                  {"$set": {"statut": "sonne", "decroche_par_nom": None, "repondu_par": None,
                                            "auto": None, "motif": None}})


async def demande_de_rappel(db, appel: Dict[str, Any], resume: str) -> Optional[str]:
    """Transmission à un humain : tâche « Rappeler … » dans les tâches du client concerné."""
    try:
        tache_id = str(uuid.uuid4())
        maintenant = _maintenant()
        await db.client_tasks.insert_one({
            "id": tache_id, "client_id": appel.get("client_id"),
            "title": f"📞 Rappeler {appel.get('contact_nom') or ''} (+{appel.get('telephone')}) — demandé à Liluvine",
            "description": resume or None, "due_at": (maintenant + timedelta(hours=1)).isoformat(),
            "status": "open", "remind_via_whatsapp": False, "voice_note_url": None, "voice_note_transcript": None,
            "reminder_sent_at": None, "author_id": None, "author_label": NOM_LILUVINE,
            "wa_appel_id": appel.get("id"), "created_at": maintenant.isoformat(), "updated_at": maintenant.isoformat()})
        return tache_id
    except Exception:  # noqa: BLE001
        logger.warning("[liluvine_decroche] tâche de rappel non créée", exc_info=True)
        return None


async def prevenir_proprietaire(db, s: Dict[str, Any], appel: Dict[str, Any], texte: str) -> List[Dict[str, Any]]:
    """Envoie le résumé de l'appel au(x) numéro(s) du propriétaire (relais du lot 67, depuis la ligne appelée)."""
    cfg67 = ap.reglages(s)
    numero_id = appel.get("numero_id") or ap.ligne_appelante(s, cfg67)[0]
    resultats = []
    for proprio in cfg67["numeros"]:
        r = await ap.envoyer_relais(db, s, cfg67, numero_id, proprio, texte,
                                    [f"{appel.get('contact_nom')} (+{appel.get('telephone')})",
                                     ap.extrait(texte, 200), ap.formater_date(_maintenant())], _maintenant())
        resultats.append({"telephone": proprio, "ok": r.get("ok"), "erreur": r.get("erreur")})
    return resultats


async def decrocher_et_converser(db, call_id: str, *, attendre_s: float = 0) -> Dict[str, Any]:
    """Prend l'appel (si possible), converse, raccroche et écrit le journal. Ne lève jamais d'exception."""
    try:
        return await _decrocher_et_converser(db, call_id, attendre_s=attendre_s)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[liluvine_decroche] appel %s en échec", call_id, exc_info=True)
        return {"resultat": "échec", "raison": str(exc)[:200]}
    finally:
        _actifs.discard(call_id)


async def _decrocher_et_converser(db, call_id: str, *, attendre_s: float = 0) -> Dict[str, Any]:
    # 0. Mode « délai » : on laisse sonner chez les humains pendant N secondes
    if attendre_s > 0:
        await asyncio.sleep(attendre_s)
    ok, raison = ap.moteur_disponible()
    if not ok:
        return {"resultat": "non", "raison": raison}
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfg = reglages_decroche(s)
    if not cfg["actif"]:
        return {"resultat": "non", "raison": "désactivé entre-temps"}
    # 1. Prise atomique : si un humain a décroché (ou l'appelant a raccroché), Liluvine s'efface
    if not await prendre_appel(db, call_id):
        return {"resultat": "non", "raison": "appel déjà pris ou terminé"}
    appel = await db.wa_appels.find_one({"id": call_id}, {"_id": 0}) or {}
    offre, numero_id = appel.get("sdp_offre"), appel.get("numero_id")
    if not offre or not numero_id:
        await _rendre_appel(db, call_id)
        return {"resultat": "échec", "raison": "offre SDP ou numéro absent"}

    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
    from routes.audio_appel import SondeBoucle, lancer_sur_media, sur_media
    ice = ap.serveurs_ice()
    detecteur = DetecteurParole()
    phrases: asyncio.Queue = asyncio.Queue()
    raccroche = asyncio.Event()
    principale = asyncio.get_running_loop()      # boucle de la conversation (API)
    lecteurs: List[Any] = []
    mesures: Dict[str, Any] = {"stt_secondes": 0.0, "stt_modele": None, "tts_caracteres": {}, "llm_entree": 0,
                               "llm_sortie": 0, "tours": 0, "latences_s": [], "premier_son_s": []}
    transcription: List[Dict[str, Any]] = []
    accepte = False
    debut = time.monotonic()            # remis à l'heure du décroché effectif (accept)
    # Lot 69.2 — sondes de retard : boucle principale (API) et boucle média (son)
    sonde_principale, sonde_media = SondeBoucle(), SondeBoucle()
    sondes = [asyncio.ensure_future(sonde_principale.tourner()), lancer_sur_media(sonde_media.tourner)]  # références gardées

    def signaler_raccroche() -> None:
        """Pose « raccroché » dans la boucle principale (appelable depuis la boucle média)."""
        principale.call_soon_threadsafe(raccroche.set)

    async def _preparer():
        """(boucle média) Connexion WebRTC, piste persistante, écoute de l'appelant, réponse SDP.
        Lot 69.2 : tout le son vit dans la boucle média, isolée des lenteurs de l'API."""
        connexion = RTCPeerConnection(RTCConfiguration(iceServers=ice))
        p = creer_piste_conversation()

        @connexion.on("track")
        def sur_piste(piste_appelant):
            """Son de l'appelant : rééchantillonné en 16 kHz mono puis découpé en phrases (léger :
            ~0,1 ms par trame) ; les phrases finies partent vers la boucle principale."""
            if piste_appelant.kind != "audio":
                return

            async def lire():
                import av
                reech = av.AudioResampler(format="s16", layout="mono", rate=FREQ_ANALYSE)
                while True:
                    try:
                        trame = await piste_appelant.recv()
                    except Exception:  # noqa: BLE001 — fin du flux : l'appelant a raccroché
                        signaler_raccroche()
                        return
                    for t in reech.resample(trame):
                        for phrase in detecteur.ajouter(bytes(t.planes[0])[: t.samples * 2]):
                            principale.call_soon_threadsafe(phrases.put_nowait, phrase)
            lecteurs.append(asyncio.ensure_future(lire()))

        @connexion.on("connectionstatechange")
        async def sur_etat():
            if connexion.connectionState in ("failed", "closed"):
                signaler_raccroche()

        await connexion.setRemoteDescription(RTCSessionDescription(sdp=offre, type="offer"))
        connexion.addTrack(p)
        await connexion.setLocalDescription(await connexion.createAnswer())
        return connexion, p

    async def _fermer():
        """(boucle média) Arrête l'écoute et ferme la connexion."""
        for t in lecteurs:
            t.cancel()
        await pc.close()

    pc = None
    try:
        # 2. Réponse SDP du serveur à l'offre de Meta, puis pre_accept + accept
        pc, piste = await sur_media(_preparer)
        session = {"sdp_type": "answer", "sdp": pc.localDescription.sdp}
        for action in ("pre_accept", "accept"):
            rep = await _graph_appel(s, numero_id, {"call_id": call_id, "action": action, "session": session})
            if not rep.get("ok"):
                await _rendre_appel(db, call_id)
                await db.wa_appels.update_one({"id": call_id}, {"$set": {
                    "liluvine": {"erreur": f"{action} : {rep.get('erreur')}"}}})
                return {"resultat": "échec", "raison": f"{action} : {rep.get('erreur')}"}
        accepte = True
        debut = time.monotonic()
        await db.wa_appels.update_one({"id": call_id}, {"$set": {
            "statut": "en_cours", "debut": _maintenant().isoformat(), "sdp_offre": None,
            "maj": _maintenant().isoformat()}})

        # 3. Attente de la connexion audio (ICE + DTLS)
        async def connecte():
            if pc.connectionState == "failed":
                return "failed"
            return "ok" if pc.connectionState == "connected" else None
        if await ap._attendre(connecte, 12, 0.1) != "ok":
            raise RuntimeError("connexion audio impossible (ICE/DTLS) — vérifiez l'UDP sortant ou le TURN")
        prompt = await prompt_de_l_appel(db, s, appel)

        # 4. Accueil puis conversation (lot 70 : moteur commun aux appels entrants et sortants)
        conv = Conversation(db=db, call_id=call_id, s=s, cfg=cfg, piste=piste, detecteur=detecteur,
                            phrases=phrases, raccroche=raccroche, mesures=mesures, transcription=transcription,
                            debut=debut)
        await asyncio.sleep(0.3)
        await conv.dire(cfg["accueil"])
        fin, transfert = None, False
        if not cle_openai(s):
            # Pas de transcription possible : excuse, demande de rappel, fin
            await conv.dire(TEXTE_SANS_STT)
            fin, transfert = "transcription indisponible (clé OpenAI absente)", True
        if fin is None:
            fin, transfert = await conv.converser(prompt)
        # Laisse finir la dernière phrase avant de raccrocher
        await asyncio.sleep(0.6)
        mesures["qualite_audio"] = qualite_audio(piste, sonde_principale, sonde_media, mesures)
        duree_s = int(round(time.monotonic() - debut))
        return await _cloturer(db, s, cfg, appel, transcription, mesures, fin or "fin", transfert, duree_s,
                               raccrocher=not (fin == "l'appelant a raccroché"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[liluvine_decroche] erreur pendant l'appel %s", call_id, exc_info=True)
        if not accepte:
            await _rendre_appel(db, call_id)
            return {"resultat": "échec", "raison": str(exc)[:200]}
        if pc is not None:
            mesures["qualite_audio"] = qualite_audio(piste, sonde_principale, sonde_media, mesures)
        return await _cloturer(db, s, cfg, appel, transcription, mesures, f"erreur : {str(exc)[:150]}", True,
                               int(round(time.monotonic() - debut)), raccrocher=True)
    finally:
        sonde_principale.arreter()
        sonde_media.arreter()
        for f in sondes:
            f.cancel()
        try:
            if pc is not None:
                await sur_media(_fermer)
        except Exception:  # noqa: BLE001
            pass


class Conversation:
    """Lot 70 — moteur de conversation COMMUN aux appels entrants (lot 69) et sortants (agenda, lot 70).

    Reçoit les objets d'un appel déjà connecté (piste de Liluvine, détecteur de parole, file des
    phrases de l'interlocuteur, évènement « raccroché ») et fournit :
      - dire(texte)       : Liluvine parle (phrases synthétisées à la suite, coupure de parole possible) ;
      - converser(prompt) : boucle écoute → transcription → réponse IA → voix, jusqu'à [FIN] / [HUMAIN],
                            silence prolongé, durée maximale ou raccroché ; renvoie (raison de fin, transfert).
    La transcription et les mesures (coût, latences) sont écrites dans les listes / dictionnaires fournis."""

    def __init__(self, *, db, call_id: str, s: Dict[str, Any], cfg: Dict[str, Any], piste, detecteur,
                 phrases: asyncio.Queue, raccroche: asyncio.Event, mesures: Dict[str, Any],
                 transcription: List[Dict[str, Any]], debut: Optional[float] = None,
                 texte_silence: str = TEXTE_SILENCE, texte_duree_max: str = TEXTE_DUREE_MAX):
        self.db, self.call_id, self.s, self.cfg = db, call_id, s, cfg
        self.piste, self.detecteur, self.phrases, self.raccroche = piste, detecteur, phrases, raccroche
        self.mesures, self.transcription = mesures, transcription
        # Instant du décroché effectif (horloge monotone) : base des « [m:ss] » de la transcription
        self.debut = debut if debut is not None else time.monotonic()
        # Phrases dites dans les cas particuliers (personnalisables pour les appels sortants)
        self.texte_silence, self.texte_duree_max = texte_silence, texte_duree_max

    async def dire(self, texte: str, t_question: Optional[float] = None) -> bool:
        """Dit un texte. Lot 69.2 : les phrases sont synthétisées l'une après l'autre et AJOUTÉES À LA
        SUITE dans la file de la piste dès qu'elles sont prêtes (aucun trou entre deux phrases) ; la
        lecture commence avec 400 ms d'avance. Renvoie False si l'interlocuteur a coupé la parole."""
        texte = nettoyer_pour_voix(texte)          # lot 70 : jamais de liste lue à voix haute
        if not texte:
            return True
        piste, mesures = self.piste, self.mesures
        self.transcription.append(tour("liluvine", texte, self.debut, _maintenant()))
        morceaux = decouper_phrases(texte)
        piste.debut_reponse()

        async def producteur():
            """Synthèse des phrases dans l'ordre ; chacune rejoint la file dès qu'elle est prête."""
            try:
                for m in morceaux:
                    try:
                        pcm, fournisseur = await synthese_vocale(m, self.s, self.cfg)
                    except Exception:  # noqa: BLE001 — voix indisponible pour ce morceau
                        logger.warning("[liluvine_decroche] voix impossible", exc_info=True)
                        continue
                    if fournisseur:
                        mesures["tts_caracteres"][fournisseur] = mesures["tts_caracteres"].get(fournisseur, 0) + len(m)
                    piste.ajouter(pcm)
            finally:
                piste.fin_reponse()
        production = asyncio.ensure_future(producteur())
        try:
            # Attente de la fin de la lecture (ou coupure de parole par l'interlocuteur)
            while piste.en_lecture and not self.raccroche.is_set():
                if (self.cfg.get("coupure_parole", True) and self.detecteur.parle and self.detecteur.debut_parole
                        and time.monotonic() - self.detecteur.debut_parole > 0.4):
                    production.cancel()
                    piste.arreter()
                    self.transcription[-1]["interrompu"] = True
                    return False
                await asyncio.sleep(0.03)
            return True
        finally:
            if not production.done():
                production.cancel()
            # Délai entre la fin de la phrase de l'interlocuteur et le premier son de la réponse
            premier = piste.lecteur.premier_son
            if t_question is not None and premier is not None and premier >= t_question:
                mesures["premier_son_s"].append(round(premier - t_question, 2))

    async def converser(self, prompt: str) -> Tuple[str, bool]:
        """Boucle de conversation → (raison de fin, transmettre à un humain ?)."""
        cfg, mesures, transcription = self.cfg, self.mesures, self.transcription
        fin: Optional[str] = None
        transfert = False
        dernier = time.monotonic()
        while fin is None:
            if self.raccroche.is_set() or await _termine_chez_meta(self.db, self.call_id):
                fin = "l'appelant a raccroché"
                break
            if time.monotonic() - self.debut > cfg["duree_max_s"]:
                await self.dire(self.texte_duree_max)
                fin, transfert = "durée maximale atteinte", cfg["transfert_actif"]
                break
            try:
                phrase = await asyncio.wait_for(self.phrases.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if self.detecteur.parle or self.piste.en_lecture:
                    dernier = time.monotonic()
                elif time.monotonic() - dernier > cfg["silence_s"]:
                    await self.dire(self.texte_silence)
                    fin = "silence prolongé"
                continue
            t0 = time.monotonic()
            # a. Transcription de la phrase de l'interlocuteur
            try:
                texte, modele = await transcrire(wav_16k(phrase), self.s, cfg)
                mesures["stt_secondes"] += duree_pcm_s(phrase)
                mesures["stt_modele"] = modele
            except Exception:  # noqa: BLE001
                logger.warning("[liluvine_decroche] transcription impossible", exc_info=True)
                texte = ""
            texte = transcription_utile(texte)
            if not texte:
                dernier = time.monotonic()
                continue
            transcription.append(tour("appelant", texte, self.debut, _maintenant()))
            # b. Réponse de Liluvine (prompt système + consigne téléphone + historique)
            try:
                hist = historique_llm(transcription[:-1])
                rep = await repondre_llm(prompt, hist, texte)
                mesures["llm_entree"] += int(rep.get("entree") or 0)
                mesures["llm_sortie"] += int(rep.get("sortie") or 0)
                reponse, marque = analyser_reponse(rep.get("texte") or "")
                # Lot 70 — style oral : pas de seconde salutation, une seule question à la fois
                reponse = style_telephone(reponse, deja_salue=any(x["qui"] == "liluvine" for x in transcription))
            except Exception:  # noqa: BLE001
                logger.warning("[liluvine_decroche] réponse IA impossible", exc_info=True)
                reponse, marque = TEXTE_ERREUR, "erreur"
            mesures["tours"] += 1
            mesures["latences_s"].append(round(time.monotonic() - t0, 2))
            await self.dire(reponse or TEXTE_REPETER, t0)
            dernier = time.monotonic()
            if marque == "humain":
                fin, transfert = "demande à parler à un humain", cfg["transfert_actif"]
            elif marque == "erreur":
                fin, transfert = "IA indisponible : rappel demandé", True
            elif marque == "fin":
                fin = "au revoir"
        return fin or "fin", transfert


def qualite_audio(piste, sonde_principale, sonde_media, mesures: Dict[str, Any]) -> Dict[str, Any]:
    """Lot 69.2 — mesures de qualité du son d'un appel (journal, ligne « Qualité audio ») :
    manques de son pendant une réponse, recalages d'horloge, retards maximaux des boucles,
    délai moyen avant le premier son d'une réponse."""
    from routes.audio_appel import boucle_media_active
    m = piste.mesures() if hasattr(piste, "mesures") else {}
    premiers = mesures.get("premier_son_s") or []
    return {
        "sous_alimentations": int(m.get("sous_alimentations") or 0),
        "recalages": int(m.get("recalages") or 0),
        "trames_son": int(m.get("trames_son") or 0),
        "retard_boucle_max_ms": int(round(sonde_principale.retard_max_ms)),
        "retard_media_max_ms": int(round(sonde_media.retard_max_ms)),
        "premier_son_moyen_s": round(sum(premiers) / len(premiers), 2) if premiers else None,
        "boucle_media": boucle_media_active(),
    }


async def _termine_chez_meta(db, call_id: str) -> bool:
    """Meta a-t-il signalé la fin de l'appel (webhook « terminate ») ?"""
    doc = await db.wa_appels.find_one({"id": call_id}, {"_id": 0, "statut": 1}) or {}
    return doc.get("statut") in ("termine", "manque", "refuse")


async def _cloturer(db, s: Dict[str, Any], cfg: Dict[str, Any], appel: Dict[str, Any],
                    transcription: List[Dict[str, Any]], mesures: Dict[str, Any], fin: str, transfert: bool,
                    duree_s: int, *, raccrocher: bool) -> Dict[str, Any]:
    """Raccroche (si besoin), résume, écrit le journal, crée la demande de rappel, prévient le propriétaire."""
    call_id = appel["id"]
    if raccrocher:
        await _graph_appel(s, appel.get("numero_id"), {"call_id": call_id, "action": "terminate"})
    # Résumé de l'appel (1 à 3 lignes)
    resume = ""
    if any(t["qui"] == "appelant" for t in transcription):
        try:
            r = await resumer(transcription)
            mesures["llm_entree"] += int(r.get("entree") or 0)
            mesures["llm_sortie"] += int(r.get("sortie") or 0)
            resume = analyser_reponse(r.get("texte") or "")[0]
        except Exception:  # noqa: BLE001
            logger.warning("[liluvine_decroche] résumé impossible", exc_info=True)
    if not resume:
        resume = "Appel sans échange exploitable." if not transcription else \
            f"Appel de {appel.get('contact_nom')} : {len([t for t in transcription if t['qui'] == 'appelant'])} intervention(s)."
    tache_id = await demande_de_rappel(db, appel, resume) if transfert else None
    cout = estimer_cout(mesures)
    lat = mesures.get("latences_s") or []
    journal = {"transcription": transcription, "resume": resume, "fin": fin, "transfert_humain": bool(transfert),
               "tache_rappel_id": tache_id, "duree_s": duree_s, "tours": mesures["tours"], "cout": cout,
               "latence_moyenne_s": round(sum(lat) / len(lat), 2) if lat else None,
               "voix": sorted(mesures["tts_caracteres"]), "stt_modele": mesures.get("stt_modele"),
               # Lot 69.2 — qualité du son (diagnostic des coupures)
               "qualite_audio": mesures.get("qualite_audio")}
    maj: Dict[str, Any] = {"liluvine": journal, "repondu_par": NOM_LILUVINE, "decroche_par_nom": NOM_LILUVINE,
                           "resultat": "répondu par Liluvine", "maj": _maintenant().isoformat()}
    doc = await db.wa_appels.find_one({"id": call_id}, {"_id": 0, "statut": 1, "duree_s": 1}) or {}
    if doc.get("statut") in ("en_cours", "decroche"):
        # Le webhook « terminate » de Meta n'est pas encore arrivé : durée mesurée par le serveur
        maj.update({"statut": "termine", "duree_s": duree_s, "fin": _maintenant().isoformat()})
    await db.wa_appels.update_one({"id": call_id}, {"$set": maj})
    # Résumé envoyé au propriétaire sur WhatsApp (réglage, activé par défaut)
    envoi = []
    if cfg["resume_proprio"] or transfert:
        try:
            envoi = await prevenir_proprietaire(db, s, appel, texte_resume_proprio(
                appel.get("contact_nom") or "", appel.get("telephone") or "", resume, duree_s, transfert))
        except Exception:  # noqa: BLE001
            logger.warning("[liluvine_decroche] résumé non envoyé au propriétaire", exc_info=True)
    return {"resultat": "répondu", "fin": fin, "transfert": transfert, "resume": resume, "cout": cout,
            "tours": mesures["tours"], "envoi_proprio": envoi}


# ---------------------------------------------------------------------------
# Point d'entrée du webhook (appel entrant qui sonne)
# ---------------------------------------------------------------------------

def _lancer(coro) -> None:
    """Lance une coroutine en arrière-plan (référence gardée)."""
    tache = asyncio.get_running_loop().create_task(coro)
    _taches.add(tache)
    tache.add_done_callback(_taches.discard)


async def planifier_decroche(db, call_id: str, s: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Appelé par le webhook après l'inscription d'un appel entrant : décide et lance le décroché en
    arrière-plan (ne bloque jamais la réponse à Meta). Renvoie la décision (tests, journal)."""
    try:
        s = s if s is not None else (await db.settings.find_one({"_id": "global"}) or {})
        cfg = reglages_decroche(s)
        if not cfg["actif"]:
            return {"decrocher": False, "raison": "décroché automatique désactivé"}
        appel = await db.wa_appels.find_one({"id": call_id}, {"_id": 0}) or {}
        contact = None
        if appel.get("contact_id"):
            contact = await db.directory_contacts.find_one({"id": appel["contact_id"]},
                                                           {"_id": 0, "liluvine_decroche": 1})
        d = decision_decroche(cfg, ligne_cle=appel.get("ligne_cle"), telephone=appel.get("telephone") or "",
                              contact=contact, maintenant=_maintenant(), actifs=len(_actifs))
        await db.wa_appels.update_one({"id": call_id}, {"$set": {"liluvine_decision": d["raison"]}})
        if d["decrocher"]:
            _actifs.add(call_id)                 # place réservée (libérée à la fin de la tâche)
            _lancer(decrocher_et_converser(db, call_id, attendre_s=d["delai_s"]))
        return d
    except Exception as exc:  # noqa: BLE001 — jamais d'exception vers le webhook
        logger.warning("[liluvine_decroche] décision impossible", exc_info=True)
        return {"decrocher": False, "raison": f"erreur : {str(exc)[:120]}"}


# ---------------------------------------------------------------------------
# Routes d'administration
# ---------------------------------------------------------------------------

CHAMPS = {
    "liluvine_decroche_actif": bool, "liluvine_decroche_lignes": list, "liluvine_decroche_mode": str,
    "liluvine_decroche_delai_s": int, "liluvine_decroche_ouverture_debut": str,
    "liluvine_decroche_ouverture_fin": str, "liluvine_decroche_jours": str, "liluvine_decroche_accueil": str,
    "liluvine_decroche_duree_max_min": int, "liluvine_decroche_silence_s": int, "liluvine_decroche_voix": str,
    "liluvine_decroche_voix_elevenlabs": str, "liluvine_decroche_transfert_actif": bool,
    "liluvine_decroche_resume_proprio": bool, "liluvine_decroche_max_simultanes": int,
    "liluvine_decroche_coupure_parole": bool, "liluvine_decroche_stt_modele": str, "liluvine_decroche_exclus": str,
    # Lot 69.2 — profil de voix (aussi utilisé par « Liluvine appelle le propriétaire », lot 67)
    "liluvine_decroche_voix_openai": str, "liluvine_decroche_modele_openai": str, "liluvine_decroche_accent": str,
    "liluvine_decroche_modele_elevenlabs": str,
}

# Lot 69.2 — Bibliothèque de voix ElevenLabs : accents proposés pour la recherche de voix françaises
ACCENTS_BIBLIOTHEQUE = ("african", "west african", "ivorian", "senegalese", "cameroonian", "congolese", "")
# Texte d'essai par défaut (« Écouter un essai ») quand aucun accueil n'est saisi
TEXTE_ESSAI = ACCUEIL_DEFAUT


async def _elevenlabs_get(chemin: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET sur l'API ElevenLabs avec la clé ELEVENLABS_API_KEY (côté serveur, jamais envoyée au navigateur)."""
    cle = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not cle:
        raise RuntimeError("ELEVENLABS_API_KEY absente (variable d'environnement Render)")
    async with httpx.AsyncClient(timeout=15) as http:
        r = await http.get(f"https://api.elevenlabs.io{chemin}", params=params, headers={"xi-api-key": cle})
    if r.status_code >= 300:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}")
    return r.json() or {}


def voix_du_compte(donnees: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Réponse de GET /v1/voices → liste simple (nom, accent, genre, extrait sonore)."""
    sortie = []
    for v in donnees.get("voices") or []:
        etiquettes = v.get("labels") or {}
        sortie.append({"voice_id": v.get("voice_id"), "nom": v.get("name"), "accent": etiquettes.get("accent"),
                       "genre": etiquettes.get("gender"), "langue": etiquettes.get("language"),
                       "description": etiquettes.get("description") or v.get("description"),
                       "extrait": v.get("preview_url"), "categorie": v.get("category"), "source": "compte"})
    return sortie


def voix_de_la_bibliotheque(donnees: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Réponse de GET /v1/shared-voices → liste simple (à ajouter au compte avant usage)."""
    return [{"voice_id": v.get("voice_id"), "proprietaire_id": v.get("public_owner_id"), "nom": v.get("name"),
             "accent": v.get("accent"), "genre": v.get("gender"), "langue": v.get("language"),
             "locale": v.get("locale"), "description": (v.get("description") or "")[:200],
             "extrait": v.get("preview_url"), "source": "bibliotheque"}
            for v in donnees.get("voices") or []]


def reglages_essai(s: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages de voix pour « Écouter un essai » : ceux enregistrés, remplacés par ceux du formulaire
    (non encore enregistrés) — seuls les champs de voix connus sont pris."""
    brut = dict(s or {})
    for cle in ("liluvine_decroche_voix", "liluvine_decroche_voix_elevenlabs", "liluvine_decroche_voix_openai",
                "liluvine_decroche_modele_openai", "liluvine_decroche_accent", "liluvine_decroche_modele_elevenlabs"):
        if cle in (payload or {}):
            brut[cle] = str(payload.get(cle) or "").strip()[:500]
    return reglages_decroche(brut)


def setup_liluvine_decroche_routes(*, db, api, get_current_user) -> None:
    """Déclare les routes /admin/liluvine-decroche (administrateurs et superviseurs)."""
    from fastapi import Body, Depends, HTTPException

    def _exiger_admin(user: dict) -> None:
        """Réservé aux administrateurs et superviseurs."""
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")

    @api.get("/admin/liluvine-decroche", tags=["Admin — WhatsApp"])
    async def lire(user: dict = Depends(get_current_user)):
        """Réglages, état du moteur et des clés (présence seulement, jamais la valeur), derniers appels."""
        _exiger_admin(user)
        from ia_client import cle_ia
        from routes.numeros_wa import lignes_configurees
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = reglages_decroche(s)
        moteur, raison = ap.moteur_disponible()
        derniers = await db.wa_appels.find({"repondu_par": NOM_LILUVINE},
                                           {"_id": 0, "sdp_offre": 0, "sdp_reponse": 0}) \
            .sort("created_at", -1).limit(10).to_list(10)
        return {
            "reglages": {k: s.get(k) for k in CHAMPS},
            "effectif": {**{k: v for k, v in cfg.items() if k != "exclus"}, "exclus": sorted(cfg["exclus"])},
            "lignes": [{"cle": li["cle"], "libelle": li["libelle"], "telephone": li["telephone"]}
                       for li in lignes_configurees(s)],
            "moteur": {"disponible": moteur, "raison": raison, "transcription": bool(cle_openai(s)),
                       "ia": bool(cle_ia("anthropic")), "voix": ap.fournisseurs_voix(s, cfg),
                       "en_cours": len(_actifs)},
            "proprietaire": bool(ap.reglages(s)["numeros"]),
            "derniers": derniers,
            # Lot 69.2 — choix proposés pour la voix (et présence de la clé ElevenLabs, jamais sa valeur)
            "choix_voix": {"openai": list(ap.VOIX_OPENAI), "modeles_openai": list(ap.MODELES_OPENAI),
                           "modeles_elevenlabs": list(ap.MODELES_ELEVENLABS), "accent_defaut": ap.ACCENT_DEFAUT,
                           "elevenlabs_cle": bool(os.environ.get("ELEVENLABS_API_KEY", "").strip()),
                           "openai_cle": bool(cle_openai(s))},
        }

    @api.put("/admin/liluvine-decroche", tags=["Admin — WhatsApp"])
    async def enregistrer(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Enregistre les réglages (champs connus uniquement, valeurs contrôlées)."""
        _exiger_admin(user)
        maj: Dict[str, Any] = {}
        for cle, genre in CHAMPS.items():
            if cle not in payload:
                continue
            valeur = payload[cle]
            if genre is bool:
                maj[cle] = bool(valeur)
            elif genre is int:
                try:
                    maj[cle] = int(valeur)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Valeur entière attendue pour {cle}")
            elif genre is list:
                maj[cle] = _liste_lignes(valeur)[:20]
            else:
                maj[cle] = str(valeur or "").strip()[:2000]
        if maj.get("liluvine_decroche_mode") and maj["liluvine_decroche_mode"] not in MODES:
            raise HTTPException(status_code=422, detail="Mode inconnu (toujours, delai, hors_heures)")
        for cle in ("liluvine_decroche_ouverture_debut", "liluvine_decroche_ouverture_fin"):
            if maj.get(cle) and not re.fullmatch(r"\d{1,2}[:hH]\d{2}", maj[cle]):
                raise HTTPException(status_code=422, detail="Heure attendue au format HH:MM")
        if maj.get("liluvine_decroche_voix") and maj["liluvine_decroche_voix"] not in ("auto", "openai", "elevenlabs", "google"):
            raise HTTPException(status_code=422, detail="Voix inconnue")
        if maj.get("liluvine_decroche_stt_modele") and maj["liluvine_decroche_stt_modele"] not in MODELES_STT:
            raise HTTPException(status_code=422, detail="Modèle de transcription inconnu")
        # Lot 69.2 — profil de voix
        if maj.get("liluvine_decroche_voix_openai") and maj["liluvine_decroche_voix_openai"] not in ap.VOIX_OPENAI:
            raise HTTPException(status_code=422, detail="Voix OpenAI inconnue")
        if maj.get("liluvine_decroche_modele_openai") and maj["liluvine_decroche_modele_openai"] not in ap.MODELES_OPENAI:
            raise HTTPException(status_code=422, detail="Modèle de voix OpenAI inconnu")
        if (maj.get("liluvine_decroche_modele_elevenlabs")
                and maj["liluvine_decroche_modele_elevenlabs"] not in ap.MODELES_ELEVENLABS):
            raise HTTPException(status_code=422, detail="Modèle ElevenLabs inconnu")
        if maj.get("liluvine_decroche_voix_elevenlabs") and not re.fullmatch(r"[A-Za-z0-9]{8,64}",
                                                                             maj["liluvine_decroche_voix_elevenlabs"]):
            raise HTTPException(status_code=422, detail="Identifiant de voix ElevenLabs invalide")
        maj["liluvine_decroche_maj_par"] = user.get("full_name") or user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True}

    @api.post("/admin/liluvine-decroche/simuler", tags=["Admin — WhatsApp"])
    async def simuler(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Simulation écrite d'un appel : ce que Liluvine répondrait au téléphone (même prompt, même modèle,
        mêmes marqueurs de fin) — sans appel réel ni voix."""
        _exiger_admin(user)
        texte = str(payload.get("texte") or "").strip()[:1000]
        if not texte:
            raise HTTPException(status_code=400, detail="Écrivez ce que dit l'appelant")
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = reglages_decroche(s)
        transcription = [t for t in (payload.get("historique") or [])
                         if isinstance(t, dict) and t.get("qui") in ("appelant", "liluvine") and t.get("texte")][-20:]
        if not transcription:
            transcription = [{"qui": "liluvine", "texte": cfg["accueil"]}]
        appel = {"contact_nom": "Appelant d'essai", "telephone": "22600000000", "ligne_cle": "principal",
                 "client_id": user.get("client_id") or user.get("id")}
        prompt = await prompt_de_l_appel(db, s, appel)
        try:
            rep = await repondre_llm(prompt, historique_llm(transcription), texte)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"IA indisponible : {str(exc)[:200]}")
        reponse, fin = analyser_reponse(rep.get("texte") or "")
        return {"reponse": reponse or TEXTE_REPETER, "fin": fin, "phrases": decouper_phrases(reponse),
                "historique": transcription + [{"qui": "appelant", "texte": texte},
                                               {"qui": "liluvine", "texte": reponse}],
                "jetons": {"entree": rep.get("entree"), "sortie": rep.get("sortie")}}

    @api.get("/admin/liluvine-decroche/voix-elevenlabs", tags=["Admin — WhatsApp"])
    async def voix_elevenlabs(source: str = "compte", accent: str = "african", recherche: str = "",
                              user: dict = Depends(get_current_user)):
        """Lot 69.2 — « Choisir une voix ElevenLabs » : voix du compte (GET /v1/voices) ou recherche de
        voix FRANÇAISES dans la bibliothèque partagée (GET /v1/shared-voices, language=fr, accent).
        Si aucun résultat avec l'accent demandé, nouvelle recherche par mots-clés (« afrique »)."""
        _exiger_admin(user)
        try:
            if source == "bibliotheque":
                params: Dict[str, Any] = {"language": "fr", "page_size": 30}
                if accent.strip():
                    params["accent"] = accent.strip()[:40]
                if recherche.strip():
                    params["search"] = recherche.strip()[:60]
                voix = voix_de_la_bibliotheque(await _elevenlabs_get("/v1/shared-voices", params))
                if not voix and accent.strip():
                    voix = voix_de_la_bibliotheque(await _elevenlabs_get("/v1/shared-voices", {
                        "language": "fr", "page_size": 30, "search": recherche.strip()[:60] or "africa"}))
            else:
                voix = voix_du_compte(await _elevenlabs_get("/v1/voices", {}))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=str(exc)[:200])
        return {"source": source, "voix": voix}

    @api.post("/admin/liluvine-decroche/voix-elevenlabs/ajouter", tags=["Admin — WhatsApp"])
    async def ajouter_voix_elevenlabs(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Lot 69.2 — ajoute une voix de la bibliothèque partagée au compte ElevenLabs
        (POST /v1/voices/add/{public_owner_id}/{voice_id}) ; renvoie l'identifiant à utiliser."""
        _exiger_admin(user)
        proprietaire = str(payload.get("proprietaire_id") or "").strip()
        voix_id = str(payload.get("voice_id") or "").strip()
        nom = (str(payload.get("nom") or "").strip() or "Liluvine")[:60]
        if not re.fullmatch(r"[A-Za-z0-9]{4,128}", proprietaire) or not re.fullmatch(r"[A-Za-z0-9]{8,64}", voix_id):
            raise HTTPException(status_code=422, detail="Voix de la bibliothèque invalide")
        cle = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not cle:
            raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY absente (variable d'environnement Render)")
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.post(f"https://api.elevenlabs.io/v1/voices/add/{proprietaire}/{voix_id}",
                                    json={"new_name": nom}, headers={"xi-api-key": cle})
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"ElevenLabs injoignable : {str(exc)[:150]}")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"ElevenLabs HTTP {r.status_code} : ajout refusé "
                                                         "(offre ElevenLabs ou voix non partageable)")
        return {"ok": True, "voice_id": (r.json() or {}).get("voice_id") or voix_id}

    @api.post("/admin/liluvine-decroche/essai-voix", tags=["Admin — WhatsApp"])
    async def essai_voix(payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_user)):
        """Lot 69.2 — « Écouter un essai » : synthétise l'accueil (ou le texte donné) avec la voix, l'accent
        et le moteur choisis (réglages du formulaire, même non enregistrés) et renvoie le son
        (audio/wav pour OpenAI et ElevenLabs, audio/mpeg pour Google). Réservé aux administrateurs."""
        from fastapi import Response
        _exiger_admin(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = reglages_essai(s, payload or {})
        texte = (str((payload or {}).get("texte") or "").strip() or cfg["accueil"] or TEXTE_ESSAI)[:400]
        try:
            audio, fournisseur = await ap.synthetiser(texte, s, cfg)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=str(exc)[:300])
        type_mime = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"
        return Response(content=audio, media_type=type_mime,
                        headers={"X-Voix-Fournisseur": fournisseur, "Cache-Control": "no-store"})

    @api.get("/admin/liluvine-decroche/voix-clonees", tags=["Admin — WhatsApp"])
    async def voix_clonees(user: dict = Depends(get_current_user)):
        """Lot 70 — « Voix clonées dans SAWALI (Story Studio) » : voix ElevenLabs créées par clonage
        (db.eleven_voices, tous les utilisateurs, visibles par l'administrateur) ; « Utiliser pour Liluvine »
        règle le moteur ElevenLabs avec l'identifiant choisi (même clé ELEVENLABS_API_KEY)."""
        _exiger_admin(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {"voix": await voix_story_studio(db),
                "voix_actuelle": (s.get("liluvine_decroche_voix_elevenlabs") or "").strip(),
                "elevenlabs_cle": bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())}


async def voix_story_studio(db) -> List[Dict[str, Any]]:
    """Lot 70 — voix clonées dans Story Studio (db.eleven_voices) avec le nom de leur auteur.
    Une voix sans identifiant ElevenLabs valide est écartée (elle ne pourrait pas parler)."""
    docs = await db.eleven_voices.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    ids = list({d.get("user_id") for d in docs if d.get("user_id")})
    auteurs: Dict[str, str] = {}
    if ids:
        async for u in db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "full_name": 1, "email": 1, "company": 1}):
            auteurs[u["id"]] = u.get("full_name") or u.get("company") or u.get("email") or ""
    sortie = []
    for d in docs:
        voix_id = str(d.get("voice_id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{8,64}", voix_id):
            continue
        sortie.append({"voice_id": voix_id, "nom": d.get("name") or "Voix clonée",
                       "description": (d.get("description") or "")[:200], "auteur": auteurs.get(d.get("user_id"), ""),
                       "cree_le": d.get("created_at"), "source": "story_studio"})
    return sortie
