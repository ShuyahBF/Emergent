"""Lot 49 — Contrôle (et, sur demande, déchiffre) un export complet SAWALI (.sawali) hors serveur.

Usage (sur son poste, jamais sur un serveur partagé) :
    python backend/outils/dechiffrer_export_complet.py chemin/vers/sawali-export-....sawali
        -> contrôle la phrase et l'intégrité, puis affiche le manifeste (collections, documents)
    python backend/outils/dechiffrer_export_complet.py fichier.sawali --zip sortie.zip
        -> écrit en plus l'archive ZIP EN CLAIR (collections/*.jsonl en JSON étendu canonique,
           index/*.json, manifeste.json). Attention : elle contient tous les secrets.
La phrase secrète est demandée au lancement (non affichée). La signature (JWT_SECRET) n'est
contrôlée que si la variable JWT_SECRET est définie dans l'environnement du poste.
"""
import getpass
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sauvegarde_format as sf  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sortie = sys.argv[sys.argv.index("--zip") + 1] if "--zip" in sys.argv else None
    phrase = getpass.getpass("Phrase secrète : ")
    try:
        lecteur = sf.LecteurChiffre(sys.argv[1], phrase)
        signature = lecteur.verifier(sf.cle_signature(os.environ.get("JWT_SECRET")))
    except sf.ErreurSauvegarde as exc:
        sys.exit(f"Refusé : {exc}")
    print(f"Fichier intact. Signature : {signature}")
    with zipfile.ZipFile(lecteur) as archive:
        manifeste = json.loads(archive.read("manifeste.json"))
    print(f"Export du {manifeste.get('cree_le')} — {len(manifeste.get('collections', {}))} collections, "
          f"{manifeste.get('total_documents')} documents")
    if sortie:
        lecteur.seek(0)
        with open(sortie, "wb") as f:
            shutil.copyfileobj(lecteur, f, 1024 * 1024)
        print(f"Archive en clair écrite : {sortie}")
    lecteur.close()


if __name__ == "__main__":
    main()
