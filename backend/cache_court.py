# cache_court.py — Lot 473 : petit CACHE EN MÉMOIRE à durée de vie courte, pour les routes d'affichage qui refont les mêmes lectures à chaque appel.
#
# Pourquoi : l'export des appels lents du 27/11/2026 (737 appels, 4 749 requêtes à la base) montre que `/me/notifications/counts` fait 31 requêtes à chaque appel
# (25 % de toutes les requêtes du serveur), sans parler des diagnostics d'administration qui relisent 77 à 289 fois la base à chaque ouverture de page.
# Règle 7 du propriétaire : « calcul lourd = cache court, jamais refait à chaque clic ».
#
# Principe : une valeur gardée `duree_s` secondes au plus ; une écriture qui change le résultat (« marquer comme vu », import…) l'INVALIDE tout de suite, donc
# l'utilisateur ne voit jamais l'effet de sa propre action en retard. Taille bornée (les plus anciennes entrées sont retirées). Aucune base, aucun réseau :
# la valeur est perdue au redémarrage (elle se recalcule au prochain appel). Testé dans tests/test_cache_court.py (horloge injectable, aucune attente réelle).
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple


class CacheCourt:
    def __init__(self, duree_s: float, max_entrees: int = 500, horloge: Callable[[], float] = time.monotonic) -> None:
        self.duree_s = duree_s
        self.max_entrees = max_entrees
        self._horloge = horloge
        self._valeurs: Dict[str, Tuple[float, Any]] = {}

    def lire(self, cle: str) -> Optional[Any]:
        """Valeur gardée et encore fraîche, sinon None (une valeur expirée est retirée)."""
        trouvee = self._valeurs.get(cle)
        if trouvee is None:
            return None
        if self._horloge() - trouvee[0] >= self.duree_s:
            self._valeurs.pop(cle, None)
            return None
        return trouvee[1]

    def ecrire(self, cle: str, valeur: Any) -> Any:
        """Garde la valeur et la rend telle quelle (pratique : `return cache.ecrire(k, calcul)`)."""
        if len(self._valeurs) >= self.max_entrees and cle not in self._valeurs:
            plus_ancienne = min(self._valeurs, key=lambda c: self._valeurs[c][0])           # taille bornée : on retire la plus ancienne
            self._valeurs.pop(plus_ancienne, None)
        self._valeurs[cle] = (self._horloge(), valeur)
        return valeur

    def invalider(self, prefixe: Optional[str] = None) -> int:
        """Retire les entrées dont la clé commence par `prefixe` (toutes si None) ; rend leur nombre."""
        a_retirer = [c for c in self._valeurs if prefixe is None or c.startswith(prefixe)]
        for c in a_retirer:
            self._valeurs.pop(c, None)
        return len(a_retirer)

    def __len__(self) -> int:
        return len(self._valeurs)
