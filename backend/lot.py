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
LOT = "337"
LOT_LIBELLE = "Liluvine : un ancien message citant un logiciel absent de l'offre du client (ex. Aizenta pour un client qui n'a que e-KOL) n'est plus rejoué dans la conversation, et elle ne cite plus un logiciel que le client n'a pas nommé (cas d'un simple « Ok » qui relançait sur Aizenta). Lot 336 : Liluvine : l'assistance WhatsApp est limitée à l'offre du client (un logiciel absent de la fiche, ex. Aizenta pour un client qui n'a que e-KOL, n'est plus dépanné : réponse « ne figure pas dans votre offre » puis escalade). Lot 335 : Clés clients Loois consultables par le super-admin : bouton « Afficher la clé » (LK- et LKS-), clé conservée chiffrée avec le secret LOOIS_CLES_CHIFFREMENT (hors base), chaque affichage inscrit à l'historique ; les clés déjà créées sont à régénérer. Lot 334 : Clés clients Loois : liste déroulante du compte client (contrat) lié à chaque clé + colonne Contrat — une clé sans compte lié faisait anonymiser les listes de Loois. Lot 333 : Portail e-Kol : suivi d'utilisation des postes Loois vérifié avec la clé client Loois (route signée de vérification). Lot 332 : contrôle à distance, presse-papiers du poste copié chez le technicien (copie automatique + bouton). Lot 331 : clavier du technicien respecté, pixels parasites corrigés, vue zoomée et barre en haut, transferts fiabilisés (mémoire du serveur libérée après les sauvegardes)."
