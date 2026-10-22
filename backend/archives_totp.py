"""archives_totp.py — Lot 279 : code à usage unique basé sur l'heure (TOTP, RFC 6238) pour les archives d'auRor.

Pour un développeur WinDev : c'est le même principe que les applications « Authenticator » (Google Authenticator, Microsoft Authenticator,
Aegis…) : un secret partagé (montré une fois sous forme de QR code) + l'heure donnent un code à 6 chiffres qui change toutes les 30 secondes.
Fonctions PURES (aucune base, aucun réseau), testées avec les vecteurs officiels de la RFC 6238.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from typing import Optional
from urllib.parse import quote

PERIODE_S = 30            # un nouveau code toutes les 30 secondes (valeur attendue par toutes les applications)
CHIFFRES = 6
FENETRE = 1               # tolérance : le pas précédent et le suivant (décalage d'horloge de ±30 s)


def nouveau_secret() -> str:
    """Secret aléatoire de 160 bits, en base32 sans « = » (format attendu par les applications d'authentification)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _octets(secret_b32: str) -> bytes:
    propre = secret_b32.strip().replace(" ", "").upper()
    return base64.b32decode(propre + "=" * (-len(propre) % 8))


def code_au_pas(secret_b32: str, pas: int, chiffres: int = CHIFFRES) -> str:
    """Code du pas de temps `pas` (HOTP, RFC 4226) : HMAC-SHA1 puis troncature dynamique."""
    mac = hmac.new(_octets(secret_b32), struct.pack(">Q", pas), hashlib.sha1).digest()
    decalage = mac[-1] & 0x0F
    valeur = struct.unpack(">I", mac[decalage:decalage + 4])[0] & 0x7FFFFFFF
    return str(valeur % (10 ** chiffres)).zfill(chiffres)


def pas_de(timestamp: float) -> int:
    return int(timestamp // PERIODE_S)


def verifier(secret_b32: str, code: str, timestamp: float, dernier_pas: Optional[int] = None) -> Optional[int]:
    """Renvoie le pas de temps qui correspond au code saisi, ou None. Un pas déjà utilisé (<= dernier_pas) est refusé : un code ne sert qu'une fois
    (protection contre le rejeu d'un code vu par-dessus l'épaule)."""
    code = "".join(c for c in str(code or "") if c.isdigit())
    if len(code) != CHIFFRES:
        return None
    courant = pas_de(timestamp)
    for pas in range(courant - FENETRE, courant + FENETRE + 1):
        if dernier_pas is not None and pas <= dernier_pas:
            continue
        if hmac.compare_digest(code_au_pas(secret_b32, pas), code):
            return pas
    return None


def uri_otpauth(secret_b32: str, compte: str, emetteur: str = "auRor") -> str:
    """Adresse « otpauth:// » que l'application d'authentification lit en scannant le QR code."""
    etiquette = quote(f"{emetteur}:{compte}", safe="")
    return f"otpauth://totp/{etiquette}?secret={secret_b32}&issuer={quote(emetteur)}&algorithm=SHA1&digits={CHIFFRES}&period={PERIODE_S}"
