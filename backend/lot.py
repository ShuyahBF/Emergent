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
LOT = "272"
LOT_LIBELLE = "Index MongoDB recommandés (conseiller Atlas) : état et création en un clic dans les Paramètres, pour accélérer e-Kol et les messages WhatsApp sans payer un palier supérieur"
