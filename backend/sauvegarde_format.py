"""Lot 49 — Format du fichier d'export complet chiffré (« .sawali »).

Le fichier contient une archive ZIP (une entrée par collection, en JSON étendu
canonique, plus les index et un manifeste), chiffrée EN FLUX, par blocs :

  en-tête   : MAGIC (14 octets) | version (1 octet) | longueur L (4 octets, gros-boutiste)
              | L octets de JSON (paramètres scrypt, sel, préfixe de nonce, taille des blocs,
              | vérificateur de phrase, présence d'une signature)
  blocs     : longueur C (4 octets) | C octets chiffrés (AES-256-GCM, étiquette de 16 octets)
              - tous les blocs sauf le dernier contiennent exactement `taille_bloc` octets clairs ;
              - nonce = préfixe aléatoire (7 octets) | numéro du bloc (4 octets) | drapeau
                « dernier bloc » (1 octet) : un bloc déplacé, supprimé ou une fin tronquée
                est détecté ;
              - données associées (AAD) = l'en-tête complet : un en-tête modifié est détecté.
  fin       : MAGIC_FIN (10 octets) | HMAC-SHA256 (32 octets) de tout ce qui précède,
              calculé avec une clé dérivée de JWT_SECRET (HKDF). 32 zéros si le serveur
              n'avait pas de JWT_SECRET sûr : le fichier est alors « non signé ».

Clé de chiffrement : scrypt(phrase, sel aléatoire de 16 octets, n=2^15, r=8, p=1) -> 32 octets.
Une phrase incorrecte est reconnue grâce au vérificateur (HMAC de la clé) sans rien déchiffrer ;
toute autre modification du fichier fait échouer le contrôle d'intégrité GCM ou la signature.

Lecture : `LecteurChiffre` est un fichier « seekable » en lecture : il déchiffre à la demande
le bloc voulu, ce qui permet à zipfile de lire l'archive sans jamais écrire de données en
clair sur le disque.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import struct
from datetime import datetime, timezone
from typing import Any, BinaryIO, Callable, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"SAWALI-EXPORT\x00"
MAGIC_FIN = b"SAWALI-FIN"
VERSION = 1
TAILLE_BLOC = 1024 * 1024  # 1 Mo de données claires par bloc
ETIQUETTE = 16  # étiquette GCM
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
LONGUEUR_FIN = len(MAGIC_FIN) + 32
PHRASE_MIN = 12  # caractères au minimum pour une phrase secrète
# Clé de secours du code (auth.py) : jamais utilisée pour signer
JWT_SECRET_DE_SECOURS = "fallback-insecure"


class ErreurSauvegarde(Exception):
    """Fichier illisible : message clair destiné à l'administrateur."""


class PhraseIncorrecte(ErreurSauvegarde):
    pass


class FichierAltere(ErreurSauvegarde):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _deb64(s: str) -> bytes:
    return base64.b64decode(s)


def deriver_cle(phrase: str, sel: bytes, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> bytes:
    return Scrypt(salt=sel, length=32, n=n, r=r, p=p).derive(phrase.encode("utf-8"))


def _verificateur(cle: bytes) -> str:
    return _b64(hmac.new(cle, b"sawali-export-complet:verification", hashlib.sha256).digest()[:16])


def cle_signature(jwt_secret: Optional[str]) -> Optional[bytes]:
    """Clé HMAC dérivée de JWT_SECRET ; None si le secret est absent ou est celui de secours."""
    jwt_secret = (jwt_secret or "").strip()
    if not jwt_secret or jwt_secret == JWT_SECRET_DE_SECOURS:
        return None
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"sawali-export-complet",
                info=b"signature-v1").derive(jwt_secret.encode("utf-8"))


def _nonce(prefixe: bytes, numero: int, dernier: bool) -> bytes:
    return prefixe + struct.pack(">I", numero) + (b"\x01" if dernier else b"\x00")


class EcrivainChiffre(io.RawIOBase):
    """Fichier en écriture seule qui chiffre au fil de l'eau ce qu'on lui écrit.
    `tell()` répond, `seek()` est refusé : zipfile écrit alors l'archive en continu."""

    def __init__(self, sortie: BinaryIO, phrase: str, signature: Optional[bytes] = None,
                 taille_bloc: int = TAILLE_BLOC, scrypt_n: int = SCRYPT_N):
        super().__init__()
        if len(phrase or "") < PHRASE_MIN:
            raise ErreurSauvegarde(f"Phrase secrète trop courte ({PHRASE_MIN} caractères au minimum)")
        self._sortie = sortie
        self._taille_bloc = taille_bloc
        sel, self._prefixe = os.urandom(16), os.urandom(7)
        cle = deriver_cle(phrase, sel, n=scrypt_n)
        self._aes = AESGCM(cle)
        self._signature = signature
        self._hmac = hmac.new(signature or b"\x00" * 32, digestmod=hashlib.sha256)
        entete_json = json.dumps({
            "format": "sawali-export-complet", "version": VERSION, "algo": "AES-256-GCM",
            "kdf": "scrypt", "n": scrypt_n, "r": SCRYPT_R, "p": SCRYPT_P, "sel": _b64(sel),
            "prefixe_nonce": _b64(self._prefixe), "taille_bloc": taille_bloc,
            "verificateur": _verificateur(cle), "signe": signature is not None,
            "cree_le": datetime.now(timezone.utc).isoformat(),
        }, sort_keys=True).encode("utf-8")
        self._entete = MAGIC + bytes([VERSION]) + struct.pack(">I", len(entete_json)) + entete_json
        self._ecrire_brut(self._entete)
        self._tampon = bytearray()
        self._numero = 0
        self._position = 0  # octets clairs reçus
        self._ferme = False

    def _ecrire_brut(self, donnees: bytes) -> None:
        self._sortie.write(donnees)
        self._hmac.update(donnees)

    def _emettre(self, clair: bytes, dernier: bool) -> None:
        chiffre = self._aes.encrypt(_nonce(self._prefixe, self._numero, dernier), clair, self._entete)
        self._ecrire_brut(struct.pack(">I", len(chiffre)) + chiffre)
        self._numero += 1

    # --- interface fichier ---
    def writable(self) -> bool:
        return True

    def write(self, donnees) -> int:  # type: ignore[override]
        if self._ferme:
            raise ValueError("fichier chiffré déjà fermé")
        donnees = bytes(donnees)
        self._tampon += donnees
        self._position += len(donnees)
        # On garde toujours au moins un bloc incomplet (ou plein) pour le « dernier bloc »
        while len(self._tampon) > self._taille_bloc:
            self._emettre(bytes(self._tampon[:self._taille_bloc]), False)
            del self._tampon[:self._taille_bloc]
        return len(donnees)

    def tell(self) -> int:
        return self._position

    def seek(self, *args, **kwargs):  # noqa: ARG002
        raise io.UnsupportedOperation("écriture chiffrée en continu : seek impossible")

    def seekable(self) -> bool:
        return False

    def flush(self) -> None:
        self._sortie.flush()

    def close(self) -> None:
        if not self._ferme:
            self._emettre(bytes(self._tampon), True)
            self._tampon = bytearray()
            empreinte = self._hmac.digest() if self._signature else b"\x00" * 32
            self._sortie.write(MAGIC_FIN + empreinte)
            self._sortie.flush()
            self._ferme = True
        super().close()


def lire_entete(f: BinaryIO) -> tuple:
    """(octets de l'en-tête, paramètres) ; lève ErreurSauvegarde si ce n'est pas un export SAWALI."""
    f.seek(0)
    debut = f.read(len(MAGIC) + 5)
    if len(debut) < len(MAGIC) + 5 or not debut.startswith(MAGIC):
        raise ErreurSauvegarde("Ce fichier n'est pas un export complet SAWALI (.sawali)")
    if debut[len(MAGIC)] != VERSION:
        raise ErreurSauvegarde(f"Version de fichier non prise en charge ({debut[len(MAGIC)]})")
    longueur = struct.unpack(">I", debut[len(MAGIC) + 1:])[0]
    if longueur > 64 * 1024:
        raise FichierAltere("En-tête du fichier invalide")
    brut = f.read(longueur)
    try:
        params = json.loads(brut.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FichierAltere("En-tête du fichier illisible") from exc
    return debut + brut, params


class LecteurChiffre(io.RawIOBase):
    """Lecture « seekable » d'un export chiffré : chaque bloc est déchiffré (et contrôlé) à la demande."""

    def __init__(self, chemin: str, phrase: str):
        super().__init__()
        self._f = open(chemin, "rb")  # noqa: SIM115 — fermé par close()
        try:
            self._entete, p = lire_entete(self._f)
            self.params = p
            self._taille_bloc = int(p["taille_bloc"])
            self._prefixe = _deb64(p["prefixe_nonce"])
            cle = deriver_cle(phrase or "", _deb64(p["sel"]), n=int(p["n"]), r=int(p["r"]), p=int(p["p"]))
        except ErreurSauvegarde:
            self._f.close()
            raise
        except Exception as exc:  # noqa: BLE001 — en-tête incomplet ou modifié
            self._f.close()
            raise FichierAltere("En-tête du fichier invalide") from exc
        if not hmac.compare_digest(_verificateur(cle), str(p.get("verificateur", ""))):
            self._f.close()
            raise PhraseIncorrecte("Phrase secrète incorrecte")
        self._aes = AESGCM(cle)
        taille_fichier = os.fstat(self._f.fileno()).st_size
        zone = taille_fichier - len(self._entete) - LONGUEUR_FIN
        self._enreg = self._taille_bloc + ETIQUETTE + 4
        if zone < ETIQUETTE + 4:
            self._f.close()
            raise FichierAltere("Fichier incomplet (tronqué)")
        self._nb_blocs = -(-zone // self._enreg)
        dernier = zone - (self._nb_blocs - 1) * self._enreg
        if dernier < ETIQUETTE + 4:
            self._f.close()
            raise FichierAltere("Fichier incomplet (tronqué)")
        self._taille_claire = (self._nb_blocs - 1) * self._taille_bloc + (dernier - ETIQUETTE - 4)
        self._fin_blocs = len(self._entete) + zone
        self._pos = 0
        self._cache = (-1, b"")

    # --- contrôle complet ---
    def verifier(self, signature: Optional[bytes] = None,
                 progression: Optional[Callable[[int, int], None]] = None) -> str:
        """Déchiffre tous les blocs (intégrité) et contrôle la signature.
        Renvoie « valide », « absente » (fichier non signé), « invalide » (autre serveur ou fichier
        modifié par quelqu'un qui connaît la phrase) ou « non_verifiable » (ce serveur n'a pas de clé)."""
        for i in range(self._nb_blocs):
            self._bloc(i, garder=False)
            if progression and (i % 16 == 0 or i == self._nb_blocs - 1):
                progression(i + 1, self._nb_blocs)
        self._f.seek(self._fin_blocs)
        fin = self._f.read(LONGUEUR_FIN)
        if len(fin) != LONGUEUR_FIN or not fin.startswith(MAGIC_FIN):
            raise FichierAltere("Fin du fichier absente ou modifiée")
        empreinte = fin[len(MAGIC_FIN):]
        if empreinte == b"\x00" * 32 or not self.params.get("signe"):
            return "absente"
        if signature is None:
            return "non_verifiable"
        h = hmac.new(signature, digestmod=hashlib.sha256)
        self._f.seek(0)
        reste = self._fin_blocs
        while reste > 0:
            morceau = self._f.read(min(reste, 1024 * 1024))
            if not morceau:
                break
            h.update(morceau)
            reste -= len(morceau)
        return "valide" if hmac.compare_digest(h.digest(), empreinte) else "invalide"

    def _bloc(self, i: int, garder: bool = True) -> bytes:
        if self._cache[0] == i:
            return self._cache[1]
        self._f.seek(len(self._entete) + i * self._enreg)
        longueur_brute = self._f.read(4)
        if len(longueur_brute) != 4:
            raise FichierAltere("Fichier incomplet (tronqué)")
        longueur = struct.unpack(">I", longueur_brute)[0]
        attendu = self._enreg - 4 if i < self._nb_blocs - 1 else None
        if (attendu is not None and longueur != attendu) or longueur > self._enreg - 4:
            raise FichierAltere("Structure des blocs modifiée")
        chiffre = self._f.read(longueur)
        try:
            clair = self._aes.decrypt(_nonce(self._prefixe, i, i == self._nb_blocs - 1), chiffre, self._entete)
        except InvalidTag as exc:
            raise FichierAltere("Fichier altéré ou incomplet (contrôle d'intégrité en échec)") from exc
        if garder:
            self._cache = (i, clair)
        return clair

    # --- interface fichier ---
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, decalage: int, origine: int = 0) -> int:
        if origine == 0:
            self._pos = decalage
        elif origine == 1:
            self._pos += decalage
        else:
            self._pos = self._taille_claire + decalage
        self._pos = max(0, self._pos)
        return self._pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self._taille_claire - self._pos
        morceaux = []
        while n > 0 and self._pos < self._taille_claire:
            i, debut = divmod(self._pos, self._taille_bloc)
            bloc = self._bloc(i)
            morceau = bloc[debut:debut + n]
            if not morceau:
                break
            morceaux.append(morceau)
            self._pos += len(morceau)
            n -= len(morceau)
        return b"".join(morceaux)

    def readinto(self, tampon) -> int:
        donnees = self.read(len(tampon))
        tampon[:len(donnees)] = donnees
        return len(donnees)

    def close(self) -> None:
        try:
            self._f.close()
        finally:
            super().close()


# ---------------------------------------------------------------------------
# Index : description renvoyée par list_indexes -> arguments de create_index
# ---------------------------------------------------------------------------
OPTIONS_INDEX = ("unique", "sparse", "expireAfterSeconds", "partialFilterExpression", "collation",
                 "weights", "default_language", "language_override", "textIndexVersion",
                 "2dsphereIndexVersion", "bits", "min", "max", "wildcardProjection", "hidden")


def cles_et_options_index(info: Dict[str, Any]) -> Optional[tuple]:
    """(clés, options) pour recréer un index ; None pour l'index _id (créé d'office).
    Un index TEXTE est décrit par MongoDB avec les clés internes « _fts / _ftsx » : ses
    champs sont reconstruits depuis « weights » (les autres clés du composé restent à leur place)."""
    nom = info.get("name")
    if nom == "_id_":
        return None
    cle = list((info.get("key") or {}).items())
    if any(k == "_fts" for k, _ in cle):
        champs_texte = [(champ, "text") for champ in (info.get("weights") or {})]
        cles = []
        for k, v in cle:
            if k == "_fts":
                cles.extend(champs_texte)
            elif k == "_ftsx":
                continue
            else:
                cles.append((k, v))
    else:
        cles = cle
    options = {k: info[k] for k in OPTIONS_INDEX if k in info}
    options["name"] = nom
    return cles, options
