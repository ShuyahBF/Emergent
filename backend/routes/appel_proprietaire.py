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
        "voix_elevenlabs": (s.get("appel_proprio_voix_elevenlabs") or "").strip(),
        "repetitions": _entier(s.get("appel_proprio_repetitions"), 2, 1, 3),
        "sonnerie_s": _entier(s.get("appel_proprio_sonnerie_s"), 30, 10, 60),
        "exclus": {_chiffres(x)[-8:] for x in re.split(r"[,;\n]+", exclus_brut) if len(_chiffres(x)) >= 8},
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

async def _voix_openai(texte: str, s: Dict[str, Any]) -> bytes:
    """Synthèse OpenAI (voix féminine « nova ») — clé lue dans les réglages ou l'environnement."""
    cle = (s.get("openai_api_key") or "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not cle:
        raise RuntimeError("clé OpenAI absente")
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post("https://api.openai.com/v1/audio/speech",
                            json={"model": "tts-1", "voice": "nova", "input": texte, "response_format": "mp3"},
                            headers={"Authorization": f"Bearer {cle}"})
    if r.status_code >= 300:
        raise RuntimeError(f"OpenAI HTTP {r.status_code}")
    return r.content


async def _voix_elevenlabs(texte: str, cfg: Dict[str, Any]) -> bytes:
    """Synthèse ElevenLabs (voix choisie dans les réglages) — clé ELEVENLABS_API_KEY."""
    cle = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not cle or not cfg.get("voix_elevenlabs"):
        raise RuntimeError("clé ou voix ElevenLabs absente")
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['voix_elevenlabs']}",
                            json={"text": texte, "model_id": "eleven_multilingual_v2"},
                            headers={"xi-api-key": cle, "Accept": "audio/mpeg"})
    if r.status_code >= 300:
        raise RuntimeError(f"ElevenLabs HTTP {r.status_code}")
    return r.content


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
    """Fabrique l'audio (MP3) du message ; renvoie (octets, fournisseur). Lève RuntimeError si tout échoue."""
    erreurs = []
    for f in fournisseurs_voix(s, cfg):
        try:
            if f == "openai":
                return await _voix_openai(texte, s), f
            if f == "elevenlabs":
                return await _voix_elevenlabs(texte, cfg), f
            return await _voix_google(texte), f
        except Exception as exc:  # noqa: BLE001 — on essaie la voix suivante
            erreurs.append(f"{f} : {str(exc)[:80]}")
    raise RuntimeError("synthèse vocale impossible (" + " ; ".join(erreurs) + ")")


def decoder_pcm(audio: bytes) -> bytes:
    """Décode un fichier audio (MP3, WAV…) en PCM 16 bits mono 48 kHz (bibliothèque av / FFmpeg)."""
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


def creer_piste(pcm: bytes, repetitions: int = 2, pause_s: float = 1.2):
    """Piste audio WebRTC : silence tant que lecture() n'est pas appelée, puis le message
    (répété), puis silence ; l'évènement `fini` est posé à la fin de la lecture."""
    import fractions

    import av
    from aiortc import MediaStreamTrack

    octets_trame = ECHANTILLONS_TRAME * 2          # 20 ms de son 16 bits mono
    silence = b"\x00" * octets_trame
    programme = (pcm + b"\x00" * int(FREQUENCE * pause_s) * 2) * max(1, repetitions)

    class PisteLiluvine(MediaStreamTrack):
        """Piste audio envoyée à Meta (une trame de 20 ms toutes les 20 ms, en temps réel)."""
        kind = "audio"

        def __init__(self):
            super().__init__()
            self.fini = asyncio.Event()
            self._position: Optional[int] = None    # None = pas encore en lecture
            self._debut: Optional[float] = None
            self._horodatage = 0

        def lecture(self) -> None:
            """Démarre la lecture du message."""
            self._position = 0

        async def recv(self):
            # Cadence temps réel : une trame toutes les 20 ms
            if self._debut is None:
                self._debut = time.time()
            else:
                self._horodatage += ECHANTILLONS_TRAME
                attente = self._debut + self._horodatage / FREQUENCE - time.time()
                if attente > 0:
                    await asyncio.sleep(attente)
            # Morceau à jouer : message en cours, sinon silence
            morceau = silence
            if self._position is not None and self._position < len(programme):
                morceau = programme[self._position:self._position + octets_trame].ljust(octets_trame, b"\x00")
                self._position += octets_trame
                if self._position >= len(programme):
                    self.fini.set()
            trame = av.AudioFrame(format="s16", layout="mono", samples=ECHANTILLONS_TRAME)
            trame.planes[0].update(morceau)
            trame.pts = self._horodatage
            trame.sample_rate = FREQUENCE
            trame.time_base = fractions.Fraction(1, FREQUENCE)
            return trame

    return PisteLiluvine()


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
    Chaque tentative (même échouée avant Meta) est inscrite au journal des appels."""
    maintenant = _maintenant()
    base = {"direction": "sortant", "motif": MOTIF, "numero_id": numero_id, "ligne_cle": ligne_cle,
            "telephone": proprio, "contact_nom": "Propriétaire (alerte Liluvine)", "auto": True,
            "agent_id": None, "decroche_par_nom": "Liluvine", "texte_parle": texte_voix,
            "created_at": maintenant.isoformat(), "maj": maintenant.isoformat(), **alerte}

    async def echec_avant_meta(raison: str) -> Dict[str, Any]:
        """Échec avant l'appel : ligne « échec » au journal."""
        await db.wa_appels.insert_one({**base, "id": f"alerte-{uuid.uuid4()}", "statut": "echec",
                                       "resultat": "échec", "raison": raison})
        logger.warning("[appel_proprietaire] appel impossible : %s", raison)
        return {"resultat": "échec", "raison": raison}

    ok, raison = moteur_disponible()
    if not ok:
        return await echec_avant_meta(raison)
    # 1. Voix de Liluvine
    try:
        audio, fournisseur = await synthetiser(texte_voix, s, cfg)
        pcm = await asyncio.to_thread(decoder_pcm, audio)
        if len(pcm) < FREQUENCE:                  # moins d'une demi-seconde : audio inutilisable
            raise RuntimeError("audio vide")
    except Exception as exc:  # noqa: BLE001
        return await echec_avant_meta(f"voix : {str(exc)[:200]}")

    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
    pc = RTCPeerConnection(RTCConfiguration(iceServers=serveurs_ice()))
    call_id: Optional[str] = None
    try:
        # 2. Offre SDP avec la piste audio (aiortc rassemble les candidats ICE avant de rendre la main)
        piste = creer_piste(pcm, cfg["repetitions"])
        pc.addTrack(piste)
        offre = await pc.createOffer()
        await pc.setLocalDescription(offre)
        rep = await _graph_post(s, numero_id, "calls", {
            "messaging_product": "whatsapp", "to": proprio, "action": "connect",
            "session": {"sdp_type": "offer", "sdp": pc.localDescription.sdp},
            "biz_opaque_callback_data": "alerte-message"})
        call_id = ((rep.get("donnees") or {}).get("calls") or [{}])[0].get("id") if rep["ok"] else None
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
            await _raccrocher(s, numero_id, call_id)
            await _journal(db, call_id, resultat=resultat, statut="refuse" if resultat == "refusé" else "sans_reponse")
            return {"resultat": resultat, "raison": None, "call_id": call_id}

        # 4. Décroché : réponse SDP appliquée, attente de la connexion audio (ICE + DTLS)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=etat["sdp"], type="answer"))

        async def connecte():
            if pc.connectionState == "failed":
                return "failed"
            return "ok" if pc.connectionState == "connected" else None
        cnx = await _attendre(connecte, 12, 0.2)
        if cnx != "ok":
            raison = ("connexion audio impossible (ICE/DTLS) — l'UDP sortant est peut-être bloqué "
                      "par l'hébergeur : configurez un serveur TURN (APPEL_TURN_URL)")
            await _raccrocher(s, numero_id, call_id)
            await _journal(db, call_id, resultat="échec", raison=raison)
            return {"resultat": "échec", "raison": raison, "call_id": call_id}

        # 5. Liluvine parle (le message est répété), puis raccroche
        await asyncio.sleep(1.0)
        piste.lecture()
        duree_max = len(pcm) / (FREQUENCE * 2) * cfg["repetitions"] + 2 * cfg["repetitions"] + 5
        try:
            await asyncio.wait_for(piste.fini.wait(), timeout=duree_max)
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(0.8)
        await _raccrocher(s, numero_id, call_id)
        await _journal(db, call_id, resultat="décroché", raison=None, message_lu=True)
        return {"resultat": "décroché", "raison": None, "call_id": call_id}
    except Exception as exc:  # noqa: BLE001 — jamais d'exception vers l'appelant
        raison = f"erreur : {str(exc)[:200]}"
        if call_id:
            await _raccrocher(s, numero_id, call_id)
            await _journal(db, call_id, resultat="échec", raison=raison)
            return {"resultat": "échec", "raison": raison, "call_id": call_id}
        return await echec_avant_meta(raison)
    finally:
        try:
            await pc.close()
        except Exception:  # noqa: BLE001
            pass


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
    if cfg["relais_actif"]:
        for proprio in cfg["numeros"]:
            r = await envoyer_relais(db, s, cfg, numero_id, proprio, texte_relais(qui_ecrit, message, date_msg),
                                     [qui_ecrit, extrait(message), formater_date(date_msg)], maintenant)
            resume["relais"].append({"telephone": proprio, **r})
            if not r["ok"]:
                logger.warning("[appel_proprietaire] relais …%s : %s", proprio[-4:], r.get("erreur"))

    # 2. Appel vocal (contrôles : activé, heures calmes, anti-répétition)
    if not cfg["appel_actif"]:
        resume["raison"] = "appel vocal désactivé (relais seul)"
        return resume
    if not test and en_heures_calmes(cfg, maintenant):
        resume["raison"] = "heures calmes : relais seul"
        return resume
    async with _verrou_client(chiffres):
        if not test and await appel_recent(db, chiffres, cfg["fenetre_min"], maintenant):
            resume["raison"] = f"déjà appelé pour ce client il y a moins de {cfg['fenetre_min']} min"
            return resume
        verrou = _verrou_global()
        if verrou.locked():
            resume["raison"] = "un autre appel au propriétaire est en cours"
            return resume
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
                    resume["raison"] = "autorisation d'appel du propriétaire en attente"
                    continue
                res = await appeler_et_parler(db, s, cfg, numero_id=numero_id, ligne_cle=ligne_cle, proprio=proprio,
                                              texte_voix=texte_voix, alerte=alerte)
                resume["appel"] = res
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
}


def setup_appel_proprietaire_routes(*, db, api, get_current_user, graph_version: str = "v21.0") -> None:
    """Déclare les routes /admin/appel-proprietaire (administrateurs et superviseurs)."""
    from fastapi import Body, Depends, HTTPException

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

    @api.post("/admin/appel-proprietaire/diagnostic-reseau", tags=["Admin — WhatsApp"])
    async def diagnostic(user: dict = Depends(get_current_user)):
        """L'hébergeur laisse-t-il sortir l'UDP nécessaire à l'audio WebRTC ?"""
        _exiger_admin(user)
        try:
            return await asyncio.wait_for(diagnostic_reseau(), timeout=20)
        except Exception as exc:  # noqa: BLE001
            return {"moteur": False, "raison": f"diagnostic impossible : {str(exc)[:200]}"}
