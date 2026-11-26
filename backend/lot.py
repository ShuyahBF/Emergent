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
LOT = "467.1"
LOT_LIBELLE = "PDF de l'historique : les messages longs sont répartis sur plusieurs lignes (« suite 2/3 ») au lieu d'être tronqués. Historique Conversation : bloc « Chat interne » (Support Loois) sous WhatsApp, avec la durée de chaque session d'assistance, PDF et CSV ; blocs repliables. Historique Conversation : PDF corrigé pour les messages très longs (texte tronqué dans le PDF, complet dans le CSV). Historique Conversation : les contacts bloqués sont proposés et leurs messages d'avant le blocage restent visibles. Lot 466 : Liluvine → Historique Conversation : conversations WhatsApp par client et contacts, du plus récent au plus ancien (messages bloqués ignorés), impression PDF et export CSV."
