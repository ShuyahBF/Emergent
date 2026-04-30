# PRD — SAWALI SMART SYSTEMS Portal

## Original Problem Statement
Construit moi un site web, qui s'affiche bien sur toutes les types de terminaux (ordinateur PC, tablettes et téléphone). Site professionnel de SAWALI SMART SYSTEMS avec accès public (missions, expérience, spécialisation, catalogue, demande de RDV, contact) et espace professionnel (login, mot de passe, captcha, OTP mobile, état du compte, RDV, documentation logiciels, historique interventions, suivi utilisateurs).

## User Choices
- **OTP** : par email via SMTP (paramétrable depuis l'admin)
- **Captcha** : Google reCAPTCHA v2 (clés paramétrables admin)
- **Logo** : fourni (URL CDN Emergent)
- **Contenus** : upload PDF/images/textes possible à tout moment depuis l'admin
- **RDV** : stockés en base + Google Calendar (sup.alphasofti@gmail.com), credentials paramétrables admin, vérification disponibilité avant booking
- **Tous les endpoints API** : documentés (Swagger + page /documentation)

## Architecture
- **Backend**: FastAPI + MongoDB (Motor). Auth JWT + bcrypt + OTP. Modules : auth.py, email_service.py, recaptcha.py, google_calendar.py, models.py, server.py
- **Frontend**: React 19 + React Router 7 + Tailwind + Shadcn UI. AuthContext + Protected routes. Marketing dark theme + Portal/Admin light theme.
- **Fonts**: Space Grotesk (titres) + Geist (corps)
- **Brand**: Deep Navy #0E1F3D + Electric Blue #1E90FF + White

## Implemented (2026-04-25)
✅ Backend complet (61 endpoints, tests pytest 100%)
- Auth: login + reCAPTCHA + OTP + JWT + change password
- Public: content, catalog, contact, availability, RDV public booking
- Client portal: account, appointments, documents, interventions, users tracking
- Admin: clients CRUD, appointments, interventions, documents (upload PDF/image), contents (CMS), settings, contacts, tracked-users
- **Témoignages NPS** : auto feedback_token quand RDV passé en "completed", form public sur /feedback/:token, modération admin, stats NPS publiques (promoteurs/passifs/détracteurs)
- Settings configurables : reCAPTCHA, SMTP, Google Calendar OAuth, business hours, slot duration, company info
- Google Calendar OAuth flow (/admin/google/auth-url + callback) avec free/busy check + auto event creation
- File upload + serving
- Auto-seed admin + default contents
- Auto Swagger docs + /api/api-routes meta endpoint

✅ Frontend complet (responsive PC/tablette/mobile)
- Public: Home (avec section témoignages preview), Missions, Spécialisations, Catalogue, Témoignages (avec dashboard NPS), Contact, RDV (date strip + slot picker)
- Feedback NPS public sur /feedback/:token (échelle 0-10 + commentaire + opt-in publication)
- Auth: Login + reCAPTCHA + OTP step (avec dev_otp banner si SMTP non configuré)
- Portal client: Dashboard, Appointments, Documents (PDF viewer), Interventions, UsersTracking
- Admin: Dashboard, Clients, Appointments, Interventions, Documents (upload + RTE), Contents (CMS), Settings, Contacts, TrackedUsers, **Testimonials (modération + génération de liens)**
- Page /documentation listant tous les endpoints API

## Implemented (2026-04-28) — Tracked Users + Webhooks update
✅ Bug fix : 6 modales admin (Clients, Interventions, Tracked Users, Case Studies, Documents, Testimonials) qui ne s'ouvraient pas — refactor `editing` state → `isOpen` state séparé.
✅ **Messages reçus → Utilisateur suivi** : bouton "Enregistrer" par message (POST /admin/contacts/{id}/save-as-tracked-user) avec modale (client + rôle + service). Validation email syntaxe (regex). Badge "Enregistré" si déjà fait.
✅ **Rôles utilisateur suivi (enum)** : Consultation / Edition / Moderation / Administrateur / Superviseur. Validation backend. Liste exposée via GET /admin/meta/tracked-roles.
✅ **Filtre + groupement par client** sur /admin/tracked-users. Colonne "Mis à jour".
✅ **Code client** (`client_code`) sur les fiches clients (utilisé pour la numérotation des interventions).
✅ **Numérotation des interventions** : `INT-AAAA-CODE-NNNN` séquentiel par (client_id, année). Compteurs dans `db.counters`.
✅ **Webhook Interventions** : à chaque create/update, POST fire-and-forget vers `{base_url}/{action}/{client_code}/{numero}` avec body JSON intervention complète. Auth : Aucune | Bearer | Basic. UI dans /admin/settings.
✅ **Horodatages** : `created_at` + `updated_at` sur Interventions, Clients, Tracked Users (les autres collections les avaient déjà).

## Implemented (2026-04-28) — Catégories documents éditables + Client Primaire (Superviseur)
✅ **Catégories de documents éditables** (CRUD inline depuis /admin/documents) :
  - Endpoints : GET/POST/PUT/DELETE /admin/document-categories + GET /document-categories (public).
  - Auto-seed des 3 catégories par défaut : Catalogue (catalog), Documentation, Annonce (announcement) — non supprimables, libellés modifiables.
  - Renommage du slug propage automatiquement à tous les documents existants.
  - UI : bouton "Catégories" sur la page Documents → modale CRUD (ajout, édition libellé+slug, suppression sauf défaut, garde-fou "X documents l'utilisent").
✅ **Client Primaire (Superviseur)** :
  - Nouveau rôle `superviseur` ajouté à `users.role` (en plus de `client` et `admin`).
  - Endpoints : POST /admin/clients/{id}/set-primary (force role=superviseur), POST /admin/clients/{id}/unset-primary (revert role=client).
  - Un seul client primaire à la fois (les précédents sont automatiquement rétrogradés).
  - UI : icône ★ dans la liste Clients, badge "superviseur", ligne en surbrillance bleutée. Bouton ★ pour set, ★̶ pour unset.
  - Endpoint protégé portail : GET / PUT /me/admin-clients (le Superviseur voit/édite les comptes clients ayant role=admin). Dépendance `get_current_supervisor`.
  - Page portail Superviseur (/portal/admin-clients) : NON encore implémentée — backlog P1.

## Implemented (2026-04-28) — Icônes personnalisables + Catégories Clients + Mappemonde déploiements
✅ **IconPicker réutilisable** (`/components/IconPicker.jsx`) : 41 icônes lucide curatées (pictos métiers : Stethoscope, Pill, Store, Factory…) + palette 10 couleurs + sélecteur HTML natif pour couleur custom.
✅ **Catégories de documents** : ajout `icon` + `color`. UI : picker visuel intégré dans la modale "Catégories". Affichage de l'icône colorée à côté du libellé sur chaque carte de document.
✅ **Catégories de clients** (nouveau collection `client_categories`) : 8 catégories par défaut auto-seedées (Clinique, Pharmacie, Commerce, Alimentation, Industrie, Éducation, Bureautique, Autre) avec icône et couleur. CRUD complet via /admin/client-categories (admin) + /client-categories (public).
✅ **Champs `category_slug` / `country` / `city`** ajoutés au modèle utilisateur. Affichés dans la table /admin/clients (colonnes Catégorie + Pays). Édition dans le formulaire client.
✅ **Mappemonde "Déploiements"** :
  - Modèle `deployments` avec clé composite (solution_name, country). Endpoints CRUD admin /admin/deployments + endpoint public groupé /deployments.
  - Nouvelle page admin `/admin/deployments` (3 cartes statistiques + table CRUD). Lien dans la sidebar.
  - Composant React `<DeploymentsMap>` sur la page d'accueil : SVG mondial via `@vnedyalk0v/react19-simple-maps` (compat React 19). TopoJSON local `/public/countries-110m.json` (110m simplified, 106KB) pour éviter les soucis SRI/CORS du fork.
  - Marqueurs bleus avec rayon proportionnel au nombre d'installations. Tooltip flottant au survol affichant solution + nombre + ville.
  - Curated set ~40 pays africains et internationaux pour le placement des marqueurs (centroides approximatifs). Fallback partiel sur première lettres si nom non trouvé.

## Implemented (2026-04-28) — Mappemonde mondiale + zoom automatique
✅ **Couverture mondiale** : `COUNTRY_COORDS` étendu à ~140 pays (Afrique complète, Europe, Amériques, Asie, Océanie). Aliases FR/EN/avec accents pour matching robuste. Fallback intelligent sur normalisation NFD (accents).
✅ **Zoom auto-adaptatif** : `projectionConfig` calcule dynamiquement `rotate` (centre lng), `center` (centre lat) et `scale` à partir du bounding box des marqueurs avec padding (~20% min). Si aucun déploiement, vue mondiale par défaut.
✅ **Marqueurs et tuiles cliquables** → modale détaillée par pays :
  - Header : nom + total installations + nb villes + nb solutions
  - Liste détaillée des solutions installées (nom, ville, date d'installation, compteur)
  - Graphique d'évolution cumulative des installations dans le temps (recharts AreaChart avec dégradé bleu)
  - Tooltip Recharts français au survol des points
  - Backend public `/deployments` enrichi avec `created_at` + `updated_at` par solution

## Implemented (2026-04-29) — Filtre solution + Blacklist IP + Vidéo Hero + Logo Client + Assistant virtuel
✅ **Filtre par solution** sur la mappemonde : pills cliquables (Toutes / Aizenta / PharmaPlus / …) qui restreignent les marqueurs et recalculent stats + zoom auto.
✅ **Blacklist IP** :
  - Collection `blacklisted_ips` + middleware FastAPI sur tous les `/api/*` (sauf endpoints de gestion).
  - Supporte IP simples (`192.168.1.42`) et plages CIDR (`10.0.0.0/24`). Validation `ipaddress`.
  - Trust X-Forwarded-For (Kubernetes ingress).
  - Cache des CIDRs en mémoire, rechargé à chaque add/delete.
  - Page admin `/admin/blacklist` : formulaire + table CRUD avec motif optionnel.
✅ **Vidéo Hero paramétrable** :
  - 8 nouveaux champs sur Settings : `hero_video_enabled`, `hero_video_url`, `hero_video_title`, `hero_video_description`, `hero_video_autoplay`, `hero_video_loop`, `hero_video_muted`, `hero_video_poster_url`.
  - Upload MP4 (max 80 Mo) via `/admin/upload` existant.
  - Composant `<HeroVideoSection>` sur la page d'accueil entre Hero et Mappemonde, ne s'affiche que si `enabled` + `url`.
  - UI dans /admin/settings (section "Vidéo de la page d'accueil").
  - Endpoint public `/company-info` enrichi avec `hero_video`.
✅ **Logo client + sidebar portail** :
  - Champ `logo_url` sur User (upload via fiche client admin).
  - Endpoint `/me/branding` qui retourne le bon logo (logo client ou logo SAWALI).
  - Tracked-users héritent du logo de leur client_id (lookup par email → tracked_users → client).
  - Sidebar du portail (`PortalLayout`) affiche le logo client à la place de SAWALI quand un utilisateur de ce client est connecté.
✅ **Assistant virtuel (chatbot Liluvine / JotForm)** :
  - Bouton flottant bottom-right présent sur toutes les pages (public + portail) via `<VirtualAssistant>` racine dans App.js.
  - Reproduit le comportement du snippet HTML : popup **responsive** (90% du viewport, capped 720×640), paramètre `parentURL=` ajouté automatiquement, fenêtre nommée pour réutilisation.
  - **Bouton lui-même responsive** : icône seule 48×48 sur mobile (<640px), label visible à partir de tablette, padding et taille de texte qui croissent jusqu'à 4K.
  - 4 paramètres dans /admin/settings : enabled, URL, label, couleur (color picker + champ hex).
  - Bouton dismissible pour la session (sessionStorage) sans toucher à la config admin.
  - Auto-seed des defaults à l'URL JotForm `0199e26b35a87a6ea156d196e3e180731e7d` + libellé "Liluvine — Support Technique" + couleur `#0075E3`.
  - Backfill automatique au démarrage pour les bases existantes (n'écrase pas les overrides admin).

## Implemented (2026-04-29) — Rapports & Suivis (WYSIWYG) + Document logs + File icons + Tracked-user passwords + Notes webhook
✅ **Rapports & Suivis** dans l'espace utilisateur :
  - Endpoints `/me/notes/{kind}` (GET/POST/PUT/DELETE) + `/me/notes-summary` (compteurs).
  - Page `/portal/notes/:kind` et `/admin/notes/:kind` avec un éditeur **WYSIWYG complet** (contentEditable + execCommand) : gras, italique, souligné, barré, h2/h3, citation, code, listes (puces/numérotées), alignement, couleurs de texte, surlignage, lien, undo/redo, effacer la mise en forme.
  - **Cartes Rapports/Suivis** ajoutées sur le tableau de bord client ET admin (compteurs + dernière mise à jour).
  - Toggles d'affichage dans /admin/settings (`show_reports_button`, `show_suivis_button`).
✅ **Historique de téléchargement** par document :
  - Collection `document_logs` enregistre upload + download (file_id, user_id, ip, durée, user-agent).
  - Endpoint admin `/admin/document-logs?file_id=...` + modale "Historique" dans /admin/documents avec compteurs et tableau (date, utilisateur, IP, durée).
✅ **Icônes par type de fichier** : librairie `/lib/fileIcons.js` étendue à 50+ extensions (PDF, Word, Excel, PowerPoint, images, audio, vidéo, archives, code, eBooks, CAD, design Apple iWork). Affichage automatique avec couleur dédiée + extension .EXT en sous-titre. Le clic sur l'icône télécharge le fichier.
✅ **Mot de passe pour utilisateur suivi** :
  - Endpoint `/admin/tracked-users/{id}/set-password` qui crée un pont vers la collection `users` (role=client) et permet le login via /auth/login + OTP standard.
  - Endpoint `/admin/tracked-users/{id}/revoke-password` pour révoquer l'accès.
  - UI dans /admin/tracked-users : icône clé, modale `password-dialog` avec générateur, copy-to-clipboard, validation 8+ chars, indicateur "Activé/Aucun" dans la table.
✅ **Webhook Rapports & Suivis** :
  - Settings `notes_webhook_*` (enabled, url, auth_type none/bearer/basic, token, basic_user, basic_pass).
  - À chaque create/update/delete de note → POST fire-and-forget `{url}/{action}/{kind}/{note_id}` avec body JSON {action, kind, note, author, fired_at}.
  - UI Section "Webhook Rapports & Suivis" dans /admin/settings.
✅ **Bonus** : safeguard server-side qui ignore "********" lors d'un PUT /admin/settings pour éviter d'écraser les secrets masqués (smtp_password, google_client_secret, recaptcha_secret_key, webhook_token, webhook_basic_pass, notes_webhook_token, notes_webhook_basic_pass, tracking_auth_header).

## Implemented (2026-04-29) — Compteur de visites + Horloge live sur Home
✅ **Compteur de visites** sur la page d'accueil publique :
  - Endpoint public `GET /api/visits/count` → `{enabled, count}` où count = visites réelles + offset.
  - Endpoint admin `POST /api/admin/visits/reset` qui règle l'offset à `-(real_count)` pour afficher 0.
  - Settings : `visits_counter_enabled` (toggle) + `visits_counter_offset` (offset manuel modifiable).
  - UI admin : section "Compteur de visites" dans /admin/settings avec toggle + champ offset + bouton "Réinitialiser à 0".
✅ **Horloge live + ticker glass-morphism** sur la page d'accueil :
  - Composant `<HomeStatsTicker>` (top du hero, au-dessus du kicker SAWALI).
  - Pill 1 : date complète + heure mise à jour chaque seconde (capitalize, `tabular-nums`).
  - Pill 2 : compteur de visites avec icône œil, refresh toutes les 30s, ring accent bleu.
  - Style : backdrop-blur-md, `bg-[#0E1F3D]/70`, ring `sawali-blue/30`, ombre douce, responsive (date courte sur mobile).

## Implemented (2026-04-29) — Itération 4 : RBAC tracked-roles + Rapports/Suivis/Interventions enrichis + Access Logs
✅ **Rôles élevés (tracked) en self-service** : Modération / Administrateur / Superviseur peuvent désormais créer rapports, suivis et interventions depuis le portail (`/me/notes/{kind}` et `/me/interventions`).
✅ **Suppression restreinte** : DELETE rapport/suivi/intervention réservé à Admin/Superviseur (incl. tracked Administrateur/Superviseur). 403 sinon.
✅ **Suivis & interventions** : `client_id` et `event_date` (datetime-local) **requis** à la saisie. Rapports : seul l'horodatage automatique.
✅ **Heure de descente** (`descent_time` HH:MM) paramétrable dans `/admin/settings`. Au-delà de descent_time + 1h, l'enregistrement de tout rapport/suivi/intervention renvoie HTTP 403 « verrouillé ».
✅ **Auto-numéros** : `RPT-YYYY-NNNN`, `SUI-YYYY-NNNN`, `INT-YYYY-CODE-NNNN` (existant). IP du créateur enregistrée systématiquement.
✅ **Galerie d'images** (max 10 par enregistrement) : uploader inline, miniatures sur la fiche, lightbox en clic. Endpoint portail `/me/upload` accessible aux rôles Modération+.
✅ **Notation 5 étoiles** : seuls Admin/Superviseur peuvent noter. La note est **personnelle** (visible seulement par celui qui la pose). Endpoints `/me/ratings/{kind}/{target}` POST/DELETE. Listes décorées avec `my_rating`.
✅ **Documents** : Modération+ voit + uploade tous les documents (cross-clients) via `/me/documents` ; suppression réservée Admin/Superviseur.
✅ **Messages reçus** : page admin appelle désormais `/me/contacts/{id}/save-as-tracked-user` qui auto-génère un mot de passe (≥12 chars), crée le compte bridgé, **envoie l'email** (si SMTP configuré) et retourne le mot de passe à l'écran (copié dans le presse-papiers, toast 12s).
✅ **Logs d'accès portail** : nouveau collection `access_logs` ; `PortalLayout` POST `/me/access-log` à chaque changement de route (module + page) ; nouvelle page `/admin/access-logs` avec recherche, stats top modules, et **export CSV**. Accès réservé Admin/Superviseur.
✅ **Verrouillage 1h après création** des rapports/suivis : édition refusée 1h après `created_at` (Admin/Superviseur restent libres).
✅ **Heures d'activité** : champs ouverture/fermeture déjà existants désormais explicitement labélisés et documentés ; nouveau champ « Heure de descente » à côté.
✅ **RBAC propagé** : changement de rôle sur un tracked-user via PUT met à jour `users.tracked_role` du compte bridgé (correctif iter4).

## Implemented (2026-04-30) — Itération 5 : Formations Spécialisées (catalogue + modules + tracking + Q/R)
✅ **Module Admin** `/admin/formations` :
  - CRUD formations (nom, description, dispo, accès libre/payant, prix, crédits par défaut, image de cover).
  - Panneau latéral pour CRUD modules (nom, ordre, capture d'écran, chemin logiciel, contenu HTML enrichi, **API REST POST paramétrable** + auth none/bearer/basic).
  - Onglet « Inscrits » : table avec état, modules vus, crédits, temps total, dernier accès, actions (ajuster crédits, annuler).
✅ **Module Portail** `/portal/formations` (visible uniquement pour utilisateurs suivis) :
  - Catalogue de cartes avec inscription en un clic.
  - Vue détail `/portal/formations/:fid` : navigation par modules, capture d'écran, contenu enrichi, **chrono d'affichage** (POST visit + close avec sendBeacon pour survivre au unload).
  - **Q/R intégré** : question saisie → forward POST vers `module.api_url` configuré côté admin → réponse affichée.
  - Notation 5★ par formation par utilisateur (mémorisée dans `ratings.kind=formations`).
✅ **État auto** calculé à chaque lecture : `inscription` → `commencée` → `en_cours` → `terminée` selon `modules_seen / modules_total`. `suspendue` si > 7j sans accès. `annulée` modifiable manuellement par admin (verrouillage).
✅ **Crédits** : achetés − consommés = disponibles. Endpoint admin `POST /admin/formations/{fid}/enrollments/{user_id}/credits {credits_delta}`.
✅ **Sidebar conditionnelle** : lien « Formations Spécialisées » filtré via `trackedOnly:true` + `isTracked = !!tracked_user_id || !!tracked_role`.
✅ **Backend public DTO** : exposé `tracked_user_id` en plus de `tracked_role` et `parent_client_id` pour permettre les contrôles côté frontend.
✅ **Tests** : 10/10 backend + frontend admin (modal formation + module avec api_url & auth) ; portal corrigé.

## Implemented (2026-04-30) — Itération 6 : PasswordInput + Traces API + PDF dans Rapports/Suivis
✅ **Composant `<PasswordInput>`** réutilisable avec œil cliquable (Eye/EyeOff de Lucide). Utilisé sur :
  - `/login` (mot de passe)
  - `/admin/settings` (smtp_password, webhook_token, webhook_basic_pass, notes_webhook_token, notes_webhook_basic_pass — via wrapper Input)
  - `/admin/tracked-users` (modale set-password)
  - `/admin/formations` (api_token, api_basic_pass)
✅ **Traces API** — backend collection `api_traces` :
  - `POST /me/api-trace` (auth) reçoit chaque requête mutante (POST/PUT/PATCH/DELETE) capturée par l'axios interceptor.
  - `GET /admin/api-traces` (super-admin uniquement, contrôlé via `SUPER_ADMIN_EMAIL` env, fallback `admin@sawalismartsystems.com`) avec filtres `q`, `method`, `only_errors`, `user_email`.
  - `GET /admin/api-traces/export.csv` export CSV.
  - `DELETE /admin/api-traces` purge globale.
  - **Redaction des secrets** : `password`, `passwd`, `secret`, `token`, `api_key`, `recaptcha`, `otp`, `code`, `session_token`, `webhook_*`, `smtp_password`, etc. → remplacés par `[REDACTED]` (côté frontend ET côté backend en double sécurité).
  - Endpoints filtrés (skip) : `/me/access-log`, `/me/api-trace` (anti-récursion), `/track`, `/visits/count|trend`, `/auth/captcha-config`, `/me/formations/*` (visit/close).
  - **Toast furtif** « Opération effectuée avec succès » (1.5 s) sur chaque succès 2xx (sauf endpoints noisy + `/auth/login|verify-otp|resend-otp` déjà toastés).
  - Page `/admin/api-traces` (sidebar visible uniquement pour le super-admin) avec table, stats (total, erreurs, utilisateurs, durée moyenne), modal détail avec body JSON pretty-printed (request + response).
✅ **PDF + autres documents dans Rapports/Suivis** :
  - `<ImageUploader>` renommé conceptuellement → accepte désormais images, PDF, Word, Excel, PowerPoint, TXT, CSV (max 25 Mo, max 10).
  - `<AttachmentThumb>` : preview <img> pour les images, sinon icône colorée + extension via `getFileIcon()`.

## Test Credentials
- Admin: `admin@sawalismartsystems.com` / `Admin@Sawali2026` (auto-seeded)
- Tracked users : créer puis utiliser /admin/tracked-users → bouton "clé" pour définir un mot de passe → login via /login standard.

## Backlog (P1/P2)
- P1 : Refactor `server.py` (~2700 lignes) en routers `/app/backend/routes/` (auth, public, admin, portal, files).
- P1 : Connecter SMTP (Gmail App Password) pour réellement envoyer les OTP
- P1 : Connecter Google reCAPTCHA (créer clés site/secret)
- P1 : Connecter Google Calendar (créer projet GCP, OAuth 2.0 client, autoriser le compte sup.alphasofti@gmail.com)
- P2 : Editeur Rich Text plus complet (TipTap) au lieu de l'éditeur HTML basique
- P2 : Notifications email/SMS lors d'un RDV (statut changements)
- P2 : Pagination & recherche avancée sur les listes admin
- P2 : Export CSV des interventions / RDV
