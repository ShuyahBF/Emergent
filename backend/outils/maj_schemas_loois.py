"""Lot 68 — régénère la COPIE EMBARQUÉE des schémas de référence Loois (backend/loois_schemas/*.json.gz).

Les structures des bases HFSQL (identiques chez tous les clients d'une même application) sont publiées
par Loois dans son dépôt GitHub (dossier « schemas/ », voir PublicateurSchemaGitHub.cs) :
  schemas/e-kol/structure.json   → e-Kol
  schemas/biolog/structure.json  → Biolog
  schemas/Aizenta/<Table>.json   → Aizenta (table par table) + aizenta_tables_completes.txt (noms seuls)
Le dépôt étant privé, SAWALI embarque une copie compacte (aucun jeton dans le code).
Lot 68.1 : « la structure ne changera JAMAIS » (propriétaire) — cette copie est LA référence de tous les postes ;
Loois la télécharge (GET /api/loois/synchro/structure) et la garde chiffrée. Si elle devait malgré tout être
régénérée, l'empreinte annoncée (« structure_hash ») change et chaque poste retélécharge la nouvelle d'elle-même.
À relancer seulement après une nouvelle publication d'un schéma :
    python backend/outils/maj_schemas_loois.py /chemin/vers/loois
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

SORTIE = Path(__file__).resolve().parents[1] / "loois_schemas"


def compacter_structure(chemin: Path, application: str) -> dict:
    """structure.json de Loois → {application, base, genere_le, tables:[{nom, colonnes:[{nom,type,taille,echelle}]}]}."""
    d = json.loads(chemin.read_text(encoding="utf-8"))
    return {
        "application": application, "base": d.get("baseDeDonnees"), "genere_le": d.get("genereLe"),
        "source": f"github:ShuyahBF/loois/{chemin.parent.name}/{chemin.name}",
        "tables": [{"nom": t["nom"], "colonnes": [{"nom": c["nom"], "type": c.get("type") or "",
                                                     "taille": c.get("taille"), "echelle": c.get("echelle")}
                                                    for c in t.get("colonnes", [])]}
                   for t in d.get("tables", [])],
    }


def lire_liste(chemin: Path) -> list:
    """Liste « *_tables_completes.txt » : une table par ligne, commentaires « # » ignorés."""
    noms, vus = [], set()
    for ligne in chemin.read_text(encoding="utf-8-sig").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and ligne.lower() not in vus:
            vus.add(ligne.lower())
            noms.append(ligne)
    return noms


def ecrire(nom: str, contenu: dict) -> None:
    """Écrit le fichier compressé (gzip, JSON compact)."""
    SORTIE.mkdir(exist_ok=True)
    donnees = json.dumps(contenu, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (SORTIE / f"{nom}.json.gz").write_bytes(gzip.compress(donnees, mtime=0))
    print(f"{nom}: {len(contenu['tables'])} table(s)")


def main(depot: Path) -> None:
    ecrire("eKol", compacter_structure(depot / "schemas" / "e-kol" / "structure.json", "eKol"))
    ecrire("Biolog", compacter_structure(depot / "schemas" / "biolog" / "structure.json", "Biolog"))
    # Aizenta : schémas table par table + liste complète des noms (colonnes inconnues pour les autres tables)
    tables = {}
    for f in sorted((depot / "schemas" / "Aizenta").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        tables[d["table"].lower()] = {"nom": d["table"], "colonnes": [
            {"nom": c["nom"], "type": c.get("type") or "", "taille": c.get("taille"), "echelle": c.get("echelle")}
            for c in d.get("colonnes", [])]}
    for nom in lire_liste(depot / "aizenta_tables_completes.txt"):
        tables.setdefault(nom.lower(), {"nom": nom, "colonnes": []})
    ecrire("Aizenta", {"application": "Aizenta", "base": "myAizenta", "genere_le": None,
                       "source": "github:ShuyahBF/loois/schemas/Aizenta + aizenta_tables_completes.txt",
                       "tables": sorted(tables.values(), key=lambda t: t["nom"].lower())})


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../loois"))
