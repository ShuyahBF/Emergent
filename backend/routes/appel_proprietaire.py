# appel_proprietaire.py — Lot 67 : Liluvine prévient le propriétaire à chaque message d'un client.
#
# À chaque message WhatsApp reçu d'un client (traitement EN ARRIÈRE-PLAN, jamais bloquant
# pour le webhook de Meta) :
#   1. RELAIS : Liluvine envoie au propriétaire, sur son WhatsApp, depuis le numéro SAWALI choisi :
#        « 📩 <Nom (+numéro)> écrit au support : "<extrait>" — JJ/MM/AAAA HH:MM »
#      (texte libre si le propriétaire a écrit à ce numéro depuis moins de 24 h, sinon modèle
#       Meta à 3 variables si un modèle est déclaré dans les réglages) ;
#   2. APPEL VOCAL WhatsApp : si le client l'autorise (fiche contact, autorisé par défaut), hors
#      heures calmes, et au plus un appel par client toutes les 30 minutes, SAWALI appelle le
#      propriétaire. Le SERVEUR est lui-même l'interlocuteur WebRTC (bibliothèque aiortc) : il
#      crée l'offre SDP avec une piste audio, Meta renvoie la réponse SDP par le webhook
#      « calls » (évènement connect), puis Liluvine prononce :
#        « Bonjour, ici Liluvine. <qui> écrit au support. Son dernier message date du … à … »
#      (deux fois), et raccroche (action terminate).
#   3. JOURNAL : chaque tentative est inscrite dans le journal des appels (db.wa_appels) :
#      direction « sortant », motif « alerte message », résultat (sonné, décroché,
#      sans réponse, refusé, échec + raison).
#   4. AUTORISATION : Meta exige que le propriétaire ait accepté les appels du numéro SAWALI.
#      Sinon, la demande d'autorisation (call_permission_request) lui est envoyée
#      automatiquement (au plus une fois tous les 7 jours) et l'appel n'a pas lieu (le relais
#      part quand même).
#
# Repli : si aiortc n'est pas installé, si la voix ne peut pas être fabriquée ou si l'appel
# échoue, le message relayé part quand même et l'échec est inscrit au journal.
#
# Réglages (Administration → Paramètres → « 📞 Liluvine appelle le propriétaire ») dans
# db.settings {_id: "global"} — aucun secret :
#   appel_proprio_actif (défaut vrai), appel_proprio_numeros (numéros du propriétaire, sinon
#   variable d'environnement NUMERO_APPEL_PROPRIETAIRE), appel_proprio_ligne (ligne SAWALI qui
#   appelle, défaut « principal »), appel_proprio_fenetre_min (défaut 30),
#   appel_proprio_calme_actif / _debut / _fin (heures calmes, défaut désactivées 22:00–06:00),
#   appel_proprio_relais_actif (défaut vrai), appel_proprio_modele / _modele_langue (modèle Meta
#   pour le relais hors fenêtre de 24 h), appel_proprio_voix (auto | openai | elevenlabs | google),
#   appel_proprio_voix_elevenlabs (identifiant de voix ElevenLabs), appel_proprio_repetitions
#   (défaut 2), appel_proprio_sonnerie_s (défaut 30), appel_proprio_exclus (numéros jamais
#   relayés : personnel, tests…).
#   Lot 67.1 — tarifs de l'historique : appel_proprio_tarif_appel_minute (défaut 0),
#   appel_proprio_tarif_devise (FCFA | USD, défaut FCFA), appel_proprio_tarif_arrondi (pulse6 = tranches
#   de 6 s comme Meta | minute | seconde), appel_proprio_tarif_relais_modele (prix d'un message modèle,
#   défaut 0), appel_proprio_tarif_tts_1000 (prix de 1000 caractères de voix, défaut 0).
#   Historique : db.appel_proprio_historique (voir la section « Lot 67.1 » plus bas).
# Variables d'environnement facultatives (saisies par le propriétaire sur Render) :
#   NUMERO_APPEL_PROPRIETAIRE, APPEL_TURN_URL / APPEL_TURN_UTILISATEUR / APPEL_TURN_MOT_DE_PASSE
#   (serveur TURN si l'UDP sortant est bloqué), OPENAI_API_KEY, ELEVENLABS_API_KEY.
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("sawali.appel_proprietaire")

# Version de l'API Graph de Meta (remplacée au démarrage par celle du serveur)
GRAPH_VERSION = "v21.0"
# Motif inscrit au journal des appels
MOTIF = "alerte message"
# Serveur STUN public (découverte de l'adresse publique du serveur pour WebRTC)
STUN_DEFAUT = "stun:stun.l.google.com:19302"
# Types de messages qui déclenchent l'alerte (les réponses à des boutons, réactions,
# formulaires et autorisations d'appel ne déclenchent rien)
TYPES_ALERTE = {"text", "image", "audio", "video", "document", "sticker", "location", "contacts"}
# Rôles considérés comme « personnel » (leurs messages ne déclenchent jamais d'alerte)
ROLES_PERSONNEL = ("admin", "superviseur", "moderateur", "moderator")
# Délai minimal entre deux demandes d'autorisation d'appel au propriétaire
INTERVALLE_DEMANDE = timedelta(days=7)
# Mois en toutes lettres (date prononcée par Liluvine)
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
# Fréquence audio attendue par WebRTC / Opus (48 kHz) et taille d'une trame de 20 ms
FREQUENCE = 48000
ECHANTILLONS_TRAME = 960

# Tâches d'arrière-plan en cours (référence gardée, sinon Python peut les supprimer)
_taches: set = set()
# Un seul appel au propriétaire à la fois (il ne peut pas décrocher deux appels)
_verrou_appel: Optional[asyncio.Lock] = None
# Verrous par client (deux messages simultanés du même client = un seul appel)
_verrous_clients: Dict[str, asyncio.Lock] = {}


# ---------------------------------------------------------------------------
# Petits outils : chiffres, dates, fuseau horaire
# ---------------------------------------------------------------------------

def _chiffres(valeur: Any) -> str:
    """Garde uniquement les chiffres d'un numéro."""
    return re.sub(r"\D", "", str(valeur or ""))


def _maintenant() -> datetime:
    """Date et heure actuelles (UTC). Fonction isolée pour pouvoir la simuler dans les tests."""
    return datetime.now(timezone.utc)


def _fuseau():
    """Fuseau horaire du Burkina Faso (Africa/Ouagadougou = UTC toute l'année)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Africa/Ouagadougou")
    except Exception:  # noqa: BLE001 — base des fuseaux absente : UTC (identique au Burkina)
        return timezone.utc


def _local(dt: datetime) -> datetime:
    """Convertit une date (UTC si sans fuseau) en heure de Ouagadougou."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_fuseau())


def lire_date(valeur: Any) -> Optional[datetime]:
    """Date ISO (texte) ou datetime → datetime avec fuseau (None si illisible)."""
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def formater_date(dt: datetime) -> str:
    """Date affichée « JJ/MM/AAAA HH:MM » (heure de Ouagadougou)."""
    return _local(dt).strftime("%d/%m/%Y %H:%M")


def date_parlee(dt: datetime) -> Tuple[str, str]:
    """Date et heure à prononcer : (« 6 octobre 2026 », « 14 heures 05 »)."""
    d = _local(dt)
    jour = "1er" if d.day == 1 else str(d.day)
    heure = f"{d.hour} heure" + ("s" if d.hour > 1 else "")
    if d.minute:
        heure += f" {d.minute:02d}"
    return f"{jour} {MOIS[d.month - 1]} {d.year}", heure


def _heure_minutes(texte: Any, defaut: str) -> int:
    """« 22:00 » → nombre de minutes depuis minuit (valeur par défaut si illisible)."""
    m = re.fullmatch(r"\s*(\d{1,2})[:hH](\d{2})\s*", str(texte or "")) or re.fullmatch(r"(\d{1,2}):(\d{2})", defaut)
    h, mn = int(m.group(1)), int(m.group(2))
    if h > 23 or mn > 59:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", defaut)
        h, mn = int(m.group(1)), int(m.group(2))
    return h * 60 + mn


def _entier(valeur: Any, defaut: int, mini: int, maxi: int) -> int:
    """Entier borné (valeur par défaut si illisible)."""
    try:
        return max(mini, min(maxi, int(valeur)))
    except (TypeError, ValueError):
        return defaut


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def numeros_proprietaire(s: Dict[str, Any]) -> List[str]:
    """Numéros WhatsApp du propriétaire (chiffres) : réglage, sinon variable d'environnement."""
    brut = s.get("appel_proprio_numeros")
    if isinstance(brut, list):
        brut = ",".join(str(x) for x in brut)
    brut = (brut or "").strip() or os.environ.get("NUMERO_APPEL_PROPRIETAIRE", "")
    sortie: List[str] = []
    for morceau in re.split(r"[,;\n]+", brut or ""):
        chiffres = _chiffres(morceau)
        if len(chiffres) >= 8 and chiffres not in sortie:
            sortie.append(chiffres)
    return sortie


def reglages(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages de l'alerte, complétés par les valeurs par défaut."""
    s = s or {}
    exclus_brut = s.get("appel_proprio_exclus") or ""
    if isinstance(exclus_brut, list):
        exclus_brut = ",".join(str(x) for x in exclus_brut)
    return {
        # Activée par défaut, mais inactive tant qu'aucun numéro du propriétaire n'est connu
        "actif": s.get("appel_proprio_actif") is not False,
        "numeros": numeros_proprietaire(s),
        "numeros_source": "reglage" if (s.get("appel_proprio_numeros") or "") else (
            "environnement" if os.environ.get("NUMERO_APPEL_PROPRIETAIRE") else "aucun"),
        "ligne": (s.get("appel_proprio_ligne") or "principal").strip() or "principal",
        "fenetre_min": _entier(s.get("appel_proprio_fenetre_min"), 30, 1, 24 * 60),
        "calme_actif": bool(s.get("appel_proprio_calme_actif")),
        "calme_debut": s.get("appel_proprio_calme_debut") or "22:00",
        "calme_fin": s.get("appel_proprio_calme_fin") or "06:00",
        "relais_actif": s.get("appel_proprio_relais_actif") is not False,
        "appel_actif": s.get("appel_proprio_appel_actif") is not False,
        "modele": (s.get("appel_proprio_modele") or "").strip(),
        "modele_langue": (s.get("appel_proprio_modele_langue") or "fr").strip() or "fr",
        "voix": (s.get("appel_proprio_voix") or "auto").strip() or "auto",
        "voix_elevenlabs": (s.get("appel_proprio_voix_elevenlabs") or s.get("liluvine_decroche_voix_elevenlabs")
                            or "").strip(),
        # Lot 69.2 — profil de voix commun avec « Liluvine décroche » (accent, voix et modèles)
        **profil_voix(s),
        "repetitions": _entier(s.get("appel_proprio_repetitions"), 2, 1, 3),
        "sonnerie_s": _entier(s.get("appel_proprio_sonnerie_s"), 30, 10, 60),
        "exclus": {_chiffres(x)[-8:] for x in re.split(r"[,;\n]+", exclus_brut) if len(_chiffres(x)) >= 8},
    }


def profil_voix(s: Dict[str, Any]) -> Dict[str, Any]:
    """Lot 69.2 — réglages de voix communs aux appels de Liluvine (lots 67 et 69), saisis dans le bloc
    « Liluvine décroche les appels WhatsApp » : voix et modèle OpenAI, consigne d'accent, modèle ElevenLabs."""
    s = s or {}
    voix = str(s.get("liluvine_decroche_voix_openai") or "nova").strip()
    m_oa = str(s.get("liluvine_decroche_modele_openai") or MODELES_OPENAI[0]).strip()
    m_el = str(s.get("liluvine_decroche_modele_elevenlabs") or MODELES_ELEVENLABS[0]).strip()
    return {
        "voix_openai": voix if voix in VOIX_OPENAI else "nova",
        "modele_openai": m_oa if m_oa in MODELES_OPENAI else MODELES_OPENAI[0],
        "accent": (s.get("liluvine_decroche_accent") or "").strip() or ACCENT_DEFAUT,
        "modele_elevenlabs": m_el if m_el in MODELES_ELEVENLABS else MODELES_ELEVENLABS[0],
    }


def en_heures_calmes(cfg: Dict[str, Any], dt: datetime) -> bool:
    """Vrai si l'heure (de Ouagadougou) tombe dans les heures calmes (pas d'appel, relais seul)."""
    if not cfg.get("calme_actif"):
        return False
    debut = _heure_minutes(cfg.get("calme_debut"), "22:00")
    fin = _heure_minutes(cfg.get("calme_fin"), "06:00")
    d = _local(dt)
    m = d.hour * 60 + d.minute
    if debut == fin:
        return False
    if debut < fin:                       # ex. 12:00 → 14:00 (même journée)
        return debut <= m < fin
    return m >= debut or m < fin          # ex. 22:00 → 06:00 (passe minuit)


def contact_autorise(contact: Optional[Dict[str, Any]]) -> bool:
    """Autorisation de la fiche client « Appeler le propriétaire à chaque message » :
    absente = autorisée (valeur par défaut)."""
    return (contact or {}).get("appel_proprietaire") is not False


def ligne_appelante(s: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """(Phone Number ID Meta, clé de ligne) du numéro SAWALI qui relaie et appelle."""
    from routes.numeros_wa import ligne_par_cle
    ligne = ligne_par_cle(s, cfg.get("ligne")) or ligne_par_cle(s, "principal")
    return ((ligne or {}).get("phone_number_id") or (s.get("wa_phone_number_id") or "").strip(),
            (ligne or {}).get("cle"))


# ---------------------------------------------------------------------------
# Textes : qui écrit, message relayé, message prononcé
# ---------------------------------------------------------------------------

def nom_affiche(contact: Optional[Dict[str, Any]], profil: Optional[str], chiffres: str) -> str:
    """« Nom (+226…) » pour le relais écrit (le numéro seul si personne n'est connu)."""
    nom = ((contact or {}).get("name") or profil or "").strip()
    if nom and not re.fullmatch(r"\+?[\d\s().-]+", nom):
        return f"{nom} (+{chiffres})"
    return f"+{chiffres}"


def nom_parle(contact: Optional[Dict[str, Any]], profil: Optional[str], chiffres: str) -> str:
    """Nom à prononcer ; sans nom : « le numéro 70 11 22 33 » (8 derniers chiffres par paires)."""
    nom = ((contact or {}).get("name") or profil or "").strip()
    if nom and not re.fullmatch(r"\+?[\d\s().-]+", nom):
        return nom
    fin = chiffres[-8:]
    return "le numéro " + " ".join(fin[i:i + 2] for i in range(0, len(fin), 2))


def extrait(texte: Optional[str], longueur: int = 200) -> str:
    """Extrait d'un message sur une seule ligne (les modèles Meta refusent les retours à la ligne)."""
    t = re.sub(r"\s+", " ", (texte or "").strip())
    return t if len(t) <= longueur else t[: longueur - 1].rstrip() + "…"


def texte_relais(qui: str, message: str, dt: datetime) -> str:
    """Message relayé au propriétaire."""
    return f"📩 {qui} écrit au support : \"{extrait(message)}\" — {formater_date(dt)}"


def texte_parle(qui: str, dt: datetime) -> str:
    """Message prononcé par Liluvine pendant l'appel."""
    jour, heure = date_parlee(dt)
    return (f"Bonjour, ici Liluvine. {qui} écrit au support. "
            f"Son dernier message date du {jour} à {heure}.")


# ---------------------------------------------------------------------------
# Décision : faut-il relayer ? faut-il appeler ?
# ---------------------------------------------------------------------------

async def _est_personnel(db, chiffres: str) -> bool:
    """Le numéro appartient-il à un administrateur, superviseur ou modérateur de SAWALI ?"""
    fin = re.escape(chiffres[-8:])
    u = await db.users.find_one({"role": {"$in": list(ROLES_PERSONNEL)},
                                 "$or": [{"phone": {"$regex": fin}}, {"whatsapp": {"$regex": fin}}]}, {"_id": 1})
    return bool(u)


def _numeros_lignes(s: Dict[str, Any]) -> set:
    """8 derniers chiffres des numéros SAWALI eux-mêmes (jamais d'alerte pour un écho)."""
    from routes.numeros_wa import lignes_configurees
    return {_chiffres(li.get("telephone"))[-8:] for li in lignes_configurees(s) if len(_chiffres(li.get("telephone"))) >= 8}


async def decision_relais(db, s: Dict[str, Any], *, chiffres: str, mtype: str, texte: Optional[str],
                          contact: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """Ce message doit-il être relayé au propriétaire ? Renvoie (oui/non, raison)."""
    cfg = reglages(s)
    if not cfg["actif"]:
        return False, "alerte désactivée"
    if not cfg["numeros"]:
        return False, "numéro du propriétaire non renseigné"
    if len(chiffres) < 8:
        return False, "numéro de l'expéditeur invalide"
    fin = chiffres[-8:]
    if fin in {n[-8:] for n in cfg["numeros"]}:
        return False, "message du propriétaire lui-même"
    if mtype not in TYPES_ALERTE:
        return False, f"type de message non concerné ({mtype})"
    t = (texte or "").strip()
    if mtype == "text" and (t.startswith("!") or t.startswith("/") or t.startswith("#R")):
        return False, "commande Liluvine"
    if fin in cfg["exclus"] or fin in _numeros_lignes(s):
        return False, "numéro exclu"
    if not contact_autorise(contact):
        return False, "alerte désactivée sur la fiche du client"
    try:
        from routes.liste_noire_commandes import fiche_bloquee
        if await fiche_bloquee(db, chiffres):
            return False, "numéro en liste noire"
    except Exception:  # noqa: BLE001 — liste noire illisible : on n'empêche pas l'alerte
        pass
    if await _est_personnel(db, chiffres):
        return False, "numéro du personnel SAWALI"
    return True, "ok"


async def appel_recent(db, chiffres: str, minutes: int, maintenant: datetime) -> bool:
    """Un appel d'alerte a-t-il déjà été tenté pour ce client dans les N dernières minutes ?"""
    depuis = (maintenant - timedelta(minutes=minutes)).isoformat()
    doc = await db.wa_appels.find_one({
        "motif": MOTIF, "created_at": {"$gte": depuis},
        "alerte_client_telephone": {"$regex": re.escape(chiffres[-8:]) + "$"},
    }, {"_id": 1})
    return bool(doc)


# ---------------------------------------------------------------------------
# API Graph de Meta (fonctions isolées : remplacées par des imitations dans les tests)
# ---------------------------------------------------------------------------

async def _graph_post(s: Dict[str, Any], numero_id: str, chemin: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """POST /{numero_id}/{chemin} → {"ok", "donnees", "erreur"} (ne lève jamais d'exception)."""
    jeton = (s.get("wa_access_token") or "").strip()
    if not jeton or not numero_id:
        return {"ok": False, "donnees": {}, "erreur": "WhatsApp non configuré (jeton ou numéro manquant)"}
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(f"https://graph.facebook.com/{GRAPH_VERSION}/{numero_id}/{chemin}",
                                json=corps, headers={"Authorization": f"Bearer {jeton}"})
        try:
            donnees = r.json()
        except Exception:  # noqa: BLE001
            donnees = {}
        if r.status_code >= 300:
            err = (donnees.get("error") or {}) if isinstance(donnees, dict) else {}
            details = (err.get("error_data") or {}).get("details")
            message = (err.get("message") or f"HTTP {r.status_code}") + (f" — {details}" if details else "")
            return {"ok": False, "donnees": donnees, "erreur": f"Meta : {message}", "code": err.get("code")}
        return {"ok": True, "donnees": donnees, "erreur": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "donnees": {}, "erreur": f"Meta injoignable : {exc}"}


async def _graph_get(s: Dict[str, Any], numero_id: str, chemin: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """GET /{numero_id}/{chemin} → {"ok", "donnees", "erreur"} (ne lève jamais d'exception)."""
    jeton = (s.get("wa_access_token") or "").strip()
    if not jeton or not numero_id:
        return {"ok": False, "donnees": {}, "erreur": "WhatsApp non configuré"}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{numero_id}/{chemin}",
                               params=params, headers={"Authorization": f"Bearer {jeton}"})
        donnees = r.json() if r.status_code < 300 else {}
        ok = r.status_code < 300
        return {"ok": ok, "donnees": donnees or {}, "erreur": None if ok else f"HTTP {r.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "donnees": {}, "erreur": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Relais écrit au propriétaire
# ---------------------------------------------------------------------------

async def fenetre_24h_ouverte(db, proprio: str, numero_id: str, maintenant: datetime) -> bool:
    """Le propriétaire a-t-il écrit à ce numéro SAWALI depuis moins de 24 h ? (texte libre permis)"""
    depuis = (maintenant - timedelta(hours=24)).isoformat()
    filtre: Dict[str, Any] = {"direction": "inbound", "created_at": {"$gte": depuis},
                              "phone_digits": {"$regex": re.escape(proprio[-8:]) + "$"}}
    # Fenêtre liée au numéro SAWALI (messages antérieurs au lot 59 : numéro non mémorisé)
    filtre["$or"] = [{"wa_numero_id": numero_id}, {"wa_numero_id": None}, {"wa_numero_id": {"$exists": False}}]
    return bool(await db.whatsapp_messages.find_one(filtre, {"_id": 1}))


async def envoyer_relais(db, s: Dict[str, Any], cfg: Dict[str, Any], numero_id: str, proprio: str,
                         texte: str, variables: List[str], maintenant: datetime) -> Dict[str, Any]:
    """Envoie le relais : texte libre dans la fenêtre de 24 h, sinon modèle Meta (s'il est déclaré)."""
    ouverte = await fenetre_24h_ouverte(db, proprio, numero_id, maintenant)
    if not ouverte and cfg["modele"]:
        corps = {"messaging_product": "whatsapp", "to": proprio, "type": "template",
                 "template": {"name": cfg["modele"], "language": {"code": cfg["modele_langue"]},
                              "components": [{"type": "body", "parameters": [
                                  {"type": "text", "text": v[:900] or "—"} for v in variables]}]}}
        mode = "modele"
    else:
        # Fenêtre ouverte, ou pas de modèle : texte libre (Meta le refusera si la fenêtre est fermée)
        corps = {"messaging_product": "whatsapp", "to": proprio, "type": "text",
                 "text": {"body": texte[:4000], "preview_url": False}}
        mode = "texte"
    res = await _graph_post(s, numero_id, "messages", corps)
    mid = ((res.get("donnees") or {}).get("messages") or [{}])[0].get("id") if res["ok"] else None
    erreur = res.get("erreur")
    if not res["ok"] and mode == "texte" and not ouverte:
        erreur = (f"{erreur} — fenêtre de 24 h fermée : déclarez un modèle Meta « relais » dans les réglages")
    # Trace dans la conversation du propriétaire (Centre de messagerie)
    try:
        await db.whatsapp_messages.insert_one({
            "id": str(uuid.uuid4()), "direction": "outbound", "to": f"+{proprio}", "phone_digits": proprio,
            "body": texte, "message_type": "template" if mode == "modele" else "text",
            "template_name": cfg["modele"] if mode == "modele" else None,
            "ai_generated": True, "alerte_proprietaire": True, "sender_label": "Liluvine — alerte propriétaire",
            "wa_numero_id": numero_id, "wa_message_id": mid, "ok": res["ok"], "error": erreur,
            "created_at": maintenant.isoformat(), "sent_at": maintenant.isoformat() if res["ok"] else None,
        })
    except Exception:  # noqa: BLE001
        pass
    return {"ok": res["ok"], "mode": mode, "erreur": erreur, "message_id": mid}


# ---------------------------------------------------------------------------
# Autorisation d'appel du propriétaire (exigée par Meta)
# ---------------------------------------------------------------------------

async def etat_permission(db, s: Dict[str, Any], numero_id: str, proprio: str) -> Dict[str, Any]:
    """État de l'autorisation d'appel : {"etat": accordee | en_attente | refusee | inconnue, ...}."""
    res = await _graph_get(s, numero_id, "call_permissions", {"user_wa_id": proprio})
    trace = await db.wa_appels_permissions.find_one({"telephone": proprio}, {"_id": 0}) or {}
    demande = await db.appel_proprio_demandes.find_one({"telephone": proprio}, {"_id": 0}) or {}
    sortie: Dict[str, Any] = {"telephone": proprio, "demande_le": demande.get("demande_le")}
    if res["ok"] and res["donnees"]:
        perm = res["donnees"].get("permission") or {}
        statut = str(perm.get("status") or "").lower()
        actions = {a.get("action_name"): bool(a.get("can_perform_action")) for a in res["donnees"].get("actions") or []}
        sortie["peut_appeler"] = actions.get("start_call", statut in ("temporary", "permanent"))
        sortie["peut_demander"] = actions.get("send_call_permission_request")
        sortie["etat"] = "accordee" if statut in ("temporary", "permanent") else "en_attente"
        sortie["source"] = "meta"
    else:
        # Meta illisible : dernière réponse connue du propriétaire (webhook)
        if trace.get("accepte"):
            sortie["etat"], sortie["peut_appeler"] = "accordee", True
        elif trace:
            sortie["etat"], sortie["peut_appeler"] = "refusee", False
        else:
            sortie["etat"] = "en_attente" if demande else "inconnue"
            sortie["peut_appeler"] = False
        sortie["peut_demander"] = not trace.get("accepte")
        sortie["source"] = "journal"
    return sortie


async def demander_permission(db, s: Dict[str, Any], numero_id: str, proprio: str, maintenant: datetime,
                              forcer: bool = False) -> Dict[str, Any]:
    """Envoie au propriétaire la demande d'autorisation d'appel (au plus une fois tous les 7 jours,
    sauf demande manuelle depuis les réglages)."""
    deja = await db.appel_proprio_demandes.find_one({"telephone": proprio}, {"_id": 0}) or {}
    derniere = lire_date(deja.get("demande_le"))
    if not forcer and derniere and maintenant - derniere < INTERVALLE_DEMANDE:
        return {"ok": True, "envoyee": False, "raison": "demande déjà envoyée récemment"}
    texte = ("Bonjour, ici Liluvine (SAWALI). Pour vous prévenir par un appel WhatsApp à chaque message "
             "d'un client, j'ai besoin de votre autorisation. Acceptez-vous mes appels ?")
    res = await _graph_post(s, numero_id, "messages", {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": proprio, "type": "interactive",
        "interactive": {"type": "call_permission_request", "action": {"name": "call_permission_request"},
                        "body": {"text": texte}}})
    await db.appel_proprio_demandes.update_one(
        {"telephone": proprio},
        {"$set": {"telephone": proprio, "demande_le": maintenant.isoformat(), "ok": res["ok"],
                  "erreur": res.get("erreur")}}, upsert=True)
    logger.info("[appel_proprietaire] demande d'autorisation d'appel …%s : %s", proprio[-4:],
                "envoyée" if res["ok"] else res.get("erreur"))
    return {"ok": res["ok"], "envoyee": res["ok"], "raison": res.get("erreur")}


# ---------------------------------------------------------------------------
# Voix de Liluvine (synthèse vocale) et décodage en trames audio 48 kHz
# ---------------------------------------------------------------------------

# Lot 69.2 — Voix OpenAI proposées (gpt-4o-mini-tts les accepte toutes ; tts-1 seulement les 9 premières)
VOIX_OPENAI_TTS1 = ("alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer")
VOIX_OPENAI = VOIX_OPENAI_TTS1 + ("ballad", "verse", "cedar", "marin")
# Modèles de voix : OpenAI (gpt-4o-mini-tts suit une consigne d'accent / de ton) et ElevenLabs
MODELES_OPENAI = ("gpt-4o-mini-tts", "tts-1")
MODELES_ELEVENLABS = ("eleven_flash_v2_5", "eleven_multilingual_v2")
# Consigne d'accent par défaut (gpt-4o-mini-tts)
ACCENT_DEFAUT = "français d'Afrique de l'Ouest, chaleureux et posé"
# Les voix OpenAI et ElevenLabs sont demandées en PCM brut 24 kHz (aucun MP3 à décoder)
FREQUENCE_VOIX = 24000


def consigne_accent(accent: str) -> str:
    """Consigne donnée à gpt-4o-mini-tts : accent, ton et débit (paramètre « instructions »)."""
    accent = (accent or "").strip() or ACCENT_DEFAUT
    return (f"Parle en français avec cet accent et ce style : {accent}. Par exemple un accent d'Afrique de "
            "l'Ouest (Burkina Faso). Ton chaleureux et professionnel, débit posé, articulation claire, "
            "comme une hôtesse d'accueil au téléphone.")


def _wav(pcm: bytes, frequence: int) -> bytes:
    """PCM brut → WAV (simple en-tête, aucun calcul) pour garder une seule interface « fichier audio »."""
    from routes.audio_appel import wav_depuis_pcm
    return wav_depuis_pcm(pcm, frequence)


async def _voix_openai(texte: str, s: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None) -> bytes:
    """Synthèse OpenAI en PCM 24 kHz (rendu en WAV). Lot 69.2 : modèle gpt-4o-mini-tts avec consigne
    d'accent (« instructions »), voix au choix ; repli automatique sur tts-1 si le modèle est refusé.
    Clé lue dans les réglages (ancien) ou la variable d'environnement OPENAI_API_KEY."""
    cfg = cfg or {}
    cle = (s.get("openai_api_key") or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not cle:
        raise RuntimeError("clé OpenAI absente")
    voix = cfg.get("voix_openai") if cfg.get("voix_openai") in VOIX_OPENAI else "nova"
    modele = cfg.get("modele_openai") if cfg.get("modele_openai") in MODELES_OPENAI else MODELES_OPENAI[0]
    essais = [modele] + (["tts-1"] if modele != "tts-1" else [])
    erreur = ""
    async with httpx.AsyncClient(timeout=30) as http:
        for m in essais:
            corps: Dict[str, Any] = {"model": m, "input": texte, "response_format": "pcm",
                                     "voice": voix if (m != "tts-1" or voix in VOIX_OPENAI_TTS1) else "nova"}
            if m == "gpt-4o-mini-tts":
                corps["instructions"] = consigne_accent(cfg.get("accent") or "")
            r = await http.post("https://api.openai.com/v1/audio/speech", json=corps,
                                headers={"Authorization": f"Bearer {cle}"})
            if r.status_code < 300 and r.content:
                return _wav(r.content, FREQUENCE_VOIX)
            erreur = f"OpenAI HTTP {r.status_code} ({m})"
    raise RuntimeError(erreur)


async def _voix_elevenlabs(texte: str, cfg: Dict[str, Any]) -> bytes:
    """Synthèse ElevenLabs (voix choisie dans les réglages) en PCM 24 kHz (rendu en WAV).
    Lot 69.2 : modèle au choix, eleven_flash_v2_5 par défaut (le plus rapide pour le téléphone).
    Clé ELEVENLABS_API_KEY (variable d'environnement)."""
    cle = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not cle or not cfg.get("voix_elevenlabs"):
        raise RuntimeError("clé ou voix ElevenLabs absente")
    modele = cfg.get("modele_elevenlabs") if cfg.get("modele_elevenlabs") in MODELES_ELEVENLABS else MODELES_ELEVENLABS[0]
    corps: Dict[str, Any] = {"text": texte, "model_id": modele}
    if "flash" in modele or "turbo" in modele:
        corps["language_code"] = "fr"          # langue imposée (accepté par les modèles flash / turbo)
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['voix_elevenlabs']}",
                            params={"output_format": f"pcm_{FREQUENCE_VOIX}"}, json=corps,
                            headers={"xi-api-key": cle})
    if r.status_code >= 300 or not r.content:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}")
    return _wav(r.content, FREQUENCE_VOIX)


def decouper_texte(texte: str, maxi: int = 180) -> List[str]:
    """Découpe le texte en morceaux de moins de 200 caractères (limite du service vocal Google),
    de préférence à la fin d'une phrase ou après une virgule."""
    morceaux: List[str] = []
    reste = re.sub(r"\s+", " ", texte).strip()
    while len(reste) > maxi:
        coupe = max(reste.rfind(". ", 0, maxi), reste.rfind(", ", 0, maxi))
        if coupe <= 0:
            coupe = reste.rfind(" ", 0, maxi)
        if coupe <= 0:
            coupe = maxi - 1
        morceaux.append(reste[: coupe + 1].strip())
        reste = reste[coupe + 1:].strip()
    if reste:
        morceaux.append(reste)
    return morceaux


async def _voix_google(texte: str) -> bytes:
    """Voix de secours Google (voix féminine française, sans clé) : MP3 des morceaux mis bout à bout."""
    audio = b""
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) as http:
        for morceau in decouper_texte(texte):
            r = await http.get("https://translate.google.com/translate_tts",
                               params={"ie": "UTF-8", "client": "tw-ob", "tl": "fr", "q": morceau})
            if r.status_code >= 300 or not r.content:
                raise RuntimeError(f"Google HTTP {r.status_code}")
            audio += r.content
    return audio


def fournisseurs_voix(s: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    """Ordre d'essai des voix : choix des réglages, sinon OpenAI → ElevenLabs → Google (selon les clés)."""
    if cfg["voix"] in ("openai", "elevenlabs", "google"):
        ordre = [cfg["voix"]]
    else:
        ordre = []
        if (s.get("openai_api_key") or "").strip() or os.environ.get("OPENAI_API_KEY"):
            ordre.append("openai")
        if os.environ.get("ELEVENLABS_API_KEY") and cfg.get("voix_elevenlabs"):
            ordre.append("elevenlabs")
    if "google" not in ordre:
        ordre.append("google")            # toujours en dernier recours (aucune clé nécessaire)
    return ordre


async def synthetiser(texte: str, s: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[bytes, str]:
    """Fabrique l'audio (WAV pour OpenAI / ElevenLabs, MP3 pour Google) du message ; renvoie (octets, fournisseur). Lève RuntimeError si tout échoue."""
    erreurs = []
    for f in fournisseurs_voix(s, cfg):
        try:
            if f == "openai":
                return await _voix_openai(texte, s, cfg), f
            if f == "elevenlabs":
                return await _voix_elevenlabs(texte, cfg), f
            return await _voix_google(texte), f
        except Exception as exc:  # noqa: BLE001 — on essaie la voix suivante
            erreurs.append(f"{f} : {str(exc)[:80]}")
    raise RuntimeError("synthèse vocale impossible (" + " ; ".join(erreurs) + ")")


def decoder_pcm(audio: bytes) -> bytes:
    """Décode un fichier audio (MP3, WAV…) en PCM 16 bits mono 48 kHz (lot 69.2 : module audio_appel)."""
    from routes.audio_appel import decoder_pcm as _decoder
    return _decoder(audio)


def preparer_pcm(audio: bytes) -> bytes:
    """Lot 69.2 — décodage 48 kHz + silences de début/fin raccourcis (à appeler hors de la boucle)."""
    from routes.audio_appel import preparer_pcm as _preparer
    return _preparer(audio)


def creer_piste(pcm: bytes, repetitions: int = 2, pause_s: float = 1.2):
    """Piste audio « message répété » (compatibilité, utilisée par les tests comme voix d'un appelant) :
    silence tant que lecture() n'est pas appelée, puis le message (répété), puis silence ;
    l'évènement `fini` est posé à la fin de la lecture. Repose sur la piste persistante du lot 69.2
    (horloge monotone, pré-chargement nul : le message est entièrement prêt)."""
    from routes.audio_appel import creer_piste_voix
    programme = (pcm + b"\x00" * int(FREQUENCE * pause_s) * 2) * max(1, repetitions)
    piste = creer_piste_voix(prechargement_ms=0)
    piste.fini = asyncio.Event()
    recv_origine = piste.recv

    def lecture() -> None:
        """Démarre la lecture du message."""
        piste.ajouter(programme)
        piste.fin_reponse()

    async def recv():
        """Trame suivante ; `fini` est posé quand tout le message a été joué."""
        trame = await recv_origine()
        if piste.lecteur.trames_son and not piste.en_lecture and not piste.fini.is_set():
            piste.fini.set()
        return trame

    piste.lecture = lecture
    piste.recv = recv
    return piste


def serveurs_ice() -> list:
    """Serveurs STUN/TURN : STUN public + TURN facultatif (variables d'environnement)."""
    from aiortc import RTCIceServer
    serveurs = [RTCIceServer(urls=STUN_DEFAUT)]
    turn = os.environ.get("APPEL_TURN_URL", "").strip()
    if turn:
        serveurs.append(RTCIceServer(urls=turn, username=os.environ.get("APPEL_TURN_UTILISATEUR") or None,
                                     credential=os.environ.get("APPEL_TURN_MOT_DE_PASSE") or None))
    return serveurs


def moteur_disponible() -> Tuple[bool, str]:
    """aiortc et av sont-ils installés ? (sinon : relais seul)"""
    try:
        import aiortc  # noqa: F401
        import av  # noqa: F401
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"aiortc indisponible : {exc}"


# ---------------------------------------------------------------------------
# Appel vocal au propriétaire
# ---------------------------------------------------------------------------

async def _attendre(predicat, delai_s: float, pas_s: float = 0.4):
    """Attend qu'une coroutine renvoie une valeur « vraie » (None après le délai)."""
    limite = time.monotonic() + delai_s
    while time.monotonic() < limite:
        valeur = await predicat()
        if valeur:
            return valeur
        await asyncio.sleep(pas_s)
    return None


async def _raccrocher(s: Dict[str, Any], numero_id: str, call_id: str) -> None:
    """Termine l'appel chez Meta (action terminate)."""
    await _graph_post(s, numero_id, "calls", {"messaging_product": "whatsapp", "call_id": call_id, "action": "terminate"})


async def _journal(db, call_id: str, **champs) -> None:
    """Met à jour la ligne de l'appel dans le journal."""
    champs["maj"] = _maintenant().isoformat()
    await db.wa_appels.update_one({"id": call_id}, {"$set": champs})


async def appeler_et_parler(db, s: Dict[str, Any], cfg: Dict[str, Any], *, numero_id: str, ligne_cle: Optional[str],
                            proprio: str, texte_voix: str, alerte: Dict[str, Any]) -> Dict[str, Any]:
    """Appelle le propriétaire et lui fait entendre le message de Liluvine. Renvoie {resultat, raison}.
    Chaque tentative (même échouée avant Meta) est inscrite au journal des appels.
    Lot 67.1 : la réponse contient aussi les mesures de l'appel (clé « mesures ») utilisées par
    l'historique : voix utilisée, caractères synthétisés, durée de sonnerie et de conversation."""
    maintenant = _maintenant()
    # Mesures de l'appel (lot 67.1) : remplies au fil des étapes, renvoyées dans tous les cas
    mesures: Dict[str, Any] = {"voix": None, "tts_caracteres": 0, "sonnerie_s": 0, "conversation_s": 0}
    # Instants (horloge monotone) : appel lancé, décroché, raccroché
    instants: Dict[str, Optional[float]] = {"appel": None, "decroche": None}

    def _mesurer_fin() -> None:
        """Calcule la durée de sonnerie et de conversation au moment de raccrocher."""
        fin = time.monotonic()
        if instants["appel"] is not None:
            fin_sonnerie = instants["decroche"] if instants["decroche"] is not None else fin
            mesures["sonnerie_s"] = max(0, int(round(fin_sonnerie - instants["appel"])))
        if instants["decroche"] is not None:
            mesures["conversation_s"] = max(0, int(round(fin - instants["decroche"])))
    base = {"direction": "sortant", "motif": MOTIF, "numero_id": numero_id, "ligne_cle": ligne_cle,
            "telephone": proprio, "contact_nom": "Propriétaire (alerte Liluvine)", "auto": True,
            "agent_id": None, "decroche_par_nom": "Liluvine", "texte_parle": texte_voix,
            "created_at": maintenant.isoformat(), "maj": maintenant.isoformat(), **alerte}

    async def echec_avant_meta(raison: str) -> Dict[str, Any]:
        """Échec avant l'appel : ligne « échec » au journal."""
        await db.wa_appels.insert_one({**base, "id": f"alerte-{uuid.uuid4()}", "statut": "echec",
                                       "resultat": "échec", "raison": raison})
        logger.warning("[appel_proprietaire] appel impossible : %s", raison)
        return {"resultat": "échec", "raison": raison, "mesures": mesures}

    ok, raison = moteur_disponible()
    if not ok:
        return await echec_avant_meta(raison)
    # 1. Voix de Liluvine
    try:
        audio, fournisseur = await synthetiser(texte_voix, s, cfg)
        # Lot 69.2 : décodage + silences raccourcis hors de la boucle (fil séparé)
        pcm = await asyncio.to_thread(preparer_pcm, audio)
        if len(pcm) < FREQUENCE:                  # moins d'une demi-seconde : audio inutilisable
            raise RuntimeError("audio vide")
        # Voix fabriquée : fournisseur et nombre de caractères synthétisés (coût de la synthèse)
        mesures["voix"], mesures["tts_caracteres"] = fournisseur, len(texte_voix)
    except Exception as exc:  # noqa: BLE001
        return await echec_avant_meta(f"voix : {str(exc)[:200]}")

    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
    from routes.audio_appel import creer_piste_voix, sur_media
    ice = serveurs_ice()

    # Lot 69.2 : la connexion WebRTC et la piste vivent dans la BOUCLE MÉDIA dédiée (son régulier
    # même si l'API est chargée). On les crée là-bas, et on y exécute chaque opération WebRTC.
    async def _creer():
        """(boucle média) Connexion + piste persistante + offre SDP."""
        connexion = RTCPeerConnection(RTCConfiguration(iceServers=ice))
        p = creer_piste_voix()
        connexion.addTrack(p)
        await connexion.setLocalDescription(await connexion.createOffer())
        return connexion, p
    pc = None
    call_id: Optional[str] = None
    try:
        # 2. Offre SDP avec la piste audio (aiortc rassemble les candidats ICE avant de rendre la main)
        pc, piste = await sur_media(_creer)
        rep = await _graph_post(s, numero_id, "calls", {
            "messaging_product": "whatsapp", "to": proprio, "action": "connect",
            "session": {"sdp_type": "offer", "sdp": pc.localDescription.sdp},
            "biz_opaque_callback_data": "alerte-message"})
        call_id = ((rep.get("donnees") or {}).get("calls") or [{}])[0].get("id") if rep["ok"] else None
        instants["appel"] = time.monotonic()      # début de la sonnerie
        if not call_id:
            return await echec_avant_meta(rep.get("erreur") or "Meta n'a pas renvoyé d'identifiant d'appel")
        await db.wa_appels.insert_one({**base, "id": call_id, "statut": "appel", "resultat": "sonné",
                                       "voix": fournisseur})

        # 3. Sonnerie : attente de la réponse SDP (le propriétaire décroche) ou d'un refus
        async def reponse():
            doc = await db.wa_appels.find_one({"id": call_id}, {"_id": 0, "sdp_reponse": 1, "statut": 1}) or {}
            if doc.get("sdp_reponse"):
                return {"sdp": doc["sdp_reponse"]}
            if doc.get("statut") in ("refuse", "sans_reponse", "termine", "manque"):
                return {"fin": doc["statut"]}
            return None
        etat = await _attendre(reponse, cfg["sonnerie_s"])
        if not etat or etat.get("fin"):
            resultat = "refusé" if (etat or {}).get("fin") == "refuse" else "sans réponse"
            _mesurer_fin()
            await _raccrocher(s, numero_id, call_id)
            await _journal(db, call_id, resultat=resultat, statut="refuse" if resultat == "refusé" else "sans_reponse")
            return {"resultat": resultat, "raison": None, "call_id": call_id, "mesures": mesures}

        # 4. Décroché : réponse SDP appliquée, attente de la connexion audio (ICE + DTLS)
        instants["decroche"] = time.monotonic()   # fin de la sonnerie, début de la conversation
        await sur_media(lambda: pc.setRemoteDescription(RTCSessionDescription(sdp=etat["sdp"], type="answer")))

        async def connecte():
            if pc.connectionState == "failed":
                return "failed"
            return "ok" if pc.connectionState == "connected" else None
        cnx = await _attendre(connecte, 12, 0.2)
        if cnx != "ok":
            raison = ("connexion audio impossible (ICE/DTLS) — l'UDP sortant est peut-être bloqué "
                      "par l'hébergeur : configurez un serveur TURN (APPEL_TURN_URL)")
            _mesurer_fin()
            await _raccrocher(s, numero_id, call_id)
            await _journal(db, call_id, resultat="échec", raison=raison)
            return {"resultat": "échec", "raison": raison, "call_id": call_id, "mesures": mesures}

        # 5. Liluvine parle (le message est répété), puis raccroche
        await asyncio.sleep(1.0)
        # Message répété (avec une pause) ajouté d'un bloc à la file de la piste persistante
        piste.debut_reponse()
        piste.ajouter((pcm + b"\x00" * int(FREQUENCE * 1.2) * 2) * max(1, cfg["repetitions"]))
        piste.fin_reponse()
        duree_max = len(pcm) / (FREQUENCE * 2) * cfg["repetitions"] + 2 * cfg["repetitions"] + 5
        limite = time.monotonic() + duree_max
        while piste.en_lecture and time.monotonic() < limite:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.8)
        _mesurer_fin()
        await _raccrocher(s, numero_id, call_id)
        await _journal(db, call_id, resultat="décroché", raison=None, message_lu=True)
        return {"resultat": "décroché", "raison": None, "call_id": call_id, "mesures": mesures}
    except Exception as exc:  # noqa: BLE001 — jamais d'exception vers l'appelant
        raison = f"erreur : {str(exc)[:200]}"
        if call_id:
            _mesurer_fin()
            await _raccrocher(s, numero_id, call_id)
            await _journal(db, call_id, resultat="échec", raison=raison)
            return {"resultat": "échec", "raison": raison, "call_id": call_id, "mesures": mesures}
        return await echec_avant_meta(raison)
    finally:
        try:
            if pc is not None:
                await sur_media(pc.close)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Lot 67.1 — Historique des appels automatiques de Liluvine : durées et coûts
# ---------------------------------------------------------------------------
#
# Une ligne par alerte et par numéro du propriétaire dans db.appel_proprio_historique :
#   date/heure de début, client (qui a écrit), destinataire (numéro du propriétaire appelé),
#   ligne SAWALI (Standard / VIP), durée de sonnerie, durée de conversation (secondes),
#   résultat, relais envoyé (texte libre ou modèle Meta), voix utilisée et caractères synthétisés,
#   coût calculé AU MOMENT DE L'APPEL avec le tarif de ce moment (le tarif est recopié dans la
#   ligne : un changement de tarif ultérieur ne réécrit jamais l'historique).
#
# Règle de facturation de Meta (Calling API, page « Pricing ») : seuls les appels émis par
# l'entreprise sont facturés, à la durée, « calculée en tranches (pulses) de 6 secondes » ;
# une tranche entamée est due (ex. 56 s = 9,33 tranches → 10 tranches). Le tarif est publié
# à la minute, par pays appelé et par palier de volume mensuel. Arrondi par défaut : « pulse6 ».

# Collection de l'historique
COLLECTION_HISTORIQUE = "appel_proprio_historique"
# Devises proposées et modes d'arrondi de la durée facturée
DEVISES = ("FCFA", "USD")
ARRONDIS = {"pulse6": 6, "minute": 60, "seconde": 1}
# Catégories de résultat (filtres, badges, synthèse)
CATEGORIES = ("decroche", "sans_reponse", "echec", "relais_seul")
# Périodes de la synthèse et étendue par défaut (en jours) quand aucune date n'est donnée
PERIODES = {"jour": 30, "semaine": 7 * 12, "mois": 365, "annee": 365 * 5}


def _decimal(valeur: Any, defaut: float = 0.0) -> float:
    """Nombre décimal positif (accepte la virgule : « 12,5 ») ; valeur par défaut si illisible."""
    try:
        return max(0.0, float(str(valeur).replace(",", ".").replace(" ", "")))
    except (TypeError, ValueError):
        return defaut


def tarif_actuel(s: Dict[str, Any]) -> Dict[str, Any]:
    """Tarif en vigueur (réglages), complété par les valeurs par défaut (tout à 0, FCFA, tranches de 6 s)."""
    s = s or {}
    devise = str(s.get("appel_proprio_tarif_devise") or "FCFA").upper()
    arrondi = str(s.get("appel_proprio_tarif_arrondi") or "pulse6")
    return {
        "minute": _decimal(s.get("appel_proprio_tarif_appel_minute")),          # prix d'une minute d'appel
        "devise": devise if devise in DEVISES else "FCFA",
        "arrondi": arrondi if arrondi in ARRONDIS else "pulse6",
        "relais_modele": _decimal(s.get("appel_proprio_tarif_relais_modele")),  # prix d'un message modèle
        "tts_1000": _decimal(s.get("appel_proprio_tarif_tts_1000")),            # prix de 1000 caractères de voix
    }


def secondes_facturees(duree_s: Any, arrondi: str = "pulse6") -> int:
    """Durée facturée : arrondie à la tranche supérieure (6 s chez Meta, ou minute entamée, ou seconde)."""
    try:
        duree = max(0, int(duree_s or 0))
    except (TypeError, ValueError):
        return 0
    pas = ARRONDIS.get(arrondi, 6)
    return -(-duree // pas) * pas             # division arrondie vers le haut


def calculer_cout(tarif: Dict[str, Any], *, conversation_s: Any, relais_modele: bool,
                  tts_caracteres: int, voix: Optional[str]) -> Dict[str, Any]:
    """Coût d'une alerte = appel (durée facturée × tarif minute) + relais par modèle Meta
    + voix de synthèse (la voix Google, gratuite, n'est pas comptée)."""
    facture = secondes_facturees(conversation_s, tarif.get("arrondi", "pulse6"))
    cout_appel = facture / 60 * float(tarif.get("minute") or 0)
    cout_relais = float(tarif.get("relais_modele") or 0) if relais_modele else 0.0
    cout_tts = 0.0
    if voix and voix != "google" and tts_caracteres:
        cout_tts = tts_caracteres / 1000 * float(tarif.get("tts_1000") or 0)
    return {"secondes_facturees": facture, "cout_appel": round(cout_appel, 2), "cout_relais": round(cout_relais, 2),
            "cout_tts": round(cout_tts, 2), "cout_total": round(cout_appel + cout_relais + cout_tts, 2)}


def categorie_resultat(resultat: Optional[str]) -> str:
    """Résultat d'appel → catégorie : décroché, sans réponse (dont refusé), échec, relais seul."""
    if not resultat:
        return "relais_seul"
    return {"décroché": "decroche", "sans réponse": "sans_reponse", "refusé": "sans_reponse"}.get(resultat, "echec")


def _libelle_ligne(s: Dict[str, Any], cle: Optional[str]) -> str:
    """Libellé de la ligne SAWALI (« Liluvine Standard », « Liluvine VIP »…) d'après sa clé."""
    try:
        from routes.numeros_wa import lignes_configurees
        for li in lignes_configurees(s):
            if li.get("cle") == cle:
                return li.get("libelle") or cle or ""
    except Exception:  # noqa: BLE001 — libellé facultatif
        pass
    return cle or ""


async def noter_historique(db, *, s: Dict[str, Any], cfg: Dict[str, Any], maintenant: datetime, numero_id: str,
                           ligne_cle: Optional[str], client_telephone: str, client_nom: str, destinataire: str,
                           relais: Optional[Dict[str, Any]], appel: Optional[Dict[str, Any]], raison: Optional[str],
                           test: bool = False, client_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Inscrit une ligne dans l'historique des appels de Liluvine (ne lève jamais d'exception)."""
    try:
        mesures = (appel or {}).get("mesures") or {}
        call_id = (appel or {}).get("call_id")
        conversation = int(mesures.get("conversation_s") or 0)
        source = "serveur"
        # Durée donnée par Meta (webhook « terminate ») si elle est déjà arrivée : elle est préférée
        if call_id:
            j = await db.wa_appels.find_one({"id": call_id}, {"_id": 0, "duree_s": 1, "statut_meta": 1}) or {}
            if "statut_meta" in j:
                conversation, source = int(j.get("duree_s") or 0), "meta"
        tarif = tarif_actuel(s)                   # tarif FIGÉ dans la ligne
        relais_ok = bool((relais or {}).get("ok"))
        relais_mode = (relais or {}).get("mode") if relais else None
        doc = {
            "id": str(uuid.uuid4()), "created_at": maintenant.isoformat(), "test": bool(test),
            "client_id": client_id,
            "client_nom": client_nom, "client_telephone": client_telephone, "destinataire": destinataire,
            "numero_id": numero_id, "ligne_cle": ligne_cle, "ligne_libelle": _libelle_ligne(s, ligne_cle),
            "call_id": call_id, "resultat": (appel or {}).get("resultat") or "relais seul",
            "categorie": categorie_resultat((appel or {}).get("resultat")), "raison": raison,
            "relais_envoye": relais_ok, "relais_mode": relais_mode if relais else None,
            "relais_modele": cfg.get("modele") if relais_mode == "modele" else None,
            "relais_erreur": (relais or {}).get("erreur"),
            "voix": mesures.get("voix"), "tts_caracteres": int(mesures.get("tts_caracteres") or 0),
            "sonnerie_s": int(mesures.get("sonnerie_s") or 0), "conversation_s": conversation,
            "duree_source": source, "tarif": tarif, "devise": tarif["devise"],
        }
        doc.update(calculer_cout(tarif, conversation_s=conversation, relais_modele=relais_ok and relais_mode == "modele",
                                 tts_caracteres=doc["tts_caracteres"], voix=doc["voix"]))
        await db[COLLECTION_HISTORIQUE].insert_one(dict(doc))
        return doc
    except Exception:  # noqa: BLE001 — l'historique ne doit jamais empêcher l'alerte
        logger.warning("[appel_proprietaire] historique non inscrit", exc_info=True)
        return None


async def noter_duree_meta(db, call_id: str, duree_s: Any) -> bool:
    """Webhook « terminate » de Meta : la durée officielle remplace la durée mesurée par le serveur,
    et le coût est recalculé avec le tarif FIGÉ de la ligne (jamais avec le tarif actuel)."""
    doc = await db[COLLECTION_HISTORIQUE].find_one({"call_id": call_id}, {"_id": 0})
    if not doc:
        return False                              # ligne pas encore écrite : elle lira la durée Meta
    try:
        duree = max(0, int(duree_s or 0))
    except (TypeError, ValueError):
        return False
    cout = calculer_cout(doc.get("tarif") or {}, conversation_s=duree,
                         relais_modele=bool(doc.get("relais_envoye")) and doc.get("relais_mode") == "modele",
                         tts_caracteres=int(doc.get("tts_caracteres") or 0), voix=doc.get("voix"))
    await db[COLLECTION_HISTORIQUE].update_one({"call_id": call_id}, {"$set": {
        "conversation_s": duree, "duree_source": "meta", **cout}})
    return True


def lire_jour(texte: Optional[str]) -> Optional[datetime]:
    """« AAAA-MM-JJ » → minuit UTC de ce jour (None si vide) ; ValueError si illisible."""
    if not texte:
        return None
    return datetime.strptime(str(texte)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)


def filtre_historique(du: Optional[str], au: Optional[str], client: Optional[str] = None,
                      resultat: Optional[str] = None) -> Dict[str, Any]:
    """Filtre MongoDB de l'historique : dates (incluses, heure de Ouagadougou = UTC), client, résultat."""
    filtre: Dict[str, Any] = {}
    debut, fin = lire_jour(du), lire_jour(au)
    if debut or fin:
        filtre["created_at"] = {}
        if debut:
            filtre["created_at"]["$gte"] = debut.isoformat()
        if fin:
            filtre["created_at"]["$lt"] = (fin + timedelta(days=1)).isoformat()   # jour de fin inclus
    if client and client.strip():
        motif = re.escape(client.strip())
        ou = [{"client_nom": {"$regex": motif, "$options": "i"}}]
        if _chiffres(client):
            ou.append({"client_telephone": {"$regex": re.escape(_chiffres(client))}})
        filtre["$or"] = ou
    if resultat:
        if resultat not in CATEGORIES:
            raise ValueError("résultat inconnu")
        filtre["categorie"] = resultat
    return filtre


def totaliser(docs: List[Dict[str, Any]], devise_defaut: str = "FCFA") -> Dict[str, Any]:
    """Cumuls d'un ensemble de lignes : nombres par résultat, durées, coûts (par devise)."""
    t: Dict[str, Any] = {"alertes": len(docs), "appels": 0, "decroches": 0, "sans_reponse": 0, "echecs": 0,
                         "relais_seuls": 0, "duree_totale_s": 0, "sonnerie_totale_s": 0, "couts": {}}
    for d in docs:
        cat = d.get("categorie") or "relais_seul"
        if cat == "relais_seul":
            t["relais_seuls"] += 1
        else:
            t["appels"] += 1
            t[{"decroche": "decroches", "sans_reponse": "sans_reponse"}.get(cat, "echecs")] += 1
        t["duree_totale_s"] += int(d.get("conversation_s") or 0)
        t["sonnerie_totale_s"] += int(d.get("sonnerie_s") or 0)
        devise = d.get("devise") or devise_defaut
        t["couts"][devise] = round(t["couts"].get(devise, 0.0) + float(d.get("cout_total") or 0), 2)
    t["duree_moyenne_s"] = int(round(t["duree_totale_s"] / t["decroches"])) if t["decroches"] else 0
    # Coût total : une seule devise dans l'immense majorité des cas
    devises = list(t["couts"]) or [devise_defaut]
    t["devise"] = devises[0] if len(devises) == 1 else "mixte"
    t["cout_total"] = round(sum(t["couts"].values()), 2) if len(devises) == 1 else None
    return t


def cle_periode(dt: datetime, periode: str) -> Tuple[str, str]:
    """(clé de tri, libellé) de la période d'une date : jour, semaine (du lundi), mois ou année."""
    d = _local(dt)
    if periode == "jour":
        return d.strftime("%Y-%m-%d"), d.strftime("%d/%m/%Y")
    if periode == "semaine":
        lundi = (d - timedelta(days=d.weekday())).date()
        return lundi.isoformat(), f"Semaine du {lundi.strftime('%d/%m/%Y')}"
    if periode == "mois":
        return d.strftime("%Y-%m"), f"{MOIS[d.month - 1].capitalize()} {d.year}"
    return d.strftime("%Y"), d.strftime("%Y")


def synthese_par_periode(docs: List[Dict[str, Any]], periode: str, devise_defaut: str = "FCFA") -> Dict[str, Any]:
    """Regroupe les lignes par période (jour / semaine / mois / année) avec les cumuls de chacune."""
    groupes: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        dt = lire_date(d.get("created_at"))
        if not dt:
            continue
        cle, libelle = cle_periode(dt, periode)
        groupes.setdefault(cle, {"cle": cle, "libelle": libelle, "docs": []})["docs"].append(d)
    lignes = [{"cle": g["cle"], "libelle": g["libelle"], **totaliser(g["docs"], devise_defaut)}
              for g in sorted(groupes.values(), key=lambda g: g["cle"], reverse=True)]
    return {"periode": periode, "lignes": lignes, "totaux": totaliser(docs, devise_defaut)}


def _hms(secondes: Any) -> str:
    """Durée en secondes → « hh:mm:ss »."""
    sec = max(0, int(secondes or 0))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def csv_historique(docs: List[Dict[str, Any]]) -> str:
    """Export CSV (séparateur « ; », lisible par Excel en français) de l'historique."""
    import csv
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    w.writerow(["Date/Heure", "Client", "Téléphone client", "Destinataire", "Ligne", "Sonnerie (s)",
                "Conversation (s)", "Conversation (hh:mm:ss)", "Source durée", "Résultat", "Raison", "Relais",
                "Modèle", "Voix", "Caractères synthétisés", "Secondes facturées", "Coût appel", "Coût relais",
                "Coût voix", "Coût total", "Devise", "Essai"])
    nombre = lambda v: str(v if v is not None else 0).replace(".", ",")  # noqa: E731 — virgule décimale
    for d in docs:
        dt = lire_date(d.get("created_at"))
        relais = ("modèle" if d.get("relais_mode") == "modele" else "écrit") if d.get("relais_envoye") else "non"
        w.writerow([_local(dt).strftime("%d/%m/%Y %H:%M:%S") if dt else "", d.get("client_nom") or "",
                    f"+{d.get('client_telephone')}" if d.get("client_telephone") else "",
                    f"+{d.get('destinataire')}" if d.get("destinataire") else "", d.get("ligne_libelle") or "",
                    d.get("sonnerie_s") or 0, d.get("conversation_s") or 0, _hms(d.get("conversation_s")),
                    d.get("duree_source") or "", d.get("resultat") or "", d.get("raison") or "", relais,
                    d.get("relais_modele") or "", d.get("voix") or "", d.get("tts_caracteres") or 0,
                    d.get("secondes_facturees") or 0, nombre(d.get("cout_appel")), nombre(d.get("cout_relais")),
                    nombre(d.get("cout_tts")), nombre(d.get("cout_total")), d.get("devise") or "",
                    "oui" if d.get("test") else ""])
    return sortie.getvalue()


# ---------------------------------------------------------------------------
# Traitement complet d'un message reçu (appelé en arrière-plan par le webhook)
# ---------------------------------------------------------------------------

def _verrou_client(chiffres: str) -> asyncio.Lock:
    """Verrou propre à un client (deux messages simultanés = un seul appel)."""
    cle = chiffres[-8:]
    if cle not in _verrous_clients:
        _verrous_clients[cle] = asyncio.Lock()
    return _verrous_clients[cle]


def _verrou_global() -> asyncio.Lock:
    """Verrou « un seul appel au propriétaire à la fois »."""
    global _verrou_appel
    if _verrou_appel is None:
        _verrou_appel = asyncio.Lock()
    return _verrou_appel


async def traiter_message(db, *, chiffres: str, mtype: str, texte: Optional[str],
                          contact: Optional[Dict[str, Any]] = None, profil: Optional[str] = None,
                          recu_le: Optional[Any] = None, client_id: Optional[str] = None,
                          test: bool = False) -> Dict[str, Any]:
    """Relais + appel pour un message reçu. Renvoie un résumé (utilisé par les tests et le bouton d'essai)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    cfg = reglages(s)
    chiffres = _chiffres(chiffres)
    # Fiche client relue (le webhook ne lit pas le champ appel_proprietaire)
    if contact and contact.get("id") and "appel_proprietaire" not in contact:
        fiche = await db.directory_contacts.find_one({"id": contact["id"]}, {"_id": 0, "appel_proprietaire": 1}) or {}
        contact = {**contact, **fiche}
    if not test:
        oui, raison = await decision_relais(db, s, chiffres=chiffres, mtype=mtype, texte=texte, contact=contact)
        if not oui:
            return {"relais": False, "appel": False, "raison": raison}
    elif not cfg["numeros"]:
        return {"relais": False, "appel": False, "raison": "numéro du propriétaire non renseigné"}
    maintenant = _maintenant()
    date_msg = lire_date(recu_le) or maintenant
    numero_id, ligne_cle = ligne_appelante(s, cfg)
    if not numero_id:
        return {"relais": False, "appel": False, "raison": "aucun numéro SAWALI configuré"}
    message = texte or f"[{mtype}]"
    qui_ecrit = nom_affiche(contact, profil, chiffres)
    resume: Dict[str, Any] = {"relais": [], "appel": None, "raison": None}

    # 1. Relais écrit à chaque numéro du propriétaire
    relais_par_tel: Dict[str, Dict[str, Any]] = {}
    if cfg["relais_actif"]:
        for proprio in cfg["numeros"]:
            r = await envoyer_relais(db, s, cfg, numero_id, proprio, texte_relais(qui_ecrit, message, date_msg),
                                     [qui_ecrit, extrait(message), formater_date(date_msg)], maintenant)
            resume["relais"].append({"telephone": proprio, **r})
            relais_par_tel[proprio] = r
            if not r["ok"]:
                logger.warning("[appel_proprietaire] relais …%s : %s", proprio[-4:], r.get("erreur"))

    # Lot 67.1 — éléments communs aux lignes de l'historique des appels de Liluvine
    contexte = {"s": s, "cfg": cfg, "maintenant": maintenant, "numero_id": numero_id, "ligne_cle": ligne_cle,
                "client_telephone": chiffres, "client_nom": qui_ecrit, "test": test,
                "client_id": client_id}

    async def relais_seul(raison: str, numeros: Optional[List[str]] = None) -> Dict[str, Any]:
        """Pas d'appel : une ligne « relais seul » par numéro du propriétaire ayant reçu un relais."""
        resume["raison"] = raison
        for proprio in (numeros if numeros is not None else cfg["numeros"]):
            if proprio in relais_par_tel:
                await noter_historique(db, **contexte, destinataire=proprio, relais=relais_par_tel[proprio],
                                       appel=None, raison=raison)
        return resume

    # 2. Appel vocal (contrôles : activé, heures calmes, anti-répétition)
    if not cfg["appel_actif"]:
        return await relais_seul("appel vocal désactivé (relais seul)")
    if not test and en_heures_calmes(cfg, maintenant):
        return await relais_seul("heures calmes : relais seul")
    async with _verrou_client(chiffres):
        if not test and await appel_recent(db, chiffres, cfg["fenetre_min"], maintenant):
            return await relais_seul(f"déjà appelé pour ce client il y a moins de {cfg['fenetre_min']} min")
        verrou = _verrou_global()
        if verrou.locked():
            return await relais_seul("un autre appel au propriétaire est en cours")
        async with verrou:
            alerte = {"alerte_client_telephone": chiffres, "alerte_client_nom": qui_ecrit,
                      "alerte_contact_id": (contact or {}).get("id"), "alerte_message": extrait(message, 300),
                      "alerte_message_le": date_msg.isoformat(), "client_id": client_id or await _perimetre(db)}
            texte_voix = texte_parle(nom_parle(contact, profil, chiffres), date_msg)
            for proprio in cfg["numeros"]:
                perm = await etat_permission(db, s, numero_id, proprio)
                if perm["etat"] != "accordee" or perm.get("peut_appeler") is False:
                    # Pas encore autorisé : demande envoyée (une fois), pas d'appel
                    if perm.get("peut_demander") is not False:
                        await demander_permission(db, s, numero_id, proprio, maintenant)
                    await relais_seul("autorisation d'appel du propriétaire en attente", [proprio])
                    continue
                res = await appeler_et_parler(db, s, cfg, numero_id=numero_id, ligne_cle=ligne_cle, proprio=proprio,
                                              texte_voix=texte_voix, alerte=alerte)
                resume["appel"] = res
                # Lot 67.1 — ligne de l'historique (durées, coût calculé avec le tarif du moment)
                await noter_historique(db, **contexte, destinataire=proprio, relais=relais_par_tel.get(proprio),
                                       appel=res, raison=res.get("raison"))
                if res.get("resultat") == "décroché":
                    break                         # un seul propriétaire suffit
    return resume


async def _perimetre(db) -> Optional[str]:
    """Entreprise principale (premier superviseur, sinon premier administrateur) — rattachement du journal."""
    u = await db.users.find_one({"role": "superviseur"}, {"_id": 0, "id": 1})
    if not u:
        u = await db.users.find_one({"role": "admin", "email": {"$ne": "admin@sawalismartsystems.com"}}, {"_id": 0, "id": 1})
    return (u or {}).get("id")


def planifier(db, **parametres) -> None:
    """Lance traiter_message en arrière-plan (appelé par le webhook) — ne lève jamais d'exception
    et ne ralentit jamais la réponse à Meta."""
    async def _executer():
        try:
            await traiter_message(db, **parametres)
        except Exception:  # noqa: BLE001
            logger.warning("[appel_proprietaire] traitement en échec", exc_info=True)
    try:
        tache = asyncio.get_running_loop().create_task(_executer())
        _taches.add(tache)
        tache.add_done_callback(_taches.discard)
    except Exception:  # noqa: BLE001
        logger.warning("[appel_proprietaire] tâche non lancée", exc_info=True)


# ---------------------------------------------------------------------------
# Diagnostic réseau : l'hébergeur laisse-t-il sortir l'UDP (STUN) ?
# ---------------------------------------------------------------------------

async def diagnostic_reseau() -> Dict[str, Any]:
    """Rassemble les candidats ICE : « srflx » = l'UDP sortant fonctionne (STUN a répondu),
    « relay » = le serveur TURN répond. Aucune adresse n'est renvoyée, seulement les types."""
    ok, raison = moteur_disponible()
    if not ok:
        return {"moteur": False, "raison": raison}
    from aiortc import RTCConfiguration, RTCPeerConnection
    pc = RTCPeerConnection(RTCConfiguration(iceServers=serveurs_ice()))
    try:
        pc.addTransceiver("audio", direction="sendonly")
        await pc.setLocalDescription(await pc.createOffer())
        types = re.findall(r"typ (host|srflx|prflx|relay)", pc.localDescription.sdp)
    finally:
        await pc.close()
    return {"moteur": True, "candidats": {t: types.count(t) for t in sorted(set(types))},
            "udp_sortant": "srflx" in types, "turn": "relay" in types,
            "conclusion": ("UDP sortant fonctionnel : l'appel vocal devrait pouvoir s'établir." if "srflx" in types
                           else "TURN joignable : l'audio passera par le serveur TURN." if "relay" in types
                           else "Aucun candidat public : l'UDP sortant semble bloqué. Configurez un serveur TURN "
                                "(TCP/TLS 443) dans APPEL_TURN_URL / APPEL_TURN_UTILISATEUR / APPEL_TURN_MOT_DE_PASSE.")}


# ---------------------------------------------------------------------------
# Routes d'administration (réglages, état de l'autorisation, essai, diagnostic)
# ---------------------------------------------------------------------------

CHAMPS = {
    "appel_proprio_actif": bool, "appel_proprio_numeros": str, "appel_proprio_ligne": str,
    "appel_proprio_fenetre_min": int, "appel_proprio_calme_actif": bool, "appel_proprio_calme_debut": str,
    "appel_proprio_calme_fin": str, "appel_proprio_relais_actif": bool, "appel_proprio_appel_actif": bool,
    "appel_proprio_modele": str, "appel_proprio_modele_langue": str, "appel_proprio_voix": str,
    "appel_proprio_voix_elevenlabs": str, "appel_proprio_repetitions": int, "appel_proprio_sonnerie_s": int,
    "appel_proprio_exclus": str,
    # Lot 67.1 — tarifs (coût des appels de Liluvine), devise et arrondi de la durée facturée
    "appel_proprio_tarif_appel_minute": float, "appel_proprio_tarif_devise": str,
    "appel_proprio_tarif_arrondi": str, "appel_proprio_tarif_relais_modele": float,
    "appel_proprio_tarif_tts_1000": float,
}


def setup_appel_proprietaire_routes(*, db, api, get_current_user, graph_version: str = "v21.0") -> None:
    """Déclare les routes /admin/appel-proprietaire (administrateurs et superviseurs)."""
    from fastapi import Body, Depends, HTTPException, Query, Response

    global GRAPH_VERSION
    GRAPH_VERSION = graph_version

    def _exiger_admin(user: dict) -> None:
        """Réservé aux administrateurs et superviseurs."""
        if user.get("role") not in ("admin", "superviseur") and user.get("tracked_role") not in ("Administrateur", "Superviseur"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs et superviseurs")

    @api.get("/admin/appel-proprietaire", tags=["Admin — WhatsApp"])
    async def lire(user: dict = Depends(get_current_user)):
        """Réglages, état de l'autorisation d'appel du propriétaire, moteur audio et dernières alertes."""
        _exiger_admin(user)
        from routes.numeros_wa import lignes_configurees
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = reglages(s)
        numero_id, _ = ligne_appelante(s, cfg)
        permissions = [await etat_permission(db, s, numero_id, n) for n in cfg["numeros"]]
        moteur, raison = moteur_disponible()
        derniers = await db.wa_appels.find({"motif": MOTIF}, {"_id": 0, "sdp_reponse": 0, "sdp_offre": 0}) \
            .sort("created_at", -1).limit(10).to_list(10)
        return {
            "reglages": {k: s.get(k) for k in CHAMPS},
            "effectif": {**{k: v for k, v in cfg.items() if k != "exclus"}, "exclus": sorted(cfg["exclus"])},
            "lignes": [{"cle": li["cle"], "libelle": li["libelle"], "telephone": li["telephone"]}
                       for li in lignes_configurees(s)],
            "permissions": permissions,
            "moteur": {"disponible": moteur, "raison": raison, "voix": fournisseurs_voix(s, cfg)},
            "derniers": derniers,
            "tarif": tarif_actuel(s),             # lot 67.1 — tarif en vigueur
        }

    @api.put("/admin/appel-proprietaire", tags=["Admin — WhatsApp"])
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
            elif genre is float:
                # Tarif : nombre décimal positif (virgule acceptée)
                try:
                    maj[cle] = max(0.0, float(str(valeur).replace(",", ".").replace(" ", "") or 0))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Montant attendu pour {cle}")
            elif genre is int:
                try:
                    maj[cle] = int(valeur)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Valeur entière attendue pour {cle}")
            else:
                maj[cle] = str(valeur or "").strip()[:2000]
        for cle in ("appel_proprio_calme_debut", "appel_proprio_calme_fin"):
            if maj.get(cle) and not re.fullmatch(r"\d{1,2}[:hH]\d{2}", maj[cle]):
                raise HTTPException(status_code=422, detail="Heure attendue au format HH:MM")
        if maj.get("appel_proprio_tarif_devise") and maj["appel_proprio_tarif_devise"].upper() not in DEVISES:
            raise HTTPException(status_code=422, detail="Devise inconnue (FCFA ou USD)")
        if maj.get("appel_proprio_tarif_devise"):
            maj["appel_proprio_tarif_devise"] = maj["appel_proprio_tarif_devise"].upper()
        if maj.get("appel_proprio_tarif_arrondi") and maj["appel_proprio_tarif_arrondi"] not in ARRONDIS:
            raise HTTPException(status_code=422, detail="Arrondi inconnu (pulse6, minute ou seconde)")
        if maj.get("appel_proprio_voix") and maj["appel_proprio_voix"] not in ("auto", "openai", "elevenlabs", "google"):
            raise HTTPException(status_code=422, detail="Voix inconnue")
        maj["appel_proprio_maj_par"] = user.get("full_name") or user.get("email")
        await db.settings.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
        return {"ok": True}

    @api.post("/admin/appel-proprietaire/demander-autorisation", tags=["Admin — WhatsApp"])
    async def demander(user: dict = Depends(get_current_user)):
        """Envoie maintenant la demande d'autorisation d'appel au(x) numéro(s) du propriétaire."""
        _exiger_admin(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        cfg = reglages(s)
        if not cfg["numeros"]:
            raise HTTPException(status_code=400, detail="Renseignez d'abord le numéro du propriétaire")
        numero_id, _ = ligne_appelante(s, cfg)
        return {"resultats": [{"telephone": n, **await demander_permission(db, s, numero_id, n, _maintenant(), forcer=True)}
                              for n in cfg["numeros"]]}

    @api.post("/admin/appel-proprietaire/essai", tags=["Admin — WhatsApp"])
    async def essai(user: dict = Depends(get_current_user)):
        """Essai réel : relais + appel du propriétaire avec un message fictif (en arrière-plan)."""
        _exiger_admin(user)
        s = await db.settings.find_one({"_id": "global"}) or {}
        if not reglages(s)["numeros"]:
            raise HTTPException(status_code=400, detail="Renseignez d'abord le numéro du propriétaire")
        planifier(db, chiffres="22600000000", mtype="text", texte="Message d'essai de l'alerte Liluvine",
                  contact={"name": "Client d'essai"}, recu_le=_maintenant().isoformat(), test=True)
        return {"ok": True, "message": "Essai lancé : relais puis appel dans quelques secondes (voir le journal)."}

    # --- Lot 67.1 : historique des appels automatiques de Liluvine (durées, coûts, synthèse) ---

    def _filtre(du, au, client=None, resultat=None) -> Dict[str, Any]:
        """Filtre de l'historique ; dates ou résultat illisibles → erreur 422."""
        try:
            return filtre_historique(du, au, client, resultat)
        except ValueError:
            raise HTTPException(status_code=422, detail="Date (AAAA-MM-JJ) ou résultat invalide")

    @api.get("/admin/appel-proprietaire/historique", tags=["Admin — WhatsApp"])
    async def historique(du: Optional[str] = None, au: Optional[str] = None, client: Optional[str] = None,
                         resultat: Optional[str] = None, page: int = Query(1, ge=1),
                         par_page: int = Query(25, ge=1, le=200), user: dict = Depends(get_current_user)):
        """Historique paginé (du plus récent au plus ancien) + cumuls de tout le filtre."""
        _exiger_admin(user)
        filtre = _filtre(du, au, client, resultat)
        col = db[COLLECTION_HISTORIQUE]
        total = await col.count_documents(filtre)
        lignes = await col.find(filtre, {"_id": 0}).sort("created_at", -1).skip((page - 1) * par_page) \
            .limit(par_page).to_list(par_page)
        tous = await col.find(filtre, {"_id": 0}).to_list(None)
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {"items": lignes, "total": total, "page": page, "par_page": par_page,
                "pages": max(1, -(-total // par_page)), "totaux": totaliser(tous, tarif_actuel(s)["devise"])}

    @api.get("/admin/appel-proprietaire/historique.csv", tags=["Admin — WhatsApp"])
    async def historique_csv(du: Optional[str] = None, au: Optional[str] = None, client: Optional[str] = None,
                             resultat: Optional[str] = None, user: dict = Depends(get_current_user)):
        """Export CSV de l'historique filtré (toutes les lignes, BOM UTF-8 pour Excel)."""
        _exiger_admin(user)
        docs = await db[COLLECTION_HISTORIQUE].find(_filtre(du, au, client, resultat), {"_id": 0}) \
            .sort("created_at", -1).to_list(None)
        nom = f"historique_appels_liluvine_{_maintenant().strftime('%Y%m%d_%H%M')}.csv"
        return Response(content="\ufeff" + csv_historique(docs), media_type="text/csv; charset=utf-8",
                         headers={"Content-Disposition": f'attachment; filename="{nom}"'})

    @api.get("/admin/appel-proprietaire/synthese", tags=["Admin — WhatsApp"])
    async def synthese(periode: str = "jour", du: Optional[str] = None, au: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
        """Cumuls par période (jour, semaine, mois, année — heure de Ouagadougou = UTC)."""
        _exiger_admin(user)
        if periode not in PERIODES:
            raise HTTPException(status_code=422, detail="Période inconnue (jour, semaine, mois, annee)")
        # Sans dates : étendue par défaut selon la période (30 jours, 12 semaines, 12 mois, 5 ans)
        if not du and not au:
            aujourd_hui = _local(_maintenant()).date()
            du = (aujourd_hui - timedelta(days=PERIODES[periode])).isoformat()
            au = aujourd_hui.isoformat()
        docs = await db[COLLECTION_HISTORIQUE].find(_filtre(du, au), {"_id": 0}).to_list(None)
        s = await db.settings.find_one({"_id": "global"}) or {}
        return {"du": du, "au": au, **synthese_par_periode(docs, periode, tarif_actuel(s)["devise"])}

    @api.post("/admin/appel-proprietaire/diagnostic-reseau", tags=["Admin — WhatsApp"])
    async def diagnostic(user: dict = Depends(get_current_user)):
        """L'hébergeur laisse-t-il sortir l'UDP nécessaire à l'audio WebRTC ?"""
        _exiger_admin(user)
        try:
            return await asyncio.wait_for(diagnostic_reseau(), timeout=20)
        except Exception as exc:  # noqa: BLE001
            return {"moteur": False, "raison": f"diagnostic impossible : {str(exc)[:200]}"}
