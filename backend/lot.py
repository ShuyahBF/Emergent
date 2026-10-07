# lot.py — numéro du lot actuellement déployé (source UNIQUE, lue par /api/version).
#
# Règle permanente (03/10/2026) : à CHAQUE déploiement sur render-production,
# mettre à jour LOT (et LOT_LIBELLE) dans ce fichier :
#   - nouveau lot fonctionnel : numéro entier suivant (ex. "56") ;
#   - petite mise à jour d'un lot déjà en ligne : sous-numéro (ex. "55.4").
# Effet voulu : ce fichier étant dans le dossier backend, sa modification force
# Render à redéployer le serveur, ce qui incrémente aussi le numéro de version
# (1.N, compteur de déploiements) — même quand le changement ne touche que l'interface.
# Règle (06/10/2026) : chaque nouveau lot ajoute AUSSI sa carte dans backend/nouveautes.py (test tests/test_regle_nouveautes.py).
LOT = "73"
LOT_LIBELLE = "Menu « Liluvine » dépliable dans la barre latérale (agenda, Liluvine PRO, historique, commandes « ! », handlers IA), partage des éléments de Liluvine par superviseur (Paramètres, contrôlé par le serveur pour l'agenda), demande d'autorisation d'appel renvoyable (bouton + relance automatique après 24 h, limites Meta), voix clonées de Voice Studio transmises à Liluvine, sentinelle muette pendant l'arrêt du serveur"
