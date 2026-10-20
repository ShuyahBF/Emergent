"""Lot 255 — programmation du bandeau d'incident : date et heure de DÉBUT et de FIN d'affichage.

Règles (heure du serveur, instants en UTC) :
  - début vide = affiché dès l'activation ; fin vide = affiché jusqu'à la désactivation ;
  - le bandeau n'est visible que si « Activer le bandeau » est coché ET si l'instant présent est dans la fenêtre ;
  - un bandeau dont le début est dans le futur n'ouvre AUCUN incident dans l'historique public (/uptime) : ce n'est pas
    encore un incident (même règle que les annonces de sévérité « info »).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple


def lire_instant(valeur: Optional[str]) -> Optional[datetime]:
    """Date-heure ISO → instant UTC (sans fuseau = UTC). Vide → None. Illisible → ValueError."""
    if not valeur or not str(valeur).strip():
        return None
    d = datetime.fromisoformat(str(valeur).strip().replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def valider_fenetre(debut: Optional[str], fin: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Contrôle la fenêtre saisie : dates lisibles et fin après début. Lève ValueError avec un message en français."""
    try:
        d, f = lire_instant(debut), lire_instant(fin)
    except ValueError:
        raise ValueError("Date et heure du bandeau illisibles")
    if d and f and f <= d:
        raise ValueError("La fin d'affichage du bandeau doit être après son début")
    return d, f


def bandeau_visible(actif: bool, debut: Optional[str], fin: Optional[str], a: Optional[datetime] = None) -> bool:
    """Vrai si le bandeau doit s'afficher maintenant."""
    if not actif:
        return False
    a = a or datetime.now(timezone.utc)
    try:
        d, f = lire_instant(debut), lire_instant(fin)
    except ValueError:
        return True                     # dates illisibles déjà enregistrées : on n'efface pas le bandeau
    return not ((d and a < d) or (f and a >= f))


def debut_a_venir(debut: Optional[str], a: Optional[datetime] = None) -> bool:
    """Vrai si un début d'affichage est programmé dans le futur."""
    try:
        d = lire_instant(debut)
    except ValueError:
        return False
    return bool(d and d > (a or datetime.now(timezone.utc)))
