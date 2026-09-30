"""Lot 47 — Sauvegardes de migration PROGRAMMÉES, rotation (rétention) dans R2 et
rapport envoyé à l'admin par Liluvine.

Complète routes/migration_render.py (même moteur de sauvegarde, mêmes collections de suivi).

1. PROGRAMMATION (Paramètres → Migration vers Render, Admin uniquement)
   Réglage : un document `_id = "parametres"` de la collection `migration_programmation`
   (exclue de la copie : le nouveau site n'hérite pas de la programmation) :
     actif, tous_les (N jours, 1 = tous les jours), heure « HH:MM », fuseau
     (Africa/Ouagadougou par défaut, comme les plages d'envoi du lot 42), contenu
     (base, fichiers, médias), rétention, rapport, prochaine_execution (UTC).
   Toujours en mode FUSION (jamais « Remplacer » en automatique). Les SECRETS (variables
   d'environnement) ne sont jamais sauvegardés en programmé : voir plus bas.

2. IDENTIFIANTS DES SAUVEGARDES PROGRAMMÉES
   Le coffre du lot 45 exige son mot de passe à chaque ouverture : inutilisable sans
   l'admin. L'admin enregistre donc UNE FOIS, avec le bouton « Utiliser ces identifiants
   pour les sauvegardes programmées », l'URI Atlas et les clés R2 saisies :
     - vérifiés (connexion Atlas, accès au bucket) avant d'être gardés ;
     - chiffrés en AES-256-GCM avec une clé dérivée (HKDF-SHA256, sel aléatoire) de la
       variable d'environnement MIGRATION_COFFRE_CLE si elle existe, sinon de JWT_SECRET ;
       refus si aucune n'est définie (ou si JWT_SECRET vaut la valeur de secours du code) ;
     - rangés dans `migration_programmation` (`_id = "identifiants"`), collection exclue de
       la copie vers Atlas ; l'API ne renvoie JAMAIS leur contenu (seulement l'hôte Atlas,
       le nom de la base et du bucket, la date) ;
     - une empreinte de la clé permet de signaler « illisibles » si la clé du serveur change.
   Le mot de passe de chiffrement des secrets ne peut pas être conservé ainsi sans
   affaiblir le fichier des secrets (qui contient JWT_SECRET lui-même) : l'option
   « Variables d'environnement » est donc désactivée en programmé.

3. EXÉCUTION : `passage()` toutes les 60 s (tâche asyncio lancée au démarrage, hors preview) :
     - une échéance passée déclenche UNE sauvegarde : le document `parametres` passe de
       l'échéance lue à la suivante par find_one_and_update (un seul processus gagne) ;
     - jamais si une sauvegarde est EN_COURS (l'échéance attend le passage suivant) ;
     - serveur arrêté à l'heure prévue : exécution au premier passage, puis échéance
       suivante = échéance + N jours, avancée jusqu'au futur (pas de rafale de rattrapage).

4. RÉTENTION : après chaque sauvegarde programmée terminée (et « Purger maintenant »), les
   préfixes `migration-AAAAMMJJ-HHMMSS/` plus anciens que la rétention sont supprimés de R2,
   sauf : les K dernières sauvegardes réussies, toute sauvegarde EN_COURS, tout préfixe
   inconnu de l'historique ou hors motif, et (option) les sauvegardes manuelles. Les
   documents de suivi sont gardés, marqués `purgee: true`.

5. RAPPORT « 🤖 Liluvine » par WhatsApp aux numéros admin de Liluvine (fenêtre 24 h : texte ;
   sinon modèle Meta s'il est réglé), avec repli par e-mail si aucun WhatsApp n'est parti.

  GET    /api/admin/migration/programmation                  réglage + état (sans identifiants)
  PUT    /api/admin/migration/programmation                  enregistrement du réglage
  PUT    /api/admin/migration/programmation/identifiants     identifiants (vérifiés puis chiffrés)
  DELETE /api/admin/migration/programmation/identifiants     oubli des identifiants
  POST   /api/admin/migration/programmation/lancer           « Lancer maintenant avec ces réglages »
  POST   /api/admin/migration/programmation/purger           « Purger maintenant »
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_admin
from routes import migration_render as mr

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/migration/programmation", tags=["Migration vers Render"])

DOC_ID = "parametres"  # réglage de la programmation
IDENTIFIANTS_ID = "identifiants"  # identifiants chiffrés par la clé du serveur
INTERVALLE = 60  # secondes entre deux passages du planificateur
RE_HEURE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# Préfixe d'une sauvegarde dans R2 : seul ce motif exact peut être purgé
RE_PREFIXE = re.compile(r"^migration-(\d{8})-(\d{6})$")
# Statuts d'une sauvegarde complète (manifeste écrit) : comptent pour « les K dernières réussies »
REUSSIS = ("TERMINEE", "TERMINEE_AVEC_ERREURS")
FINAUX = ("TERMINEE", "TERMINEE_AVEC_ERREURS", "ECHEC", "INTERROMPUE")
LOT_SUPPRESSION = 1000  # clés par appel delete_objects (maximum S3/R2)
DESTINATAIRES_WA_MAX = 5
# Clé de chiffrement de secours du code (auth.py) : jamais acceptée comme clé du coffre
CLE_DE_SECOURS = "fallback-insecure"

DEFAUT: Dict[str, Any] = {
    "actif": False, "tous_les": 1, "heure": "03:00", "fuseau": "Africa/Ouagadougou",
    "base": True, "fichiers": True, "medias": True,
    "retention_jours": 14, "garder_min": 3, "purge_manuelles": True,
    "rapport_si_ok": True, "modele_wa": "", "modele_wa_langue": "fr",
}
STATUTS_TEXTE = {
    "TERMINEE": "✅ Terminée", "TERMINEE_AVEC_ERREURS": "⚠️ Terminée avec anomalies",
    "ECHEC": "❌ Échec", "INTERROMPUE": "⏸️ Interrompue", "EN_COURS": "⏳ En cours",
}
EXPLICATION_SECRETS = ("Les variables d'environnement ne sont pas sauvegardées en programmé : leur fichier "
                       "est chiffré par un mot de passe que le serveur ne doit pas conserver. Faites-le "
                       "avec une sauvegarde manuelle après chaque changement de variable.")


def _maintenant() -> datetime:
    """Horloge (remplaçable en test)."""
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.astimezone(timezone.utc).isoformat() if d else None


def _lire_date(valeur: Any) -> Optional[datetime]:
    """ISO ou datetime -> datetime UTC (None si absent ou illisible)."""
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Échéances (fonctions pures, testées sans base)
# ---------------------------------------------------------------------------
def normaliser(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Contrôle le réglage ; lève ValueError avec un message clair."""
    cfg = {**DEFAUT, **{k: v for k, v in (cfg or {}).items() if v is not None}}
    try:
        ZoneInfo(cfg["fuseau"])
    except Exception:  # noqa: BLE001 — fuseau inconnu
        raise ValueError(f"Fuseau horaire inconnu : « {cfg['fuseau']} »")
    heure = str(cfg["heure"]).strip()
    if not RE_HEURE.match(heure):
        raise ValueError("Heure au format HH:MM (ex. 03:00)")
    tous_les, retention, garder = int(cfg["tous_les"]), int(cfg["retention_jours"]), int(cfg["garder_min"])
    if not 1 <= tous_les <= 365:
        raise ValueError("Fréquence : tous les 1 à 365 jours")
    if not 1 <= retention <= 3650:
        raise ValueError("Rétention : 1 à 3650 jours")
    if not 1 <= garder <= 100:
        raise ValueError("Sauvegardes réussies toujours gardées : 1 à 100")
    if cfg["actif"] and not (cfg["base"] or cfg["fichiers"]):
        raise ValueError("Choisissez au moins la base ou les fichiers")
    return {"actif": bool(cfg["actif"]), "tous_les": tous_les, "heure": heure, "fuseau": cfg["fuseau"],
            "base": bool(cfg["base"]), "fichiers": bool(cfg["fichiers"]), "medias": bool(cfg["medias"]),
            "retention_jours": retention, "garder_min": garder, "purge_manuelles": bool(cfg["purge_manuelles"]),
            "rapport_si_ok": bool(cfg["rapport_si_ok"]), "modele_wa": str(cfg["modele_wa"] or "").strip()[:120],
            "modele_wa_langue": str(cfg["modele_wa_langue"] or "fr").strip()[:12] or "fr"}


def _a_l_heure(cfg: Dict[str, Any], jour) -> datetime:
    """Le jour `jour` (date locale) à l'heure du réglage, dans le fuseau du réglage."""
    h, m = (int(x) for x in cfg["heure"].split(":"))
    return datetime(jour.year, jour.month, jour.day, h, m, tzinfo=ZoneInfo(cfg["fuseau"]))


def premiere_echeance(cfg: Dict[str, Any], maintenant: datetime) -> datetime:
    """Première exécution après l'activation (ou un changement d'heure / de fréquence) :
    aujourd'hui à l'heure prévue si elle n'est pas passée, sinon demain. -> UTC."""
    local = maintenant.astimezone(ZoneInfo(cfg["fuseau"]))
    candidat = _a_l_heure(cfg, local.date())
    if candidat <= local:
        candidat = _a_l_heure(cfg, local.date() + timedelta(days=1))
    return candidat.astimezone(timezone.utc)


def echeance_suivante(cfg: Dict[str, Any], echeance: datetime, maintenant: datetime) -> datetime:
    """Échéance qui suit `echeance` (exécutée à `maintenant`, éventuellement en retard) :
    + N jours à l'heure prévue, avancée de N jours tant qu'elle est déjà passée.
    Un serveur arrêté plusieurs jours rattrape donc UNE seule sauvegarde, sans rafale. -> UTC."""
    jour = echeance.astimezone(ZoneInfo(cfg["fuseau"])).date()
    while True:
        jour += timedelta(days=cfg["tous_les"])
        candidat = _a_l_heure(cfg, jour)
        if candidat > maintenant:
            return candidat.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Identifiants chiffrés par la clé du serveur
# ---------------------------------------------------------------------------
def _materiau_cle() -> tuple:
    """-> (octets de la clé maîtresse, nom de la variable utilisée). MIGRATION_COFFRE_CLE d'abord
    (clé dédiée, recommandée), sinon JWT_SECRET. Lève RuntimeError si aucune n'est utilisable."""
    for nom in ("MIGRATION_COFFRE_CLE", "JWT_SECRET"):
        valeur = os.environ.get(nom) or ""
        if len(valeur) >= 16 and valeur != CLE_DE_SECOURS:
            return valeur.encode(), nom
    raise RuntimeError("Aucune clé serveur utilisable : définissez MIGRATION_COFFRE_CLE (32 caractères "
                       "aléatoires ou plus) ou JWT_SECRET dans les variables d'environnement")


def _empreinte_cle(materiau: bytes) -> str:
    """Empreinte courte de la clé (détecte un changement de clé, ne révèle rien de la clé)."""
    return hashlib.sha256(b"sawali-migration-programmation/empreinte|" + materiau).hexdigest()[:16]


def _deriver(materiau: bytes, sel: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=sel,
                info=b"sawali-migration-programmation/v1").derive(materiau)


# Données associées (AAD) : l'enveloppe ne peut pas être déplacée vers un autre usage
AAD = b"migration_programmation/identifiants"


def chiffrer_serveur(donnees: bytes) -> Dict[str, Any]:
    """AES-256-GCM, clé dérivée (HKDF-SHA256, sel aléatoire) de la clé maîtresse du serveur."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    materiau, source = _materiau_cle()
    sel, nonce = os.urandom(16), os.urandom(12)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"format": "sawali-migration-programmation/v1", "algo": "AES-256-GCM", "kdf": "HKDF-SHA256",
            "source_cle": source, "empreinte_cle": _empreinte_cle(materiau), "sel": b64(sel), "nonce": b64(nonce),
            "donnees": b64(AESGCM(_deriver(materiau, sel)).encrypt(nonce, donnees, AAD))}


def dechiffrer_serveur(enveloppe: Dict[str, Any]) -> bytes:
    """Inverse de chiffrer_serveur. Lève RuntimeError si la clé du serveur a changé."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    materiau, _ = _materiau_cle()
    if enveloppe.get("empreinte_cle") != _empreinte_cle(materiau):
        raise RuntimeError("Identifiants illisibles : la clé du serveur a changé. Enregistrez-les à nouveau")
    d = lambda k: base64.b64decode(enveloppe[k])  # noqa: E731
    return AESGCM(_deriver(materiau, d("sel"))).decrypt(d("nonce"), d("donnees"), AAD)


def _identifiants_publics(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ce que l'écran peut savoir des identifiants : JAMAIS l'URI ni les clés."""
    if not doc:
        return {"existe": False}
    try:
        lisibles = doc["enveloppe"].get("empreinte_cle") == _empreinte_cle(_materiau_cle()[0])
    except Exception:  # noqa: BLE001 — aucune clé serveur
        lisibles = False
    return {"existe": True, "cree_le": doc.get("cree_le"), "par": doc.get("par"), "champs": doc.get("champs", []),
            "mongo_hote": doc.get("mongo_hote"), "mongo_db": doc.get("mongo_db"), "r2_bucket": doc.get("r2_bucket"),
            "source_cle": doc["enveloppe"].get("source_cle"), "lisibles": lisibles}


async def charger_identifiants() -> Dict[str, str]:
    """Identifiants en clair, en mémoire seulement (pour la sauvegarde ou la purge)."""
    doc = await mr.db.migration_programmation.find_one({"_id": IDENTIFIANTS_ID})
    if not doc:
        raise RuntimeError("Aucun identifiant enregistré pour les sauvegardes programmées")
    try:
        return json.loads(await asyncio.to_thread(dechiffrer_serveur, doc["enveloppe"]))
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 — contrôle d'intégrité GCM
        raise RuntimeError("Identifiants illisibles (clé du serveur changée ?). Enregistrez-les à nouveau")


def _client_r2(ids: Dict[str, str]):
    return mr._client_r2(ids["r2_account_id"], ids["r2_access_key_id"], ids["r2_secret_access_key"])


# ---------------------------------------------------------------------------
# Rétention : purge des anciennes sauvegardes dans R2
# ---------------------------------------------------------------------------
def choisir_a_purger(prefixes: List[str], jobs_par_prefixe: Dict[str, List[dict]], cfg: Dict[str, Any],
                     maintenant: datetime) -> tuple:
    """-> (préfixes à supprimer, {préfixe: raison de le garder}). Fonction pure.
    Gardés : hors motif `migration-AAAAMMJJ-HHMMSS`, inconnus de l'historique, EN_COURS,
    parmi les K dernières réussies, plus récents que la rétention, manuels (si l'option le dit)."""
    candidats = []
    gardes: Dict[str, str] = {}
    for p in prefixes:
        m = RE_PREFIXE.match(p)
        if not m:
            gardes[p] = "hors motif"
            continue
        try:
            date = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            gardes[p] = "hors motif"
            continue
        candidats.append((date, p, jobs_par_prefixe.get(p) or []))
    candidats.sort(reverse=True)
    reussies = [p for _, p, jobs in candidats if any(j.get("statut") in REUSSIS for j in jobs)]
    k_dernieres = set(reussies[:cfg["garder_min"]])
    limite = maintenant - timedelta(days=cfg["retention_jours"])
    a_supprimer = []
    for date, p, jobs in candidats:
        if any(j.get("statut") == "EN_COURS" for j in jobs):
            gardes[p] = "en cours"
        elif not jobs:
            gardes[p] = "inconnue de l'historique"
        elif p in k_dernieres:
            gardes[p] = f"parmi les {cfg['garder_min']} dernières réussies"
        elif date >= limite:
            gardes[p] = "dans la rétention"
        elif not cfg["purge_manuelles"] and not any(j.get("programmee") for j in jobs):
            gardes[p] = "manuelle (non purgée)"
        else:
            a_supprimer.append(p)
    return a_supprimer, gardes


def _lister_prefixes(r2, bucket: str) -> List[str]:
    """Dossiers de premier niveau du bucket (liste paginée)."""
    prefixes, jeton = [], None
    while True:
        args = {"Bucket": bucket, "Delimiter": "/", "MaxKeys": 1000}
        if jeton:
            args["ContinuationToken"] = jeton
        page = r2.list_objects_v2(**args)
        prefixes += [cp["Prefix"].rstrip("/") for cp in page.get("CommonPrefixes") or []]
        if not page.get("IsTruncated"):
            return prefixes
        jeton = page.get("NextContinuationToken")


def _supprimer_prefixe(r2, bucket: str, prefixe: str) -> tuple:
    """Supprime tous les objets `prefixe/…` (liste paginée, delete_objects par lots de 1000).
    La page suivante est demandée APRÈS la dernière clé vue (StartAfter) : fiable même si la
    suppression décale la liste, et sans boucle infinie sur un objet impossible à supprimer.
    -> (objets supprimés, octets libérés, erreurs)."""
    objets, octets, erreurs, apres = 0, 0, 0, None
    while True:
        args = {"Bucket": bucket, "Prefix": f"{prefixe}/", "MaxKeys": LOT_SUPPRESSION}
        if apres:
            args["StartAfter"] = apres
        page = r2.list_objects_v2(**args)
        lot = (page.get("Contents") or [])[:LOT_SUPPRESSION]
        if not lot:
            return objets, octets, erreurs
        reponse = r2.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in lot],
                                                           "Quiet": True})
        en_erreur = {e.get("Key") for e in (reponse or {}).get("Errors") or []}
        erreurs += len(en_erreur)
        for o in lot:
            if o["Key"] not in en_erreur:
                objets += 1
                octets += int(o.get("Size") or 0)
        apres = lot[-1]["Key"]
        if not page.get("IsTruncated"):
            return objets, octets, erreurs


async def purger(maintenant: Optional[datetime] = None, r2=None, bucket: Optional[str] = None,
                 cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Applique la rétention au bucket des sauvegardes programmées. Les documents de suivi des
    sauvegardes supprimées sont gardés et marqués `purgee: true`. Résultat journalisé et gardé
    dans le réglage (`derniere_purge`)."""
    maintenant = maintenant or _maintenant()
    cfg = cfg or await lire_reglage()
    if r2 is None:
        ids = await charger_identifiants()
        r2, bucket = _client_r2(ids), ids["r2_bucket"]
    prefixes = await asyncio.to_thread(_lister_prefixes, r2, bucket)
    jobs_par_prefixe: Dict[str, List[dict]] = {}
    async for j in mr.db.migration_jobs.find({"cible.r2_bucket": bucket},
                                             {"_id": 0, "id": 1, "statut": 1, "programmee": 1, "cible": 1}):
        jobs_par_prefixe.setdefault((j.get("cible") or {}).get("prefixe"), []).append(j)
    a_supprimer, gardes = choisir_a_purger(prefixes, jobs_par_prefixe, cfg, maintenant)
    supprimees, total_objets, total_octets, total_erreurs = [], 0, 0, 0
    for p in a_supprimer:
        objets, octets, erreurs = await asyncio.to_thread(_supprimer_prefixe, r2, bucket, p)
        total_objets, total_octets, total_erreurs = total_objets + objets, total_octets + octets, total_erreurs + erreurs
        supprimees.append({"prefixe": p, "objets": objets, "octets": octets, "erreurs": erreurs})
        # Historique conservé : la sauvegarde est seulement marquée « purgée »
        await mr.db.migration_jobs.update_many(
            {"cible.prefixe": p, "cible.r2_bucket": bucket},
            {"$set": {"purgee": erreurs == 0, "purgee_le": _iso(maintenant),
                      "purge": {"objets": objets, "octets": octets, "erreurs": erreurs}}})
        logger.info("[migration-purge] %s/%s : %d objet(s), %d octet(s) supprimé(s), %d erreur(s)",
                    bucket, p, objets, octets, erreurs)
    resultat = {"le": _iso(maintenant), "bucket": bucket, "examinees": len(prefixes), "supprimees": supprimees,
                "objets": total_objets, "octets": total_octets, "erreurs": total_erreurs,
                "gardees": len(gardes), "raisons": _compter(gardes.values())}
    logger.info("[migration-purge] bilan : %d sauvegarde(s) supprimée(s), %d objet(s), %d octet(s), %d erreur(s)",
                len(supprimees), total_objets, total_octets, total_erreurs)
    await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"derniere_purge": resultat}},
                                                   upsert=True)
    return resultat


def _compter(valeurs) -> Dict[str, int]:
    compte: Dict[str, int] = {}
    for v in valeurs:
        compte[v] = compte.get(v, 0) + 1
    return compte


# ---------------------------------------------------------------------------
# Rapport Liluvine à l'admin (WhatsApp, repli e-mail)
# ---------------------------------------------------------------------------
# Fonctions d'envoi fournies par server.py au démarrage (configurer) ; simulées en test
_ENVOIS: Dict[str, Optional[Callable[..., Awaitable[dict]]]] = {"texte": None, "modele": None, "email": None}
_EMAIL_DEFAUT = {"adresse": os.environ.get("SUPER_ADMIN_EMAIL", "")}


def configurer(*, envoyer_wa_texte=None, envoyer_wa_modele=None, envoyer_email=None,
               email_defaut: Optional[str] = None) -> None:
    """Branche l'envoi WhatsApp (texte, modèle Meta) et l'e-mail existants du serveur."""
    _ENVOIS.update(texte=envoyer_wa_texte, modele=envoyer_wa_modele,
                   email=envoyer_email or _ENVOIS.get("email"))
    if email_defaut:
        _EMAIL_DEFAUT["adresse"] = email_defaut


def _chiffres(n: Any) -> str:
    return "".join(ch for ch in str(n or "") if ch.isdigit())


def _destinataires_wa(reglages_globaux: Dict[str, Any]) -> List[str]:
    """Numéros admin de Liluvine (Paramètres → Liluvine), comme le récapitulatif d'import de
    sauvegarde ; à défaut le numéro d'escalade de Liluvine, puis le WhatsApp de l'entreprise."""
    bruts = list(reglages_globaux.get("liluvine_remote_admin_phones") or [])
    if not bruts:
        bruts = [reglages_globaux.get("liluvine_escalation_wa_phone") or reglages_globaux.get("llm_budget_notify_wa_phone")
                 or reglages_globaux.get("company_whatsapp")]
    vus: List[str] = []
    for b in bruts:
        c = _chiffres(b)
        if len(c) >= 6 and c not in vus:
            vus.append(c)
    return vus[:DESTINATAIRES_WA_MAX]


async def _fenetre_ouverte(chiffres: str, maintenant: datetime) -> bool:
    """Fenêtre de 24 h de Meta : l'admin a-t-il écrit (à Liluvine) depuis moins de 24 h ?
    Hors fenêtre, un texte libre n'est pas remis : il faut un modèle approuvé."""
    dernier = await mr.db.whatsapp_messages.find_one(
        {"direction": "inbound", "phone_digits": chiffres}, {"_id": 0, "received_at": 1, "created_at": 1},
        sort=[("created_at", -1)])
    quand = _lire_date((dernier or {}).get("received_at") or (dernier or {}).get("created_at"))
    return bool(quand) and (maintenant - quand).total_seconds() < 24 * 3600


def _une_ligne(texte: str, maximum: int = 1000) -> str:
    """Paramètre de modèle Meta : sans saut de ligne ni suite d'espaces, 1 024 caractères au plus."""
    t = re.sub(r"\s*\n\s*", " · ", texte.strip())
    return re.sub(r"\s{2,}", " ", t)[:maximum]


async def envoyer_rapport(sujet: str, texte: str, cfg: Dict[str, Any], important: bool,
                          maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Envoie le rapport à l'admin. `important` (échec, anomalie, erreur de purge) : toujours envoyé ;
    sinon seulement si « M'envoyer le rapport même quand tout va bien » est coché.
    WhatsApp : texte dans la fenêtre de 24 h, sinon modèle Meta réglé (une variable {{1}}) ;
    e-mail (SMTP existant) si aucun WhatsApp n'est parti."""
    maintenant = maintenant or _maintenant()
    if not important and not cfg.get("rapport_si_ok", True):
        return {"envoye": False, "motif": "tout va bien : rapport non demandé"}
    globaux = await mr.db.settings.find_one({"_id": "global"}) or {}
    resultat: Dict[str, Any] = {"envoye": False, "whatsapp": [], "email": None}
    for numero in _destinataires_wa(globaux):
        try:
            if await _fenetre_ouverte(numero, maintenant) and _ENVOIS["texte"]:
                mode, r = "texte", await _ENVOIS["texte"](numero, texte)
            elif cfg.get("modele_wa") and _ENVOIS["modele"]:
                composants = [{"type": "body", "parameters": [{"type": "text", "text": _une_ligne(texte)}]}]
                mode, r = "modèle", await _ENVOIS["modele"](numero, cfg["modele_wa"], cfg.get("modele_wa_langue") or "fr",
                                                             composants)
            else:
                mode, r = "aucun", {"ok": False, "error": "hors fenêtre de 24 h et aucun modèle Meta réglé"}
        except Exception as exc:  # noqa: BLE001
            mode, r = "erreur", {"ok": False, "error": str(exc)[:200]}
        resultat["whatsapp"].append({"a": numero, "mode": mode, "ok": bool(r.get("ok")),
                                     "erreur": None if r.get("ok") else str(r.get("error") or "")[:200]})
    if any(w["ok"] for w in resultat["whatsapp"]):
        resultat["envoye"] = True
        return resultat
    # Repli : e-mail à l'adresse des sauvegardes (ou du rapport de santé, ou du super-admin)
    adresse = (globaux.get("auto_snapshot_email_to") or globaux.get("health_email_to")
               or _EMAIL_DEFAUT["adresse"] or "").strip()
    if adresse and "@" in adresse:
        try:
            envoi = _ENVOIS["email"]
            if envoi is None:
                from email_service import send_email as envoi
            corps = f"<pre style=\"font-family:Arial,sans-serif;white-space:pre-wrap\">{html.escape(texte)}</pre>"
            ok = bool(await envoi(adresse, f"[SAWALI] {sujet}", corps, texte))
            resultat["email"] = {"a": adresse, "ok": ok}
            resultat["envoye"] = ok
        except Exception as exc:  # noqa: BLE001
            resultat["email"] = {"a": adresse, "ok": False, "erreur": str(exc)[:200]}
    else:
        resultat["email"] = {"a": None, "ok": False, "erreur": "aucune adresse e-mail d'administration"}
    if not resultat["envoye"]:
        logger.warning("[migration-programmation] rapport non remis : %s", resultat)
    return resultat


def _taille(octets: Any) -> str:
    """Octets -> « 1,2 Go », « 350,0 Mo », « 12 Ko »."""
    o = int(octets or 0)
    for seuil, unite in ((1 << 30, "Go"), (1 << 20, "Mo")):
        if o >= seuil:
            return f"{o / seuil:.1f} {unite}".replace(".", ",")
    return f"{max(0, round(o / 1024))} Ko"


def _nombre(n: Any) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _duree(debut: Any, fin: Any) -> str:
    d1, d2 = _lire_date(debut), _lire_date(fin)
    if not d1 or not d2:
        return "—"
    s = max(0, int((d2 - d1).total_seconds()))
    return f"{s // 3600} h {s % 3600 // 60:02d} min" if s >= 3600 else f"{s // 60} min {s % 60:02d} s"


def _local(d: Any, cfg: Dict[str, Any]) -> str:
    """Date UTC -> « 30/09/2026 à 03:00 » dans le fuseau du réglage."""
    date = _lire_date(d)
    return date.astimezone(ZoneInfo(cfg["fuseau"])).strftime("%d/%m/%Y à %H:%M") if date else "—"


def _lignes_purge(purge: Optional[Dict[str, Any]]) -> List[str]:
    if not purge:
        return []
    if purge.get("erreur"):
        return [f"Purge : ❌ {purge['erreur']}"]
    lignes = [f"Purge : {len(purge['supprimees'])} sauvegarde(s) supprimée(s), {_taille(purge['octets'])} libéré(s) "
              f"({_nombre(purge['objets'])} objet(s)) · {purge['gardees']} gardée(s)"]
    if purge.get("erreurs"):
        lignes.append(f"⚠️ Purge : {purge['erreurs']} objet(s) non supprimé(s)")
    return lignes


def texte_rapport_sauvegarde(job: Dict[str, Any], purge: Optional[Dict[str, Any]], cfg: Dict[str, Any],
                             prochaine: Optional[str]) -> str:
    """Rapport d'une sauvegarde programmée (signé Liluvine)."""
    opts = job.get("options") or {}
    cible = job.get("cible") or {}
    lignes = ["🤖 Liluvine — Rapport de sauvegarde",
              f"Sauvegarde programmée du {_local(job.get('debut'), cfg)} ({cfg['fuseau']})",
              f"Statut : {STATUTS_TEXTE.get(job.get('statut'), job.get('statut'))}",
              f"Durée : {_duree(job.get('debut'), job.get('fin'))}"]
    if opts.get("base"):
        lignes.append(f"Base : {job.get('collections_faites', 0)}/{job.get('collections_total', 0)} collections copiées "
                      f"({_nombre(job.get('documents_copies'))} documents)")
    if opts.get("fichiers"):
        lignes.append(f"Fichiers : {_nombre(job.get('fichiers_copies'))} copiés · {_nombre(job.get('fichiers_absents'))} "
                      f"absents à la source · {_nombre(job.get('fichiers_medias_ignores'))} médias ignorés · "
                      f"{_nombre(job.get('fichiers_echecs'))} vraies erreurs")
    lignes.append(f"Taille envoyée : {_taille((job.get('octets_archives') or 0) + (job.get('octets_fichiers') or 0))}")
    lignes.append(f"Emplacement R2 : {cible.get('r2_bucket')}/{cible.get('prefixe')}")
    if job.get("statut") not in REUSSIS and job.get("journal"):
        lignes.append(f"Dernière étape : {str(job['journal'][-1])[:300]}")
    lignes += _lignes_purge(purge)
    lignes.append(f"Prochaine exécution : {_local(prochaine, cfg) if prochaine else 'aucune (programmation arrêtée)'}")
    return "\n".join(lignes)


def texte_rapport_echec(erreur: str, debut: datetime, cfg: Dict[str, Any], prochaine: Optional[str]) -> str:
    """Rapport d'une sauvegarde programmée qui n'a pas pu démarrer."""
    return "\n".join([
        "🤖 Liluvine — Rapport de sauvegarde",
        f"Sauvegarde programmée du {_local(debut, cfg)} ({cfg['fuseau']})",
        f"Statut : {STATUTS_TEXTE['ECHEC']} (non démarrée)",
        f"Cause : {erreur[:300]}",
        f"Prochaine exécution : {_local(prochaine, cfg) if prochaine else 'aucune (programmation arrêtée)'}",
    ])


def texte_rapport_purge(purge: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    """Rapport de « Purger maintenant »."""
    lignes = ["🤖 Liluvine — Rapport de purge des sauvegardes",
              f"Purge du {_local(purge.get('le'), cfg)} ({cfg['fuseau']}) · bucket {purge.get('bucket')}",
              f"Règle : rétention {cfg['retention_jours']} jour(s), {cfg['garder_min']} dernière(s) réussie(s) "
              f"toujours gardée(s)" + ("" if cfg["purge_manuelles"] else ", sauvegardes manuelles non purgées")]
    lignes += _lignes_purge(purge)
    lignes += [f"  - {s['prefixe']} : {_taille(s['octets'])}" for s in purge.get("supprimees", [])[:10]]
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Réglage, déclenchement et passage du planificateur
# ---------------------------------------------------------------------------
async def lire_reglage() -> Dict[str, Any]:
    """Réglage complet (valeurs par défaut + état : prochaine exécution, dernière exécution...)."""
    doc = await mr.db.migration_programmation.find_one({"_id": DOC_ID}) or {}
    return {**DEFAUT, **{k: v for k, v in doc.items() if k != "_id"}}


def _cible_programmee(cfg: Dict[str, Any], ids: Dict[str, str]) -> "mr.Cible":
    """Demande de sauvegarde d'une exécution programmée : toujours en fusion, jamais les secrets."""
    if cfg["base"] and len(ids.get("mongo_uri") or "") < 10:
        raise RuntimeError("Base demandée mais aucune URI Atlas enregistrée pour les sauvegardes programmées")
    return mr.Cible(mongo_uri=ids.get("mongo_uri") or "", mongo_db=ids.get("mongo_db") or "sawali", remplacer=False,
                    r2_account_id=ids.get("r2_account_id") or "", r2_access_key_id=ids.get("r2_access_key_id") or "",
                    r2_secret_access_key=ids.get("r2_secret_access_key") or "", r2_bucket=ids.get("r2_bucket") or "",
                    copier_base=cfg["base"], copier_fichiers=cfg["fichiers"], sauver_secrets=False,
                    copier_medias=cfg["medias"])


async def declencher(cfg: Dict[str, Any], maintenant: datetime, lance_par: str = "programmation") -> Dict[str, Any]:
    """Lance une sauvegarde avec les réglages et identifiants de la programmation.
    Échec au démarrage (identifiants, connexion, sauvegarde déjà en cours) : rapport d'échec."""
    try:
        cible = _cible_programmee(cfg, await charger_identifiants())
        res = await mr._demarrer(cible, lance_par, programmee=True)
    except (HTTPException, RuntimeError, ValueError) as exc:
        erreur = str(exc.detail if isinstance(exc, HTTPException) else exc)
        # Échec avant toute copie : pas de document de sauvegarde, le réglage garde la trace
        rapport = await envoyer_rapport("Sauvegarde programmée : échec",
                                        texte_rapport_echec(erreur, maintenant, cfg, cfg.get("prochaine_execution")),
                                        cfg, important=True, maintenant=maintenant)
        await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"derniere_execution": {
            "debut": _iso(maintenant), "fin": _iso(maintenant), "statut": "ECHEC", "erreur": erreur[:300],
            "lance_par": lance_par, "rapport": rapport}}}, upsert=True)
        logger.warning("[migration-programmation] sauvegarde non démarrée : %s", erreur)
        return {"ok": False, "erreur": erreur}
    await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"derniere_execution": {
        "job_id": res["id"], "prefixe": res["prefixe"], "debut": _iso(maintenant), "statut": "EN_COURS",
        "lance_par": lance_par}}}, upsert=True)
    logger.info("[migration-programmation] sauvegarde lancée : %s", res["prefixe"])
    return {"ok": True, **res}


async def _traiter_terminees(maintenant: datetime) -> List[str]:
    """Sauvegardes programmées terminées (même avant un redémarrage) dont le rapport n'est pas
    parti : purge (si réussie), puis rapport. Chaque sauvegarde est prise par un seul processus."""
    traitees = []
    a_traiter = await mr.db.migration_jobs.find({"programmee": True, "statut": {"$in": list(FINAUX)}, "rapport": None},
                                                {"_id": 0, "id": 1}).to_list(50)
    for j in a_traiter:
        job = await mr.db.migration_jobs.find_one_and_update(
            {"id": j["id"], "rapport": None}, {"$set": {"rapport": {"etat": "en cours", "le": _iso(maintenant)}}},
            projection={"_id": 0, "secrets_chiffres": 0, "echecs_fichiers": 0, "absents_fichiers": 0,
                        "resultats_collections": 0})
        if not job:
            continue
        cfg = await lire_reglage()
        purge = None
        if job.get("statut") in REUSSIS:
            try:
                purge = await purger(maintenant, cfg=cfg)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[migration-programmation] purge impossible : %s", exc)
                purge = {"erreur": str(exc)[:200]}
        important = job.get("statut") != "TERMINEE" or bool(purge and (purge.get("erreur") or purge.get("erreurs")))
        texte = texte_rapport_sauvegarde(job, purge, cfg, cfg.get("prochaine_execution") if cfg["actif"] else None)
        rapport = await envoyer_rapport(f"Sauvegarde programmée : {STATUTS_TEXTE.get(job.get('statut'), '')}",
                                        texte, cfg, important, maintenant)
        rapport["le"] = _iso(maintenant)
        await mr.db.migration_jobs.update_one({"id": job["id"]}, {"$set": {"rapport": rapport}})
        await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"derniere_execution": {
            "job_id": job["id"], "prefixe": (job.get("cible") or {}).get("prefixe"), "debut": job.get("debut"),
            "fin": job.get("fin"), "statut": job.get("statut"), "lance_par": job.get("lance_par"),
            "rapport": rapport, "purge": purge}}}, upsert=True)
        traitees.append(job["id"])
    return traitees


async def passage(maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Un passage du planificateur : rapports des sauvegardes terminées, puis déclenchement si
    l'échéance est passée (une seule fois par échéance, jamais pendant une sauvegarde en cours)."""
    maintenant = maintenant or _maintenant()
    await mr._marquer_orphelines()
    bilan: Dict[str, Any] = {"rapports": await _traiter_terminees(maintenant), "declenchee": None, "attente": None}
    cfg = await lire_reglage()
    echeance = _lire_date(cfg.get("prochaine_execution"))
    if not cfg["actif"] or not echeance or maintenant < echeance:
        return bilan
    if await mr.db.migration_jobs.find_one({"statut": "EN_COURS"}, {"_id": 1}):
        # L'échéance attend la fin de la sauvegarde en cours (rattrapée au passage suivant)
        bilan["attente"] = "sauvegarde en cours"
        await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"attente": bilan["attente"]}})
        return bilan
    suivante = _iso(echeance_suivante(normaliser(cfg), echeance, maintenant))
    # Verrou : seul le processus qui fait passer l'échéance lue à la suivante déclenche
    pris = await mr.db.migration_programmation.find_one_and_update(
        {"_id": DOC_ID, "actif": True, "prochaine_execution": cfg["prochaine_execution"]},
        {"$set": {"prochaine_execution": suivante, "attente": None, "dernier_declenchement": _iso(maintenant)}})
    if not pris:
        return bilan
    bilan["declenchee"] = await declencher({**cfg, "prochaine_execution": suivante}, maintenant)
    return bilan


_BOUCLE: Dict[str, Optional[asyncio.Task]] = {"tache": None}


async def _boucle() -> None:
    while True:
        try:
            await passage()
        except Exception:  # noqa: BLE001 — un passage raté n'arrête pas la boucle
            logger.warning("[migration-programmation] passage", exc_info=True)
        await asyncio.sleep(INTERVALLE)


def demarrer() -> None:
    """Lance la boucle du planificateur (une seule fois par processus ; au démarrage, hors preview)."""
    if _BOUCLE["tache"] is None or _BOUCLE["tache"].done():
        _BOUCLE["tache"] = asyncio.create_task(_boucle())
        logger.info("[migration-programmation] planificateur démarré (toutes les %d s)", INTERVALLE)


# ---------------------------------------------------------------------------
# Routes (Admin uniquement)
# ---------------------------------------------------------------------------
class ReglageIn(BaseModel):
    actif: bool = False
    tous_les: int = Field(1, ge=1, le=365)
    heure: str = "03:00"
    fuseau: str = "Africa/Ouagadougou"
    base: bool = True
    fichiers: bool = True
    medias: bool = True
    retention_jours: int = Field(14, ge=1, le=3650)
    garder_min: int = Field(3, ge=1, le=100)
    purge_manuelles: bool = True
    rapport_si_ok: bool = True
    modele_wa: str = Field("", max_length=120)
    modele_wa_langue: str = Field("fr", max_length=12)


class IdentifiantsIn(BaseModel):
    mongo_uri: str = Field("", max_length=2000)
    mongo_db: str = Field("sawali", max_length=60)
    r2_account_id: str = Field(..., min_length=4)
    r2_access_key_id: str = Field(..., min_length=4)
    r2_secret_access_key: str = Field(..., min_length=4)
    r2_bucket: str = Field(..., min_length=3, max_length=63)


def _etat_public(cfg: Dict[str, Any], ids_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Réponse de l'API : réglage, état, identifiants SANS leur contenu."""
    return {"reglage": {k: cfg.get(k, v) for k, v in DEFAUT.items()},
            "prochaine_execution": cfg.get("prochaine_execution") if cfg.get("actif") else None,
            "attente": cfg.get("attente"), "derniere_execution": cfg.get("derniere_execution"),
            "derniere_purge": cfg.get("derniere_purge"), "maj_le": cfg.get("maj_le"), "maj_par": cfg.get("maj_par"),
            "identifiants": _identifiants_publics(ids_doc),
            "secrets_programmes": False, "explication_secrets": EXPLICATION_SECRETS}


async def _etat() -> Dict[str, Any]:
    return _etat_public(await lire_reglage(),
                        await mr.db.migration_programmation.find_one({"_id": IDENTIFIANTS_ID}))


@router.get("")
async def lire(_: dict = Depends(get_current_admin)):
    return await _etat()


@router.put("")
async def enregistrer(corps: ReglageIn, admin: dict = Depends(get_current_admin)):
    """Enregistre le réglage ; (re)calcule la prochaine exécution si la programmation est activée
    ou si son heure, sa fréquence ou son fuseau changent."""
    try:
        cfg = normaliser(corps.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    avant = await lire_reglage()
    ids_doc = await mr.db.migration_programmation.find_one({"_id": IDENTIFIANTS_ID})
    if cfg["actif"] and not ids_doc:
        raise HTTPException(400, "Enregistrez d'abord les identifiants des sauvegardes programmées")
    if cfg["actif"] and cfg["base"] and "mongo_uri" not in (ids_doc.get("champs") or []):
        raise HTTPException(400, "Base demandée : les identifiants enregistrés n'ont pas d'URI Atlas")
    prochaine = avant.get("prochaine_execution")
    change = any(avant.get(k) != cfg[k] for k in ("actif", "tous_les", "heure", "fuseau"))
    if not cfg["actif"]:
        prochaine = None
    elif change or not prochaine:
        prochaine = _iso(premiere_echeance(cfg, _maintenant()))
    await mr.db.migration_programmation.update_one(
        {"_id": DOC_ID}, {"$set": {**cfg, "prochaine_execution": prochaine, "attente": None,
                                   "maj_le": _iso(_maintenant()), "maj_par": admin.get("email", "")}}, upsert=True)
    return await _etat()


@router.put("/identifiants")
async def enregistrer_identifiants(corps: IdentifiantsIn, admin: dict = Depends(get_current_admin)):
    """« Utiliser ces identifiants pour les sauvegardes programmées » : connexions vérifiées, puis
    identifiants chiffrés par la clé du serveur. Jamais renvoyés au navigateur."""
    try:
        _materiau_cle()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    if corps.mongo_uri:
        client = None
        try:
            client = mr._client_cible(corps.mongo_uri)
            await client.admin.command("ping")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Connexion à MongoDB Atlas impossible : {str(exc)[:200]}")
        finally:
            try:
                if client is not None:
                    client.close()
            except Exception:  # noqa: BLE001
                pass
    r2 = mr._client_r2(corps.r2_account_id, corps.r2_access_key_id, corps.r2_secret_access_key)
    try:
        await asyncio.to_thread(r2.head_bucket, Bucket=corps.r2_bucket)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Accès au bucket R2 « {corps.r2_bucket} » impossible : {str(exc)[:200]}")
    valeurs = {k: v for k, v in corps.model_dump().items() if v}
    enveloppe = await asyncio.to_thread(chiffrer_serveur, json.dumps(valeurs).encode())
    await mr.db.migration_programmation.replace_one(
        {"_id": IDENTIFIANTS_ID},
        {"_id": IDENTIFIANTS_ID, "enveloppe": enveloppe, "cree_le": _iso(_maintenant()), "par": admin.get("email", ""),
         "champs": sorted(valeurs), "mongo_hote": mr._hote(corps.mongo_uri) if corps.mongo_uri else None,
         "mongo_db": corps.mongo_db, "r2_bucket": corps.r2_bucket},
        upsert=True)
    return await _etat()


@router.delete("/identifiants")
async def oublier_identifiants(_: dict = Depends(get_current_admin)):
    """Efface les identifiants et arrête la programmation (elle ne pourrait plus s'exécuter)."""
    await mr.db.migration_programmation.delete_one({"_id": IDENTIFIANTS_ID})
    await mr.db.migration_programmation.update_one({"_id": DOC_ID},
                                                   {"$set": {"actif": False, "prochaine_execution": None}})
    return await _etat()


@router.post("/lancer", status_code=202)
async def lancer_maintenant(admin: dict = Depends(get_current_admin)):
    """« Lancer maintenant avec ces réglages » : sauvegarde immédiate (rapport et purge ensuite),
    sans changer la prochaine exécution programmée."""
    reglage = await lire_reglage()
    try:
        cfg = normaliser(reglage)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    cfg["prochaine_execution"] = reglage.get("prochaine_execution") if cfg["actif"] else None
    res = await declencher(cfg, _maintenant(), lance_par=f"{admin.get('email', '')} (réglages programmés)")
    if not res["ok"]:
        raise HTTPException(400, res["erreur"])
    return res


@router.post("/purger")
async def purger_maintenant(_: dict = Depends(get_current_admin)):
    """« Purger maintenant » : applique la rétention tout de suite, puis envoie le rapport."""
    cfg = await lire_reglage()
    maintenant = _maintenant()
    try:
        resultat = await purger(maintenant, cfg=cfg)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Purge impossible : {str(exc)[:200]}")
    resultat["rapport"] = await envoyer_rapport("Purge des sauvegardes", texte_rapport_purge(resultat, cfg), cfg,
                                                important=bool(resultat["erreurs"]), maintenant=maintenant)
    await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"derniere_purge": resultat}})
    return resultat
