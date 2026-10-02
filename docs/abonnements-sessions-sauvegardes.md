# Abonnements, sessions et sauvegardes (lot 50 — spécification commune du 02/10/2026)

Paramètres (Admin) › onglet **Sécurité & Auth** › **Abonnements (grâce et coupure) et sessions des comptes** (super-admin).
Le « locataire » SAWALI est le **client** (compte principal et ses utilisateurs suivis).

## A. Période de grâce puis coupure

- Échéance = dernier règlement (`last_payment_at`, à défaut `contract_signed_at`) + périodicité (`contract_billing_period` : mensuel 30 j, trimestriel 90 j, annuel 365 j), comme les rappels de facturation. Un client sans périodicité ou sans date n'a pas d'échéance : jamais coupé.
- Impayée dès le lendemain de l'échéance (00:00 UTC). Grâce : **3 jours** par défaut, réglable par client (0 à 30). Pendant la grâce : bandeau rouge « Abonnement expiré — N jour(s) de grâce restant(s) — Renouveler ».
- « Renouveler la grâce (+3 j) » : 3 fois au plus par échéance impayée ; compteur lié à l'échéance, donc remis à zéro par un paiement. Journalisé (`abonnements_grace_journal`).
- Après la grâce : **402** (`code: abonnement_expire`) à chaque requête, à l'heure exacte, pour tous les comptes du client (sauf le super-admin et les sessions « Voir en tant que »). Restent ouvertes : `/api/auth/*`, `/api/me/abonnement`, `/api/me/sessions`, `/api/me/activite`, `/api/me/idle-config`, `/api/me/derniere-sauvegarde`, `/api/me/tenant-meta`, journaux techniques du navigateur. Le site affiche l'écran « Abonnement expiré — renouveler », sans donnée métier.
- **Interrupteur général** `abonnement_coupure_active` : désactivé par défaut (même prudence qu'au lot 27). Désactivé, seul le super-admin voit l'état des abonnements.
- La suspension manuelle et la suspension automatique existantes ne changent pas.

## B. Sessions simultanées limitées

- Chaque connexion (code OTP ou WhatsApp) ouvre une session : `sid` dans le jeton + document `sessions_comptes` (index TTL `expire_a`).
- Au plus **5** sessions par compte (réglage `sessions_max_par_compte`, 1 à 20). À la connexion suivante, la session dont la dernière activité est la plus ancienne est fermée : « Session fermée : nombre maximal d'appareils atteint pour ce compte. » (401, `code: session_limite`).
- « Mon compte » : sessions (appareil, navigateur, IP, ouverture, dernière activité) et « Fermer ». Le super-admin voit les sessions par compte d'un client et peut les fermer. Journal : `sessions_comptes_journal`.
- Les sessions « Voir en tant que » ne comptent pas et ne ferment jamais une session du client. Les jetons émis avant le lot 50 (sans `sid`) restent valables jusqu'à leur expiration.

## Inactivité (réglage existant, en minutes)

`auto_logout_minutes` et la fenêtre « Rester connecté » ne changent pas. Le serveur contrôle désormais la dernière activité de chaque session (écrite au plus une fois par minute ; requêtes marquées `X-Requete-Fond: 1` exclues ; activité signalée par `POST /api/me/activite`) : au-delà du délai + 2 minutes, 401 `session_inactive`.

## D. Dernière sauvegarde

« Mon compte » et pied de page de l'espace de gestion : « Dernière sauvegarde générale : JJ/MM/AAAA HH:MM » (dernière sauvegarde quotidienne réussie vers R2, lot 49) ou « Aucune sauvegarde enregistrée » (orange). Les clients n'ont pas de sauvegarde propre.
