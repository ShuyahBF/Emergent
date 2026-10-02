"""Lot 52 — Choix du service d'envoi des e-mails de la plateforme (super-admin SAWALI).

Quatre services au choix : Resend, ZeptoMail (Zoho), Brevo, SMTP (plus « Désactivé »).
Resend, ZeptoMail et Brevo passent par HTTPS (port 443) : ils fonctionnent aussi sur les services
Render gratuits, qui bloquent les ports SMTP 25, 465 et 587 (le port 25 est bloqué partout).

Stockage
  - Collection `email_fournisseur`, document unique `_id: "plateforme"` :
      fournisseur (resend | zeptomail | brevo | smtp | desactive), actif, expediteur, nom_affiche,
      zeptomail_hote, cle_<fournisseur>_chiffree, smtp_mot_de_passe_chiffre, modifie_le, modifie_par.
  - Les champs SMTP non secrets restent ceux d'avant dans les réglages globaux (`settings` _id
    « global » : smtp_host, smtp_port, smtp_user, smtp_from_email, smtp_from_name, smtp_use_tls).
  - Clés et mot de passe SMTP CHIFFRÉS (Fernet dérivé de JWT_SECRET, même principe que Story Studio).
    Jamais renvoyés au navigateur : seulement `a_cle: true/false`.
  - Journal des modifications : `email_fournisseur_journal` (qui, quand, quel fournisseur, quels
    champs ; jamais une clé). Journal des envois : `email_envois_journal` (ENVOYE / ECHEC /
    NON_CONFIGURE), effacé au bout de 90 jours.

Compatibilité
  - Aucun document ou document sans `fournisseur` : les anciens réglages SMTP restent valables
    (fournisseur « smtp ») ; l'ancien mot de passe en clair est chiffré au démarrage.
  - Rien de réglé dans l'écran : repli sur les variables d'environnement, par ordre de priorité
    RESEND_API_KEY + RESEND_EXPEDITEUR, puis PLATEFORME_SMTP_* / SMTP_*, puis (en option)
    BREVO_API_KEY, puis ZEPTOMAIL_API_KEY (+ ZEPTOMAIL_HOTE), avec EMAIL_EXPEDITEUR.

Pas de réglages d'envoi par locataire dans SAWALI : seul le niveau plateforme existe.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken

from db import db

logger = logging.getLogger("sawali.email_fournisseurs")

# ---------------------------------------------------------------------------
# Constantes : fournisseurs, hôtes ZeptoMail, collections, aides affichées
# ---------------------------------------------------------------------------
RESEND, ZEPTOMAIL, BREVO, SMTP, DESACTIVE = "resend", "zeptomail", "brevo", "smtp", "desactive"
FOURNISSEURS = (RESEND, ZEPTOMAIL, BREVO, SMTP)
FOURNISSEURS_HTTP = (RESEND, ZEPTOMAIL, BREVO)
LIBELLES = {RESEND: "Resend", ZEPTOMAIL: "ZeptoMail", BREVO: "Brevo", SMTP: "SMTP", DESACTIVE: "Désactivé"}
ZEPTOMAIL_HOTES = ("api.zeptomail.com", "api.zeptomail.eu", "api.zeptomail.in")
ZEPTOMAIL_HOTE_DEFAUT = ZEPTOMAIL_HOTES[0]
URL_RESEND = "https://api.resend.com/emails"
URL_BREVO = "https://api.brevo.com/v3/smtp/email"
DELAI_HTTP_S = 20.0
LONGUEUR_ERREUR = 250
NOM_MAX = 60

REGLAGES = "email_fournisseur"
ID_PLATEFORME = "plateforme"
JOURNAL_REGLAGES = "email_fournisseur_journal"
JOURNAL_ENVOIS = "email_envois_journal"
CONSERVATION_ENVOIS_JOURS = 90

ENVOYE, ECHEC, NON_CONFIGURE = "ENVOYE", "ECHEC", "NON_CONFIGURE"

AVERTISSEMENT_SMTP = ("Bloqué sur les services Render gratuits (ports 25, 465, 587). "
                      "Fonctionne seulement avec une offre payante (Starter).")
AIDES = {
    RESEND: {"lien": "https://resend.com", "texte": "resend.com — gratuit jusqu'à 3 000 e-mails/mois (100/jour)."},
    ZEPTOMAIL: {"lien": "https://www.zoho.com/zeptomail/",
                "texte": "zoho.com/zeptomail — 10 000 premiers offerts, puis 2,50 $ les 10 000 ; "
                         "boîtes mail possibles avec Zoho Mail."},
    BREVO: {"lien": "https://www.brevo.com", "texte": "brevo.com — gratuit jusqu'à 300/jour."},
    SMTP: {"lien": "", "texte": AVERTISSEMENT_SMTP},
}


class ErreurEnvoi(Exception):
    """Échec d'envoi : « <Fournisseur> <code HTTP> : <message du fournisseur> » (jamais la clé)."""


# ---------------------------------------------------------------------------
# Chiffrement des clés et du mot de passe SMTP (Fernet dérivé de JWT_SECRET)
# ---------------------------------------------------------------------------
def _fernet() -> Fernet:
    """Même principe que routes/story_studio._get_fernet : clé stable dérivée de JWT_SECRET,
    avec une étiquette propre à cet usage (aucune variable d'environnement de plus)."""
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    empreinte = hashlib.sha256(f"sawali-email-fournisseur::{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(empreinte))


def chiffrer(clair: Optional[str]) -> Optional[str]:
    if not clair:
        return None
    return _fernet().encrypt(clair.encode()).decode()


def dechiffrer(chiffre: Optional[str]) -> Optional[str]:
    """None si absent ou illisible (JWT_SECRET changé) : le service est alors « non configuré »."""
    if not chiffre:
        return None
    try:
        return _fernet().decrypt(chiffre.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        logger.warning("[email] clé chiffrée illisible (JWT_SECRET modifié ?) : à saisir de nouveau")
        return None


# ---------------------------------------------------------------------------
# Petits utilitaires : nom affiché, adresse, texte brut, variables d'environnement
# ---------------------------------------------------------------------------
_RE_ADRESSE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def nettoyer_nom(nom: Optional[str]) -> str:
    """Nom affiché sans < > ni retour à la ligne, 60 caractères au plus."""
    propre = re.sub(r"[<>\r\n\t]", " ", nom or "")
    propre = re.sub(r"\s{2,}", " ", propre).strip()
    return propre[:NOM_MAX].strip()


def adresse_valide(adresse: Optional[str]) -> bool:
    return bool(adresse) and bool(_RE_ADRESSE.match(adresse.strip()))


def texte_depuis_html(html: str) -> str:
    """Version texte d'un corps HTML (le corps texte est toujours envoyé)."""
    sans_style = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", html or "")
    avec_retours = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h[1-6]>|</li>|</tr>", "\n", sans_style)
    brut = re.sub(r"<[^>]+>", " ", avec_retours)
    brut = brut.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lignes = [re.sub(r"[ \t]{2,}", " ", ligne).strip() for ligne in brut.splitlines()]
    return "\n".join(ligne for ligne in lignes if ligne)


def _env(*noms: str) -> str:
    """Première variable d'environnement renseignée parmi `noms` (chaîne vide sinon)."""
    for nom in noms:
        val = (os.environ.get(nom) or "").strip()
        if val:
            return val
    return ""


def _vrai(val: Any, defaut: bool = True) -> bool:
    if val is None or val == "":
        return defaut
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "vrai", "oui", "yes", "on")


def _cle_env(fournisseur: str) -> str:
    return {RESEND: _env("RESEND_API_KEY"), BREVO: _env("BREVO_API_KEY"),
            ZEPTOMAIL: _env("ZEPTOMAIL_API_KEY")}.get(fournisseur, "")


def _expediteur_env(fournisseur: str) -> str:
    if fournisseur == RESEND:
        return _env("RESEND_EXPEDITEUR", "EMAIL_EXPEDITEUR")
    return _env("EMAIL_EXPEDITEUR")


def _separer_expediteur(valeur: str) -> tuple[str, str]:
    """« Nom <adresse> » ou « adresse » (variables d'environnement) -> (nom, adresse)."""
    m = re.match(r"^\s*(.*?)\s*<([^<>]+)>\s*$", valeur or "")
    if m:
        return nettoyer_nom(m.group(1).strip('"')), m.group(2).strip()
    return "", (valeur or "").strip()


# ---------------------------------------------------------------------------
# Construction des requêtes HTTP (fonction pure, vérifiée par les tests)
# ---------------------------------------------------------------------------
def _pieces_b64(pieces: Optional[List[dict]]) -> List[dict]:
    """Pièces jointes {filename, content (octets), mime_type} -> contenu en base 64."""
    sortie = []
    for p in pieces or []:
        if not p or p.get("content") is None:
            continue
        contenu = p["content"]
        if isinstance(contenu, str):
            contenu = contenu.encode()
        sortie.append({"nom": p.get("filename") or "piece-jointe.bin",
                       "type": p.get("mime_type") or "application/octet-stream",
                       "b64": base64.b64encode(contenu).decode()})
    return sortie


def entete_zeptomail(cle: str) -> str:
    """Clé ZeptoMail : préfixe « Zoho-enczapikey » ajouté une seule fois."""
    cle = (cle or "").strip()
    if cle.lower().startswith("zoho-enczapikey"):
        return "Zoho-enczapikey " + cle[len("zoho-enczapikey"):].strip()
    return f"Zoho-enczapikey {cle}"


def construire_requete(cfg: Dict[str, Any], destinataire: str, sujet: str, texte: str,
                       html: str = "", reply_to: Optional[str] = None,
                       pieces: Optional[List[dict]] = None) -> tuple[str, Dict[str, str], Dict[str, Any]]:
    """(url, en-têtes, JSON) de l'appel au fournisseur `cfg["fournisseur"]` (Resend, Brevo, ZeptoMail)."""
    four = cfg["fournisseur"]
    adresse = cfg["expediteur"]
    nom = nettoyer_nom(cfg.get("nom"))
    cle = cfg.get("cle") or ""
    jointes = _pieces_b64(pieces)
    if four == RESEND:
        corps: Dict[str, Any] = {"from": f"{nom} <{adresse}>" if nom else adresse, "to": [destinataire],
                                 "subject": sujet, "text": texte}
        if html:
            corps["html"] = html
        if reply_to:
            corps["reply_to"] = reply_to
        if jointes:
            corps["attachments"] = [{"filename": j["nom"], "content": j["b64"]} for j in jointes]
        return URL_RESEND, {"Authorization": f"Bearer {cle}"}, corps
    if four == BREVO:
        corps = {"sender": {"name": nom, "email": adresse}, "to": [{"email": destinataire}],
                 "subject": sujet, "textContent": texte}
        if html:
            corps["htmlContent"] = html
        if reply_to:
            corps["replyTo"] = {"email": reply_to}
        if jointes:
            corps["attachment"] = [{"name": j["nom"], "content": j["b64"]} for j in jointes]
        return URL_BREVO, {"api-key": cle, "accept": "application/json"}, corps
    if four == ZEPTOMAIL:
        hote = cfg.get("zeptomail_hote") if cfg.get("zeptomail_hote") in ZEPTOMAIL_HOTES else ZEPTOMAIL_HOTE_DEFAUT
        corps = {"from": {"address": adresse, "name": nom}, "to": [{"email_address": {"address": destinataire}}],
                 "subject": sujet, "textbody": texte}
        if html:
            corps["htmlbody"] = html
        if reply_to:
            corps["reply_to"] = [{"address": reply_to}]
        if jointes:
            corps["attachments"] = [{"name": j["nom"], "content": j["b64"], "mime_type": j["type"]} for j in jointes]
        return f"https://{hote}/v1.1/email", {"Authorization": entete_zeptomail(cle)}, corps
    raise ValueError(f"Fournisseur HTTP inconnu : {four}")


def message_erreur(fournisseur: str, statut: int, reponse: Any, texte_brut: str = "", cle: str = "") -> str:
    """« <Fournisseur> <code HTTP> : <message du fournisseur> », 250 caractères au plus, sans la clé."""
    msg = ""
    if isinstance(reponse, dict):
        if fournisseur == ZEPTOMAIL and isinstance(reponse.get("error"), dict):
            err = reponse["error"]
            msg = str(err.get("message") or "")
            details = err.get("details") or []
            if details and isinstance(details[0], dict) and details[0].get("message"):
                msg = f"{msg} ({details[0]['message']})" if msg else str(details[0]["message"])
        else:
            msg = str(reponse.get("message") or reponse.get("error") or "")
            if fournisseur == BREVO and reponse.get("code") and not msg:
                msg = str(reponse["code"])
    if not msg:
        msg = (texte_brut or "").strip() or "réponse inattendue"
    complet = f"{LIBELLES.get(fournisseur, fournisseur)} {statut} : {msg}"
    for secret in {cle, cle.strip(), entete_zeptomail(cle) if cle else ""}:
        if secret and len(secret) >= 4:
            complet = complet.replace(secret, "***")
    return complet[:LONGUEUR_ERREUR]


async def envoyer_http(cfg: Dict[str, Any], destinataire: str, sujet: str, texte: str, html: str = "",
                       reply_to: Optional[str] = None, pieces: Optional[List[dict]] = None) -> Dict[str, Any]:
    """Envoi par Resend, Brevo ou ZeptoMail (httpx, délai 20 s). Lève ErreurEnvoi en cas d'échec."""
    four = cfg["fournisseur"]
    url, entetes, corps = construire_requete(cfg, destinataire, sujet, texte, html, reply_to, pieces)
    try:
        async with httpx.AsyncClient(timeout=DELAI_HTTP_S) as http:
            rep = await http.post(url, json=corps, headers=entetes)
    except httpx.TimeoutException as exc:
        raise ErreurEnvoi(f"{LIBELLES[four]} : délai dépassé ({int(DELAI_HTTP_S)} s)") from exc
    except httpx.HTTPError as exc:
        raise ErreurEnvoi(f"{LIBELLES[four]} : connexion impossible ({type(exc).__name__})"[:LONGUEUR_ERREUR]) from exc
    try:
        donnees = rep.json()
    except Exception:  # noqa: BLE001 — réponse non JSON
        donnees = None
    if 200 <= rep.status_code < 300:
        ident = None
        if isinstance(donnees, dict):
            ident = donnees.get("id") or donnees.get("messageId") or donnees.get("request_id")
        return {"ok": True, "fournisseur": four, "statut_http": rep.status_code, "id": ident}
    texte_brut = ""
    if donnees is None:
        try:
            texte_brut = rep.text[:LONGUEUR_ERREUR]
        except Exception:  # noqa: BLE001
            texte_brut = ""
    raise ErreurEnvoi(message_erreur(four, rep.status_code, donnees, texte_brut, cfg.get("cle") or ""))


# ---------------------------------------------------------------------------
# Lecture des réglages et configuration effective (écran, anciens réglages, environnement)
# ---------------------------------------------------------------------------
async def _docs() -> tuple[dict, dict]:
    doc = await db[REGLAGES].find_one({"_id": ID_PLATEFORME}) or {}
    glob = await db.settings.find_one({"_id": "global"}) or {}
    return doc, glob


def _smtp_ecran(doc: dict, glob: dict) -> Dict[str, Any]:
    """Réglages SMTP enregistrés (champs existants + mot de passe chiffré, ou ancien mot de passe en clair)."""
    mot_de_passe = dechiffrer(doc.get("smtp_mot_de_passe_chiffre")) or (glob.get("smtp_password") or None)
    expediteur = (doc.get("expediteur") or glob.get("smtp_from_email") or glob.get("smtp_user") or "").strip()
    try:
        port = int(glob.get("smtp_port") or 587)
    except (TypeError, ValueError):
        port = 587
    return {"fournisseur": SMTP, "host": (glob.get("smtp_host") or "").strip() or None, "port": port,
            "user": (glob.get("smtp_user") or "").strip() or None, "password": mot_de_passe,
            "from_email": expediteur, "from_name": nettoyer_nom(doc.get("nom_affiche") or glob.get("smtp_from_name")),
            "use_tls": glob.get("smtp_use_tls", True) is not False}


def _smtp_env() -> Dict[str, Any]:
    """Repli SMTP sur PLATEFORME_SMTP_* puis SMTP_*."""
    def lire(*suffixes: str) -> str:
        return _env(*[f"PLATEFORME_SMTP_{s}" for s in suffixes], *[f"SMTP_{s}" for s in suffixes])
    utilisateur = lire("USER", "UTILISATEUR", "USERNAME")
    nom, adresse = _separer_expediteur(lire("FROM_EMAIL", "FROM", "EXPEDITEUR") or _env("EMAIL_EXPEDITEUR"))
    try:
        port = int(lire("PORT") or 587)
    except ValueError:
        port = 587
    return {"fournisseur": SMTP, "host": lire("HOST", "HOTE") or None, "port": port, "user": utilisateur or None,
            "password": lire("PASSWORD", "MOT_DE_PASSE", "PASS") or None, "from_email": adresse or utilisateur,
            "from_name": nettoyer_nom(lire("FROM_NAME", "NOM") or nom),
            "use_tls": _vrai(lire("USE_TLS", "STARTTLS"), True)}


def smtp_complet(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("host") and cfg.get("user") and cfg.get("password") and adresse_valide(cfg.get("from_email")))


def _http_env(fournisseur: str) -> Optional[Dict[str, Any]]:
    """Repli Resend / Brevo / ZeptoMail sur les variables d'environnement (clé + expéditeur)."""
    cle = _cle_env(fournisseur)
    nom, adresse = _separer_expediteur(_expediteur_env(fournisseur))
    if not cle or not adresse_valide(adresse):
        return None
    hote = _env("ZEPTOMAIL_HOTE")
    return {"fournisseur": fournisseur, "cle": cle, "expediteur": adresse, "nom": nom or nettoyer_nom(_env("EMAIL_NOM")),
            "zeptomail_hote": hote if hote in ZEPTOMAIL_HOTES else ZEPTOMAIL_HOTE_DEFAUT}


def _repli_env() -> Optional[Dict[str, Any]]:
    """Ordre de priorité : Resend, SMTP, puis Brevo et ZeptoMail (en option)."""
    resend = _http_env(RESEND)
    if resend:
        return {**resend, "source": "env:RESEND_API_KEY"}
    smtp = _smtp_env()
    if smtp_complet(smtp):
        return {**smtp, "source": "env:SMTP"}
    for four, source in ((BREVO, "env:BREVO_API_KEY"), (ZEPTOMAIL, "env:ZEPTOMAIL_API_KEY")):
        cfg = _http_env(four)
        if cfg:
            return {**cfg, "source": source}
    return None


def configuration_depuis(doc: dict, glob: dict) -> Dict[str, Any]:
    """Configuration effective. Renvoie {"fournisseur": None, "raison": ...} si rien n'est utilisable.
    La clé déchiffrée reste côté serveur (jamais renvoyée par l'API)."""
    four = doc.get("fournisseur")
    if four == DESACTIVE or (four in FOURNISSEURS and doc.get("actif") is False):
        return {"fournisseur": None, "raison": "Envoi des e-mails désactivé dans les Paramètres", "source": "ecran"}
    if four in FOURNISSEURS_HTTP:
        cle = dechiffrer(doc.get(f"cle_{four}_chiffree")) or _cle_env(four)
        nom_env, adr_env = _separer_expediteur(_expediteur_env(four))
        expediteur = (doc.get("expediteur") or adr_env or "").strip()
        if not cle:
            return {"fournisseur": None, "raison": f"Clé API {LIBELLES[four]} absente", "source": "ecran"}
        if not adresse_valide(expediteur):
            return {"fournisseur": None, "raison": "Adresse d'expéditeur absente ou invalide", "source": "ecran"}
        hote = doc.get("zeptomail_hote") or _env("ZEPTOMAIL_HOTE")
        return {"fournisseur": four, "cle": cle, "expediteur": expediteur,
                "nom": nettoyer_nom(doc.get("nom_affiche") or nom_env),
                "zeptomail_hote": hote if hote in ZEPTOMAIL_HOTES else ZEPTOMAIL_HOTE_DEFAUT, "source": "ecran"}
    # SMTP choisi, ou ancien document sans `fournisseur` (vaut « smtp ») : réglages SMTP enregistrés
    smtp = _smtp_ecran(doc, glob)
    if smtp_complet(smtp):
        return {**smtp, "source": "ecran" if four == SMTP else "ancien_smtp"}
    if four == SMTP:
        repli = _smtp_env()
        if smtp_complet(repli):
            return {**repli, "source": "env:SMTP"}
        return {"fournisseur": None, "raison": "Réglages SMTP incomplets", "source": "ecran"}
    # Rien de réglé dans l'écran : variables d'environnement
    return _repli_env() or {"fournisseur": None, "raison": "Aucun service d'envoi configuré", "source": None}


async def configuration_effective() -> Dict[str, Any]:
    doc, glob = await _docs()
    return configuration_depuis(doc, glob)


# ---------------------------------------------------------------------------
# Journaux : modifications des réglages et envois (jamais bloquants, jamais de clé)
# ---------------------------------------------------------------------------
def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


async def journaliser_envoi(statut: str, fournisseur: Optional[str], destinataire: str, sujet: str,
                            erreur: Optional[str] = None, origine: str = "send_email") -> None:
    """Trace d'un envoi (ENVOYE / ECHEC / NON_CONFIGURE). Ne bloque jamais l'action en cours."""
    try:
        await asyncio.wait_for(db[JOURNAL_ENVOIS].insert_one({
            "le": _maintenant().isoformat(), "le_dt": _maintenant(), "statut": statut,
            "fournisseur": fournisseur, "destinataire": (destinataire or "")[:254],
            "sujet": (sujet or "")[:150], "erreur": (erreur or None) and erreur[:LONGUEUR_ERREUR],
            "origine": origine,
        }), timeout=3)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[email] journal des envois non écrit : %s", exc)


async def _journaliser_reglages(par: dict, fournisseur: str, champs: List[str], action: str = "REGLAGES") -> None:
    await db[JOURNAL_REGLAGES].insert_one({
        "le": _maintenant().isoformat(), "action": action, "fournisseur": fournisseur,
        "champs": sorted(set(champs)),
        "par": {"id": par.get("id"), "email": (par.get("email") or "").lower()},
    })


async def assurer_index() -> None:
    """Index du journal des envois (effacement automatique au bout de 90 jours) et du journal des réglages."""
    await db[JOURNAL_ENVOIS].create_index("le_dt", expireAfterSeconds=CONSERVATION_ENVOIS_JOURS * 86400)
    await db[JOURNAL_REGLAGES].create_index([("le", -1)])


async def migrer_ancien_mot_de_passe_smtp() -> bool:
    """Ancien mot de passe SMTP en clair dans les réglages globaux -> chiffré dans `email_fournisseur`.
    Le fournisseur n'est pas fixé : l'ancien document reste « smtp » par défaut."""
    glob = await db.settings.find_one({"_id": "global"}, {"smtp_password": 1}) or {}
    clair = glob.get("smtp_password")
    if not clair or clair == "********":
        return False
    await db[REGLAGES].update_one({"_id": ID_PLATEFORME}, {"$set": {"smtp_mot_de_passe_chiffre": chiffrer(clair)}},
                                  upsert=True)
    await db.settings.update_one({"_id": "global"}, {"$unset": {"smtp_password": ""}})
    logger.info("[email] ancien mot de passe SMTP chiffré (lot 52)")
    return True


# ---------------------------------------------------------------------------
# Vue de l'écran (sans aucun secret) et enregistrement par le super-admin
# ---------------------------------------------------------------------------
def _env_presentes() -> Dict[str, bool]:
    """Variables de repli présentes (noms seulement, jamais les valeurs)."""
    noms = ("RESEND_API_KEY", "RESEND_EXPEDITEUR", "BREVO_API_KEY", "ZEPTOMAIL_API_KEY", "ZEPTOMAIL_HOTE",
            "EMAIL_EXPEDITEUR", "PLATEFORME_SMTP_HOST", "SMTP_HOST")
    return {n: bool(_env(n)) for n in noms}


async def vue_publique() -> Dict[str, Any]:
    doc, glob = await _docs()
    choisi = doc.get("fournisseur") or SMTP   # ancien document sans `fournisseur` : « smtp »
    smtp = _smtp_ecran(doc, glob)
    eff = configuration_depuis(doc, glob)
    cles = {f: {"a_cle": bool(doc.get(f"cle_{f}_chiffree"))} for f in FOURNISSEURS_HTTP}
    return {
        "fournisseur": choisi,
        "actif": doc.get("actif", True) is not False and choisi != DESACTIVE,
        "expediteur": doc.get("expediteur") or (glob.get("smtp_from_email") or ""),
        "nom_affiche": doc.get("nom_affiche") or (glob.get("smtp_from_name") or ""),
        "zeptomail_hote": doc.get("zeptomail_hote") or ZEPTOMAIL_HOTE_DEFAUT,
        "cles": cles,
        "a_cle": cles[choisi]["a_cle"] if choisi in cles else bool(smtp.get("password")) if choisi == SMTP else False,
        "smtp": {"hote": glob.get("smtp_host") or "", "port": smtp["port"], "utilisateur": glob.get("smtp_user") or "",
                 "starttls": smtp["use_tls"], "a_mot_de_passe": bool(smtp.get("password"))},
        "effectif": {"fournisseur": eff.get("fournisseur"), "source": eff.get("source"),
                     "raison": eff.get("raison"), "expediteur": eff.get("expediteur") or eff.get("from_email")},
        "env_repli": _env_presentes(),
        "choix": [{"valeur": f, "libelle": LIBELLES[f]} for f in (*FOURNISSEURS, DESACTIVE)],
        "zeptomail_hotes": list(ZEPTOMAIL_HOTES),
        "aides": AIDES,
        "avertissement_smtp": AVERTISSEMENT_SMTP,
        "modifie_le": doc.get("modifie_le"), "modifie_par": doc.get("modifie_par"),
    }


class ReglagesInvalides(ValueError):
    """Valeur refusée (message affiché tel quel)."""


async def enregistrer(donnees: Dict[str, Any], par: dict) -> Dict[str, Any]:
    """Enregistre les réglages. Champ secret vide = valeur conservée. Journalise qui, quand, quel
    fournisseur et les noms des champs modifiés (jamais une clé)."""
    doc, glob = await _docs()
    maj: Dict[str, Any] = {}
    maj_glob: Dict[str, Any] = {}
    champs: List[str] = []

    four = donnees.get("fournisseur")
    if four is not None:
        four = str(four).strip().lower()
        if four not in (*FOURNISSEURS, DESACTIVE):
            raise ReglagesInvalides("Service d'envoi inconnu (Resend, ZeptoMail, Brevo, SMTP ou Désactivé)")
        maj["fournisseur"] = four
    four_final = maj.get("fournisseur") or doc.get("fournisseur") or SMTP

    if donnees.get("actif") is not None:
        maj["actif"] = bool(donnees["actif"])
    if donnees.get("expediteur") is not None:
        adr = str(donnees["expediteur"]).strip()
        if adr and not adresse_valide(adr):
            raise ReglagesInvalides("Adresse d'expéditeur invalide")
        maj["expediteur"] = adr
    if donnees.get("nom_affiche") is not None:
        maj["nom_affiche"] = nettoyer_nom(donnees["nom_affiche"])
    if donnees.get("zeptomail_hote") is not None:
        hote = str(donnees["zeptomail_hote"]).strip().lower()
        if hote not in ZEPTOMAIL_HOTES:
            raise ReglagesInvalides("Région ZeptoMail inconnue (.com, .eu ou .in)")
        maj["zeptomail_hote"] = hote

    # Clé API : appliquée au fournisseur choisi ; vide = conservée
    cle = (donnees.get("cle") or "").strip()
    if cle and cle != "********":
        if four_final not in FOURNISSEURS_HTTP:
            raise ReglagesInvalides("Une clé API ne s'applique qu'à Resend, ZeptoMail ou Brevo")
        maj[f"cle_{four_final}_chiffree"] = chiffrer(cle)

    # SMTP : champs existants des réglages globaux, mot de passe chiffré (vide = conservé)
    smtp = donnees.get("smtp") or {}
    if smtp.get("hote") is not None:
        maj_glob["smtp_host"] = str(smtp["hote"]).strip()
    if smtp.get("port") not in (None, ""):
        try:
            port = int(smtp["port"])
        except (TypeError, ValueError) as exc:
            raise ReglagesInvalides("Port SMTP invalide") from exc
        if not 1 <= port <= 65535:
            raise ReglagesInvalides("Port SMTP invalide")
        maj_glob["smtp_port"] = port
    if smtp.get("utilisateur") is not None:
        maj_glob["smtp_user"] = str(smtp["utilisateur"]).strip()
    if smtp.get("starttls") is not None:
        maj_glob["smtp_use_tls"] = bool(smtp["starttls"])
    mdp = (smtp.get("mot_de_passe") or "").strip()
    if mdp and mdp != "********":
        maj["smtp_mot_de_passe_chiffre"] = chiffrer(mdp)
    # Expéditeur et nom communs recopiés dans les champs SMTP existants (compatibilité)
    if four_final == SMTP:
        if "expediteur" in maj:
            maj_glob["smtp_from_email"] = maj["expediteur"]
        if "nom_affiche" in maj:
            maj_glob["smtp_from_name"] = maj["nom_affiche"]

    # Champs réellement modifiés (noms seulement)
    for k, v in maj.items():
        if k.endswith("_chiffre") or k.endswith("_chiffree"):
            champs.append(k.replace("_chiffree", "").replace("_chiffre", ""))
        elif doc.get(k) != v:
            champs.append(k)
    for k, v in maj_glob.items():
        if glob.get(k) != v:
            champs.append(k)

    if maj or maj_glob:
        horodatage = _maintenant().isoformat()
        maj.update({"modifie_le": horodatage, "modifie_par": (par.get("email") or "").lower()})
        await db[REGLAGES].update_one({"_id": ID_PLATEFORME}, {"$set": maj}, upsert=True)
        operation: Dict[str, Any] = {}
        if maj_glob:
            operation["$set"] = {**maj_glob, "updated_at": horodatage}
        if "smtp_mot_de_passe_chiffre" in maj:
            operation["$unset"] = {"smtp_password": ""}   # plus jamais en clair
        if operation:
            await db.settings.update_one({"_id": "global"}, operation, upsert=True)
    if champs:
        await _journaliser_reglages(par, four_final, champs)
    return await vue_publique()


async def filtrer_maj_parametres_generiques(update: Dict[str, Any], user: dict, est_super_admin) -> Dict[str, Any]:
    """PUT /admin/settings (écran général) : les champs smtp_* sont réservés au super-admin ;
    un mot de passe SMTP reçu là est chiffré (jamais enregistré en clair)."""
    champs_smtp = [k for k in update if k.startswith("smtp_")]
    if not champs_smtp:
        return update
    if not est_super_admin(user):
        for k in champs_smtp:
            update.pop(k, None)
        return update
    mdp = update.pop("smtp_password", None)
    if mdp and mdp != "********":
        await db[REGLAGES].update_one({"_id": ID_PLATEFORME}, {"$set": {
            "smtp_mot_de_passe_chiffre": chiffrer(mdp), "modifie_le": _maintenant().isoformat(),
            "modifie_par": (user.get("email") or "").lower()}}, upsert=True)
        await db.settings.update_one({"_id": "global"}, {"$unset": {"smtp_password": ""}})
    champs = [k for k in champs_smtp if k != "smtp_password" or mdp]
    if champs:
        doc = await db[REGLAGES].find_one({"_id": ID_PLATEFORME}, {"fournisseur": 1}) or {}
        await _journaliser_reglages(user, doc.get("fournisseur") or SMTP,
                                    [("smtp_mot_de_passe" if k == "smtp_password" else k) for k in champs])
    return update


async def journal(limite: int = 50) -> Dict[str, Any]:
    limite = min(max(int(limite or 50), 1), 500)
    modifs = await db[JOURNAL_REGLAGES].find({}, {"_id": 0}).sort("le", -1).to_list(limite)
    envois = await db[JOURNAL_ENVOIS].find({}, {"_id": 0, "le_dt": 0}).sort("le", -1).to_list(limite)
    return {"modifications": modifs, "envois": envois}


__all__ = [
    "RESEND", "ZEPTOMAIL", "BREVO", "SMTP", "DESACTIVE", "FOURNISSEURS", "LIBELLES", "ErreurEnvoi",
    "ReglagesInvalides", "construire_requete", "envoyer_http", "configuration_effective", "configuration_depuis",
    "vue_publique", "enregistrer", "journal", "journaliser_envoi", "assurer_index", "chiffrer", "dechiffrer",
    "migrer_ancien_mot_de_passe_smtp", "filtrer_maj_parametres_generiques", "nettoyer_nom", "texte_depuis_html",
]
