# loois_secrets_hfsql.py — Lot 79.11 : MOTS DE PASSE HFSQL remis à Loois par SAWALI (jamais en clair sur les postes).
#
# Demande du propriétaire (08/10/2026) : « Pourquoi ne pas en faire des paramètres dans SAWALI que pour une 1ère fois
# Loois va lire et stocker de son côté crypté ? » — le mot de passe du SERVEUR HFSQL (X) et celui des FICHIERS (Y) ne
# changent jamais ; ils ne doivent plus traîner en clair dans un fichier ou une variable d'environnement du poste.
#
# En résumé (pour un développeur WinDev) :
#   1. L'administrateur saisit X et Y UNE fois : Paramètres → « 🔐 Loois — mots de passe HFSQL ».
#      SAWALI les garde CHIFFRÉS (Fernet dérivé de JWT_SECRET, comme les clés e-mail) dans
#      db.loois_reglages {id: "secrets_hfsql"} — aucune nouvelle collection. L'écran ne les réaffiche JAMAIS :
#      il indique seulement « défini / non défini » ;
#   2. Loois, au premier besoin, appelle GET /api/loois/secrets-hfsql avec sa CLÉ CLIENT (en-tête X-Cle-Loois,
#      lot 68.1). La clé commune est REFUSÉE (seule une clé client identifie un établissement) ;
#   3. Loois stocke la réponse chiffrée sur le poste (DPAPI « machine ») et ne redemande plus ;
#   4. Chaque remise est notée (date, client, machine) : les 50 dernières sont visibles dans la rubrique.
from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request  # au niveau du module : l'annotation de la route doit être résolue (from __future__)

logger = logging.getLogger("sawali.loois_secrets_hfsql")

ID_DOC = "secrets_hfsql"
MAX_LIVRAISONS = 50          # historique des remises gardé dans le document (pas de nouvelle collection)
MAX_LONGUEUR = 200           # un mot de passe plus long est refusé (protection)


def _fernet() -> Fernet:
    """Clé stable dérivée de JWT_SECRET, avec une étiquette propre à cet usage (aucune variable de plus)."""
    secret = os.environ.get("JWT_SECRET") or "fallback-insecure-jwt"
    empreinte = hashlib.sha256(f"sawali-loois-secrets-hfsql::{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(empreinte))


def chiffrer(clair: Optional[str]) -> Optional[str]:
    """Texte chiffré, ou None pour une valeur vide."""
    if not clair:
        return None
    return _fernet().encrypt(clair.encode()).decode()


def dechiffrer(chiffre: Optional[str]) -> Optional[str]:
    """Texte clair, ou None si absent / illisible (JWT_SECRET changé : à saisir de nouveau)."""
    if not chiffre:
        return None
    try:
        return _fernet().decrypt(chiffre.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        logger.warning("[loois-secrets] mot de passe chiffré illisible (JWT_SECRET modifié ?) : à saisir de nouveau")
        return None


def etat_public(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ce que l'écran peut montrer : défini ou non, auteur, date, remises — JAMAIS les mots de passe."""
    doc = doc or {}
    return {
        "serveur_defini": bool(doc.get("mdp_serveur")),
        "fichiers_defini": bool(doc.get("mdp_fichiers")),
        "maj_le": doc.get("maj_le"),
        "maj_par": doc.get("maj_par"),
        "livraisons": list(reversed(doc.get("livraisons") or []))[:MAX_LIVRAISONS],
    }


def valeurs_a_enregistrer(corps: Any, existant: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Champs à écrire d'après la saisie de l'écran :
       - champ absent ou vide → valeur actuelle conservée (l'écran n'affiche jamais l'ancienne) ;
       - « effacer_serveur » / « effacer_fichiers » vrai → valeur supprimée ;
       - texte saisi → chiffré. Lève ValueError si trop long."""
    corps = corps if isinstance(corps, dict) else {}
    existant = existant or {}
    sortie: Dict[str, Any] = {}
    for champ, cle in (("serveur", "mdp_serveur"), ("fichiers", "mdp_fichiers")):
        if corps.get(f"effacer_{champ}"):
            sortie[cle] = None
            continue
        saisie = corps.get(f"mot_de_passe_{champ}")
        if isinstance(saisie, str) and saisie != "":
            if len(saisie) > MAX_LONGUEUR:
                raise ValueError(f"mot de passe {champ} trop long")
            sortie[cle] = chiffrer(saisie)
        else:
            sortie[cle] = existant.get(cle)
    return sortie


def setup_loois_secrets_hfsql_routes(*, db, api, get_current_user) -> None:
    """Routes : rubrique des Paramètres (admin) et remise à Loois (clé client)."""
    from fastapi import Depends, HTTPException
    from routes import loois_cles_clients as cles

    def admin(user: dict) -> None:
        if user.get("role") not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="Réservé aux administrateurs")

    @api.get("/admin/loois-secrets-hfsql", tags=["Loois clés clients"])
    async def etat(user: dict = Depends(get_current_user)):
        """État de la rubrique (défini / non défini, remises) — jamais les mots de passe."""
        admin(user)
        return etat_public(await db.loois_reglages.find_one({"id": ID_DOC}, {"_id": 0}))

    @api.put("/admin/loois-secrets-hfsql", tags=["Loois clés clients"])
    async def enregistrer(request: Request, user: dict = Depends(get_current_user)):
        """Enregistre les mots de passe saisis (chiffrés). Champ vide = inchangé."""
        admin(user)
        existant = await db.loois_reglages.find_one({"id": ID_DOC}, {"_id": 0})
        try:
            champs = valeurs_a_enregistrer(await request.json(), existant)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        champs.update({"maj_le": datetime.now(timezone.utc).isoformat(),
                       "maj_par": user.get("email") or user.get("name") or user.get("id")})
        await db.loois_reglages.update_one({"id": ID_DOC}, {"$set": champs}, upsert=True)
        return etat_public(await db.loois_reglages.find_one({"id": ID_DOC}, {"_id": 0}))

    @api.get("/loois/secrets-hfsql", tags=["Loois"])
    async def remettre(request: Request, machine: str = ""):
        """Remise à Loois des mots de passe HFSQL (HTTPS). CLÉ CLIENT obligatoire ; clé commune refusée."""
        identite = await cles.identifier_cle(db, request.headers.get("X-Cle-Loois"), machine=machine)
        if not identite or identite.get("type") != "client":
            raise HTTPException(status_code=401, detail="clé client Loois absente ou refusée", headers=cles.EN_TETE_REFUS)
        doc = await db.loois_reglages.find_one({"id": ID_DOC}, {"_id": 0}) or {}
        serveur, fichiers = dechiffrer(doc.get("mdp_serveur")), dechiffrer(doc.get("mdp_fichiers"))
        if serveur is None and fichiers is None:
            raise HTTPException(status_code=404, detail="mots de passe HFSQL non définis dans SAWALI (Paramètres)")
        # Remise notée (sans aucun mot de passe) — les 50 dernières seulement
        await db.loois_reglages.update_one({"id": ID_DOC}, {"$push": {"livraisons": {
            "$each": [{"le": datetime.now(timezone.utc).isoformat(), "client": identite.get("code"),
                       "machine": str(machine or "")[:80]}], "$slice": -MAX_LIVRAISONS}}})
        logger.info("[loois-secrets] remis au client %s (machine %s)", identite.get("code"), str(machine or "")[:80])
        return {"mot_de_passe_serveur": serveur or "", "mot_de_passe_fichiers": fichiers or ""}
