"""Lot 49 — Sauvegarde et transfert des données : export / import COMPLETS chiffrés,
restauration initiale d'un site neuf, sauvegarde automatique quotidienne vers Cloudflare R2.

Les instantanés existants (Admin → « Sauvegarde de la base (Snapshot) ») ne couvrent
qu'une liste fixe de 39 collections et restent sur le disque du serveur : ils ne sont pas
modifiés. Ce module ajoute un export « Tous les éléments » :

1. EXPORT COMPLET (Admin)
   - TOUTES les collections de la base (list_collection_names, sauf system.* et les
     collections de EXCLUES), avec leurs index (list_indexes) ;
   - documents en JSON étendu CANONIQUE (bson.json_util) : ObjectId, dates, Decimal128,
     binaires, entiers 32/64 bits… sont restitués avec leur type exact ;
   - archive ZIP chiffrée en flux (sauvegarde_format.py : AES-256-GCM par blocs de 1 Mo,
     clé scrypt dérivée d'une phrase secrète de 12 caractères au moins, détection de toute
     altération, signature HMAC par une clé dérivée de JWT_SECRET) ;
   - tâche de fond avec progression, téléchargement UNIQUE par un lien à usage unique,
     fichier effacé après le téléchargement ou au plus tard une heure après sa création.

   SECRETS : l'export complet contient les secrets rangés en base (jetons WhatsApp, SMTP,
   clés d'API du document `settings`, empreintes des mots de passe…), NON masqués. C'est le
   choix le plus sûr pour une restauration : un export masqué donnerait un site restauré
   incomplet, et masquer seulement `settings` ne protégerait pas le reste (comptes, données
   des clients). La protection est le chiffrement du fichier entier : sans la phrase, il est
   illisible. Le coffre-fort des secrets (lot existant) reste disponible à part.

2. IMPORT COMPLET (Admin)
   - « Base vide uniquement » : refusé si la base contient autre chose que ce que crée le
     démarrage (COLLECTIONS_DEMARRAGE), les journaux techniques remplis automatiquement
     (COLLECTIONS_TECHNIQUES, suffixes de journaux) et au plus UN compte (l'administrateur
     initial qui lance l'import) ;
   - « Remplacer » : il faut taper REMPLACER et son mot de passe ; chaque collection présente
     dans la sauvegarde est vidée puis rechargée (les collections absentes de la sauvegarde
     sont conservées) ;
   - le fichier est entièrement contrôlé (phrase, intégrité) AVANT toute écriture ;
   - insertion par lots, index recréés (un index texte est reconstruit depuis « weights »),
     rapport comparant les nombres de documents attendus et présents.

3. RESTAURATION INITIALE (page publique /restauration)
   Sur un site neuf (aucun compte), elle permet d'importer sans pouvoir se connecter. Contrôles,
   tous faits avant la moindre écriture : base sans aucun compte et sans données, JWT_SECRET
   défini et différent de la valeur de secours, phrase correcte, fichier intact ET signé par un
   serveur ayant le MÊME JWT_SECRET, identifiants d'un administrateur actif présents dans la
   sauvegarde (e-mail + mot de passe vérifié). Essais limités (TENTATIVES_MAX par 15 minutes).

4. SAUVEGARDE AUTOMATIQUE QUOTIDIENNE vers R2 (03:00 Africa/Abidjan, planificateur existant,
   donc jamais avec DISABLE_SCHEDULER=1 ni dans la preview)
   - phrase lue dans la variable SAUVEGARDE_AUTO_PHRASE (jamais en base ni dans les journaux) ;
     absente : sauvegarde automatique désactivée, alerte dans l'admin ;
   - R2 : variables R2_SAUVEGARDES_ACCOUNT_ID / _ACCESS_KEY_ID / _SECRET_ACCESS_KEY ; à défaut,
     les identifiants R2_STOCKS_* (même compte Cloudflare). Bucket : R2_SAUVEGARDES_BUCKET
     (« sawali-sauvegardes » par défaut), dossier R2_SAUVEGARDES_PREFIXE (« sauvegardes-completes/ ») ;
     le bucket des stocks n'est jamais utilisé par défaut : les sauvegardes contiennent toute la base ;
   - rétention : 7 quotidiennes + 4 hebdomadaires + 12 mensuelles ; seuls les objets dont le nom
     suit exactement « sawali-AAAAMMJJ-HHMMSS.sawali » sous le dossier peuvent être supprimés ;
   - rapport par e-mail (succès ou échec) avec l'envoi SMTP existant ;
   - alerte dans l'admin si la dernière sauvegarde réussie a plus de 26 heures ;
   - liste des sauvegardes R2 dans l'admin, avec « Restaurer » (mode Remplacer, mêmes garde-fous).

Suivi : collection `sauvegardes_completes` (tâches, état de la sauvegarde automatique, verrous),
exclue de l'export et jamais touchée par un import.

  GET    /api/admin/sauvegarde-complete/etat
  POST   /api/admin/sauvegarde-complete/export                 {phrase}
  GET    /api/admin/sauvegarde-complete/taches/{id}
  POST   /api/admin/sauvegarde-complete/taches/{id}/lien       lien de téléchargement à usage unique
  POST   /api/admin/sauvegarde-complete/import                 multipart : fichier, phrase, mode, confirmation, mot_de_passe
  GET    /api/admin/sauvegarde-complete/r2                     sauvegardes présentes dans R2
  POST   /api/admin/sauvegarde-complete/r2/lancer              sauvegarde automatique immédiate
  POST   /api/admin/sauvegarde-complete/r2/restaurer           {cle, phrase?, confirmation, mot_de_passe}
  GET    /api/sauvegarde-complete/telecharger/{id}?jeton=…     (sans connexion : le jeton suffit, une fois)
  GET    /api/public/restauration/etat
  POST   /api/public/restauration                              multipart : fichier, phrase, email, mot_de_passe
  GET    /api/public/restauration/suivi/{id}?jeton=…
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import secrets
import time
import zipfile
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from bson import json_util
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import sauvegarde_format as sf
from auth import get_current_admin, verify_password
from chemins import EXPORTS_DIR
from db import db

logger = logging.getLogger("sawali.sauvegarde_complete")
router = APIRouter(prefix="/admin/sauvegarde-complete", tags=["Sauvegarde complète"])
router_public = APIRouter(tags=["Sauvegarde complète"])

SUIVI = "sauvegardes_completes"  # tâches, état de la sauvegarde automatique, verrous
# Jamais exportées ni touchées par un import :
#  - le suivi de ce module ;
#  - le réglage des sauvegardes de migration programmées (lot 47) : un site restauré
#    ne doit pas hériter de la programmation (même règle que la migration) ;
#  - lot 50 : l'état de la maintenance de la plateforme (un site restauré ne démarre pas
#    « en maintenance ») et les sessions des comptes (un import « Remplacer » ne ferme pas la
#    session de l'Admin qui le suit ; sur un site restauré, chacun se reconnecte).
EXCLUES = frozenset({SUIVI, "migration_programmation", "maintenance_plateforme", "sessions_comptes"})
# Collections qu'un démarrage sur une base vide remplit tout seul (relevé sur une base vide) :
# réglages par défaut, contenus du site, configuration VIDAL, empreinte du déploiement.
COLLECTIONS_DEMARRAGE = frozenset({"settings", "contents", "vidal_sync_config", "app_deployments"})
# Journaux et contrôles techniques remplis automatiquement (planificateur, visites, traces)
COLLECTIONS_TECHNIQUES = frozenset({
    "auth_checks", "uptime_checks", "integration_health_checks", "llm_health_state", "wa_silence_alerts",
    "incidents", "api_traces", "visits", "access_logs", "error_registry",
})
SUFFIXES_JOURNAUX = ("_log", "_logs", "_traces", "_audit", "_journal")
COMPTES_TOLERES_IMPORT = 1  # « Base vide uniquement » : l'administrateur initial qui lance l'import

LOT_LECTURE = 500  # documents lus puis écrits dans l'archive par lot
LOT_INSERTION = 1000  # documents insérés par lot à l'import
DUREE_FICHIER = 3600  # un export est effacé au plus tard 1 h après sa création
DUREE_LIEN = 600  # un lien de téléchargement vaut 10 minutes, une seule fois
SILENCE_MAX = 900  # une tâche sans signe de vie depuis 15 min (serveur redémarré) est « Interrompue »
SEUIL_ALERTE_H = 26  # alerte si la dernière sauvegarde automatique réussie est plus ancienne
JOURNAL_MAX = 200
TENTATIVES_MAX = 10  # essais de restauration initiale par fenêtre
FENETRE_TENTATIVES = 900  # secondes
RETENTION = {"quotidiennes": 7, "hebdomadaires": 4, "mensuelles": 12}
HEURE_AUTO = "03:00 (Africa/Abidjan)"
CANONIQUE = json_util.CANONICAL_JSON_OPTIONS
RE_CLE = re.compile(r"sawali-(\d{8})-(\d{6})\.sawali")  # nom exact d'une sauvegarde automatique

# Envoi d'e-mail (configuré par server.py : email_service.send_email) et destinataire par défaut
_ENVOIS: Dict[str, Any] = {"email": None, "email_defaut": ""}
# Références fortes vers les tâches de fond (asyncio ne garde qu'une référence faible)
_TACHES: Dict[str, asyncio.Task] = {}
_TENTATIVES: deque = deque()


def configurer(*, envoyer_email: Optional[Callable[..., Awaitable[bool]]] = None, email_defaut: str = "") -> None:
    _ENVOIS["email"] = envoyer_email
    _ENVOIS["email_defaut"] = (email_defaut or "").strip()


def _maintenant() -> datetime:
    """Horloge (remplaçable en test)."""
    return datetime.now(timezone.utc)


def _iso(d: Optional[datetime] = None) -> str:
    return (d or _maintenant()).astimezone(timezone.utc).isoformat()


def _lire_date(valeur: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _cle_signature() -> Optional[bytes]:
    """Clé de signature des exports (dérivée de JWT_SECRET) ; None si le secret est absent ou par défaut."""
    return sf.cle_signature(os.environ.get("JWT_SECRET"))


def _taille_lisible(octets: Optional[int]) -> str:
    o = int(octets or 0)
    if o >= 1024 ** 3:
        return f"{o / 1024 ** 3:.2f} Go"
    if o >= 1024 ** 2:
        return f"{o / 1024 ** 2:.1f} Mo"
    return f"{o / 1024:.0f} Ko"


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
async def _collections() -> List[str]:
    """Collections réelles de la base (sans les vues ni system.*), hors EXCLUES."""
    try:
        noms = await db.list_collection_names(filter={"type": "collection"})
    except Exception:  # noqa: BLE001 — filtre non pris en charge (base simulée)
        noms = await db.list_collection_names()
    return sorted(n for n in noms if not n.startswith("system.") and n not in EXCLUES)


def toleree(nom: str) -> bool:
    """Collection qu'une base « vide » peut contenir (démarrage, journaux techniques)."""
    return nom in COLLECTIONS_DEMARRAGE or nom in COLLECTIONS_TECHNIQUES or nom.endswith(SUFFIXES_JOURNAUX)


async def etat_base() -> Dict[str, Any]:
    """Nombre de comptes, collections non vides tolérées et bloquantes."""
    comptes, bloquantes, tolerees = 0, [], []
    for nom in await _collections():
        n = await db[nom].count_documents({})
        if not n:
            continue
        if nom == "users":
            comptes = n
        elif toleree(nom):
            tolerees.append({"nom": nom, "documents": n})
        else:
            bloquantes.append({"nom": nom, "documents": n})
    return {"comptes": comptes, "bloquantes": bloquantes, "tolerees": tolerees}


def _refus_base_non_vide(etat: Dict[str, Any], comptes_max: int) -> Optional[str]:
    """Message de refus si la base n'est pas « vide » au sens du mode « Base vide uniquement »."""
    if etat["comptes"] > comptes_max:
        return (f"La base contient déjà {etat['comptes']} compte(s) : utilisez le mode « Remplacer »"
                if comptes_max else "La base contient déjà des comptes : restauration initiale impossible")
    if etat["bloquantes"]:
        liste = ", ".join(f"{c['nom']} ({c['documents']})" for c in etat["bloquantes"][:8])
        plus = "…" if len(etat["bloquantes"]) > 8 else ""
        return f"La base n'est pas vide : {liste}{plus}"
    return None


async def _lister_index(collection) -> List[Dict[str, Any]]:
    try:
        return [dict(i) async for i in collection.list_indexes()]
    except Exception:  # noqa: BLE001 — repli : index_information()
        infos = await collection.index_information()
        return [{"name": nom, **{k: v for k, v in info.items() if k != "key"}, "key": dict(info["key"])}
                for nom, info in infos.items()]


# ---------------------------------------------------------------------------
# Suivi des tâches
# ---------------------------------------------------------------------------
async def _nouvelle_tache(type_: str, auteur: str, **extra) -> str:
    tache_id = secrets.token_hex(8)
    await db[SUIVI].insert_one({
        "_id": tache_id, "id": tache_id, "type": type_, "statut": "EN_COURS", "etape": "Préparation",
        "auteur": auteur, "cree_le": _iso(), "battement": _iso(), "journal": [], "progression": {}, **extra,
    })
    return tache_id


async def _maj(tache_id: Optional[str], ligne: Optional[str] = None, **champs) -> None:
    if not tache_id:
        return
    maj: Dict[str, Any] = {"$set": {**champs, "battement": _iso()}}
    if ligne:
        maj["$push"] = {"journal": {"$each": [f"{_maintenant():%H:%M:%S} {ligne}"], "$slice": -JOURNAL_MAX}}
    try:
        await db[SUIVI].update_one({"_id": tache_id}, maj)
    except Exception:  # noqa: BLE001 — le suivi ne doit jamais faire échouer la tâche
        logger.exception("[sauvegarde-complete] suivi %s non mis à jour", tache_id)


def _lancer(tache_id: str, coro) -> None:
    """Lance une tâche de fond ; une exception imprévue la marque « Échec »."""
    async def enveloppe():
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            logger.exception("[sauvegarde-complete] tâche %s en échec", tache_id)
            await _maj(tache_id, f"Échec : {_motif(exc)}", statut="ECHEC", erreur=_motif(exc, 500),
                       termine_le=_iso())
        finally:
            _TACHES.pop(tache_id, None)
    _TACHES[tache_id] = asyncio.create_task(enveloppe())


def _vue_tache(doc: Optional[dict]) -> Optional[dict]:
    """Tâche renvoyée au navigateur : sans jeton ni chemin interne."""
    if not doc:
        return None
    return {k: v for k, v in doc.items() if k not in ("_id", "jeton_hash", "jeton_suivi_hash")}


async def _marquer_orphelines() -> None:
    """Tâche EN_COURS sans signe de vie (serveur redémarré) et absente de ce processus : « Interrompue »."""
    limite = _iso(_maintenant() - timedelta(seconds=SILENCE_MAX))
    async for t in db[SUIVI].find({"statut": "EN_COURS", "battement": {"$lt": limite}}, {"_id": 1}):
        if t["_id"] not in _TACHES:
            await db[SUIVI].update_one({"_id": t["_id"], "statut": "EN_COURS"}, {"$set": {
                "statut": "INTERROMPUE", "termine_le": _iso(),
                "erreur": "Tâche interrompue (serveur redémarré ?) : relancez-la."}})


async def _import_en_cours() -> bool:
    await _marquer_orphelines()
    return bool(await db[SUIVI].find_one({"type": {"$in": ["import", "restauration", "restauration_r2"]},
                                          "statut": "EN_COURS"}, {"_id": 1}))


# ---------------------------------------------------------------------------
# Fichiers d'export : effacement après 1 h, après le téléchargement
# ---------------------------------------------------------------------------
def _effacer(chemin: Path) -> None:
    try:
        chemin.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sauvegarde-complete] effacement de %s impossible : %s", chemin.name, exc)


async def _purger_exports() -> int:
    """Efface les exports et fichiers temporaires de plus d'une heure (même après un redémarrage)."""
    n = 0
    limite = time.time() - DUREE_FICHIER
    try:
        for f in EXPORTS_DIR.glob("*.sawali*"):
            if f.is_file() and f.stat().st_mtime < limite:
                _effacer(f)
                n += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sauvegarde-complete] purge des exports : %s", exc)
    await db[SUIVI].update_many({"type": "export", "fichier": {"$ne": None}, "expire_le": {"$lt": _iso()},
                                 "efface_le": None}, {"$set": {"efface_le": _iso(), "jeton_hash": None}})
    return n


def _programmer_effacement(tache_id: str, chemin: Path, delai: float) -> None:
    async def plus_tard():
        await asyncio.sleep(delai)
        _effacer(chemin)
        await _maj(tache_id, "Fichier effacé (délai d'une heure écoulé)", efface_le=_iso(), jeton_hash=None)
    t = asyncio.create_task(plus_tard())
    _TACHES[f"effacement-{tache_id}"] = t
    t.add_done_callback(lambda _t: _TACHES.pop(f"effacement-{tache_id}", None))


# ---------------------------------------------------------------------------
# EXPORT
# ---------------------------------------------------------------------------
def _serialiser(docs: List[dict]) -> bytes:
    return "".join(json_util.dumps(d, json_options=CANONIQUE, ensure_ascii=False) + "\n" for d in docs).encode("utf-8")


async def exporter(chemin: Path, phrase: str, signature: Optional[bytes], tache_id: Optional[str] = None) -> Dict[str, Any]:
    """Écrit l'export complet chiffré dans `chemin`. Renvoie le manifeste."""
    noms = await _collections()
    totaux = {}
    for nom in noms:
        try:
            totaux[nom] = await db[nom].estimated_document_count()
        except Exception:  # noqa: BLE001
            totaux[nom] = await db[nom].count_documents({})
    documents_total = sum(totaux.values())
    await _maj(tache_id, f"Export : {len(noms)} collections, environ {documents_total} documents",
               etape="Export des collections",
               progression={"collections_faites": 0, "collections_total": len(noms),
                            "documents": 0, "documents_total": documents_total})
    manifeste: Dict[str, Any] = {
        "format": "sawali-export-complet", "version": 1, "cree_le": _iso(),
        "base": os.environ.get("DB_NAME", ""), "application": os.environ.get("APP_VERSION", ""),
        "secrets_inclus": True, "signe": signature is not None, "exclues": sorted(EXCLUES),
        "collections": {},
    }

    def ouvrir():
        sortie = open(chemin, "wb")  # noqa: SIM115 — fermé plus bas
        try:
            os.chmod(chemin, 0o600)
        except OSError:
            pass
        ecrivain = sf.EcrivainChiffre(sortie, phrase, signature=signature)
        archive = zipfile.ZipFile(ecrivain, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6)
        return sortie, ecrivain, archive

    sortie, ecrivain, archive = await asyncio.to_thread(ouvrir)
    faits, documents, dernier = 0, 0, 0.0
    try:
        for nom in noms:
            entree = await asyncio.to_thread(archive.open, f"collections/{nom}.jsonl", "w", force_zip64=True)
            n, lot = 0, []
            async for doc in db[nom].find({}, batch_size=LOT_LECTURE):
                lot.append(doc)
                if len(lot) >= LOT_LECTURE:
                    await asyncio.to_thread(entree.write, await asyncio.to_thread(_serialiser, lot))
                    n += len(lot)
                    lot = []
                    if time.monotonic() - dernier > 2:
                        dernier = time.monotonic()
                        await _maj(tache_id, progression={"collection": nom, "collections_faites": faits,
                                                          "collections_total": len(noms),
                                                          "documents": documents + n, "documents_total": documents_total})
            if lot:
                await asyncio.to_thread(entree.write, await asyncio.to_thread(_serialiser, lot))
                n += len(lot)
            await asyncio.to_thread(entree.close)
            index = await _lister_index(db[nom])
            await asyncio.to_thread(archive.writestr, f"index/{nom}.json",
                                    json_util.dumps(index, json_options=CANONIQUE))
            manifeste["collections"][nom] = {"documents": n, "index": len(index)}
            faits += 1
            documents += n
        manifeste["total_documents"] = documents
        await asyncio.to_thread(archive.writestr, "manifeste.json",
                                json.dumps(manifeste, ensure_ascii=False, indent=1))

        def fermer():
            archive.close()
            ecrivain.close()
            sortie.close()
        await asyncio.to_thread(fermer)
    except BaseException:
        try:
            sortie.close()
        finally:
            _effacer(chemin)
        raise
    await _maj(tache_id, f"Export terminé : {faits} collections, {documents} documents",
               progression={"collections_faites": faits, "collections_total": len(noms),
                            "documents": documents, "documents_total": documents_total})
    return manifeste


def _nom_export(prefixe: str = "sawali-export") -> str:
    return f"{prefixe}-{_maintenant():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.sawali"


async def _tache_export(tache_id: str, phrase: str) -> None:
    await _purger_exports()
    nom = _nom_export()
    chemin = EXPORTS_DIR / nom
    manifeste = await exporter(chemin, phrase, _cle_signature(), tache_id)
    taille = chemin.stat().st_size
    expire = _maintenant() + timedelta(seconds=DUREE_FICHIER)
    await _maj(tache_id, f"Fichier prêt ({_taille_lisible(taille)}), à télécharger une seule fois avant "
                         f"{expire:%H:%M} UTC", statut="TERMINE", etape="Prêt à télécharger", fichier=nom,
               taille=taille, expire_le=_iso(expire), termine_le=_iso(), efface_le=None, telecharge_le=None,
               rapport={"collections": len(manifeste["collections"]), "documents": manifeste["total_documents"],
                        "signe": manifeste["signe"]})
    _programmer_effacement(tache_id, chemin, DUREE_FICHIER)


# ---------------------------------------------------------------------------
# IMPORT
# ---------------------------------------------------------------------------
def _lire_lot(flux, n: int) -> List[dict]:
    lot = []
    for ligne in flux:
        ligne = ligne.strip()
        if ligne:
            lot.append(json_util.loads(ligne, json_options=CANONIQUE))
            if len(lot) >= n:
                break
    return lot


def _chercher_admin(archive: zipfile.ZipFile, email: str, mot_de_passe: str) -> Optional[str]:
    """Message de refus, ou None si un administrateur ACTIF de la sauvegarde a ces identifiants."""
    email = (email or "").strip().lower()
    if not email or not mot_de_passe:
        return "E-mail et mot de passe d'un administrateur de la sauvegarde obligatoires"
    if "collections/users.jsonl" not in archive.namelist():
        return "La sauvegarde ne contient aucun compte"
    with archive.open("collections/users.jsonl") as brut:
        for ligne in io.TextIOWrapper(brut, encoding="utf-8"):
            if not ligne.strip():
                continue
            u = json_util.loads(ligne, json_options=CANONIQUE)
            if str(u.get("email") or "").strip().lower() != email:
                continue
            if u.get("role") == "admin" and u.get("account_status") == "active" \
                    and verify_password(mot_de_passe, str(u.get("password_hash") or "")):
                return None
            break
    return "Identifiants refusés : il faut l'e-mail et le mot de passe d'un administrateur actif de la sauvegarde"


async def importer(chemin: Path, phrase: str, mode: str, tache_id: Optional[str] = None, *,
                   exiger_signature: bool = False, identifiants: Optional[Dict[str, str]] = None,
                   comptes_max: int = COMPTES_TOLERES_IMPORT) -> Dict[str, Any]:
    """Contrôle tout le fichier, puis importe. Lève sf.ErreurSauvegarde (message clair) si un contrôle
    échoue : dans ce cas, RIEN n'a été écrit dans la base.
    mode « vide » : base vide exigée (voir etat_base) ; « remplacer » : collections vidées puis rechargées."""
    if mode not in ("vide", "remplacer"):
        raise sf.ErreurSauvegarde(f"Mode d'import inconnu : {mode}")
    await _maj(tache_id, "Contrôle du fichier (phrase, intégrité, signature)…", etape="Contrôle du fichier")
    lecteur = await asyncio.to_thread(sf.LecteurChiffre, str(chemin), phrase)
    try:
        signature = await asyncio.to_thread(lecteur.verifier, _cle_signature())
        await _maj(tache_id, f"Fichier intact ; signature : {signature}", signature=signature)
        if exiger_signature and signature != "valide":
            raise sf.ErreurSauvegarde(
                "Signature refusée : le fichier doit venir d'un serveur SAWALI qui a le même JWT_SECRET que celui-ci")
        archive = await asyncio.to_thread(zipfile.ZipFile, lecteur)
        try:
            manifeste = json.loads(await asyncio.to_thread(archive.read, "manifeste.json"))
        except KeyError as exc:
            raise sf.FichierAltere("Manifeste absent : ce n'est pas un export complet") from exc
        if manifeste.get("format") != "sawali-export-complet":
            raise sf.ErreurSauvegarde("Ce fichier n'est pas un export complet SAWALI")
        noms = sorted(n for n in (manifeste.get("collections") or {}) if n not in EXCLUES and not n.startswith("system."))
        presentes = set(archive.namelist())
        manquantes = [n for n in noms if f"collections/{n}.jsonl" not in presentes]
        if manquantes:
            raise sf.FichierAltere(f"Archive incomplète : {', '.join(manquantes[:5])} absente(s)")
        if identifiants is not None:
            refus = await asyncio.to_thread(_chercher_admin, archive, identifiants.get("email", ""),
                                            identifiants.get("mot_de_passe", ""))
            if refus:
                raise sf.ErreurSauvegarde(refus)
            await _maj(tache_id, "Identifiants de l'administrateur vérifiés dans la sauvegarde")
        if mode == "vide":
            refus = _refus_base_non_vide(await etat_base(), comptes_max)
            if refus:
                raise sf.ErreurSauvegarde(refus)
        total = sum(int(manifeste["collections"][n].get("documents") or 0) for n in noms)
        await _maj(tache_id, f"Import ({'base vide' if mode == 'vide' else 'remplacement'}) : {len(noms)} "
                             f"collections, {total} documents", etape="Import des collections",
                   progression={"collections_faites": 0, "collections_total": len(noms),
                                "documents": 0, "documents_total": total})
        # --- À partir d'ici seulement, la base est modifiée ---
        comparaisons, documents, dernier = [], 0, 0.0
        for i, nom in enumerate(noms):
            attendus = int(manifeste["collections"][nom].get("documents") or 0)
            coll = db[nom]
            await coll.drop()
            inseres, erreurs = 0, []
            flux = io.TextIOWrapper(await asyncio.to_thread(archive.open, f"collections/{nom}.jsonl"), encoding="utf-8")
            try:
                while True:
                    lot = await asyncio.to_thread(_lire_lot, flux, LOT_INSERTION)
                    if not lot:
                        break
                    try:
                        res = await coll.insert_many(lot, ordered=False)
                        inseres += len(res.inserted_ids)
                    except Exception as exc:  # noqa: BLE001 — les documents valides du lot sont insérés
                        details = getattr(exc, "details", None) or {}
                        inseres += int(details.get("nInserted") or 0) if isinstance(details, dict) else 0
                        erreurs.append(str(exc)[:200])
                    documents += len(lot)
                    if time.monotonic() - dernier > 2:
                        dernier = time.monotonic()
                        await _maj(tache_id, progression={"collection": nom, "collections_faites": i,
                                                          "collections_total": len(noms),
                                                          "documents": documents, "documents_total": total})
            finally:
                flux.close()
            # Index
            index_attendus, index_recrees = 0, 0
            try:
                specs = json_util.loads(await asyncio.to_thread(archive.read, f"index/{nom}.json"),
                                        json_options=CANONIQUE)
            except KeyError:
                specs = []
            for spec in specs:
                cles_options = sf.cles_et_options_index(spec)
                if cles_options is None:
                    continue
                index_attendus += 1
                try:
                    await coll.create_index(cles_options[0], **cles_options[1])
                    index_recrees += 1
                except Exception as exc:  # noqa: BLE001
                    erreurs.append(f"index {spec.get('name')} : {str(exc)[:150]}")
            en_base = await coll.count_documents({})
            ok = en_base == attendus and index_recrees == index_attendus
            comparaisons.append({"collection": nom, "attendus": attendus, "inseres": inseres, "en_base": en_base,
                                 "index_attendus": index_attendus, "index_recrees": index_recrees, "ok": ok,
                                 "erreurs": erreurs[:5]})
            if not ok:
                await _maj(tache_id, f"  ✗ {nom} : {attendus} attendus, {en_base} en base, index "
                                     f"{index_recrees}/{index_attendus}")
        archive.close()
    finally:
        lecteur.close()
    anomalies = [c["collection"] for c in comparaisons if not c["ok"]]
    rapport = {"mode": mode, "collections": len(comparaisons), "documents_attendus": total,
               "documents_en_base": sum(c["en_base"] for c in comparaisons), "anomalies": anomalies,
               "comparaisons": comparaisons, "signature": signature, "export_du": manifeste.get("cree_le")}
    await _maj(tache_id, f"Import terminé : {len(comparaisons)} collections, {len(anomalies)} anomalie(s)",
               progression={"collections_faites": len(noms), "collections_total": len(noms),
                            "documents": documents, "documents_total": total})
    return rapport


async def _tache_import(tache_id: str, chemin: Path, phrase: str, mode: str, **options) -> None:
    # Un seul import à la fois (deux demandes simultanées ne peuvent pas écrire ensemble)
    if not await _prendre_verrou("verrou_import", 6 * 3600):
        _effacer(chemin)
        await _maj(tache_id, "Refusé : un autre import est en cours", statut="ECHEC", etape="Refusé",
                   erreur="Un autre import est déjà en cours", termine_le=_iso())
        return
    try:
        rapport = await importer(chemin, phrase, mode, tache_id, **options)
        await _maj(tache_id, statut="TERMINE" if not rapport["anomalies"] else "TERMINE_AVEC_ANOMALIES",
                   etape="Terminé", rapport=rapport, termine_le=_iso())
    except sf.ErreurSauvegarde as exc:
        await _maj(tache_id, f"Refusé : {exc}", statut="ECHEC", etape="Refusé", erreur=str(exc), termine_le=_iso())
    finally:
        _effacer(chemin)
        await _rendre_verrou("verrou_import")


async def _enregistrer_televersement(fichier: UploadFile, nom: str) -> Path:
    chemin = EXPORTS_DIR / nom
    with open(chemin, "wb") as sortie:
        try:
            os.chmod(chemin, 0o600)
        except OSError:
            pass
        while True:
            morceau = await fichier.read(1024 * 1024)
            if not morceau:
                break
            await asyncio.to_thread(sortie.write, morceau)
    return chemin


async def _controle_remplacer(admin: dict, confirmation: str, mot_de_passe: str) -> None:
    """Mode « Remplacer » : le mot REMPLACER et le mot de passe de l'administrateur connecté."""
    if (confirmation or "").strip() != "REMPLACER":
        raise HTTPException(400, "Tapez REMPLACER (en majuscules) pour confirmer le remplacement")
    doc = await db.users.find_one({"id": admin.get("id")}, {"_id": 0, "password_hash": 1})
    if not doc or not verify_password(mot_de_passe or "", str(doc.get("password_hash") or "")):
        raise HTTPException(403, "Mot de passe incorrect")


# ---------------------------------------------------------------------------
# R2 : configuration, rétention
# ---------------------------------------------------------------------------
def config_r2() -> Optional[Dict[str, str]]:
    """Identifiants R2 des sauvegardes : R2_SAUVEGARDES_*, à défaut ceux de R2_STOCKS_* (même compte
    Cloudflare). Le bucket est toujours R2_SAUVEGARDES_BUCKET (« sawali-sauvegardes » par défaut)."""
    def lire(nom: str) -> str:
        return (os.environ.get(nom) or "").strip()
    compte, cle, secret = (lire("R2_SAUVEGARDES_ACCOUNT_ID"), lire("R2_SAUVEGARDES_ACCESS_KEY_ID"),
                           lire("R2_SAUVEGARDES_SECRET_ACCESS_KEY"))
    source = "R2_SAUVEGARDES_*"
    if not (compte and cle and secret):
        compte, cle, secret = (lire("R2_STOCKS_ACCOUNT_ID"), lire("R2_STOCKS_ACCESS_KEY_ID"),
                               lire("R2_STOCKS_SECRET_ACCESS_KEY"))
        source = "R2_STOCKS_* (repli)"
    if not (compte and cle and secret):
        return None
    prefixe = lire("R2_SAUVEGARDES_PREFIXE").strip("/") or "sauvegardes-completes"
    return {"compte": compte, "cle": cle, "secret": secret, "source": source,
            "bucket": lire("R2_SAUVEGARDES_BUCKET") or "sawali-sauvegardes", "prefixe": prefixe + "/"}


def _motif(exc: BaseException, longueur: int = 300) -> str:
    """Lot 79.5 — motif d'une erreur, sans aucun jeton (une adresse R2 mal construite peut en contenir un)."""
    try:
        from masque_jetons import masquer
        return masquer(str(exc))[:longueur]
    except Exception:  # noqa: BLE001
        return type(exc).__name__


def _client_r2(cfg: Dict[str, str]):
    # Lot 79.5 — l'identifiant de compte Cloudflare fait 32 caractères hexadécimaux ; une autre valeur (souvent un
    # jeton d'API collé par erreur) est signalée clairement, sans être recopiée.
    if not re.fullmatch(r"[0-9a-fA-F]{32}", cfg.get("compte") or ""):
        variable = "R2_SAUVEGARDES_ACCOUNT_ID" if cfg.get("source") == "R2_SAUVEGARDES_*" else "R2_STOCKS_ACCOUNT_ID"
        raise RuntimeError(f"{variable} invalide : identifiant de compte Cloudflare attendu (32 caractères "
                           "hexadécimaux, visible dans Cloudflare → R2 → « Account ID »), pas un jeton d'API.")
    import boto3
    from botocore.config import Config as BotoConfig
    return boto3.client("s3", endpoint_url=f"https://{cfg['compte']}.r2.cloudflarestorage.com",
                        aws_access_key_id=cfg["cle"], aws_secret_access_key=cfg["secret"], region_name="auto",
                        config=BotoConfig(signature_version="s3v4", connect_timeout=30, read_timeout=120,
                                          retries={"max_attempts": 5}))


_FABRIQUE_R2: Dict[str, Callable] = {"client": _client_r2}  # remplaçable en test


def _phrase_auto() -> str:
    return (os.environ.get("SAUVEGARDE_AUTO_PHRASE") or "").strip()


def raison_auto_desactivee() -> Optional[str]:
    if not _phrase_auto():
        return "variable SAUVEGARDE_AUTO_PHRASE absente"
    if len(_phrase_auto()) < sf.PHRASE_MIN:
        return f"SAUVEGARDE_AUTO_PHRASE trop courte ({sf.PHRASE_MIN} caractères au minimum)"
    if config_r2() is None:
        return "Cloudflare R2 non configuré (R2_SAUVEGARDES_* ou R2_STOCKS_*)"
    return None


def date_de_cle(cle: str) -> Optional[datetime]:
    """Date d'une sauvegarde d'après son nom ; None si le nom ne suit pas exactement le motif."""
    m = RE_CLE.fullmatch(cle.rsplit("/", 1)[-1])
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def retention(cles: List[str], quotidiennes: int = RETENTION["quotidiennes"],
              hebdomadaires: int = RETENTION["hebdomadaires"], mensuelles: int = RETENTION["mensuelles"]) -> Dict[str, Any]:
    """Rotation 7 quotidiennes + 4 hebdomadaires + 12 mensuelles (la plus récente de chaque jour,
    semaine ISO et mois). Renvoie {"garder": {clé: [raisons]}, "supprimer": [clés]}.
    Une clé dont le nom ne suit pas exactement le motif n'est JAMAIS supprimée."""
    datees = sorted(((date_de_cle(c), c) for c in cles if date_de_cle(c)), reverse=True)
    garder: Dict[str, List[str]] = {}
    for libelle, periode, nombre in (("quotidienne", lambda d: d.date(), quotidiennes),
                                     ("hebdomadaire", lambda d: tuple(d.isocalendar())[:2], hebdomadaires),
                                     ("mensuelle", lambda d: (d.year, d.month), mensuelles)):
        vues = set()
        for d, c in datees:
            p = periode(d)
            if p in vues:
                continue
            if len(vues) >= nombre:
                break
            vues.add(p)
            garder.setdefault(c, []).append(libelle)
    if datees and datees[0][1] not in garder:
        garder[datees[0][1]] = ["la plus récente"]  # toujours conservée, quel que soit le réglage
    return {"garder": garder, "supprimer": [c for _, c in datees if c not in garder]}


def _lister_r2(client, cfg: Dict[str, str]) -> List[Dict[str, Any]]:
    objets, jeton = [], None
    while True:
        args = {"Bucket": cfg["bucket"], "Prefix": cfg["prefixe"]}
        if jeton:
            args["ContinuationToken"] = jeton
        page = client.list_objects_v2(**args)
        for o in page.get("Contents", []) or []:
            objets.append({"cle": o["Key"], "taille": int(o.get("Size") or 0)})
        if not page.get("IsTruncated"):
            return objets
        jeton = page.get("NextContinuationToken")


def _appliquer_retention(client, cfg: Dict[str, str]) -> Dict[str, Any]:
    objets = _lister_r2(client, cfg)
    decision = retention([o["cle"] for o in objets])
    a_supprimer = [c for c in decision["supprimer"] if c.startswith(cfg["prefixe"])]
    for i in range(0, len(a_supprimer), 1000):
        client.delete_objects(Bucket=cfg["bucket"], Delete={"Objects": [{"Key": c} for c in a_supprimer[i:i + 1000]],
                                                             "Quiet": True})
    return {"conservees": len(decision["garder"]), "supprimees": len(a_supprimer)}


# ---------------------------------------------------------------------------
# Sauvegarde automatique
# ---------------------------------------------------------------------------
async def _prendre_verrou(nom: str, duree_s: int) -> bool:
    maintenant = _iso()
    try:
        await db[SUIVI].find_one_and_update(
            {"_id": nom, "$or": [{"jusqu_a": {"$lt": maintenant}}, {"jusqu_a": {"$exists": False}}]},
            {"$set": {"jusqu_a": _iso(_maintenant() + timedelta(seconds=duree_s))}}, upsert=True)
        return True
    except Exception:  # noqa: BLE001 — clé en double : verrou déjà pris
        return False


async def _rendre_verrou(nom: str) -> None:
    await db[SUIVI].update_one({"_id": nom}, {"$set": {"jusqu_a": _iso(_maintenant() - timedelta(seconds=1))}})


async def _destinataire() -> str:
    s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "auto_snapshot_email_to": 1, "health_email_to": 1}) or {}
    for adresse in (s.get("auto_snapshot_email_to"), s.get("health_email_to"), _ENVOIS["email_defaut"]):
        if adresse and "@" in str(adresse):
            return str(adresse).strip()
    return ""


async def _rapport_email(ok: bool, details: Dict[str, Any]) -> bool:
    envoyer = _ENVOIS.get("email")
    adresse = await _destinataire()
    if not envoyer or not adresse:
        logger.warning("[sauvegarde-complete] rapport non envoyé (envoi e-mail ou destinataire absent)")
        return False
    sujet = (f"[SAWALI] Sauvegarde quotidienne réussie — {details.get('date', '')}" if ok
             else f"[SAWALI] ÉCHEC de la sauvegarde quotidienne — {details.get('date', '')}")
    lignes = [(k, v) for k, v in (
        ("Statut", "Réussie" if ok else "Échec"), ("Date", details.get("date")), ("Déclencheur", details.get("declencheur")),
        ("Durée", f"{details.get('duree_s', 0):.0f} s"), ("Collections", details.get("collections")),
        ("Documents", details.get("documents")), ("Taille", details.get("taille_lisible")),
        ("Bucket R2", details.get("bucket")), ("Fichier", details.get("cle")),
        ("Rétention", details.get("retention")), ("Erreur", details.get("erreur")),
        ("Prochaine sauvegarde", f"demain à {HEURE_AUTO}")) if v not in (None, "")]
    texte = "\n".join(f"{k} : {v}" for k, v in lignes)
    html = ("<div style=\"font-family:Arial,sans-serif\"><h2 style=\"color:#0E1F3D\">SAWALI — Sauvegarde quotidienne"
            "</h2><ul>" + "".join(f"<li><strong>{k}</strong> : {v}</li>" for k, v in lignes) +
            "</ul><p style=\"color:#64748B;font-size:12px\">Fichier chiffré par la phrase SAUVEGARDE_AUTO_PHRASE. "
            "Restauration : Paramètres → Sauvegarde / transfert des données.</p></div>")
    try:
        return bool(await envoyer(adresse, sujet, html, texte))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sauvegarde-complete] envoi du rapport impossible : %s", exc)
        return False


async def sauvegarde_automatique(declencheur: str = "cron:quotidienne-03h") -> Dict[str, Any]:
    """Export complet chiffré par SAUVEGARDE_AUTO_PHRASE, envoyé dans R2, puis rétention et rapport."""
    debut = _maintenant()
    raison = raison_auto_desactivee()
    if raison:
        await db[SUIVI].update_one({"_id": "etat_auto"}, {"$set": {"derniere_tentative": {
            "le": _iso(debut), "statut": "DESACTIVEE", "raison": raison, "declencheur": declencheur}}}, upsert=True)
        logger.warning("[sauvegarde-complete] sauvegarde automatique désactivée : %s", raison)
        return {"statut": "DESACTIVEE", "raison": raison}
    if not await _prendre_verrou("verrou_auto", 3 * 3600):
        return {"statut": "DEJA_EN_COURS"}
    cfg = config_r2()
    tache_id = await _nouvelle_tache("auto", declencheur, bucket=cfg["bucket"])
    chemin = EXPORTS_DIR / _nom_export("auto")
    cle = f"{cfg['prefixe']}sawali-{debut:%Y%m%d-%H%M%S}.sawali"
    details: Dict[str, Any] = {"date": f"{debut:%d/%m/%Y %H:%M} UTC", "declencheur": declencheur,
                               "bucket": cfg["bucket"], "cle": cle}
    try:
        manifeste = await exporter(chemin, _phrase_auto(), _cle_signature(), tache_id)
        taille = chemin.stat().st_size
        await _maj(tache_id, f"Envoi vers R2 : {cfg['bucket']}/{cle} ({_taille_lisible(taille)})", etape="Envoi vers R2")
        client = _FABRIQUE_R2["client"](cfg)
        await asyncio.to_thread(client.upload_file, str(chemin), cfg["bucket"], cle,
                                ExtraArgs={"ContentType": "application/octet-stream"})
        tete = await asyncio.to_thread(client.head_object, Bucket=cfg["bucket"], Key=cle)
        if int(tete.get("ContentLength", -1)) != taille:
            raise sf.ErreurSauvegarde("La taille du fichier dans R2 ne correspond pas : envoi incomplet")
        await _maj(tache_id, "Rétention (7 quotidiennes, 4 hebdomadaires, 12 mensuelles)…", etape="Rétention")
        purge = await asyncio.to_thread(_appliquer_retention, client, cfg)
        duree = (_maintenant() - debut).total_seconds()
        details.update(collections=len(manifeste["collections"]), documents=manifeste["total_documents"],
                       taille=taille, taille_lisible=_taille_lisible(taille), duree_s=duree,
                       retention=f"{purge['conservees']} conservée(s), {purge['supprimees']} supprimée(s)")
        await db[SUIVI].update_one({"_id": "etat_auto"}, {"$set": {
            "derniere_reussite": {"le": _iso(), "cle": cle, "taille": taille, "duree_s": duree,
                                  "documents": manifeste["total_documents"], "declencheur": declencheur},
            "derniere_tentative": {"le": _iso(debut), "statut": "TERMINE", "declencheur": declencheur}}}, upsert=True)
        details["email_envoye"] = await _rapport_email(True, details)
        await _maj(tache_id, "Sauvegarde automatique terminée" + ("" if details["email_envoye"] else
                                                                   " (rapport e-mail non envoyé)"),
                   statut="TERMINE", etape="Terminé", termine_le=_iso(), rapport=details)
        return {"statut": "TERMINE", **details}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[sauvegarde-complete] sauvegarde automatique en échec")
        details.update(erreur=_motif(exc), duree_s=(_maintenant() - debut).total_seconds())
        await db[SUIVI].update_one({"_id": "etat_auto"}, {"$set": {
            "dernier_echec": {"le": _iso(), "erreur": _motif(exc), "declencheur": declencheur},
            "derniere_tentative": {"le": _iso(debut), "statut": "ECHEC", "declencheur": declencheur}}}, upsert=True)
        details["email_envoye"] = await _rapport_email(False, details)
        await _maj(tache_id, f"Échec : {_motif(exc)}", statut="ECHEC", etape="Échec", erreur=_motif(exc, 500),
                   termine_le=_iso(), rapport=details)
        return {"statut": "ECHEC", **details}
    finally:
        _effacer(chemin)
        await _rendre_verrou("verrou_auto")


async def etat_auto() -> Dict[str, Any]:
    doc = await db[SUIVI].find_one({"_id": "etat_auto"}, {"_id": 0}) or {}
    raison = raison_auto_desactivee()
    cfg = config_r2()
    reussite = doc.get("derniere_reussite") or {}
    age_h = None
    if reussite.get("le") and _lire_date(reussite["le"]):
        age_h = round((_maintenant() - _lire_date(reussite["le"])).total_seconds() / 3600, 1)
    if raison:
        alerte = f"Sauvegarde automatique désactivée : {raison}."
    elif age_h is None:
        alerte = "Aucune sauvegarde automatique réussie pour l'instant."
    elif age_h > SEUIL_ALERTE_H:
        alerte = f"La dernière sauvegarde automatique réussie date de {age_h:.0f} h (plus de {SEUIL_ALERTE_H} h)."
    else:
        alerte = None
    return {"active": raison is None, "raison": raison, "phrase_definie": bool(_phrase_auto()),
            "r2": ({"configure": True, "bucket": cfg["bucket"], "prefixe": cfg["prefixe"], "source": cfg["source"]}
                   if cfg else {"configure": False}),
            "heure": HEURE_AUTO, "retention": RETENTION, "seuil_alerte_h": SEUIL_ALERTE_H, "age_heures": age_h,
            "alerte": alerte, "derniere_reussite": reussite or None, "dernier_echec": doc.get("dernier_echec"),
            "derniere_tentative": doc.get("derniere_tentative")}


# ---------------------------------------------------------------------------
# Routes Admin
# ---------------------------------------------------------------------------
class DemandeExport(BaseModel):
    phrase: str = Field(..., min_length=sf.PHRASE_MIN, max_length=500)


class DemandeRestaurationR2(BaseModel):
    cle: str = Field(..., min_length=5, max_length=500)
    phrase: str = Field("", max_length=500)
    confirmation: str = ""
    mot_de_passe: str = ""


@router.get("/etat")
async def route_etat(_: dict = Depends(get_current_admin)):
    await _marquer_orphelines()
    await _purger_exports()
    taches = [_vue_tache(t) async for t in db[SUIVI].find({"type": {"$exists": True}}).sort("cree_le", -1).limit(10)]
    base = await etat_base()
    return {"auto": await etat_auto(), "taches": taches, "base": base, "signature_possible": _cle_signature() is not None,
            "exclues": sorted(EXCLUES), "phrase_min": sf.PHRASE_MIN, "duree_fichier_min": DUREE_FICHIER // 60,
            "import_vide_possible": _refus_base_non_vide(base, COMPTES_TOLERES_IMPORT) is None}


@router.post("/export")
async def route_export(corps: DemandeExport, admin: dict = Depends(get_current_admin)):
    if await db[SUIVI].find_one({"type": "export", "statut": "EN_COURS"}, {"_id": 1}):
        await _marquer_orphelines()
        if await db[SUIVI].find_one({"type": "export", "statut": "EN_COURS"}, {"_id": 1}):
            raise HTTPException(409, "Un export complet est déjà en cours")
    tache_id = await _nouvelle_tache("export", admin.get("email") or "admin")
    _lancer(tache_id, _tache_export(tache_id, corps.phrase))
    return _vue_tache(await db[SUIVI].find_one({"_id": tache_id}))


@router.get("/taches/{tache_id}")
async def route_tache(tache_id: str, _: dict = Depends(get_current_admin)):
    await _marquer_orphelines()
    doc = await db[SUIVI].find_one({"_id": tache_id, "type": {"$exists": True}})
    if not doc:
        raise HTTPException(404, "Tâche introuvable")
    return _vue_tache(doc)


@router.post("/taches/{tache_id}/lien")
async def route_lien(tache_id: str, _: dict = Depends(get_current_admin)):
    """Lien de téléchargement à usage unique (10 min). Le fichier est effacé une fois téléchargé."""
    doc = await db[SUIVI].find_one({"_id": tache_id, "type": "export"})
    if not doc or doc.get("statut") != "TERMINE" or not doc.get("fichier"):
        raise HTTPException(404, "Aucun fichier prêt pour cet export")
    if doc.get("telecharge_le") or doc.get("efface_le") or not (EXPORTS_DIR / doc["fichier"]).exists():
        raise HTTPException(410, "Fichier déjà téléchargé ou effacé : relancez un export")
    jeton = secrets.token_urlsafe(32)
    await db[SUIVI].update_one({"_id": tache_id}, {"$set": {
        "jeton_hash": hashlib.sha256(jeton.encode()).hexdigest(),
        "jeton_expire": _iso(_maintenant() + timedelta(seconds=DUREE_LIEN))}})
    return {"url": f"/api/sauvegarde-complete/telecharger/{tache_id}?jeton={jeton}", "expire_dans_s": DUREE_LIEN}


@router.post("/import")
async def route_import(fichier: UploadFile = File(...), phrase: str = Form(...), mode: str = Form(...),
                       confirmation: str = Form(""), mot_de_passe: str = Form(""),
                       admin: dict = Depends(get_current_admin)):
    if mode not in ("vide", "remplacer"):
        raise HTTPException(400, "Mode inconnu : « vide » ou « remplacer »")
    if mode == "remplacer":
        await _controle_remplacer(admin, confirmation, mot_de_passe)
    else:
        refus = _refus_base_non_vide(await etat_base(), COMPTES_TOLERES_IMPORT)
        if refus:
            raise HTTPException(409, refus)
    if await _import_en_cours():
        raise HTTPException(409, "Un import est déjà en cours")
    tache_id = await _nouvelle_tache("import", admin.get("email") or "admin", mode=mode,
                                     nom_fichier=(fichier.filename or "")[:200])
    chemin = await _enregistrer_televersement(fichier, f"import-{tache_id}.sawali.part")
    _lancer(tache_id, _tache_import(tache_id, chemin, phrase, mode))
    return _vue_tache(await db[SUIVI].find_one({"_id": tache_id}))


@router.get("/r2")
async def route_r2(_: dict = Depends(get_current_admin)):
    cfg = config_r2()
    if not cfg:
        return {"configure": False, "elements": []}
    try:
        objets = await asyncio.to_thread(_lister_r2, _FABRIQUE_R2["client"](cfg), cfg)
    except Exception as exc:  # noqa: BLE001
        motif = _motif(exc, 200)
        logger.warning("[sauvegarde_complete] lecture R2 impossible (%s, %s) : %s", cfg["bucket"], cfg["source"], motif)
        raise HTTPException(502, f"Lecture de R2 impossible ({cfg['bucket']}) : {motif}")
    decision = retention([o["cle"] for o in objets])
    elements = []
    for o in objets:
        d = date_de_cle(o["cle"])
        elements.append({**o, "nom": o["cle"].rsplit("/", 1)[-1], "date": _iso(d) if d else None,
                         "taille_lisible": _taille_lisible(o["taille"]), "conservee": decision["garder"].get(o["cle"], [])})
    elements.sort(key=lambda e: e["date"] or "", reverse=True)
    return {"configure": True, "bucket": cfg["bucket"], "prefixe": cfg["prefixe"], "elements": elements}


@router.post("/r2/lancer")
async def route_r2_lancer(admin: dict = Depends(get_current_admin)):
    raison = raison_auto_desactivee()
    if raison:
        raise HTTPException(400, f"Sauvegarde automatique désactivée : {raison}")
    task = asyncio.create_task(sauvegarde_automatique(f"manuel:{admin.get('email') or 'admin'}"))
    _TACHES[f"auto-{id(task)}"] = task
    task.add_done_callback(lambda t: _TACHES.pop(f"auto-{id(t)}", None))
    return {"lance": True}


@router.post("/r2/restaurer")
async def route_r2_restaurer(corps: DemandeRestaurationR2, admin: dict = Depends(get_current_admin)):
    cfg = config_r2()
    if not cfg:
        raise HTTPException(400, "Cloudflare R2 non configuré")
    if not corps.cle.startswith(cfg["prefixe"]) or not date_de_cle(corps.cle):
        raise HTTPException(400, "Sauvegarde R2 inconnue")
    await _controle_remplacer(admin, corps.confirmation, corps.mot_de_passe)
    phrase = corps.phrase or _phrase_auto()
    if not phrase:
        raise HTTPException(400, "Phrase secrète requise (SAUVEGARDE_AUTO_PHRASE absente de ce serveur)")
    if await _import_en_cours():
        raise HTTPException(409, "Un import est déjà en cours")
    tache_id = await _nouvelle_tache("restauration_r2", admin.get("email") or "admin", mode="remplacer",
                                     nom_fichier=corps.cle)

    async def telecharger_puis_importer():
        chemin = EXPORTS_DIR / f"import-{tache_id}.sawali.part"
        try:
            await _maj(tache_id, f"Téléchargement depuis R2 : {corps.cle}", etape="Téléchargement depuis R2")
            client = _FABRIQUE_R2["client"](cfg)
            await asyncio.to_thread(client.download_file, cfg["bucket"], corps.cle, str(chemin))
        except Exception:
            _effacer(chemin)
            raise
        await _tache_import(tache_id, chemin, phrase, "remplacer")

    _lancer(tache_id, telecharger_puis_importer())
    return _vue_tache(await db[SUIVI].find_one({"_id": tache_id}))


# ---------------------------------------------------------------------------
# Routes sans connexion : téléchargement à usage unique, restauration initiale
# ---------------------------------------------------------------------------
@router_public.get("/sauvegarde-complete/telecharger/{tache_id}")
async def route_telecharger(tache_id: str, jeton: str = ""):
    if not jeton:
        raise HTTPException(403, "Lien invalide")
    doc = await db[SUIVI].find_one_and_update(
        {"_id": tache_id, "type": "export", "jeton_hash": hashlib.sha256(jeton.encode()).hexdigest(),
         "jeton_expire": {"$gt": _iso()}, "telecharge_le": None},
        {"$set": {"telecharge_le": _iso(), "jeton_hash": None}})
    if not doc:
        raise HTTPException(410, "Lien expiré ou déjà utilisé")
    chemin = EXPORTS_DIR / doc["fichier"]
    if not chemin.exists():
        raise HTTPException(410, "Fichier effacé : relancez un export")

    async def apres_envoi():
        _effacer(chemin)
        await _maj(tache_id, "Fichier téléchargé puis effacé du serveur", efface_le=_iso())

    return FileResponse(str(chemin), media_type="application/octet-stream", filename=doc["fichier"],
                        background=BackgroundTask(apres_envoi))


async def raison_restauration_impossible() -> Optional[str]:
    # Contrôle rapide d'abord (la page de connexion interroge cette route à chaque affichage)
    if await db.users.find_one({}, {"_id": 1}):
        return "le site contient déjà des comptes"
    if _cle_signature() is None:
        return "JWT_SECRET absent ou laissé à sa valeur par défaut sur ce serveur"
    if await _import_en_cours():
        return "Une restauration est déjà en cours"
    return _refus_base_non_vide(await etat_base(), 0)


def _compter_tentative() -> bool:
    """Vrai si une nouvelle tentative de restauration initiale est permise."""
    limite = time.monotonic() - FENETRE_TENTATIVES
    while _TENTATIVES and _TENTATIVES[0] < limite:
        _TENTATIVES.popleft()
    if len(_TENTATIVES) >= TENTATIVES_MAX:
        return False
    _TENTATIVES.append(time.monotonic())
    return True


@router_public.get("/public/restauration/etat")
async def route_restauration_etat():
    raison = await raison_restauration_impossible()
    return {"disponible": raison is None, "raison": raison}


@router_public.post("/public/restauration")
async def route_restauration(request: Request, fichier: UploadFile = File(...), phrase: str = Form(...),
                             email: str = Form(...), mot_de_passe: str = Form(...)):
    if not _compter_tentative():
        raise HTTPException(429, "Trop d'essais : réessayez dans 15 minutes")
    raison = await raison_restauration_impossible()
    if raison:
        raise HTTPException(403, f"Restauration initiale impossible : {raison}")
    jeton = secrets.token_urlsafe(24)
    from ip_client import ip_reelle   # lot 55 : fonction unique
    ip = ip_reelle(request)
    tache_id = await _nouvelle_tache("restauration", f"restauration initiale ({(email or '').strip().lower()[:120]})",
                                     mode="vide", ip=ip[:64], nom_fichier=(fichier.filename or "")[:200],
                                     jeton_suivi_hash=hashlib.sha256(jeton.encode()).hexdigest())
    chemin = await _enregistrer_televersement(fichier, f"import-{tache_id}.sawali.part")
    _lancer(tache_id, _tache_import(tache_id, chemin, phrase, "vide", exiger_signature=True,
                                    identifiants={"email": email, "mot_de_passe": mot_de_passe}, comptes_max=0))
    return {"id": tache_id, "jeton": jeton}


@router_public.get("/public/restauration/suivi/{tache_id}")
async def route_restauration_suivi(tache_id: str, jeton: str = ""):
    doc = await db[SUIVI].find_one({"_id": tache_id, "type": "restauration"})
    if not doc or not jeton or doc.get("jeton_suivi_hash") != hashlib.sha256(jeton.encode()).hexdigest():
        raise HTTPException(404, "Restauration introuvable")
    rapport = doc.get("rapport") or {}
    return {"statut": doc.get("statut"), "etape": doc.get("etape"), "progression": doc.get("progression"),
            "erreur": doc.get("erreur"), "journal": (doc.get("journal") or [])[-15:],
            "rapport": {k: rapport.get(k) for k in ("collections", "documents_attendus", "documents_en_base",
                                                    "anomalies")} if rapport else None}
