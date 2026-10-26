"""Lot 287 — Réponse automatique de Liluvine aux demandes de REPORT de RDV, adaptée à la clinique (code_clinique).

Contexte : le numéro WhatsApp qui envoie les rappels « RDV dans 1 h » reçoit aussi les réponses des patients,
dont beaucoup demandent un report. Quand un patient écrit APRÈS avoir reçu un rappel, Liluvine retrouve son RDV
(par son numéro), lit le `code_clinique` du RDV et répond avec le message réglé POUR CETTE CLINIQUE
(ex. « Appelez l'accueil SVP : 78267900/70463624 »).

Réglages (dans `settings.global`, aucune nouvelle collection) :
  - planning_report_actif         : bool, activation (absent = non)
  - planning_report_reponses      : [{code_clinique, message}]  (un message par clinique)
  - planning_report_defaut        : message utilisé si le code_clinique n'a pas de ligne (vide = pas de réponse)
  - planning_report_repondre_tout : bool, répondre à TOUT message après un rappel (sinon : seulement aux demandes de report)

Le réglage se fait dans Paramètres → « Webhook Planning consultations (RDV patients) ».
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("sawali.planning_report_rdv")

# Un patient qui écrit plus de 24 h après son rappel n'est plus rattaché à ce RDV
FENETRE_HEURES = 24

# Mots (sans accents, en minuscules) qui trahissent une demande de report / d'annulation / d'indisponibilité
MOTS_REPORT = (
    "report", "reporte", "reporter", "decaler", "decale", "deplacer", "deplace", "repousser", "reprogramm",
    "changer", "changement", "modifier", "annul", "autre jour", "autre date", "autre heure", "plus tard",
    "pas disponible", "indisponible", "pas pu venir", "pas venir", "ne pourrai", "ne peux pas", "ne pourrais",
    "empeche", "empechement", "retard",
)


def _sans_accents(texte: str) -> str:
    """Minuscules sans accents, pour comparer « Reporté » et « reporte »."""
    base = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in base if unicodedata.category(c) != "Mn").lower()


def chiffres(valeur: Any) -> str:
    """Ne garde que les chiffres d'un numéro."""
    return "".join(c for c in str(valeur or "") if c.isdigit())


def meme_numero(a: Any, b: Any) -> bool:
    """Deux numéros désignent le même abonné si leurs 8 derniers chiffres sont égaux (+226 70 00 11 22 = 70001122)."""
    x, y = chiffres(a), chiffres(b)
    return len(x) >= 8 and len(y) >= 8 and x[-8:] == y[-8:]


def est_demande_report(texte: str) -> bool:
    """Vrai si le message ressemble à une demande de report / d'annulation / d'indisponibilité."""
    t = _sans_accents(texte)
    return any(mot in t for mot in MOTS_REPORT)


# Liste FINIE des pictogrammes proposés en tête du message (choix dans une liste déroulante de l'écran de réglage)
EMOJIS = ("📞", "☎️", "🏥", "🩺", "📅", "🕒", "ℹ️", "⚠️", "🙏", "👋", "✅", "💬")


def emoji_valide(valeur: Any) -> str:
    """Pictogramme accepté seulement s'il est dans la liste ; sinon vide (aucun pictogramme)."""
    v = str(valeur or "").strip()
    return v if v in EMOJIS else ""


def normaliser_reponses(brut: Any) -> List[Dict[str, str]]:
    """Nettoie la liste des réponses par client : code en majuscules sans espaces, doublons retirés (le dernier gagne),
    pictogramme limité à la liste proposée."""
    par_code: Dict[str, Dict[str, str]] = {}
    for ligne in brut if isinstance(brut, list) else []:
        if not isinstance(ligne, dict):
            continue
        code = str(ligne.get("code_clinique") or "").strip()
        message = str(ligne.get("message") or "").strip()
        if code and message:
            par_code[code.upper()] = {"code_clinique": code.upper(), "message": message[:1000], "emoji": emoji_valide(ligne.get("emoji"))}
    return list(par_code.values())


def message_pour_clinique(reglages: Dict[str, Any], code_clinique: Optional[str]) -> str:
    """Message réglé pour ce client (comparaison sans casse), sinon le message par défaut, sinon vide.
    Le pictogramme choisi est placé en tête ; les numéros de téléphone sont rendus cliquables (voir `lier_numeros`)."""
    code = (code_clinique or "").strip().upper()
    indicatif = chiffres(reglages.get("planning_report_indicatif")) or INDICATIF_DEFAUT
    for ligne in normaliser_reponses(reglages.get("planning_report_reponses")):
        if ligne["code_clinique"] == code:
            return composer(ligne["emoji"], ligne["message"], indicatif)
    defaut = str(reglages.get("planning_report_defaut") or "").strip()
    return composer(emoji_valide(reglages.get("planning_report_defaut_emoji")), defaut, indicatif) if defaut else ""


# Indicatif pays ajouté aux numéros locaux à 8 chiffres (Burkina Faso) ; réglable : planning_report_indicatif
INDICATIF_DEFAUT = "226"
# Un numéro à 8 chiffres, éventuellement précédé d'un préfixe international « +226 » (alors laissé tel quel)
_NUMERO_LOCAL = re.compile(r"(\+\d{1,3}[ .]?)?(?<![\d])(\d{2})[ .]?(\d{2})[ .]?(\d{2})[ .]?(\d{2})(?!\d)")


def lier_numeros(texte: str, indicatif: str = INDICATIF_DEFAUT) -> str:
    """Met chaque numéro local à 8 chiffres au format international « +226 78 26 79 00 ».
    WhatsApp reconnaît alors le numéro et le rend cliquable : un appui ouvre le compositeur du téléphone (ou propose d'appeler).
    Les numéros déjà au format « +… » ne sont pas touchés ; « 78267900/70463624 » donne deux numéros cliquables."""
    def remplacer(m):
        if m.group(1):          # déjà international : on ne change rien
            return m.group(0)
        return f"+{indicatif} {m.group(2)} {m.group(3)} {m.group(4)} {m.group(5)}"
    return _NUMERO_LOCAL.sub(remplacer, texte or "")


def composer(emoji: str, message: str, indicatif: str = INDICATIF_DEFAUT) -> str:
    """Message final : pictogramme en tête (s'il y en a un) puis le texte avec ses numéros cliquables."""
    corps = lier_numeros(message, indicatif)
    return f"{emoji} {corps}" if emoji else corps


def remplir(message: str, rdv: Dict[str, Any]) -> str:
    """Remplace {patient}, {medecin}, {code_clinique} ; un marqueur inconnu reste tel quel (jamais d'erreur)."""
    valeurs = {"patient": rdv.get("patient") or "", "medecin": rdv.get("medecin") or "",
               "code_clinique": rdv.get("code_clinique") or ""}
    return re.sub(r"\{(patient|medecin|code_clinique)\}", lambda m: valeurs[m.group(1)], message)


async def rdv_rappele(db, phone_digits: str, maintenant: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """RDV le plus récemment rappelé à ce numéro (dans les dernières 24 h) et pas encore traité par cette réponse.
    Une seule lecture en bloc des rappels récents, regroupée en mémoire (pas de boucle N+1)."""
    depuis = ((maintenant or datetime.now(timezone.utc)) - timedelta(hours=FENETRE_HEURES)).isoformat()
    curseur = db.planning_appointments.find(
        {"reminder_sent_at": {"$gte": depuis}, "reminder_status": "sent", "report_reponse_at": {"$exists": False}},
        {"_id": 0, "id": 1, "patient": 1, "medecin": 1, "code_clinique": 1, "patient_phone": 1, "reminder_sent_at": 1},
    ).sort("reminder_sent_at", -1).limit(500)
    async for rdv in curseur:
        if meme_numero(rdv.get("patient_phone"), phone_digits):
            return rdv
    return None


async def repondre_report_rdv(
    db, *, phone_digits: str, texte: str, reglages: Dict[str, Any],
    envoyer: Callable[[str, str], Awaitable[Any]], numero_destinataire: str,
) -> Optional[Dict[str, Any]]:
    """Point d'entrée appelé par Liluvine pour chaque message texte reçu.
    Renvoie None si rien à faire (le traitement habituel de Liluvine continue), sinon le résultat de l'envoi."""
    if not reglages.get("planning_report_actif"):
        return None
    if not reglages.get("planning_report_repondre_tout") and not est_demande_report(texte):
        return None
    rdv = await rdv_rappele(db, phone_digits)
    if not rdv:
        return None
    message = message_pour_clinique(reglages, rdv.get("code_clinique"))
    if not message:
        return None   # clinique sans message réglé et pas de message par défaut : Liluvine répond comme d'habitude
    texte_reponse = remplir(message, rdv)
    await envoyer(numero_destinataire, texte_reponse)
    # Une seule réponse par RDV : les messages suivants du patient suivent le traitement habituel de Liluvine
    await db.planning_appointments.update_one(
        {"id": rdv["id"]},
        {"$set": {"report_reponse_at": datetime.now(timezone.utc).isoformat(), "report_reponse_code": rdv.get("code_clinique")}},
    )
    return {"ok": True, "command": "report_rdv", "code_clinique": rdv.get("code_clinique"), "reply": texte_reponse[:120]}


# Code fictif des essais « client sans ligne » : il n'existe dans aucune ligne réglée, donc le message par défaut s'applique
CODE_ESSAI_SANS_LIGNE = "ESSAI-SANS-LIGNE"


def simuler_reponse(reglages: Dict[str, Any], code_client: Optional[str]) -> Dict[str, Any]:
    """Message que Liluvine enverrait pour ce code client, avec un patient et un médecin d'exemple (boutons d'essai).
    `source` dit d'où vient le message : « ligne » (réglé pour ce client), « defaut » ou « aucun » (Liluvine répondrait comme d'habitude)."""
    code = (code_client or "").strip().upper()
    ligne = next((l for l in normaliser_reponses(reglages.get("planning_report_reponses")) if l["code_clinique"] == code), None)
    message = message_pour_clinique(reglages, code)   # pictogramme en tête + numéros cliquables, comme l'envoi réel
    source = "ligne" if ligne else ("defaut" if message else "aucun")
    exemple = {"patient": "PATIENT TEST", "medecin": "DR TEST", "code_clinique": code}
    return {"source": source, "message": remplir(message, exemple) if message else ""}
