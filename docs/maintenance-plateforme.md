# Maintenance de la plateforme — déconnexion de tous les utilisateurs (lot 50, règle R8)

Paramètres (Admin) › onglet **Sécurité & Auth** › **Maintenance — Déconnexion de tous les utilisateurs**.
Même comportement que sur adLyn. Actions réservées au **super-admin SAWALI** (`SUPER_ADMIN_EMAIL`).

## Déroulement

| Phase | Période | Utilisateurs (clients, suivis, superviseurs, démo) | Admins |
|---|---|---|---|
| Annonce | de l'envoi au début du verrouillage (100 − part %) | fenêtre fermable (message + décompte), puis bandeau rouge | bandeau orange ; « Annuler » (super-admin) |
| Verrouillage | dernière part de la durée (80 % par défaut) | écran plein, non fermable (ni Échap, ni clic, page inerte), décompte mm:ss | idem |
| Maintenance | de l'échéance à la réactivation | déconnexion forcée ; API → **503** (`code: maintenance_plateforme`) ; connexion (mot de passe, code OTP, WhatsApp) → **503** | bandeau rouge « Maintenance en cours — connexions bloquées » ; « Réactiver les connexions » (super-admin) |

- Réglages : message (obligatoire, 1 000 caractères max), durée **1 à 120 min (5 par défaut)**, part verrouillée **0 à 100 % (80 par défaut)**.
- Décompte calé sur l'heure du serveur (`maintenant_serveur`) ; état relu toutes les 15 s et au retour sur l'onglet.
- Annulation possible avant l'échéance : personne n'est déconnecté.
- Réactivation : « sessions valides après » = échéance ; les jetons émis avant (`iat`) sont refusés (401, `code: session_maintenance`) et les sessions de comptes ouvertes avant sont notées fermées : chacun se reconnecte.
- **Jamais bloqués** : les comptes de rôle `admin` (super-admin et Admins rattachés à un client) et les sessions « Voir en tant que » (lot 44), qui sont celles d'un Admin.
- La page de connexion affiche l'avis de maintenance et le motif de la déconnexion.

## Routes

- `GET /api/maintenance/etat` — public, sans donnée sensible (phase, message, dates, `secondes_restantes`, `maintenant_serveur`).
- `GET|POST /api/admin/deconnexion-generale`, `POST …/annuler`, `POST …/reactiver` — super-admin.

## Non bloqué (vérifié par le test `test_aucun_webhook_ni_route_publique_du_serveur_ne_depend_d_une_session`)

Le blocage passe uniquement par `auth.get_current_user` (sessions des comptes) et par la connexion. Ne sont donc pas bloqués :

- **Webhooks entrants** : WhatsApp / Meta (`/api/whatsapp/webhook`, `/api/meta/webhook`), Stripe (`/api/webhook/stripe`, monté si `STRIPE_API_KEY`), PawaPay (`/api/webhooks/pawapay/…`), n8n (`/api/webhooks/agenda/{secret}`, `/api/webhooks/n8n/payroll/{tenant_id}`), planning (`/api/webhooks/planning/{secret}`), Liluvine (`/api/webhook/liluvine-send`, `/api/webhooks/liluvine-pro/…`), SMS Bird, inventaire des officines, Google Agenda, VIDAL, jauge support.
- **Pages et portails publics** : `/api/public/…` (formulaires, sondages, liens de paiement, catalogue, rapports signés, restauration…), portail des officines (`/api/officines-portal/…`, jeton distinct), retours OAuth (Facebook, LinkedIn, X).
- `/health`, `/api/maintenance/etat`, `/api/auth/logout`.
- **Tâches de fond** (planificateur : rappels, sauvegardes de la nuit, envois programmés) : elles ne passent pas par l'API. Les envois WhatsApp sortants continuent.
- La discussion interne (WebSocket) est fermée pendant la maintenance, sauf pour les Admins.

## Stockage

`maintenance_plateforme` (document unique `_id: "etat"`) et `maintenance_plateforme_journal` (annonce, annulation, réactivation : qui, quand, message, durée, part verrouillée).

## Fichiers

`backend/maintenance_plateforme.py`, `backend/routes/maintenance_plateforme.py`, `backend/controle_acces.py`,
`frontend/src/lib/maintenancePlateforme.js`, `frontend/src/components/MaintenancePlateforme.jsx`,
`frontend/src/pages/admin/sections/DeconnexionGeneraleSection.jsx`.
