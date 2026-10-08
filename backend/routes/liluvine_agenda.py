# liluvine_agenda.py — Lot 70 : agenda d'appels de Liluvine (appels SORTANTS planifiés) et anniversaires.
#
# Principe :
#   1. AGENDA (collection db.liluvine_agenda) : chaque évènement dit à Liluvine QUI appeler, QUAND, POURQUOI
#      (type : relance, prospection, anniversaire, suivi client, compte rendu de maintenance, rappel de
#      rendez-vous, autre), avec un objectif libre, les informations à recueillir (questions typées), un texte
#      à lire, un contexte (ou le résumé d'une fiche de maintenance), la ligne WhatsApp appelante, une
#      récurrence, un nombre de tentatives, une plage horaire et une priorité.
#   2. MOTEUR (toutes les minutes, APScheduler) : les évènements échus sont « réclamés » de façon ATOMIQUE
#      (mise à jour conditionnelle dans MongoDB : si plusieurs serveurs tournent, un seul gagne) ; le moteur
#      respecte la plage horaire autorisée et la limite d'appels simultanés de Liluvine (lot 69).
#   3. AUTORISATION (exigée par Meta pour tout appel émis par l'entreprise) : si le contact n'a pas autorisé
#      les appels, Liluvine lui envoie UNE demande d'autorisation (message interactif call_permission_request,
#      avec une courte explication), l'évènement passe « en attente d'autorisation » ; il repart dès que la
#      réponse arrive (webhook) ou à la tentative suivante ; sans autorisation au bout du délai réglé, un
#      message WhatsApp de repli (facultatif) reprend le contenu de l'appel.
#   4. APPEL : le SERVEUR appelle (offre SDP aiortc, action « connect » de l'API Calling, comme au lot 67),
#      puis Liluvine converse avec le moteur du lot 69 (classe Conversation : écoute, transcription OpenAI,
#      réponses Claude Haiku avec son prompt système + base de connaissances + objectif de l'évènement,
#      voix du lot 69.2). Ouverture : salutation + motif + texte à lire ; puis les questions, naturellement.
#   5. APRÈS L'APPEL : extraction par l'IA, en JSON, des informations demandées (+ confiance), résumé, action
#      suivante suggérée (option : créer automatiquement l'évènement de relance) ; coût estimé (tarifs du
#      lot 67.1, tranches de 6 s) ; tout est écrit dans l'évènement ET dans le journal des appels
#      (db.wa_appels, direction « sortant », motif = type), visible dans le fil de conversation du contact.
#   6. SANS RÉPONSE / OCCUPÉ / REFUSÉ : nouvelles tentatives selon les réglages, puis « sans réponse » et
#      message WhatsApp de repli facultatif.
#   7. ANNIVERSAIRES : chaque utilisateur suivi qui a une date de naissance et un numéro WhatsApp reçoit, chaque
#      année, un évènement « Anniversaire » (UN par personne et par an : identifiant fixe « anniv-<id>-<année> »)
#      à l'heure réglée ; Liluvine lit le texte (variables {prenom} {nom} {age} {entreprise}, réécriture légère
#      par l'IA en option), peut répéter le message, remercie et raccroche.
#      Choix pour les personnes nées un 29 février : les années non bissextiles, l'appel a lieu le 28 février.
#
# Réglages dans db.settings {_id: "global"}, préfixe liluvine_agenda_ (aucun secret) — voir CHAMPS.
# Clés (variables d'environnement Render, jamais dans le code) : les mêmes que le lot 69
# (OPENAI_API_KEY, ANTHROPIC_API_KEY, ELEVENLABS_API_KEY facultative, APPEL_TURN_* facultatives).
# Heures : Africa/Ouagadougou (= UTC toute l'année) ; dates stockées en ISO UTC.
#
# Lot 71 — « Mode de l'appel » : « prompt » (objectif + questions, comportement du lot 70 inchangé) ou
# « formulaire » : les champs d'un formulaire SAWALI deviennent les questions (voir
# liluvine_agenda_formulaire.py) ; à la fin, une vraie réponse au formulaire est créée (source « appel
# Liluvine ») et le lien du formulaire peut être envoyé par WhatsApp (réglage lien_formulaire).
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo   # lot 72 : heure locale (Ouagadougou) du prochain essai dans les alertes
from typing import Any, Dict, List, Optional, Tuple

import routes.appel_proprietaire as ap
import routes.liluvine_agenda_formulaire as fm   # lot 71 : appels basés sur un formulaire
import routes.liluvine_decroche as ld

logger = logging.getLogger("sawali.liluvine_agenda")

# Collection des évènements de l'agenda
COLLECTION = "liluvine_agenda"
# Types d'évènements (clé → libellé affiché et inscrit comme motif au journal des appels)
TYPES = {
    "relance": "Relance", "prospection": "Recherche de prospects", "anniversaire": "Anniversaire",
    "suivi_client": "Suivi client", "compte_rendu_maintenance": "Compte rendu de maintenance",
    "rappel_rdv": "Rappel de rendez-vous", "autre": "Autre",
}
# Motif de l'appel prononcé dans l'ouverture (« Je vous appelle … »)
MOTIFS_PARLES = {
    "relance": "pour faire suite à notre dernier échange",
    "prospection": "pour vous présenter brièvement ce que nous proposons",
    "suivi_client": "pour prendre de vos nouvelles et savoir si tout se passe bien avec nos services",
    "compte_rendu_maintenance": "pour vous faire le compte rendu de la maintenance de votre équipement",
    "rappel_rdv": "pour vous rappeler votre rendez-vous",
    "autre": "",
}
# Statuts d'un évènement (clé → libellé)
STATUTS = {
    "planifie": "Planifié", "attente_autorisation": "En attente d'autorisation", "en_cours": "En cours",
    "termine": "Terminé", "sans_reponse": "Sans réponse", "echec": "Échec", "annule": "Annulé",
}
# Récurrences proposées
RECURRENCES = ("aucune", "quotidienne", "hebdomadaire", "mensuelle", "annuelle")
# Types de réponse attendus pour les informations à recueillir
TYPES_QUESTION = ("texte", "oui_non", "date", "montant", "choix")
# Priorités (ordre de traitement : haute d'abord)
PRIORITES = {"haute": 0, "normale": 1, "basse": 2}
# Lot 71 — mode de l'appel : « prompt » (objectif + questions, lot 70) ou « formulaire » (champs d'un formulaire)
MODES_APPEL = ("prompt", "formulaire")
# Instance du serveur (inscrite dans le verrou d'un évènement réclamé)
INSTANCE = uuid.uuid4().hex[:12]
# Nombre maximal d'évènements lancés par passage du moteur (une minute)
LANCEMENTS_PAR_MINUTE = 10
# Délai minimal entre deux générations des anniversaires (secondes)
GENERATION_ANNIV_S = 600

# Texte d'anniversaire par défaut (variables : {prenom} {nom} {age} {entreprise})
ANNIV_TEXTE_DEFAUT = (
    "Bonjour {prenom} ! Ici Liluvine, de la part de toute l'équipe {entreprise}. Aujourd'hui est un jour "
    "spécial : nous vous souhaitons un très joyeux anniversaire ! Que cette nouvelle année vous apporte la "
    "santé, la joie et la réussite dans tous vos projets. Belle journée à vous !"
)
# Consigne d'appel SORTANT ajoutée au prompt système de Liluvine
CONSIGNE_SORTANT = (
    "\n\n[IMPORTANT — Tu es AU TÉLÉPHONE : c'est TOI qui appelles (appel WhatsApp sortant planifié)]\n"
    "- Tu parles à voix haute : réponses courtes, 1 à 2 phrases, ton chaleureux, poli et naturel.\n"
    "- Pas de listes, pas de puces, pas d'emojis, pas de liens, pas de markdown ; écris les nombres comme on les dit.\n"
    + ld.STYLE_ORAL +
    "- Respecte le temps de la personne : si elle n'est pas disponible, propose de rappeler plus tard, "
    f"remercie, dis au revoir et termine par {ld.MARQUEUR_FIN}.\n"
    "- Pose UNE seule question à la fois, reformule si la réponse n'est pas claire, n'insiste pas si la "
    "personne ne veut pas répondre.\n"
    "- Si la transcription semble incomplète ou incompréhensible, demande poliment de répéter.\n"
    f"- Quand l'objectif est atteint (ou que la personne veut terminer), dis au revoir en une phrase et termine par {ld.MARQUEUR_FIN}.\n"
    "- N'invente jamais d'informations ; ne donne aucune donnée confidentielle."
)
# Consigne particulière d'un appel d'anniversaire
CONSIGNE_ANNIVERSAIRE = (
    "\n- C'est un appel d'ANNIVERSAIRE : tu viens de lire le message de vœux. Réponds très brièvement "
    f"(remerciements, vœux), ne propose aucun service, dis au revoir chaleureusement et termine par {ld.MARQUEUR_FIN}."
)
# Phrases dites dans les cas particuliers d'un appel sortant
TEXTE_SILENCE_SORTANT = "Je ne vous entends plus. Je vous recontacterai. Excellente journée, au revoir."
TEXTE_DUREE_MAX_SORTANT = "Je ne veux pas vous retenir plus longtemps. Merci pour votre temps, au revoir."
TEXTE_SANS_STT_SORTANT = ("Je ne peux pas encore écouter vos réponses sur cette ligne : un conseiller vous "
                          "recontactera. Merci et au revoir.")

# Tâches d'arrière-plan (référence gardée, sinon Python peut les supprimer)
_taches: set = set()
# Index créés (une fois par processus)
_index_ok = False
# Dernière génération des anniversaires (horloge monotone)
_derniere_generation: Optional[float] = None


# ---------------------------------------------------------------------------
# Petits outils : horloge, dates, textes
# ---------------------------------------------------------------------------

def _maintenant() -> datetime:
    """Date et heure actuelles (UTC = heure de Ouagadougou) — horloge du lot 67 (simulée dans les tests)."""
    return ap._maintenant()


def _iso(dt: datetime) -> str:
    """Date → texte ISO UTC à la seconde (format unique : les comparaisons de textes restent justes)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def lire_date_heure(valeur: Any) -> Optional[datetime]:
    """« 2026-10-06T09:30 » (heure de Ouagadougou = UTC), ISO complet ou datetime → datetime UTC."""
    if not valeur:
        return None
    dt = ap.lire_date(valeur)
    return dt.astimezone(timezone.utc) if dt else None


def formater(dt: Optional[datetime]) -> str:
    """Date → « JJ/MM/AAAA HH:MM » (heure de Ouagadougou)."""
    return ap.formater_date(dt) if dt else ""


def lire_date_naissance(valeur: Any) -> Optional[date]:
    """Date de naissance « AAAA-MM-JJ » ou « JJ/MM/AAAA » → date (None si absente ou invalide)."""
    texte = str(valeur or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texte[:10]):
            return date.fromisoformat(texte[:10])
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texte)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def est_bissextile(annee: int) -> bool:
    """Année bissextile (29 février) ?"""
    return annee % 4 == 0 and (annee % 100 != 0 or annee % 400 == 0)


def anniversaire_de(naissance: date, annee: int) -> date:
    """Jour de l'anniversaire une année donnée. Choix documenté : né un 29 février → 28 février les
    années non bissextiles (on reste dans le mois de naissance)."""
    if naissance.month == 2 and naissance.day == 29 and not est_bissextile(annee):
        return date(annee, 2, 28)
    return date(annee, naissance.month, naissance.day)


def prochain_anniversaire(naissance: date, aujourd_hui: date) -> date:
    """Prochain anniversaire (aujourd'hui compris)."""
    jour = anniversaire_de(naissance, aujourd_hui.year)
    return jour if jour >= aujourd_hui else anniversaire_de(naissance, aujourd_hui.year + 1)


def age_a(naissance: date, jour: date) -> int:
    """Âge atteint à une date (l'anniversaire du 28/02 compte pour un 29/02 les années non bissextiles)."""
    age = jour.year - naissance.year
    if jour < anniversaire_de(naissance, jour.year):
        age -= 1
    return max(0, age)


def separer_nom(nom_complet: str) -> Tuple[str, str]:
    """« OUOBA Jean-François » → (« Jean-François », « OUOBA ») : un mot TOUT EN MAJUSCULES est le nom de
    famille ; sinon le premier mot est le prénom (« Awa Kaboré » → (« Awa », « Kaboré »))."""
    mots = [m for m in re.split(r"\s+", (nom_complet or "").strip()) if m]
    if not mots:
        return "", ""
    majuscules = [m for m in mots if len(m) > 1 and m.isupper()]
    if majuscules and len(majuscules) < len(mots):
        prenom = " ".join(m for m in mots if m not in majuscules)
        return prenom, " ".join(majuscules)
    return mots[0], " ".join(mots[1:])


def rendre_modele(modele: str, variables: Dict[str, Any]) -> str:
    """Remplace {prenom} {nom} {age} {entreprise}… dans un texte ; une variable inconnue reste telle quelle."""
    def remplacer(m):
        cle = m.group(1).lower()
        return str(variables[cle]) if cle in variables and variables[cle] not in (None, "") else (
            "" if cle in variables else m.group(0))
    texte = re.sub(r"\{([A-Za-zéè_]+)\}", remplacer, modele or "")
    # Variable vide : espaces doublés retirés, pas d'espace avant une virgule ou un point
    return re.sub(r"[ \t]+([,.])", r"\1", re.sub(r"[ \t]{2,}", " ", texte)).strip()


def prochaine_occurrence(dt: datetime, recurrence: str) -> Optional[datetime]:
    """Date suivante d'un évènement récurrent (None si « aucune »). Mensuelle : même jour le mois suivant
    (ramené au dernier jour du mois s'il n'existe pas, ex. 31 → 30) ; annuelle : 29/02 → 28/02."""
    if recurrence == "quotidienne":
        return dt + timedelta(days=1)
    if recurrence == "hebdomadaire":
        return dt + timedelta(days=7)
    if recurrence == "mensuelle":
        import calendar
        annee, mois = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
        jour = min(dt.day, calendar.monthrange(annee, mois)[1])
        return dt.replace(year=annee, month=mois, day=jour)
    if recurrence == "annuelle":
        j = anniversaire_de(dt.date(), dt.year + 1)
        return dt.replace(year=j.year, month=j.month, day=j.day)
    return None


def _minutes(texte: Any, defaut: str) -> int:
    """« 08:00 » → minutes depuis minuit."""
    return ap._heure_minutes(texte, defaut)


def dans_plage(dt: datetime, debut: str, fin: str, jours: List[int]) -> bool:
    """L'instant (heure de Ouagadougou) est-il dans la plage horaire et les jours autorisés ?"""
    d = ap._local(dt)
    if d.isoweekday() not in jours:
        return False
    a, b = _minutes(debut, "08:00"), _minutes(fin, "20:00")
    m = d.hour * 60 + d.minute
    if a == b:
        return True
    if a < b:
        return a <= m < b
    return m >= a or m < b


def prochain_creneau(dt: datetime, debut: str, fin: str, jours: List[int]) -> datetime:
    """Premier instant autorisé à partir de dt (recherche minute par minute bornée à 8 jours, par pas de 15 min)."""
    d = ap._local(dt).replace(second=0, microsecond=0)
    if dans_plage(d, debut, fin, jours):
        return d
    # Début de plage le jour même ou les jours suivants
    a = _minutes(debut, "08:00")
    for n in range(0, 9):
        jour = (d + timedelta(days=n)).replace(hour=a // 60, minute=a % 60)
        if jour > d and dans_plage(jour, debut, fin, jours):
            return jour.astimezone(timezone.utc)
    return (d + timedelta(hours=1)).astimezone(timezone.utc)


def _chiffres(valeur: Any) -> str:
    """Chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def reglages_agenda(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages de l'agenda, complétés par les valeurs par défaut."""
    s = s or {}
    e = ap._entier
    return {
        # Moteur actif par défaut : les évènements sont créés volontairement par l'équipe
        "actif": s.get("liluvine_agenda_actif") is not False,
        "ligne": (s.get("liluvine_agenda_ligne") or "principal").strip() or "principal",
        "plage_debut": s.get("liluvine_agenda_plage_debut") or "08:00",
        "plage_fin": s.get("liluvine_agenda_plage_fin") or "20:00",
        "jours": ld._jours(s.get("liluvine_agenda_jours") or "1,2,3,4,5,6"),
        "tentatives_max": e(s.get("liluvine_agenda_tentatives_max"), 3, 1, 10),
        "intervalle_min": e(s.get("liluvine_agenda_intervalle_min"), 30, 5, 1440),
        "sonnerie_s": e(s.get("liluvine_agenda_sonnerie_s"), 30, 10, 60),
        "attente_autorisation_h": e(s.get("liluvine_agenda_attente_autorisation_h"), 48, 1, 168),
        "repli_message": s.get("liluvine_agenda_repli_message") is not False,
        "repli_modele": (s.get("liluvine_agenda_repli_modele") or "").strip(),
        "repli_modele_langue": (s.get("liluvine_agenda_repli_modele_langue") or "fr").strip() or "fr",
        "relance_auto": bool(s.get("liluvine_agenda_relance_auto")),
        # Lot 73 — demande d'autorisation d'appel renvoyée automatiquement après 24 h sans réponse
        # (limites Meta : 1 par 24 h, 2 par 7 jours) ; activé par défaut
        "relance_autorisation": s.get("liluvine_agenda_relance_autorisation") is not False,
        "duree_max_min": e(s.get("liluvine_agenda_duree_max_min"), 5, 1, 30),
        "silence_s": e(s.get("liluvine_agenda_silence_s"), 15, 5, 120),
        # Anniversaires des utilisateurs suivis
        "anniv_actif": s.get("liluvine_agenda_anniv_actif") is not False,
        "anniv_heure": s.get("liluvine_agenda_anniv_heure") or "09:00",
        "anniv_texte": (s.get("liluvine_agenda_anniv_texte") or "").strip() or ANNIV_TEXTE_DEFAUT,
        "anniv_ia": bool(s.get("liluvine_agenda_anniv_ia")),
        "anniv_ligne": (s.get("liluvine_agenda_anniv_ligne") or "").strip(),
        "anniv_repli": s.get("liluvine_agenda_anniv_repli") is not False,
        "anniv_repetitions": e(s.get("liluvine_agenda_anniv_repetitions"), 1, 1, 3),
    }


CHAMPS = {
    "liluvine_agenda_actif": bool, "liluvine_agenda_ligne": str, "liluvine_agenda_plage_debut": str,
    "liluvine_agenda_plage_fin": str, "liluvine_agenda_jours": str, "liluvine_agenda_tentatives_max": int,
    "liluvine_agenda_intervalle_min": int, "liluvine_agenda_sonnerie_s": int,
    "liluvine_agenda_attente_autorisation_h": int, "liluvine_agenda_repli_message": bool,
    "liluvine_agenda_repli_modele": str, "liluvine_agenda_repli_modele_langue": str,
    "liluvine_agenda_relance_auto": bool, "liluvine_agenda_relance_autorisation": bool,   # lot 73
    "liluvine_agenda_duree_max_min": int, "liluvine_agenda_silence_s": int,
    "liluvine_agenda_anniv_actif": bool, "liluvine_agenda_anniv_heure": str, "liluvine_agenda_anniv_texte": str,
    "liluvine_agenda_anniv_ia": bool, "liluvine_agenda_anniv_ligne": str, "liluvine_agenda_anniv_repli": bool,
    "liluvine_agenda_anniv_repetitions": int,
}


# ---------------------------------------------------------------------------
# Validation d'un évènement (création / modification)
# ---------------------------------------------------------------------------

def nettoyer_questions(brut: Any) -> List[Dict[str, Any]]:
    """Informations à recueillir → liste propre [{id, libelle, type, choix}] (15 au plus). Lève ValueError."""
    sortie: List[Dict[str, Any]] = []
    for i, q in enumerate(brut or []):
        if isinstance(q, str):
            q = {"libelle": q}
        if not isinstance(q, dict):
            continue
        libelle = str(q.get("libelle") or "").strip()[:300]
        if not libelle:
            continue
        genre = str(q.get("type") or "texte").strip()
        if genre not in TYPES_QUESTION:
            raise ValueError(f"Type de réponse inconnu : {genre}")
        choix = [str(c).strip()[:80] for c in (q.get("choix") or []) if str(c).strip()][:12]
        if genre == "choix" and len(choix) < 2:
            raise ValueError(f"La question « {libelle} » attend au moins deux choix")
        qid = re.sub(r"[^a-z0-9_]", "", str(q.get("id") or "").lower())[:20] or f"q{i + 1}"
        if any(x["id"] == qid for x in sortie):
            qid = f"q{i + 1}_{len(sortie)}"
        sortie.append({"id": qid, "libelle": libelle, "type": genre, "choix": choix if genre == "choix" else []})
    if len(sortie) > 15:
        raise ValueError("15 informations à recueillir au plus")
    return sortie


def valider_evenement(payload: Dict[str, Any], cfga: Dict[str, Any]) -> Dict[str, Any]:
    """Contrôle et normalise les champs saisis (fonction pure, testée). Lève ValueError (message en français)."""
    p = payload or {}
    quand = lire_date_heure(p.get("date_heure"))
    if not quand:
        raise ValueError("Date et heure obligatoires (JJ/MM/AAAA HH:MM)")
    genre = str(p.get("type") or "").strip()
    if genre not in TYPES:
        raise ValueError("Type d'évènement inconnu")
    contact = p.get("contact") or {}
    tel = _chiffres(contact.get("telephone") or p.get("telephone"))
    if len(tel) < 8:
        raise ValueError("Numéro WhatsApp du contact obligatoire (8 chiffres au moins, indicatif compris)")
    nom = str(contact.get("nom") or "").strip()[:160] or f"+{tel}"
    recurrence = str(p.get("recurrence") or "aucune")
    if recurrence not in RECURRENCES:
        raise ValueError("Récurrence inconnue")
    priorite = str(p.get("priorite") or "normale")
    if priorite not in PRIORITES:
        raise ValueError("Priorité inconnue (haute, normale, basse)")
    for cle in ("plage_debut", "plage_fin"):
        if p.get(cle) and not re.fullmatch(r"\d{1,2}[:hH]\d{2}", str(p[cle])):
            raise ValueError("Plage horaire attendue au format HH:MM")
    source = str(contact.get("source") or "libre")
    if source not in ("contact", "client", "suivi", "libre"):
        source = "libre"
    # Lot 71 — mode de l'appel : prompt (lot 70, inchangé) ou formulaire (identifiant du formulaire choisi)
    mode = str(p.get("mode") or "prompt").strip()
    if mode not in MODES_APPEL:
        raise ValueError("Mode de l'appel inconnu (prompt ou formulaire)")
    formulaire = None
    if mode == "formulaire":
        fid = str((p.get("formulaire") or {}).get("id") if isinstance(p.get("formulaire"), dict)
                  else (p.get("formulaire_id") or "")).strip()[:80]
        if not fid:
            raise ValueError("Choisissez le formulaire sur lequel Liluvine base l'appel")
        formulaire = {"id": fid}
    lien_formulaire = str(p.get("lien_formulaire") or "auto")
    if lien_formulaire not in fm.REGLAGES_LIEN:
        lien_formulaire = "auto"
    maintenance = p.get("maintenance") or None
    if maintenance and not (isinstance(maintenance, dict) and maintenance.get("id")
                            and maintenance.get("source") in ("maintenance", "intervention")):
        maintenance = None
    return {
        "date_heure": _iso(quand), "type": genre,
        "titre": (str(p.get("titre") or "").strip()[:160] or f"{TYPES[genre]} — {nom}"),
        "contact": {"source": source, "id": str(contact.get("id") or "")[:80] or None, "nom": nom,
                    "telephone": tel, "entreprise": str(contact.get("entreprise") or "").strip()[:160] or None},
        "telephone": tel,
        "objectif": str(p.get("objectif") or "").strip()[:3000],
        # En mode formulaire, les questions viennent des champs du formulaire (questions libres ignorées)
        "questions": nettoyer_questions(p.get("questions")) if mode == "prompt" else [],
        "mode": mode, "formulaire": formulaire, "lien_formulaire": lien_formulaire,
        "texte_a_lire": str(p.get("texte_a_lire") or "").strip()[:3000],
        "contexte": str(p.get("contexte") or "").strip()[:4000],
        "maintenance": {"source": maintenance["source"], "id": str(maintenance["id"])[:80]} if maintenance else None,
        "ligne_cle": (str(p.get("ligne_cle") or "").strip()[:80] or None),
        "recurrence": recurrence,
        "tentatives_max": ap._entier(p.get("tentatives_max"), cfga["tentatives_max"], 1, 10),
        "intervalle_min": ap._entier(p.get("intervalle_min"), cfga["intervalle_min"], 5, 1440),
        "plage_debut": (str(p.get("plage_debut") or "").strip() or None),
        "plage_fin": (str(p.get("plage_fin") or "").strip() or None),
        "priorite": priorite,
        "creer_relance": bool(p.get("creer_relance")),
    }


# ---------------------------------------------------------------------------
# Décision d'exécution (fonction pure, testée) : plage horaire, simultanéité
# ---------------------------------------------------------------------------

def decision_execution(ev: Dict[str, Any], cfga: Dict[str, Any], maintenant: datetime, *, occupes: int,
                       max_simultanes: int, force: bool = False) -> Dict[str, Any]:
    """→ {action: appeler | reporter | annuler, a (ISO, si reporter), raison}."""
    if ev.get("type") == "anniversaire" and not cfga["anniv_actif"]:
        return {"action": "annuler", "raison": "appels d'anniversaire désactivés"}
    if len(_chiffres(ev.get("telephone"))) < 8:
        return {"action": "annuler", "raison": "numéro du contact manquant"}
    if not force:
        debut = ev.get("plage_debut") or cfga["plage_debut"]
        fin = ev.get("plage_fin") or cfga["plage_fin"]
        if not dans_plage(maintenant, debut, fin, cfga["jours"]):
            a = prochain_creneau(maintenant, debut, fin, cfga["jours"])
            return {"action": "reporter", "a": _iso(a), "raison": f"hors plage horaire autorisée ({debut}–{fin})"}
    if occupes >= max_simultanes:
        return {"action": "reporter", "a": _iso(maintenant + timedelta(minutes=2)),
                "raison": f"déjà {occupes} appel(s) en cours avec Liluvine (limite {max_simultanes})"}
    return {"action": "appeler", "raison": "ok"}


# ---------------------------------------------------------------------------
# Extraction des informations après l'appel (réponse de l'IA en JSON, lecture robuste)
# ---------------------------------------------------------------------------

def _json_tolerant(texte: str) -> Optional[Dict[str, Any]]:
    """Lit le premier objet JSON d'un texte (blocs ```json, virgules finales, apostrophes) ; None si illisible."""
    t = (texte or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.I | re.M).strip()
    debut, fin = t.find("{"), t.rfind("}")
    if debut < 0 or fin <= debut:
        return None
    bloc = t[debut:fin + 1]
    for essai in (bloc, re.sub(r",\s*([}\]])", r"\1", bloc),
                  re.sub(r",\s*([}\]])", r"\1", bloc).replace("'", '"')):
        try:
            v = json.loads(essai)
            return v if isinstance(v, dict) else None
        except (ValueError, TypeError):
            continue
    return None


def normaliser_valeur(valeur: Any, question: Dict[str, Any]) -> Any:
    """Valeur extraite → type attendu (None si absente ou incohérente)."""
    if valeur is None or (isinstance(valeur, str) and valeur.strip().lower() in ("", "null", "none", "inconnu", "n/a")):
        return None
    genre = question.get("type")
    if genre == "oui_non":
        if isinstance(valeur, bool):
            return valeur
        v = str(valeur).strip().lower()
        if v in ("oui", "yes", "true", "vrai", "1", "d'accord", "ok"):
            return True
        if v in ("non", "no", "false", "faux", "0"):
            return False
        return None
    if genre == "montant":
        if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
            return valeur
        brut = re.sub(r"[^\d,.\-]", "", str(valeur)).replace(",", ".")
        try:
            n = float(brut)
            return int(n) if n.is_integer() else n
        except ValueError:
            return None
    if genre == "date":
        d = lire_date_naissance(valeur)
        return d.isoformat() if d else None
    if genre == "choix":
        v = str(valeur).strip().lower()
        for c in question.get("choix") or []:
            if c.lower() == v:
                return c
        for c in question.get("choix") or []:
            if c.lower() in v or v in c.lower():
                return c
        return None
    return str(valeur).strip()[:1000]


def analyser_extraction(texte: str, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Réponse de l'IA → {resume, informations: [{id, libelle, type, valeur, confiance}], action_suivante, erreur}.
    Ne lève jamais d'exception : un texte illisible donne des informations vides et un résumé brut."""
    donnees = _json_tolerant(texte)
    erreur = None
    if donnees is None:
        erreur = "réponse de l'IA illisible (JSON attendu)"
        donnees = {}
    reponses = donnees.get("reponses") if isinstance(donnees.get("reponses"), dict) else {}
    informations = []
    for q in questions or []:
        brut = reponses.get(q["id"], reponses.get(q["libelle"]))
        confiance = None
        if isinstance(brut, dict):
            confiance = brut.get("confiance")
            brut = brut.get("valeur")
        try:
            confiance = max(0.0, min(1.0, float(confiance))) if confiance is not None else None
        except (TypeError, ValueError):
            confiance = None
        valeur = normaliser_valeur(brut, q)
        informations.append({"id": q["id"], "libelle": q["libelle"], "type": q["type"], "valeur": valeur,
                             "confiance": confiance if valeur is not None else 0.0})
    action = donnees.get("action_suivante") if isinstance(donnees.get("action_suivante"), dict) else {}
    genre = str(action.get("type") or "aucune")
    quand = lire_date_heure(str(action.get("date") or "").replace(" ", "T")) if action.get("date") else None
    resume = str(donnees.get("resume") or "").strip()
    if not resume and erreur:
        resume = re.sub(r"\s+", " ", re.sub(r"[{}\[\]\"`]", " ", texte or "")).strip()[:400]
    return {
        "resume": resume[:1500], "informations": informations, "erreur": erreur,
        "action_suivante": {"texte": str(action.get("texte") or "").strip()[:500],
                            "type": genre if genre in TYPES else "aucune",
                            "date": _iso(quand) if quand else None},
    }


SYSTEME_EXTRACTION = (
    "Tu analyses la transcription d'un appel téléphonique passé par Liluvine, l'assistante de SAWALI. "
    "Réponds UNIQUEMENT par un objet JSON valide, sans texte autour, de la forme : "
    '{"resume": "1 à 3 phrases en français", '
    '"reponses": {"<id>": {"valeur": <valeur ou null>, "confiance": <0 à 1>}}, '
    '"action_suivante": {"texte": "action conseillée", "type": "relance|suivi_client|rappel_rdv|prospection|autre|aucune", '
    '"date": "AAAA-MM-JJ HH:MM ou null"}}. '
    "Types de valeur : texte = chaîne ; oui_non = true/false ; date = AAAA-MM-JJ ; montant = nombre ; "
    "choix = un des choix proposés. Mets null si l'information n'a pas été donnée ; n'invente rien."
)


def texte_a_extraire(ev: Dict[str, Any], transcription: List[Dict[str, Any]], maintenant: datetime) -> str:
    """Message envoyé à l'IA d'extraction : objectif, questions (id, type, choix), transcription."""
    lignes = [f"Date de l'appel : {formater(maintenant)} (heure de Ouagadougou)",
              f"Type : {TYPES.get(ev.get('type'), ev.get('type'))}", f"Objectif : {ev.get('objectif') or '—'}",
              "Informations demandées :"]
    for q in ev.get("questions") or []:
        choix = f" (choix : {', '.join(q['choix'])})" if q.get("choix") else ""
        lignes.append(f"- id={q['id']} ; type={q['type']} ; question : {q['libelle']}{choix}")
    if not ev.get("questions"):
        lignes.append("- (aucune : renvoie \"reponses\": {})")
    lignes.append("\nTranscription :")
    lignes.append("\n".join(f"{'Liluvine' if t.get('qui') == 'liluvine' else 'Interlocuteur'} : {t.get('texte')}"
                            for t in transcription or [])[:12000])
    return "\n".join(lignes)


async def llm_texte(systeme: str, texte: str, max_jetons: int = 900) -> Dict[str, Any]:
    """Appel du modèle (Claude Haiku via ia_client, comme le lot 69) → {texte, entree, sortie}.
    Fonction isolée : remplacée par une imitation dans les tests."""
    from ia_client import LlmChat, UserMessage, cle_ia
    if not cle_ia("anthropic"):
        raise RuntimeError("clé ANTHROPIC_API_KEY absente")
    chat = LlmChat(session_id=f"agenda-{uuid.uuid4()}", system_message=systeme,
                   initial_messages=[]).with_model("anthropic", ld.MODELE_LLM).with_params(max_tokens=max_jetons)
    rep = await asyncio.wait_for(chat.send_message_with_tools(UserMessage(text=texte)), timeout=40)
    return {"texte": rep.content or "", "entree": rep.usage.input_tokens, "sortie": rep.usage.output_tokens}


async def personnaliser_anniversaire(texte: str, variables: Dict[str, Any]) -> str:
    """Option « personnaliser avec l'IA » : réécriture LÉGÈRE du message (même sens, même longueur) ;
    en cas d'échec, le texte d'origine est gardé."""
    try:
        r = await llm_texte("Tu réécris légèrement un message d'anniversaire lu au téléphone par Liluvine, "
                            "l'assistante de SAWALI : même sens, ton chaleureux, 4 phrases au plus, en français, "
                            "sans emoji, sans markdown, sans guillemets. Réponds uniquement par le message.",
                            f"Prénom : {variables.get('prenom')}\nMessage :\n{texte}", 300)
        nouveau = ld.analyser_reponse(r.get("texte") or "")[0]
        return nouveau if 20 <= len(nouveau) <= 1200 else texte
    except Exception:  # noqa: BLE001
        return texte


# ---------------------------------------------------------------------------
# Textes de l'appel : ouverture, prompt, message de repli, demande d'autorisation
# ---------------------------------------------------------------------------

def variables_contact(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Variables utilisables dans les textes : prénom, nom, âge, entreprise."""
    contact = ev.get("contact") or {}
    prenom, nom = separer_nom(contact.get("nom") or "")
    if re.fullmatch(r"\+?\d+", prenom or ""):
        prenom, nom = "", ""
    return {"prenom": prenom, "nom": nom, "age": ev.get("age") if ev.get("age") is not None else "",
            "entreprise": contact.get("entreprise") or "SAWALI"}


def texte_ouverture(ev: Dict[str, Any]) -> str:
    """Ouverture d'un appel sortant (hors anniversaire) : salutation, motif, texte à lire, question d'accroche."""
    v = variables_contact(ev)
    salut = f"Bonjour {v['prenom']}, ici" if v["prenom"] else "Bonjour, ici"
    morceaux = [f"{salut} Liluvine, l'assistante de SAWALI."]
    motif = MOTIFS_PARLES.get(ev.get("type") or "", "")
    if motif:
        morceaux.append(f"Je vous appelle {motif}.")
    if ev.get("texte_a_lire"):
        morceaux.append(rendre_modele(ev["texte_a_lire"], v))
    plan = ev.get("formulaire_plan") if ev.get("mode") == "formulaire" else None
    if plan:
        # Lot 71 : appel basé sur un formulaire → annonce courte (le titre du formulaire)
        morceaux.append(f"J'aimerais remplir avec vous le formulaire {fm.libelle_oral(plan.get('titre'))}, "
                        "cela ne prendra que quelques minutes.")
    morceaux.append("Avez-vous un petit moment ?" if (ev.get("questions") or ev.get("objectif") or plan
                                                      or ev.get("type") == "compte_rendu_maintenance")
                    else "Avez-vous des questions ?")
    return " ".join(m.strip() for m in morceaux if m.strip())


def assembler_prompt_sortant(base: str, ev: Dict[str, Any], ouverture: str, *, connaissances: str = "",
                             transfert: bool = True) -> str:
    """Prompt système d'un appel sortant (fonction pure, testée) : prompt de Liluvine + consigne téléphone
    sortant + base de connaissances + objectif, contexte et informations à recueillir de l'évènement."""
    morceaux = [(base or "").strip(), CONSIGNE_SORTANT,
                ld.CONSIGNE_HUMAIN if transfert else ld.CONSIGNE_SANS_HUMAIN]
    if ev.get("type") == "anniversaire":
        morceaux.append(CONSIGNE_ANNIVERSAIRE)
    if connaissances:
        morceaux.append("\n\n" + connaissances.strip())
    contact = ev.get("contact") or {}
    bloc = [f"\n\n[Appel planifié — {TYPES.get(ev.get('type'), ev.get('type'))}]",
            f"Interlocuteur : {contact.get('nom') or 'inconnu'} (+{ev.get('telephone')})"
            + (f" — {contact['entreprise']}" if contact.get("entreprise") else "")]
    if ev.get("objectif"):
        bloc.append(f"Objectif de l'appel (consignes de l'équipe) : {ev['objectif']}")
    if ev.get("contexte"):
        bloc.append(f"Contexte : {ev['contexte']}")
    if (ev.get("maintenance") or {}).get("resume"):
        bloc.append(f"Compte rendu de maintenance à présenter simplement : {ev['maintenance']['resume']}")
    if ev.get("questions"):
        bloc.append("Informations à recueillir, une question à la fois, de façon naturelle :")
        for n, q in enumerate(ev["questions"], 1):
            precision = {"oui_non": "réponse oui ou non", "date": "une date", "montant": "un montant",
                         "choix": "choix : " + ", ".join(q.get("choix") or []), "texte": ""}.get(q["type"], "")
            bloc.append(f"{n}. {q['libelle']}" + (f" ({precision})" if precision else ""))
        bloc.append(f"Quand tu as toutes les réponses (ou si la personne ne veut pas répondre), remercie, "
                    f"dis au revoir et termine par {ld.MARQUEUR_FIN}.")
    plan = ev.get("formulaire_plan") if ev.get("mode") == "formulaire" else None
    if plan:
        # Lot 71 : les champs du formulaire, dans l'ordre, avec les consignes de vérification
        bloc.append(fm.bloc_prompt(plan, lien_prevu=fm.envoyer_lien_voulu(ev.get("lien_formulaire") or "auto",
                                                                           plan, None)))
    bloc.append(f"Tu as déjà dit en ouverture : « {ouverture} »")
    morceaux.append("\n".join(bloc))
    return "".join(morceaux)


def texte_repli(ev: Dict[str, Any]) -> str:
    """Message WhatsApp de repli quand l'appel n'aboutit pas (contenu de l'appel, par écrit)."""
    v = variables_contact(ev)
    if ev.get("type") == "anniversaire":
        return ev.get("texte_a_lire") or rendre_modele(ANNIV_TEXTE_DEFAUT, v)
    salut = f"Bonjour {v['prenom']}" if v["prenom"] else "Bonjour"
    morceaux = [f"{salut}, ici Liluvine, l'assistante de SAWALI. J'ai essayé de vous joindre par téléphone"]
    motif = MOTIFS_PARLES.get(ev.get("type") or "", "")
    morceaux[0] += f" {motif}." if motif else "."
    if ev.get("texte_a_lire"):
        morceaux.append(rendre_modele(ev["texte_a_lire"], v))
    if (ev.get("maintenance") or {}).get("resume") and ev.get("type") == "compte_rendu_maintenance":
        morceaux.append(ev["maintenance"]["resume"])
    plan = ev.get("formulaire_plan") if ev.get("mode") == "formulaire" else None
    if plan and plan.get("lien") and ev.get("lien_formulaire") != "jamais":
        # Lot 71 : appel non abouti → le contact peut remplir le formulaire en ligne
        morceaux.append(f"Vous pouvez remplir le formulaire « {plan.get('titre')} » ici : {plan['lien']}")
    elif ev.get("questions"):
        morceaux.append("Pourriez-vous me répondre ici :\n" + "\n".join(f"• {q['libelle']}" for q in ev["questions"]))
    else:
        morceaux.append("N'hésitez pas à me répondre ici ou à nous rappeler.")
    return "\n".join(morceaux)[:3900]


def texte_demande_autorisation(ev: Dict[str, Any]) -> str:
    """Courte explication jointe à la demande d'autorisation d'appel (limite Meta : 1024 caractères)."""
    v = variables_contact(ev)
    salut = f"Bonjour {v['prenom']}" if v["prenom"] else "Bonjour"
    if ev.get("type") == "anniversaire":
        raison = "pour un petit appel de vœux"
    else:
        raison = MOTIFS_PARLES.get(ev.get("type") or "", "") or "pour un court échange"
    return (f"{salut}, ici Liluvine, l'assistante de SAWALI. J'aimerais vous appeler sur WhatsApp {raison}. "
            "Acceptez-vous mes appels ?")[:1024]


# ---------------------------------------------------------------------------
# Accès aux données : index, anniversaires, réclamation atomique
# ---------------------------------------------------------------------------

async def assurer_index(db) -> None:
    """Index de la collection (une fois par processus, sans erreur bloquante)."""
    global _index_ok
    if _index_ok:
        return
    try:
        col = db[COLLECTION]
        await col.create_index("id", unique=True)
        await col.create_index([("statut", 1), ("prochaine_tentative", 1)])
        await col.create_index("date_heure")
        await col.create_index("telephone")
    except Exception:  # noqa: BLE001
        logger.warning("[liluvine_agenda] index non créés", exc_info=True)
    _index_ok = True


def _nouvel_evenement(champs: Dict[str, Any], *, par: str, maintenant: datetime, ev_id: Optional[str] = None) -> Dict[str, Any]:
    """Document complet d'un nouvel évènement « planifié »."""
    doc = {"id": ev_id or str(uuid.uuid4()), **champs, "statut": "planifie", "tentatives": 0,
           "prochaine_tentative": champs["date_heure"], "historique": [], "resultat": None,
           "cree_par": par, "cree_le": _iso(maintenant), "maj_le": _iso(maintenant)}
    # Ordre de traitement : haute (0) avant normale (1) avant basse (2)
    if doc.get("priorite_ordre") is None:
        doc["priorite_ordre"] = PRIORITES.get(doc.get("priorite") or "normale", 1)
    return doc


async def _entreprise_du_client(db, client_id: Optional[str], cache: Dict[str, str]) -> str:
    """Nom de l'entreprise d'un compte client (mémorisé pendant une génération)."""
    if not client_id:
        return ""
    if client_id not in cache:
        u = await db.users.find_one({"id": client_id}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        cache[client_id] = u.get("company") or ""
    return cache[client_id]


async def generer_anniversaires(db, s: Dict[str, Any], maintenant: datetime) -> Dict[str, int]:
    """Crée / tient à jour l'évènement « Anniversaire » de chaque utilisateur suivi (UN par personne et par an,
    identifiant fixe « anniv-<id>-<année> » : deux serveurs ne peuvent pas le créer deux fois)."""
    cfga = reglages_agenda(s)
    rapport = {"crees": 0, "mis_a_jour": 0, "annules": 0}
    if not cfga["anniv_actif"]:
        return rapport
    aujourd_hui = ap._local(maintenant).date()
    h = _minutes(cfga["anniv_heure"], "09:00")
    attendus: set = set()
    cache: Dict[str, str] = {}
    col = db[COLLECTION]
    async for tu in db.tracked_users.find({"date_naissance": {"$nin": [None, ""]}}, {"_id": 0}):
        naissance = lire_date_naissance(tu.get("date_naissance"))
        tel = _chiffres(tu.get("whatsapp_number") or tu.get("phone"))
        if not naissance or len(tel) < 8 or (tu.get("status") or "active") != "active":
            continue
        jour = prochain_anniversaire(naissance, aujourd_hui)
        quand = datetime(jour.year, jour.month, jour.day, h // 60, h % 60, tzinfo=timezone.utc)
        ev_id = f"anniv-{tu['id']}-{jour.year}"
        attendus.add(ev_id)
        age = age_a(naissance, jour)
        entreprise = tu.get("company") or await _entreprise_du_client(db, tu.get("client_id"), cache) or "SAWALI"
        contact = {"source": "suivi", "id": tu["id"], "nom": tu.get("name") or f"+{tel}", "telephone": tel,
                   "entreprise": entreprise}
        champs = {
            "date_heure": _iso(quand), "type": "anniversaire",
            "titre": f"🎂 Anniversaire — {contact['nom']} ({age} ans)", "contact": contact, "telephone": tel,
            "objectif": "Souhaiter un joyeux anniversaire de la part de l'équipe, remercier et raccrocher.",
            "questions": [], "texte_a_lire": "", "contexte": "", "maintenance": None,
            "ligne_cle": cfga["anniv_ligne"] or None, "recurrence": "aucune",
            "tentatives_max": cfga["tentatives_max"], "intervalle_min": cfga["intervalle_min"],
            "plage_debut": None, "plage_fin": None, "priorite": "normale", "creer_relance": False,
            "source_anniversaire": True, "tracked_user_id": tu["id"], "client_id": tu.get("client_id"),
            "annee": jour.year, "age": age, "date_naissance": naissance.isoformat(),
        }
        existant = await col.find_one({"id": ev_id}, {"_id": 0})
        if not existant:
            try:
                await col.insert_one({"_id": ev_id, **_nouvel_evenement(champs, par="Liluvine (anniversaires)",
                                                                         maintenant=maintenant, ev_id=ev_id)})
                rapport["crees"] += 1
            except Exception:  # noqa: BLE001 — créé au même instant par un autre serveur : rien à faire
                pass
        elif existant.get("statut") == "planifie" and (
                existant.get("date_heure") != champs["date_heure"] or existant.get("telephone") != tel
                or existant.get("titre") != champs["titre"] or existant.get("ligne_cle") != champs["ligne_cle"]):
            # Date de naissance, heure réglée, numéro ou nom modifiés : l'évènement suit
            await col.update_one({"id": ev_id, "statut": "planifie"}, {"$set": {
                **{k: champs[k] for k in ("date_heure", "titre", "contact", "telephone", "age", "ligne_cle",
                                          "date_naissance")},
                "prochaine_tentative": champs["date_heure"], "maj_le": _iso(maintenant)}})
            rapport["mis_a_jour"] += 1
    # Anniversaires planifiés devenus caducs (date retirée ou changée d'année, personne désactivée)
    async for ev in col.find({"source_anniversaire": True, "statut": "planifie",
                              "date_heure": {"$gt": _iso(maintenant)}}, {"_id": 0, "id": 1}):
        if ev["id"] not in attendus:
            await col.update_one({"id": ev["id"], "statut": "planifie"}, {"$set": {
                "statut": "annule", "raison": "date de naissance retirée ou modifiée", "maj_le": _iso(maintenant)}})
            rapport["annules"] += 1
    return rapport


async def reclamer(db, maintenant: datetime, ev_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Réclamation ATOMIQUE d'un évènement échu : une seule mise à jour conditionnelle le passe « en cours »
    avec un verrou daté ; si deux serveurs essaient en même temps, un seul gagne (l'autre reçoit None).
    Les évènements restés « en cours » après l'expiration du verrou (serveur arrêté) sont repris."""
    from pymongo import ReturnDocument
    col = db[COLLECTION]
    iso = _iso(maintenant)
    verrou = _iso(maintenant + timedelta(minutes=45))
    origines = [("planifie", {"statut": "planifie", "prochaine_tentative": {"$lte": iso}}),
                ("attente_autorisation", {"statut": "attente_autorisation", "prochaine_tentative": {"$lte": iso}}),
                ("planifie", {"statut": "en_cours", "verrou_jusqua": {"$lt": iso}})]
    for origine, filtre in origines:
        if ev_id:
            filtre = {**filtre, "id": ev_id}
        doc = await col.find_one_and_update(
            filtre, {"$set": {"statut": "en_cours", "statut_avant": origine, "verrou_par": INSTANCE,
                              "verrou_jusqua": verrou, "maj_le": iso}},
            sort=[("priorite_ordre", 1), ("prochaine_tentative", 1)], return_document=ReturnDocument.AFTER)
        if doc:
            doc.pop("_id", None)              # identifiant interne MongoDB, jamais renvoyé
            return doc
    return None


async def relacher(db, ev: Dict[str, Any], a: str, raison: str) -> None:
    """Rend un évènement réclamé (report) : statut d'origine, nouvelle échéance, raison."""
    await db[COLLECTION].update_one({"id": ev["id"], "verrou_par": INSTANCE}, {"$set": {
        "statut": ev.get("statut_avant") or "planifie", "prochaine_tentative": a, "report_raison": raison,
        "verrou_par": None, "verrou_jusqua": None, "maj_le": _iso(_maintenant())}})


async def appels_en_cours_ligne(db, ligne_cle: Optional[str], sauf: str) -> int:
    """Appels de Liluvine en cours : appels de l'agenda sur cette ligne (tous serveurs) + appels entrants
    pris par Liluvine sur ce serveur (limite « appels simultanés » du lot 69)."""
    n = await db[COLLECTION].count_documents({"statut": "en_cours", "ligne_cle_effective": ligne_cle,
                                              "id": {"$ne": sauf}})
    entrants = len([c for c in ld._actifs if not str(c).startswith("agenda-")])
    return int(n) + entrants


def ligne_de(s: Dict[str, Any], cle: Optional[str]) -> Tuple[str, Optional[str]]:
    """(Phone Number ID, clé) de la ligne appelante : celle de l'évènement, sinon la ligne principale."""
    from routes.numeros_wa import ligne_par_cle
    ligne = ligne_par_cle(s, cle) if cle else None
    ligne = ligne or ligne_par_cle(s, "principal")
    return ((ligne or {}).get("phone_number_id") or (s.get("wa_phone_number_id") or "").strip(),
            (ligne or {}).get("cle") or "principal")


# ---------------------------------------------------------------------------
# Moteur : passage de chaque minute
# ---------------------------------------------------------------------------

def _lancer(coro) -> None:
    """Lance une coroutine en arrière-plan (référence gardée)."""
    tache = asyncio.get_running_loop().create_task(coro)
    _taches.add(tache)
    tache.add_done_callback(_taches.discard)


async def executer_echeances(db, *, lancer_en_fond: bool = True) -> Dict[str, Any]:
    """Tâche planifiée (chaque minute) : anniversaires, évènements échus réclamés puis lancés en arrière-plan."""
    global _derniere_generation
    await assurer_index(db)
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfga = reglages_agenda(s)
    if not cfga["actif"]:
        return {"actif": False}
    maintenant = _maintenant()
    rapport: Dict[str, Any] = {"actif": True, "lances": [], "reportes": [], "annules": []}
    if _derniere_generation is None or time.monotonic() - _derniere_generation > GENERATION_ANNIV_S:
        _derniere_generation = time.monotonic()
        try:
            rapport["anniversaires"] = await generer_anniversaires(db, s, maintenant)
        except Exception:  # noqa: BLE001
            logger.warning("[liluvine_agenda] génération des anniversaires impossible", exc_info=True)
    max_simultanes = ld.reglages_decroche(s)["max_simultanes"]
    for _ in range(LANCEMENTS_PAR_MINUTE):
        ev = await reclamer(db, maintenant)
        if not ev:
            break
        _, ligne_cle = ligne_de(s, ev.get("ligne_cle") or cfga["ligne"])
        occupes = await appels_en_cours_ligne(db, ligne_cle, ev["id"])
        d = decision_execution(ev, cfga, maintenant, occupes=occupes, max_simultanes=max_simultanes)
        if d["action"] == "reporter":
            await relacher(db, ev, d["a"], d["raison"])
            rapport["reportes"].append(ev["id"])
            continue
        if d["action"] == "annuler":
            await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {
                "statut": "annule", "raison": d["raison"], "verrou_par": None, "maj_le": _iso(maintenant)}})
            rapport["annules"].append(ev["id"])
            continue
        await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {"ligne_cle_effective": ligne_cle}})
        ld._actifs.add(f"agenda-{ev['id']}")          # place réservée (limite du lot 69)
        if lancer_en_fond:
            _lancer(executer_evenement(db, ev["id"]))
        else:
            await executer_evenement(db, ev["id"])
        rapport["lances"].append(ev["id"])
    return rapport


async def executer_evenement(db, ev_id: str) -> Dict[str, Any]:
    """Exécute un évènement réclamé : autorisation, appel, conversation, résultats. Ne lève jamais d'exception."""
    try:
        return await _executer(db, ev_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[liluvine_agenda] évènement %s en échec", ev_id, exc_info=True)
        await db[COLLECTION].update_one({"id": ev_id, "statut": "en_cours"}, {"$set": {
            "statut": "echec", "raison": f"erreur : {str(exc)[:200]}", "verrou_par": None,
            "maj_le": _iso(_maintenant())}})
        return {"resultat": "echec", "raison": str(exc)[:200]}
    finally:
        ld._actifs.discard(f"agenda-{ev_id}")


async def _executer(db, ev_id: str) -> Dict[str, Any]:
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfga = reglages_agenda(s)
    ev = await db[COLLECTION].find_one({"id": ev_id}, {"_id": 0})
    if not ev:
        return {"resultat": "absent"}
    numero_id, ligne_cle = ligne_de(s, ev.get("ligne_cle") or cfga["ligne"])
    ev = await preparer_contenu(db, s, cfga, ev)
    tel = ev["telephone"]
    # Lot 71 — appel basé sur un formulaire supprimé entre-temps : pas d'appel
    if ev.get("mode") == "formulaire" and not ev.get("formulaire_plan"):
        return await _terminer_sans_appel(db, s, cfga, ev, numero_id, "echec",
                                          "formulaire introuvable (supprimé ?) : appel annulé")
    # 1. Autorisation d'appel du contact (Meta) — un refus explicite (webhook) arrête l'évènement
    if ev.get("autorisation_refusee"):
        return await _terminer_sans_appel(db, s, cfga, ev, numero_id, "echec",
                                          "le contact a refusé les appels WhatsApp")
    perm = await ap.etat_permission(db, s, numero_id, tel)
    if not perm.get("peut_appeler"):
        return await _sans_autorisation(db, s, cfga, ev, numero_id, perm)
    # 2. Appel et conversation — lot 72 : l'administrateur et le superviseur sont prévenus (toast persistant)
    alerte_id = await alerte_debut(db, ev, ligne_cle)
    res = await appeler_et_converser(db, s, cfga, ev, numero_id=numero_id, ligne_cle=ligne_cle)
    sortie = await apres_appel(db, s, cfga, ev, res, numero_id=numero_id)
    await alerte_fin(db, alerte_id, res, sortie)
    return sortie


# ---------------------------------------------------------------------------
# Lot 72 — alertes « Liluvine appelle … » pour l'administrateur et le superviseur
# ---------------------------------------------------------------------------
# Une alerte par appel : créée quand l'appel part, complétée à la fin (résultat, résumé). Le portail la lit
# toutes les 10 s (/admin/liluvine-agenda/alertes) et l'affiche dans un toast qui reste jusqu'à sa fermeture.
COLLECTION_ALERTES = "liluvine_agenda_alertes"


async def alerte_debut(db, ev: Dict[str, Any], ligne_cle: str) -> Optional[str]:
    """Enregistre « Liluvine appelle <contact> pour <type> » ; renvoie l'identifiant (None si échec, jamais bloquant)."""
    try:
        maintenant = _iso(_maintenant())
        alerte = {
            "id": str(uuid.uuid4()), "ev_id": ev["id"], "etat": "appel",
            "type": ev.get("type"), "type_libelle": TYPES.get(ev.get("type") or "", "Appel"),
            "titre": (ev.get("titre") or "")[:120], "mode": ev.get("mode") or "prompt",
            "contact_nom": (ev.get("contact") or {}).get("nom") or f"+{ev.get('telephone')}",
            "telephone": ev.get("telephone"), "ligne_cle": ligne_cle,
            "tentative": int(ev.get("tentatives") or 0) + 1, "le": maintenant, "maj": maintenant,
        }
        await db[COLLECTION_ALERTES].insert_one(dict(alerte))
        return alerte["id"]
    except Exception:  # noqa: BLE001 — une alerte manquée ne doit jamais empêcher l'appel
        logger.exception("[agenda] alerte de début d'appel non enregistrée")
        return None


def libelle_resultat(res: Dict[str, Any], sortie: Dict[str, Any]) -> Tuple[str, str]:
    """(état, phrase) affichés dans le toast à la fin de l'appel."""
    r = res.get("resultat")
    if r == "decroche":
        return "termine", "Conversation terminée"
    if sortie.get("resultat") == "nouvelle_tentative":
        heure = ""
        try:
            heure = datetime.fromisoformat(sortie["prochaine"]).astimezone(ZoneInfo("Africa/Ouagadougou")).strftime("%H:%M")
        except Exception:  # noqa: BLE001
            pass
        motif = "appel refusé" if r == "refuse" else ("pas de réponse" if r == "sans_reponse" else (res.get("raison") or "échec"))
        return "nouvelle_tentative", f"{motif[:120]} — nouvel essai{(' à ' + heure) if heure else ''}"
    if r == "refuse":
        return "refuse", "Appel refusé par le contact"
    if r == "sans_reponse":
        return "sans_reponse", "Pas de réponse"
    return "echec", f"Échec : {(res.get('raison') or 'erreur inconnue')[:160]}"


async def alerte_fin(db, alerte_id: Optional[str], res: Dict[str, Any], sortie: Dict[str, Any]) -> None:
    """Complète l'alerte avec le résultat de l'appel (résumé de Liluvine si conversation)."""
    if not alerte_id:
        return
    try:
        etat, phrase = libelle_resultat(res, sortie)
        await db[COLLECTION_ALERTES].update_one({"id": alerte_id}, {"$set": {
            "etat": etat, "resultat": phrase, "resume": (sortie.get("resume") or "")[:400],
            "maj": _iso(_maintenant())}})
    except Exception:  # noqa: BLE001
        logger.exception("[agenda] alerte de fin d'appel non enregistrée")


async def preparer_contenu(db, s: Dict[str, Any], cfga: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    """Juste avant l'appel : texte d'anniversaire (modèle du moment, IA en option), résumé de maintenance relu."""
    maj: Dict[str, Any] = {}
    if ev.get("type") == "anniversaire" and ev.get("source_anniversaire"):
        texte = rendre_modele(cfga["anniv_texte"], variables_contact(ev))
        if cfga["anniv_ia"]:
            texte = await personnaliser_anniversaire(texte, variables_contact(ev))
        maj["texte_a_lire"] = texte
    if ev.get("maintenance") and ev["maintenance"].get("id"):
        resume = await resume_maintenance(db, ev["maintenance"]["source"], ev["maintenance"]["id"])
        if resume:
            maj["maintenance"] = {**ev["maintenance"], "resume": resume}
    if ev.get("mode") == "formulaire":
        # Lot 71 : plan de l'appel relu juste avant l'appel (le formulaire a pu changer depuis la planification)
        maj["formulaire_plan"] = await plan_de_l_evenement(db, s, ev)
    if maj:
        await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": maj})
        ev = {**ev, **maj}
    return ev


async def plan_de_l_evenement(db, s: Dict[str, Any], ev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Lot 71 — formulaire de l'évènement → plan de l'appel (champs, questions, lien public) ; None si absent."""
    fid = (ev.get("formulaire") or {}).get("id")
    form = await db.forms.find_one({"id": fid}, {"_id": 0}) if fid else None
    if not form:
        return None
    plan = fm.plan_formulaire(form)
    plan["lien"] = fm.lien_public(form, fm.base_publique(s))
    return plan


# ---------------------------------------------------------------------------
# Autorisation d'appel (Meta) : demande unique, attente, refus
# ---------------------------------------------------------------------------

async def demandes_recentes(db, tel: str, maintenant: datetime) -> Tuple[int, int]:
    """Demandes d'autorisation envoyées à ce numéro : (dernières 24 h, 7 derniers jours) — limites Meta."""
    fin = re.escape(tel[-8:]) + "$"
    filtre = {"message_type": "call_permission_request", "phone_digits": {"$regex": fin}}
    j1 = await db.whatsapp_messages.count_documents({**filtre, "created_at": {"$gte": _iso(maintenant - timedelta(hours=24))}})
    j7 = await db.whatsapp_messages.count_documents({**filtre, "created_at": {"$gte": _iso(maintenant - timedelta(days=7))}})
    return int(j1), int(j7)


async def demander_autorisation(db, s: Dict[str, Any], numero_id: str, ev: Dict[str, Any],
                                maintenant: datetime) -> Dict[str, Any]:
    """Envoie au contact la demande d'autorisation d'appel (message interactif call_permission_request) avec
    une courte explication — au plus 1 par 24 h et 2 par 7 jours par numéro (limites Meta)."""
    tel = ev["telephone"]
    j1, j7 = await demandes_recentes(db, tel, maintenant)
    if j1 >= 1 or j7 >= 2:
        return {"ok": False, "envoyee": False, "raison": "limite Meta des demandes d'autorisation atteinte"}
    texte = texte_demande_autorisation(ev)
    res = await ap._graph_post(s, numero_id, "messages", {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": tel, "type": "interactive",
        "interactive": {"type": "call_permission_request", "action": {"name": "call_permission_request"},
                        "body": {"text": texte}}})
    await db.whatsapp_messages.insert_one({
        "id": str(uuid.uuid4()), "client_id": ev.get("client_id"), "direction": "outbound", "to": f"+{tel}",
        "phone_digits": tel, "contact_id": (ev.get("contact") or {}).get("id") if (ev.get("contact") or {}).get("source") == "contact" else None,
        "body": f"📞 Demande d'autorisation d'appel : {texte}", "message_type": "call_permission_request",
        "sender_label": "Liluvine — agenda", "ai_generated": True, "wa_numero_id": numero_id, "ok": res["ok"],
        "error": res.get("erreur"), "created_at": _iso(maintenant), "sent_at": _iso(maintenant) if res["ok"] else None,
        "agenda_id": ev["id"]})
    return {"ok": res["ok"], "envoyee": res["ok"], "raison": res.get("erreur")}


async def _sans_autorisation(db, s, cfga, ev, numero_id, perm) -> Dict[str, Any]:
    """Contact sans autorisation d'appel : demande envoyée UNE fois, puis attente ; au-delà du délai → repli."""
    maintenant = _maintenant()
    deja = ap.lire_date(ev.get("autorisation_demandee_le"))
    limite_h = cfga["attente_autorisation_h"]
    if deja and maintenant - deja >= timedelta(hours=limite_h):
        return await _terminer_sans_appel(db, s, cfga, ev, numero_id, "echec",
                                          f"autorisation d'appel non accordée après {limite_h} h")
    maj: Dict[str, Any] = {"statut": "attente_autorisation", "verrou_par": None, "verrou_jusqua": None,
                           "permission": {"etat": perm.get("etat"), "source": perm.get("source")},
                           "maj_le": _iso(maintenant)}
    envoi = None
    relance = False
    if not deja:
        envoi = await demander_autorisation(db, s, numero_id, ev, maintenant)
        maj["autorisation_demandee_le"] = _iso(maintenant)
        maj["autorisation_derniere_demande_le"] = _iso(maintenant)
        maj["autorisation_demandes"] = 1
        maj["autorisation_envoi"] = envoi
        deja = maintenant
    elif cfga.get("relance_autorisation"):
        # Lot 73 — la demande a pu se perdre parmi les autres messages : renvoyée après 24 h sans réponse
        derniere = ap.lire_date(ev.get("autorisation_derniere_demande_le")) or deja
        if maintenant - derniere >= timedelta(hours=24):
            envoi = await demander_autorisation(db, s, numero_id, ev, maintenant)
            relance = True
            if envoi.get("envoyee"):
                maj["autorisation_derniere_demande_le"] = _iso(maintenant)
                maj["autorisation_demandes"] = int(ev.get("autorisation_demandes") or 1) + 1
            maj["autorisation_envoi"] = envoi
    # Nouvelle vérification à l'intervalle des tentatives (ou dès la réponse du contact, par le webhook)
    echeance = min(maintenant + timedelta(minutes=ev.get("intervalle_min") or cfga["intervalle_min"]),
                   deja + timedelta(hours=limite_h))
    maj["prochaine_tentative"] = _iso(echeance)
    await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": maj, "$push": {"historique": {
        "le": _iso(maintenant),
        "resultat": ("autorisation redemandée (relance automatique)" if relance else "autorisation demandée")
        if envoi else "en attente d'autorisation",
        "raison": (envoi or {}).get("raison")}}})
    return {"resultat": "attente_autorisation", "envoi": envoi}


def prochaine_demande_possible(dernieres: List[str]) -> Optional[str]:
    """Lot 73 — date à partir de laquelle Meta accepte une nouvelle demande (1 par 24 h, 2 par 7 jours)."""
    dates = sorted(d for d in (ap.lire_date(x) for x in dernieres) if d)
    if not dates:
        return None
    candidates = [dates[-1] + timedelta(hours=24)]
    if len(dates) >= 2:
        candidates.append(dates[-2] + timedelta(days=7))
    return _iso(max(candidates))


async def redemander_autorisation(db, ev: Dict[str, Any], par: str) -> Dict[str, Any]:
    """Lot 73 — renvoie la demande d'autorisation d'appel au contact (bouton de l'agenda).
    Le délai d'attente repart de zéro ; refusé si la limite de Meta est atteinte (date du prochain essai possible)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfga = reglages_agenda(s)
    numero_id, _ = ligne_de(s, ev.get("ligne_cle") or cfga["ligne"])
    maintenant = _maintenant()
    envoi = await demander_autorisation(db, s, numero_id, ev, maintenant)
    if not envoi.get("envoyee"):
        # Dates des demandes déjà envoyées à ce numéro (7 derniers jours) → prochaine date possible
        fin = re.escape(ev["telephone"][-8:]) + "$"
        docs = await db.whatsapp_messages.find(
            {"message_type": "call_permission_request", "phone_digits": {"$regex": fin}, "ok": True,
             "created_at": {"$gte": _iso(maintenant - timedelta(days=7))}}, {"_id": 0, "created_at": 1}).to_list(10)
        return {"ok": False, "raison": envoi.get("raison") or "envoi impossible",
                "possible_a_partir_de": prochaine_demande_possible([d["created_at"] for d in docs])}
    await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {
        "statut": "attente_autorisation", "autorisation_demandee_le": _iso(maintenant),
        "autorisation_derniere_demande_le": _iso(maintenant),
        "autorisation_demandes": int(ev.get("autorisation_demandes") or 1) + 1, "autorisation_envoi": envoi,
        "autorisation_refusee": False, "raison": None, "verrou_par": None, "verrou_jusqua": None,
        "prochaine_tentative": _iso(maintenant + timedelta(minutes=ev.get("intervalle_min") or cfga["intervalle_min"])),
        "maj_le": _iso(maintenant)},
        "$push": {"historique": {"le": _iso(maintenant), "resultat": "autorisation redemandée", "raison": f"par {par}"}}})
    return {"ok": True, "envoi": envoi}


async def permission_recue(db, telephone: str, accepte: bool) -> int:
    """Webhook : réponse du contact à une demande d'autorisation d'appel. Acceptée → les évènements en
    attente repartent tout de suite ; refusée → ils s'arrêtent à leur prochain passage (repli éventuel)."""
    fin = _chiffres(telephone)[-8:]
    if len(fin) < 8:
        return 0
    maj: Dict[str, Any] = {"prochaine_tentative": _iso(_maintenant()), "maj_le": _iso(_maintenant())}
    if accepte:
        maj["autorisation_accordee_le"] = _iso(_maintenant())
    else:
        maj["autorisation_refusee"] = True
    r = await db[COLLECTION].update_many({"statut": "attente_autorisation",
                                          "telephone": {"$regex": re.escape(fin) + "$"}}, {"$set": maj})
    return int(getattr(r, "modified_count", 0))


# ---------------------------------------------------------------------------
# Repli : message WhatsApp quand l'appel n'aboutit pas
# ---------------------------------------------------------------------------

async def envoyer_message(db, s: Dict[str, Any], cfga: Dict[str, Any], numero_id: str, ev: Dict[str, Any],
                          texte: str) -> Dict[str, Any]:
    """Texte libre si le contact a écrit depuis moins de 24 h, sinon modèle Meta de repli (s'il est réglé,
    1 variable = le texte) ; trace dans la conversation du contact."""
    tel = ev["telephone"]
    maintenant = _maintenant()
    ouverte = await ap.fenetre_24h_ouverte(db, tel, numero_id, maintenant)
    if not ouverte and cfga["repli_modele"]:
        corps = {"messaging_product": "whatsapp", "to": tel, "type": "template",
                 "template": {"name": cfga["repli_modele"], "language": {"code": cfga["repli_modele_langue"]},
                              "components": [{"type": "body", "parameters": [
                                  {"type": "text", "text": ap.extrait(texte, 900) or "—"}]}]}}
        mode = "modele"
    else:
        corps = {"messaging_product": "whatsapp", "to": tel, "type": "text",
                 "text": {"body": texte[:4000], "preview_url": False}}
        mode = "texte"
    res = await ap._graph_post(s, numero_id, "messages", corps)
    mid = ((res.get("donnees") or {}).get("messages") or [{}])[0].get("id") if res["ok"] else None
    erreur = res.get("erreur")
    if not res["ok"] and mode == "texte" and not ouverte:
        erreur = f"{erreur} — fenêtre de 24 h fermée : déclarez un modèle Meta de repli dans les réglages de l'agenda"
    try:
        await db.whatsapp_messages.insert_one({
            "id": str(uuid.uuid4()), "client_id": ev.get("client_id"), "direction": "outbound", "to": f"+{tel}",
            "phone_digits": tel, "body": texte, "message_type": "template" if mode == "modele" else "text",
            "template_name": cfga["repli_modele"] if mode == "modele" else None, "ai_generated": True,
            "sender_label": "Liluvine — agenda", "wa_numero_id": numero_id, "wa_message_id": mid, "ok": res["ok"],
            "error": erreur, "created_at": _iso(maintenant), "sent_at": _iso(maintenant) if res["ok"] else None,
            "agenda_id": ev["id"]})
    except Exception:  # noqa: BLE001
        pass
    return {"ok": res["ok"], "mode": mode, "erreur": erreur, "le": _iso(maintenant)}


def repli_voulu(ev: Dict[str, Any], cfga: Dict[str, Any]) -> bool:
    """Le message de repli est-il demandé pour cet évènement ?"""
    return cfga["anniv_repli"] if ev.get("type") == "anniversaire" else cfga["repli_message"]


async def _terminer_sans_appel(db, s, cfga, ev, numero_id, statut: str, raison: str) -> Dict[str, Any]:
    """Fin d'un évènement sans conversation (sans réponse, autorisation absente…) : repli puis occurrence suivante."""
    repli = None
    if repli_voulu(ev, cfga):
        try:
            repli = await envoyer_message(db, s, cfga, numero_id, ev, texte_repli(ev))
        except Exception as exc:  # noqa: BLE001
            repli = {"ok": False, "erreur": str(exc)[:200]}
    maintenant = _maintenant()
    await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {
        "statut": statut, "raison": raison, "repli": repli, "verrou_par": None, "verrou_jusqua": None,
        "termine_le": _iso(maintenant), "maj_le": _iso(maintenant)}, "$push": {"historique": {
            "le": _iso(maintenant), "resultat": STATUTS.get(statut, statut), "raison": raison}}})
    await creer_occurrence_suivante(db, ev)
    return {"resultat": statut, "raison": raison, "repli": repli}


# ---------------------------------------------------------------------------
# Appel sortant + conversation (moteur du lot 69 en mode « sortant »)
# ---------------------------------------------------------------------------

async def _graph_appel(s: Dict[str, Any], numero_id: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """Action d'appel chez Meta (connect, terminate) — via la fonction du lot 67 (imitée dans les tests)."""
    return await ap._graph_post(s, numero_id, "calls", {"messaging_product": "whatsapp", **corps})


async def prompt_de_l_evenement(db, s: Dict[str, Any], ev: Dict[str, Any], ouverture: str) -> str:
    """Prompt système de Liluvine (client ou prospects) + base de connaissances + évènement."""
    base = ""
    try:
        from routes.liluvine_pro import DEFAULT_WA_PROSPECT_SYSTEM_PROMPT, _resolve_base_system_prompt
        if ev.get("type") == "prospection":
            base = (s.get("liluvine_wa_prospect_system_prompt") or "").strip() or DEFAULT_WA_PROSPECT_SYSTEM_PROMPT
        else:
            base = await _resolve_base_system_prompt(db, ev.get("client_id") or "")
    except Exception:  # noqa: BLE001 — prompt de base minimal
        base = ""
    base = base or "Tu es Liluvine, l'assistante de SAWALI, chaleureuse, professionnelle et concise."
    connaissances = ""
    try:
        from routes.liluvine_kb import build_kb_context
        connaissances = await asyncio.wait_for(build_kb_context(
            db, max_chars=3000, audience="prospects" if ev.get("type") == "prospection" else "clients"), timeout=3)
    except Exception:  # noqa: BLE001
        connaissances = ""
    return assembler_prompt_sortant(base, ev, ouverture, connaissances=connaissances,
                                    transfert=ld.reglages_decroche(s)["transfert_actif"])


async def appeler_et_converser(db, s: Dict[str, Any], cfga: Dict[str, Any], ev: Dict[str, Any], *,
                               numero_id: str, ligne_cle: Optional[str]) -> Dict[str, Any]:
    """Appelle le contact (offre SDP du serveur), attend qu'il décroche, puis Liluvine converse.
    → {resultat: decroche | sans_reponse | refuse | echec, raison, call_id, transcription, mesures, fin, ...}."""
    ok, raison = ap.moteur_disponible()
    if not ok:
        return {"resultat": "echec", "raison": raison}
    anniversaire = ev.get("type") == "anniversaire"
    cfg = {**ld.reglages_decroche(s), "duree_max_s": cfga["duree_max_min"] * 60,
           "silence_s": min(cfga["silence_s"], 10) if anniversaire else cfga["silence_s"]}
    tel = ev["telephone"]
    ouverture = (ev.get("texte_a_lire") or texte_ouverture(ev)) if anniversaire else texte_ouverture(ev)
    prompt = await prompt_de_l_evenement(db, s, ev, ouverture)

    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
    from routes.audio_appel import SondeBoucle, lancer_sur_media, sur_media
    ice = ap.serveurs_ice()
    detecteur = ld.DetecteurParole()
    phrases: asyncio.Queue = asyncio.Queue()
    raccroche = asyncio.Event()
    principale = asyncio.get_running_loop()
    lecteurs: List[Any] = []
    mesures: Dict[str, Any] = {"stt_secondes": 0.0, "stt_modele": None, "tts_caracteres": {}, "llm_entree": 0,
                               "llm_sortie": 0, "tours": 0, "latences_s": [], "premier_son_s": []}
    transcription: List[Dict[str, Any]] = []
    # Sondes de retard (lot 69.2) : boucle principale (API) et boucle média (son)
    sonde_principale, sonde_media = SondeBoucle(), SondeBoucle()
    sondes = [asyncio.ensure_future(sonde_principale.tourner()), lancer_sur_media(sonde_media.tourner)]
    contact = ev.get("contact") or {}
    sonnerie_debut = time.monotonic()

    def signaler_raccroche() -> None:
        """Pose « raccroché » dans la boucle principale (appelable depuis la boucle média)."""
        principale.call_soon_threadsafe(raccroche.set)

    async def _creer():
        """(boucle média) Connexion WebRTC, piste persistante de Liluvine, écoute du contact, offre SDP."""
        connexion = RTCPeerConnection(RTCConfiguration(iceServers=ice))
        p = ld.creer_piste_conversation()

        @connexion.on("track")
        def sur_piste(piste_contact):
            """Son du contact : rééchantillonné en 16 kHz mono puis découpé en phrases."""
            if piste_contact.kind != "audio":
                return

            async def lire():
                import av
                reech = av.AudioResampler(format="s16", layout="mono", rate=ld.FREQ_ANALYSE)
                while True:
                    try:
                        trame = await piste_contact.recv()
                    except Exception:  # noqa: BLE001 — fin du flux : le contact a raccroché
                        signaler_raccroche()
                        return
                    for t in reech.resample(trame):
                        for phrase in detecteur.ajouter(bytes(t.planes[0])[: t.samples * 2]):
                            principale.call_soon_threadsafe(phrases.put_nowait, phrase)
            lecteurs.append(asyncio.ensure_future(lire()))

        @connexion.on("connectionstatechange")
        async def sur_etat():
            logger.info("[appel-audio] agenda de Liluvine : connexion %s", connexion.connectionState)   # lot 79.7 : diagnostic
            if connexion.connectionState in ("failed", "closed"):
                signaler_raccroche()

        connexion.addTrack(p)
        await connexion.setLocalDescription(await connexion.createOffer())
        return connexion, p

    async def _fermer():
        """(boucle média) Arrête l'écoute et ferme la connexion."""
        for t in lecteurs:
            t.cancel()
        # Lot 79.7 — son réellement transmis (paquets envoyés / reçus) écrit au journal, puis fermeture
        from routes.audio_appel import fermer_avec_mesures
        await fermer_avec_mesures(pc, "agenda de Liluvine")

    pc = None
    piste = None
    call_id: Optional[str] = None
    debut: Optional[float] = None
    try:
        # 1. Offre SDP et appel (action connect)
        pc, piste = await sur_media(_creer)
        rep = await _graph_appel(s, numero_id, {"to": tel, "action": "connect",
                                                "session": {"sdp_type": "offer", "sdp": pc.localDescription.sdp},
                                                "biz_opaque_callback_data": f"agenda:{ev['id']}"})
        call_id = ((rep.get("donnees") or {}).get("calls") or [{}])[0].get("id") if rep.get("ok") else None
        if not call_id:
            return {"resultat": "echec", "raison": rep.get("erreur") or "Meta n'a pas renvoyé d'identifiant d'appel",
                    "code": rep.get("code")}
        maintenant = _maintenant()
        await db.wa_appels.insert_one({
            "id": call_id, "direction": "sortant", "statut": "appel", "motif": f"Agenda — {TYPES.get(ev['type'])}",
            "agenda_id": ev["id"], "agenda_type": ev["type"], "numero_id": numero_id, "ligne_cle": ligne_cle,
            "telephone": tel, "contact_id": contact.get("id") if contact.get("source") == "contact" else None,
            "contact_nom": contact.get("nom") or f"+{tel}", "client_id": ev.get("client_id"), "auto": True,
            "agent_id": None, "decroche_par_nom": ld.NOM_LILUVINE, "repondu_par": ld.NOM_LILUVINE,
            "created_at": _iso(maintenant), "maj": _iso(maintenant)})
        await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {"call_id_en_cours": call_id}})

        # 2. Sonnerie : réponse SDP (le contact décroche) ou fin (refus, sans réponse)
        async def reponse():
            doc = await db.wa_appels.find_one({"id": call_id}, {"_id": 0, "sdp_reponse": 1, "statut": 1}) or {}
            if doc.get("sdp_reponse"):
                return {"sdp": doc["sdp_reponse"]}
            if doc.get("statut") in ("refuse", "sans_reponse", "termine", "manque"):
                return {"fin": doc["statut"]}
            return None
        etat = await ap._attendre(reponse, cfga["sonnerie_s"], 0.3)
        sonnerie_s = int(round(time.monotonic() - sonnerie_debut))
        if not etat or etat.get("fin"):
            resultat = "refuse" if (etat or {}).get("fin") == "refuse" else "sans_reponse"
            await _graph_appel(s, numero_id, {"call_id": call_id, "action": "terminate"})
            await db.wa_appels.update_one({"id": call_id}, {"$set": {
                "statut": resultat, "resultat": "refusé" if resultat == "refuse" else "sans réponse",
                "maj": _iso(_maintenant())}})
            return {"resultat": resultat, "raison": "appel refusé" if resultat == "refuse" else "pas de réponse",
                    "call_id": call_id, "sonnerie_s": sonnerie_s}

        # 3. Décroché : réponse SDP appliquée, connexion audio (ICE + DTLS)
        await sur_media(lambda: pc.setRemoteDescription(RTCSessionDescription(sdp=etat["sdp"], type="answer")))

        async def connecte():
            if pc.connectionState == "failed":
                return "failed"
            return "ok" if pc.connectionState == "connected" else None
        if await ap._attendre(connecte, 12, 0.1) != "ok":
            raise RuntimeError("connexion audio impossible (ICE/DTLS) — vérifiez l'UDP sortant ou le TURN")
        debut = time.monotonic()
        await db.wa_appels.update_one({"id": call_id}, {"$set": {"statut": "en_cours",
                                                                 "debut": _iso(_maintenant())}})

        # 4. Ouverture (texte d'anniversaire répété au besoin), puis conversation
        conv = ld.Conversation(db=db, call_id=call_id, s=s, cfg=cfg, piste=piste, detecteur=detecteur,
                               phrases=phrases, raccroche=raccroche, mesures=mesures, transcription=transcription,
                               debut=debut, texte_silence=TEXTE_SILENCE_SORTANT,
                               texte_duree_max=TEXTE_DUREE_MAX_SORTANT)
        await asyncio.sleep(0.5)
        await conv.dire(ouverture)
        if anniversaire:
            for _ in range(cfga["anniv_repetitions"] - 1):
                if raccroche.is_set():
                    break
                await asyncio.sleep(0.8)
                await conv.dire("Je répète : " + ouverture)
        fin, transfert = None, False
        if not ld.cle_openai(s):
            await conv.dire(TEXTE_SANS_STT_SORTANT)
            fin = "écoute indisponible (clé OpenAI absente)"
        if fin is None:
            fin, transfert = await conv.converser(prompt)
        await asyncio.sleep(0.6)
        mesures["qualite_audio"] = ld.qualite_audio(piste, sonde_principale, sonde_media, mesures)
        duree_s = int(round(time.monotonic() - debut))
        if fin != "l'appelant a raccroché":
            await _graph_appel(s, numero_id, {"call_id": call_id, "action": "terminate"})
        return {"resultat": "decroche", "call_id": call_id, "transcription": transcription, "mesures": mesures,
                "fin": "le contact a raccroché" if fin == "l'appelant a raccroché" else fin,
                "transfert": transfert, "duree_s": duree_s, "sonnerie_s": sonnerie_s, "ouverture": ouverture}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[liluvine_agenda] erreur pendant l'appel de %s", ev.get("id"), exc_info=True)
        if call_id:
            await _graph_appel(s, numero_id, {"call_id": call_id, "action": "terminate"})
        if call_id and debut is not None:
            if piste is not None:
                mesures["qualite_audio"] = ld.qualite_audio(piste, sonde_principale, sonde_media, mesures)
            return {"resultat": "decroche", "call_id": call_id, "transcription": transcription, "mesures": mesures,
                    "fin": f"erreur : {str(exc)[:150]}", "transfert": True,
                    "duree_s": int(round(time.monotonic() - debut)), "ouverture": ouverture}
        return {"resultat": "echec", "raison": f"erreur : {str(exc)[:200]}", "call_id": call_id}
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


# ---------------------------------------------------------------------------
# Après l'appel : extraction, coût, journal, tentatives, récurrence, relance
# ---------------------------------------------------------------------------

def cout_appel(s: Dict[str, Any], mesures: Dict[str, Any], duree_s: int) -> Dict[str, Any]:
    """Coût estimé : appel émis facturé par Meta (tarif du lot 67.1, tranches de 6 s) + voix (tarif lot 67.1)
    dans la devise réglée ; IA (transcription, modèle, voix) en USD (tarifs publics, lot 69)."""
    tarif = ap.tarif_actuel(s)
    caracteres = sum(n for f, n in (mesures.get("tts_caracteres") or {}).items() if f != "google")
    meta = ap.calculer_cout(tarif, conversation_s=duree_s, relais_modele=False, tts_caracteres=caracteres,
                            voix="payante" if caracteres else None)
    ia = ld.estimer_cout(mesures or {})
    return {"devise": tarif["devise"], "tarif": tarif, **meta, "ia_usd": ia["total"], "detail_ia": ia}


async def apres_appel(db, s: Dict[str, Any], cfga: Dict[str, Any], ev: Dict[str, Any], res: Dict[str, Any], *,
                      numero_id: str) -> Dict[str, Any]:
    """Écrit le résultat : conversation → extraction + journal ; sinon tentative suivante ou fin + repli."""
    maintenant = _maintenant()
    col = db[COLLECTION]
    tentatives = int(ev.get("tentatives") or 0) + 1
    trace = {"le": _iso(maintenant), "resultat": res.get("resultat"), "raison": res.get("raison") or res.get("fin"),
             "call_id": res.get("call_id")}
    if res.get("resultat") != "decroche":
        # Pas de conversation : nouvelle tentative ou fin
        if tentatives < int(ev.get("tentatives_max") or cfga["tentatives_max"]):
            prochaine = maintenant + timedelta(minutes=int(ev.get("intervalle_min") or cfga["intervalle_min"]))
            await col.update_one({"id": ev["id"]}, {"$set": {
                "statut": "planifie", "tentatives": tentatives, "prochaine_tentative": _iso(prochaine),
                "raison": res.get("raison"), "verrou_par": None, "verrou_jusqua": None, "call_id_en_cours": None,
                "maj_le": _iso(maintenant)}, "$push": {"historique": trace}})
            return {"resultat": "nouvelle_tentative", "prochaine": _iso(prochaine)}
        await col.update_one({"id": ev["id"]}, {"$set": {"tentatives": tentatives}, "$push": {"historique": trace}})
        statut = "echec" if res.get("resultat") == "echec" else "sans_reponse"
        return await _terminer_sans_appel(db, s, cfga, {**ev, "tentatives": tentatives}, numero_id, statut,
                                          f"{res.get('raison') or 'pas de réponse'} ({tentatives} tentative(s))")

    # Conversation : extraction (informations, résumé, action suivante)
    transcription = res.get("transcription") or []
    mesures = res.get("mesures") or {}
    extraction = {"resume": "", "informations": [], "action_suivante": {"texte": "", "type": "aucune", "date": None},
                  "erreur": None}
    # Lot 71 — appel basé sur un formulaire : extraction champ par champ, contrôlée contre le formulaire
    plan = ev.get("formulaire_plan") if ev.get("mode") == "formulaire" else None
    analyse = fm.analyser_reponses({}, plan) if plan else None
    if any(t.get("qui") == "appelant" for t in transcription):
        try:
            if plan:
                r = await llm_texte(fm.SYSTEME_EXTRACTION_FORMULAIRE,
                                    fm.texte_a_extraire(plan, transcription, formater(maintenant)), 1500)
            else:
                r = await llm_texte(SYSTEME_EXTRACTION, texte_a_extraire(ev, transcription, maintenant), 900)
            mesures["llm_entree"] = mesures.get("llm_entree", 0) + int(r.get("entree") or 0)
            mesures["llm_sortie"] = mesures.get("llm_sortie", 0) + int(r.get("sortie") or 0)
            extraction = analyser_extraction(r.get("texte") or "", ev.get("questions") or [])
            if plan:
                analyse = fm.analyser_reponses(_json_tolerant(r.get("texte") or "") or {}, plan)
        except Exception as exc:  # noqa: BLE001
            extraction["erreur"] = f"extraction impossible : {str(exc)[:150]}"
    else:
        extraction["informations"] = [{"id": q["id"], "libelle": q["libelle"], "type": q["type"], "valeur": None,
                                       "confiance": 0.0} for q in ev.get("questions") or []]
    if plan:
        extraction["informations"] = fm.informations_depuis(analyse)
    resume = extraction["resume"] or ("Message lu, aucune réponse du contact." if transcription
                                      else "Appel décroché sans échange.")
    duree_s = int(res.get("duree_s") or 0)
    cout = cout_appel(s, mesures, duree_s)
    tache_id = None
    appel_journal = {"id": res.get("call_id"), "client_id": ev.get("client_id"),
                     "contact_nom": (ev.get("contact") or {}).get("nom"), "telephone": ev["telephone"]}
    if res.get("transfert"):
        tache_id = await ld.demande_de_rappel(db, appel_journal, resume)
    resultat = {
        "call_id": res.get("call_id"), "fin": res.get("fin"), "resume": resume, "transcription": transcription,
        "informations": extraction["informations"], "action_suivante": extraction["action_suivante"],
        "extraction_erreur": extraction.get("erreur"), "cout": cout, "duree_s": duree_s,
        "sonnerie_s": res.get("sonnerie_s"), "qualite_audio": mesures.get("qualite_audio"),
        "transfert_humain": bool(res.get("transfert")), "tache_rappel_id": tache_id, "tours": mesures.get("tours", 0),
        "ouverture": res.get("ouverture"), "termine_le": _iso(maintenant),
    }
    if plan:
        # Lot 71 : réponse au formulaire (soumission « appel Liluvine ») + lien WhatsApp si besoin
        resultat["formulaire"] = await enregistrer_formulaire(db, s, cfga, ev, plan, analyse,
                                                              call_id=res.get("call_id"), numero_id=numero_id,
                                                              maintenant=maintenant)
    # Journal des appels (visible dans le fil de conversation du contact) : même forme que le lot 69
    lat = mesures.get("latences_s") or []
    journal = {"transcription": transcription, "resume": resume, "fin": res.get("fin"),
               "transfert_humain": bool(res.get("transfert")), "tache_rappel_id": tache_id, "duree_s": duree_s,
               "tours": mesures.get("tours", 0), "cout": cout["detail_ia"],
               "latence_moyenne_s": round(sum(lat) / len(lat), 2) if lat else None,
               "voix": sorted((mesures.get("tts_caracteres") or {})), "stt_modele": mesures.get("stt_modele"),
               "qualite_audio": mesures.get("qualite_audio"),
               "agenda": {"id": ev["id"], "type": ev["type"], "type_libelle": TYPES.get(ev["type"]),
                          "titre": ev.get("titre"), "informations": extraction["informations"],
                          "action_suivante": extraction["action_suivante"],
                          "cout_appel": {k: cout[k] for k in ("devise", "secondes_facturees", "cout_total")}}}
    maj_journal: Dict[str, Any] = {"liluvine": journal, "resultat": "décroché", "maj": _iso(maintenant)}
    doc = await db.wa_appels.find_one({"id": res.get("call_id")}, {"_id": 0, "statut": 1}) or {}
    if doc.get("statut") in ("en_cours", "appel", "decroche"):
        maj_journal.update({"statut": "termine", "duree_s": duree_s, "fin": _iso(maintenant)})
    await db.wa_appels.update_one({"id": res.get("call_id")}, {"$set": maj_journal})
    await col.update_one({"id": ev["id"]}, {"$set": {
        "statut": "termine", "tentatives": tentatives, "resultat": resultat, "raison": None, "verrou_par": None,
        "verrou_jusqua": None, "call_id_en_cours": None, "termine_le": _iso(maintenant), "maj_le": _iso(maintenant)},
        "$push": {"historique": trace}})
    ev_final = {**ev, "resultat": resultat}
    await creer_occurrence_suivante(db, ev_final)
    relance = None
    if (cfga["relance_auto"] or ev.get("creer_relance")) and extraction["action_suivante"].get("date") \
            and extraction["action_suivante"].get("type") not in ("aucune", "anniversaire"):
        relance = await creer_relance(db, ev_final, extraction["action_suivante"])
    return {"resultat": "termine", "resume": resume, "informations": extraction["informations"], "cout": cout,
            "relance_id": relance}


async def enregistrer_formulaire(db, s: Dict[str, Any], cfga: Dict[str, Any], ev: Dict[str, Any],
                                 plan: Dict[str, Any], analyse: Dict[str, Any], *, call_id: Optional[str],
                                 numero_id: str, maintenant: datetime) -> Dict[str, Any]:
    """Lot 71 — après un appel en mode formulaire :
      1. crée une VRAIE réponse au formulaire (db.form_submissions, source « appel Liluvine ») dès qu'au
         moins un champ a été rempli ; statut « incomplète » s'il manque un champ obligatoire ;
      2. envoie le lien du formulaire par WhatsApp si le réglage de l'évènement le demande.
    → résumé affiché dans le tiroir de l'agenda (réponses par champ, lien vers la soumission)."""
    sortie: Dict[str, Any] = {
        "id": plan.get("id"), "titre": plan.get("titre"), "soumission_id": None,
        "statut": "complete" if analyse.get("complet") else "incomplete", "complet": bool(analyse.get("complet")),
        "reponses": analyse.get("reponses") or [], "a_completer": analyse.get("a_completer") or [],
        "lien_soumission": f"/admin/forms/{plan.get('id')}/analytics#submissions", "lien_envoye": None,
    }
    form = await db.forms.find_one({"id": plan.get("id")}, {"_id": 0, "id": 1, "client_id": 1})
    if form and analyse.get("data"):
        doc = fm.document_soumission(form, ev, analyse, call_id=call_id, le=_iso(maintenant))
        try:
            await db.form_submissions.insert_one(dict(doc))
            await db.forms.update_one({"id": form["id"]}, {"$inc": {"uses_count": 1}})
            sortie["soumission_id"] = doc["id"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[liluvine_agenda] soumission du formulaire impossible", exc_info=True)
            sortie["erreur"] = f"soumission impossible : {str(exc)[:150]}"
    elif not form:
        sortie["erreur"] = "formulaire supprimé : réponses gardées seulement dans l'agenda"
    if fm.envoyer_lien_voulu(ev.get("lien_formulaire") or "auto", plan, analyse):
        try:
            sortie["lien_envoye"] = await envoyer_message(
                db, s, cfga, numero_id, ev, fm.texte_lien(variables_contact(ev)["prenom"], plan, analyse))
        except Exception as exc:  # noqa: BLE001
            sortie["lien_envoye"] = {"ok": False, "erreur": str(exc)[:200]}
    return sortie


async def creer_occurrence_suivante(db, ev: Dict[str, Any]) -> Optional[str]:
    """Évènement récurrent : crée l'occurrence suivante (UNE seule : identifiant fixe « <id>-suite »)."""
    recurrence = ev.get("recurrence") or "aucune"
    quand = lire_date_heure(ev.get("date_heure"))
    suivante = prochaine_occurrence(quand, recurrence) if quand else None
    if not suivante:
        return None
    maintenant = _maintenant()
    while suivante <= maintenant:                      # occurrences manquées : on va à la prochaine à venir
        suivante = prochaine_occurrence(suivante, recurrence)
    champs = {k: ev.get(k) for k in ("type", "titre", "contact", "telephone", "objectif", "questions", "texte_a_lire",
                                     "contexte", "maintenance", "ligne_cle", "recurrence", "tentatives_max",
                                     "intervalle_min", "plage_debut", "plage_fin", "priorite", "creer_relance",
                                     "client_id", "priorite_ordre")}
    champs["date_heure"] = _iso(suivante)
    nouvel_id = f"{ev['id']}-suite"
    doc = _nouvel_evenement(champs, par=ev.get("cree_par") or "Liluvine", maintenant=maintenant, ev_id=nouvel_id)
    doc.update({"precedent_id": ev["id"], "serie_id": ev.get("serie_id") or ev["id"]})
    try:
        await db[COLLECTION].insert_one({"_id": nouvel_id, **doc})
        return nouvel_id
    except Exception:  # noqa: BLE001 — déjà créée (autre serveur ou nouvel essai)
        return None


async def creer_relance(db, ev: Dict[str, Any], action: Dict[str, Any]) -> Optional[str]:
    """Option « créer automatiquement l'évènement de relance suggéré » (une seule par évènement)."""
    quand = lire_date_heure(action.get("date"))
    if not quand or quand <= _maintenant():
        return None
    genre = action.get("type") if action.get("type") in TYPES else "relance"
    champs = {"type": genre, "titre": f"{TYPES[genre]} — {(ev.get('contact') or {}).get('nom')}",
              "contact": ev.get("contact"), "telephone": ev.get("telephone"),
              "objectif": action.get("texte") or f"Suite de l'appel « {ev.get('titre')} »",
              "questions": [], "texte_a_lire": "", "maintenance": None,
              "contexte": f"Appel précédent ({formater(lire_date_heure(ev.get('date_heure')))}) : "
                          f"{(ev.get('resultat') or {}).get('resume') or ''}"[:4000],
              "ligne_cle": ev.get("ligne_cle"), "recurrence": "aucune", "tentatives_max": ev.get("tentatives_max"),
              "intervalle_min": ev.get("intervalle_min"), "plage_debut": ev.get("plage_debut"),
              "plage_fin": ev.get("plage_fin"), "priorite": "normale", "priorite_ordre": 1, "creer_relance": False,
              "client_id": ev.get("client_id"), "date_heure": _iso(quand)}
    nouvel_id = f"{ev['id']}-relance"
    doc = _nouvel_evenement(champs, par="Liluvine (relance suggérée)", maintenant=_maintenant(), ev_id=nouvel_id)
    doc["parent_id"] = ev["id"]
    try:
        await db[COLLECTION].insert_one({"_id": nouvel_id, **doc})
        await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {"relance_id": nouvel_id}})
        return nouvel_id
    except Exception:  # noqa: BLE001
        return None


async def noter_duree_meta(db, call_id: str, duree_s: Any) -> bool:
    """Webhook « terminate » : la durée officielle de Meta remplace la durée mesurée ; coût recalculé avec le
    tarif FIGÉ de l'appel (jamais avec le tarif actuel)."""
    ev = await db[COLLECTION].find_one({"resultat.call_id": call_id}, {"_id": 0, "id": 1, "resultat": 1})
    if not ev or not (ev.get("resultat") or {}).get("cout"):
        return False
    try:
        duree = max(0, int(duree_s or 0))
    except (TypeError, ValueError):
        return False
    cout = dict(ev["resultat"]["cout"])
    meta = ap.calculer_cout(cout.get("tarif") or {}, conversation_s=duree, relais_modele=False,
                            tts_caracteres=0, voix=None)
    cout.update({"secondes_facturees": meta["secondes_facturees"], "cout_appel": meta["cout_appel"],
                 "cout_total": round(meta["cout_appel"] + float(cout.get("cout_tts") or 0), 2),
                 "duree_source": "meta"})
    await db[COLLECTION].update_one({"id": ev["id"]}, {"$set": {"resultat.cout": cout, "resultat.duree_meta_s": duree}})
    return True


# ---------------------------------------------------------------------------
# Recherches : contacts (WhatsApp, clients, utilisateurs suivis) et maintenances
# ---------------------------------------------------------------------------

async def rechercher_contacts(db, q: str, limite: int = 20) -> List[Dict[str, Any]]:
    """Contacts proposés pour un évènement : contacts WhatsApp, comptes clients, utilisateurs suivis."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    rx = {"$regex": re.escape(q), "$options": "i"}
    chiffres = _chiffres(q)
    # Chiffres cherchés même si le numéro est enregistré avec des espaces ou des tirets (« 70 00 00 01 »)
    rx_tel = {"$regex": r"\D*".join(chiffres[-8:])} if len(chiffres) >= 3 else None
    sortie: List[Dict[str, Any]] = []

    def ou(champs_texte, champs_tel):
        """Filtre « nom contient q » ou « numéro contient les chiffres »."""
        conditions = [{c: rx} for c in champs_texte]
        if rx_tel:
            conditions += [{c: rx_tel} for c in champs_tel]
        return {"$or": conditions}
    async for c in db.directory_contacts.find(ou(["name", "company"], ["whatsapp", "phone"]),
                                              {"_id": 0, "id": 1, "name": 1, "whatsapp": 1, "phone": 1,
                                               "company": 1, "client_id": 1}).limit(limite):
        tel = _chiffres(c.get("whatsapp") or c.get("phone"))
        if len(tel) >= 8:
            sortie.append({"source": "contact", "id": c.get("id"), "nom": c.get("name") or f"+{tel}",
                           "telephone": tel, "entreprise": c.get("company"), "client_id": c.get("client_id")})
    async for u in db.users.find({"role": "client", **ou(["company", "full_name", "email"], ["whatsapp_number", "phone"])},
                                 {"_id": 0, "id": 1, "company": 1, "full_name": 1, "whatsapp_number": 1,
                                  "phone": 1}).limit(limite):
        tel = _chiffres(u.get("whatsapp_number") or u.get("phone"))
        if len(tel) >= 8:
            sortie.append({"source": "client", "id": u.get("id"), "nom": u.get("full_name") or u.get("company"),
                           "telephone": tel, "entreprise": u.get("company"), "client_id": u.get("id")})
    async for t in db.tracked_users.find(ou(["name", "company"], ["whatsapp_number", "phone"]),
                                         {"_id": 0, "id": 1, "name": 1, "whatsapp_number": 1, "phone": 1,
                                          "company": 1, "client_id": 1}).limit(limite):
        tel = _chiffres(t.get("whatsapp_number") or t.get("phone"))
        if len(tel) >= 8:
            sortie.append({"source": "suivi", "id": t.get("id"), "nom": t.get("name") or f"+{tel}",
                           "telephone": tel, "entreprise": t.get("company"), "client_id": t.get("client_id")})
    return sortie[: limite * 3]


async def rechercher_maintenances(db, q: str, limite: int = 20) -> List[Dict[str, Any]]:
    """Fiches de maintenance (lot 41/47) et interventions proposées pour un « compte rendu de maintenance »."""
    q = (q or "").strip()
    rx = {"$regex": re.escape(q), "$options": "i"}
    sortie: List[Dict[str, Any]] = []
    filtre_f = {"$or": [{"numero": rx}, {"client_nom": rx}, {"marque_modele": rx}, {"type_materiel": rx}]} if q else {}
    async for f in db.maintenance_fiches.find(filtre_f, {"_id": 0, "id": 1, "numero": 1, "client_nom": 1,
                                                         "client_telephone": 1, "type_materiel": 1,
                                                         "marque_modele": 1, "date_reception": 1}) \
            .sort("date_reception", -1).limit(limite):
        sortie.append({"source": "maintenance", "id": f.get("id"),
                       "libelle": " — ".join(x for x in (f.get("numero"), f"{f.get('type_materiel') or ''} {f.get('marque_modele') or ''}".strip(),
                                                         f.get("client_nom")) if x),
                       "date": f.get("date_reception"), "client_nom": f.get("client_nom"),
                       "telephone": _chiffres(f.get("client_telephone"))})
    filtre_i = {"$or": [{"title": rx}, {"intervention_number": rx}, {"description": rx}]} if q else {}
    async for i in db.interventions.find(filtre_i, {"_id": 0, "id": 1, "title": 1, "intervention_number": 1,
                                                    "intervention_date": 1, "client_id": 1}) \
            .sort("intervention_date", -1).limit(limite):
        sortie.append({"source": "intervention", "id": i.get("id"),
                       "libelle": " — ".join(x for x in (i.get("intervention_number"), i.get("title")) if x),
                       "date": i.get("intervention_date"), "client_id": i.get("client_id")})
    return sortie


async def resume_maintenance(db, source: str, ident: str) -> str:
    """Résumé lisible d'une fiche de maintenance ou d'une intervention (injecté dans le prompt de Liluvine)."""
    if source == "maintenance":
        f = await db.maintenance_fiches.find_one({"id": ident}, {"_id": 0})
        if not f:
            return ""
        from routes import maintenance_equipements as me
        morceaux = [f"Fiche {f.get('numero') or ''} reçue le {f.get('date_reception') or '—'} : "
                    f"{f.get('type_materiel') or 'équipement'} {f.get('marque_modele') or ''}".strip() + "."]
        if f.get("motif"):
            morceaux.append(f"Motif : {f['motif']}.")
        if f.get("diagnostic"):
            morceaux.append(f"Diagnostic : {f['diagnostic']}.")
        if f.get("remplacement_pieces") and f.get("pieces"):
            morceaux.append(f"Pièces remplacées : {f['pieces']}.")
        morceaux.append(f"État : {me.LIBELLES_STATUT.get(me.statut_de(f), '')}.")
        if f.get("observations"):
            morceaux.append(f"Observations : {f['observations']}.")
        recap = me.recap_interventions(f)
        if recap:
            morceaux.append(recap.replace("\n", " ; "))
        return " ".join(morceaux)[:3000]
    if source == "intervention":
        i = await db.interventions.find_one({"id": ident}, {"_id": 0})
        if not i:
            return ""
        morceaux = [f"Intervention {i.get('intervention_number') or ''} du {i.get('intervention_date') or '—'} : "
                    f"{i.get('title') or ''}".strip() + "."]
        if i.get("description"):
            morceaux.append(str(i["description"]))
        if i.get("technician"):
            morceaux.append(f"Technicien : {i['technician']}.")
        if i.get("duration_hours"):
            morceaux.append(f"Durée : {i['duration_hours']} h.")
        if i.get("status"):
            morceaux.append(f"Statut : {i['status']}.")
        return " ".join(morceaux)[:3000]
    return ""


# ---------------------------------------------------------------------------
# Liste, totaux et export CSV
# ---------------------------------------------------------------------------

def totaux(docs: List[Dict[str, Any]], devise_defaut: str = "FCFA") -> Dict[str, Any]:
    """Totaux d'une période : nombre par statut, durée, coût des appels (devise réglée) et de l'IA (USD)."""
    par_statut = {k: 0 for k in STATUTS}
    duree = 0
    cout = 0.0
    ia = 0.0
    devise = devise_defaut
    for d in docs:
        par_statut[d.get("statut")] = par_statut.get(d.get("statut"), 0) + 1
        r = d.get("resultat") or {}
        duree += int(r.get("duree_meta_s") or r.get("duree_s") or 0)
        c = r.get("cout") or {}
        cout += float(c.get("cout_total") or 0)
        ia += float(c.get("ia_usd") or 0)
        devise = c.get("devise") or devise
    return {"nombre": len(docs), "par_statut": par_statut, "duree_s": duree, "cout": round(cout, 2),
            "devise": devise, "ia_usd": round(ia, 4)}


def _valeur_lisible(v: Any) -> str:
    """Valeur extraite → texte (oui / non, montants, dates)."""
    if v is True:
        return "oui"
    if v is False:
        return "non"
    if isinstance(v, list):                      # lot 71 : choix multiples d'un formulaire
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v)


def csv_agenda(docs: List[Dict[str, Any]]) -> str:
    """Export CSV (séparateur « ; », Excel français) : un évènement par ligne."""
    tampon = io.StringIO()
    w = csv.writer(tampon, delimiter=";")
    w.writerow(["Date", "Heure", "Type", "Titre", "Contact", "Téléphone", "Statut", "Tentatives", "Durée (s)",
                "Résumé", "Informations recueillies", "Action suivante", "Coût appel", "Devise", "Coût IA (USD)"])
    for d in docs:
        dt = lire_date_heure(d.get("date_heure"))
        r = d.get("resultat") or {}
        c = r.get("cout") or {}
        infos = " | ".join(f"{i.get('libelle')} = {_valeur_lisible(i.get('valeur'))}" for i in r.get("informations") or [])
        w.writerow([ap._local(dt).strftime("%d/%m/%Y") if dt else "", ap._local(dt).strftime("%H:%M") if dt else "",
                    TYPES.get(d.get("type"), d.get("type")), d.get("titre"), (d.get("contact") or {}).get("nom"),
                    f"+{d.get('telephone')}", STATUTS.get(d.get("statut"), d.get("statut")), d.get("tentatives") or 0,
                    r.get("duree_meta_s") or r.get("duree_s") or "", r.get("resume") or d.get("raison") or "", infos,
                    (r.get("action_suivante") or {}).get("texte") or "", c.get("cout_total", ""), c.get("devise", ""),
                    c.get("ia_usd", "")])
    return "﻿" + tampon.getvalue()


def filtre_liste(du: Optional[str], au: Optional[str], genre: Optional[str], statut: Optional[str],
                 q: Optional[str]) -> Dict[str, Any]:
    """Filtre MongoDB de la liste (période en jours AAAA-MM-JJ inclus, type, statut, contact)."""
    filtre: Dict[str, Any] = {}
    plage: Dict[str, Any] = {}
    if du and re.fullmatch(r"\d{4}-\d{2}-\d{2}", du):
        plage["$gte"] = f"{du}T00:00:00+00:00"
    if au and re.fullmatch(r"\d{4}-\d{2}-\d{2}", au):
        plage["$lte"] = f"{au}T23:59:59+00:00"
    if plage:
        filtre["date_heure"] = plage
    if genre and genre in TYPES:
        filtre["type"] = genre
    if statut and statut in STATUTS:
        filtre["statut"] = statut
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        conditions = [{"contact.nom": rx}, {"titre": rx}]
        if len(_chiffres(q)) >= 3:
            conditions.append({"telephone": {"$regex": re.escape(_chiffres(q))}})
        filtre["$or"] = conditions
    return filtre


def _alleger(d: Dict[str, Any]) -> Dict[str, Any]:
    """Évènement pour la liste : sans la transcription complète (lue dans le détail)."""
    d = dict(d)
    if d.get("resultat"):
        d["resultat"] = {k: v for k, v in d["resultat"].items() if k != "transcription"}
    return d


# ---------------------------------------------------------------------------
# Routes d'administration (administrateurs et superviseurs)
# ---------------------------------------------------------------------------

def setup_liluvine_agenda_routes(*, db, api, get_current_user) -> None:
    """Déclare les routes /admin/liluvine-agenda (administrateurs et superviseurs)."""
    from fastapi import Body, Depends, HTTPException, Query, Response

    def _exiger_admin(user: dict) -> None:
        """Réservé aux administrateurs et superviseurs."""
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")

    async def _exiger_agenda(user: dict, element: str = "agenda") -> None:
        """Lot 73 — administrateur, ou superviseur avec qui l'élément de Liluvine est partagé (Paramètres)."""
        _exiger_admin(user)
        from routes.liluvine_partage import verifier_element
        await verifier_element(db, user, element)

    async def _reglages() -> Tuple[Dict[str, Any], Dict[str, Any]]:
        s = await db.settings.find_one({"_id": "global"}) or {}
        return s, reglages_agenda(s)

    async def _evenement(ev_id: str) -> Dict[str, Any]:
        ev = await db[COLLECTION].find_one({"id": ev_id}, {"_id": 0})
        if not ev:
            raise HTTPException(status_code=404, detail="Évènement introuvable")
        return ev

    def _filtre_formulaires(user: dict) -> Dict[str, Any]:
        """Lot 71 — formulaires utilisables : tous pour l'administrateur ; sinon ceux du compte + les publics."""
        if user.get("role") == "admin":
            return {}
        return {"$or": [{"client_id": user.get("client_id") or user.get("id")}, {"is_public": True}]}

    async def _preparer(payload: Dict[str, Any], cfga: Dict[str, Any], user: dict) -> Dict[str, Any]:
        """Validation + résumé de la maintenance choisie + formulaire choisi (lot 71) + ordre de priorité."""
        try:
            champs = valider_evenement(payload, cfga)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if champs.get("formulaire"):
            form = await db.forms.find_one({"id": champs["formulaire"]["id"], **_filtre_formulaires(user)}, {"_id": 0})
            if not form:
                raise HTTPException(status_code=422, detail="Formulaire introuvable ou non accessible")
            resume = fm.resume_formulaire(form)
            if not resume["nb_vocaux"]:
                raise HTTPException(status_code=422, detail="Ce formulaire n'a aucun champ que Liluvine peut "
                                                            "demander au téléphone (fichiers, signatures…)")
            champs["formulaire"] = resume
        if champs["maintenance"]:
            resume = await resume_maintenance(db, champs["maintenance"]["source"], champs["maintenance"]["id"])
            if not resume:
                raise HTTPException(status_code=422, detail="Fiche de maintenance introuvable")
            champs["maintenance"]["resume"] = resume
        champs["priorite_ordre"] = PRIORITES[champs["priorite"]]
        return champs

    @api.get("/admin/liluvine-agenda", tags=["Admin — Liluvine agenda"])
    async def lister(du: Optional[str] = None, au: Optional[str] = None, type: Optional[str] = None,  # noqa: A002
                     statut: Optional[str] = None, q: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Évènements de la période (filtres) + totaux (nombre, durée, coûts) + réglages utiles à l'écran."""
        await _exiger_agenda(user)
        s, cfga = await _reglages()
        docs = await db[COLLECTION].find(filtre_liste(du, au, type, statut, q), {"_id": 0}) \
            .sort("date_heure", 1).to_list(3000)
        from routes.numeros_wa import lignes_configurees
        return {"evenements": [_alleger(d) for d in docs], "totaux": totaux(docs, ap.tarif_actuel(s)["devise"]),
                "types": TYPES, "statuts": STATUTS, "recurrences": list(RECURRENCES),
                "types_question": list(TYPES_QUESTION),
                "lignes": [{"cle": li["cle"], "libelle": li["libelle"]} for li in lignes_configurees(s)],
                "reglages": cfga, "moteur": {"disponible": ap.moteur_disponible()[0], "en_cours": len(ld._actifs)}}

    @api.get("/admin/liluvine-agenda/alertes", tags=["Admin — Liluvine agenda"])
    async def alertes(since: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Lot 72 — alertes « Liluvine appelle … » modifiées depuis `since` (sinon : 2 dernières heures)."""
        await _exiger_agenda(user, "alertes")
        maintenant = _maintenant()
        depuis = since or _iso(maintenant - timedelta(hours=2))
        docs = await db[COLLECTION_ALERTES].find({"maj": {"$gte": depuis}}, {"_id": 0}).sort("maj", -1).to_list(50)
        return {"alertes": docs, "server_now": _iso(maintenant)}

    @api.get("/admin/liluvine-agenda/export.csv", tags=["Admin — Liluvine agenda"])
    async def exporter(du: Optional[str] = None, au: Optional[str] = None, type: Optional[str] = None,  # noqa: A002
                       statut: Optional[str] = None, q: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Export CSV de la liste filtrée."""
        await _exiger_agenda(user)
        docs = await db[COLLECTION].find(filtre_liste(du, au, type, statut, q), {"_id": 0}) \
            .sort("date_heure", 1).to_list(5000)
        return Response(content=csv_agenda(docs), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=agenda-liluvine.csv"})

    @api.get("/admin/liluvine-agenda/reglages", tags=["Admin — Liluvine agenda"])
    async def lire_reglages(user: dict = Depends(get_current_user)):
        """Réglages de l'agenda et des anniversaires (+ texte par défaut)."""
        await _exiger_agenda(user)
        s, cfga = await _reglages()
        return {"reglages": {k: s.get(k) for k in CHAMPS}, "effectif": cfga, "texte_defaut": ANNIV_TEXTE_DEFAUT}

    @api.put("/admin/liluvine-agenda/reglages", tags=["Admin — Liluvine agenda"])
    async def enregistrer_reglages(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Enregistre les réglages (champs connus, valeurs contrôlées)."""
        await _exiger_agenda(user)
        maj: Dict[str, Any] = {}
        for cle, genre in CHAMPS.items():
            if cle not in payload:
                continue
            v = payload[cle]
            if genre is bool:
                maj[cle] = bool(v)
            elif genre is int:
                try:
                    maj[cle] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Valeur entière attendue pour {cle}")
            else:
                if isinstance(v, list):
                    v = ",".join(str(x) for x in v)
                maj[cle] = str(v or "").strip()[:3000]
        for cle in ("liluvine_agenda_plage_debut", "liluvine_agenda_plage_fin", "liluvine_agenda_anniv_heure"):
            if maj.get(cle) and not re.fullmatch(r"\d{1,2}[:hH]\d{2}", maj[cle]):
                raise HTTPException(status_code=422, detail="Heure attendue au format HH:MM")
        maj["liluvine_agenda_maj_par"] = user.get("full_name") or user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True}

    @api.get("/admin/liluvine-agenda/contacts", tags=["Admin — Liluvine agenda"])
    async def contacts(q: str = Query("", max_length=80), user: dict = Depends(get_current_user)):
        """Recherche d'un contact (WhatsApp, client, utilisateur suivi)."""
        await _exiger_agenda(user)
        return {"contacts": await rechercher_contacts(db, q)}

    @api.get("/admin/liluvine-agenda/maintenances", tags=["Admin — Liluvine agenda"])
    async def maintenances(q: str = Query("", max_length=80), user: dict = Depends(get_current_user)):
        """Recherche d'une fiche de maintenance / intervention (compte rendu de maintenance)."""
        await _exiger_agenda(user)
        return {"maintenances": await rechercher_maintenances(db, q)}

    @api.get("/admin/liluvine-agenda/formulaires", tags=["Admin — Liluvine agenda"])
    async def formulaires(q: str = Query("", max_length=80), user: dict = Depends(get_current_user)):
        """Lot 71 — formulaires disponibles pour un appel « basé sur un formulaire » (nombre de champs,
        champs demandés au téléphone, champs à compléter par écrit)."""
        await _exiger_agenda(user)
        filtre = _filtre_formulaires(user)
        if q.strip():
            filtre = {"$and": [filtre, {"title": {"$regex": re.escape(q.strip()), "$options": "i"}}]} if filtre \
                else {"title": {"$regex": re.escape(q.strip()), "$options": "i"}}
        docs = await db.forms.find(filtre, {"_id": 0, "id": 1, "title": 1, "number": 1, "pages": 1, "is_public": 1,
                                            "client_id": 1}).sort("created_at", -1).to_list(300)
        return {"formulaires": [fm.resume_formulaire(d) for d in docs if d.get("id")]}

    @api.get("/admin/liluvine-agenda/formulaires/{fid}/apercu", tags=["Admin — Liluvine agenda"])
    async def apercu_formulaire(fid: str, user: dict = Depends(get_current_user)):
        """Lot 71 — questions que Liluvine posera (ordre, formulation orale) et champs à compléter."""
        await _exiger_agenda(user)
        form = await db.forms.find_one({"id": fid, **_filtre_formulaires(user)}, {"_id": 0})
        if not form:
            raise HTTPException(status_code=404, detail="Formulaire introuvable")
        return fm.plan_formulaire(form)

    @api.post("/admin/liluvine-agenda/apercu-anniversaire", tags=["Admin — Liluvine agenda"])
    async def apercu_anniversaire(payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_user)):
        """Aperçu du texte d'anniversaire (modèle du formulaire, même non enregistré) pour une personne fictive."""
        await _exiger_agenda(user)
        _, cfga = await _reglages()
        modele = str((payload or {}).get("texte") or "").strip() or cfga["anniv_texte"]
        variables = {"prenom": "Awa", "nom": "KABORÉ", "age": 35, "entreprise": "SAWALI"}
        return {"texte": rendre_modele(modele, variables)}

    @api.post("/admin/liluvine-agenda/anniversaires/generer", tags=["Admin — Liluvine agenda"])
    async def generer(user: dict = Depends(get_current_user)):
        """Crée / met à jour tout de suite les évènements d'anniversaire (sinon : toutes les 10 minutes)."""
        await _exiger_agenda(user)
        s, _ = await _reglages()
        await assurer_index(db)
        return await generer_anniversaires(db, s, _maintenant())

    @api.post("/admin/liluvine-agenda", tags=["Admin — Liluvine agenda"])
    async def creer(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Nouvel évènement (statut « planifié »)."""
        await _exiger_agenda(user)
        _, cfga = await _reglages()
        champs = await _preparer(payload, cfga, user)
        champs["client_id"] = user.get("client_id") or user.get("id")
        doc = _nouvel_evenement(champs, par=user.get("full_name") or user.get("email") or "", maintenant=_maintenant())
        await db[COLLECTION].insert_one(dict(doc))
        doc.pop("_id", None)
        return doc

    @api.get("/admin/liluvine-agenda/{ev_id}", tags=["Admin — Liluvine agenda"])
    async def lire(ev_id: str, user: dict = Depends(get_current_user)):
        """Un évènement complet (transcription comprise)."""
        await _exiger_agenda(user)
        return await _evenement(ev_id)

    @api.put("/admin/liluvine-agenda/{ev_id}", tags=["Admin — Liluvine agenda"])
    async def modifier(ev_id: str, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
        """Modifie un évènement qui n'est pas en cours ; il redevient « planifié » à la nouvelle date."""
        await _exiger_agenda(user)
        ev = await _evenement(ev_id)
        if ev.get("statut") == "en_cours":
            raise HTTPException(status_code=409, detail="Appel en cours : modification impossible")
        _, cfga = await _reglages()
        champs = await _preparer(payload, cfga, user)
        maj = {**champs, "statut": "planifie", "prochaine_tentative": champs["date_heure"], "tentatives": 0,
               "autorisation_refusee": False, "raison": None, "maj_le": _iso(_maintenant()),
               "maj_par": user.get("full_name") or user.get("email")}
        await db[COLLECTION].update_one({"id": ev_id}, {"$set": maj})
        return await _evenement(ev_id)

    @api.post("/admin/liluvine-agenda/{ev_id}/dupliquer", tags=["Admin — Liluvine agenda"])
    async def dupliquer(ev_id: str, payload: Dict[str, Any] = Body(default={}), user: dict = Depends(get_current_user)):
        """Copie d'un évènement (nouvelle date facultative, sinon même date + 1 jour), statut « planifié »."""
        await _exiger_agenda(user)
        ev = await _evenement(ev_id)
        quand = lire_date_heure((payload or {}).get("date_heure")) or (
            max(lire_date_heure(ev["date_heure"]), _maintenant()) + timedelta(days=1))
        champs = {k: ev.get(k) for k in ("type", "titre", "contact", "telephone", "objectif", "questions",
                                         "texte_a_lire", "contexte", "maintenance", "ligne_cle", "recurrence",
                                         "tentatives_max", "intervalle_min", "plage_debut", "plage_fin", "priorite",
                                         "priorite_ordre", "creer_relance", "client_id",
                                         "mode", "formulaire", "lien_formulaire")}
        champs["date_heure"] = _iso(quand)
        doc = _nouvel_evenement(champs, par=user.get("full_name") or user.get("email") or "", maintenant=_maintenant())
        doc["copie_de"] = ev_id
        await db[COLLECTION].insert_one(dict(doc))
        doc.pop("_id", None)
        return doc

    @api.post("/admin/liluvine-agenda/{ev_id}/annuler", tags=["Admin — Liluvine agenda"])
    async def annuler(ev_id: str, user: dict = Depends(get_current_user)):
        """Annule un évènement planifié ou en attente (un appel en cours n'est pas coupé)."""
        await _exiger_agenda(user)
        r = await db[COLLECTION].update_one(
            {"id": ev_id, "statut": {"$in": ["planifie", "attente_autorisation", "sans_reponse", "echec"]}},
            {"$set": {"statut": "annule", "raison": f"annulé par {user.get('full_name') or user.get('email')}",
                      "maj_le": _iso(_maintenant())}})
        if not getattr(r, "modified_count", 0):
            raise HTTPException(status_code=409, detail="Évènement déjà terminé, annulé ou en cours")
        return {"ok": True}

    @api.post("/admin/liluvine-agenda/{ev_id}/redemander-autorisation", tags=["Admin — Liluvine agenda"])
    async def redemander_autorisation_route(ev_id: str, user: dict = Depends(get_current_user)):
        """Lot 73 — « Renvoyer la demande d'autorisation » : la demande a pu se perdre parmi les messages."""
        await _exiger_agenda(user)
        ev = await _evenement(ev_id)
        if ev.get("statut") in ("en_cours", "termine", "annule"):
            raise HTTPException(status_code=409, detail="Évènement en cours, terminé ou annulé")
        res = await redemander_autorisation(db, ev, user.get("full_name") or user.get("email") or "?")
        if not res["ok"]:
            quand = res.get("possible_a_partir_de")
            suite = ""
            if quand:
                try:
                    suite = " — prochaine demande possible le " + datetime.fromisoformat(quand).astimezone(
                        ZoneInfo("Africa/Ouagadougou")).strftime("%d/%m/%Y à %H:%M")
                except ValueError:
                    pass
            raise HTTPException(status_code=409, detail=f"{res['raison']}{suite}")
        return {"ok": True, "evenement": _alleger(await _evenement(ev_id))}

    @api.post("/admin/liluvine-agenda/{ev_id}/appeler-maintenant", tags=["Admin — Liluvine agenda"])
    async def appeler_maintenant(ev_id: str, user: dict = Depends(get_current_user)):
        """« Appeler maintenant » : l'évènement est réclamé tout de suite (hors plage horaire acceptée)."""
        await _exiger_agenda(user)
        ev = await _evenement(ev_id)
        if ev.get("statut") in ("en_cours", "termine", "annule"):
            raise HTTPException(status_code=409, detail="Évènement en cours, terminé ou annulé : dupliquez-le")
        maintenant = _maintenant()
        await db[COLLECTION].update_one({"id": ev_id}, {"$set": {
            "statut": "planifie" if ev.get("statut") != "attente_autorisation" else "attente_autorisation",
            "prochaine_tentative": _iso(maintenant), "lance_par": user.get("full_name") or user.get("email")}})
        reclame = await reclamer(db, maintenant, ev_id)
        if not reclame:
            raise HTTPException(status_code=409, detail="Évènement déjà pris par le moteur")
        s, cfga = await _reglages()
        _, ligne_cle = ligne_de(s, reclame.get("ligne_cle") or cfga["ligne"])
        d = decision_execution(reclame, cfga, maintenant, occupes=await appels_en_cours_ligne(db, ligne_cle, ev_id),
                               max_simultanes=ld.reglages_decroche(s)["max_simultanes"], force=True)
        if d["action"] != "appeler":
            await relacher(db, reclame, _iso(maintenant + timedelta(minutes=2)), d["raison"])
            raise HTTPException(status_code=409, detail=d["raison"])
        await db[COLLECTION].update_one({"id": ev_id}, {"$set": {"ligne_cle_effective": ligne_cle}})
        ld._actifs.add(f"agenda-{ev_id}")
        _lancer(executer_evenement(db, ev_id))
        return {"ok": True, "lance": True}
