"""État d'un fichier de la bibliothèque de médias (lot 213) — logique pure, testée.

Les fichiers sont servis depuis le disque du serveur, vidé à chaque redéploiement Render ; seule une copie « durable »
(stockage R2) permet de les retrouver. Trois états, déduits SANS lire le fichier :
  - durable : la fiche du fichier porte un `storage_path` → restaurable après un redéploiement ;
  - à risque : sur le disque mais sans copie durable → sera perdu au prochain redéploiement (copie faite en arrière-plan) ;
  - perdu : ni sur le disque, ni de copie durable (ou fiche absente) → irrécupérable, le lien est définitivement cassé.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def etat_fichier(fiche: Optional[Dict[str, Any]], sur_disque: bool) -> Tuple[bool, bool]:
    """(durable, perdu) d'un fichier à partir de sa fiche (collection files) et de sa présence sur le disque."""
    durable = bool((fiche or {}).get("storage_path"))
    return durable, (not durable and not sur_disque)


def a_copier(fiche: Optional[Dict[str, Any]], sur_disque: bool) -> bool:
    """Vrai si le fichier est à risque : présent sur le disque mais sans copie durable."""
    durable, _perdu = etat_fichier(fiche, sur_disque)
    return bool(fiche) and sur_disque and not durable
