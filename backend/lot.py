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
LOT = "70"
LOT_LIBELLE = "Agenda d'appels de Liluvine (relances, prospection, suivi client, compte rendu de maintenance, rappels de rendez-vous : appels sortants planifiés, informations recueillies, coûts), anniversaires des utilisateurs suivis, voix clonées Story Studio pour Liluvine et style oral corrigé au téléphone (pas de listes, pas de seconde salutation, une question à la fois, appelant reconnu par son nom)"
