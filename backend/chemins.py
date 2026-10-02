"""Lot 49 — Chemins portables (Emergent, Render, poste local).

Sur Emergent, le projet est installé dans `/app` : le code utilisait des chemins
figés (`/app/backend/uploads`, `/app/backend/snapshots`, `/app/memory`, `/app/docs`…).
Sur Render, `/app` n'existe pas et ne peut pas être créé : créer ces dossiers à
l'import faisait échouer le démarrage.

Chaque dossier est calculé ici, une seule fois, dans cet ordre :
  1. la variable d'environnement dédiée (UPLOAD_DIR, SNAPSHOTS_DIR, EXPORTS_DIR,
     MEMORY_DIR, DOCS_DIR, UPLOAD_AI_DIR), si elle est définie et utilisable ;
  2. le chemin historique d'Emergent (`/app/...`), s'il est utilisable ;
  3. le même chemin relatif au répertoire du projet (sur Emergent, c'est le même
     dossier ; sur Render, par exemple `/opt/render/project/src/backend/uploads`) ;
  4. pour un dossier où l'on écrit : un dossier du répertoire temporaire du système.

« Utilisable » : pour un dossier où l'on écrit, il existe (ou a pu être créé) et
on peut y écrire ; pour un dossier seulement lu (documentation, mémoire), il existe.
Aucune erreur n'est levée : un dossier impossible à créer est noté dans le journal
et le candidat suivant est essayé. Le démarrage ne peut donc plus échouer ici.

Sur Emergent, rien ne change : sans variable, le chemin `/app/...` est retenu.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("sawali.chemins")

# Répertoire du dossier backend/ et racine du projet (le dossier qui contient backend/)
BACKEND_DIR = Path(__file__).resolve().parent
RACINE_PROJET = BACKEND_DIR.parent
# Racine historique d'Emergent
RACINE_EMERGENT = Path("/app")


def _utilisable(dossier: Path, ecriture: bool) -> bool:
    """Vrai si le dossier peut servir ; le crée si l'on doit y écrire. Ne lève jamais."""
    try:
        if ecriture:
            dossier.mkdir(parents=True, exist_ok=True)
            return dossier.is_dir() and os.access(dossier, os.W_OK | os.X_OK)
        return dossier.is_dir()
    except Exception as exc:  # noqa: BLE001 — aucune erreur ne doit remonter au démarrage
        logger.info("[chemins] dossier %s inutilisable : %s", dossier, exc)
        return False


def resoudre(variable: Optional[str], relatif: str, *, ecriture: bool = True,
             racine_emergent: Path = RACINE_EMERGENT, racine_projet: Path = RACINE_PROJET,
             projet: bool = True, candidats_en_plus: Iterable[Path] = ()) -> Path:
    """Choisit le dossier à utiliser (voir l'ordre en tête du module).

    variable  : nom de la variable d'environnement (None : aucune)
    relatif   : chemin relatif à la racine du projet, ex. « backend/uploads »
    ecriture  : True pour un dossier où l'on écrit (il est créé au besoin)
    projet    : False pour ne pas essayer le chemin relatif au projet (les candidats
                en plus le remplacent)
    """
    candidats = []
    valeur = (os.environ.get(variable) or "").strip() if variable else ""
    if valeur:
        candidats.append(("variable " + variable, Path(valeur)))
    candidats.append(("chemin Emergent", racine_emergent / relatif))
    if projet:
        candidats.append(("répertoire du projet", racine_projet / relatif))
    for c in candidats_en_plus:
        candidats.append(("repli", Path(c)))
    for origine, dossier in candidats:
        if _utilisable(dossier, ecriture):
            if valeur and origine != "variable " + variable:
                logger.warning("[chemins] %s=%s inutilisable : %s retenu à la place", variable, valeur, dossier)
            return dossier
    if not ecriture:
        # Dossier lu seulement et absent partout : le chemin du projet (les lectures
        # répondront « introuvable », comme avant quand le fichier manquait).
        return racine_projet / relatif
    secours = Path(tempfile.gettempdir()) / "sawali" / relatif
    if _utilisable(secours, True):
        logger.warning("[chemins] aucun dossier utilisable pour %s : dossier temporaire %s", relatif, secours)
    else:
        logger.error("[chemins] aucun dossier utilisable pour %s (même %s)", relatif, secours)
    return secours


def sous_dossier(parent: Path, nom: str) -> Path:
    """parent/nom, créé si possible ; jamais d'erreur (un échec est seulement noté)."""
    dossier = parent / nom
    _utilisable(dossier, True)
    return dossier


# ---------------------------------------------------------------------------
# Dossiers de l'application (calculés une fois, à l'import)
# ---------------------------------------------------------------------------
# Fichiers déposés (documents, médias WhatsApp, logos…)
UPLOAD_DIR = resoudre("UPLOAD_DIR", "backend/uploads")
# Images et vidéos générées par l'IA : chemin historique /app/backend/uploads/ai, sinon UPLOAD_DIR/ai
UPLOAD_AI_DIR = resoudre("UPLOAD_AI_DIR", "backend/uploads/ai", projet=False, candidats_en_plus=[UPLOAD_DIR / "ai"])
# Instantanés de la base (Admin → Sauvegarde de la base)
SNAPSHOTS_DIR = resoudre("SNAPSHOTS_DIR", "backend/snapshots")
# Exports complets chiffrés et fichiers importés (lot 49), effacés au plus tard une heure après.
# Volontairement HORS du dépôt (dossier temporaire du système) : sur Emergent, /app est un dépôt
# git enregistré automatiquement, un export ne doit jamais s'y retrouver.
EXPORTS_DIR = resoudre("EXPORTS_DIR", "exports_complets", racine_emergent=Path(tempfile.gettempdir()) / "sawali",
                       racine_projet=BACKEND_DIR / "var")
# Mémoire du projet (CHANGELOG.md, SUGGESTIONS.md) et documents PDF publics : lus seulement
MEMORY_DIR = resoudre("MEMORY_DIR", "memory", ecriture=False)
DOCS_DIR = resoudre("DOCS_DIR", "docs", ecriture=False)
