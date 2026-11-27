# appareils_android.py — Lot 468 : REGISTRE DES APPAREILS ANDROID de « Loois mobile » (logique pure + stockage, sans accès réseau).
#
# Demande du propriétaire (26/11/2026) : un APK « Loois » publié sur ShuyahStore ; chaque téléphone / tablette est référencé dans SAWALI avec : l'identifiant de l'appareil,
# le nom de l'utilisateur, son adresse IP à la connexion, l'ÉTAT de son accès (Interdit ou Autorisé), la zone de lancement et le nom de la base de données utilisée
# (myAizenta-CMC, myAurora, myAizenta-PMT…). L'administrateur édite et maintient ces informations (Paramètres → « 📱 Appareils Android »).
#
# En résumé (pour un développeur WinDev) :
#   1. Au premier lancement, l'APK s'ENREGISTRE (POST /api/android/appareil/enregistrer) : SAWALI crée la fiche en état « Interdit » et rend UN JETON secret, montré une seule fois
#      à l'appareil (SAWALI ne garde que son empreinte SHA-256). Un appareil déjà connu ne reçoit JAMAIS un second jeton (sinon n'importe qui pourrait se faire passer pour lui) :
#      l'administrateur doit d'abord « Réinitialiser le jeton » (réinstallation, téléphone réinitialisé…).
#   2. À chaque ouverture, l'APK demande son STATUT (POST /api/android/appareil/statut, jeton en en-tête) : SAWALI note l'adresse IP VUE PAR LE SERVEUR (règle 21 : on ancre la
#      confiance sur ce que le serveur voit, pas sur ce que le téléphone déclare), la version de l'APK et l'heure, puis répond : état, zone, base, client, nom d'utilisateur.
#   3. L'administrateur autorise / interdit, choisit la zone et la base, nomme l'utilisateur : tout se fait dans les Paramètres (interface graphique).
#   4. Les étapes suivantes (lecture de l'Historique de Caisse, Corrections de Reçus…) vérifieront ce même jeton et cet état à CHAQUE appel : un appareil « Interdit » n'obtient rien.
# Stockage : UNE seule fiche de `settings` (`_id = "android_appareils"`, champ `appareils` = dictionnaire id → fiche) — aucune nouvelle collection (cluster MongoDB plein).
# Chaque champ est écrit séparément (`$set` sur « appareils.<id>.<champ> ») : deux modifications simultanées ne s'écrasent pas.
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ID_FICHE = "android_appareils"
MAX_APPAREILS = 500
MAX_JOURNAL = 20                      # dernières connexions gardées par appareil
ETATS = ("interdit", "autorise")

# Zones de lancement connues (règle d'accès HFSQL de Loois : /docx= → Biolog, /doc= → Aizenta, /ekol → e-Kol) et la base qu'elles ouvrent. Liste FINIE → liste déroulante
# dans l'écran, avec « Autre… » en fin de liste (règle 10) : une zone ou une base hors liste reste possible.
ZONES: List[Dict[str, str]] = [
    {"cle": "docx=CMC", "libelle": "Biolog — CMC", "base": "myAurora-CMC"},
    {"cle": "docx=IPM", "libelle": "Biolog — IPM", "base": "myAurora-IPM"},
    {"cle": "docx=PHL", "libelle": "Biolog — PHL (sans suffixe)", "base": "myAurora"},
    {"cle": "doc=CMC", "libelle": "Aizenta — CMC", "base": "myAizenta-CMC"},
    {"cle": "doc=PMT", "libelle": "Aizenta — PMT", "base": "myAizenta-PMT"},
    {"cle": "ekol", "libelle": "e-Kol", "base": "e-KOL"},
]
_RE_ZONE = re.compile(r"^(docx=[A-Za-z0-9_-]{1,20}|doc=[A-Za-z0-9_-]{1,20}|ekol)$")
_RE_BASE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")
_RE_CLIENT = re.compile(r"^[A-Za-z0-9_-]{1,30}$")


# ---------------------------------------------------------------------------------------------------------------------------- outils
def maintenant_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_secret(valeur: str) -> str:
    """Empreinte SHA-256 (le jeton et l'identifiant Android sont des valeurs longues et aléatoires : une empreinte simple suffit ; rien de lisible n'est gardé)."""
    return hashlib.sha256(str(valeur or "").encode("utf-8")).hexdigest()


def jetons_egaux(jeton_recu: str, empreinte_enregistree: str) -> bool:
    """Comparaison à temps constant du jeton présenté avec l'empreinte gardée."""
    return bool(jeton_recu) and bool(empreinte_enregistree) and hmac.compare_digest(hash_secret(jeton_recu), empreinte_enregistree)


def nettoyer(texte: Any, longueur: int) -> str:
    """Texte saisi : espaces superflus retirés, caractères de contrôle supprimés, longueur bornée."""
    return re.sub(r"[\x00-\x1f\x7f]", "", str(texte or "")).strip()[:longueur]


def base_de_la_zone(zone: str) -> str:
    """Base que la zone ouvre (vide si la zone n'est pas dans la liste connue)."""
    return next((z["base"] for z in ZONES if z["cle"] == zone), "")


# ---------------------------------------------------------------------------------------------------------------------------- fiche
def nouvelle_fiche(android_id: str, modele: str, version_app: str, ip: str, maintenant: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """(fiche, jeton en clair) d'un appareil qui s'enregistre : état INTERDIT par défaut, jamais autorisé tout seul. Le jeton n'est rendu qu'ici."""
    quand = maintenant or maintenant_iso()
    jeton = secrets.token_urlsafe(32)
    fiche = {"id": uuid.uuid4().hex[:16], "android_id_hash": hash_secret(android_id), "jeton_hash": hash_secret(jeton), "modele": nettoyer(modele, 80),
             "version_app": nettoyer(version_app, 30), "nom_utilisateur": "", "zone": "", "base": "", "client_code": "", "etat": "interdit", "notes": "",
             "cree_le": quand, "derniere_connexion": None, "ip_derniere": nettoyer(ip, 64), "ip_premiere": nettoyer(ip, 64), "journal": []}
    return fiche, jeton


def vue_admin(fiche: Dict[str, Any]) -> Dict[str, Any]:
    """Fiche telle qu'elle est montrée à l'administrateur : jamais le jeton ni les empreintes ; `jeton_actif` dit si un jeton existe."""
    return {**{k: v for k, v in fiche.items() if k not in ("jeton_hash", "android_id_hash")}, "jeton_actif": bool(fiche.get("jeton_hash")),
            "nouveau": fiche.get("etat") == "interdit" and not (fiche.get("zone") or fiche.get("nom_utilisateur"))}


def valider_modifications(donnees: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """(champs à écrire, message d'erreur) : seuls les champs modifiables par l'administrateur, tous contrôlés. Une valeur vide est permise (efface le champ)."""
    sortie: Dict[str, Any] = {}
    if "nom_utilisateur" in donnees:
        sortie["nom_utilisateur"] = nettoyer(donnees["nom_utilisateur"], 120)
    if "notes" in donnees:
        sortie["notes"] = nettoyer(donnees["notes"], 500)
    if "etat" in donnees:
        if donnees["etat"] not in ETATS:
            return {}, "État invalide : « autorise » ou « interdit »."
        sortie["etat"] = donnees["etat"]
    if "zone" in donnees:
        zone = nettoyer(donnees["zone"], 40)
        if zone and not _RE_ZONE.match(zone):
            return {}, "Zone invalide : « docx=CMC », « doc=PMT », « ekol »… (lettres, chiffres, tiret)."
        sortie["zone"] = zone
    if "base" in donnees:
        base = nettoyer(donnees["base"], 60)
        if base and not _RE_BASE.match(base):
            return {}, "Nom de base invalide : lettres, chiffres, point, tiret, souligné."
        sortie["base"] = base
    if "client_code" in donnees:
        code = nettoyer(donnees["client_code"], 30).upper()
        if code and not _RE_CLIENT.match(code):
            return {}, "Code client invalide : lettres, chiffres, tiret, souligné."
        sortie["client_code"] = code
    return sortie, ""


def reponse_statut(fiche: Dict[str, Any]) -> Dict[str, Any]:
    """Ce que l'APK reçoit de son statut : de quoi se lancer (zone, base, utilisateur) ou le motif du refus. Jamais d'empreinte ni d'IP."""
    autorise = fiche.get("etat") == "autorise"
    return {"etat": fiche.get("etat"), "autorise": autorise, "nom_utilisateur": fiche.get("nom_utilisateur") or "",
            "zone": fiche.get("zone") if autorise else "", "base": fiche.get("base") if autorise else "", "client_code": fiche.get("client_code") if autorise else "",
            "message": "" if autorise else "Accès interdit : cet appareil n'est pas encore autorisé par l'administrateur SAWALI."}


# ---------------------------------------------------------------------------------------------------------------------------- stockage
async def lire_tous(db) -> Dict[str, Dict[str, Any]]:
    fiche = await db.settings.find_one({"_id": ID_FICHE}) or {}
    return {k: v for k, v in (fiche.get("appareils") or {}).items() if isinstance(v, dict)}


async def lire_un(db, appareil_id: str) -> Optional[Dict[str, Any]]:
    return (await lire_tous(db)).get(appareil_id)


async def trouver_par_android_id(db, android_id: str) -> Optional[Dict[str, Any]]:
    h = hash_secret(android_id)
    return next((f for f in (await lire_tous(db)).values() if f.get("android_id_hash") == h), None)


async def trouver_par_jeton(db, jeton: str) -> Optional[Dict[str, Any]]:
    """Fiche dont l'empreinte correspond au jeton présenté (None si inconnu)."""
    if not jeton:
        return None
    h = hash_secret(jeton)
    return next((f for f in (await lire_tous(db)).values() if hmac.compare_digest(f.get("jeton_hash") or "", h)), None)


async def creer(db, fiche: Dict[str, Any]) -> None:
    await db.settings.update_one({"_id": ID_FICHE}, {"$set": {f"appareils.{fiche['id']}": fiche}}, upsert=True)


async def modifier(db, appareil_id: str, champs: Dict[str, Any]) -> None:
    await db.settings.update_one({"_id": ID_FICHE}, {"$set": {f"appareils.{appareil_id}.{k}": v for k, v in champs.items()}})


async def noter_connexion(db, appareil_id: str, ip: str, version_app: str, resultat: str, maintenant: Optional[str] = None) -> None:
    """Dernière connexion : heure, IP VUE PAR LE SERVEUR, version de l'APK ; ajoute une ligne au journal de l'appareil (les 20 dernières seulement)."""
    quand = maintenant or maintenant_iso()
    await db.settings.update_one({"_id": ID_FICHE}, {
        "$set": {f"appareils.{appareil_id}.derniere_connexion": quand, f"appareils.{appareil_id}.ip_derniere": nettoyer(ip, 64),
                 f"appareils.{appareil_id}.version_app": nettoyer(version_app, 30)},
        "$push": {f"appareils.{appareil_id}.journal": {"$each": [{"quand": quand, "ip": nettoyer(ip, 64), "resultat": resultat}], "$slice": -MAX_JOURNAL}}})


async def supprimer(db, appareil_id: str) -> bool:
    existe = await lire_un(db, appareil_id)
    if not existe:
        return False
    await db.settings.update_one({"_id": ID_FICHE}, {"$unset": {f"appareils.{appareil_id}": ""}})
    return True


def candidats_nettoyage(fiches: Dict[str, Dict[str, Any]], modele: str = "") -> List[Dict[str, Any]]:
    """Appareils à nettoyer : INTERDITS et jamais renseignés (badge « Nouveau » : ni utilisateur ni zone), éventuellement d'un modèle donné (« robolectric » = tests). Un appareil autorisé ou déjà renseigné n'est JAMAIS candidat."""
    m = (modele or "").strip().lower()
    return [vue_admin(f) for f in fiches.values() if vue_admin(f)["nouveau"] and (not m or m in str(f.get("modele") or "").lower())]


async def supprimer_plusieurs(db, ids: List[str]) -> int:
    """Supprime plusieurs fiches en une seule écriture ; rend le nombre de fiches réellement présentes."""
    existants = [i for i in ids if await lire_un(db, i)]
    if existants:
        await db.settings.update_one({"_id": ID_FICHE}, {"$unset": {f"appareils.{i}": "" for i in existants}})
    return len(existants)
