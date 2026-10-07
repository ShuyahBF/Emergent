# sentinelle_boucle.py — Lot 71.1 : surveille que le serveur ne se fige jamais sans laisser de trace.
#
# Contexte : la boucle principale (asyncio) traite TOUTES les requêtes. Si un code synchrone lent y tourne
# (import lourd, accès réseau bloquant…), tout le serveur attend : c'est ce qui figeait SAWALI ~5,5 s à la
# première ouverture des Paramètres (import de qdrant_client dans la boucle, corrigé dans qdrant_rag.py).
#
# Fonctionnement :
#   - une petite tâche asyncio note l'heure toutes les 0,25 s (« battement ») ;
#   - un fil séparé (thread) vérifie ce battement ; si la boucle ne bat plus depuis SEUIL secondes, il écrit
#     dans les journaux Render la PILE d'appels de la boucle, c'est-à-dire la ligne de code exacte qui bloque ;
#   - quand la boucle repart, il écrit la durée totale du blocage.
# Les journaux contiennent seulement des noms de fichiers et de fonctions, jamais de données ni de secrets.
# Désactivation : variable d'environnement SENTINELLE_BOUCLE=0.
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sawali.sentinelle")

SEUIL_S = 1.5            # au-delà, la boucle est considérée comme figée
INTERVALLE_S = 0.25      # fréquence du battement et de la vérification
_LIGNES_PILE = 25        # nombre maximal de lignes de pile écrites dans les journaux

_etat = {"battement": time.monotonic(), "demarree": False, "id_fil": None, "fil_lance": False}
# Lot 71.3 — 20 derniers blocages (affichés dans Paramètres → « Santé du serveur ») : heure, durée, lieu
_BLOCAGES: deque = deque(maxlen=20)


async def _battre() -> None:
    """Tâche asyncio : note l'heure à chaque tour de boucle (si elle ne bat plus, la boucle est figée)."""
    while True:
        _etat["battement"] = time.monotonic()
        await asyncio.sleep(INTERVALLE_S)


def _pile_du_fil(id_fil: int) -> str:
    """Pile d'appels actuelle du fil de la boucle (les dernières lignes = le code qui bloque)."""
    cadre = sys._current_frames().get(id_fil)  # noqa: SLF001 — outil de diagnostic standard de Python
    if cadre is None:
        return "(pile indisponible)"
    lignes = traceback.format_stack(cadre)
    return "".join(lignes[-_LIGNES_PILE:])


def _lieu_du_blocage(pile: str) -> str:
    """Dernière ligne « File … » qui appartient à SAWALI (sinon la toute dernière) : le code en cause."""
    lignes = [l.strip() for l in pile.splitlines() if l.strip().startswith("File ")]
    sawali = [l for l in lignes if "site-packages" not in l and "<frozen" not in l and "/python3" not in l]
    choisie = (sawali or lignes or ["(inconnu)"])[-1]
    return choisie.replace("/opt/render/project/src/", "")[:200]


def etat() -> Dict[str, Any]:
    """Pour la rubrique « Santé du serveur » : sentinelle active ? derniers blocages (plus récent d'abord)."""
    blocages: List[Dict[str, Any]] = list(_BLOCAGES)
    return {"active": bool(_etat["demarree"]), "seuil_s": SEUIL_S, "blocages": blocages}


def _surveiller() -> None:
    """Fil de surveillance (un seul par processus) : signale chaque blocage une fois (pile au début, durée
    à la fin). Le fil surveillé est relu à chaque tour (_etat["id_fil"]) : un redémarrage ne crée pas de doublon."""
    debut_blocage: Optional[float] = None
    while True:
        time.sleep(INTERVALLE_S)
        retard = time.monotonic() - _etat["battement"]
        if retard >= SEUIL_S and debut_blocage is None:
            # Début d'un blocage : on note la ligne de code fautive (une seule fois par blocage)
            debut_blocage = _etat["battement"]
            pile = _pile_du_fil(_etat["id_fil"])
            logger.warning("[boucle-bloquee] serveur figé depuis %.1f s — code en cours :\n%s", retard, pile)
            _BLOCAGES.appendleft({"le": datetime.now(timezone.utc).isoformat(), "duree_s": None,
                                  "lieu": _lieu_du_blocage(pile)})
        elif retard < SEUIL_S and debut_blocage is not None:
            # La boucle a repris : durée totale du blocage
            duree = _etat["battement"] - debut_blocage
            logger.warning("[boucle-bloquee] le serveur a repris après %.1f s de blocage", duree)
            if _BLOCAGES and _BLOCAGES[0]["duree_s"] is None:
                _BLOCAGES[0]["duree_s"] = round(duree, 1)
            debut_blocage = None


def demarrer() -> None:
    """À appeler depuis un événement « startup » (donc dans la boucle principale). Une seule fois."""
    if _etat["demarree"] or os.environ.get("SENTINELLE_BOUCLE", "1") == "0":
        return
    _etat["demarree"] = True
    _etat["battement"] = time.monotonic()
    _etat["id_fil"] = threading.get_ident()          # fil de la boucle principale à surveiller
    asyncio.get_running_loop().create_task(_battre())
    if not _etat["fil_lance"]:                       # un seul fil de surveillance par processus
        _etat["fil_lance"] = True
        threading.Thread(target=_surveiller, name="sentinelle-boucle", daemon=True).start()
    logger.info("[sentinelle] surveillance de la boucle principale active (seuil %.1f s)", SEUIL_S)
