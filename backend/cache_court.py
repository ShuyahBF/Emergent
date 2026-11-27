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


class CacheOctets:
    """Cache d'OBJETS (octets + type) pour les fichiers lus dans le stockage externe : durée courte ET budget de mémoire borné, car chaque lecture coûte ~1,8 s (téléchargement
    complet) et la mémoire du serveur est comptée (512 Mo). Un objet plus gros que `max_objet` n'est jamais gardé ; au-delà de `max_total` octets, les plus anciens sont retirés."""

    def __init__(self, duree_s: float, max_total: int, max_objet: int, horloge: Callable[[], float] = time.monotonic) -> None:
        self.duree_s, self.max_total, self.max_objet = duree_s, max_total, max_objet
        self._horloge = horloge
        self._valeurs: Dict[str, Tuple[float, bytes, str]] = {}
        self.total = 0

    def lire(self, cle: str) -> Optional[Tuple[bytes, str]]:
        trouve = self._valeurs.get(cle)
        if trouve is None:
            return None
        if self._horloge() - trouve[0] >= self.duree_s:
            self._retirer(cle)
            return None
        return trouve[1], trouve[2]

    def ecrire(self, cle: str, octets: bytes, type_contenu: str) -> bool:
        """Garde l'objet si sa taille le permet ; rend True s'il est gardé."""
        taille = len(octets)
        if taille > self.max_objet or taille > self.max_total:
            return False
        self._retirer(cle)
        while self.total + taille > self.max_total and self._valeurs:          # on libère de la place en retirant les plus anciens
            self._retirer(min(self._valeurs, key=lambda c: self._valeurs[c][0]))
        self._valeurs[cle] = (self._horloge(), octets, type_contenu)
        self.total += taille
        return True

    def _retirer(self, cle: str) -> None:
        ancien = self._valeurs.pop(cle, None)
        if ancien is not None:
            self.total -= len(ancien[1])

    def invalider(self) -> None:
        self._valeurs.clear()
        self.total = 0

    def __len__(self) -> int:
        return len(self._valeurs)
