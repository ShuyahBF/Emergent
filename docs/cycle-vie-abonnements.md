# Cycle de vie du non-renouvellement (lot 51 — spécification commune, point C, validée le 02/10/2026)

Paramètres (Admin) › onglet **Sécurité & Auth** › **Cycle de vie des abonnements (suspension J+110, archivage J+113)** (super-admin).
Le « locataire » SAWALI est le **client abonné** : son compte principal et tout ce qui lui est rattaché.
Code : `backend/cycle_vie_abonnements.py`, routes `backend/routes/cycle_vie_abonnements.py`.

## Calendrier

Échéance = celle du lot 50 (dernier règlement + périodicité du contrat). Un client sans échéance n'est jamais concerné. J+N = jours calendaires depuis l'échéance (grâce comprise).

| Jour | Action |
|------|--------|
| J+103 | Avertissement WhatsApp + e-mail : suspension dans 7 jours |
| J+110 | Suspension (`cycle_vie.statut = SUSPENDU_NON_RENOUVELE`) + avertissement |
| J+112 | Dernier avis : suppression demain |
| J+113 | Archive chiffrée → R2 `archives-locataires/<client>/` → relecture et vérification → suppression |

Les délais sont des minimums : 7 jours au moins entre l'avertissement J+103 et la suspension, 3 jours de suspension au moins et le dernier avis la veille au plus tard avant l'archivage. Avertissements journalisés (`cycle_vie_avertissements`, clé unique client + échéance + étape) : chacun n'est envoyé qu'une fois.

## Suspension

Tous les comptes du client reçoivent **403** (`code: abonnement_suspendu`) sur toutes les routes ; leurs sessions sont fermées (`session_abonnement_suspendu`) ; la connexion par mot de passe, code e-mail et code WhatsApp est refusée. Le super-admin et les sessions « Voir en tant que » restent possibles. Un règlement saisi (nouvelle échéance) rend l'accès aussitôt ; la tâche suivante retire la suspension. « Lever la suspension » (super-admin) : pas de nouvelle suspension pour cette échéance.

## Archive (J+113)

- Données archivées : toute collection (hors `COLLECTIONS_CONSERVEES`) dont un champ propriétaire (`client_id`, `tenant_id`, `parent_client_id`, `user_id`, `owner_id`, `owner_user_id`, `owner_parent_client_id`, `tracked_user_id`, `user_account_id`, `created_by_id`, `uploaded_by_user_id`, `billing_tenant_id`, `linked_client_id`) vaut l'identifiant d'un compte du client (principal, comptes rattachés, utilisateurs suivis), plus les documents enfants de ses formulaires (`form_id`), sondages (`survey_id`), campagnes (`campaign_id`) et officines liées (`officine_id`).
- Conservées (jamais archivées ni supprimées) : réglages, journaux de la plateforme, sessions (fermées puis effacées à part), pièces comptables de SAWALI (`tenant_payments`, `interventions_invoices`, `payments`, `payment_transactions`, `billing_reminders`, `contract_overdue_alerts`), `activity_events`.
- Format : celui de l'export complet du lot 49 (ZIP chiffré AES-256-GCM, clé scrypt de `SAUVEGARDE_AUTO_PHRASE`, signature HMAC dérivée de `JWT_SECRET`), manifeste `sawali-archive-client` avec, par collection, le nombre de documents et l'empreinte des identifiants.
- Vérification : l'archive est retéléchargée depuis R2, déchiffrée, contrôlée (intégrité, signature) et comparée (nombres et identifiants). Seuls les documents relus sont supprimés. Échec : rien n'est supprimé, alerte e-mail au super-admin, journal `ARCHIVAGE_ECHEC`, nouvel essai à l'exécution suivante.
- Fiche du client conservée, réduite (identité, contrat), `account_status = archive`, sans mot de passe, `cycle_vie.archive` = clé, date, taille, nombres de documents.

## Conservation et réouverture

- Conservation : 365 jours par défaut (30 à 3 650), puis effacement de l'archive dans R2 (seulement une clé au format `archives-locataires/…/sawali-client-AAAAMMJJ-HHMMSS-xxxxxx.sawali`).
- Réouverture (super-admin) : frais de réouverture paramétrables (montant + devise), case « frais encaissés », REOUVRIR + mot de passe. L'archive est relue et vérifiée, puis restaurée (remplacement limité aux documents du client). Statut actif, `last_payment_at` = jour de la réouverture (nouvelle échéance), frais enregistrés dans `tenant_payments` (`type: frais_reouverture`).

## Réglages et tâche

- `cycle_vie_actif` (**désactivé par défaut**), `cycle_vie_simulation` (activé par défaut), `cycle_vie_conservation_jours`, `cycle_vie_frais_reouverture_montant`, `cycle_vie_frais_reouverture_devise`.
- Tâche quotidienne 06:40 (Africa/Abidjan) dans le planificateur existant : jamais avec `DISABLE_SCHEDULER=1` ni dans la preview. « Simuler maintenant » fonctionne même désactivé ; « Lancer maintenant » exige l'interrupteur.
- Rapport quotidien par e-mail au super-admin (`SUPER_ADMIN_EMAIL`), dernière exécution dans `cycle_vie_etat`, journal `cycle_vie_journal`.
- Exclus : super-admin, clients de test (`est_test`), démo (`is_demo`, DEMO SAWALI, comptes WhatsApp de démonstration), comptes des domaines internes.

## Connexion par code WhatsApp

Depuis ce lot, `POST /api/auth/wa-otp/verify` contrôle le statut du compte (`account_status`) comme la connexion par mot de passe (« Compte suspendu : … » ou « Compte désactivé »), puis le cycle de vie du client. La connexion par code e-mail le contrôle aussi au moment du code.
