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

6. LOT 48 — RAPPORTS ARCHIVÉS ET DESTINATAIRES DU BLOC
   - chaque rapport (sauvegarde programmée ou manuelle, échec au démarrage, purge) est archivé
     dans `migration_rapports` avec le journal de ses envois (routes/migration_rapports.py) ;
   - « Numéros WhatsApp du rapport » (`rapport_wa`) et « E-mails du rapport » (`rapport_emails`)
     du bloc passent AVANT les numéros / adresses repris des autres réglages ; vides = comme avant ;
   - chaque envoi garde le code d'erreur Meta et son explication en clair (131042 : paiement du
     compte WhatsApp Business, 131047 : hors fenêtre de 24 h...).

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
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union
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
EMAILS_MAX = 10  # adresses « E-mails du rapport » au plus
RE_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
# Clé de chiffrement de secours du code (auth.py) : jamais acceptée comme clé du coffre
CLE_DE_SECOURS = "fallback-insecure"

DEFAUT: Dict[str, Any] = {
    "actif": False, "tous_les": 1, "heure": "03:00", "fuseau": "Africa/Ouagadougou",
    "base": True, "fichiers": True, "medias": True,
    "retention_jours": 14, "garder_min": 3, "purge_manuelles": True,
    "rapport_si_ok": True, "modele_wa": "", "modele_wa_langue": "fr",
    # Lot 48 : destinataires propres au rapport (prioritaires s'ils sont remplis)
    "rapport_wa": [], "rapport_emails": [],
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
    numeros, emails = _verifier_destinataires(cfg.get("rapport_wa"), cfg.get("rapport_emails"))
    return {"actif": bool(cfg["actif"]), "tous_les": tous_les, "heure": heure, "fuseau": cfg["fuseau"],
            "base": bool(cfg["base"]), "fichiers": bool(cfg["fichiers"]), "medias": bool(cfg["medias"]),
            "retention_jours": retention, "garder_min": garder, "purge_manuelles": bool(cfg["purge_manuelles"]),
            "rapport_si_ok": bool(cfg["rapport_si_ok"]), "modele_wa": str(cfg["modele_wa"] or "").strip()[:120],
            "modele_wa_langue": str(cfg["modele_wa_langue"] or "fr").strip()[:12] or "fr",
            "rapport_wa": numeros, "rapport_emails": emails}


# ---------------------------------------------------------------------------
# Listes de destinataires (lot 48)
# ---------------------------------------------------------------------------
def _morceaux(brut: Any, separateurs: str) -> List[str]:
    """Liste ou texte (« a, b ; c ») -> éléments non vides, sans espaces autour."""
    elements = brut if isinstance(brut, (list, tuple)) else [brut]
    sortie: List[str] = []
    for e in elements:
        sortie += [m.strip() for m in re.split(separateurs, str(e or "")) if m.strip()]
    return sortie


def liste_numeros(brut: Any) -> List[str]:
    """Numéros WhatsApp (liste ou texte séparé par virgules) -> chiffres seuls, dédoublonnés.
    Les éléments trop courts (moins de 6 chiffres) sont écartés."""
    vus: List[str] = []
    for m in _morceaux(brut, r"[,;\n]+"):
        c = _chiffres(m)
        if len(c) >= 6 and c not in vus:
            vus.append(c)
    return vus


def liste_emails(brut: Any) -> List[str]:
    """Adresses e-mail (liste ou texte séparé par virgules, points-virgules ou espaces),
    dédoublonnées ; les éléments sans forme d'adresse sont écartés."""
    vues: List[str] = []
    for m in _morceaux(brut, r"[,;\s]+"):
        if RE_EMAIL.match(m) and m.lower() not in (v.lower() for v in vues):
            vues.append(m)
    return vues


def _verifier_destinataires(numeros: Any, emails: Any) -> tuple:
    """Champs du bloc -> (numéros, e-mails) propres ; ValueError avec un message clair si un
    élément est illisible ou s'il y en a trop."""
    for m in _morceaux(numeros, r"[,;\n]+"):
        if len(_chiffres(m)) < 6:
            raise ValueError(f"Numéro WhatsApp du rapport illisible : « {m} » (indicatif pays + numéro)")
    for m in _morceaux(emails, r"[,;\s]+"):
        if not RE_EMAIL.match(m):
            raise ValueError(f"E-mail du rapport illisible : « {m} »")
    n, e = liste_numeros(numeros), liste_emails(emails)
    if len(n) > DESTINATAIRES_WA_MAX:
        raise ValueError(f"Numéros WhatsApp du rapport : {DESTINATAIRES_WA_MAX} au plus")
    if len(e) > EMAILS_MAX:
        raise ValueError(f"E-mails du rapport : {EMAILS_MAX} au plus")
    return n, e


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
    return destinataires_rapport(reglages_globaux, {})["whatsapp"]


# Origine de chaque numéro / adresse par défaut, telle que l'admin la retrouve dans les Paramètres
SOURCES_WA = (
    ("liluvine_remote_admin_phones", "Jauge d'occupation du Support technique → Contrôle via WhatsApp "
                                     "(numéros autorisés)"),
    ("liluvine_escalation_wa_phone", "Liluvine PRO appelle l'admin quand elle est bloquée → numéro WhatsApp de l'admin"),
    ("llm_budget_notify_wa_phone", "Budget IA → Numéro WhatsApp de l'admin pour les alertes"),
    ("company_whatsapp", "Coordonnées de l'entreprise → WhatsApp"),
)
SOURCES_EMAIL = (
    ("auto_snapshot_email_to", "Sauvegarde de la base (Snapshot) → e-mail des sauvegardes automatiques"),
    ("health_email_to", "Santé applicative → Email destinataire"),
)
SOURCE_BLOC_WA = "champ « Numéros WhatsApp du rapport » de ce bloc"
SOURCE_BLOC_EMAIL = "champ « E-mails du rapport » de ce bloc"


def destinataires_rapport(globaux: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Destinataires du prochain rapport et leur origine (lot 48).
    WhatsApp : champ du bloc s'il est rempli, sinon le premier réglage renseigné de SOURCES_WA
    (les numéros autorisés de la Jauge peuvent être une liste ou un texte séparé par virgules).
    E-mail (repli si aucun WhatsApp n'est remis) : champ du bloc, sinon SOURCES_EMAIL, sinon
    l'adresse du super-administrateur."""
    numeros, source_wa = liste_numeros(cfg.get("rapport_wa")), SOURCE_BLOC_WA
    if not numeros:
        source_wa = None
        for cle, libelle in SOURCES_WA:
            numeros = liste_numeros(globaux.get(cle))
            if numeros:
                source_wa = libelle
                break
    emails, source_email = liste_emails(cfg.get("rapport_emails")), SOURCE_BLOC_EMAIL
    if not emails:
        source_email = None
        for cle, libelle in SOURCES_EMAIL:
            emails = liste_emails(globaux.get(cle))
            if emails:
                source_email = libelle
                break
    if not emails and liste_emails(_EMAIL_DEFAUT["adresse"]):
        emails, source_email = liste_emails(_EMAIL_DEFAUT["adresse"]), "adresse du super-administrateur (SUPER_ADMIN_EMAIL)"
    numeros = numeros[:DESTINATAIRES_WA_MAX]
    # Phrase affichée sous les champs du bloc : où partira le prochain rapport
    morceaux = []
    if numeros:
        morceaux.append(f"WhatsApp {', '.join('+' + n for n in numeros)} (source : {source_wa})")
    if emails:
        role = "e-mail de repli si aucun WhatsApp n'est remis" if numeros else "e-mail"
        morceaux.append(f"{role} {', '.join(emails)} (source : {source_email})")
    ligne = ("Le prochain rapport partira vers : " + " ; ".join(morceaux) if morceaux else
             "Aucun destinataire : renseignez les numéros WhatsApp ou les e-mails du rapport dans ce bloc")
    return {"whatsapp": numeros, "source_whatsapp": source_wa, "emails": emails, "source_email": source_email,
            "ligne": ligne}


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


# ---------------------------------------------------------------------------
# Erreurs Meta traduites en clair (lot 48)
# ---------------------------------------------------------------------------
ERREURS_META: Dict[int, str] = {
    131042: "Paiement du compte WhatsApp Business à régulariser chez Meta (moyen de paiement)",
    131047: "Hors fenêtre de 24 h : un modèle est nécessaire",
    470: "Hors fenêtre de 24 h : un modèle est nécessaire",
    132000: "Modèle : nombre de variables ou nom/langue incorrects",
    132001: "Modèle : nombre de variables ou nom/langue incorrects",
    132005: "Modèle : texte des variables trop long",
    132007: "Modèle : contenu refusé par la politique de Meta",
    132012: "Modèle : format des variables incorrect",
    132015: "Modèle mis en pause par Meta (qualité insuffisante)",
    132016: "Modèle désactivé par Meta",
    131026: "Numéro injoignable / pas sur WhatsApp",
    131051: "Type de message non pris en charge par WhatsApp",
    131049: "Message non remis par Meta pour préserver l'engagement : réessayez plus tard",
    131056: "Trop de messages envoyés à ce numéro en peu de temps : réessayez plus tard",
    131048: "Envoi limité par Meta (signalements ou qualité du numéro)",
    131031: "Compte WhatsApp Business verrouillé par Meta",
    131021: "Le destinataire est le numéro d'envoi lui-même",
    131008: "Paramètre obligatoire manquant",
    131009: "Valeur de paramètre incorrecte",
    131000: "Erreur passagère chez Meta : réessayez",
    131016: "Service WhatsApp momentanément indisponible : réessayez",
    130429: "Débit maximal d'envoi atteint : réessayez plus tard",
    130472: "Numéro du destinataire inclus dans une expérience Meta : message non remis",
    368: "Compte temporairement bloqué par Meta (non-respect de la politique)",
    190: "Jeton d'accès WhatsApp expiré ou invalide (Paramètres → WhatsApp)",
    100: "Paramètre invalide dans la requête envoyée à Meta",
}
RE_CODE_META = re.compile(r"\(#(\d{3,6})\)|\b(13\d{4}|470)\b")


def traduire_erreur_meta(code: Any, message: Any = None) -> tuple:
    """(code d'erreur Meta, message) -> (code entier ou None, explication en clair ou None).
    Sans code fourni, il est cherché dans le message (« (#131042) ... »)."""
    try:
        n = int(code) if code not in (None, "") else None
    except (TypeError, ValueError):
        n = None
    if n is None and message:
        m = RE_CODE_META.search(str(message))
        if m:
            n = int(m.group(1) or m.group(2))
    return n, ERREURS_META.get(n) if n is not None else None


# ---------------------------------------------------------------------------
# Envois unitaires, chacun décrit par une ligne du journal des envois (lot 48)
# ---------------------------------------------------------------------------
def _ligne_journal(canal: str, a: str, par: str, lot: str, maintenant: datetime, **champs) -> Dict[str, Any]:
    """Ligne du journal des envois. `etat` : accepte (Meta a pris le message ; son issue arrive
    plus tard par le webhook), envoye, remis, lu, echec."""
    return {"le": _iso(maintenant), "par": par, "lot": lot, "canal": canal, "a": a, "mode": None, "modele": None,
            "langue": None, "ok": False, "etat": "echec", "code": None, "erreur": None, "explication": None,
            "message_id": None, **champs}


async def envoyer_wa(numero: str, texte: str, *, modele: str = "", langue: str = "fr", par: str = "auto",
                     lot: str = "", maintenant: Optional[datetime] = None,
                     forcer_modele: bool = False) -> Dict[str, Any]:
    """Un WhatsApp : texte libre si le destinataire a écrit depuis moins de 24 h (sauf
    `forcer_modele`), sinon le modèle Meta indiqué avec le rapport en variable {{1}}.
    -> ligne du journal (jamais d'exception)."""
    maintenant = maintenant or _maintenant()
    ligne = _ligne_journal("whatsapp", numero, par, lot, maintenant)
    try:
        if not forcer_modele and _ENVOIS["texte"] and await _fenetre_ouverte(numero, maintenant):
            ligne["mode"] = "texte"
            r = await _ENVOIS["texte"](numero, texte)
        elif modele and _ENVOIS["modele"]:
            ligne.update(mode="modele", modele=modele, langue=langue or "fr")
            composants = [{"type": "body", "parameters": [{"type": "text", "text": _une_ligne(texte)}]}]
            r = await _ENVOIS["modele"](numero, modele, langue or "fr", composants)
        else:
            ligne.update(mode="aucun", erreur="hors fenêtre de 24 h et aucun modèle Meta réglé",
                         explication=ERREURS_META[131047])
            return ligne
    except Exception as exc:  # noqa: BLE001
        ligne.update(erreur=str(exc)[:200])
        return ligne
    r = r or {}
    if r.get("ok"):
        # Meta a accepté le message : un refus (ex. 131042) peut encore arriver par le webhook
        ligne.update(ok=True, etat="accepte" if r.get("message_id") else "envoye", message_id=r.get("message_id"))
    else:
        code, explication = traduire_erreur_meta(r.get("error_code"), r.get("error"))
        ligne.update(erreur=str(r.get("error") or "échec sans détail")[:300], code=code, explication=explication)
    return ligne


def html_rapport(sujet: str, texte: str) -> str:
    """Rapport en HTML lisible pour l'e-mail : titre, lignes « Libellé : valeur » en tableau,
    autres lignes en paragraphes."""
    lignes = [brute for brute in texte.splitlines() if brute.strip()]
    titre = html.escape(lignes[0] if lignes else sujet)
    corps = []
    for ligne in lignes[1:]:
        if " : " in ligne and not ligne.startswith("  "):
            cle, valeur = ligne.split(" : ", 1)
            corps.append(f"<tr><td style=\"padding:4px 12px 4px 0;color:#475569;vertical-align:top;white-space:nowrap\">"
                         f"{html.escape(cle)}</td><td style=\"padding:4px 0\"><b>{html.escape(valeur)}</b></td></tr>")
        else:
            corps.append(f"<tr><td colspan=\"2\" style=\"padding:4px 0\">{html.escape(ligne)}</td></tr>")
    return ("<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#0f172a\">"
            f"<h2 style=\"font-size:18px;margin:0 0 12px\">{titre}</h2>"
            f"<table style=\"border-collapse:collapse\">{''.join(corps)}</table>"
            "<p style=\"margin-top:16px;color:#64748b;font-size:12px\">Rapport archivé dans SAWALI : "
            "Paramètres → Migration vers Render → Historique → Rapport.</p></div>")


async def envoyer_email(adresse: str, sujet: str, texte: str, *, par: str = "auto", lot: str = "",
                        maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Un e-mail (SMTP existant, HTML lisible + texte) -> ligne du journal (jamais d'exception)."""
    ligne = _ligne_journal("email", adresse, par, lot, maintenant or _maintenant(), mode="smtp")
    try:
        envoi = _ENVOIS["email"]
        if envoi is None:
            from email_service import send_email as envoi
        ok = bool(await envoi(adresse, f"[SAWALI] {sujet}", html_rapport(sujet, texte), texte))
        ligne.update(ok=ok, etat="envoye" if ok else "echec", erreur=None if ok else "envoi SMTP refusé ou non configuré")
    except Exception as exc:  # noqa: BLE001
        ligne.update(erreur=str(exc)[:200])
    return ligne


async def envoyer_rapport(sujet: str, texte: str, cfg: Dict[str, Any], important: bool,
                          maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Envoie le rapport à l'admin. `important` (échec, anomalie, erreur de purge) : toujours envoyé ;
    sinon seulement si « M'envoyer le rapport même quand tout va bien » est coché.
    WhatsApp : texte dans la fenêtre de 24 h, sinon modèle Meta réglé (une variable {{1}}) ;
    e-mail (SMTP existant) si aucun WhatsApp n'est parti.
    Lot 48 : destinataires du bloc d'abord ; `envois` = lignes du journal (archivées avec le rapport)."""
    maintenant = maintenant or _maintenant()
    if not important and not cfg.get("rapport_si_ok", True):
        return {"envoye": False, "motif": "tout va bien : rapport non demandé", "envois": []}
    globaux = await mr.db.settings.find_one({"_id": "global"}) or {}
    dest = destinataires_rapport(globaux, cfg)
    lot = f"auto-{_iso(maintenant)}"
    resultat: Dict[str, Any] = {"envoye": False, "whatsapp": [], "email": None, "envois": []}
    for numero in dest["whatsapp"]:
        ligne = await envoyer_wa(numero, texte, modele=cfg.get("modele_wa") or "",
                                 langue=cfg.get("modele_wa_langue") or "fr", lot=lot, maintenant=maintenant)
        resultat["envois"].append(ligne)
        mode = {"modele": "modèle"}.get(ligne["mode"], ligne["mode"] or "erreur")
        resultat["whatsapp"].append({"a": numero, "mode": mode, "ok": ligne["ok"], "erreur": ligne["erreur"],
                                     "code": ligne["code"], "explication": ligne["explication"]})
    if any(w["ok"] for w in resultat["whatsapp"]):
        resultat["envoye"] = True
        return resultat
    # Repli : e-mail aux adresses du bloc (ou des sauvegardes, du rapport de santé, du super-admin)
    if dest["emails"]:
        lignes = [await envoyer_email(a, sujet, texte, lot=lot, maintenant=maintenant) for a in dest["emails"]]
        resultat["envois"] += lignes
        ok = any(x["ok"] for x in lignes)
        resultat["email"] = {"a": ", ".join(dest["emails"]), "ok": ok}
        if not ok:
            resultat["email"]["erreur"] = next((x["erreur"] for x in lignes if x["erreur"]), None)
        resultat["envoye"] = ok
    else:
        resultat["email"] = {"a": None, "ok": False, "erreur": "aucune adresse e-mail d'administration"}
    if not resultat["envoye"]:
        logger.warning("[migration-programmation] rapport non remis : %s",
                       {k: v for k, v in resultat.items() if k != "envois"})
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
                             prochaine: Optional[str], recalcule: bool = False) -> str:
    """Rapport d'une sauvegarde (signé Liluvine). Lot 48 : aussi pour une sauvegarde manuelle ;
    `recalcule` : rapport reconstitué plus tard depuis le suivi (prochaine exécution non connue)."""
    opts = job.get("options") or {}
    cible = job.get("cible") or {}
    genre = "programmée" if job.get("programmee") else f"manuelle (par {job.get('lance_par') or '—'})"
    lignes = ["🤖 Liluvine — Rapport de sauvegarde",
              f"Sauvegarde {genre} du {_local(job.get('debut'), cfg)} ({cfg['fuseau']})",
              f"Statut : {STATUTS_TEXTE.get(job.get('statut'), job.get('statut'))}",
              f"Durée : {_duree(job.get('debut'), job.get('fin'))}"]
    if opts.get("base"):
        lignes.append(f"Base : {job.get('collections_faites', 0)}/{job.get('collections_total', 0)} collections copiées "
                      f"({_nombre(job.get('documents_copies'))} documents)")
    if opts.get("fichiers"):
        lignes.append(f"Fichiers : {_nombre(job.get('fichiers_copies'))} copiés · {_nombre(job.get('fichiers_absents'))} "
                      f"absents à la source · {_nombre(job.get('fichiers_medias_ignores'))} médias ignorés · "
                      f"{_nombre(job.get('fichiers_echecs'))} vraies erreurs")
        exemples = (job.get("references_ignorees") or {}).get("exemples")
        if exemples:
            lignes.append(f"Références ignorées : {_nombre(exemples)} chemin(s) d'exemple cités dans des textes")
    lignes.append(f"Taille envoyée : {_taille((job.get('octets_archives') or 0) + (job.get('octets_fichiers') or 0))}")
    lignes.append(f"Emplacement R2 : {cible.get('r2_bucket')}/{cible.get('prefixe')}")
    if job.get("statut") not in REUSSIS and job.get("journal"):
        lignes.append(f"Dernière étape : {str(job['journal'][-1])[:300]}")
    if job.get("purgee"):
        lignes.append(f"Supprimée de R2 par la rétention le {_local(job.get('purgee_le'), cfg)}")
    lignes += _lignes_purge(purge)
    if recalcule:
        lignes.append("Prochaine exécution : non connue (rapport recalculé depuis le suivi de la sauvegarde)")
    else:
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
        from routes import migration_rapports as rap  # import tardif : ce module importe celui-ci
        sujet, texte = "Sauvegarde programmée : échec", texte_rapport_echec(erreur, maintenant, cfg,
                                                                            cfg.get("prochaine_execution"))
        archive = await rap.archiver("echec", sujet, texte, rap.donnees_echec(erreur, maintenant, cfg),
                                     important=True, maintenant=maintenant)
        rapport = await envoyer_rapport(sujet, texte, cfg, important=True, maintenant=maintenant)
        await rap.noter_envois(archive["id"], rapport.pop("envois", []), rapport.get("motif"))
        rapport["rapport_id"] = archive["id"]
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
    parti : purge (si réussie), puis rapport archivé et envoyé. Chaque sauvegarde est prise par
    un seul processus. Lot 48 : les sauvegardes MANUELLES terminées ont aussi leur rapport
    archivé (sans envoi automatique ni purge : envoi à la demande depuis l'Historique)."""
    from routes import migration_rapports as rap  # import tardif : ce module importe celui-ci
    manuelles = await mr.db.migration_jobs.find(
        {"programmee": {"$ne": True}, "statut": {"$in": list(FINAUX)}, "rapport_archive": False},
        {"_id": 0, "id": 1}).to_list(50)
    for j in manuelles:
        job = await mr.db.migration_jobs.find_one_and_update(
            {"id": j["id"], "rapport_archive": False}, {"$set": {"rapport_archive": True}},
            projection={"_id": 0, "secrets_chiffres": 0, "echecs_fichiers": 0, "absents_fichiers": 0,
                        "resultats_collections": 0})
        if job:
            cfg = await lire_reglage()
            await rap.archiver_sauvegarde(job, None, cfg, cfg.get("prochaine_execution") if cfg["actif"] else None,
                                          maintenant=maintenant)
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
        prochaine = cfg.get("prochaine_execution") if cfg["actif"] else None
        archive = await rap.archiver_sauvegarde(job, purge, cfg, prochaine, important=important, maintenant=maintenant)
        rapport = await envoyer_rapport(archive["sujet"], archive["texte"], cfg, important, maintenant)
        await rap.noter_envois(archive["id"], rapport.pop("envois", []), rapport.get("motif"))
        rapport["le"] = _iso(maintenant)
        rapport["rapport_id"] = archive["id"]
        await mr.db.migration_jobs.update_one({"id": job["id"]}, {"$set": {"rapport": rapport,
                                                                         "rapport_archive": True}})
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
    # Lot 48 : issue des WhatsApp acceptés par Meta (un refus comme 131042 arrive par le webhook ;
    # pour un envoi automatique, l'e-mail de repli est alors tenté)
    try:
        from routes import migration_rapports as rap  # import tardif : ce module importe celui-ci
        await rap.verifier_envois_en_attente(maintenant)
    except Exception:  # noqa: BLE001 — jamais bloquant pour la programmation
        logger.warning("[migration-programmation] vérification des envois", exc_info=True)
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
    # Lot 48 : destinataires du rapport (liste ou texte séparé par virgules ; vides = réglages repris)
    rapport_wa: Union[List[str], str] = Field(default_factory=list)
    rapport_emails: Union[List[str], str] = Field(default_factory=list)


class IdentifiantsIn(BaseModel):
    mongo_uri: str = Field("", max_length=2000)
    mongo_db: str = Field("sawali", max_length=60)
    r2_account_id: str = Field(..., min_length=4)
    r2_access_key_id: str = Field(..., min_length=4)
    r2_secret_access_key: str = Field(..., min_length=4)
    r2_bucket: str = Field(..., min_length=3, max_length=63)


def _etat_public(cfg: Dict[str, Any], ids_doc: Optional[Dict[str, Any]],
                 globaux: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Réponse de l'API : réglage, état, identifiants SANS leur contenu, et (lot 48) destinataires
    du prochain rapport avec leur source."""
    return {"reglage": {k: cfg.get(k, v) for k, v in DEFAUT.items()},
            "prochaine_execution": cfg.get("prochaine_execution") if cfg.get("actif") else None,
            "attente": cfg.get("attente"), "derniere_execution": cfg.get("derniere_execution"),
            "derniere_purge": cfg.get("derniere_purge"), "maj_le": cfg.get("maj_le"), "maj_par": cfg.get("maj_par"),
            "identifiants": _identifiants_publics(ids_doc),
            "secrets_programmes": False, "explication_secrets": EXPLICATION_SECRETS,
            "destinataires": destinataires_rapport(globaux or {}, cfg)}


async def _etat() -> Dict[str, Any]:
    return _etat_public(await lire_reglage(),
                        await mr.db.migration_programmation.find_one({"_id": IDENTIFIANTS_ID}),
                        await mr.db.settings.find_one({"_id": "global"}) or {})


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
    from routes import migration_rapports as rap  # import tardif : ce module importe celui-ci
    texte = texte_rapport_purge(resultat, cfg)
    archive = await rap.archiver("purge", "Purge des sauvegardes", texte, rap.donnees_purge(resultat),
                                 important=bool(resultat["erreurs"]), maintenant=maintenant)
    resultat["rapport"] = await envoyer_rapport("Purge des sauvegardes", texte, cfg,
                                                important=bool(resultat["erreurs"]), maintenant=maintenant)
    await rap.noter_envois(archive["id"], resultat["rapport"].pop("envois", []), resultat["rapport"].get("motif"))
    resultat["rapport"]["rapport_id"] = archive["id"]
    await mr.db.migration_programmation.update_one({"_id": DOC_ID}, {"$set": {"derniere_purge": resultat}})
    return resultat
