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


def normaliser_reponses(brut: Any) -> List[Dict[str, str]]:
    """Nettoie la liste des réponses par clinique : code en majuscules sans espaces, doublons retirés (le dernier gagne)."""
    par_code: Dict[str, str] = {}
    for ligne in brut if isinstance(brut, list) else []:
        if not isinstance(ligne, dict):
            continue
        code = str(ligne.get("code_clinique") or "").strip()
        message = str(ligne.get("message") or "").strip()
        if code and message:
            par_code[code.upper()] = message[:1000]
    return [{"code_clinique": c, "message": m} for c, m in par_code.items()]


def message_pour_clinique(reglages: Dict[str, Any], code_clinique: Optional[str]) -> str:
    """Message réglé pour cette clinique (comparaison sans casse), sinon le message par défaut, sinon vide."""
    code = (code_clinique or "").strip().upper()
    for ligne in normaliser_reponses(reglages.get("planning_report_reponses")):
        if ligne["code_clinique"] == code:
            return ligne["message"]
    return str(reglages.get("planning_report_defaut") or "").strip()


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
