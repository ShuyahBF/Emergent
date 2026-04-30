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

## Implemented (2026-04-25 → 2026-04-30)
Backend complet (61+ endpoints, RBAC, webhooks, APScheduler, IP blacklist, traces API redactées, formations LMS, DB Explorer générique, dashboard santé).

Frontend responsive complet :
- Public : Home (vidéo hero, mappemonde déploiements, ticker visites/horloge, NPS), Missions, Spécialisations, Catalogue, Témoignages, RDV, Contact, Études de cas, Blog, Newsletter, Feedback NPS.
- Auth : Login + reCAPTCHA + OTP (avec dev_otp banner si SMTP non configuré).
- Portal client : Dashboard, RDV, Documents (PDF viewer), Interventions, Suivi utilisateurs, Rapports/Suivis (WYSIWYG + PDF/image), Formations spécialisées (LMS).
- Admin : Dashboard, Clients, RDV, Interventions, Documents, Formations, Contenus, Études de cas, Blog, Newsletter, Trafic, Déploiements, Blacklist IP, Logs d'accès, **Traces API**, **Santé applicative**, **Explorateur DB** (super-admin), Messages, Témoignages, Utilisateurs suivis, Paramètres.
- Composants : `<PasswordInput>`, `<HomeStatsTicker>`, `<DeploymentsMap>`, `<HeroVideoSection>`, `<VirtualAssistant>` (Jotform), `<ImageUploader>` (PDF/Word/Excel/PowerPoint/CSV/TXT/images, max 10×25 Mo), `<RouteTracker>`.

Voir `CHANGELOG.md` ci-dessous pour le détail itération par itération.

---

## CHANGELOG

### 2026-04-30 — Itération 10 : Auth Checker (sentinelle horaire du flow login)
✅ Sonde horaire 4 étapes (admin_user_exists → jwt_mint_decode → auth_me_http → login_endpoint_responsive) exécutée par APScheduler chaque heure (Africa/Abidjan).
✅ Persistence dans `db.auth_checks` (capped 200 entrées). Endpoints : `POST /admin/health/auth-check`, `GET /admin/health/auth-check/latest`, `GET /admin/health/auth-check/history`.
✅ Banner sur `/admin/health` : statut vert/rouge, détail des 4 étapes avec durée, dots historique des 24 derniers contrôles, bouton "Vérifier maintenant".
✅ Alerte email + webhook (vers `health_email_to` + `health_webhook_url`) si une sonde échoue, conditionnée par toggle `health_auth_check_enabled` dans `/admin/settings`.
✅ Collection `auth_checks` whitelistée dans le DB Explorer.

### 2026-04-30 — Itération 9 : Bug fix critique login flow
✅ **Bug** : après saisie OTP, l'espace client/admin s'affichait brièvement puis l'utilisateur était redirigé sur `/login`.
✅ **Cause racine** : l'intercepteur Axios de tracing API tirait un `POST /me/api-trace` sur la réponse de `/auth/verify-otp` AVANT que `login()` n'ait sauvegardé le token dans `localStorage`. Le `/me/api-trace` partait donc sans Authorization → 401 → l'intercepteur d'erreur effaçait `localStorage` et redirigeait vers `/login`.
✅ **Fix** (`/app/frontend/src/lib/api.js`) :
  - `TRACE_SKIP_PATTERNS` : `"/auth/captcha-config"` remplacé par `"/auth/"` (skip de tous les endpoints d'auth — login, verify-otp, resend-otp).
  - Nouveau `NO_LOGOUT_ON_401 = ["/me/api-trace", "/me/access-log", "/track"]` : les 401 sur endpoints de télémétrie ne déclenchent JAMAIS de logout forcé (filet de sécurité).
✅ Vérifié en bout-en-bout via screenshot : login + OTP → `/admin` rendu, token+user en localStorage, toast "Connexion réussie".

### 2026-04-30 — Itération 8 : DB Explorer + filtres Auteur/Contenu
- `/admin/db-explorer` (super-admin) : sélecteur de collection, filtres dynamiques (eq, regex, gte/lte, ne), tri, export CSV (séparateur ',' ou ':'), export JSON, modal détail JSON pretty-printed, redaction automatique des champs sensibles.
- `GET /api/admin/db/{collection}/...?author=X&q=Y` : recherche par auteur (regex case-insensitive sur `owner_email`) + recherche full-text dans `title`/`content_html`/`tags`.
- `GET /api/me/notes/{kind}/authors` : liste agrégée des auteurs distincts (pour dropdown).
- UI `UserNotes.jsx` : barre `notes-filters-{kind}` avec `notes-filter-author` (combobox), `notes-filter-q` (input), `notes-filter-apply` (submit), `notes-filter-clear` (apparaît uniquement si filtre actif).
- 11/11 backend pytest + 4/4 critical frontend flows pass.

### 2026-04-30 — Itération 7 : Dashboard santé + alertes + API générique
- `/admin/health` (super-admin) : stats `api_traces` (total, erreurs ≥400, taux d'erreur, durée moy., histogramme/heure, top endpoints en erreur, top users), sélecteur de fenêtre 1h/6h/24h/3j/7j/14j, boutons "Test alerte" + "Hebdo maintenant".
- Alertes temps réel : sur `status >= 400`, fire-and-forget email + webhook (sémaphore `asyncio.Semaphore(5)`).
- Rapport hebdomadaire APScheduler : cron Vendredi 05:00 Africa/Abidjan → email HTML + webhook (toggle `health_weekly_enabled`).
- API REST générique `/api/admin/db/{collection}` (super-admin, 30+ collections whitelistées) avec filtres dynamiques + redaction.

### 2026-04-30 — Itération 6 : PasswordInput + Traces API + PDF dans notes
- `<PasswordInput>` réutilisable (Eye/EyeOff Lucide) déployé sur Login, Settings (smtp, webhooks, notes_webhook), Tracked Users (set-password), Formations (api_token, basic_pass).
- Traces API : collection `api_traces`, redaction backend+frontend, page `/admin/api-traces` super-admin avec stats + modal détail. Toast furtif "Opération effectuée" sur 2xx (1.5s).
- PDF/Word/Excel/PowerPoint/CSV/TXT acceptés dans Rapports/Suivis (max 10 fichiers × 25 Mo).

### 2026-04-30 — Itération 5 : Formations Spécialisées (LMS)
- Admin `/admin/formations` : CRUD formations + modules (capture, contenu HTML, API REST par module avec auth bearer/basic), onglet Inscrits avec ajustement crédits.
- Portail `/portal/formations` (tracked-users only) : catalogue, vue détail avec modules, chrono d'affichage (sendBeacon), Q/R (forward POST → module.api_url), notation 5★.
- État auto : inscription → commencée → en_cours → terminée. Suspendue si > 7j. Annulée verrouille manuellement.

### 2026-04-29 — Itération 4 : RBAC tracked-roles + Notes/Interventions enrichies
- Modération/Administrateur/Superviseur peuvent créer rapports/suivis/interventions depuis le portail.
- Suppression Admin/Superviseur uniquement.
- `descent_time` paramétrable + verrouillage 1h après descent_time.
- Galerie images max 10/note, lightbox.
- Notation 5★ personnelle (Admin/Superviseur).
- `/admin/access-logs` avec recherche + export CSV.

### 2026-04-29 — Compteur de visites + Horloge live
- `<HomeStatsTicker>` glass-morphism sur Home (date+heure live, compteur visites refresh 30s).
- Endpoint admin `/admin/visits/reset` (offset = -real_count).

### 2026-04-29 — Rapports/Suivis WYSIWYG + Document logs + File icons + Tracked-user passwords + Notes webhook
- `/me/notes/{kind}` (GET/POST/PUT/DELETE) + WYSIWYG (gras, italique, h2/h3, listes, alignement, couleurs, undo/redo).
- `document_logs` collection + modale "Historique" par document.
- 50+ extensions de fichiers reconnues avec icônes colorées dédiées.
- Mot de passe tracked-user via `/admin/tracked-users/{id}/set-password`.
- Webhook notes : `{url}/{action}/{kind}/{note_id}`.

### 2026-04-29 — Filtre solution + Blacklist IP + Vidéo Hero + Logo Client + Assistant virtuel
- Mappemonde : pills filtre par solution.
- Middleware blacklist IP (single + CIDR), trust X-Forwarded-For.
- Vidéo hero paramétrable (8 champs settings).
- Logo client + sidebar portail (héritage tracked-users).
- `<VirtualAssistant>` (Jotform Liluvine) responsive bottom-right.

### 2026-04-28 — Mappemonde + zoom auto + Catégories + Client primaire + Tracked Users
- `<DeploymentsMap>` SVG mondial (`@vnedyalk0v/react19-simple-maps`) avec ~140 pays, zoom auto sur bounding box des marqueurs.
- Modale détail pays (liste solutions, graphe cumulative recharts).
- Catégories documents/clients éditables avec icônes lucide + couleurs.
- Numérotation interventions `INT-AAAA-CODE-NNNN`.
- Webhook interventions configurable (none/bearer/basic).
- Rôles tracked : Consultation/Edition/Moderation/Administrateur/Superviseur.

### 2026-04-25 — MVP initial
- Backend FastAPI complet (auth, public, portal, admin, documents, settings, NPS feedback).
- Frontend marketing + portal client + admin console.
- Google Calendar OAuth flow, reCAPTCHA v2, SMTP OTP.
- Auto-seed admin + default contents.

---

## Test Credentials
- Admin: `admin@sawalismartsystems.com` / `Admin@Sawali2026` (auto-seeded)
- Tracked users : créer puis utiliser /admin/tracked-users → bouton "clé" pour définir un mot de passe → login via /login standard.

## Backlog (P1/P2)
- **P0** : Refactor `server.py` (4143 lignes) en routers `/app/backend/routes/` (auth, public, admin, portal, files, notes, db, health).
- **P1** — UI polish iter 8 : remplacer `<select>` natifs par Shadcn `<Select>` dans AdminDbExplorer ; badge "champs sensibles masqués" ; debounce 300ms sur `notes-filter-q` ; combobox auteur si > 30 entrées.
- **P1** : Stripe Checkout pour Formations payantes (reporté par l'utilisateur).
- **P1** : Connecter SMTP réel (Gmail App Password) pour OTP en production.
- **P1** : Connecter Google reCAPTCHA (clés site/secret).
- **P1** : Connecter Google Calendar (créer projet GCP, OAuth 2.0 client, autoriser sup.alphasofti@gmail.com).
- **P2** : Editeur Rich Text TipTap (vs execCommand actuel).
- **P2** : Notifications email/SMS lors d'un changement de statut RDV.
- **P2** : Pagination & recherche avancée sur les listes admin.
- **P2** : Export CSV des interventions / RDV.
