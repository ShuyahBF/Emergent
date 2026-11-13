"""Lot 379 — « Ma famille » (application Android Personnel de maison) : comptes, liens de vérification entre comptes, messagerie chiffrée.

PRINCIPES
- Pas de mot de passe : chaque téléphone reçoit à l'inscription un JETON SECRET (affiché une seule fois, gardé chiffré sur le téléphone) ;
  le serveur n'en conserve que l'empreinte SHA-256. Chaque appel porte l'identifiant du compte et le jeton.
- LIEN entre deux comptes : l'un crée une INVITATION (code à usage unique, valable 15 minutes), l'autre l'accepte. Le lien n'est « vérifié » que
  lorsque LES DEUX personnes ont comparé, de vive voix, le NUMÉRO DE SÉCURITÉ affiché par leur application (calculé côté téléphone à partir des deux
  clés publiques) et l'ont confirmé : cela garantit qu'aucun intermédiaire (même le serveur) n'a substitué une clé.
- MESSAGES : chiffrés DE BOUT EN BOUT sur les téléphones (AES-256-GCM, clé issue de l'échange ECDH des deux clés publiques) ; le serveur ne stocke
  et ne voit que du texte chiffré. Messagerie réservée aux liens vérifiés.
- Les collections (famille_comptes, famille_invitations, famille_liens, famille_messages) ne contiennent AUCUNE donnée du personnel ni du portefeuille.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

UTC = timezone.utc

INVITATION_VALIDITE_MIN = 15
ESSAIS_MAX_PAR_HEURE = 10            # codes d'invitation faux tolérés par compte et par heure (anti-devinette)
MESSAGE_MAX = 8000                   # taille maximale du texte chiffré (base64)
NOM_MAX = 60
ALPHABET_CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sans 0/O/1/I (lisible à voix haute)


def _maintenant() -> datetime:
    return datetime.now(UTC)


def empreinte_jeton(jeton: str) -> str:
    """SHA-256 du jeton (seule trace conservée côté serveur)."""
    return hashlib.sha256((jeton or "").encode()).hexdigest()


def nom_valide(nom: Any) -> str:
    n = re.sub(r"\s+", " ", str(nom or "")).strip()
    if len(n) < 2:
        raise ValueError("Saisissez votre nom (2 caractères au moins).")
    return n[:NOM_MAX]


def cle_publique_valide(cle: Any) -> str:
    """Clé publique EC (X.509, base64) : on vérifie seulement la forme (base64, longueur plausible) ; le serveur ne s'en sert jamais pour chiffrer."""
    c = str(cle or "").strip()
    try:
        brut = base64.b64decode(c, validate=True)
    except Exception:
        raise ValueError("Clé publique illisible.")
    if not 60 <= len(brut) <= 200:
        raise ValueError("Clé publique de taille invalide.")
    return c


def code_invitation() -> str:
    """Code de 8 caractères, tiré au hasard cryptographique, affiché « ABCD-EFGH »."""
    return "".join(secrets.choice(ALPHABET_CODE) for _ in range(8))


def normaliser_code(code: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


# --------------------------------------------------------------------------------------------------------------------
# Comptes
# --------------------------------------------------------------------------------------------------------------------
async def inscrire(db, nom: Any, cle_publique: Any) -> Dict[str, str]:
    """Crée un compte ; retourne {compte_id, jeton} (le jeton n'est jamais renvoyé ensuite)."""
    doc = {"_id": uuid.uuid4().hex, "nom": nom_valide(nom), "cle_publique": cle_publique_valide(cle_publique), "jeton_hash": None, "cree_le": _maintenant(), "echecs": []}
    jeton = secrets.token_urlsafe(32)
    doc["jeton_hash"] = empreinte_jeton(jeton)
    await db.famille_comptes.insert_one(doc)
    return {"compte_id": doc["_id"], "jeton": jeton}


async def authentifier(db, compte_id: Optional[str], jeton: Optional[str]) -> Optional[dict]:
    """Le compte si (identifiant, jeton) concordent, sinon None (comparaison à temps constant)."""
    if not compte_id or not jeton:
        return None
    compte = await db.famille_comptes.find_one({"_id": str(compte_id)})
    if not compte or not hmac.compare_digest(compte.get("jeton_hash") or "", empreinte_jeton(jeton)):
        return None
    return compte


# --------------------------------------------------------------------------------------------------------------------
# Invitations et liens
# --------------------------------------------------------------------------------------------------------------------
async def creer_invitation(db, compte: dict) -> Dict[str, Any]:
    """Nouvelle invitation (les précédentes non utilisées du même compte sont annulées : un seul code valide à la fois)."""
    await db.famille_invitations.delete_many({"compte_id": compte["_id"]})
    code = code_invitation()
    expire = _maintenant() + timedelta(minutes=INVITATION_VALIDITE_MIN)
    await db.famille_invitations.insert_one({"_id": code, "compte_id": compte["_id"], "expire_le": expire})
    return {"code": f"{code[:4]}-{code[4:]}", "expire_le": expire.isoformat(), "validite_minutes": INVITATION_VALIDITE_MIN}


async def _echec(db, compte: dict) -> None:
    """Note un code faux ; au-delà de ESSAIS_MAX_PAR_HEURE, les essais sont refusés (voir `essais_restants`)."""
    limite = time.time() - 3600
    recents = [t for t in compte.get("echecs", []) if t > limite] + [time.time()]
    await db.famille_comptes.update_one({"_id": compte["_id"]}, {"$set": {"echecs": recents}})


def essais_restants(compte: dict) -> int:
    limite = time.time() - 3600
    return ESSAIS_MAX_PAR_HEURE - len([t for t in compte.get("echecs", []) if t > limite])


async def accepter_invitation(db, compte: dict, code: Any) -> Dict[str, Any]:
    """L'invité entre le code de l'autre personne : crée le lien (statut « en attente de vérification »)."""
    if essais_restants(compte) <= 0:
        raise PermissionError("Trop de codes faux : réessayez dans une heure.")
    inv = await db.famille_invitations.find_one({"_id": normaliser_code(code)})
    if not inv or inv["expire_le"].replace(tzinfo=UTC) < _maintenant():
        await _echec(db, compte)
        raise LookupError("Code inconnu ou expiré.")
    if inv["compte_id"] == compte["_id"]:
        raise ValueError("Vous ne pouvez pas accepter votre propre invitation.")
    paire = sorted([inv["compte_id"], compte["_id"]])
    if await db.famille_liens.find_one({"comptes": paire}):
        await db.famille_invitations.delete_one({"_id": inv["_id"]})
        raise ValueError("Vous êtes déjà liés.")
    lien = {"_id": uuid.uuid4().hex, "comptes": paire, "verifie_par": [], "statut": "a_verifier", "cree_le": _maintenant()}
    await db.famille_liens.insert_one(lien)
    await db.famille_invitations.delete_one({"_id": inv["_id"]})       # usage unique
    return {"lien_id": lien["_id"]}


async def vue_lien(db, lien: dict, moi: str) -> Dict[str, Any]:
    """Un lien vu par `moi` : le correspondant (nom, clé publique) et l'état de vérification de chacun."""
    autre_id = next(c for c in lien["comptes"] if c != moi)
    autre = await db.famille_comptes.find_one({"_id": autre_id}, {"nom": 1, "cle_publique": 1}) or {}
    return {"lien_id": lien["_id"], "statut": lien["statut"], "correspondant": {"compte_id": autre_id, "nom": autre.get("nom", "?"), "cle_publique": autre.get("cle_publique", "")},
            "verifie_par_moi": moi in lien["verifie_par"], "verifie_par_lui": autre_id in lien["verifie_par"], "cree_le": lien["cree_le"].isoformat()}


async def lister_liens(db, compte: dict) -> List[Dict[str, Any]]:
    liens = await db.famille_liens.find({"comptes": compte["_id"]}).to_list(200)
    return [await vue_lien(db, l, compte["_id"]) for l in sorted(liens, key=lambda l: l["cree_le"])]


async def _lien_du_compte(db, compte: dict, lien_id: str) -> dict:
    lien = await db.famille_liens.find_one({"_id": str(lien_id), "comptes": compte["_id"]})
    if not lien:
        raise LookupError("Lien introuvable.")
    return lien


async def confirmer_verification(db, compte: dict, lien_id: str) -> Dict[str, Any]:
    """Je confirme avoir comparé le numéro de sécurité avec l'autre personne. Le lien devient « vérifié » quand les deux ont confirmé."""
    lien = await _lien_du_compte(db, compte, lien_id)
    if compte["_id"] not in lien["verifie_par"]:
        lien["verifie_par"].append(compte["_id"])
    statut = "verifie" if set(lien["verifie_par"]) == set(lien["comptes"]) else "a_verifier"
    await db.famille_liens.update_one({"_id": lien["_id"]}, {"$set": {"verifie_par": lien["verifie_par"], "statut": statut}})
    lien["statut"] = statut
    return await vue_lien(db, lien, compte["_id"])


async def supprimer_lien(db, compte: dict, lien_id: str) -> None:
    """Rompt le lien (l'un ou l'autre) et efface les messages échangés."""
    lien = await _lien_du_compte(db, compte, lien_id)
    await db.famille_messages.delete_many({"lien_id": lien["_id"]})
    await db.famille_liens.delete_one({"_id": lien["_id"]})


# --------------------------------------------------------------------------------------------------------------------
# Messagerie (texte chiffré de bout en bout)
# --------------------------------------------------------------------------------------------------------------------
async def envoyer_message(db, compte: dict, lien_id: str, nonce: Any, chiffre: Any) -> Dict[str, Any]:
    lien = await _lien_du_compte(db, compte, lien_id)
    if lien["statut"] != "verifie":
        raise PermissionError("Vérifiez d'abord le numéro de sécurité avec cette personne : la messagerie n'est ouverte qu'aux liens vérifiés.")
    n, c = str(nonce or ""), str(chiffre or "")
    if not n or not c:
        raise ValueError("Message vide.")
    if len(c) > MESSAGE_MAX or len(n) > 64:
        raise ValueError("Message trop long.")
    for morceau in (n, c):
        try:
            base64.b64decode(morceau, validate=True)
        except Exception:
            raise ValueError("Message mal formé (base64 attendu).")
    seq = time.time_ns()                    # curseur croissant pour « messages après tel numéro »
    await db.famille_messages.insert_one({"_id": uuid.uuid4().hex, "lien_id": lien["_id"], "de": compte["_id"], "nonce": n, "chiffre": c, "seq": seq, "cree_le": _maintenant()})
    return {"seq": seq}


async def lire_messages(db, compte: dict, lien_id: str, apres: int = 0, limite: int = 200) -> List[Dict[str, Any]]:
    """Messages du lien dont `seq` > `apres`, du plus ancien au plus récent."""
    lien = await _lien_du_compte(db, compte, lien_id)
    docs = await db.famille_messages.find({"lien_id": lien["_id"], "seq": {"$gt": int(apres or 0)}}).sort("seq", 1).to_list(max(1, min(limite, 500)))
    return [{"seq": d["seq"], "de": d["de"], "nonce": d["nonce"], "chiffre": d["chiffre"], "cree_le": d["cree_le"].isoformat()} for d in docs]


async def assurer_index(db) -> None:
    """Index utiles (règle 7) : messages par lien et curseur, liens par compte, invitations qui expirent."""
    await db.famille_messages.create_index([("lien_id", 1), ("seq", 1)])
    await db.famille_liens.create_index("comptes")
    await db.famille_invitations.create_index("expire_le", expireAfterSeconds=0)
