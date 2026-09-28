"""Relit le fichier des secrets produit par la sauvegarde de migration
(sawali-secrets-<id>.enc.json ou <prefixe>/secrets/env-secrets.enc.json dans R2).

Usage (sur son poste, jamais sur un serveur partagé) :
    python backend/outils/dechiffrer_secrets_migration.py chemin/vers/fichier.enc.json
Le mot de passe saisi au lancement de la sauvegarde est demandé (non affiché).
Affiche les variables au format « NOM=valeur », prêtes à être recopiées dans
Render (Environment > Add from .env). Option --noms : n'affiche que les noms.
"""
import base64
import getpass
import json
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def dechiffrer(enveloppe: dict, mot_de_passe: str) -> dict:
    """AES-256-GCM, clé dérivée du mot de passe (PBKDF2-SHA256, nombre de tours lu dans le fichier)."""
    cle = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=base64.b64decode(enveloppe["sel"]),
                     iterations=int(enveloppe["iterations"])).derive(mot_de_passe.encode())
    clair = AESGCM(cle).decrypt(base64.b64decode(enveloppe["nonce"]), base64.b64decode(enveloppe["donnees"]), None)
    return json.loads(clair)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        enveloppe = json.load(f)
    if "--noms" in sys.argv:
        print("\n".join(enveloppe.get("cles", [])))
        sys.exit(0)
    try:
        valeurs = dechiffrer(enveloppe, getpass.getpass("Mot de passe des secrets : "))
    except Exception:
        sys.exit("Mot de passe incorrect ou fichier altéré.")
    for nom, valeur in sorted(valeurs.items()):
        print(f"{nom}={valeur}")
