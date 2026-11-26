# captures_suivis.py — Lot 465 : réglages des CAPTURES D'ÉCRAN ANNOTÉES dans les suivis (Paramètres → « 📸 Captures d'écran annotées dans les suivis »).
# Deux réglages (db.settings {_id: "global"}), exposés au site par /api/public/ui-flags (le site les garde dans son cache de réglages publics) :
#   - suivis_captures_actives : la fenêtre d'annotation s'ouvre au collage d'une image (oui par défaut ; non = le collage garde son comportement habituel) ;
#   - suivis_captures_largeur_max : largeur maximale (pixels) de la capture insérée, 800 à 2400, 1600 par défaut (une capture plus large est réduite, jamais agrandie).
from __future__ import annotations

from typing import Any, Dict

LARGEUR_DEFAUT = 1600
LARGEUR_MIN = 800
LARGEUR_MAX = 2400


def reglages_captures(s: Dict[str, Any]) -> Dict[str, Any]:
    """Réglages normalisés : {actives: bool, largeur_max: int}. Une valeur absente ou absurde redevient la valeur par défaut ; la largeur est bornée."""
    s = s or {}
    try:
        largeur = int(float(s.get("suivis_captures_largeur_max")))
    except (TypeError, ValueError):
        largeur = LARGEUR_DEFAUT
    if largeur <= 0:
        largeur = LARGEUR_DEFAUT
    return {"actives": s.get("suivis_captures_actives") is not False, "largeur_max": max(LARGEUR_MIN, min(LARGEUR_MAX, largeur))}
