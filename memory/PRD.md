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

### 2026-05-03 — Itération 25 : Automations CRM (WhatsApp triggered)
✅ Backend : nouvelle collection `automations` + 5 endpoints admin (`GET /events`, GET liste, POST, PUT, DELETE).
✅ 4 événements supportés : `appointment.created`, `appointment.reminder` (J-1 cron horaire), `intervention.created`, `client.created`.
✅ Helper central `_emit_event(event, target)` : résout le destinataire (client_id/tracked_user_id/phone), construit le ctx de variables avec `extra_ctx` (ex: `{appointment_date}`), traite immediate (delay=0 → `_wa_send_template` direct + log) OU delayed (delay>0 → planifie via `whatsapp_schedules` réutilisé) + incrémente `trigger_count`. Branches no-phone, disabled, unsupported event toutes idempotentes.
✅ Hook fire-and-forget (`asyncio.create_task`) ajouté dans 4 routes : `POST /me/appointments`, `POST /admin/clients`, `POST /admin/interventions`, `POST /me/interventions`.
✅ Cron horaire `_appointment_reminder_cron` (minute=15) : balaye les RDV dans la fenêtre `[now+23h, now+25h]` sans `reminder_sent_at`, émet `appointment.reminder` puis stamp.
✅ Frontend `AdminAutomations.jsx` (`/admin/automations`) : liste avec toggle ON/OFF, modal create/edit pré-rempli (sélection événement → template Meta → variables avec picker tokens → délai). Bouton désactivé + bandeau si Meta non configuré. Sidebar admin enrichie avec lien "Automations" (icône Zap).
✅ Tests : 20/20 pytest iter14 + 53/53 cumulé (iter12+13+14, ~14s). Couvre validation 400, CRUD complet, 5 branches de `_emit_event` (immediate/delayed/no-phone/disabled/unsupported), intégration via POST /admin/clients + /admin/interventions, cron `_appointment_reminder_cron`, frontend create→toggle→edit→delete avec injection JWT.

### 2026-05-03 — Itération 24 : Variables dynamiques pour templates WhatsApp
✅ Backend : 4 helpers réutilisables — `_VAR_TOKEN_RE`, `_render_variable(value, ctx)`, `_build_recipient_ctx(kind, user_doc, phone, label)` (retourne `{full_name, company, phone, email, client_code, today, tomorrow}`), `_build_components(variables, ctx)` qui produit `[{type:'body', parameters:[{type:'text', text:rendered}, …]}]` ou `None`.
✅ Backend : `AdminBulkSendRequest.variables` + `AdminScheduleCreate.variables` (`Optional[List[str]]`). Bulk-send et runner cron substituent les tokens **par destinataire** au moment de l'envoi.
✅ Endpoint `GET /api/admin/messaging/variable-tokens` → liste les 7 tokens disponibles avec libellé FR + exemple (auto-renseigne le picker frontend).
✅ Frontend `AdminMessaging.jsx` : nouvelle section "Variables dynamiques" qui détecte automatiquement les `{{N}}` du body Meta du template sélectionné, affiche un input par variable + un dropdown "+ Insérer…" pour insérer un token. Bouton "Aperçu" qui rend le message final pour le 1er destinataire sélectionné.
✅ Tests : 21/21 pytest iter13 + 47/47 cumulé (iter11+iter12+iter13). `test_sawali_iter13.py` couvre helpers unit + `/variable-tokens` endpoint + bulk-send avec variables monkeypatch capturant les `components` résolus + scheduler runner avec variables. `conftest.py` mutualise un event_loop session-scope pour stabiliser motor.
✅ Test harness fix : remplacé `asyncio.run(...)` par `event_loop.run_until_complete(...)` dans iter12 + iter13 pour éviter le motor loop-binding error en cumulé.

### 2026-05-03 — Itération 23 : Planification d'envois WhatsApp
✅ Backend : `whatsapp_schedules` collection + 3 endpoints admin
- `GET /api/admin/messaging/schedules` (liste, admin-only).
- `POST /api/admin/messaging/schedules` (validation : destinataires requis, template requis, date future uniquement).
- `DELETE /api/admin/messaging/schedules/{id}` : hard-delete si `status=pending`, soft-cancel si `running|done`.
✅ Cron job APScheduler `CronTrigger(minute='*')` — chaque minute, drain des planifications dues (atomic claim pending→running→done/failed) avec résolution des contacts (client/tracked/raw), envoi via `_wa_send_template`, log dans `whatsapp_messages` (`schedule_id`, `scheduled=true`, `bulk=true`) et `result_summary` détaillé `{requested, sent_ok, sent_ko, skipped_count, skipped, results}`.
✅ Frontend `AdminMessaging.jsx` : section "Planifier un envoi" (titre, date, heure, bouton Planifier) + tableau "Envois programmés" avec statut coloré (En attente / En cours / Terminé / Échec / Annulé), bouton suppression sur pending/running, auto-refresh toutes les 30s pour voir les transitions en direct.
✅ Tests : 12/12 nouveaux pytest + 14/14 iter11 regression = 26/26 green (`test_sawali_iter12.py`, 3.85s solo / 6.79s combined). Frontend end-to-end create→display→cancel validé.

### 2026-05-03 — Itération 22 : Admin Formulaires + Messagerie WhatsApp groupée
✅ Sidebar admin : 2 nouveaux liens — "Formulaires" (`/admin/forms`) et "Messagerie WhatsApp" (`/admin/messaging`). Les routes Admin réutilisent les composants existants (FormsList, FormEditor, FormRunner, FormsAnalytics, FormAnalyticsDetail).
✅ Backend : 3 nouveaux endpoints admin
- `GET /api/admin/messaging/audience` → liste unifiée des clients + utilisateurs suivis avec `has_phone` pour filtrer les candidats à l'envoi.
- `POST /api/admin/messaging/bulk-send` → envoi groupé d'un template Meta à N destinataires ({kind:client|tracked|raw, id?, phone?}); retourne `{requested, sent_ok, sent_ko, skipped, results}`. Log complet dans `whatsapp_messages` avec `bulk=true`, `recipient_kind`, `recipient_label`.
- `GET /api/admin/messaging/history?limit=200` → historique d'envois (admin voit tout).
✅ Frontend `AdminMessaging.jsx` : onglets Clients/Utilisateurs suivis, recherche, sélection multi + "Tout sélectionner (avec tél.)", dropdown des templates Meta approuvés, langue, bouton "Envoyer à N". Barre d'envoi toujours rendue (désactivée tant que Meta n'est pas configurée + tooltip explicatif).
✅ Gate UX : bandeau jaune vers `/admin/settings` si WhatsApp non configuré (WABA ID / Phone Number ID / Token / App ID manquants).
✅ Historique complet (200 derniers) avec badge "groupé", statut OK/KO et erreur au survol.
✅ Fix : `TrackedUserCreate` / `TrackedUserUpdate` acceptent désormais `phone` (parité avec le contact→tracked-user path). Le formulaire admin `/admin/tracked-users` a un champ "Téléphone (WhatsApp)".
✅ Fix : audience endpoint lit maintenant `name` OU `full_name` (tracked_users stocke `name`, le résolveur tombait sur "—").
✅ Tests : 14/14 pytest (test_sawali_iter11.py, 4.2s) — tous les nouveaux endpoints admin + régression `/me/whatsapp/*` verts ; frontend 100% après fix barre d'envoi toujours rendue.

### 2026-05-02 — Itération 21 : Form Analytics Dashboard (global + per-form)
✅ Backend : 3 nouveaux endpoints `GET /api/me/forms-analytics` (global), `GET /api/me/forms/{id}/analytics` (détail), `GET /api/me/forms/{id}/analytics/export.csv` (export).
✅ Agrégation sans pipeline complexe : série temporelle par jour UTC, top auteurs, pays (via `geo.country`), auth vs anonyme, completion rate (soumissions / uses_count), 10 dernières soumissions.
✅ Scope : admin voit tout, client voit ses formulaires. `_require_owner_or_admin` enforce l'accès detail + CSV (403/404 corrects).
✅ CSV : UTF-8 BOM pour Excel, header dynamique `[id, date, auteur, type, email, pays, ville, ip, <labels des champs>]`, 1 ligne par soumission.
✅ Fix filtres de dates : `.isoformat()` sur les bornes avant `$gte/$lte` (car `created_at` est stocké en ISO string par `_now()`).
✅ Fix admin `is_mine` : me_list_forms court-circuite à `True` pour les admins → boutons Stats/Éditer/Partager/Supprimer visibles sur toutes les cartes.
✅ Frontend : 2 nouvelles pages React `FormsAnalytics.jsx` (global) et `FormAnalyticsDetail.jsx` (par formulaire), layout Shadcn-like, courbes Recharts (AreaChart + PieChart), barres horizontales pour les pays, KPI cards, quick-range (7j/30j/90j/1an), date pickers.
✅ Bouton "Analytics global" sur /portal/forms + bouton "Stats" par carte avec navigation vers `/portal/forms/:fid/analytics`.
✅ Export CSV côté front via `fetch` avec header `Authorization` + content-type guard + toast d'erreur explicite.
✅ Tests : 13/13 pytest passent (`/app/backend/tests/test_sawali_iter9.py`) + flows frontend validés (nav, KPI, timeseries, pie, pays, CSV download).

### 2026-05-02 — Itération 20 : Formulaires publics partageables (QR + URL courte)
✅ Endpoints publics (no auth) : `GET /public/forms/{id}` + `POST /public/forms/{id}/submission`. Fonctionnent uniquement si `is_public=True`.
✅ Index unique contourné pour les anonymes : `user_id = anon-{uuid[:8]}` → plusieurs soumissions depuis le même lien possible.
✅ Tracking IP source + nom/email optionnels du répondant + géolocalisation + timestamps complets.
✅ Page publique `/f/{fid}` (PublicForm.jsx) : dark theme SAWALI, grille 12 colonnes respectée, validation required côté client, success screen avec CheckCircle, multi-pages + navigation Précédent/Suivant.
✅ Composant `<ShareFormModal>` (QR 240×240 via api.qrserver.com + URL copyable + download PNG + open in new tab), accessible depuis FormsList (bouton "Partager" sur les formulaires publics) et FormEditor (bouton vert dans la barre d'outils).
✅ Validé e2e : toggle is_public → bouton Partager apparaît → modal avec QR/URL → scan/clic → formulaire public accessible → soumission anonyme OK (2/2 succès).

### 2026-05-02 — Itération 19 : Phases 5/4/3 complètes (badges, formulaires, répertoire+WhatsApp)
✅ **Phase 5 — Badges de notifications** : collection `user_module_visits` (unique par user+module), endpoints `GET /me/notifications/counts` + `POST /me/notifications/mark-seen`. 14 modules couverts (RDV, docs, interventions, rapports, suivis, formations + 8 admin). Frontend : fetch au mount/navigation/90s, affichage badge rouge (ring glass), auto mark-seen quand on navigue sur la page correspondante. Validé : admin_clients 6→0 après mark-seen.
✅ **Phase 4 — Formulaires dynamiques** : modèles FormField/FormPage/FormCreate/Update. Endpoints CRUD `/me/forms`, `/me/forms/{id}/import` (clone public form), `/me/forms/{id}/submission` (get/post avec auto-increment revisions_count), `/me/forms/{id}/submissions` (list pour owner/admin). Auto-numérotation `FORM-{client_code}-{NNNN}`. Frontend 3 pages : FormsList (catalogue avec filtre mine/public/all), FormEditor (12 types champs, multi-pages, grille 12 cols, toggle public/privé, reorder ↑↓), FormRunner (auto-prefill, géoloc, 3 boutons réinit/save/CSV, navigation pages).
✅ **Phase 3 — Répertoire + WhatsApp Business API Meta** : 
  - Settings admin (nouvelle section) : WABA ID, Phone Number ID, App ID, Access Token (masked), Verify Token (masked), langue par défaut.
  - Endpoints contacts : `GET/POST/PUT/DELETE /me/contacts` avec scope owner + shared dans client.
  - Endpoint WhatsApp : `POST /me/whatsapp/send` (appelle Graph API v21.0 avec template + language + components). `GET /me/whatsapp/history`. `GET /admin/whatsapp/templates` (liste templates approuvés).
  - Frontend `/portal/contacts` : table complète, modal d'édition (nom, société, tél, whatsapp, email, tags, partagé), modal WhatsApp (dropdown templates + envoi + résultat inline).
  - RBAC : envoi WhatsApp réservé aux rôles élevés (Modérateur/Admin/Superviseur) + client principal.
  - Collection `directory_contacts` + `whatsapp_messages` (log tentatives avec ok/status/message_id/error) indexées + whitelistées DB Explorer.
✅ Menu sidebar enrichi : "Formulaires", "Répertoire & WhatsApp" ajoutés. Badges rouges visibles (ex: Mes rendez-vous **3**, Trafic & Visites **99+**, Messages reçus **6**).

### 2026-05-02 — Itération 18 : Phase 2 — Liens externes cryptés (deep-links JWT 15min)
✅ JWT signé séparé (`LINK_JWT_SECRET` env) pour ne pas confondre avec l'auth JWT. Actions supportées : `login`, `rdv`, `appointments`, `document`, `intervention`, `contact`, `dashboard`, `formations`, `note`, `status`.
✅ 3 endpoints : `POST /integrations/build-link` (admin), `GET /integrations/link-actions` (admin), `GET /integrations/resolve-link?t=<jwt>` (public).
✅ Page `/launch?t=<jwt>` : décode le token, redirige vers la bonne route selon `action`, stash les claims en sessionStorage pour que Login pré-remplisse email + toast informatif.
✅ UI admin `/admin/integration-links` (super-admin) avec sélecteur action/TTL (5min → 24h), code client, username, target_id, bouton "Générer" → aperçu URL + token JWT + copy-to-clipboard.
✅ Menu sidebar : entrée "🔗 Liens cryptés" ajoutée.
✅ Validé via curl : token 300s généré + resolve-link retourne `{valid:true, action:'rdv', client_code:'ACME-001', ...}`, token invalide retourne `{valid:false, reason:'invalid'}`.

### 2026-05-02 — Itération 17 : Phase 1 — Fix webhooks POST API REST (kind singulier français + vrais codes HTTP + popup)
✅ **Bug kind pluriel anglais** : URLs webhook construisaient `.../reports/...` et `.../suivis/...` (valeurs internes). Désormais mappées en français singulier : `reports` → `rapport`, `suivis` → `suivi` (naturel pour les API clientes).
✅ **Bug tous les 200** : webhooks étaient fire-and-forget (`asyncio.create_task`) donc l'API répondait 200 instantanément sans attendre la réponse. Désormais **synchrones** (timeout 8s) et retournent `{enabled, fired, ok, status, url, body, error}` dans la réponse API du POST/PUT/DELETE.
✅ Composant `<WebhookResultModal>` monté globalement dans App.js : écoute l'event `sawali:webhook-result` et affiche popup centrée (backdrop flou, design vert/rouge selon status, URL, code HTTP, body JSON formaté, erreur, bouton copier).
✅ Axios intercepteur dans `lib/api.js` détecte `webhook_result.enabled` dans toute réponse et dispatche le CustomEvent automatiquement — zéro modification requise dans les pages métier existantes.
✅ Endpoints impactés : `POST /me/notes/{kind}`, `PUT /me/notes/{kind}/{id}`, `DELETE /me/notes/{kind}/{id}`, `POST /admin/interventions`, `PUT /admin/interventions/{id}`, `POST /me/interventions`.
✅ Validé via curl (backend renvoie bien webhook_result) + screenshot (modal rouge "HTTP 500" avec tous les détails).

### 2026-05-02 — Itération 16 : Performance fix critique (lenteurs login + navigation)
✅ **Bug** : `/api/track` (appelé à chaque navigation) bloquait jusqu'à 5s en attendant la géolocalisation IP via `ip-api.com` (rate-limited). Sous charge, les requêtes s'empilaient et bloquaient la file asyncio, ralentissant TOUT.
✅ **Fix géo non-bloquant** :
  - Geolocalisation déplacée en `asyncio.create_task` (post-réponse) → patch du document MongoDB en background.
  - Cache IP en mémoire (5000 entrées) → 1 seul appel par IP unique.
  - Timeout ip-api.com : 5s → 1.5s.
✅ **Forward externe non-bloquant** : si `tracking_enabled`, le POST vers le webhook externe configuré part aussi en background — ne bloque plus jamais `/track`.
✅ **Index MongoDB ajoutés** (idempotents) sur 13 collections : visits.datetime, visits.session_id, otps.expires_at, auth_checks.created_at, uptime_checks.created_at, incidents.started_at, incident_subscribers.email/tokens, user_notes (compound user_id+kind), interventions.client_id, access_logs.created_at, document_logs (compound), users.id, appointments.client_id, documents.client_id.
✅ **`/admin/visits/stats` optimisé** : aggregation MongoDB native (group + sort + limit) au lieu de charger 50000 docs en mémoire Python.
✅ Latences mesurées : `/track` 50-300ms (avant : jusqu'à 5000ms), `/admin/visits/stats` ~100ms (avant : plusieurs secondes), tous les autres endpoints 90-120ms.

### 2026-05-02 — Itération 15 : Abonnement email aux incidents (double opt-in + broadcast)
✅ Collection `incident_subscribers` (DB Explorer whitelisted) avec `confirmation_token` + `unsubscribe_token` uniques par abonné.
✅ 5 endpoints :
  - `POST /public/incidents/subscribe` (envoie email de confirmation — gère déjà-abonné + renvoi)
  - `GET /public/incidents/confirm?token=...` → redirect `/uptime?subscribe=confirmed`
  - `GET /public/incidents/unsubscribe?token=...` → redirect `/uptime?subscribe=ok`
  - `GET /admin/incident-subscribers` (avec compteur confirmed)
  - `DELETE /admin/incident-subscribers/{id}`
✅ Hook automatique dans `admin_update_settings` : sur `off→on` (incident ouvert) et `on→off` (résolu), broadcast email personnalisé à chaque abonné confirmé avec sévérité colorée, durée, lien `/uptime` + **lien de désabonnement unique**. Sémaphore 10 pour borner les bursts.
✅ Frontend `/uptime` : composant `<SubscribeForm>` (gradient bleu sawali, double opt-in expliqué, états idle/loading/success/error) + `<SubscribeFeedback>` qui affiche banner emerald/rose après confirm/unsubscribe (auto-clear 6s via setSearchParams).
✅ Validation : email syntaxique côté backend (Pydantic `EmailStr` + regex), gestion des cas déjà-abonné/non-confirmé/confirmation-renvoyée.

### 2026-04-30 — Itération 14 : Historique des incidents (timeline complète)
✅ Hook dans `admin_update_settings` qui détecte 3 transitions :
  - off → on : crée un nouvel incident `ongoing` avec `created_by`
  - on → off : marque `resolved`, calcule `duration_minutes`, enregistre `resolved_by`
  - on → on (edit) : append une `update` (ts, severity, message, by) à la timeline
✅ Collection `incidents` (whitelistée DB Explorer) avec id, severity, message, status, started_at, resolved_at, duration_minutes, updates[], created_by, resolved_by.
✅ Endpoints publics + admin :
  - `GET /api/public/incidents?limit=30` (no auth)
  - `GET /api/admin/incidents` + `DELETE /api/admin/incidents/{id}` + `GET /api/admin/incidents/export.csv`
✅ Section "Historique des incidents" sur `/uptime` avec composant `<IncidentItem>` :
  - Tag sévérité (icônes Info/AlertTriangle/AlertOctagon)
  - Badge "En cours" (pulse) ou "Résolu" (avec check)
  - Durée formatée (< 1 min, X h Y min)
  - Timeline verticale des updates (dots bleus + dot vert pour la résolution)
✅ Validé e2e : transitions on→on (edit)→off génèrent l'incident attendu avec sa timeline complète.

### 2026-04-30 — Itération 13 : Bandeau d'incident éditable (public + portail)
✅ 5 champs settings (`incident_banner_enabled`, `_severity` info/warning/critical, `_message`, `_link_url`, `_link_label`) + auto-stamp `_updated_at` quand le contenu change.
✅ Exposé dans `/api/company-info` (public, pas d'auth requise).
✅ Composant `<IncidentBanner>` ajouté à MarketingLayout ET PortalLayout (sticky en haut, au-dessus du nav).
✅ 3 sévérités avec palettes dédiées (info=sky, warning=amber, critical=rose), icônes Info/AlertTriangle/AlertOctagon.
✅ Dismiss session liée à `incident_banner_updated_at` : un nouveau message ré-apparaît auto pour ceux qui avaient masqué l'ancien.
✅ Re-fetch toutes les 2 min pour propager les changements sans recharger la page.
✅ Section "Bandeau d'incident" dans `/admin/settings` avec aperçu en direct (BannerPreview).

### 2026-04-30 — Itération 12 : StatusPill (trust seal public)
✅ Composant `<StatusPill>` flottant bottom-left sur toutes les pages publiques (via MarketingLayout).
✅ Polling 60s sur `/api/public/status?window_hours=24` — dot pulsant vert (≥99%), amber (≥95%) ou rouge (<95%) + libellé + uptime %.
✅ Click → ouvre `/uptime`. Dismissible pour la session via sessionStorage. Responsive (mobile : dot + % seuls, label masqué).
✅ Lien "État des services" ajouté dans le footer (section Espaces).
✅ Style glass-morphism cohérent avec HomeStatsTicker. Ne conflit pas avec l'assistant Liluvine (bottom-right).

### 2026-04-30 — Itération 11 : Uptime Monitor multi-endpoints + Page publique /uptime
✅ 5 sondes (db_ping, api_health, api_company_info, api_visits_count, auth_login_endpoint) exécutées en parallèle (`asyncio.gather`) chaque heure à H:05 (cron Africa/Abidjan).
✅ Persistence dans `db.uptime_checks` (capped 720 entrées). Stats : uptime % par sonde + global, durée moyenne, timeline des 168 derniers points.
✅ Alerte email + webhook conditionnée par `health_uptime_alerts_enabled` (si une sonde échoue).
✅ Section `<UptimeMonitorSection>` ajoutée sur `/admin/health` : sparkline horizontal par sonde, uptime %, latence moyenne, sélecteur fenêtre 24h/3j/7j/30j, bouton "Exécuter maintenant".
✅ **Page publique `/uptime`** (NB: `/status` est intercepté par l'ingress Kubernetes — réservé pour healthcheck) : design dark theme, auto-refresh 60s, sondes publiques uniquement (l'endpoint admin /auth/login est masqué). Partageable avec les clients pour SLA visibility.
✅ Endpoints : `POST /admin/health/uptime/run-now`, `GET /admin/health/uptime/stats`, **`GET /public/status`** (public).
✅ Collection `uptime_checks` whitelistée dans le DB Explorer.

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
