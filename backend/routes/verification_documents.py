# verification_documents.py — Lot 268 : AUTHENTICITÉ DES DOCUMENTS (QR code chiffré, vérifié uniquement sur SAWALI).
#
# Principe (demande du propriétaire, 20/10/2026) : chaque page d'un document officiel (ex. « Guide de prise en main ALBARKA »)
# porte un QR code. Le QR ne contient PAS d'information lisible : seulement un lien
#   https://sawalismartsystems.com/verifier-document?t=<jeton>
# où <jeton> est un message CHIFFRÉ (X25519 + HKDF-SHA256 + AES-GCM). Seul le serveur SAWALI possède la clé privée :
# lui seul peut déchiffrer. La page de vérification affiche alors, en clair, le titre, la version, le copyright, le numéro
# d'exemplaire et la page. Un jeton falsifié ou modifié est refusé (AES-GCM authentifie le contenu).
#
# Clés :
#   - la clé PRIVÉE est créée par SAWALI (bouton dans Paramètres), gardée CHIFFRÉE dans la collection existante `settings`
#     (même chiffrement que les clés d'e-mail, dérivé de JWT_SECRET) et n'est JAMAIS affichée ni exportée ;
#   - la clé PUBLIQUE (32 octets, sans danger) est affichée : elle sert au générateur du document à chiffrer les jetons.
# Aucune nouvelle collection (cluster plein) ; aucun appel externe ; réponse immédiate (règle 7).
from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from email_fournisseurs import chiffrer, dechiffrer

logger = logging.getLogger(__name__)

ID_DOC = "verification_documents"                 # document dans la collection `settings`
INFO_HKDF = b"SAWALI-verification-document-v1"     # étiquette de dérivation (identique côté générateur)
AAD = b"v1"
SEPARATEUR = "|"
TAILLE_JETON_MAX = 400                              # un jeton valide fait ~100 caractères
SITE_VERIFICATION = "https://sawalismartsystems.com/verifier-document"

# Documents reconnus : le jeton ne porte que le CODE, le titre et le copyright viennent de cette table.
DOCUMENTS: Dict[str, Dict[str, str]] = {
    "ALB-GUIDE": {"titre": "Guide de prise en main ALBARKA",
                  "droits": "© 2026, 2027, 2028 OUOBA Jean-François"},
}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


# ---------------------------------------------------------------------------
# Chiffrement (ECIES) : jeton = clé éphémère publique (32 octets) + AES-GCM(texte) — le tout en base64 « url-safe »
# ---------------------------------------------------------------------------
def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).decode().rstrip("=")


def _debase64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def _cle_et_nonce(secret_partage: bytes) -> tuple:
    """Dérive la clé AES (32 octets) et le nonce (12 octets) du secret partagé (la clé éphémère est unique à chaque jeton)."""
    sortie = HKDF(algorithm=hashes.SHA256(), length=44, salt=None, info=INFO_HKDF).derive(secret_partage)
    return sortie[:32], sortie[32:]


def sceller(cle_publique_b64: str, texte: str) -> str:
    """Chiffre `texte` pour le détenteur de la clé privée (utilisé par le générateur du document et par les tests)."""
    destinataire = X25519PublicKey.from_public_bytes(_debase64(cle_publique_b64))
    ephemere = X25519PrivateKey.generate()
    cle, nonce = _cle_et_nonce(ephemere.exchange(destinataire))
    chiffre = AESGCM(cle).encrypt(nonce, texte.encode("utf-8"), AAD)
    pub_eph = ephemere.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return _b64(pub_eph + chiffre)


def ouvrir(cle_privee: X25519PrivateKey, jeton: str) -> Optional[str]:
    """Déchiffre un jeton ; None s'il est illisible, modifié ou chiffré pour une autre clé."""
    try:
        brut = _debase64(jeton)
        if len(brut) < 32 + 16 + 1:
            return None
        cle, nonce = _cle_et_nonce(cle_privee.exchange(X25519PublicKey.from_public_bytes(brut[:32])))
        return AESGCM(cle).decrypt(nonce, brut[32:], AAD).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeDecodeError):
        return None


def _nouvelle_paire() -> Dict[str, str]:
    privee = X25519PrivateKey.generate()
    brute = privee.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    publique = privee.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"cle_privee": chiffrer(_b64(brute)), "cle_publique": _b64(publique)}


def _libelle_date(aaaammjj: str) -> str:
    """« 20261020 » → « 20 octobre 2026 » (texte d'origine si le format est inattendu)."""
    try:
        d = datetime.strptime(aaaammjj, "%Y%m%d")
        return f"{d.day} {MOIS[d.month - 1]} {d.year}"
    except ValueError:
        return aaaammjj


def lire_contenu(texte: str) -> Dict[str, Any]:
    """Texte clair « CODE|AAAAMMJJ|EXEMPLAIRE|pNN » → champs affichés par la page de vérification."""
    morceaux = texte.split(SEPARATEUR)
    code = morceaux[0] if morceaux else ""
    info = DOCUMENTS.get(code, {})
    page = (morceaux[3] if len(morceaux) > 3 else "").lstrip("p")
    return {
        "code": code,
        "titre": info.get("titre") or "Document non répertorié",
        "droits": info.get("droits") or "",
        "version": _libelle_date(morceaux[1]) if len(morceaux) > 1 else "",
        "exemplaire": morceaux[2] if len(morceaux) > 2 else "",
        "page": page,
    }


class GenererIn(BaseModel):
    remplacer: bool = False     # remplacer une paire existante INVALIDE tous les QR déjà imprimés


def make_verification_documents_router(*, db, get_super_admin) -> APIRouter:
    router = APIRouter()

    async def _doc() -> Dict[str, Any]:
        return await db.settings.find_one({"_id": ID_DOC}) or {}

    @router.get("/admin/verification-documents", tags=["Admin — Authenticité des documents"])
    async def etat(_: dict = Depends(get_super_admin)):
        """État de la clé (jamais la clé privée) : présence, clé publique à donner au générateur, date de création."""
        d = await _doc()
        return {"cree": bool(d.get("cle_privee")), "cle_publique": d.get("cle_publique") or "",
                "cree_le": d.get("cree_le"), "site_verification": SITE_VERIFICATION,
                "documents": [{"code": c, **i} for c, i in DOCUMENTS.items()]}

    @router.post("/admin/verification-documents/generer", tags=["Admin — Authenticité des documents"])
    async def generer(data: GenererIn, user: dict = Depends(get_super_admin)):
        """Crée la paire de clés. Si elle existe déjà, exige `remplacer` (les anciens QR deviendraient illisibles)."""
        d = await _doc()
        if d.get("cle_privee") and not data.remplacer:
            raise HTTPException(status_code=409, detail="Une paire de clés existe déjà : la remplacer rendrait tous les QR déjà imprimés invérifiables.")
        paire = _nouvelle_paire()
        await db.settings.update_one({"_id": ID_DOC}, {"$set": {**paire, "cree_le": datetime.now(timezone.utc).isoformat(),
                                                               "cree_par": user.get("email") or ""}}, upsert=True)
        logger.info("[verification-documents] paire de clés créée par %s (remplacement : %s)", user.get("email"), data.remplacer)
        return {"cree": True, "cle_publique": paire["cle_publique"]}

    @router.get("/public/verifier-document", tags=["Public"])
    async def verifier(t: str = Query(..., max_length=TAILLE_JETON_MAX)):
        """Page publique de vérification (ouverte par le QR code) : déchiffre le jeton et renvoie le contenu EN CLAIR.
        Réponse identique pour tout jeton invalide (aucune information sur la cause)."""
        d = await _doc()
        brute = dechiffrer(d.get("cle_privee")) if d.get("cle_privee") else None
        texte = None
        if brute:
            texte = ouvrir(X25519PrivateKey.from_private_bytes(_debase64(brute)), t.strip())
        if texte is None:
            return {"authentique": False}
        return {"authentique": True, "texte_clair": texte, **lire_contenu(texte)}

    return router
