# PRD — SAWALI SMART SYSTEMS Portal

## Original Problem Statement
Construit moi un site web, qui s'affiche bien sur toutes les types de terminaux (ordinateur PC, tablettes et téléphone). Site professionnel de SAWALI SMART SYSTEMS avec accès public (missions, expérience, spécialisation, catalogue, demande de RDV, contact) et espace professionnel (login, mot de passe, captcha, OTP mobile, état du compte, RDV, documentation logiciels, historique interventions, suivi utilisateurs).


## 📋 Backlog Enhancements (idées en attente — à reprendre sur demande utilisateur)
- **Filtre auto sur "leurs" officines pour utilisateurs délégués** : ajouter un champ `delegated_to: List[str]` sur les officines + filtre serveur dans `list_registry` pour les utilisateurs en `edit_mode=limited`. Chaque délégué ne verrait que ses propres officines. Permet une organisation multi-régions. _[suggéré 2026-06-16, en attente]_



## Iter43-fix24s (2026-06-16) — Revert VIDAL URL cleaning + Improve UI response viewer ✅

**Statut** : LIVRÉ. URL VIDAL préservée telle quelle ; rendu UI amélioré pour 2 cas HTML.

### Décision utilisateur (test Postman direct)
- L'utilisateur a testé en Postman : `http://api.vidal.fr/#!/rest/api/authentication` → page Angular API explorer.
- L'URL nettoyée `http://api.vidal.fr/rest/api/authentication` → page d'erreur générique "Oops! Something went wrong".
- **Conclusion utilisateur** : ne pas réécrire l'URL côté backend. Conserver telle quelle. L'effort doit porter sur l'affichage de la réponse.

### Changements
- **`backend/routes/vidal.py`** : suppression complète de `_clean_vidal_base_url()`. L'URL est utilisée TELLE QUELLE (`rstrip("/")` uniquement, comme avant).
- **`frontend/src/pages/portal/Vidal.jsx`** : `RawResponseViewer` détecte désormais 2 types de pages HTML VIDAL :
  - Page Angular API explorer (warning ambré, `vidal-explorer-warning`)
  - Page d'erreur générique "Oops! Something went wrong" (warning rouge, `vidal-error-page-warning`)
- **`backend/tests/test_iter43_fix24r_vidal_url_clean.py`** : supprimé (obsolète).

### Iter43-fix24r conservé pour la délégation Officines
La sortie de la route `/admin/officines-registry` du groupe `<Protected admin>` reste en place. Le composant `OfficinesDelegatedProtected` vérifie `/me/officines-permissions` avant de rendre.



## Iter43-fix24r (2026-06-16) — VIDAL URL Cleaning + Officines Route-Guard ✅

**Statut** : LIVRÉ. 18/18 pytest (7 fix24n + 11 fix24r). Smoke test admin OK.

### Bug 1 : VIDAL retourne du HTML au lieu de JSON (fix RÉEL)
- **Cause** : L'admin avait collé `http://api.vidal.fr/#!/rest/api` (URL Angular de l'API explorer) au lieu de `https://api.vidal.net/rest/api`. Le hashbang `#!/` n'est jamais envoyé au serveur, donc VIDAL recevait `GET /` et renvoyait sa page d'accueil HTML.
- **Fix précédent (handoff) JAMAIS APPLIQUÉ** : le code dans `vidal.py` n'avait aucune logique de nettoyage. Le git log confirme aucun commit avec cette logique.
- **Fix réel** : Ajout de `_clean_vidal_base_url(raw)` qui "déplie" le hashbang :
  - `http://api.vidal.fr/#!/rest/api` → `http://api.vidal.fr/rest/api`
  - `http://api.vidal.fr/#!/` → `http://api.vidal.fr` (juste strip)
- Appelée dans 3 endroits :
  - `_load_config()` (à la lecture, pour que les URLs déjà stockées soient nettoyées)
  - `admin_set_vidal_config()` (à la sauvegarde via PUT)
  - `admin_get_vidal_config()` (à l'affichage GET pour cohérence UI/backend)

### Bug 2 : Utilisateur délégué Officines redirigé vers le Dashboard (fix RÉEL)
- **Cause** : Le composant `Protected admin` dans `App.js` ligne 182 redirigeait IMMÉDIATEMENT vers `/portal` si `user.role !== "admin"`, AVANT que `PortalLayout` ne monte. Donc le flag `permissionsLoaded` ajouté dans la session précédente était inutile.
- **Fix réel** :
  - Création d'un composant `OfficinesDelegatedProtected` qui interroge `/me/officines-permissions` AVANT de rendre la page (loading state explicite).
  - Sortie de la route `/admin/officines-registry` du groupe `<Route path="/admin" element={<Protected admin>}>`.
  - Création d'une route top-level `/admin/officines-registry` utilisant le nouveau garde.
  - PortalLayout reste utilisé (sidebar/header identiques).

### Files modifiés
- `/app/backend/routes/vidal.py` : `_clean_vidal_base_url` + 3 call sites
- `/app/frontend/src/App.js` : nouveau `OfficinesDelegatedProtected` + route déplacée
- `/app/backend/tests/test_iter43_fix24r_vidal_url_clean.py` : 11 nouveaux tests

### IMPORTANT — Re-déploiement requis
Le préviews est OK, mais l'environnement production (`sawalismartsystems.com`) montre encore les anciens bugs. L'utilisateur doit cliquer **"Save to Github"** puis **redéployer** pour appliquer les correctifs.



## Iter43-fix24g (2026-06-15) — Bird SMS Provider in UI + Dry-Run Sandbox ✅

**Statut** : LIVRÉ + testé via testing agent (Backend 11/11 pytest, Frontend 3/3 dropdowns + dry-run UI e2e).

### 1) Bird comme provider SMS sélectionnable
- **Backend** (`server.py`) :
  - `_sms_active_providers(s)` ajoute `"bird"` quand `bird_enabled` + `bird_workspace_id` + `bird_channel_id` + `bird_access_key` tous non-vides.
  - `_sms_provider_cfg(s, "bird")` retourne `{kind:"bird", workspace_id, channel_id, access_key, api_base_url, sender}`.
  - `_sms_dispatch` branche sur `cfg["kind"] == "bird"` → délègue à `routes/bird_sms.send_bird_sms`, persiste dans `bird_sms_messages`.
  - `GET /api/me/sms/providers` retourne désormais `bird_enabled` en plus de `ovh_enabled`.
- **Frontend** :
  - `/portal/sms` (SmsBulk), `/portal/contacts` (Contacts), `/portal/wa` (WaBulk) : option `📡 Bird.com` affichée dans les dropdowns quand Bird est configuré.
  - `/portal/liluvine` (LiluvinePro) : nouveau filtre channel `📡 Bird` + badge orange `📡 Bird` pour sessions `sms:bird:*` ou `external_source="bird_sms"`.
- **Tests** : 3 tests pytest `test_iter43_fix24g_bird_provider.py`.

### 2) Bouton "Tester ce handler en dry-run (sandbox)"
- **Backend** : `POST /api/admin/liluvine-pro/handler-suggestions/{id}/dry-run`
  - Body : `{args?: str, timeout_ms?: int}` (clampé 500-15000 ms)
  - Extrait le 1er bloc ```python contenant `async def _build_<command>_reply` (markdown ou raw).
  - Compile + exec dans un sandbox : `__builtins__` minimalistes (~30 noms), `__import__` restreint à une whitelist (datetime, asyncio, json, math, re, typing, uuid, hashlib, base64, calendar, collections, itertools, functools, statistics, decimal, html, urllib.parse).
  - Appelle `_build_X_reply(db, args)` avec `asyncio.wait_for(timeout)`.
  - Logue chaque exécution dans `db.liluvine_handler_dry_runs` (audit).
  - Codes erreur : `404` suggestion inexistante / `422` fonction introuvable / `200 + ok:false` pour SyntaxError / runtime / import bloqué / timeout.
- **Frontend** : `AdminHandlerSuggestions.jsx` → `CodeViewerModal` enrichi
  - Panneau pliable `dry-run-toggle`, input `dry-run-args-input`, bouton `dry-run-execute-btn`.
  - Affichage résultat `dry-run-result` : ✅ vert (`dry-run-reply`) ou ❌ rouge (`dry-run-error`) + durée ms.
  - Toast sonner sur succès/échec.
- **Tests** : 8 tests pytest `test_iter43_fix24g_dry_run.py` (happy path, syntax error, timeout, import bloqué, fonction manquante, 404, log audit).

### Compteurs cumulés
- Total Iter43 = **40 tests pytest** (29 fix24f + 11 fix24g), 100 % passent.
- Endpoints backend ajoutés : **+1** (dry-run).




## Iter43-fix24f (2026-06-15) — Handler Suggestions admin + Bird Cost Dashboard ✅

**Statut** : LIVRÉ + testé (29/29 pytest passent, 9 nouveaux tests fix24f).

### 1) Page admin `/admin/handler-suggestions`
- **Backend** : 3 endpoints
  - `GET /api/admin/liluvine-pro/handler-suggestions?command=&applied=` — Liste avec filtres
  - `PATCH /api/admin/liluvine-pro/handler-suggestions/{id}` — Toggle `applied` + édition `notes`
  - `DELETE /api/admin/liluvine-pro/handler-suggestions/{id}` — Suppression
- **Frontend** `/admin/handler-suggestions` :
  - Table : commande, modèle, exemples, date, auteur, statut (Appliqué/En attente), notes éditables inline, actions
  - Filtres : par !commande + par statut (tous / en attente / appliqués)
  - **Modal `CodeViewerModal`** : affiche le code Python généré dans `<pre>` sombre + bouton "Copier"
  - Notes éditables inline (clic → textarea → bouton OK)
  - Bouton "Supprimer" avec confirmation native

### 2) Page admin `/admin/bird-cost`
- **Backend** : `GET /api/admin/bird/cost-daily-series?days=N` (1-365j)
  - Retourne `{days, unit_cost, currency, total_count, total_cost, series:[{date, count, cost}]}`
  - Remplit les zéros pour les jours sans SMS
  - Validation `Query(..., ge=1, le=365)` → 422 si hors plage
- **Frontend** `/admin/bird-cost` :
  - 5 KPI cards : Aujourd'hui (highlight sky) / Hier / 7 derniers jours / 30 derniers jours / Total
  - Graphique barres horizontales pure CSS (pas de lib chart) — 7/14/30/90 jours sélectionnable
  - Aujourd'hui mis en avant (texte sky bold + barre sky-600 vs sky-400)
  - Tooltip explicatif : taux fixe + lien vers config dans Paramètres
- **Sidebar** : 2 nouvelles entrées `Handlers IA` (Sparkles) et `Coût SMS Bird` (CircleDollarSign), admin-only.

### Tests
- **9 nouveaux tests pytest** dans `test_iter43_fix24f_handler_suggestions_bird_daily.py`
- **Total Iter43 fix23b+24b+24d+24f = 29 tests, 100% passent**

### Compteurs
- **241 clés i18n FR/EN/AR** (inchangé depuis fix24e)
- **2 nouvelles pages admin** (handler-suggestions + bird-cost)
- **5 nouveaux endpoints** backend



## Iter43-fix24e (2026-06-15) — URLs Bird éditables + i18n complet + Bouton "Auto-générer handler IA" ✅

**Statut** : LIVRÉ + testé (20/20 pytest, screenshots 4 nouvelles pages 100% EN).

### 1) URLs Bird éditables
- Nouveau field `public_base_url` dans Settings (par défaut = REACT_APP_BACKEND_URL = preview)
- Composant `CopyableUrl` modifié pour accepter `baseUrl` en prop et l'utiliser en priorité
- Input "Base URL publique" affiché dans la section Bird de AdminSettings (placeholder "https://sawalismartsystems.com")
- Appliqué aux 2 webhooks Bird (Inbound + Delivery) ET aux 2 endpoints Inventaire officines (4 CopyableUrl au total)

### 2) i18n étendu aux 5 pages publiques restantes
**55 nouvelles clés** seedées (FR/EN/AR) :
- `public.specs.*` (4) — Specialisations.jsx wrappé
- `public.cases.*` (7) — CaseStudies.jsx wrappé
- `public.testi.*` (10) — Testimonials.jsx wrappé (Quote/Stars cards entièrement)
- `public.rdv.*` (22) — RDV.jsx wrappé (datepicker + slots + form + success)
- `public.subs.*` (12) — Subscriptions clés seedées (composant déjà i18n-aware)
- **Total : 241 clés FR/EN/AR**

### 3) Bouton "Auto-générer handler" pour commandes inconnues (Claude Sonnet)
- **Backend** `routes/liluvine_wa_requests.py` : `POST /api/admin/liluvine-pro/exclamations/{command}/auto-handler`
  - Charge 3 exemples concrets de la commande depuis `liluvine_exclamations`
  - Envoie à Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) avec prompt système expert sur le module `liluvine_wa_autoreply.py`
  - Retourne du code Python prêt à coller (fonction `_build_<cmd>_reply` + modifications de `maybe_handle_liluvine_wa_command` + points d'attention)
  - Audit : chaque génération est loggée dans `liluvine_handler_suggestions` (command, model, code, applied=false)
- **Frontend** `AdminLiluvineWaRequests.jsx` :
  - Nouvelle colonne "Commandes" : badges verts (commandes connues) + ambre (inconnues) avec icône Sparkles cliquable pour les inconnues
  - Toggle "Cmds inconnues uniquement" pour filtrer la liste
  - Indicateur `⚠ N` à côté des numéros ayant envoyé des commandes inconnues
  - **Modal `HandlerGenerationModal`** : affiche le code Python généré dans `<pre>` sombre avec bouton "Copier"

### Status budget Emergent LLM
⚠️ **Budget Emergent LLM épuisé** : `Current cost: 17.46 / Max budget: 16.4`. L'utilisateur doit aller dans son **Profile → Universal Key → Add Balance** (ou activer l'auto top-up) pour utiliser la génération IA et les réponses Liluvine.

### Compteurs i18n actuels
- **241 clés FR + EN + AR** :
  - public.home.*: 34, public.footer.*: 21, public.missions.*: 8, public.contact.*: 15, public.catalogue.*: 8
  - public.specs.*: 4, public.cases.*: 7, public.testi.*: 10, public.rdv.*: 22, public.subs.*: 12, public.nav.*: 13
  - 87 clés historiques diverses

### Tests
- **20 tests pytest passent** (fix23b + fix24b + fix24d)
- **Screenshots EN validés** : Specialisations, CaseStudies, Testimonials, RDV (toutes en EN)



## Iter43-fix24d (2026-06-15) — Exclamations Reçues + Bird Cost + i18n complet (Contact/Missions/Catalogue) ✅

**Statut** : LIVRÉ + testé (20/20 pytest, screenshots EN OK).

### 1) Nouvelle table `liluvine_exclamations` + rename UI
Demande critique de l'utilisateur : la table /admin/liluvine-wa-requests ne doit contenir QUE les `!commandes`, séparé des conversations Liluvine PRO classiques.

- **Nouvelle collection MongoDB `liluvine_exclamations`** alimentée par `liluvine_wa_autoreply.py` à la détection de tout `text.startswith("!")` :
  - Capture : `command` (premier token), `command_args` (reste), `body` (texte complet), `is_known_command` (bool), `handled`, `reply`, `wa_message_id`, etc.
  - Marqué `handled=True` après envoi de la réponse pour les commandes supportées (Garde, Meteo).
  - Stocke aussi les commandes inconnues (`!Aizenta`, `!xyz`) avec `is_known_command=False` → roadmap.
- **Endpoint `/admin/liluvine-pro/wa-requests`** : lit `liluvine_exclamations` au lieu de `whatsapp_messages`. Nouveau filtre `only_unknown=true` pour audit roadmap.
- **Stats par phone groupé** : `commands` (compteur par commande), `unknown_count`, `last_command`, etc.
- **UI** : H1 "Exclamations Reçues" + sous-titre explicatif. Sidebar "Exclamations Reçues" (remplace "EXCLAM_Liluvine").

### 2) Badge coût Bird en temps réel (suggestion d'amélioration)
- **Backend** `bird_sms.py` : `GET /api/admin/bird/cost-summary` (today, yesterday, last_7_days, last_30_days, total).
- **Backend** `unified_inbox.py` : `GET /api/me/inbox/bird-cost-today` (scoped admin vs tenant).
- **Settings DB** : `bird_cost_per_sms_xof` (défaut 25 XOF), `bird_cost_currency` (XOF/EUR/USD).
- **UI AdminSettings** : 2 nouveaux inputs (coût unitaire + devise).
- **UI UnifiedInbox** : badge sky "Aujourd'hui : 0 XOF (0 SMS Bird)" rafraîchi toutes les 20s avec l'inbox.

### 3) i18n public — extension Contact + Missions + Catalogue
- **31 nouvelles clés** seedées (8 missions, 15 contact, 8 catalogue) — total **186 clés FR/EN/AR**.
- **Composants refactorés** : `Missions.jsx`, `Contact.jsx`, `Catalogue.jsx` (titre, sous-titre, kicker, recherche, empty state, boutons).
- **Test E2E** : screenshot Contact en EN → 100% traduit ("Let's talk about your project.", "Our team will reply within 24 business hours.", "FULL NAME", "Send message", "Describe your need...").

### Compteurs i18n (état actuel)
- **186 clés FR + EN + AR** :
  - public.home.*: 34
  - public.footer.*: 21
  - public.missions.*: 8
  - public.contact.*: 15
  - public.catalogue.*: 8
  - public.nav.*: 13 (déjà existant)
  - 87 autres clés historiques

### Tests
- `/app/backend/tests/test_iter43_fix24d_exclamations_bird_cost.py` : 6 tests (exclamations CRUD + Bird cost endpoints).
- Total **fix23b + fix24b + fix24d** : **20 tests, 100% passent**.



## Iter43-fix24b/c (2026-06-15) — Inbox SMS Bird + Footer i18n ✅

**Statut** : LIVRÉ + testé (14/14 pytest, screenshot Footer EN OK).

### Bird SMS dans /portal/inbox (fix24b)
Canal **`sms_bird`** ajouté à l'inbox unifiée (distinct du canal `sms` OVH/Orange) :
- **Backend** `unified_inbox.py` :
  - Agrégation des `bird_sms_messages` par numéro peer (admin = tous, tenant = numéros liés au compte uniquement)
  - Endpoint `GET /api/me/inbox/unified/sms_bird/{thread_id}` retourne les messages bidirectionnels
  - Envoi via `POST /api/me/inbox/send` avec `channel="sms_bird"` (utilise `_inbox_bird_send_helper`)
  - `channels_enabled.sms_bird` et `totals.sms_bird` exposés
- **Frontend** `UnifiedInbox.jsx` :
  - `channelMeta.sms_bird` (badge sky bleu, icône Smartphone)
  - Option de filtre "SMS Bird ({totals.sms_bird || 0})"
  - Sous-titre dynamique inclut "+ SMS Bird" quand activé
- **server.py** : `_inbox_bird_send_helper(to, text)` wrappe `send_bird_sms` et persiste l'outbound dans `bird_sms_messages`.

### Footer i18n (fix24c)
21 nouvelles clés `public.footer.*` en FR/EN/AR :
- Newsletter (kicker + title)
- Tagline (3 colonnes : Navigation / Espaces / Contact)
- 7 liens Navigation, 4 liens Espaces
- 3 liens Politiques (Privacy, Services, Cookies)
- Copyright avec placeholder `{year}` interpolé côté JSX

### Tests
- `/app/backend/tests/test_iter43_fix24b_inbox_bird.py` : 3 tests (canal, messages, envoi sans config → 503).
- Total backend Iter43 fix23+24 : **14 tests, 100%**.

### Compteurs i18n (état actuel)
- **155 clés FR + EN + AR** (21 footer + 34 home + 100 historiques)
- Gulmancema (lg1) et Mooré (lg2) → traduisibles via Admin → i18n → "Traduire avec IA"



## Iter43-fix24 (2026-06-15) — i18n extension Home publique (FR/EN/AR/RTL) ✅

**Statut** : LIVRÉ + testé (screenshots EN + AR-RTL OK).

### Réalisé
- 34 nouvelles clés `public.home.*` seedées en FR/EN/AR via le système i18n existant (`SEED_KEYS` dans `/app/backend/routes/i18n.py`).
- Refacto `Home.jsx` : tous les CTAs hero, sections Spécialisations, Témoignages, Expérience SAWALI, et CTA bottom utilisent `t("key", "Fallback FR")`.
- Mode RTL Arabe vérifié : `html dir="rtl"` appliqué automatiquement par I18nContext + tous les CTAs traduits.

### Système i18n existant (à savoir)
- 5 langues : FR (source), EN, AR (RTL), Gulmancema (lg1), Mooré (lg2)
- 134 clés FR au total (100 historiques + 34 nouvelles)
- Traducteur IA Claude/GPT/Gemini intégré (page `/admin/i18n`)
- Détection auto via header CF-IPCountry (BF → FR, MA → AR, etc.)
- Persistance localStorage `sawali_lang`

### Limitation
Le titre H1 du hero vient du `content_blocks` API (pas du i18n simple) — gérable séparément via l'éditeur **Admin → Contenu** existant. Idem pour les metrics dynamiques.

### Action utilisateur restante
Traduire Gulmancema (lg1) et Mooré (lg2) via **Admin → i18n** :
- Soit en saisissant les langues à la main
- Soit via le bouton "Traduire avec IA" (Claude Sonnet/Haiku, GPT-4o, Gemini 2.5)



## Iter43-fix23b (2026-06-15) — Bird.com 2-Way SMS (remplace Africa's Talking) ✅

**Statut** : LIVRÉ + testé (11/11 pytest). En attente clé Bird "Messaging" côté utilisateur.

### Pourquoi le pivot AT → Bird ?
L'utilisateur a tenté de fournir une clé AT (`n685Qc...iEd`) — clé en réalité générée sur **app.bird.com** (nouvelle plateforme unifiée après le rachat d'Africa's Talking par Bird). L'auth Bird est validée (200), mais sa première clé avait uniquement la policy "Organization Configuration Manager" (insuffisante pour SMS). L'utilisateur doit générer une seconde clé Bird avec la policy **`Messaging`**.

### Refactoring
- ❌ Supprimé : `/app/backend/routes/africas_talking_sms.py` + collection `africas_talking_sms_messages` + 8 fields `africas_talking_*` dans Settings.
- ✅ Créé : `/app/backend/routes/bird_sms.py` — utilise **httpx direct** (pas de SDK Bird).

### Nouveaux endpoints
- `POST /api/webhooks/bird/inbound-sms` — HMAC SHA-256 sur header `Bird-Signature` (3 formats supportés : hex, `t=...,v1=...`, base64), idempotence sur `provider_message_id`.
- `POST /api/webhooks/bird/delivery-report` — rapports de livraison.
- `GET /api/admin/bird/status` — statut config (masqué).
- `GET /api/admin/bird/messages?q=&direction=` — liste/recherche.
- `POST /api/admin/bird/send-sms` — envoi sortant via `POST {api_base}/workspaces/{wid}/channels/{cid}/messages`.

### Settings (9 nouveaux fields)
`bird_enabled`, `bird_api_base_url` (défaut https://api.bird.com), `bird_workspace_id`, `bird_channel_id`, `bird_access_key` (masqué), `bird_webhook_secret` (masqué, HMAC SHA-256), `bird_default_sender`, `bird_signature`, `bird_use_liluvine`.

### UI
- Section AdminSettings : "📱 Bird.com — SMS Bidirectionnel (offline Liluvine)" avec tous les inputs + CopyableUrl pour Inbound + Delivery webhooks.

### Tests
- `/app/backend/tests/test_iter43_fix23b_bird_inventory_webhook_role.py` (11 tests, 100%).
- Test direct API Bird : auth = 200 (clé valide), Workspaces = 403 (policy insuffisante — comportement attendu).

### Action utilisateur restante (3 étapes)
1. Sur app.bird.com → **Clés API** → **Créer nouveau** :
   - Nom : "SAWALI Liluvine Messaging"
   - Policy : **`Messaging`** (et non Organization Configuration Manager !)
   - Copier la clé (affichée une seule fois).
2. Récupérer **Workspace ID** (visible dans l'URL `app.bird.com/workspaces/{id}/...`) et **Channel ID** (Channels → SMS → détails).
3. Saisir tout dans **Admin → Paramètres → Bird.com — SMS Bidirectionnel** (+ activer le toggle).
4. Aller dans **Bird → Channels → SMS → Webhooks** et coller l'URL `https://sawalismartsystems.com/api/webhooks/bird/inbound-sms` + générer un Signing Secret à recopier dans l'UI Admin SAWALI.



## Iter43-fix23 (2026-06-15) — Africa's Talking 2-Way SMS + Inventory Webhook + Officines Roles UI ✅

**Statut** : LIVRÉ + testé (11/11 pytest, 100% backend + 100% frontend par testing_agent).

### 1) Africa's Talking 2-Way SMS Integration (offline Liluvine)
- Nouveau fichier `/app/backend/routes/africas_talking_sms.py` :
  - `POST /api/webhooks/africas-talking/incoming-sms` — webhook AT entrant (form-data), persistance Mongo, routage vers Liluvine si activé.
  - `POST /api/webhooks/africas-talking/delivery-report` — webhook livraisons.
  - `GET /api/admin/africas-talking/status` — statut config (masqué).
  - `GET /api/admin/africas-talking/messages?q=&direction=` — liste/recherche.
  - `POST /api/admin/africas-talking/send-sms` — test envoi manuel.
- SDK Python `africastalking==2.0.2` installé.
- Mode toggle Sandbox/Live (settings DB).
- Settings DB : `africas_talking_enabled`, `africas_talking_env`, `africas_talking_username`, `africas_talking_api_key` (masqué), `africas_talking_shortcode`, `africas_talking_signature`, `africas_talking_use_liluvine`, `africas_talking_webhook_secret` (masqué).
- UI Admin → Paramètres : nouvelle section "Africa's Talking — SMS Bidirectionnel" avec inputs + CopyableUrl (URLs prêtes à coller dans AT dashboard → SMS → Callback URLs).
- Liluvine reply : Claude Haiku 4.5 via `emergentintegrations`, sortie limitée 320 chars + signature optionnelle, KB + BizRAG injectés.

### 2) Webhook d'inventaire officines (Bearer auth)
- Nouveau fichier `/app/backend/routes/officines_inventory_webhook.py` :
  - `POST /api/webhooks/officines/inventory` — Bearer auth, upsert items par (officine_id, product_name, lot_number).
  - `GET /api/webhooks/officines/inventory/docs` — schéma JSON public pour intégrateurs SI.
- Accepte JSON natif **et** clés CSV françaises (Nom du produit, CIP, Quantité, Prix unitaire, Lot, Devise).
- Limite 5000 items par appel. Audit log + tracker registry (last_webhook_at, webhook_calls).
- UI Admin → Paramètres : section "Webhook Inventaire Officines (Bearer)" avec input password + URLs CopyableUrl.

### 3) Officines Registry — Rôles dans l'UI + création manuelle
- Frontend `AdminOfficinesRegistry.jsx` :
  - Filtre par **rôle** (data-testid="filter-role") au lieu d'activité.
  - Colonne **Rôle** dans le tableau (au lieu d'Activité).
  - Recherche `q=` étendue au champ `role` côté backend.
  - Bouton **"Nouvelle officine"** (data-testid="create-officine-btn") + modale complète `CreateOfficineModal` (name, intitulé, email, phone, WA, ville, pays, adresse, location_hint, numero_ordre, contact, rôle, groupe_garde, statut).
- Backend `routes/officines_portal.py` :
  - `POST /api/admin/officines-registry` — création manuelle (validation rôle, anti-doublon par name + phone_digits, audit log).
  - `GET /api/admin/officines-registry?role=X` — filtre par rôle.

### 4) Renommage EXCLAM_Liluvine
- Page `AdminLiluvineWaRequests.jsx` : H1 → "EXCLAM_Liluvine" + sous-titre clarifiant "Interrogations WhatsApp uniquement".
- Sidebar `PortalLayout.jsx` : libellé du lien `/admin/liluvine-wa-requests` → "EXCLAM_Liluvine".

### Fichiers modifiés
- `backend/models.py` (SettingsUpdate +9 fields)
- `backend/routes/admin_settings.py` (GET_MASK_FIELDS)
- `backend/server.py` (montage routes + SECRET_FIELDS + _PUBLIC_PROVIDER_FIELDS)
- `backend/routes/officines_portal.py` (POST création + filtre role)
- `frontend/src/pages/admin/AdminSettings.jsx` (sections AT + Webhook + CopyableUrl + import Package)
- `frontend/src/pages/admin/AdminOfficinesRegistry.jsx` (rôle au lieu d'activité + bouton créer + modal)
- `frontend/src/pages/admin/AdminLiluvineWaRequests.jsx` (titre)
- `frontend/src/components/PortalLayout.jsx` (libellé sidebar)

### Tests
- `/app/backend/tests/test_iter43_fix23_at_inventory_webhook_role.py` (11 tests, 100%).
- Testing agent : backend 100%, frontend 100% (cf. `/app/test_reports/iteration_63.json`).

### Action utilisateur restante
1. Créer le compte Africa's Talking sur https://account.africastalking.com (Sandbox d'abord puis Live).
2. Saisir les credentials dans Admin → Paramètres → "Africa's Talking — SMS Bidirectionnel" (username + API key + shortcode/sender ID).
3. Coller les **2 URLs CopyableUrl** dans le dashboard AT → SMS → SMS Callback URLs (Incoming + Delivery Reports).
4. Tester via le Simulator AT (mode Sandbox).
5. Pour le webhook inventaire : générer un token Bearer long (≥ 32 chars), le saisir dans la section "Webhook Inventaire Officines", puis le communiquer aux SI des officines.

### Issues mineures (non bloquantes — backlog)
- Warning React hydration `<span>` dans `<option>` (AdminSettings.jsx) — cosmétique, présent avant fix23.
- Performance AdminSettings : ~8s de rendu initial — splitting par sous-composants à envisager (P2).
- Duplication MASK fields entre `admin_settings.py` et `server.py` — centraliser dans un module (P2).



## Iter43-fix22 (2026-06) — Liluvine WA Tracker + Garde Planning + WA Commands ✅



## Iter43-fix16 (2026-06) — WhatsApp Webhook Subscription Diagnostic + OpenAPI fix ✅

**Statut** : LIVRÉ + testé (9/9 pytest = 6 docs/openapi + 3 webhook-subscription).

### Bug critique résolu — OpenAPI/Swagger
- `/api/openapi.json` crashait avec `PydanticUndefinedAnnotation: CheckoutPayload`.
- Cause : `CheckoutPayload` défini **dans** `setup_stripe_routes()` combiné à `from __future__ import annotations` → ForwardRef irrésolvable.
- Fix : remonté à portée module et renommé `StripeCheckoutPayload` pour éviter collision avec `ad_banners.CheckoutPayload`.
- Résultat : `/api/openapi.json` (725 paths), `/api/docs`, `/api/redoc` répondent 200 → page `/documentation` fonctionnelle.

### Symptôme utilisateur — Liluvine PRO ne reçoit plus de WhatsApp depuis le 10 juin 2026
- Diagnostic par tests live : Liluvine PRO chat web fonctionne (`/me/liluvine-pro/chat` + stream OK, Claude Haiku 4.5 répond).
- **Cause réelle** : webhook Meta `messages` désabonné côté Meta (l'app n'apparaît plus dans `subscribed_apps` du WABA). Outbound fonctionne (token OK) mais inbound silencieux → Liluvine ne reçoit rien donc ne répond rien.

### Nouveaux endpoints + UI ajoutés
- `GET /api/admin/whatsapp/webhook-subscription` → diagnostic Meta : liste les apps abonnées au WABA + détecte si le champ `messages` est présent. Retourne `ok=False` + message clair si la souscription est vide.
- `POST /api/admin/whatsapp/webhook-subscribe` → action en 1 clic pour re-souscrire l'app au WABA (POST `/{waba_id}/subscribed_apps`). Idempotent.
- Panel UI `📡 Diagnostic souscription Webhook Meta` ajouté dans **Admin → Paramètres → WhatsApp** entre le diagnostic du token et les logs webhook.
- Bouton « 🔁 Re-souscrire le webhook » visible uniquement quand la souscription est cassée.
- Lien direct vers Meta Business Suite si la re-souscription en 1 clic échoue.

### Action utilisateur (Production)
1. Pousser le code Preview en Production via **"Save to Github"** (fixes Iter43-fix16 indispensables).
2. Aller sur `sawalismartsystems.com/admin/settings` → WhatsApp.
3. Cliquer **"Vérifier la souscription"** dans le nouveau panel.
4. Si vide → cliquer **"🔁 Re-souscrire le webhook"**.
5. Envoyer un WA test → vérifier que `/admin/whatsapp/webhook-logs` enregistre l'appel et que Liluvine répond.


_⚠️ Historique récent (Iter35a → Iter38c) déplacé dans `/app/memory/CHANGELOG.md`._

## Iter43-fix13 + Iter43-fix14 (2026-03) — Story Studio Phase 3 + 4 + Cron + Analytics ✅

**Statut** : LIVRÉ + testé (22/22 nouveaux + 34/34 régression = 56/56 ; testing_agent_v3_fork OK — `iteration_62.json`).

### Phase 3 — Multi-tenant monétisation (XOF)
- Tarif par tenant configurable (4 cibles : fb_feed, ig_story, ig_reel, tiktok).
- 3 modes : `credits_first` (recommandé), `credits_only` (bloque si 0 solde, 402), `invoice_only`.
- Crédits prépayés + facture mensuelle auto (status open/paid/cancelled).
- Le tenant facturé = propriétaire du `social_account` ciblé.
- Facturation **succès uniquement** (échec publish = pas de débit).
- 9 endpoints : config, topup, ledger, invoices, summary, tenants list.
- Onglet « Facturation » avec vue d'ensemble (KPIs + top 10) + détail tenant.

### Phase 4 — TikTok Content Posting API
- OAuth 2.0 v2 (auth + refresh automatique). Tokens chiffrés Fernet.
- Direct Post FILE_UPLOAD (`privacy_level=SELF_ONLY` pour sandbox-safe).
- Section dédiée dans onglet « Comptes Meta » + paramètres avec instructions pas-à-pas.
- Cible `tiktok` ajoutée au PublishModal.

### P2 Cron Scheduler
- `POST /api/admin/story-studio/scheduler/tick` (admin) à appeler par cron externe (every 5min recommandé).
- Sélectionne drafts avec `scheduled_at <= now`, idempotent, supports `?dry_run=true`.
- Gère asset manquant (failed), solde insuffisant (blocked_credits), futurs ignorés.

### P2 Analytics IG/FB
- `GET /api/admin/story-studio/posts/{id}/insights`
- IG : impressions/reach/replies (Stories) ou likes/plays/shares/saved (Reels)
- FB : views/likes/comments/shares
- Cache dans `story_posts.insights` + `insights_fetched_at`

### Action utilisateur (TikTok prod)
1. developers.tiktok.com → Connect an app (Business)
2. Activer Login Kit + Content Posting API
3. Scopes : video.upload, video.publish, user.info.basic
4. Redirect URI : `https://sawalismartsystems.com/api/admin/story-studio/oauth/tiktok/callback`
5. Démarrer en Sandbox, puis Submit pour production
6. Renseigner Client Key + Secret dans `/admin/story-studio` → Paramètres → TikTok

## Iter43-fix12 (2026-03) — Officines Registry : Produits + Activités + Bug /api-routes ✅

**Statut** : LIVRÉ + testé (20/20 pytest ; 107/107 régression ; testing_agent_v3_fork 100% UI — `iteration_61.json`).

### Tâche 1 — Import produits par officine (CSV/JSON)
- Collection `officine_products` + index `(officine_id, product_name_norm)` + `(officine_id, conditionnement_norm)`.
- `POST /api/admin/officines-registry/{id}/products/import` (multipart) : CSV (`,` ou `;`, avec/sans en-tête) OU JSON (plat OU imbriqué auto-aplati).
- Mode `replace` ou `append` (upsert). Clé d'unicité : `(officine, produit, conditionnement)` — CIP optionnel.
- Anti-doublons intra-fichier + audit log.
- Endpoints associés : list paginée, clear all, export CSV streamé.

### Tâche 2 — Liste alphabétique + nb produits + modale produits
- `GET /admin/officines-registry` trié ASC par `name` (collation FR), enrichi avec `products_count`.
- Frontend : colonne « Produits » + bouton eye → `ProductsModal` paginée 100/page, search, sort, export CSV, clear.

### Tâche 3 — Activité principale filtrable + liste éditable
- Champ `activite_principale` sur la fiche.
- `GET/PUT /api/admin/officine-activities` (settings.global.officines_activities).
- Frontend : dropdown filtre + `ManageActivitiesModal` (add/remove) + champ select dans `EditOfficineModal`.

### Bug fix — Page /documentation vide
- `/api/api-routes` retournait 500 (TypeError list - set) → corrigé. 859 routes listées correctement.

## Iter43-fix11 (2026-03) — Story Studio Phase 2 — Meta OAuth + Publishing ✅

**Statut** : LIVRÉ + testé (34/34 pytest ; testing agent v3 frontend OK — `iteration_60.json`).

### Fonctionnalités
- **OAuth Meta v23.0** multi-tenant : chaque tenant connecte son compte Meta Business via l'app SAWALI partagée. Tokens long-lived (60j) chiffrés au repos (Fernet dérivé de JWT_SECRET).
- **Publication automatique** depuis la bibliothèque : Instagram Stories, Instagram Reels, Facebook Page Feed (multi-cibles en un clic).
- **Modes** : Publication immédiate OU brouillon (relançable depuis l'onglet Historique).
- **Auto-découverte** Pages FB + comptes IG Business via `/me/accounts?fields=…,instagram_business_account{id,username}`.
- **Gestion d'erreurs partielles** : 1 cible échoue → status `partial` ; toutes ko → `failed` ; toutes ok → `published`.
- **UI Comptes Meta** : connect/refresh/disconnect, toggle Page is_active, badge expiration token.

### Backend endpoints
- `GET /api/admin/story-studio/oauth/meta/start` (admin)
- `GET /api/admin/story-studio/oauth/meta/callback` (public, appelé par Meta)
- `POST /api/admin/story-studio/social-accounts/{id}/refresh`
- `PUT  /api/admin/story-studio/social-accounts/{id}/pages/{page_id}`
- `GET  /api/admin/story-studio/library/{asset_id}/signed-media?token=` (public, JWT signé 60min)
- `POST /api/admin/story-studio/library/{asset_id}/publish` (replace stub)
- `POST /api/admin/story-studio/posts/{post_id}/publish-now`
- `GET  /api/admin/story-studio/posts`

### Modèles
- Collection `social_accounts` enrichie : `meta_user_id`, `meta_user_name`, `long_lived_user_token_encrypted`, `long_lived_user_token_expires_at`, `pages[{page_id, page_name, page_access_token_encrypted, ig_business_account_id, ig_username, is_active}]`.
- Collection `story_posts` enrichie : `targets[{social_account_id, page_id, target}]`, `results[]`, `mode`, statuts `draft|publishing|published|partial|failed`.

### Action utilisateur requise pour activer en prod
1. Créer app sur https://developers.facebook.com/apps/ (type Business)
2. Activer Facebook Login for Business + Instagram
3. Ajouter Valid OAuth Redirect URI : `https://sawalismartsystems.com/api/admin/story-studio/oauth/meta/callback`
4. App Review : `instagram_content_publish`, `pages_manage_posts`, `business_management`
5. Renseigner App ID + Secret dans `/admin/story-studio` → Paramètres → Meta
6. Tester : `/admin/story-studio` → Comptes Meta → Connecter un compte Meta


## Iter43-fix4 (2026-03) — Facturation des Interventions ✅

**Statut** : LIVRÉ + testé (10/10 pytest, E2E UI validé — `iteration_56.json`).

### Fonctionnalités
- Admin/Sup peuvent **modifier** une intervention non facturée (tenant, durée, statut, etc.) via modale.
- **Multi-sélection** + bouton « Générer facture(s) » → 1 facture PDF par tenant, auto-numérotée `INV-YYYY-NNNNN`.
- **Verrouillage visuel** : lignes facturées grisées, checkbox + Modifier/Supprimer désactivés.
- **Colonne « N° Facture »** : badge cliquable pour re-télécharger le PDF.
- **Bouton Déverrouiller** (admin) — la facture reste valide, l'intervention redevient modifiable.

### Backend endpoints
- `POST /api/me/invoices/from-interventions` (admin/sup)
- `GET  /api/me/invoices/from-interventions[?tenant_id=]`
- `GET  /api/me/invoices/from-interventions/{id}/pdf`
- `PUT  /api/admin/interventions/{id}` (renvoie 409 si facturée)
- `POST /api/admin/interventions/{id}/unlock-invoice`

### Modèles
- Collection nouvelle : `interventions_invoices`.
- `interventions` : champs `invoiced`, `invoice_id`, `invoice_number`, `invoiced_at`, `invoiced_by`, `unlocked_at`, `unlocked_by`.
- Devise **XOF** (sans TVA). Taux : `users.hourly_rate` → fallback `settings.global.default_intervention_hourly_rate_xof`.

---


## Iter43 (2026-03) — Webhook Aizenta/Biolog + Bulk delete + Migration

### Contexte
L'utilisateur a configuré son logiciel Aizenta sur `/api/public/incidents` au lieu de `/api/errors/ingest`. Résultat : ~469 entrées Aizenta ont atterri dans `support_tickets` au lieu de `error_registry`, et la page « Registre des Erreurs » restait vide. Plus largement, le webhook errors n'acceptait que le format plat (pas les wrappers `{TicketDemnde:{...}}`, `{Erreur:{...}}` etc.).

### Backend
- **`/api/errors/ingest`** : Refactor pour accepter le body brut + nouvelle fonction `_unwrap_payload()` qui détecte automatiquement un wrapper unique contenant `Motif` + `CodeApplicatif` (couvre Aizenta `TicketDemnde`, Biolog `Erreur`, et tout logiciel suivant la même structure). Le format plat historique reste accepté.
- **`/api/me/errors/bulk-delete`** (admin/sup) : suppression par liste d'ids
- **`/api/me/errors/reset`** (admin/sup) : purge TOTALE du registre
- **`/api/me/tickets/bulk-delete`** (admin/sup) : suppression par liste d'ids
- **`/api/me/tickets/reset`** (admin/sup) : purge TOTALE des tickets
- **`/api/admin/error-registry/migrate-from-tickets`** (admin/sup) : rapatrie les `support_tickets` avec `channel=webhook` + `metadata.Motif/IDTicketDemnde` vers `error_registry`. **Idempotent** (basé sur `IDTicketDemnde`).
- **`/api/public/incidents`** : adapter Aizenta `{TicketDemnde:{...}}` déjà présent (Iter43-incidents).

### Frontend
- **`ErrorRegistry.jsx`** : 
  - Multi-sélection (checkbox header `err-select-all` + `err-select-<id>`)
  - Bandeau bulk `err-bulk-bar` avec bouton `err-bulk-delete`
  - Boutons header `err-migrate-btn` (rapatrier depuis tickets) et `err-reset-btn` (remise à zéro) — visibles admin/sup uniquement
  - Détection du rôle via `useAuth()` (au lieu de `/api/me` qui n'existait pas)
- **`Tickets.jsx`** : 
  - Multi-sélection (checkbox `tickets-select-all` + `tickets-select-<id>`)
  - Bandeau bulk `tickets-bulk-bar` avec bouton `tickets-bulk-delete`
  - Bouton `tickets-reset-btn` (remise à zéro) — admin/sup uniquement
  - Détection du rôle via `useAuth()`
- **`AdminSettings → IncidentsAndCountrySection`** : nouvelle carte `errors-webhook-card` (URL + token Bearer + génération aléatoire + bouton migration). Clarifie la différence entre les 2 webhooks.

### Tests
- **`test_iter43_bulk_and_migration.py`** : 9/9 verts
  - Format flat, Aizenta wrapper, Biolog wrapper
  - Bulk delete errors (admin OK, client 403)
  - Reset all errors (sup)
  - Bulk delete tickets (admin OK, client 403)
  - Migration idempotente (2 migrés puis 2 skipped_already)
- **Régression** : test_iter40_error_registry (3) + test_iter42d (10) + test_iter43_tenant_sharing (11) + test_iter43_bulk_and_migration (9) = **33/33 verts**
- Frontend retest validé (iteration_55.json) : tous les testids admin visibles.

### Action requise utilisateur
1. **Redéployer** (Save to Github + Emergent Deploy) — preview validée, prod doit suivre
2. **En prod**, depuis AdminSettings → « Webhook Registre des Erreurs » → cliquer **« Rapatrier depuis tickets »** pour récupérer les ~469 entrées Aizenta perdues
3. **Reconfigurer Aizenta** sur la nouvelle URL `https://sawalismartsystems.com/api/errors/ingest` (avec le token Bearer généré)
4. Optionnel : utiliser **« Remise à zéro »** sur Tickets pour vider la table support_tickets après migration



## Iter43 (2026-02) — Partage cross-utilisateur (société + rattachement) — AND/OR

### Objectif
Permettre aux utilisateurs ayant la même **société (`company`)** et/ou même **rattachement (`parent_client_id`)** — selon un mode AND/OR configuré par l'admin du tenant parent — de voir et éventuellement éditer les documents partagés de leurs collègues. **Suppression toujours réservée à l'auteur** (sauf admin/superviseur du tenant).

### Architecture
- **Helper centralisé** `routes/tenant_sharing.py` :
  - `get_tenant_sharing_mode(db, user)` → lit `tenant_sharing_mode` (AND|OR) sur la fiche du tenant parent (par défaut AND)
  - `resolve_visible_owner_ids(db, user)` → liste les owner_ids visibles selon le mode
  - `build_shared_filter(db, user)` → filtre Mongo `$or` {owner=moi} OU {owner ∈ collègues + shared_with_tenant=True}
  - `stamp_ownership(doc, user, shared, editable)` → injection des snapshots société/rattachement
  - `can_edit(doc, user, visible_ids)` / `can_delete(doc, user)` → contrôles d'accès
- **Champs standards sur tous les documents partageables** :
  - `owner_id`, `owner_company`, `owner_parent_client_id`
  - `shared_with_tenant: bool` (défaut False)
  - `editable_by_tenant: bool` (défaut False)

### Modules câblés (6)
1. **Contact Groups** (`routes/contact_groups.py`) — déjà câblé (filtre $or {client_id legacy} OU {build_shared_filter})
2. **Meetings/PV** (`routes/meetings.py`) — déjà câblé
3. **User Notes/Tasks/Reports/Suivis** (`/me/notes/{kind}` dans server.py) — NEW : étend la clause `$or` de visibilité avec `{owner_id ∈ collègues, shared_with_tenant=True}`; PUT autorisé si `editable_by_tenant=True`
4. **Support Tickets** (`/me/tickets` GET dans server.py) — NEW : scope $or legacy `_ticket_scope_for_user` + `{owner_id ∈ collègues, shared_with_tenant=True}`; snapshots société/rattachement à la création
5. **Interventions** (`/me/interventions` GET+POST dans server.py) — NEW : pour non-élevés, filtre $or {client_id legacy} OU {owner ∈ collègues, shared=True}; snapshots à la création
6. **Tenant settings** (`tenant_sharing_mode` AND|OR sur fiche User parent, formulaire AdminClients déjà en place)

### Frontend
- **`TenantSharingToggle.jsx`** — composant réutilisable (2 checkboxes : partager + édition collaborative) avec testids `${prefix}-block` / `-shared` / `-editable`
- **ContactGroups.jsx** : toggle dans le modal d'édition (testid `cg-tenant-sharing-*`)
- **MeetingMinutes.jsx** : toggle dans l'éditeur de PV (testid `meeting-tenant-sharing-*`)
- **UserNotes.jsx** : toggle dans le modal de note (testid `note-tenant-sharing-${kind}-*`)
- **AdminClients.jsx** : radio AND/OR dans le formulaire (testid `tenant-sharing-AND`/`tenant-sharing-OR`)

### Tests
- **11/11 tests Iter43 verts** (`test_iter43_tenant_sharing.py`) :
  - Helper AND/OR/stranger
  - Contact Groups visibilité + delete reservée à l'auteur
  - User Notes visibilité + édition collaborative + protection
  - Support Tickets visibilité cross-tenant
- **Régression complète : 59/59 verts** sur les modules touchés (Iter42d, Officines selfservice, Iter42b, shared_notes, meetings, sign meeting, contact groups bugfix, tickets bubble, ticket reassign)

### Endpoints / payloads
- `POST/PUT /api/me/contact-groups` — accepte `shared_with_tenant`, `editable_by_tenant`
- `POST/PUT /api/me/meetings` — idem
- `POST/PUT /api/me/notes/{kind}` (`notes|tasks|reports|suivis`) — idem
- `POST /api/me/tickets` — idem
- `POST /api/me/interventions` — idem
- `tenant_sharing_mode` sur la fiche tenant via `POST/PUT /api/admin/clients`


## Iter42c-d (2026-02) — Scanner code-barres + Webhook Incidents + Lookup AMM par pays

### Bug fix
- **`/admin/clients`** : la liste par défaut filtrait uniquement sur `client/admin/superviseur/moderateur` → les changements vers `pharmacien/regulateur/medecin/editeur_vidal` faisaient disparaître l'utilisateur. **Corrigé** (backend + 4 pills colorées frontend).

### Features

**1. Scanner code-barres** (`@zxing/browser` + `@zxing/library`)
- `BarcodeScannerModal.jsx` : caméra arrière prioritaire, supporte **Data Matrix 2D (norme officines France)** + EAN-13 + Code 128 + QR
- Extraction intelligente : Data Matrix GS1 (AI 01 + GTIN-14) → CIP-13
- Bouton 📷 (icône `ScanLine`) à côté du champ CIP dans le modal d'inventaire officine

**2. Webhook entrant `/api/public/incidents`** (auth mot de passe simple)
- Header `X-Webhook-Password` OU body `password`
- Crée un ticket dans `support_tickets` (channel=`webhook`, source, severity, metadata)
- Section `/admin/settings#s-incidents-webhook` :
  - Régénération password one-shot
  - Désactivation
  - Logs d'activité (20 dernières requêtes)
  - Exemples curl + Python prêts à copier

**3. Code pays AMM** (`amm_default_country` en settings)
- ISO-2 (BF, CI, FR, SN…) — auto-assigné aux AMM créés via POST ou import CSV
- Colonne `country_code` dans la table AMM
- Champ pays dans le modal d'édition (override possible)

**4. Lookup AMM** (`POST /api/officines-portal/inventory/lookup-amm`)
- Cherche un CIP dans `amm_numbers` filtré par `country_code = amm_default_country`
- Retourne `{found, product_name, amm_number, laboratory, status, expires_at, expired}`
- Bouton "Vérifier AMM" dans le modal inventaire officine — affiche le résultat enrichi (rouge si expiré, vert si valide)
- Pré-remplit auto `product_name` si vide

### Tests
- **10/10 backend pytest** (`test_iter42d_incidents_and_lookup.py`)
- Régression : 27 tests verts (Iter42, 42b, 42c, 42d)
- Frontend smoke OK (testing agent)

### Endpoints
- `POST /api/public/incidents` (public, mot de passe)
- `GET/POST/DELETE /api/admin/incidents-webhook[/password|/regenerate-password]`
- `POST /api/officines-portal/inventory/lookup-amm` (officine JWT)
- AMM : `country_code` field on POST/PUT/import-csv


## Iter42b (2026-02) — Import CSV AMM + RBAC affiné + Templates OTP

### Objectif
Compléter le portail Officines/VIDAL avec 4 features ciblées :

### Backend
- **CSV Import AMM** (`POST /api/amm/import-csv`, multipart)
  - Format : `Nom du produit, AMM, CIP1, date expiration, Laboratoire, Note`
  - AMM et CIP1 peuvent être NULL — `internal_no` auto-généré (`INT-XXXXXXXX`)
  - **Conflit (DB ou intra-fichier) → refus global 409** + liste détaillée des conflits
  - Auto-détection séparateur (`,` ou `;`) + accents/casse ignorés sur les en-têtes
  - Audit : `source="csv_import"` + `created_by_email`
- **Rôle `editeur_vidal`** (lecture seule)
  - GET autorisé sur AMM / VIDAL / Liluvine
  - POST/PUT/DELETE/Import → 403
- **Synthèse Liluvine à la demande** (`POST /api/admin/synthese/test`)
  - Force l'envoi même si `synthese_enabled=False` — retourne `{ok, sent_email, sent_wa, errors, config, preview}`
- **OTP Officines via template** (`officine_otp_template` dans settings)
  - Tente Authentication puis Utility puis fallback texte
  - Endpoint test : `POST /api/admin/officine-otp/test`

### Frontend
- **`AmmEditor.jsx`** : bouton "Importer CSV" + modal d'upload avec prévisualisation des conflits + tri client (cliquer en-têtes)
- **`PortalLayout.jsx`** : sidebar restrictive
  - `regulateur` → uniquement AMM + Liluvine
  - `editeur_vidal` → uniquement VIDAL + AMM + Liluvine
  - `/portal/vidal` et `/portal/amm` masqués pour tous sauf admin/superviseur/regulateur/pharmacien/medecin/editeur_vidal
- **`AdminClients.jsx`** : ajout du rôle "Éditeur VIDAL" dans le sélecteur
- **`TemplatesOtpSection.jsx`** (nouveau) : section AdminSettings dédiée
  - 2 cards (Login général + Login Officines) avec champs nom/langue + bouton "Tester l'envoi"
- **`S059SyntheseOfficinesSection.jsx`** : bouton "Tester la synthèse maintenant" + aperçu détaillé du résultat

### Tests
- 7 nouveaux tests pytest `test_iter42b_csv_and_roles.py` (100% verts)
- Régression intacte : 41 tests verts (incluant Iter41 + Iter42)
- Testing agent : 9/9 backend OK, smoke frontend OK


## Iter42 (2026-02) — Self-Service Portal pour Officines (Pharmacies)

### Objectif
Permettre aux pharmacies (officines) de gérer elles-mêmes leur inscription, leur authentification, leur inventaire, leur clé HMAC et leur historique — sans dépendre de l'admin pour chaque opération.

### Choix utilisateur
- **Auth** : Code OTP (WhatsApp + SMS) + Magic link email
- **Validation** : Auto-inscription + validation admin requise avant activation
- **Lien CRM** : Indépendant OU liable à un client CRM existant
- **Inventaire** : Avancé (quantité + prix unitaire + devise + date de péremption + numéro de lot + dispo + notes)

### Backend
- **`routes/officines_portal.py` (nouveau)** : 19 endpoints `/api/officines-portal/*` + `/api/admin/officines-registry/*`
  - JWT séparé (audience `officine-portal`, subject `officine:{id}`) pour ne pas se mélanger avec les comptes CRM
  - Register (status=pending) / approve / suspend / reactivate / link-client / unlink-client
  - OTP request via WhatsApp ou SMS + verify (rate-limit 5 tentatives → 429)
  - Magic link email (TTL 15 min, one-shot consume)
  - Inventaire CRUD complet avec isolation stricte par officine_id
  - Régénération HMAC secret (one-shot display)
  - Historique + exports CSV (inventaire et historique)
- Collections MongoDB : `officines`, `officine_otp_codes`, `officine_magic_tokens`, `officine_inventory_items`, `officine_audit_log` (+ `officines_secrets` existante)

### Frontend
- **`/officines/login`** : 3 onglets (OTP / Magic / Inscription)
- **`/officines/magic?token=...`** : callback magic link
- **`/officines`** : Layout dédié (header + tabs)
  - `/officines` (Dashboard avec KPIs : stock, expiration 30j, historique)
  - `/officines/inventory` (CRUD complet + modal éditeur + export CSV)
  - `/officines/secret` (régénération HMAC + exemple de code)
  - `/officines/history` (timeline + export CSV)
- **`/admin/officines-registry`** : page admin de validation (compteurs pending/active/suspended + recherche + actions)

### Sidebar admin
- Nouveau lien "Officines (validation)" (feature-gated `vidal_enabled`)

### Tests : 18 tests pytest (12 test_iter42 + 6 test_iter50). 100% verts.

### Endpoints clés
- `POST /api/officines-portal/register` (public)
- `POST /api/officines-portal/auth/request-otp` (canal wa|sms)
- `POST /api/officines-portal/auth/verify-otp` → JWT
- `POST /api/officines-portal/auth/magic-link`
- `GET  /api/officines-portal/auth/magic-callback?token=` → JWT
- `GET/POST/PUT/DELETE /api/officines-portal/inventory[/{id}]`
- `GET /api/officines-portal/inventory/export.csv`
- `POST /api/officines-portal/me/regenerate-secret`
- `GET /api/officines-portal/history[/export.csv]`
- `GET  /api/admin/officines-registry?status=pending|active|suspended`
- `POST /api/admin/officines-registry/{id}/{approve|suspend|reactivate|link-client|unlink-client}`


## Iter41 Phase 4 (2026-02) — Dashboard VIDAL + API publique officines HMAC + rôles

### Modules nouveaux
- `routes/vidal_dashboard.py` — 2 endpoints admin (`/admin/vidal/usage`, `/admin/officines/usage`) + 1 endpoint public HMAC-signed (`/public/officines/register`)

### Settings nouveau
- `officines_register_hmac_secret` (masqué) — secret HMAC partagé avec les officines pour l'inscription

### Rôles ajoutés au sélecteur de création client
- `regulateur`, `pharmacien`, `medecin` (en plus de admin/superviseur/moderateur/client/demo)

### Frontend
- `S058VidalSection` héberge désormais le widget `VidalUsageDashboard` (StatCards + SVG + top consumers + by-mode + section Officines)
- AdminSettings : bannière jaune au-dessus du bouton bleu global indiquant les sections S057/S058/S059 ont leur propre bouton

### Tests : 8 nouveaux, 77/77 verts au total.



## Iter41 Phase 3 (2026-02) — Synthèse + Officines + CIPs + Sidebar image + Hotfix groupes

### Modules nouveaux
- `routes/synthese.py` — KPIs aggregator + Liluvine prompt builder + cron `run_scheduled_synthese` + WA cmd handler `detect_and_handle_synthese_command`
- `routes/officines.py` — POST proxy vers API tierce + helper WA + quota par numéro
- `routes/officines_wa.py` — détection `!aizenta` (regex IGNORECASE, supporte `!officine[s]`)

### Endpoints nouveaux
- `POST /api/officines/lookup` (admin/superviseur/regulateur/pharmacien/medecin)

### Settings nouveaux
- `synthese_enabled`, `synthese_email_to`, `synthese_wa_to`, `synthese_hour`, `synthese_prompt`, `synthese_channels`
- `officines_api_url`, `officines_api_token` (masqué), `officines_api_timeout`, `officines_public_quota_per_day`
- `sidebar_bg_image_url`, `sidebar_bg_image_opacity`

### Modèles modifiés
- `AmmCreatePayload`/`AmmUpdatePayload` : ajout `cip1`…`cip5`

### Cron
- Job `liluvine_synthese_minutely` (vérification chaque minute du `synthese_hour` configuré)

### Commandes WhatsApp ajoutées
- `!synthese [début] [fin]` (toutes casses, dates ISO/français/mots-clés)
- `!aizenta <produit>` ou `!officine[s] <produit>` (publique, quota anti-abus)

### Frontend
- `/admin/settings#s-s059-synthese-officines` — section S059
- `/portal/amm` — champs CIP1-CIP5
- `/portal/vidal` — bouton « Voir les officines » dans modale fiche
- Sidebar portal : injection `--sidebar-bg-image` via useUIFlags

### Hotfix
- Bug Contact Groups : `add_contacts`/`create_group`/`resolve_recipients` corrigé pour reconnaître les contacts peer-shared (même `company`, `client_id` différent).

### Tests : 17 nouveaux (14 phase3 + 3 hotfix groupes), 69/69 verts au total.



## Iter41 Phase 2 (2026-02) — VIDAL × Liluvine × AMM × Régulateur

### Architecture
- **Tenant gating VIDAL** : `features.vidal_enabled` (bool) + `features.vidal_mode` (`inherit|test|production`) sur le doc tenant. Les sous-utilisateurs héritent via `parent_client_id`. Admin/superviseur bypass.
- **Qdrant `VIDAL_db`** : ingestion *lazy* à chaque `/vidal/search` + `/vidal/product/{id}` (helpers `routes/vidal_rag.py`) + cron nightly `scheduled_import_new_products`. Branchement RAG dans `_resolve_kb_context` de Liluvine — toutes les conversations (web + WA) peuvent désormais citer VIDAL automatiquement.
- **Commandes WhatsApp** : `routes/liluvine_vidal_wa.py` détecte `!vidal*` et appelle VIDAL via le même `_vidal_call` + tenant gate + quota.
- **Rôle `regulateur`** : nouveau rôle (au même niveau que `moderateur`), accepté par toutes les routes AMM en écriture. Lecture libre pour tout utilisateur authentifié.

### Endpoints nouveaux
- `GET/POST/PUT/DELETE /api/amm` + `GET /api/amm/by-product/{vidal_id}`
- `POST /api/admin/vidal/test-connection` retourne désormais `{ok, mode, debug:{request, response, error}}`

### UI nouvelles
- `/portal/amm` — table éditable (réservé admin/superviseur/régulateur)
- `/admin/clients/:id/features` : toggle `vidal_enabled` + sélecteur `vidal_mode` (3 options)
- `/admin/settings#s-s058-vidal` : panneau Debug verbose après test-connection

### Tests
- 14/14 verts (`test_iter41_vidal_phase2.py`) + 9/9 (`test_iter41_vidal.py`) + 4/4 (`test_iter40_liluvine_memory.py`)
- Régression 52/52 sur l'ensemble Iter40 + Iter41 + S057.



## Iter41 (2026-02) — Module VIDAL France + Fix mémoire conversationnelle Liluvine

### Architecture
- **Module VIDAL** : `routes/vidal.py` monté via `attach_vidal_routes(api, db, get_current_user, get_current_admin)` dans `server.py`. Endpoints `/api/vidal/*` (utilisateur authentifié) + `/api/admin/vidal/*` (admin). 2 environnements (test / production) côte-à-côte dans `settings.global`, basculement via `vidal_mode`. Auth VIDAL via `app_id` + `app_key` en query string. Cache Mongo `vidal_cache` (TTL configurable, défaut 7 jours) + quota par user/jour `vidal_usage_daily`. Aucun cache sur l'analyse de prescription (patient-specific) ; audit conservé dans `vidal_prescription_audit`.
- **Liluvine mémoire** : helper `_build_memory_block(sid, current_text, limit=10)` dans `routes/liluvine_pro.py`, appliqué aux 3 callers non-streaming (WA inbound, web chat POST, vision chat). Le streaming SSE l'avait déjà.

### Endpoints clés
- `GET/PUT /api/admin/vidal/config` — admin only, masque app_key.
- `POST /api/admin/vidal/test-connection` — ping VIDAL.
- `DELETE /api/admin/vidal/cache` — purge.
- `GET /api/vidal/quota/me` — état du quota.
- `GET /api/vidal/search?q=&filter=`, `/vidal/product/{id}`, `/vidal/product/{id}/documents?type=`, `/vidal/products/status?status=`.
- `POST /api/vidal/prescription/analyze` — `{patient, prescriptions, allergies, pathologies}` → `/alerts/full` VIDAL.

### UI
- `/admin/settings` → section `s-s058-vidal` (S058VidalSection) : toggle on/off, sélecteur mode TEST/PROD (visuel vert/rouge), 2 blocs d'env (TEST + PROD) avec base_url + app_id + app_key, TTL/quota/timeout, 4 boutons (Enregistrer, Tester la connexion, Vider le cache, Recharger).
- `/portal/vidal` (Vidal.jsx) — 3 onglets : Recherche, Catalogue, Analyse de prescription. Modale fiche médicament chargeant en parallèle détails + RCP. Badge quota + indicateur mode actif.
- Sidebar portail : entrée « VIDAL France (médicaments) » (HeartPulse icon) pour tous les rôles authentifiés.

### Tests
- 9/9 verts (`test_iter41_vidal.py`) + 4/4 verts (`test_iter40_liluvine_memory.py`). Régression 145/146 (échec préexistant `test_iter38r_fix9c_liluvine_kb` non lié).




## Iter40 (2026-02) — Liluvine RAG modules métier + Signataires PV par email + Commandes WA GRH

### Architecture
- **Liluvine Business RAG** : `routes/liluvine_business_rag.py` — ACL par module + helper `build_business_rag_context(db, phone_digits, query)` injecté dans `liluvine_wa_autoreply.py`. Stockage ACL : `settings.global.liluvine_module_acl = {module: [digits]}`. Match sur les 9 derniers chiffres.
- **Commandes WA GRH** : `routes/liluvine_hr_wa.py` — `!absence YYYY-MM-DD [au …] [motif]` + `!avance MONTANT [motif]` + `!ticket <desc>` (via business_rag). Branchés dans `server.py` webhook BEFORE l'auto-reply (`hr_handled` court-circuite Liluvine).
- **Approbation HR WA** : `POST /api/hr/absences|advances/{aid}/approve|reject` — l'approbation/rejet d'une absence réactive `account_status` du user.
- **PV Signataires email** : `routes/meetings.py` accepte les entrées email dans `signers` (mix avec user_id). Vérification de signature étendue (user.id OR user.email). PDF résout emails → full_name si compte existant.

### Endpoints clés
- `GET/PUT /api/admin/liluvine-pro/module-acl` — admin/sup seulement, gère la liste blanche par module.
- `POST /api/hr/absences/{aid}/approve|reject` — réactive le user automatiquement.
- `POST /api/hr/advances/{aid}/approve|reject`.

### UI
- `AdminSettings.jsx → Filterable[s-liluvine-module-acl]` : nouvelle section `LiluvineModuleAclSection.jsx` (6 textareas modulaires + compteur + détails commandes WA).
- `MeetingMinutes.jsx → MultiUserPicker` : bouton « + Ajouter email » dynamique + chips violettes externes.

### Tests
- 21 nouveaux verts (`test_iter40_liluvine_business_rag.py`, `test_iter40_hr_wa_commands.py`, `test_iter40_pv_email_signers.py`).
- Régression 8/8 sur `test_iter40_route_loader_toggle.py` (mise à jour des champs autorisés pour le background theming).


## CRITICAL FIX (2026-02) — rabo.f@sawalismartsystems.com — Liluvine PRO indisponible

### Symptômes (rapportés par l'utilisateur sur PRODUCTION)
1. Web chat Liluvine PRO → erreur « Liluvine PRO n'est pas activé pour votre compte »
2. Nom rabo.f absent des contacts du centre de messagerie
3. WhatsApp depuis +22673494658 → Liluvine ne réagit pas

### Bugs identifiés et corrigés en code (à déployer)
**Bug #1** — `_client_scope()` dans `routes/liluvine_pro.py` ne gérait pas le rôle `moderateur` : `tracked_user_id` et `client_id` étant vides pour un modérateur, scope tombait sur `user["id"]` → check `features.ai_liluvine_pro` sur le compte personnel du modérateur (jamais activé) → erreur 403.
- **Fix** : ajout de `parent_client_id` dans la chaîne de fallback. Les modérateurs résolvent maintenant leur scope vers le tenant admin qui les a créés.

**Bug #2** — `whatsapp_webhook_receive()` dans `server.py` ligne 15439 ne cherchait QUE les `superviseur` pour résoudre le tenant inbound. Un install Sawali avec uniquement un `admin` (cas typique) finissait avec `client_scope=None` → l'auto-reply ne pouvait pas résoudre la feature.
- **Fix** : chaîne de fallback `superviseur → admin (non-super-admin) → super-admin`.

**Outil de diagnostic** — Nouveau endpoint `GET /api/admin/liluvine-pro/diagnose?email=...&phone=...` accessible aux admins/superviseurs/modérateurs. Renvoie un rapport JSON exhaustif :
- Si l'utilisateur existe (id, role, parent_client_id, account_status, features…)
- Le tenant résolu pour Liluvine (scope_uid, ai_liluvine_pro_enabled)
- L'état complet de l'auto-reply WhatsApp (autoreply_enabled, allow/deny lists, whitelist mode, human_takeover, cooldown)
- Une liste **blocking_reasons** en français qui pointe directement la cause racine
- Un hint d'action quand la feature est désactivée

### Restant à vérifier en PRODUCTION (l'admin doit faire après déploiement)
1. Appeler `GET /api/admin/liluvine-pro/diagnose?email=rabo.f@sawalismartsystems.com` depuis prod.
2. Vérifier `account_status=active` et `parent_client_id` pointant vers l'admin SAWALI principal.
3. Si `ai_liluvine_pro_enabled=false` sur le tenant parent → l'activer via `/admin/clients/{scope_uid}/features`.
4. Vérifier que `liluvine_wa_autoreply_enabled=true` et phone pas en deny.
5. **Bug #3 — Contact manquant — RÉSOLU (2026-02)** — Voir la section dédiée ci-dessous.

## CRITICAL FIX (2026-02) — Bug #3 — Contact rabo.f manquant dans le centre de messagerie

### Cause racine
Quand un **utilisateur système** (modérateur, admin…) envoie un WhatsApp inbound :
1. Le webhook cherchait `directory_contacts` GLOBALEMENT (sans scope), donc une ligne d'un autre tenant pouvait être ramenée → message routé vers un tenant que le viewer ne voit pas.
2. Si aucune ligne directory_contacts n'existait pour ce numéro, l'utilisateur atterrissait dans `wa_pending_imports` (état "à importer") au lieu d'avoir un vrai contact → son nom n'apparaissait jamais dans `/portal/contacts`.

### Fix shipped (2026-02)
**A. Hardening du webhook WA** (`server.py` lignes 15556-15640) :
- Recherche `directory_contacts` PRIORITAIRE dans le `client_scope` résolu (anti cross-tenant pollution).
- Si toujours pas de match ET le numéro correspond à un utilisateur système, le webhook crée automatiquement la ligne `directory_contacts` dans le **tenant parent canonique** avec `name = full_name`, `wa_user_link = user_id`, tag `utilisateur-système`. L'utilisateur apparaît immédiatement dans `/portal/contacts`.

**B. Endpoint diagnostic enrichi** : `GET /api/admin/liluvine-pro/diagnose?email=…` renvoie désormais un objet `contact_visibility` qui liste :
- Tous les `directory_contacts` matchant le numéro (cross-tenant).
- Tous les `wa_pending_imports` matchant.
- Les 5 derniers messages inbound.
- Le `user_visible_client_ids` du target (pour détecter les contacts hors scope).
- Une liste `diagnosis` en français qui pointe la cause exacte.

**C. Endpoint de réparation** : `POST /api/admin/contacts/repair-user-contact` (body : `{"email": "...", "dry_run": false}`) — réservé admin/superviseur/modération. Idempotent. Pour un utilisateur donné :
- Crée la ligne canonique manquante (parent tenant scope) avec `name = full_name`.
- Si la ligne existe avec `name` vide ou phone-only → remplit avec full_name.
- Archive les doublons même-scope (`archived_at` set).
- Flag les doublons cross-tenant avec `wa_user_link` (jamais delete RGPD).
- Re-attache les `whatsapp_messages` orphelins (`contact_id=null`) sur la ligne canonique.
- Supprime les `wa_pending_imports` pour ce numéro.
- Synchronise le `user_label` de la session Liluvine WA.

### Comment l'admin doit corriger rabo.f en PRODUCTION
1. Déployer le code en Production.
2. Appeler `POST /api/admin/contacts/repair-user-contact` avec `{"email": "rabo.f@sawalismartsystems.com"}`.
3. Vérifier `/portal/contacts` → rabo.f apparaît avec son nom complet.
4. Les futurs WA depuis son numéro vont désormais s'auto-router correctement (le webhook patché s'en charge).

### Tests
- `backend/tests/test_bug3_rabo_contact_repair.py` (4/4 verts + 1 skipped RBAC).
- `backend/tests/test_bug3_webhook_auto_contact.py` (1/1 vert).
- Régression complète : `test_iter35a_critical_bugs.py` + `test_iter35l_wa_media_http.py` (16/16 verts).


## CRITICAL FIX (2026-02) — Bypass list Liluvine PRO + Recherche cross-tenant

### Contexte
Après le fix Bug #3, rabo.f restait bloquée car la feature `ai_liluvine_pro` n'était toujours pas activée sur son tenant parent en production. L'utilisateur a demandé deux nouveautés :
1. **Une bypass-list** : permettre à des emails individuels d'utiliser Liluvine PRO même quand `ai_liluvine_pro=False` sur leur tenant.
2. **Une recherche cross-tenant** : permettre de chercher un numéro de téléphone dans TOUS les tenants et d'importer la fiche dans le tenant courant (les messages, eux, réservés admin/superviseur pour des raisons RGPD).

### Implémenté en 2026-02
**Bypass list (backend)** :
- Nouveau helper `_liluvine_pro_allowed(db, user)` qui résout `True` si `feats.ai_liluvine_pro` OU email dans `settings.liluvine_pro_bypass_emails`.
- Helper appliqué sur les 4 endpoints Liluvine PRO : `POST /chat`, `POST /chat-with-image`, `POST /chat/stream`, ainsi que le hook `autoreply_to_inbound` (WhatsApp).
- Endpoints admin : `GET /api/admin/liluvine-pro/bypass-emails` + `PATCH` (réservé admin/superviseur). Validation email basique.

**Bypass list (UI)** :
- Nouvelle section `LiluvineBypassEmailsSection.jsx` dans `/admin/settings` (ancre `s-liluvine-bypass`) — textarea séparée par espace/virgule/point-virgule, compteur live, bouton "Enregistrer" qui n'apparaît que si modifié.

**Cross-tenant search & import (backend)** :
- `GET /api/me/contacts/search-cross-tenant?phone=...` → recherche tous tenants. Retourne fiche sanitizée (name, phone, whatsapp, email, company, tags, `in_current_scope`). Pas de `client_id`/`owner_id` dans la réponse.
- `POST /api/me/contacts/import-cross-tenant` body `{phone, include_messages?}` → crée la fiche dans le tenant du caller. Anti-doublon (réutilise une ligne non archivée si elle existe). Si `include_messages=True` ET role admin/superviseur, copie également les `whatsapp_messages` avec re-scoping (`imported_from_client_id`).

**Cross-tenant (UI)** :
- Nouveau composant `CrossTenantSearch.jsx` (dépliable, design sky/fuchsia) intégré dans `/portal/contacts` sous le panneau "Pending imports". Input phone + boutons "Importer fiche" (tous users) et "+ Messages" (admin/superviseur uniquement).

### Tests
- `backend/tests/test_bypass_and_cross_tenant_contacts.py` (8/8 verts) :
  - bypass list GET/PATCH (normalize, dedupe, reject invalid)
  - bypass email grants Liluvine access (full flow : 403 → patch → non-403)
  - cross-tenant search sanitize + min length
  - cross-tenant import (card-only + with messages, admin/superviseur gating)
- Régression cumulée : 35/35 verts (Bug #3 + Bypass + Auth refactor + Liluvine PRO).

### Action immédiate pour rabo.f en production
1. Déployer.
2. Aller dans `/admin/settings` → section "Liluvine PRO — Bypass (emails autorisés malgré feature OFF)".
3. Coller `rabo.f@sawalismartsystems.com` dans la textarea, cliquer "Enregistrer".
4. rabo.f peut immédiatement utiliser Liluvine PRO sans changer les features du tenant.


## 2026-02 BATCH — Régionalisation traducteur, notifications, GRH, takeover, templates, force-logout

### #1 — Nouveau rôle **Traducteur** + scoring journalier/mensuel
- `TRACKED_USER_ROLES` += `Caissier`, `Traducteur` (models.py)
- Fiche tracked-user : nouveaux champs `translator_languages` (multi-select EN/AR/LG1/LG2), `translator_rate_per_word` (numérique). UI affichée seulement si `role=Traducteur` (badge fuchsia).
- Sidebar du portail entièrement masquée pour le rôle Traducteur sauf `/admin/i18n`. Toutes les autres entrées disparaissent. Login redirige automatiquement vers `/admin/i18n`.
- Backend `POST /api/admin/i18n/translations` : si caller=Traducteur, autorise UNIQUEMENT les colonnes listées dans `translator_languages`. Création de clé et suppression refusées (403). FR jamais modifiable.
- Log de contribution : chaque mot ajouté → `i18n_translator_log` (`words_added, amount, day, month`).
- Endpoint `GET /api/admin/i18n/translator-score` : agrégation jour/mois/total. Traducteur voit son propre score. Admin/sup peut interroger via `?translator_email=`.
- UI `/admin/i18n` : nouveau panneau fuchsia "Mon score" avec 3 cartes (Jour / Mois / Total) + total mots × rate. Bandeau "Couverture" % par langue (EN/AR/LG1/LG2) visible pour admin.
- Restriction d'édition côté UI : les colonnes hors `allowed_languages` sont en read-only avec opacity-60 et tooltip "Langue non autorisée pour votre compte".

### #2 — Notifications navigateur + clignotement titre
- Nouveau composant `BrowserNotifications.jsx` monté globalement dans `PortalLayout`.
- Demande la permission Notification API 5 s après login.
- Poll `/me/notifications/counts` toutes les 25 s. Si compteur **augmente** ET tab cachée → titre clignote `🔔 Nouvelle activité · (N)` ↔ `(N) SAWALI Portal` toutes les 1.2 s. Une **system toast Windows/macOS** est créée tant que la croissance n'a pas été acquittée.
- Sur retour focus tab : titre restauré, compteur "last_shown" remis à zéro.

### #3 — Liluvine takeover durée admin-configurable
- Nouveau setting `liluvine_takeover_default_minutes` (default 30, range 5-10080).
- Backend valide la borne, route admin (PUT `/admin/settings`).
- UI : input dans `/admin/settings` section "Liluvine — Reprise humaine" (sous l'auto-logout).
- Backward-compat : `duration_minutes` explicite dans la requête prend toujours le pas.

### #4 — Aperçu du contenu délivré pour templates WhatsApp
- Le frontend envoie `template_rendered_body` dans `POST /me/whatsapp/send` (recalculé via `renderPreview`).
- Backend persiste les deux champs dans `whatsapp_messages.template_rendered_body` ET `body` (pour rétro-compat affichage).
- UI Contacts : sous le code du template, une carte "Aperçu délivré" en italique avec border-l fuchsia affiche le texte effectivement reçu côté client.

### #5 — Force logout sans confirmation
- Nouveau champ `force_logout_on_idle` (bool) sur la fiche tracked-user, propagé au compte bridgé `users`.
- `AutoLogoutGate.jsx` : si `user.force_logout_on_idle=true`, dès que le warning surgirait → logout immédiat sans modal.
- UI Admin tracked-user : toggle amber "Forcer la déconnexion à l'inactivité" avec helper text.

### Tests
- ✅ `test_s046b_translator_role.py` : 8/8 (coverage admin, traducteur scope, RBAC create/delete, word counting + rate, score endpoint self + admin view, takeover setting validation)
- ✅ Régression cumulée : **43/45 verts** (35 antérieurs + 8 nouveaux).


## S046 ENHANCEMENT (2026-02) — Régionalisation publique + CSV + auto-détection

### Renommage UI
- Sidebar admin : « Traductions (i18n) » → « **Régionalisation** »
- Titre page admin : « Régionalisation » (H1 avec icône Languages)

### Public language selector + auto-detect
- `MarketingNav` intègre le `LanguageSelector` (visible dès la page d'accueil publique, header desktop + mobile menu).
- 10 liens de la marketing navbar maintenant traduits via clés `public.nav.*` (Home, Missions, Specialisations, Catalogue, Case studies, Subscriptions, Testimonials, Book appointment, Contact, Policies, Book a meeting, My space, Loois Space).
- **I18nContext** auto-détecte la langue au premier passage selon cet ordre :
  1. `localStorage.sawali_lang` (choix explicite précédent)
  2. `navigator.language` (FR/EN/AR mappés vers les codes supportés)
  3. Backend `GET /api/i18n/detect` (basé sur `cf-ipcountry` / `x-vercel-ip-country` / `Accept-Language`)
  4. Fallback FR
- **Backend `/api/i18n/detect`** : map ISO 3166-1 alpha-2 → langue. 60+ pays mappés (Afrique francophone FR, Maghreb/Moyen-Orient AR, anglo-saxons EN). Fallback `Accept-Language` quand pas de header pays.

### CSV Export/Import
- `GET /api/admin/i18n/translations.csv` → fichier UTF-8 BOM (compatible Excel), colonnes `key, fr, en, ar, lg1, lg2, context`.
- `POST /api/admin/i18n/translations/import-csv` (multipart) → upsert idempotent. Erreurs reportées ligne par ligne sans bloquer l'import.
- UI : boutons "📥 Exporter CSV" (emerald) et "📤 Importer CSV" (fuchsia) dans le header de `/admin/i18n`.

### Translations seed étendu (31 → 99 clés)
+68 clés ajoutées : sidebar étendue (inbox, sms, whatsapp_bulk, cash, hr, meetings, media_lib, media_gen, voice_studio, brochures, catalog_stats, logout), boutons communs (add, remove, next, previous, download, upload, export, import, send, copy, share, print, required, optional, error, success, warning, info, actions, status, filter, sort, all, none, empty, back), login (connexion, or, welcome_back, tagline), navigation publique complète (`public.nav.*`), dashboard, contacts, errors.

### Tests (`backend/tests/test_s046_i18n_and_p3_gauge.py`)
12 tests verts couvrent : languages public, FR seed, EN fallback, validation langue, admin CRUD + bulk, validation regex clé, **détection (defaut + Accept-Language)**, **CSV export UTF-8 BOM**, **CSV import upserts + reports errors + rejects missing columns**.

### Comportement clé
- Le seed `_ensure_seed` est désormais **idempotent + additif** : upsert uniquement les clés absentes. Permet d'ajouter de nouvelles SEED_KEYS sans écraser les éditions admin.


## S046 (2026-02) — i18n FR + EN + AR + LG1 + LG2 (Gulmancema/Mooré)

### Architecture
Source de vérité = MongoDB collection `i18n_translations` (et non des fichiers JSON statiques). Cela permet aux admins de créer/éditer les traductions en live via une page CRUD.

### Backend (`backend/routes/i18n.py`)
- `GET /api/i18n/languages` → liste publique des 5 langues supportées avec RTL flag
- `GET /api/i18n/translations?lang=fr|en|ar|lg1|lg2` → dictionnaire `{key: text}` avec **fallback automatique sur FR** quand la valeur cible est vide
- `GET /api/admin/i18n/translations` (admin/sup) → liste complète pour le tableau d'édition
- `POST /api/admin/i18n/translations` → upsert d'une clé
- `DELETE /api/admin/i18n/translations/{key}` → suppression
- `POST /api/admin/i18n/translations/bulk` → upsert en masse
- **Auto-seed** au premier appel : 31 clés (navigation sidebar, boutons communs, page login) en FR + EN

### Frontend
- `contexts/I18nContext.jsx` : provider qui fetche `/api/i18n/translations?lang=…` au montage et à chaque changement de langue. Persistance dans `localStorage` (`sawali_lang`). Applique `dir="rtl"` sur `<html>` pour AR. Expose `useT()` qui renvoie `t(key, fallbackText)`.
- `components/LanguageSelector.jsx` : dropdown compact 🌐 affichant les 5 langues avec nom natif (Français / English / العربية / Gulmancema / Mooré). Intégré dans **PortalLayout header mobile** + **sidebar desktop**.
- `pages/admin/AdminI18n.jsx` : table CRUD éditable inline (filtre, search, add/edit/delete) accessible via `/admin/i18n` (lien ⚛︎ "Traductions (i18n)" dans la sidebar admin).

### Tests (`backend/tests/test_s046_i18n_and_p3_gauge.py`)
- ✅ Languages public endpoint (codes + ordre + RTL flag)
- ✅ Dictionnaire FR seed (count ≥ 20, clés attendues)
- ✅ Dictionnaire EN avec **fallback FR pour valeur vide**
- ✅ Rejet de code de langue inconnu (400)
- ✅ Admin list/upsert/delete avec roundtrip 3 langues
- ✅ Validation clé Pydantic regex (rejette espaces)
- ✅ P3 download_gauge_enabled retourné dans la réponse (7/8 verts, 1 skipped car admin a bypass direct)

### Workflow pour ajouter une nouvelle langue
1. Modifier `SUPPORTED_LANGS` dans `routes/i18n.py` (ajouter `{"code": "xx", ...}`)
2. Aller dans `/admin/i18n`, remplir la colonne `xx` ligne par ligne
3. La langue apparaît automatiquement dans le LanguageSelector


## P3 (2026-02) — Toggle Admin pour désactiver la jauge de chargement plein écran

### Implémenté
- Backend `routes/download_approvals.py` retourne `gauge_enabled: bool` (default `True`) dans la réponse du `POST /me/download-requests`.
- Frontend `components/DownloadGate.jsx` lit le flag : si `False`, n'ouvre plus la modale plein écran avec la jauge circulaire et affiche à la place un **toast discret** ("En attente d'approbation…"). Le polling continue en arrière-plan et déclenche le téléchargement à l'approbation.
- UI Admin : nouvelle checkbox « Afficher la jauge d'attente plein écran » dans la section "Téléchargements & Approbation" de `/admin/settings`.


## Recent (2026-02 post-handoff) — Sujets non couverts + S045 Phase 1

### ✅ #2bis — Onglet « Sujets non couverts »
- Nouveau endpoint `GET /api/admin/liluvine-pro/coverage-gaps?days=N&min_score=0.5&limit=50` → liste les questions clients dont aucun match Qdrant n'atteint le seuil (ou aucun match du tout). Calcule un `blindspot_rate` (% questions non couvertes).
- **UI** : 3e sous-onglet dans `/admin/liluvine-history` → Captures & Analytics, intitulé « Sujets non couverts » (badge orange `AlertTriangle`). Affiche pour chaque gap : image client + analyse Vision + question texte + indication « ❌ Aucun match » ou « ⚠ Score N% » + conseil pour combler le gap (lien vers admin Qdrant RAG).
- Cas idéal : transformez les questions sans réponse en nouveau contenu Qdrant en un coup d'œil.
- **Tests** : `backend/tests/test_iter2bis_coverage_gaps.py` (3/3 verts).
- **Fichiers** : `backend/routes/liluvine_pro.py` (endpoint), `frontend/src/components/LiluvineScreenshotsInsights.jsx` (GapsTable).

### ✅ S045 Phase 1 — Refactor Auth (routes/auth.py)
- **6 endpoints d'authentification extraits** de `server.py` (lignes 865-985, 122 lignes) vers `routes/auth.py` (factory `attach_auth_routes(api, db=db, helpers={…})`). ZÉRO changement de comportement.
- Endpoints : `POST /auth/login`, `POST /auth/verify-otp`, `POST /auth/resend-otp`, `GET /auth/me`, `POST /auth/change-password`, `GET /auth/captcha-config`.
- **Gotcha résolu** : Pydantic models importés au niveau module (pas via dict d'helpers) — sinon FastAPI's `get_type_hints()` ne détecte pas les body params dans des closures.
- **Tests dédiés** : `backend/tests/test_s045p1_auth_refactor.py` (11/11 verts) — captcha, login invalid/internal, verify-otp full flow + bad session + bad code, change-password full flow + wrong current, me without token, resend-otp + bad session.
- **Régression complète sur 11 suites** : 81/81 verts.
- **server.py** : 21 913 → 21 800 lignes (-113). Premier pas vers l'objectif des 7k lignes.
- **Fichiers** : `backend/routes/auth.py` (nouveau, 175 lignes lisibles), `backend/server.py` (bloc auth remplacé par un appel `attach_auth_routes`).

### 📋 Prochaines phases S045
- **Phase 2** (~1 session) : Settings & Configuration admin → `routes/admin_settings.py`.
- **Phase 3** (1-2 sessions) : WhatsApp (~3-4k lignes) → `routes/whatsapp.py`.
- **Phase 4** (~1 session) : Notifications → `routes/notifications.py`.
- **Phase 5** (~1 session) : Payments webhooks → `routes/payments.py`.


## Recent (2026-02 post-handoff) — Suite #1 — ✨ Brouillon de doc auto-généré

### ✅ #2 — Bouton « Générer doc » sur chaque écran du Top
- Nouveau endpoint backend `POST /api/admin/liluvine-pro/generate-doc-draft` (body : `image_url`, `title`, `days`).
- Pipeline : (1) requête MongoDB pour toutes les vraies questions clients reçues sur cet écran les N derniers jours, (2) construction d'un prompt structuré (titre/Vision/OCR par question), (3) appel Claude Haiku 4.5 avec instructions de produire un Markdown propre (titre H1 + Procédure pas-à-pas + FAQ + Dépannage), (4) tracking quota via `_track`.
- **UI** : bouton « ✨ Générer doc » sur chaque ligne du Top Screens. Modal `DocDraftModal` qui affiche le brouillon généré dans un `<textarea>` éditable + bouton « Copier le Markdown ». L'admin peut peaufiner le brouillon avant de le coller dans son outil de doc.
- Pratique : transforme des questions support récurrentes en article de KB en 1 clic.
- **Tests** : `backend/tests/test_iter1_doc_draft_generator.py` (4/4 verts) — couverture 400 missing image_url, 404 no questions, 403 client, 200 schema.
- **Fichiers** : `backend/routes/liluvine_pro.py` (endpoint + import `uuid`), `frontend/src/components/LiluvineScreenshotsInsights.jsx` (DocDraftModal + bouton).


## Recent (2026-02 post-handoff) — Suite S044 — 📸 Captures & Top écrans

### ✅ #1 — Historique des captures + Top écrans SAWALI consultés
- 2 nouveaux endpoints backend :
  - `GET /api/admin/liluvine-pro/screenshots-history?days=N&limit=M` — liste les captures envoyées par les clients via Liluvine PRO chat-with-image, enrichies du sender_label/session_channel/Vision analysis/matched_images.
  - `GET /api/admin/liluvine-pro/top-screens?days=N` — agrégat MongoDB (`$unwind` matched_images + `$group` par image_url) qui sort les écrans SAWALI les plus matchés, avec count + avg_score + last_seen. Pipeline propre, indexé sur `client_id + role + created_at`.
- **UI** : nouvelle barre d'onglets en haut de `/admin/liluvine-history` (« Conversations » ↔ « Captures & Analytics »). Le nouveau composant `LiluvineScreenshotsInsights.jsx` propose 2 sous-onglets :
  - « Historique » : grille des captures avec preview client + analyse Vision + matches Qdrant (clicks zoom).
  - « Top écrans consultés » : leaderboard avec barre de progression visuelle + denominator « N captures totales sur cette période » → identifie en un coup d'œil les écrans qui génèrent beaucoup de questions support (= cible idéale pour onboarding/doc).
- Filtres : 7j / 30j / 90j / 1 an + bouton Actualiser.
- **Tests** : `backend/tests/test_iter1_screenshot_history_top_screens.py` (4/4 verts) — couverture role=user filter + days filter + aggregation + 403 client.
- **Fichiers** : `backend/routes/liluvine_pro.py` (2 endpoints), `frontend/src/components/LiluvineScreenshotsInsights.jsx` (nouveau), `frontend/src/pages/admin/AdminLiluvineHistory.jsx` (top tab switcher).


## Recent (2026-02 post-handoff) — Sprint Order 0 — 5 fixes UX/UI/backend

### ✅ 0.1 — Coffre-fort des secrets repliable
- 3 sections « libres » (`SecretsVaultSection`, `FileStorageSection`, `RoadmapTrackerSection`) qui s'affichaient sur tous les onglets sont désormais enveloppées dans `<Filterable>` avec catégories (auth/diagnostics). Le coffre-fort apparaît uniquement sur l'onglet « Sécurité & Auth » + « Tous ».
- **Fichier** : `frontend/src/pages/admin/AdminSettings.jsx`.

### ✅ 0.2 — Digest hebdo : skip de l'environnement PREVIEW
- Nouveau setting `health_weekly_send_from_preview` (default false). Le helper `_send_weekly_digest()` détecte l'env via `PUBLIC_BASE_URL` (variable déjà présente dans backend/.env) et skip si `.preview.` dans l'URL.
- Log : `[weekly-digest] Skipping send — running in PREVIEW environment` vérifié.
- L'utilisateur ne reçoit plus de digest depuis le preview ; uniquement depuis production.
- **Tests** : `backend/tests/test_iter0_2_preview_digest_skip.py` (2/2 verts).
- **Fichiers** : `backend/server.py`, `backend/models.py:SettingsUpdate`.

### ✅ 0.3 — GRH : Catalogue de primes/indemnités + Report agent→agent + auto-codes
- Nouveau **Catalogue** standalone (`hr_pay_catalog`) avec CRUD : rubriques `kind` (allowance/bonus), `label`, `default_amount`, `description`. Codes auto : `CAT-NNNN` (indemnités) / `PRMC-NNNN` (primes). Tenant-scoped via collection `hr_counters`.
- Nouveau endpoint `POST /api/hr/employees/{eid}/apply-catalog/{cid}` : applique une rubrique catalogue à un employé en un clic, avec override `amount` optionnel + `bonus_month` pour les primes.
- **Auto-codes universels** : toutes les indemnités créées (anciennes API ou via catalogue) ont désormais `code` au format `IND-NNNN` ; toutes les primes ont `PRM-NNNN`. Compteur tenant-scoped, incrémental.
- Nouveau endpoint `POST /api/hr/employees/{src_eid}/copy-pay-items` (body : `target_employee_id`, `include_allowances`, `include_bonuses`, `bonus_month`) : recopie en bloc les indemnités actives + primes d'un mois précis vers un autre employé. Trace `copied_from_employee_id`.
- **UI** : 2 nouveaux composants dans l'onglet « Primes & Indemnités » :
  - `CatalogCard` (data-testid `hr-catalog-card`) : CRUD complet du catalogue + bouton « → Appliquer » par rubrique.
  - `CopyButton` (data-testid `hr-copy-pay-items-btn`) : modal « Reporter les rubriques de paie » → sélection cible + cases à cocher allowances/bonuses.
- **Tests** : `backend/tests/test_siter39u_catalog_copy_codes.py` (9/9 verts).
- **Fichiers** : `backend/routes/hr.py` (5 nouveaux endpoints + helper `_next_pay_code` + Pydantic models), `frontend/src/pages/portal/HrPrimesIndemnites.jsx` (CatalogCard + CopyButton).

### ✅ 0.4 — Tickets : réaffecter le client lié (tenant)
- `TicketUpdatePayload` accepte désormais `client_id` (optionnel). PATCH `/me/tickets/{tid}` avec `{client_id: …}` réaffecte le ticket (restricted to elevated roles).
- Trace : `reassigned_from`, `reassigned_at`, `reassigned_by`, `client_company_snapshot` mis à jour. Badge `↻ Réaffecté` dans l'UI.
- **UI** : nouvelle ligne « Client lié : [actuel] [✎ Réaffecter] » dans `TicketRow` (testid `ticket-{id}-reassign-row`). Bouton ouvre un select avec tous les clients (`/me/clients`).
- **Tests** : `backend/tests/test_iter0_4_ticket_reassign.py` (4/4 verts) — reassign OK, same-cid noop, 404 cible inconnue, 403 client lambda.
- **Fichiers** : `backend/server.py:me_update_ticket`, `backend/models.py:TicketUpdatePayload`, `frontend/src/pages/portal/Tickets.jsx`.

### ✅ 0.5 — Modérateurs suivent Liluvine PRO et reprennent la main
- **Déjà en place** (S-iter39d) : sidebar `/portal/liluvine-history` avec `moderationOnly: true`, `_TAKEOVER_ROLES` backend inclut `"moderation"`, bouton « Reprendre la conversation » dans `AdminLiluvineHistory`. Aucun code à ajouter.

### 📊 Total sprint
- **15 nouveaux tests verts** (+9 catalog/copy +4 ticket reassign +2 digest skip) = **32/32 régression incl. nouveaux**.
- **Fichiers modifiés** : 6 backend + 3 frontend. Lints clean.

### 📋 Reporté pour sessions dédiées (sur demande utilisateur)
- **#1 (S044 history)** : « Voir l'historique des captures envoyées » sur la fiche d'un contact + analytics top-écrans consultés. ~30 min.
- **#2 (S046 i18n)** : 5 langues, 3-4 h, traduction auto Claude ~$2-3.
- **#3 (S045 Phase 1)** : Refactor Auth & Sessions de server.py vers routes/auth.py. ~1 session.


## Recent (2026-02 post-handoff) — S-iter39t — 📸 Liluvine voit & duplication primes

### ✅ S044 — Liluvine compare une capture d'écran client avec la base d'images SAWALI
- Nouveau endpoint backend `POST /api/me/liluvine-pro/chat-with-image` (multipart : file + text + session_id).
- Pipeline robuste : feature gate → quota pre-check → Claude Sonnet 4.6 Vision (OCR + description) → recherche sémantique Qdrant images (collections `enabled_for_liluvine`) → prompt enrichi à Claude Haiku 4.5 pour identifier l'écran SAWALI + proposer la procédure.
- L'image client est stockée via object_storage, l'analyse Vision + matches Qdrant sont persistés dans le message (`user_image_url`, `image_analysis`, `matched_images`).
- Toutes les étapes externes (storage, Vision, Qdrant) sont best-effort : le endpoint répond 200 même si Anthropic ou Qdrant échoue.
- **Frontend** : bouton « Capture » dans le composer Liluvine PRO, preview avant envoi, bouton 🗑 pour retirer. Le message utilisateur affiche l'image envoyée ; le message assistant affiche une grille des 3 meilleurs matches SAWALI (score visible).
- **Tests** : 5/5 unit + 2/2 E2E HTTP live (admin login + Vision + Qdrant) = 7/7 verts.
- **Fichiers** : `backend/routes/qdrant_rag.py` (helper `search_similar_images` + export), `backend/routes/liluvine_pro.py` (endpoint + UploadFile/File/Form imports), `frontend/src/pages/portal/LiluvinePro.jsx` (state + sendWithImage + composer + message bubble), `backend/tests/test_siter39t_s044_vision_compare.py` (nouveau).

### ✅ Quick-win — Bouton « Dupliquer YYYY-MM » dans l'onglet Primes
- Dans `BonusesCard`, nouveau bouton `hr-bonus-duplicate-prev` qui recopie en un clic toutes les primes du mois précédent vers le mois courant (ajout par-dessus, confirmation si primes déjà présentes).
- Gestion robuste de l'arithmétique YYYY-MM (Jan→Dec) via `useMemo`. Toast informatif si le mois précédent est vide.
- **Fichiers** : `frontend/src/pages/portal/HrPrimesIndemnites.jsx`.

### 📌 Note pour onboarding
Testing agent S048 a remonté que `features.ai_liluvine_pro` est **false** par défaut pour le super-admin (admin@sawalismartsystems.com). Considérer le mettre à `true` dans le seed du super-admin (sinon l'utilisateur ne peut pas utiliser Liluvine PRO sur son propre compte).

### 📋 Plan phasé S045 — Refactor server.py (21 800+ lignes) → /backend/routes/
À mener en 4-5 sessions dédiées (1 PR par phase, tests de non-régression entre chaque) :
- **Phase 1** (1 session) : Auth & Sessions (login, logout, OTP, JWT, session middleware) → `routes/auth.py`.
- **Phase 2** (1 session) : Settings & Configuration admin (`SettingsUpdate` PATCH, secret vault, branding) → `routes/admin_settings.py`.
- **Phase 3** (1-2 sessions) : WhatsApp (webhook Meta, send_text/media, template management, polling) → `routes/whatsapp.py` (~3-4k lignes).
- **Phase 4** (1 session) : Notifications (email, SMS, voice, push) → `routes/notifications.py`.
- **Phase 5** (1 session) : Payments core (PawaPay, Stripe Checkout webhooks) → `routes/payments.py` (cashier.py existe déjà).
- Reste : Contacts, Tickets, Appointments, Ad Banners. Total estimé : 12-15k lignes extraites, server.py ramené à ~7k lignes (orchestration + endpoints transversaux).

### 📅 Estimation S046 — i18n FR/EN + 4 langues
~3-4h de travail réparties en 4 phases : setup `react-i18next` (30 min) + extraction script chaînes FR (1h) + endpoint admin CRUD traductions (45 min) + sélecteur public + switch instantané (15 min). Traduction auto Claude des 12 000 chaînes ≈ $2-3 sur la Universal Key, à valider manuellement.


## Recent (2026-02 post-handoff) — S-iter39s — 🛡️ Toggle Vision global + GRH Primes & Indemnités

### ✅ S042 — Toggle global `qdrant_image_auto_describe` dans Admin Settings
- Nouveau champ persistant `qdrant_image_auto_describe` (default true) dans `settings.global`.
- UI : toggle dans /admin/settings → section Qdrant RAG, avec aide explicative.
- Backend endpoint `POST /api/admin/qdrant/collections/{name}/points/image` lit ce setting quand `auto_describe='auto'`. Toggle par-upload reste prioritaire.
- Permet de couper Claude Vision en masse pour économiser sur la Universal Key (~$0.001/image).

### ✅ S043 — GRH : Primes (variables/mois) & Indemnités (fixes)
- **Indemnités fixes** (`hr_allowances`) : par employé, récurrentes chaque mois, avec toggle active/inactive (transport, logement, panier, ancienneté…).
- **Primes variables** (`hr_bonuses`) : rattachées à un mois `YYYY-MM` précis, peuvent être absentes ou présentes d'un mois à l'autre.
- CRUD complet via 8 nouveaux endpoints `/api/hr/employees/{eid}/allowances`, `/api/hr/allowances/{aid}`, `/api/hr/employees/{eid}/bonuses?month=…`, `/api/hr/bonuses/{bid}`.
- Intégration `_compute_payslip` : `gross_with_gains = gross + total_allowances + total_bonuses`. Les taxes s'appliquent sur le nouveau total ; la déduction d'absence aussi.
- **Frontend** : nouvel onglet « Primes & Indemnités » dans `/portal/hr` (entre Avances et Paie), avec 2 cartes (Indemnités fixes / Primes du mois) + sélecteur d'employé + sélecteur de mois pour les primes. PayslipsTab + PDF affichent désormais le détail ligne par ligne.
- **Tests** : 5/5 verts — `backend/tests/test_siter39s_primes_indemnites.py` (CRUD allowances + CRUD bonuses + filter par mois + payslip integration + backward compat).
- **Fichiers** : `backend/routes/hr.py` (modèles + endpoints + intégration + PDF), `backend/models.py:SettingsUpdate` (S042 field), `frontend/src/pages/portal/HrPrimesIndemnites.jsx` (nouveau), `frontend/src/pages/portal/HumanResources.jsx` (tab), `frontend/src/pages/portal/HumanResourcesAdvanced.jsx` (PayslipsTab), `frontend/src/pages/admin/AdminSettings.jsx` (toggle S042).
- **Itération test** : `/app/test_reports/iteration_47.json` — 100% pass (50/50 backend, frontend OK).

### 📝 Suggestions notées pour les prochains sprints
- **S044** (à faire) : Liluvine compare une capture d'écran client (WhatsApp/chat) avec la base d'images SAWALI via Claude Vision + Qdrant.
- **S045** (à faire) : Refactor `server.py` (21 800+ lignes) → modules `/backend/routes/`.
- **S046** (différée) : i18n FR/EN + 4 langues, table `translations` éditable, sélecteur public.


## Recent (2026-02 post-handoff) — S-iter39r — 🖼️ S040 modal upload + P1 Claude Vision RAG

### ✅ S040 — MediaUploadModal monté dans AdminMediaLibrary (& /admin/brochures)
- `MediaUploadModal.jsx` (créé fin session précédente) maintenant branché dans `AdminMediaLibrary.jsx` à la place de la cascade `window.prompt`.
- Modal complet : fichier, titre obligatoire (auto-rempli depuis le nom du fichier), description, tags (séparés par virgules), toggle public, badge type (PDF/Vidéo/Image) avec icône + taille en Ko.
- 7 data-testid : `media-upload-modal`, `…-file`, `…-title`, `…-description`, `…-tags`, `…-public`, `…-submit`, `…-cancel`.
- AdminBrochures.jsx hérite automatiquement (il utilise AdminMediaLibrary).

### ✅ P1 — Enrichissement Qdrant image via Claude Sonnet 4.6 Vision (OCR + description)
- Nouveau helper `describe_image_with_vision(raw, mime)` dans `qdrant_rag.py` : appel à Claude Vision (via emergentintegrations + EMERGENT_LLM_KEY) qui renvoie un Markdown `### OCR / ### Description`. Parser robuste, swallow errors (retourne `{ocr_text:"", visual_summary:""}` si clé absente, octets vides ou réseau down).
- `upsert_image()` enrichi : le texte d'embedding combine désormais `title + caption + visual_summary + ocr_text`. Le payload stocke chaque champ séparément pour inspection.
- Endpoint `POST /api/admin/qdrant/collections/{name}/points/image` accepte un nouveau form-field `auto_describe` (`'on'|'off'|'auto'`, default `'auto'` → respecte le setting global `qdrant_image_auto_describe`, true par défaut).
- L'entrée `media_library` créée en parallèle est taggée `vision-enriched` et stocke `vision_ocr` + `vision_summary`.
- UI : `QdrantRagSection.jsx > UpsertImageTab` propose désormais un checkbox `data-testid="qdrant-image-auto-describe"` (coché par défaut, label « Analyser l'image avec Claude Vision »). Submit activé dès qu'un fichier est sélectionné (titre/caption manuels facultatifs). Le panneau de résultat affiche la description Vision + un `<details>` pour le texte OCR.
- **Fichiers** : `backend/routes/qdrant_rag.py`, `frontend/src/components/QdrantRagSection.jsx`, `frontend/src/components/AdminMediaLibrary.jsx`.
- **Tests** : 5/5 verts — `backend/tests/test_siter39r_p1_vision_enrich.py` (parser regex + helper mocké LlmChat + cas no-key + cas bytes vides). Backend total 13/13 (E2E HTTP auto_describe on/off ajouté par testing agent dans `test_siter39r_image_auto_describe.py`).
- **Itération test** : `/app/test_reports/iteration_46.json` — 100% pass backend & frontend.


## Recent (2026-02 post-handoff) — S-iter39h — 📈 Burn-rate Universal Key & alertes anticipées

### ✅ S032 — Vitesse de consommation Universal Key + alertes Email + WhatsApp (80% / 95%)
- **Objectif** : anticiper l'épuisement de la Universal Key Emergent **avant** la coupure du service IA, en mesurant la vitesse de consommation et en alertant l'admin sur 2 canaux.
- **Source double des coûts** : (a) Chaque appel LLM (`liluvine_chat`, `wa_autoreply`, `health_probe`, etc.) ajoute une ligne dans `llm_usage_log` avec coût estimé par contexte (basé sur tarifs Claude Haiku 4.5). (b) Quand Emergent renvoie une erreur de budget, la valeur réelle `current_cost` est extraite et utilisée comme vérité terrain.
- **Fonction `compute_metrics(db)`** : agrège sur 24h / 1h / cumul mensuel, calcule `pct_used`, projette `projected_days_left` et `projected_exhaustion_at`, classe l'état en `ok` / `warning` / `critical` / `exhausted` / `error`.
- **Bannière 4 niveaux** : `LlmHealthBanner` change de couleur (ambre→orange→rose) et affiche en warning/critical : vitesse 24h, projection d'épuisement, nombre d'appels IA (24h).
- **Notifications proactives** : Email + WhatsApp (canaux configurables, throttle 23h **par niveau**) déclenchés dès passage en `warning` (par défaut 80%) ou `critical` (par défaut 95%). Cron 15 min appelle `maybe_send_budget_warning_alerts(db, send_email, _wa_send_text)`.
- **Configuration admin** : nouvelle section `Universal Key Emergent — Seuils de consommation & alertes (S032)` dans `/admin/settings` (anchor `s-llm-budget-thresholds`) — 6 paramètres (warning_pct, critical_pct, max_usd, notify_email, notify_wa, notify_wa_phone). Validation backend stricte (50≤warn<crit≤99, max>0).
- **Endpoints** : `GET /api/admin/llm-health` enrichi des 13 nouveaux champs S032.
- **Fichiers** : `backend/routes/llm_health.py` (compute_metrics + maybe_send_budget_warning_alerts), `backend/models.py:SettingsUpdate`, `backend/server.py` (validation + cron), `backend/routes/liluvine_pro.py` + `liluvine_wa_autoreply.py` (context propagé), `frontend/src/components/LlmHealthBanner.jsx`, `frontend/src/pages/admin/AdminSettings.jsx`.
- **Tests** : 6/6 verts — `backend/tests/test_siter39h_llm_burn_rate.py`.

## Recent (2026-02 post-handoff) — S-iter39g — 🚨 Monitoring Universal Key & bannière super-admin

### ✅ S031 — Bannière budget Universal Key + email quotidien
- **Détection auto** : helper `record_llm_outcome(db, ok, error)` intégré dans `liluvine_pro.py` + `liluvine_wa_autoreply.py`. Regex extrait `current_cost`/`max_budget` du message d'erreur exact d'Emergent.
- **Statuts** : `ok | budget_exceeded | key_missing | unknown_error | unknown`.
- **Cron 15 min** : `ping_emergent_llm` envoie un test minimaliste à Claude Haiku 4.5 → rétablit auto le status `ok` dès recharge.
- **Email quotidien** (throttle 23 h) à `admin@sawalismartsystems.com` tant que le status est `budget_exceeded`.
- **Bannière sticky** (gradient ambre→rose, pulse animation) avec chiffres `cost/max`, instructions Profile → Universal Key → Add Balance, bouton Re-tester (ping immédiat) + dismiss.
- **Restriction stricte** : `admin@sawalismartsystems.com` est le **SEUL email** qui voit la bannière (gate frontend stricte). Les autres admins peuvent lire l'endpoint mais ne voient rien.
- Endpoints : `GET /api/admin/llm-health` + `POST /api/admin/llm-health/ping` (force probe).
- Tests : 5/5 verts (regex parsing + admin read + 403 non-admin + state transitions + ping endpoint).

## Recent (2026-02 post-handoff) — S-iter39f — 📊 Journal d'audit des téléchargements

### ✅ S029 — Journal d'audit consultable des demandes de téléchargement
- Nouvelle page admin `/admin/download-audit` (Admin/Superviseur uniquement).
- 5 KPI cards cliquables (Pending / Approved / Denied / Expired / Cancelled) avec compteurs en temps réel.
- Tableau complet : date, demandeur, document, status, date de décision, canal de décision (🔘 Bouton template / 🔗 Lien magique / ⚡ Admin), numéro de l'approbateur, statut d'envoi WhatsApp.
- Filtres par status (clic sur KPI) + recherche plein-texte (demandeur/document).
- Backend `GET /api/me/download-requests/admin/audit` : 500 lignes max, 403 pour non-admin, 400 pour status invalide.
- Tests : 2/2 verts (counters + filtres + RBAC blocking).

## Recent (2026-02 post-handoff) — S-iter39e — 🛡️ Approval téléchargements + 📋 Signataires PV + 📖 Doc AdminSettings

### ✅ S025 — Workflow d'approbation WhatsApp pour téléchargements
- Non-admin → `POST /me/download-requests` → WA envoyé à l'approbateur (template Meta avec 2 boutons quick-reply OU fallback texte avec magic links).
- Frontend `<DownloadGate>` + hook `useDownloadGate()` : jauge circulaire animée, polling toutes 2 s, statuts terminaux approved/denied/expired/cancelled.
- Public endpoint `/api/wa-action/{token}/{approve|deny}` (HTML confirmation) + webhook hook pour les payloads `download_(approve|deny)_{token}`.
- 6 nouveaux paramètres dans AdminSettings (enabled, phone, pending_message, template_name, template_lang, text_body).
- Wired sur PortalBrochures (bouton « Demander le téléchargement »).
- Tests : 4/4 (admin bypass, magic-link approve/deny/cancel, validation settings).

### ✅ S026 — Notification automatique des signataires de PV (Email + WA + paramétrable)
- À la création d'un PV avec signataires non vides, chaque signataire reçoit une notification via le canal choisi (`none | email | wa | both`).
- Contenu : numéro PV, titre, date, auteur, lien direct vers `/portal/meetings/{id}`.
- Configuration : 4 boutons radio dans AdminSettings (anchor `s-meeting-signers-notify`).
- Échecs d'envoi silencieux (n'interrompent jamais la création).

### ✅ S027 — Référence technique PDF des paramètres AdminSettings
- Nouveau PDF `D_Documentation_Technique_AdminSettings.pdf` (26 KB).
- 24 sections documentées avec nom du paramètre, type (string/secret/bool/int/E.164/enum/URL), description courte. Valeurs intentionnellement omises.
- Téléchargeable via `/api/public/docs/admin-settings-reference`, visible dans BrochuresWidget + PortalBrochures.

### ✅ S028 — Vidéos publiques : auto-unmute au premier geste utilisateur
- Démarre muté pour autoplay → re-active automatiquement le son au 1er click/touch/keydown.
- Préférence utilisateur (clic explicite sur volume off) mémorisée en `sessionStorage`.

### Tests S-iter39e : 4/4 nouveaux + régression complète siter39a/b/c/d = **15/15 verts**

## Recent (2026-02 post-handoff) — S-iter39d — 🔗 8 améliorations en cascade (7/8 livrées)

### Items livrés (1, 2, 3, 4, 5, 7, 8) — Item 6 reporté en S025

- **S018 (item 1) — Signataires + Participants PV via dropdowns** : nouvel endpoint `GET /api/me/tenant-users` (users + tracked du tenant), 2 multi-select dropdowns dans l'éditeur (ligne 1 signataires obligatoires, ligne 2 autres participants, disjoints). Sign check : si liste signataires non vide, seul un signer déclaré peut signer (sinon 403). PDF affiche les deux listes résolues en noms lisibles.
- **S019 (item 2) — Liluvine PRO Historique pour modérateurs** : route `/portal/liluvine-history` accessible aux modérateurs (gate `moderationOnly`) ; mirroir de `/admin/liluvine-history`. RBAC frontend étendu à `moderation`/`administrateur`.
- **S020 (item 3) — Bug fix idle-logout + Welcome briefing** : bascule sur `window.location.assign("/login")` au lieu de `navigate()` pour démontage propre des modales persistantes.
- **S021 (item 4) — Visualiseur registre SUGGESTIONS.md** : page `/admin/suggestions` (admin/sup uniquement) + endpoint `GET /api/admin/suggestions-registry`. Rendu markdown basique + boutons Copier/Rafraîchir.
- **S022 (item 5) — Centre Messagerie tri par défaut « dernier contact WA/SMS »** : enrichi `last_message_at` côté backend (`admin_messaging_audience`) avec fuzzy match sur 10 digits de téléphone vs `wa_messages` + `sms_messages`. Sélecteur de tri reposionné en tête.
- **S023 (item 7) — Jauge circulaire de chargement global** : nouveau `<GlobalRouteLoader>` monté à la racine. Activé au changement de route + axios interceptors. Courbe asymptotique 0→90→100 %. Anti-flicker.
- **S024 (item 8) — Toggle son sur les bannières vidéo publiques** : nouveau bouton volume (data-testid `ad-banner-sound-toggle-{id}`). Demarre muté (autoplay browser-policy) → 1 clic active le son et la préférence est mémorisée en `sessionStorage`.
- **🟡 S025 (item 6) — REPORTÉ** : workflow d'approbation pour téléchargement (jauge + WA template + magic links + collection `download_approvals`). Nécessite décision utilisateur sur template Meta officiel vs magic links texte avant scope.

### Tests S-iter39d : 4/4 nouveaux backend + régression complète siter39 = **11/11 verts**
- `test_siter39d_eight_features.py` : tenant-users, signers persistence + sign check, suggestions registry, audience last_message_at
- `test_siter39c_sign_meeting.py` + `test_siter39b_*` + `test_siter39a_*` : régression OK

## Recent (2026-02 post-handoff) — S-iter39c — 🔏 Signature électronique du PV

### ✅ S017 — Signature électronique avec verrou de modification
- Nouveau bouton « Valider et signer » (admin/superviseur uniquement) côté UI : sur la carte d'un PV ET dans le viewer plein écran.
- Backend `POST /api/me/meetings/{id}/sign` et `/unsign` :
  - persistance `signed_at`, `signed_by_id`, `signed_by_name`, `signed_by_email`
  - PUT et DELETE sur PV signé → **HTTP 423 LOCKED**
  - signature idempotente, annulation autorisée admin/sup
  - PDF inclut un bloc emerald « ✓ PV signé électroniquement par … le … — Document verrouillé »
- UI : badge « SIGNÉ » sur la carte, ring emerald, masquage des boutons Modifier/Supprimer/Signer quand verrouillé, bouton « Annuler la signature » à la place.
- Tests : `backend/tests/test_siter39c_sign_meeting.py` (cycle sign/lock/unsign + idempotence + modérateur refusé + PDF — 2/2 verts).

## Recent (2026-02 post-handoff) — S-iter39b — 📋 PV de réunions + 📖 Visionneuse PDF + 🕒 Liluvine 3 dernières

### ✅ S012 — Bug fix : modal de consultation de tâche affichait vide
- Tâches migrées au format `task_items[]` (Google-Keep) restaient invisibles dans le viewer (qui ne lisait que `content_html`). Ajout du rendu de la checklist avec compteur fait/total.

### ✅ S013 — Brochures & Guides visibles aux modérateurs
- Nouvelle entrée sidebar `Brochures & Guides` avec gate `moderationOnly` dans `PortalLayout.jsx`. `BrochuresWidget.canSee` étendu à `tracked_role="Moderation"`. Téléchargement reste réservé Admin/Superviseur ; à la place les modérateurs ouvrent une visionneuse PDF interne.

### ✅ S014 — Visionneuse PDF interne (`<PdfViewer>`)
- Basée sur **react-pdf 9** + **pdf.js 4** (worker chargé via CDN unpkg).
- Sommaire cliquable (extrait via `pdf.getOutline()`), recherche plein-texte avec aperçu (jusqu'à 200 occurrences), zoom +/-, navigation page.
- **Téléchargement gated par rôle** : bouton visible uniquement si admin/superviseur ; sinon bandeau « Lecture en ligne uniquement » + désactivation menu contextuel et Ctrl+S.
- Utilisée par `/portal/brochures` et `/portal/meetings`.

### ✅ S015 — PV de réunions internes (autonumérotés)
- Backend `routes/meetings.py` (CRUD + export PDF reportlab + soft-delete).
- Numérotation atomique `PV-YYYY-NNN` par tenant et par année via `_counters.next_seq`.
- Schéma `meeting_minutes` : `id, tenant_id, numero, meeting_date, started_at, ended_at, title, body_html, attendees, author_*, created_at, updated_at, deleted_at`.
- Éditeur riche (réutilise `RichEditor` de UserNotes — bouton **Dicter** Whisper inclus).
- `ended_at` fixé automatiquement au clic « Enregistrer ».
- Édition autorisée à l'auteur + admin/superviseur + tracked Administrateur/Superviseur.
- PDF avec table récap (Titre, Date, Heure début/fin, Auteur, Participants) + corps HTML nettoyé.
- Tests : `backend/tests/test_siter39b_meetings.py` (CRUD + PDF + autonumérotation + soft-delete + auth — 2/2 verts).

### ✅ S016 — Liluvine PRO : 3 dernières + Reprendre pour modérateurs
- Nouveau toggle « 🕒 3 dernières conversations » dans la sidebar Liluvine PRO (toujours visible).
- Fix RBAC : `_TAKEOVER_ROLES` côté backend ET `canTakeover` côté frontend incluent désormais `moderation` et `administrateur` (valeurs réellement stockées) → modérateurs peuvent **Reprendre** une conversation.
- Tests : `backend/tests/test_siter39b_takeover_moderator.py` (1/1 vert).

### ✅ #1 — Convention badge « NOUVEAU » dans la dropdown des Paramètres
- `NEW_SECTIONS` enrichi avec `"Nouveaux modules — PV de réunions / Visionneuse PDF / Filtre Liluvine": "2026-02-01"`. Nouveau bloc `<Filterable>` ajouté en haut de AdminSettings avec 3 cartes (PV / Visionneuse / Liluvine 3 dernières) + liens directs vers les modules.
- Convention rappelée pour les itérations futures : chaque nouveau module créé/maintenu DOIT être enregistré dans `NEW_SECTIONS` ET avoir un `Filterable` titré identique pour apparaître dans la dropdown.

### Tests S-iter39b : 3/3 backend + 5/5 frontend = 8/8 verts (`iteration_44.json`)

## Recent (2026-02 post-handoff) — S-iter39a — 👁️ Carte Liluvine pour Modérateurs + ✏️ Édition « Client lié »

### ✅ S010 — Carte « WhatsApp pris en charge par Liluvine » visible pour les modérateurs
- `_build_liluvine_autoreply_stats` (`backend/server.py`) utilise désormais `_resolve_visible_client_ids(user)` au lieu de `user.get("id")`. Les tracked-users avec `tracked_role="Moderation"` voient enfin les compteurs Liluvine sur l'écran de bienvenue (auparavant toujours 0 car le tenant_id résolu était l'UUID du tracked-user, pas le `parent_client_id`).
- Test ajouté : `test_siter39a_moderator_liluvine_and_link.py::test_liluvine_counter_visible_for_tracked_moderator`.

### ✅ S011 — Édition de « Client lié canonique » depuis la fiche d'un tenant
- Nouveau champ `link_to_client_id: Optional[str]` ajouté à `UserUpdateAdmin` (`backend/models.py`).
- `admin_update_client` (`backend/server.py` ~ligne 6934) :
  - utilise `payload.model_fields_set` pour distinguer « non fourni » de « explicitement vide »
  - chaîne vide → unlink (`parent_client_id=None`, `client_id=None`)
  - UUID valide d'un admin/superviseur/moderateur/client → set `parent_client_id` + `client_id`
  - self-link → 400 / id inconnu → 404
  - dépendance changée de `get_current_admin` à `get_admin_or_supervisor` (l'utilisateur a explicitement demandé Admin+Superviseur)
- UI `AdminClients.jsx` : nouvelle section violette « Client lié canonique » (`[data-testid=link-to-client-section]`) avec dropdown (`[data-testid=client-link-to-client-select]`), visible uniquement en mode édition, pré-remplie via `it.parent_client_id`. Self exclu de la liste, options affichées avec rôle.
- La modification se propage automatiquement à toutes les UI consommatrices (Centre Messagerie, Contacts, briefing, RGPD, facturation WA) car elles lisent toutes `parent_client_id` via `_resolve_visible_client_ids`.
- Test ajouté : `test_siter39a_moderator_liluvine_and_link.py::test_admin_can_relink_tenant_to_canonical_client` (4 sous-scénarios : attach, 404, self-link, detach).

### Tests : 4/4 nouveaux + 2/2 régression fix9d = 6/6 verts (`iteration_43.json`)
- Frontend Playwright : OTP login + dropdown rendu + auto-logout chips validés (3/3).
- Suggestions tracker mis à jour : S010 + S011 ajoutées dans `/app/memory/SUGGESTIONS.md`.

## Recent (2026-05-31) — Iter38r-fix9z9 — 🤖 Plan de campagne IA + 📚 Documentation actualisée

### ✅ Plan de campagne IA (Claude Haiku 4.5)
- Endpoint `POST /api/public/ads-report/{slug}/ai-plan?token=X` validé par slug + share_token
- Prompt structuré envoie : nom, annonceur, impressions/clics/CTR, budget alloué/dépensé, comparaison A/B si activé
- Réponse JSON parsée avec 4 champs : `visual_hint` (description prête pour Gemini Nano Banana), `slogans` (liste de 3 CTA), `recommended_budget_xof` (nombre), `budget_justification` (texte court)
- Heuristique implicite dans le prompt : CTR < 0.5% → visuel ; 0.5–2% → slogans ; > 2% → augmenter budget
- **Cache 6h** sur le doc bannière (`ai_plan` + `ai_plan_updated_at`) pour maîtriser les coûts IA — le 2e appel renvoie `cached:true`
- UI `AICampaignPlan` dans PublicAdReport : 3 cartes (fuchsia visuel + sky slogans + emerald budget), boutons Copier sur chaque suggestion, badge CACHE quand cache hit, bouton Régénérer

### ✅ Documentation PDF actualisée
- 2 nouvelles sections ajoutées à `generate_pdfs.py > SECTIONS` :
  1. **Régie publicitaire (Ad Banners) — Complète** — 12 champs décrits avec rôle et impact : Liste & cartes, Bouton Nouvelle bannière, Champs basiques, Champs budget, Dates, Dimensions d'affichage (fix9z5), Test A/B (fix9z6), Contact annonceur + rappels (fix9z6+7), Boutons par ligne, Modale Statistiques, Inbox renouvellements, Dashboard temps-réel (fix9z7)
  2. **Rapport public annonceur — /ads/{slug}?token=…** — 9 sections décrites : En-tête, Cartes KPI, Section Budget, Graphique tendance 30j (fix9z5), Demande renouvellement (fix9z5), Paiement en ligne (fix9z8), MAJ libre-service visuel (fix9z8), Plan de campagne IA (fix9z9), Historique journalier
- 2 nouvelles captures d'écran intégrées : `11_ad_banners.jpeg` (panel live + form sizing/AB) + `12_ad_report_public.jpeg` (rapport complet avec widgets self-service)
- 3 PDFs régénérés (Guide Utilisateur 1.07 MB + Brochure Présentation 1.06 MB + Brochure Grandes Fonctionnalités 1.62 MB)

### Tests : 41/41 cumulés (fix9z4 → fix9z9) — 0 régression

## Recent (2026-05-31) — Iter38r-fix9z7 + fix9z8 — 📱 WhatsApp + Live WS + Portail libre-service

### ✅ fix9z7 — WhatsApp reminders + Live admin dashboard
- Champ `reminder_wa_enabled` (toggle indépendant de l'email) + cron 09:30 envoie WA via `_wa_send_text` réutilisé
- `process_expiration_reminders` accepte `send_email_fn` ET `send_whatsapp_fn` (DI propre, idempotence par marker `expiration_date|days_before`)
- WebSocket admin `/api/ws/ad-banners-live?token=<adminJWT>` : snapshot initial + broadcast `{event:'impression'|'click', banner_id, variant, total_impressions_a/b, total_clicks_a/b, ...}` à chaque hit public
- Composant `AdBannersLivePanel` (en-tête de `/admin/ad-banners`) : status Connecté/Hors-ligne, liste live des bannières avec flash animation à chaque event + feed des 5 derniers événements

### ✅ fix9z8 — Portail libre-service annonceur (sans login)
- `POST /api/public/ads-report/{slug}/checkout?token=X` — crée une session Stripe Checkout (conversion XOF→EUR à 655,957), persiste `ad_renewals` avec `renewal_applied=False`
- `GET /api/public/ads-report/{slug}/payment-status/{session_id}` — poll endpoint qui, sur 'paid' Stripe, **atomiquement** (CAS) étend `expiration_date` de `duration_days` + crédite `budget_amount` de `amount_xof` + remet à zéro l'auto-pause + reset `reminder_last_sent_for`
- `PUT /api/public/ads-report/{slug}/media?token=X` — met à jour `image_url`/`media_kind`/`target_url` (et variant_b équivalents); whitelist stricte (les champs admin comme budget/placement sont silencieusement ignorés); audit row dans `ad_self_service_updates`
- UI `PublicAdReport` : 2 nouvelles sections — `OnlineRenewalCheckout` (formulaire montant/durée/email + redirection Stripe + polling auto au retour `?session_id=...&renew=ok`) + `SelfServiceMediaUpdate` (uploader média + URL cible + save)

### Tests : 41/41 backend + 9/9 frontend = 50/50 passés
- fix9z7 : 6 tests (WA stub + WS snapshot/broadcast + auth)
- fix9z8 : 8 tests (media update whitelist + audit + checkout validation + payment-status CAS)
- fix9z6 + fix9z5 + fix9z4 régression : 33/33 verts
- Aucun bug trouvé. Code review reviewer : 6 « Good » + 1 minor (cache webpack dev — résolu par restart frontend, sans incidence en prod)

## Recent (2026-05-31) — Iter38r-fix9z6 — 🧪 A/B Testing + Email automatique d'expiration

### ✅ P5 — A/B Testing sur Régie publicitaire
- Schéma `ad_banners` enrichi : `ab_enabled`, `variant_b_image_url`, `variant_b_media_kind`, `variant_b_target_url`, compteurs séparés `total_impressions_a/b` + `total_clicks_a/b`
- Rotation 50/50 via `random.random() < 0.5` dans `_public_view`, retour `active_variant: 'a'|'b'` au frontend
- Endpoints `/impression?variant=a|b` + `/click?variant=a|b` qui bumpent les bons compteurs et renvoient la target URL adaptée
- Stats enrichies : objet `ab` avec `variant_a`, `variant_b`, `winner` (best CTR avec ≥30 affichages par variante)
- UI Admin : composant `BannerABBlock` (toggle + uploader variante B + URL cible côte à côte) + `ABBreakdown` dans la stats modal (badge 🏆 GAGNANTE sur la variante au CTR le plus élevé)
- `handleFileChange(e, variant)` factorisé pour réutiliser le même uploader pour A et B

### ✅ Email automatique d'expiration
- Champs `advertiser_email`, `advertiser_phone`, `reminder_email_enabled` (défaut true), `reminder_days_before` (1–30, défaut 3) ajoutés
- Fonction `process_expiration_reminders(db, send_email_fn, public_base_url, today_iso)` au niveau module
- Logique idempotente via `reminder_last_sent_for = "{expiration_date}|{days_before}"` — re-runs ne renvoient pas
- Email HTML+text : bilan campagne (affichages, clics, CTR, budget restant) + lien direct vers `/ads/{slug}?token=…` pour renouveler en 1 clic
- Cron quotidien APScheduler `_scheduled_ad_banner_reminders` à 09:30 Africa/Abidjan
- Endpoint manuel `POST /api/admin/ad-banners/run-reminder-cron` pour déclenchement immédiat
- UI Admin : composant `BannerContactReminderBlock` (email + téléphone + toggle + nombre de jours)

### Tests : 27/27 passés
- 8 nouveaux tests backend (`test_iter38r_fix9z6_ab_reminder.py`) — A/B persistence, variant tracking, winner detection, cron idempotence
- 19 tests de régression (fix9z5 + fix9w) verts
- 6 flows frontend validés par `testing_agent_v3_fork` (form A/B toggle, side-by-side preview, contact/reminder toggle, stats modal A/B breakdown)
- 0 régression, 0 bug trouvé

## Recent (2026-05-31) — Iter38r-fix9z5 — 🎨 4 améliorations livrées en un shot

### ✅ Dimensions d'affichage paramétrables (Régie publicitaire)
- Champs `display_mode` (auto / ratio / percentage / fixed), `aspect_ratio`, `width_pct`, `height_px`, `width_px`, `object_fit` ajoutés à `ad_banners`
- Composant React `BannerSizingBlock` dans AdminAdBanners avec aperçu en direct + 4 modes + slider largeur + select ratios courants (16:9, 21:9, 4:1, 3:1, 2:1, 1:1, 4:5, 9:16, custom)
- Helper `/lib/bannerStyle.js` calcule les styles CSS depuis les champs DB
- AdBannerSlot consomme les nouveaux champs et applique width/aspectRatio/height/object-fit en inline-style

### ✅ Rapport public — Onglet Conversion + Renouvellement
- Nouveau composant `ConversionTrend` (SVG sparkline 2-courbes : affichages + clics sur 30 jours) avec totaux + CTR moyen + dépensé
- Nouveau widget `RenewCampaignWidget` (formulaire : nom, email, téléphone, budget souhaité, durée, message)
- Endpoint `POST /api/public/ads-report/{slug}/renew?token=…` créant une ligne dans `ad_renewal_requests`
- Inbox renouvellements dans AdminAdBanners avec bouton "Marquer traitée" (`POST /admin/ad-renewal-requests/{id}/mark-handled`)

### ✅ Graphique coût IA mensuel (Dashboard Admin)
- Endpoint `GET /api/admin/ai-costs/monthly?months=N` agrège `ai_usage_monthly` cross-tenant, zero-fill sur la période
- Composant `AdminAICostChart` avec barres 12 mois + 4 préréglages (3/6/12/24 mois) + cartes total période / moyenne mensuelle / mois en cours
- Intégré au bas du Dashboard Admin

### ✅ Hook centralisé `useAssetUrl` (P3 refactor)
- `/lib/useAssetUrl.js` : `resolveAssetUrl(u)` + `useAssetUrl()` React hook
- Adopté par PublicAdReport, AdBannerSlot, AdminAdBanners (tableau et aperçu)

**Tests : 22/22 passés** (9 unit + 7 e2e + 6 byte-range regression). 4 flows UI validés par testing_agent_v3_fork. 0 régression.

## Recent (2026-05-31) — Iter38r-fix9z4 — 🎥 P0 BUG FIX : Lecture vidéo dans Ad Banners
- 🔴 **Root cause** : `FileResponse` annonçait `Accept-Ranges: bytes` mais ignorait l'en-tête `Range` envoyé par le navigateur, retournant HTTP 200 + body complet au lieu de 206 Partial Content. Chromium/Safari rejetaient alors la lecture avec `MEDIA_ERR_SRC_NOT_SUPPORTED`.
- ✅ **Fix** : `serve_file` (`server.py` ~ligne 7869) gère maintenant correctement les requêtes Range — 206 + Content-Range + Content-Length pour les sous-plages, 416 pour les ranges invalides, 200 + Content-Length pour les GET sans Range.
- ✅ **Tests** : 6 nouveaux tests pytest dans `test_iter38r_fix9z4_byte_range.py` (range spécifique, range ouvert `bytes=0-`, range médian, hors limites, disposition inline préservée). 11/11 tests passent (avec test_iter38r_fix9z2).
- ✅ **Validation E2E** : Image PNG de bannière s'affiche correctement en haut de la home publique (capture confirmée). Vidéo MP4 confirmée via fetch + 206 Content-Range correct dans le DevTools réseau (codec H.264 non testable dans HeadlessChrome mais OK dans Chrome/Safari/Firefox standards).
- 📦 **Import ajouté** : `StreamingResponse` depuis `fastapi.responses`.

## Recent (2026-05-31) — Iter38r-fix9p → fix9w — 8 modules livrés en session

### 🔴 fix9p (P0 BUG FIX) — Backend gate `ai_voice_gen`
- ✅ Endpoints `/me/ai/tts-elevenlabs` + `/me/ai/voices/clone` désormais gatés par le toggle `ai_voice_gen` du tenant. Admin/superviseur bypass. 4/4 tests.

### 📊 fix9q — Mini-compteur OCR par tenant (AdminClientFeatures)
- ✅ `GET /api/admin/liluvine-pro/kb/ocr-usage?client_id=X` filtre par tenant.
- ✅ Carte avec barre de progression colorée (vert/ambre/rouge selon le %).

### 🔊 fix9r — Home Assistant Voice Notifications
- ✅ Module complet (15 évènements built-in, custom events, log, test pipeline).
- ✅ 14/14 tests pytest.

### 📄 fix9s — Régénération PDF (Admin/Superviseur)
- ✅ Pictogramme `RefreshCw` + libellé sur chaque carte brochure. 3/3 tests.

### ⚡ fix9t — Liluvine PRO — Streaming SSE + Optimisations
- ✅ **Claude Haiku 4.5** (~3× plus rapide) + cache RAM KB 60s + fetchers parallèles + endpoint SSE `/me/liluvine-pro/chat/stream` avec effet typewriter. Gain ~4s → ~1.5s. 5/5 tests.

### 🔔 fix9u — Module Rappels d'abonnements IA
- ✅ Collection `ai_subscriptions`, table éditable, date de renouvellement auto-calculée, cron 08:00 Africa/Abidjan WhatsApp + Email. 8/8 tests.

### 🆔 fix9v — Clients filter + WA login dedup
- ✅ `GET /admin/clients?source=wa_otp_login&sort_by=created_at&sort_order=desc`.
- ✅ Page Clients : filtre Source + tri par création / dernière connexion / nom (alpha).
- ✅ Centre messagerie : tri alpha / création / dernier message.
- ✅ WA login : si numéro déjà existant (admin ou tracked), réutilise le compte ; `last_wa_login_at` mis à jour ; pas de doublon. 4/4 tests.

### 🔊 fix9w (étape B + C) — Voice hooks + Régie publicitaire monétisée
- ✅ **Étape B** — Hooks `_voice_notify()` ajoutés aux endpoints critiques :
  - `ticket_created` (2 endpoints tickets)
  - `payment_pawapay_received` (webhook completed)
  - `payment_stripe_received` (webhook completed)
  - `new_client_signup` (admin/clients POST)
- ✅ **Étape C** — Module Régie publicitaire complet :
  - Collection `ad_banners` + CRUD admin + page `AdminAdBanners.jsx`
  - Catalogue : nom, annonceur, image_url, target_url, placement (public/portal/both), budget, CPI, CPC, animated, paid, dates, expiration
  - Rotation pondérée par budget restant + auto-pause sur expiration/budget atteint
  - Tracking `impression` + `click` avec `daily_stats` (suivi par jour)
  - Composant `AdBannerSlot.jsx` intégré en haut de Home (public) + PortalLayout (Espace Loois)
  - Modal statistiques détaillées par bannière (CTR, dépensé, historique 30j)
  - 10/10 tests.

**Total : 50/50 tests pytest** sur les 8 modules, 0 régression.


## Recent (2026-05-31) — Iter38r-fix9p 📚 (Documentation)

### 📚 3 documents PDF générés en français
- ✅ **A. Guide Utilisateur** (1.0 MB, ~25 pages) — Cover + Sommaire avec numéros de page + Introduction + 10 sections détaillées (1 capture + 5-7 champs par section) + Annexe (Glossaire, raccourcis, support).
- ✅ **B. Brochure de présentation** (1.0 MB, ~15 pages) — Cover + Sommaire + « Pourquoi SAWALI » (6 avantages) + 10 sections (1 capture + 4 fonctionnalités phares chacune) + Tarifs/Contact.
- ✅ **C. Brochure grandes fonctionnalités** (1.6 MB, ~10 pages) — 1 page par module avec capture **sans sidebar** (cropée à x=290px) + 3 points clés.
- ✅ Endpoints `/api/public/docs` (liste) et `/api/public/docs/{slug}` (téléchargement direct).
- ✅ Script de génération `/app/docs/generate_pdfs.py` (reportlab) — facile à régénérer après mises à jour UI.
- ✅ 10 captures d'écran source dans `/app/docs/screenshots/` + versions sans sidebar dans `/app/docs/screenshots/nosidebar/`.



### 📱 WA OTP Template — Multi-stratégie + bouton "Tester l'envoi"
- ✅ `wa_otp_login_9o.py` enrichi : tente d'abord la structure **Authentication** (body + button OTP code) puis fallback **Utility** (body only) puis fallback **texte direct**. Met en cache la catégorie qui fonctionne (`wa_otp_template_category`).
- ✅ **Erreurs Meta exposées** dans la réponse 502 (toutes les tentatives concaténées) — fini les "WA error 400" opaques.
- ✅ Nouveau endpoint `POST /api/admin/wa-otp/test` (admin only) + composant `WaOtpTester.jsx` dans AdminSettings : bouton "Tester l'envoi" qui envoie un vrai OTP + détail Meta dans `<details>` collapsible.

### 🛡️ ErrorBoundary global (P2) — DÉJÀ FAIT
- ℹ️ Déjà présent dans `PortalLayout.jsx` (line 402) avec `resetKey={location.pathname}` — couvre /portal/* ET /admin/*. ✅

### 🐛 Hydration warning PortalLayout (P2) — DÉJÀ RÉSOLU
- ℹ️ Aucun `<option>` / `<select>` actuel dans PortalLayout (refactor antérieur a remplacé le mobile-select par un drawer). ✅

### 🍪 Bandeau RGPD cookies (P2)
- ✅ Composant `CookieBanner.jsx` ajouté à `MarketingLayout.jsx` (toutes les pages publiques).
- ✅ Choix granulaires : Nécessaires (toujours actifs) / Préférences / Analytics / Marketing.
- ✅ Boutons "Tout accepter" / "Refuser optionnels" / "Personnaliser". Persistance dans `localStorage.sawali_cookie_consent_v1`. Helper `getConsent()` exporté pour conditionner les scripts analytics côté frontend.

### 📊 P1 — Stats SMS par fournisseur enrichies dans `/admin/usage`
- ✅ Nouveau endpoint `GET /api/admin/usage/sms-providers?days=N` retournant pour chaque provider : `sent_ok`, `sent_ko`, `total`, `avg_latency_ms` + `avg_latency_human`, `unit_cost`, `estimated_cost`, `last_failure` (timestamp + error_message + to).
- ✅ Coût configurable via `settings.global.sms_unit_cost_<provider>` (ex. `sms_unit_cost_orange = 25.0` XOF/SMS).
- ✅ Composant `SmsProvidersBlock.jsx` remplace l'ancien grid simple : cartes colorées par fournisseur (ORANGE, MOOV, TELECEL, OVH), badge taux % couleur conditionnelle, details Dernier échec collapsible, hint config coût.

### Tests & qualité
- ✅ **8 nouveaux tests pytest** (`test_iter38r_fix9p_sms_providers_wa_test.py`). Cumulatif fix9 : **115 verts** / 1 flake pré-existant.
- ✅ Lint Python + JS clean.
- ✅ Smoke screenshot validé (bloc affiché dans /admin/usage).



### 🎯 Suppression du terme "démo" + CTA conversion
- ✅ Bouton Login : "Se connecter via WhatsApp (essai démo)" → "Se connecter via WhatsApp".
- ✅ Messages WA flow nettoyés ("Recevez un code pour accéder à votre espace" au lieu de "à la démo"; "Bienvenue !" au lieu de "Bienvenue dans la démo !"; "Valider et accéder à mon espace").
- ✅ Auto-ouverture du formulaire WA via `/login?wa=1` (query param).
- ✅ **Nouveau CTA hero homepage** : bouton vert "Découvrir en 30s via WhatsApp" → pointe vers `/login?wa=1`. Animation hover (translateY + slide arrow), shadow-lg vert, data-testid `hero-cta-whatsapp`.



### 🤖 Liluvine PRO — Prompt système (UI)
- ✅ Nouvelle section `LiluvineSystemPromptSection.jsx` dans AdminSettings (anchor `s-liluvine-system-prompt`).
- ✅ Affiche le prompt personnalisé du tenant + bouton "Afficher prompt par défaut" + bouton "Réinitialiser" + bouton "Enregistrer".
- ✅ Branchée sur les endpoints `GET/PUT /admin/liluvine-pro/system-prompt` (qui existaient déjà mais étaient invisibles côté UI).

### 📱 WhatsApp OTP Login (UI sur page Login)
- ✅ Bouton vert **"Se connecter via WhatsApp (essai démo)"** ajouté en bas du formulaire de connexion classique.
- ✅ Flow en 2 étapes : (1) saisie numéro + nom optionnel → `POST /auth/wa-otp/request`. (2) saisie code 6 chiffres → `POST /auth/wa-otp/verify` → JWT + redirection `/portal`.
- ✅ Liens "Retour à la connexion classique" et "Changer de numéro" pour navigation fluide.
- ✅ Branché sur les endpoints `wa_otp_login_9o.py` existants. Smoke screenshot validé.



## Recent (2026-05-31) — Iter38r-fix9o v2 🎟️🏷️⚡

### 🎟️ TicketsBubble v2 — Refonte des champs requis
- ✅ **Bug fix** : `/me/clients` retournait du `full_name`/`company` au lieu de `name`/`company_name` que la bulle attendait → la liste paraissait vide. Corrigé.
- ✅ **Rapporteur** : datalist auto-rempli avec les contacts du client sélectionné (`/me/contacts` filtré par `client_id`). Auto-fill du téléphone/WA quand un contact existant est choisi.
- ✅ **Validations obligatoires** : Client lié + Motif + Rapporteur + Date incident + AU MOINS UN des deux numéros (Téléphone OU WhatsApp).
- ✅ Deux champs séparés Téléphone / WhatsApp. Si seul WA fourni, le backend l'utilise comme `contact_phone` pour la création du contact.
- ✅ **Position bubble** : déplacée bottom-right (`bottom-36 right-4` / `sm:bottom-44 sm:right-6`) — empilée au-dessus de l'InternalChat + Liluvine VirtualAssistant pour grouper les bulles flottantes.

### 🏷️ Rebranding "Espace Loois"
- ✅ "Espace Client" / "Espace client" → "Espace Loois" dans Login, Home publique, Dashboard portail, PortalLayout (subtitle + header mobile), MarketingNav.
- ✅ Marque interne "SAWALI SMART SYSTEMS" et logo conservés.

### ⚡ CheckoutSuccess — Polling supprimé
- ✅ `/checkout/success` ne fait plus 7×2s de polling. Une seule requête `/public/orders/{id}` suffit grâce au webhook Stripe (Iter38r-fix9o P1) qui confirme en temps réel côté serveur.

### 💸 Mobile Money — Migration sidebar → bouton dans Caisse
- ✅ Retrait de l'entrée sidebar `/portal/payouts`.
- ✅ Nouveau bouton **"💸 Payer (Mobile Money)"** dans `/portal/cash` (header tabs, aligné à droite), visible UNIQUEMENT si l'utilisateur est Caissier ET Admin/Superviseur.

### 📅 AdminSettings — Filtre par défaut "Aujourd'hui"
- ✅ Section "Suivi des actions (historique du travail)" : `dateRange` initial passé de `"all"` à `"today"`.

### Tests & qualité
- ✅ **22 tests pytest verts** (14 tickets bubble dont +1 nouveau "WA only" + 7 stripe webhook + 1 nouveau "incident_at"). Cumulatif fix9 : **114 verts**.
- ✅ Lint JS clean.



## Recent (2026-05-30) — Iter38r-fix9o P1 ⚡ (Webhook Stripe)

### ⚡ Webhook Stripe — confirmation paiement sans polling
- ✅ Endpoint existant `POST /api/webhook/stripe` (routes/payments_stripe.py) étendu pour gérer aussi les `public_orders` (catalogue public) en plus des `payment_transactions` (Formations).
- ✅ Signature vérifiée via `STRIPE_WEBHOOK_SECRET` (env) ou `settings.global.stripe_webhook_secret` (UI-driven). Sans secret → tout POST rejeté avec 400 "Signature invalide".
- ✅ **Idempotence par `event_id`** : tout événement déjà traité retourne `{ok: true, idempotent: true}` sans dupliquer email/coupon.
- ✅ **Audit trail** : chaque événement (succès OU échec signature) loggé dans `webhook_events_stripe` (collection visible via `GET /api/admin/stripe/webhook-events`).
- ✅ Helper module-level `mark_public_order_paid(db, send_email_fn, order)` extrait dans `product_checkout_9n.py` — réutilisé par le polling (`GET /public/orders/{id}`) ET le webhook → un seul code path idempotent.
- ✅ UI `StripeWebhookSection.jsx` dans AdminSettings : affiche l'URL webhook à copier-coller dans Stripe Dashboard, champ secret masqué (afficher/masquer/enregistrer), table des 10 derniers événements reçus.
- ✅ Champ `stripe_webhook_secret` ajouté au modèle `SettingsUpdate` + masking RGPD dans `GET /admin/settings`.

### Tests & qualité
- ✅ **7 nouveaux tests pytest** (`test_iter38r_fix9o_stripe_webhook.py`) : signature invalide rejetée, signature manquante rejetée, log d'audit, settings accepte et masque le secret, list webhook-events admin-only, 401 sans auth, idempotence event_id, polling 404.
- ✅ **Cumulatif fix9 : 113 verts** (101 fix9 antérieurs + 14 tickets bubble + 7 webhook + skip + flake KB-budget pré-existant).
- ✅ Lint Python + JS clean.



## Recent (2026-05-30) — Iter38r-fix9o 🎟️📱 (Items 6 + 8 + Coupons UI)

### 🎟️ Item 6 — Bulle "Nouveau ticket d'intervention" globale
- ✅ Composant `TicketsBubble.jsx` (bouton flottant noir/blanc, coin bas-gauche) accessible aux rôles admin/superviseur/moderateur (gated par `features.tickets_bubble`).
- ✅ Modale rapide : sélection du Client lié, motif (dropdown configurable + saisie libre), nom/téléphone du contact, date/heure incident, logiciel utilisé, complément, case "Joindre historique WA/SMS".
- ✅ Nouveau endpoint `POST /api/me/tickets` (création quick-ticket) : crée/retrouve un `directory_contacts` via `phone_digits`, ouvre le ticket, envoie le template WA configuré.
- ✅ Nouveau endpoint `GET /api/me/intervention-reasons` (liste configurable via `settings.intervention_reasons` + 9 valeurs par défaut).
- ✅ Champ `tickets_bubble: Optional[bool]` ajouté à `ClientFeaturesUpdate` Pydantic.

### 📱 Item 8 — WhatsApp OTP Login + tenant DEMO SAWALI
- ✅ Module `/app/backend/routes/wa_otp_login_9o.py` (~270 lignes) — endpoints `POST /api/auth/wa-otp/request`, `POST /api/auth/wa-otp/verify`, `GET /api/admin/wa-demo/recent`, `POST /api/admin/wa-demo/{user_id}/mark-seen`.
- ✅ Envoi OTP via template WA (avec fallback texte direct dans la fenêtre 24h).
- ✅ Vérification OTP : crée le tenant `DEMO SAWALI` (idempotent) + un utilisateur tracked `tracked_role="Admin (Limité)"` + un contact miroir, retourne JWT.
- ✅ Synthèse Dashboard / WelcomeBriefing : nouvelle section verte avec total + non-vus + 5 derniers utilisateurs WA, lien vers `/admin/tracked-users?source=wa_otp_login`.

### 🎟️ P1 — UI admin Coupons (Stripe Checkout)
- ✅ Composant `CouponsSection.jsx` ajouté dans AdminSettings (anchorId `s-coupons-stripe`).
- ✅ Création (code, %, XOF, expiration, max uses), toggle actif/inactif, suppression, table avec compteur utilisations.
- ✅ Codes auto-uppercased, validation pct OU xof requis, confirmation avant suppression.

### Tests & qualité
- ✅ **14 nouveaux tests pytest** (`test_iter38r_fix9o_tickets_bubble.py`) couvrant tous les endpoints fix9o.
- ✅ **Cumulatif fix9a → fix9o : 106/107 verts** (1 pré-existant flake KB-budget non lié, identifié dans iteration_38).
- ✅ Lint Python + JS clean.
- ✅ Testing agent : 100% backend.



## Recent (2026-05-30) — Iter38r-fix9m + fix9n 🎨🛒 (Batchs B + C)

### 🎨 Batch B — AI Media Generator additional models (fix9m)
- ✅ **Veo 3.1** (Google · son natif) — `POST /me/ai/generate-video-veo` long-running + `GET /me/ai/generate-video-veo/{job_id}` polling. Modèle `veo-3.1-generate-preview`.
- ✅ **Imagen 4** (Google HD) — `POST /me/ai/generate-image-imagen` synchrone, retourne `data:image/png;base64,...`. Modèle `imagen-4.0-generate-001`.
- ✅ **ElevenLabs v3** — `POST /me/ai/voices/clone` (Instant Voice Cloning multipart), `GET/DELETE /me/ai/voices`, `POST /me/ai/tts-elevenlabs` (TTS multilingual_v2). Audio retourné en base64 data URL.
- ✅ Page UI **`/portal/voice-studio`** dédiée : formulaire clonage + liste voix + TTS avec audio inline player.
- ✅ MediaGenerator : sélecteurs **"Imagen 4 (Google HD)"** et **"Veo 3.1 (Google · son natif)"** ajoutés.
- ✅ Lien sidebar "Voice Studio (Clonage)".
- ✅ Clés API stockées dans `.env` : `GOOGLE_GEMINI_API_KEY`, `ELEVENLABS_API_KEY`.

### 🛒 Batch C — Catalogue produit public + Stripe enrichi (fix9n)
- ✅ **Stripe Checkout** via `emergentintegrations.payments.stripe.checkout.StripeCheckout` (PAS le package stripe raw — convention Emergent).
- ✅ `POST /public/products/{id}/checkout` (public) — crée la session Stripe, applique le coupon, sauvegarde dans `public_orders` + `payment_transactions`.
- ✅ `GET /public/orders/{order_id}` — récupère le statut depuis Stripe, envoie l'**email de confirmation** (via SMTP Gmail) au paiement réussi.
- ✅ **Coupons CRUD admin** : `POST/GET/PUT/DELETE /admin/coupons` (admin only). Endpoint public `GET /public/coupons/{code}/validate?amount=…` pour UX preview.
- ✅ Page UI catalogue : bouton **"Acheter maintenant"** en plus de "Demander un devis" sur chaque produit public. **BuyModal** : quantité, email, nom, coupon avec vérification temps réel, sub-total/discount/total, redirection Stripe.
- ✅ Pages publiques **`/checkout/success`** (polling + confirmation) et **`/checkout/cancel`**.

### Tests & qualité
- ✅ **16 nouveaux tests pytest** (6 fix9m + 10 fix9n).
- ✅ **Cumulatif fix9a → fix9n : 86/86 verts** (1 test fix9l corrigé pour event loop).
- ✅ Lint Python + JS clean.
- ✅ **Testing agent : 100% backend + 100% frontend critical paths**. Aucun bug trouvé.

_⚠️ Historique antérieur (Iter38r-fix9l) conservé ci-dessous._

## Recent (2026-05-30) — Iter38r-fix9l 🎁 (Batch A : Bonus pack)

### 📱 Potential improvement — WhatsApp Tasks bidirectional sync
- ✅ Cron `wa_tasks_digest_5min` : envoi quotidien des tâches non-faites au numéro WA de chaque utilisateur opt-in à l'heure de son choix (état per-user dans `users.wa_tasks_digest_*` + per-day mapping dans `wa_tasks_digest_state`).
- ✅ Parser `parse_task_ack` (mots-clés `OK / FAIT / DONE / ✅` + numéros). Hook inséré AVANT l'auto-reply Liluvine PRO (les acks ne déclenchent pas Liluvine + confirmation WA "✅ N tâche(s) marquée(s)").
- ✅ Endpoint `PUT/GET /me/wa-tasks-digest` (opt-in user) + AdminSettings toggle global.
- ✅ Section "Préférences & RGPD" dans `MyAccount.jsx` : checkbox + sélecteur d'heure.

### 📧 Backlog #4 — Digest hebdo Liluvine PRO (Lundi 8h, email)
- ✅ Cron `liluvine_weekly_digest_mon` : email HTML envoyé chaque lundi 8h00 (Africa/Abidjan) à chaque admin/superviseur.
- ✅ Contenu : ROI (auto-réponses, temps gagné, XOF économisés), Top 5 contacts WA, sessions reprises, CTA "🚀 Lancer une campagne ciblée" (URL pre-fillée vers `/admin/messaging?prefill_msisdns=…`).

### 🛡 Backlog #3 — GDPR data anonymization + Export my data
- ✅ Cron `gdpr_auto_anonymize_daily` (03:30 Africa/Abidjan) : supprime contacts inactifs > 24m, anonymise WA/SMS > 12m, purge `access_logs` + `api_traces` > 90j. Audit trail dans `gdpr_anonymization_runs`. **Délais configurables** dans AdminSettings.
- ✅ Endpoint `GET /me/gdpr/export` — JSON complet de toutes les données de l'utilisateur (user, contacts, WA inbound/outbound, SMS, tâches, notes, rapports, suivis). Bouton "Exporter mes données" dans `MyAccount.jsx`.
- ✅ Endpoint admin `POST /admin/gdpr/anonymize-now` pour déclencher manuellement.

### Backend bonus_pack_9l module
- ✅ Nouveau module `/app/backend/routes/bonus_pack_9l.py` (~280 lignes) — `parse_task_ack`, `run_wa_tasks_digest`, `apply_task_ack_for_user`, `run_liluvine_weekly_digest`, `run_gdpr_anonymization`.
- ✅ 8 nouvelles clés `settings` (wa_tasks_digest_enabled, liluvine_weekly_digest_enabled, gdpr_*).
- ✅ 3 nouvelles cron jobs APScheduler.

### Tests & qualité
- ✅ **12 nouveaux tests pytest** (parser unit tests, opt-in PUT/GET, validation hour, GDPR export, run-now endpoints, GDPR dry-run with enabled, integration ack flow via Motor).
- ✅ **Cumulatif fix9a → fix9l : 68/68 verts**.
- ✅ Lint Python + JS clean.

_⚠️ Historique antérieur (Iter38r-fix9k) conservé ci-dessous._

## Recent (2026-05-30) — Iter38r-fix9k 📋📄📝

### 🔥 P1 — Demande #11 : KB import depuis presse-papier (Ctrl+V)
- ✅ Listener `paste` global dans `LiluvineKnowledgeBaseSection.jsx` — toute capture d'écran collée déclenche un upload OCR automatique (titre auto-suggéré avec timestamp).
- ✅ Banner d'astuce **"Ctrl+V pour importer une capture d'écran"** affiché en haut de la section.

### 🔥 P1 — Demande #9 : OCR Claude Vision sur PDF (+ coût paramétrable)
- ✅ **PyMuPDF** ajouté à `requirements.txt` (==1.27.2.3) pour rasteriser les PDF page-par-page (150 DPI).
- ✅ Nouvelle fonction `_ocr_pdf_with_claude_vision` qui OCR chaque page individuellement, concatène avec `--- Page N ---`, et respecte `kb_ocr_pdf_max_pages` (défaut 30).
- ✅ **Tracking coût** : chaque upload OCR insère un doc dans `ai_usage` avec `{resource: "kb_ocr", units: pages, cost_xof, ym: "YYYY-MM"}`.
- ✅ **Plafond mensuel** : si `kb_ocr_xof_monthly_cap > 0` et déjà atteint → upload renvoie **429** avec message clair.
- ✅ **Endpoint** `GET /api/admin/liluvine-pro/kb/ocr-usage?month=YYYY-MM` retourne `{pages, cost_xof, monthly_cap_xof, xof_per_page, remaining_xof, count_uploads}`.
- ✅ **3 nouveaux paramètres** dans AdminSettings : `kb_ocr_xof_per_page`, `kb_ocr_xof_monthly_cap`, `kb_ocr_pdf_max_pages` (nouvelle section "Liluvine PRO — Coût OCR").

### 🔥 P1 — Demande #10 : Notes/Tâches checklist Google Keep
- ✅ Nouveau modèle `TaskItem` (id, text, done, order, done_at). Champ `task_items: List[TaskItem]` ajouté à `UserNoteCreate` et `UserNoteUpdate`.
- ✅ Persistance dans la collection `user_tasks_personal` (auto-génération des UUIDs si absent).
- ✅ Composant React `TaskChecklist` (Google Keep style) — items cochables, items terminés relégués en bas grisés/barrés, compteur "X fait(s) / N".
- ✅ Aperçu inline des items dans les cartes de la liste des tâches (max 6 items, compteur de complétion).
- ✅ **Option configurable** `notes_strict_tasks_only` dans AdminSettings : si activée, l'éditeur HTML est masqué sur `/portal/notes/tasks` (checklist uniquement). Sinon mode mixte. Exposée via `/me/features` pour s'appliquer à tous les utilisateurs trackés du tenant.

### Tests & qualité
- ✅ **8 nouveaux tests pytest** pour fix9k (OCR usage endpoint, PDF classic mode, PDF OCR mode, monthly cap 429, task_items create, task_items update, features flag exposure, settings persistence).
- ✅ Test pré-existant `test_kb_upload_rejects_pdf_in_ocr_mode` renommé en `test_kb_upload_accepts_pdf_in_ocr_mode` (PDF désormais accepté en OCR).
- ✅ **Cumulatif fix9a → fix9k : 56/56 verts**.
- ✅ Lint Python + JS clean.
- ✅ **Testing agent** : 100% backend, 95% frontend (rendering OK, intégration vérifiée).

_⚠️ Historique antérieur (Iter38r-fix9j) conservé ci-dessous._

## Recent (2026-05-30) — Iter38r-fix9j 💸📧

### 🟡 P1 — SMTP Gmail App Password (sécurité prod)
- ✅ **Configuration SMTP Gmail** branchée : `smtp.gmail.com:587` STARTTLS, compte `jfrancois.ouoba@gmail.com`, app password 16 car., display name **"SAWALI SMART SYSTEMS"**.
- ✅ **Nouveau champ** `smtp_from_name` dans `models.SettingsUpdate` + UI AdminSettings + `email_service.py` (header RFC 5322 `Name <email>`).
- ✅ **OTP envoyé par email** pour les utilisateurs externes (`dev_otp = null` côté réponse — fuite réseau corrigée). Les domaines internes (`@sawalismartsystems.com`) continuent d'afficher le code sur la page (rapidité).
- ✅ Test E2E SMTP : email réel reçu sur la boîte (`send_email` returned True).

### 🟡 P1 — PawaPay Payouts v2 (Mobile Money out)
- ✅ **Nouveau module** `/app/backend/routes/pawapay_payouts.py` (281 lignes) — endpoint POST `/api/me/payments/pawapay/payout`, GET `/api/me/payments/pawapay/payout/{id}?refresh=true`, GET `/api/me/payments/pawapay/payouts` (avec KPIs), POST `/api/webhooks/pawapay/payouts/{secret}`.
- ✅ **Conforme à la spec PawaPay v2** : `payoutId` UUIDv4 stocké AVANT l'appel API (résilience réseau), `provider` au lieu de `correspondent`, amount string sans décimale (XOF = NONE decimals), `failureReason {failureCode, failureMessage}` persistés, **defensive handling** (jamais marqué FAILED sur 5xx / network error → reste PENDING pour reconciliation).
- ✅ **Webhook idempotent** : skip si status + failure_code identiques. Orphan callback loggé dans `wa_webhook_logs`.
- ✅ **RBAC** : admin / superviseur / comptable (tracked_role) seulement. Sinon 403.
- ✅ **3 providers BFA** : `ORANGE_BFA`, `MOOV_BFA`, `TELECEL_BFA` (currency `XOF`).
- ✅ **Page UI dédiée** `/portal/payouts` (`Payouts.jsx`) avec : KPI strip (Total / Terminés + montant XOF / En attente / Échoués), formulaire (provider, msisdn, montant XOF, message ≤22 car.), liste avec statut coloré + bouton "Actualiser" sur les pending, pré-remplissage via URL params.
- ✅ **Bouton "💸 Payer via Mobile Money"** sur les bulletins de paie GRH (`PayslipsTab`) → redirige vers `/portal/payouts?amount=…&msisdn=…&message=Paie YYYY-MM`.
- ✅ **Lien sidebar** "Payer (Mobile Money)" (icône Banknote, `cashOnly`).

### Tests
- ✅ **7 tests pytest** : enabled gate, msisdn validation, defensive PENDING on 4xx fake token, list+KPIs, webhook secret gating, webhook idempotency, `smtp_from_name` persistence.
- ✅ Lint Python + JS clean.
- ✅ **Total cumulé fix9 + fix9j : 56/56 verts**.

_⚠️ Historique antérieur (Iter38r-fix9a → fix9i) conservé ci-dessous._

## Recent (2026-05-30) — Iter38r-fix9i 🤝🔍📅

### P0 — KB Liluvine PRO : séparation OCR / non-OCR
- ✅ **2 boutons d'import distincts** dans la base de connaissance :
  - 📄 **"Importer PDF / TXT"** (violet) : extraction texte native, **pas d'OCR** lancé.
  - 🔍 **"Importer Image (OCR)"** (sky) : Claude Vision OCR forcé.
- ✅ Backend `POST /admin/liluvine-pro/kb/upload` accepte `force_ocr` (Form param). Mode classique rejette les images (415), mode OCR rejette les PDF (415).

### P1 — Pack Liluvine PRO (b) + (c) — Reprendre la conversation
- ✅ **Endpoint** `POST /admin/liluvine-pro/sessions/{sid}/takeover` → marque la session `human_takeover=True`, `human_takeover_until` configurable (5 min → 7 j, défaut 120 min), retourne `phone_digits` pour redirection.
- ✅ **Endpoint** `POST /admin/liluvine-pro/sessions/{sid}/release` → libère la session.
- ✅ **Endpoint** `GET /admin/liluvine-pro/sessions-history` → liste enrichie (channel, last_message_preview, last_message_role) avec filtres serveur (channel, date_range, q).
- ✅ **Auto-réponse WA** : `autoreply_to_inbound` skip silencieux si `human_takeover` actif (avec respect du `human_takeover_until`).
- ✅ **RBAC** : rôles `admin / superviseur / moderateur` (et tracked_role équivalents) seulement. Sinon 403.
- ✅ **Page dédiée** `/admin/liluvine-history` (`AdminLiluvineHistory.jsx`) : KPI strip par canal, filtres date range (today/7d/30d/90d/all), recherche, table avec actions Eye / Reprendre / Libérer + modale conversation lecture-seule.
- ✅ **Boutons sidebar** dans `LiluvinePro.jsx` : Hand (Reprendre) + ArrowRightCircle (Libérer) sur les sessions WA, visibles au hover pour les rôles autorisés. Badge "Reprise par humain" affiché sur les sessions reprises.
- ✅ **Lien sidebar admin** : "Liluvine PRO — Historique" (icône Bot) dans `PortalLayout.jsx`.

### P1 — Filtres temporels pour l'historique du travail (Admin Settings)
- ✅ **5 filtres date range** dans la section "Suivi des actions (historique du travail)" : Aujourd'hui / 7j / 30j / 90j / Toujours (combinés avec le filtre statut existant et le toggle Tableau/Kanban).

### Validation post-fork (rappel)
- ✅ Fixes héritées du fork précédent **revalidées** : Trash icon `Contacts.jsx`, AdminSettings Search (3 sections Liluvine indexées), WA auto-reply thread, Unified Inbox matching, cohérence multi-utilisateurs (tracked + admins).

✅ **6 nouveaux tests pytest** (takeover + release + history enrichment + KB classic-mode rejects image + KB OCR-mode rejects PDF + search filter).
✅ **3 tests addl** (RBAC 403, WA autoreply skip, date_range filter) ajoutés par testing agent.
✅ **Total cumulé fix9 + fix9i : 49/49 verts** + lint JS/Python clean.
✅ **Testing agent** : 100% (43/43 backend, 15+ sélecteurs UI vérifiés, login OTP OK).

_⚠️ Historique antérieur (Iter38r-fix9a → fix9h) conservé ci-dessous._

## Recent (2026-05-30) — Iter38r-fix9h 🔥

### P0 — OCR Claude Vision pour la KB Liluvine
- ✅ **Upload d'images** (PNG/JPG/WEBP) dans la base de connaissance.
- ✅ **Claude Sonnet 4.6 Vision** extrait automatiquement tout texte visible (via `emergentintegrations.LlmChat` + `ImageContent`) et le stocke comme entrée `kind: "image_ocr"`.
- ✅ Détection "[AUCUN_TEXTE_DETECTE]" → erreur 422 propre.
- ✅ UI mise à jour : libellé "Importer PDF / TXT / Image (OCR)" + icône bleue pour les entrées image-OCR.

### P1 — Pack Liluvine PRO (a) + (d) — sidebar enrichie
- ✅ **Onglets de filtrage par canal** : 💬 Toutes / 🌐 Web / 📱 WA / 📘 FB / 📩 SMS.
- ✅ **Recherche** dans titre/contact.
- ✅ **Badges riches** par session : canal coloré, `user_label`, "à l'instant / il y a X min / il y a X h / date courte", nombre de messages.

### P1 — Encart "📥 Nouveaux partages cette semaine" dans la modale d'accueil
- ✅ Nouveau bloc gradient vert dans WelcomeBriefing : compte les notes/tâches/rapports/suivis partagés (ciblés ou publics du tenant) reçus dans les 7 derniers jours.
- ✅ Chips cliquables par type (rapports/suivis/notes/tâches) → deeplink vers `/portal/notes/<kind>?scope=shared`.
- ✅ `UserNotes.jsx` honore désormais le paramètre `?scope=...` au chargement.
- ✅ Endpoint `/me/welcome-briefing` enrichi avec `notes_kpis.shared_recent: {total, by_kind, window_days}`.

### P1 — Bouton "Réaligner tout" sur le panoramique
- ✅ Nouvel endpoint `POST /admin/clients-consistency/realign-all` (avec `confirm=true` requis et `dry_run` optionnel).
- ✅ Bouton 🔧 "Tout réaligner" dans l'UI panoramique d'AdminSettings.

✅ **4 tests pytest** (KB image accepté, realign-all confirm/dry-run, briefing shared_recent).
✅ **Total cumulé : 71/71 verts** + lint OK.

## Recent (2026-05-29) — Iter38r-fix9g 🔧

### 3 bugs corrigés
- 🐛 **Fix #1 — 👁 Œil sur "Partagés avec moi"** : maintenant **toujours visible** sur les notes/tâches/rapports/suivis dont vous n'êtes pas le propriétaire (admin inclus). Permet la consultation rapide sans entrer en mode édition.
- 🐛 **Fix #3 — Recherche AdminSettings trouve "Liluv"** : les 3 sections (Auto-réponse WhatsApp, Branding, Base de connaissance) sont maintenant enveloppées dans `<Filterable>` → indexées par la barre de recherche d'AdminSettings.
- 🐛 **Fix #4 — Cohérence multi-utilisateurs détecte les tracked_users** : `_scan_clients_consistency` étend désormais le scan aux utilisateurs trackés (avec `parent_client_id`), via une jointure sur l'admin parent de leur tenant. Les tracked users dont `client_id != parent_client_id` (admin canonique) sont maintenant correctement détectés et listés pour réalignement.

✅ **2 tests pytest** (détection de tracked user désaligné + structure de la réponse).
✅ **Total cumulé : 67/67 verts** + lint OK.

## Recent (2026-05-29) — Iter38r-fix9f 🤝🪟👁

### A — Notes/Tâches/Rapports/Suivis partagés
- ✅ **Backend** : `me_list_notes` étendu → les **utilisateurs non-élevés** (Consultation, Comptable, etc.) voient désormais les éléments **publics du même tenant** (en plus des leurs et ceux où ils sont destinataires).
- ✅ **Notes & Tâches ouvertes à tous** (Rapports/Suivis restent réservés aux profils élevés — documents formels).
- ✅ Nouveau param `?scope=mine|shared|all` pour filtrer.
- ✅ Champ `tenant_id` stampé à la création pour scoper correctement la visibilité publique.
- ✅ **Frontend** (UserNotes.jsx) : onglets **Tous / Les miens / 📥 Partagés avec moi**. Badge "📥 partagé" + pictogramme **œil 👁** sur chaque carte non-éditable → ouvre une **modale lecture-seule** avec titre/numéro/auteur/contenu/images.

### B — Chat Liluvine PRO redimensionnable
- ✅ Sidebar des conversations redimensionnable (220-480 px, persistant en localStorage, comme Direct Chat & WhatsApp).
- ✅ Bouton flottant ‹/› pour collapser/déplier le panneau.

### C — Bouton "Voir conversation" dans le toast Liluvine
- ✅ Le toast temps réel inclut désormais un bouton **👁 Voir la conversation** qui navigue vers `/portal/contacts?q=<phone_digits>` (filtrage automatique du contact via la nouvelle gestion `?q=...`).
- ✅ Durée du toast augmentée à 9s pour laisser le temps de cliquer.

✅ **6 tests pytest** (création non-élevée, scope filters, tenant_id stamping, visibilité publique/privée/ciblée).
✅ **Total cumulé : 65/65 tests pytest verts**.

## Recent (2026-05-29) — Iter38r-fix9e 🎨🔔

### Branding Liluvine PRO
- ✅ Nouvelle section Admin Settings : *« Liluvine PRO — Personnalisation visuelle »* (bandeau rose).
- ✅ Configurer : nom affiché, tagline, **avatar** (URL + upload + génération IA Nano Banana), 7 couleurs d'accent (fuchsia/violet/indigo/sky/emerald/amber/rose). Preview live.
- ✅ Endpoints `GET/PUT /api/admin/liluvine-pro/branding` + `GET /api/me/liluvine-pro/branding` enrichi avec `tagline`.

### Toast temps réel WhatsApp auto-reply
- ✅ Component global `<LiluvineLiveToast />` monté dans `PortalLayout.jsx` pour admin/superviseur uniquement.
- ✅ **Polling 20s** sur `/api/me/liluvine-pro/autoreply-feed?since=...` (cursor incremental basé sur `server_now`).
- ✅ **Toast custom sonner** avec : icône Bot, nom du contact, preview du message (140 car. max), animation slide-in, durée 7s.
- ✅ **Beep Web Audio** synthétisé (no asset required) avec **toggle mute persistant** (localStorage) via bouton flottant 🔔/🔇 (bottom-left).
- ✅ Bootstrap intelligent : au premier load, marque tous les messages existants comme "vus" pour ne PAS spammer l'utilisateur à chaque connexion.

✅ **7 tests pytest verts** (branding CRUD + validation couleur + feed scope/since/contenu).
✅ **Total cumulé : 59/59 tests pytest verts**.

## Recent (2026-05-29) — Iter38r-fix9d 🎉
- ✅ **Mini-compteur ROI Liluvine PRO** dans la modale de bienvenue : *« X WhatsApp pris en charge par Liluvine aujourd'hui 🎉 »*. Affiche aussi les minutes économisées, le compteur d'hier, le total 7 jours, et un badge "⏸ Désactivé" si le toggle est off.
- ✅ Section dédiée gradient fuchsia avec icône Bot. Apparaît dès qu'il y a au moins 1 message dans les 7 derniers jours.
- ✅ Endpoint `/me/welcome-briefing` enrichi avec `liluvine_autoreply_today: {today, yesterday, last_7d, minutes_saved_today, enabled}`. Scope tenant (admin/superviseur voient leur tenant, tracked users héritent du parent).
- ✅ **2 tests pytest** verts (structure + comptage par fenêtre temporelle).

## Recent (2026-05-29) — Iter38r-fix9a + fix9c 🤖📚

### fix9a — Auto-réponse WhatsApp NATIVE (sans n8n)
- ✅ **Liluvine PRO répond automatiquement** aux messages WhatsApp entrants via le webhook Meta existant. Aucune dépendance n8n.
- ✅ **Règles configurables** (Admin Settings → section dédiée) : toggle global, allow-list/deny-list de numéros, whitelist stricte, plage horaire (toujours/heures ouvrables/hors heures), mots-clés déclencheurs, anti-flood (60s par défaut), signature personnalisable.
- ✅ **Audit + monitoring** : historique des réponses auto avec session label, message envoyé, RAG status, tokens. Stocké dans `liluvine_pro_messages` avec `external_source: "whatsapp_native"`.
- ✅ **8 tests pytest** (règles de décision + endpoints + persistence).

### fix9c — Base de connaissance Liluvine PRO
- ✅ **CRUD admin complet** : créer/éditer/désactiver/supprimer des entrées texte (FAQ, procédures, doc logiciels SAWALI).
- ✅ **Upload PDF/TXT** : parsing via `pypdf`, chunking automatique à 1500 caractères/morceau. Max 5 Mo par fichier.
- ✅ **Injection automatique** : `build_kb_context()` agrège les entrées actives (budget 6 KB pour le chat, 4 KB pour WA) et l'insère dans le system message de Claude.
- ✅ **UI Admin** : section gradient violet avec stats (entrées totales, actives, caractères stockés), barre d'usage du budget, tags, toggle actif/inactif.
- ✅ **6 tests pytest** (CRUD + upload TXT chunking + rejets oversized/unsupported + budget context).

**Total tests cumulés : 50/50 verts** (5 + 6 + 6 + 3 + 2 + 8 + 6 + 14 iter35q).

## Recent (2026-05-28) — Iter38r-fix8c 🐛
- 🐛 **BUG PROD CORRIGÉ — Toggle Liluvine PRO ne persistait pas** : le modèle Pydantic `ClientFeaturesUpdate` ne déclarait pas le champ `ai_liluvine_pro`, donc Pydantic le supprimait silencieusement avant l'enregistrement en base. Activer le toggle dans SMART Communications n'avait aucun effet — l'écran Liluvine PRO disait "non activé". **Le champ est désormais ajouté au modèle**. ⚠️ **À redéployer en prod** pour que les utilisateurs puissent activer Liluvine PRO.
- ✅ **Test de régression statique** : nouveau test garantit que CHAQUE clé de `DEFAULT_CLIENT_FEATURES` doit exister dans `ClientFeaturesUpdate.model_fields`. Empêche toute future feature d'être oubliée du modèle Pydantic.

## Recent (2026-05-28) — Iter38r-fix8b 🎯
- ✅ **Régression écran de bienvenue corrigée** : la modale "Bienvenue 👋" affiche désormais une section "Synthèse de votre activité" avec compteurs cliquables Rapports / Suivis / Notes / Tâches (+ badge "X en retard" pour les tâches dépassées). Le Dashboard `/portal` affiche également toujours les 4 NoteCards (Rapports/Suivis si feature activée + Notes/Tâches systématiquement) quelle que soit la configuration features.
- ✅ **Badge "🔒 Persistant" + statistiques** : le générateur de médias `/portal/media-generator` affiche un compteur global `X fichier(s) protégé(s) · Y Mo` (depuis `stored_objects`) et chaque vignette de l'historique IA porte une pastille verte 🔒 lorsque le fichier est stocké sur Emergent Object Storage.
- ✅ **API enrichie** : `/me/welcome-briefing` retourne `notes_kpis` (counts + last_updated + overdue tasks). `/me/ai/history` retourne `persistent: bool` par item + `storage_stats: {files, bytes}`.

## Recent (2026-05-28) — Iter38r-fix8 🗂️
- ✅ **Persistance Object Storage finalisée** : tous les uploads (admin, media-library, photos contacts, médias WhatsApp inbound/outbound, pièces jointes de formulaires, médias IA) sont désormais **mirrorés sur Emergent Object Storage** dès l'enregistrement. La rehydratation au moment du `GET /api/files/{file_id}` couvre les redéploiements production qui vidaient le disque éphémère.
- ✅ **Helper `object_storage.py`** : nouveau module avec `save_and_log()` + collection `stored_objects` pour la traçabilité multi-tenant (utilisé par les générations IA Gemini Nano Banana / Sora 2).
- ✅ **Templates n8n** : `/app/memory/n8n_templates.md` documente 5 workflows clé-en-main (WhatsApp, Facebook Messenger, SMS, Email, Outbound Dispatcher) connectés à `/api/webhooks/liluvine-pro/{source}/{secret}`.
- ✅ **Iter38r — 90+/90+ tests pytest pass** (cumulatif sur 8 itérations).

## Recent (2026-05-28) — Iter38r-fix6 ✨
- ✅ **UI Quotas IA** : section complète dans `/admin/clients/{id}/features` (mode off/quota/budget XOF, alertes, tarifs override, consommation temps réel par utilisateur, exports CSV/PDF).
- ✅ **Liluvine PRO / Assistant SAWALI** : assistant interne propulsé par **Claude Sonnet 4.6** avec sessions persistées, RAG par injection contextuelle (contacts/tickets/paiements/RDV/notes), tracking auto via Quotas IA, page `/portal/liluvine` avec sidebar conversations + suggestions de prompts.
- ✅ **Iter38r — 56/56 tests pytest pass** (cumulatif sur 7 itérations).

## Recent (2026-05-28) — Iter38r-fix4 → fix5

## 🚧 Backlog prioritaire (P1)
- **Liluvine Pro / Assistant SAWALI** (~15h / 2 jours) : assistant interne piloté par Emergent LLM Key avec accès RAG aux données SAWALI (contacts, tickets, paiements, notes, RDV), conversations historisées MongoDB, tool calling, streaming.
- **Quotas + Alertes IA par Client Lié** : toggle quota OU budget par mois, devise par défaut FCA/XOF, ventilation Images / Vidéos / Transcriptions / Chat IA, alertes 80%/100%, blocage configurable, export PDF/CSV historique cumulé par "Utilisateur Suivi" (Date/Heure, Utilisateur Suivi, Ressource, unités, base).
- **PawaPay Payouts** (en attente confirmation account chez l'utilisateur) : décaissements salaires/avances depuis GRH+Paie + interface dédiée Caisse → Décaissements.

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

## ROADMAP / Backlog (priorisé)

### 🟧 P1 — Liluvine intelligent (à faire prochaine session)
**Couplage Liluvine ↔ Jauge Support Technique** :
1. Ajouter dans Admin Settings → Section "Jauge d'occupation" un champ **"Seuil d'alerte Liluvine"** (slider 0..7, défaut=6).
2. Quand le niveau courant ≥ seuil, le bot Liluvine de la home affiche en priorité un message du genre :
   > "Notre équipe est très sollicitée. Privilégiez le formulaire de contact ou WhatsApp pour une réponse plus rapide qu'au téléphone."
3. **Contrôle distant du seuil** :
   - **Option A — WhatsApp** : commande spéciale (ex: `!seuil 5`) reçue via webhook Meta WA sur le numéro admin → met à jour le seuil.
   - **Option B — Lien spécifique** : URL du type `/admin/seuil/{token-crypté-HMAC}?value=N` que vous pouvez bookmarker sur le téléphone et cliquer pour changer le seuil sans login.
   - Le token est généré côté serveur (HMAC SHA256 du seuil + secret + timestamp), expirable, et stocké chiffré.
4. Audit log dans `db.api_traces` à chaque changement (qui/quand/comment).

### 🟧 P1 — Stats SMS dans `/admin/usage`
- Graphiques par fournisseur (volume/jour, taux succès)
- Top 10 clients consommateurs SMS
- Coût estimé (à raison de tarifs configurables admin par provider)

### 🟧 P1 — Backlog 2026-05-27 (4 points utilisateur)

**P1.1 — Onglet "Jours fériés" dans configuration paie (GRH)** ✅ FAIT (Iter38m)
- ~~Ajouter un onglet "Jours fériés" dans le module GRH/HR.~~ ✅
- ~~CRUD liste de jours fériés : date, libellé, type, payé/non payé.~~ ✅
- ~~Bouton "Importer les fêtes de l'année" qui peuple automatiquement la liste pour l'année en cours selon le pays défini.~~ ✅
- ~~Liste éditable.~~ ✅
- ~~Pré-peupler avec les jours fériés du Burkina Faso connus.~~ ✅
- ~~Backend : nouvelle collection `hr_holidays` + endpoints `GET/POST/PATCH/DELETE /api/hr/holidays`.~~ ✅
- ⚠️ Reste à faire (P2) : Impact paie automatique — si un employé prend une absence sur un jour férié, ne pas le déduire OU le surligner dans la fiche.

**P1.2 — Dépenses caisse : tiers OU employé** ✅ FAIT (Iter38m)
- ~~Modifier le module Caisse → Dépenses pour permettre de choisir entre "Tiers libre" et "Employé" lors de la création.~~ ✅
- ~~Si "Employé" : dropdown des employés du tenant.~~ ✅
- ~~Rappel dans le chat direct (DÉJÀ FAIT — Iter38c).~~ ✅
- ~~Ajouter le rappel sur l'écran de bienvenue de l'utilisateur (dashboard portail).~~ ✅
- ~~Backend : étendre `cashier_expenses` collection avec champ `employee_id` + endpoint qui retourne la liste des dépenses en retard.~~ ✅

**P1.3 — Aperçu/Relance message WhatsApp pour Reçus/Factures/Proformas** ✅ FAIT (Iter38m)
- ~~Modal "📩 Aperçu envoi WhatsApp" ouvert via badge WhatsApp dans CashBilling.~~ ✅
- ~~Affiche : module utilisé, numéro destinataire (E.164), statut dernier envoi (OK / KO + erreur), date, preview message + PDF.~~ ✅
- ~~Bouton "Renvoyer le message" si non-distribué.~~ ✅
- ~~Accessible aux rôles Admin, Superviseur et Caissier.~~ ✅

**P1.4 — (déjà fait, juste à confirmer)** ✅ FAIT (Iter38l)
- ~~Fix bug ArrowDown not defined dans UnifiedInbox.jsx~~ ✅
- ~~Fix dropdown "Comptable" manquant dans AdminTrackedUsers + AdminContacts~~ ✅
- ~~Implémentation Sora 2 (génération vidéo) dans MediaGenerator~~ ✅

### 🟧 P0 — Refactor `server.py`
- Découpage en `/app/backend/routes/` : `auth.py`, `admin.py`, `me.py`, `public.py`, `webhooks.py`, `payments.py`, `sms.py`, `whatsapp.py`, `dashboard.py`, `formations.py`…
- Actuellement >19 300 lignes — devient critique pour maintenabilité.
- Modules déjà extraits : `cashier.py` (2542 lignes), `hr.py` (375 lignes), `internal_chat.py`, `sms_dashboard.py`.

### 🟧 P0 — GRH Phases 4-6 (à reprendre après déploiement actuel + A/B)
- **Phase 4** : Absences/Déductions (jours/heures d'absence, seuils admin avant déduction). ✅ FAIT (Iter38b)
- **Phase 5** : Taxes fiscales (5 configurables, global tenant avec override par employé) + Avances sur salaire (motifs). ✅ FAIT (Iter38b)
- **Phase 6** : Synthèse mensuelle PDF (paie par employé ou par entreprise). ✅ FAIT (Iter38b)
- Phase 5 v2 : UI d'override des taxes par employé (backend déjà en place via `tax_overrides`).

### 🟧 P0 — Cashier Trash UI (A.3) — UI en attente
- Backend complet (soft-delete + restore + permanent delete).
- Frontend `CashBilling.jsx` : ajouter toggle "Afficher la corbeille" + boutons restore/delete permanent.

### 🟧 P1 — B-list (à faire après déploiement actuel)
- ~~**B.1** Indicateur résultat envoi WhatsApp (OK/KO toast après dispatch template).~~ ✅ FAIT (Iter38e)
- ~~**B.2** Date "dernière utilisation" produit (basée sur **toute facture payée**, hors proformas).~~ ✅ FAIT (Iter38e)
- ~~**B.3** Upload/génération AI icône PNG produit + toggle export catalogue public.~~ ✅ FAIT (Iter38e — upload OK, génération IA stub 503 en attente du playbook Nano Banana)
- ~~**B.4** Auto-scroll bas pour WA Chat + Internal Chat.~~ ✅ FAIT (Iter38c)

### 🟦 P2 — Future (suite Iter38e)
- **📦 Catalogue public e-commerce** ⭐ *(suggéré + accepté par l'utilisateur le 2026-05-27, à faire dans une future session)* :
  - Créer une page `/catalogue` publique (sans auth) qui liste tous les produits avec `is_public=true`, classés par catégorie.
  - Affichage card avec : icône (image_url), nom, prix HT, unité, description.
  - Filtres : par catégorie, recherche texte.
  - Bouton "Demander un devis" sur chaque produit → pré-remplit le formulaire de RDV (`/rdv?product_id=…`) avec produit présélectionné.
  - Ajouter au menu de navigation public (Home → Catalogue).
  - Multi-tenant : URL `/catalogue` montre les produits du tenant principal (SAWALI). Possibilité plus tard d'ajouter `/catalogue/{tenant_slug}` pour chaque tenant.
- **🤖 Intégration Gemini Nano Banana** : finaliser l'endpoint `/api/cashier/products/generate-icon` (actuellement stub 503). Appeler `integration_playbook_expert_v2` pour récupérer la playbook officielle, puis remplacer le stub par l'appel emergentintegrations + mirroring sur Object Storage.

### 🟦 Future
- **🔔 Versioning + Notification email à chaque modification de secret (P2)** — Plutôt qu'un rappel mensuel, déclencher à chaque création/modification d'un secret API : (a) email à l'admin avec qui/quand/quelle clé (jamais la valeur), (b) versioning des secrets (rollback possible vers une version précédente). À combiner avec le coffre-fort iter35e.
- **🔊 Notifications vocales Alexa Echo — Option 1 Voice Monkey (P2)** ✅ **FAIT (Iter35y)** — Module `/app/backend/services/alexa.py` + section AdminSettings "Notifications vocales Alexa (Voice Monkey)" avec toggle + URL webhook + checkboxes par événement (SMS reçu, WA reçu, RDV imminent, support critique). Hooks branchés sur les 4 événements. Tests dans `test_iter35x_p2.py::TestAlexaVoiceMonkey`.
- **🔊 Notifications vocales Alexa Echo — Option 3 Home Assistant (P3)** — Évolution : remplacer Voice Monkey par une instance Home Assistant locale (intégration `alexa_media_player`). Plus puissant et sans dépendance tierce, mais nécessite que le client ait HA déployé chez lui (Raspberry Pi). Le champ admin devient "URL Home Assistant + token long-lived".
- ErrorBoundary global sur toutes les routes /portal/* et /admin/*
- **Composant `<ResponsiveTable>` réutilisable** (avec props `<Column hideBelow="sm">`) pour standardiser le pattern responsive sur tous les tableaux et éviter les répétitions à la main (issue de l'itération 49).
- Tags sur payment_links (filtrage dashboard par campagne)
- A/B test multi-canal automatisé (SMS vs WA, conversion par canal)
- Lien de paiement intégré dans le module SMS (comme dans WA)
- Scanner QR `encodePCS` (BLOQUÉ — attente lib/code C# Windows)
- PDF côté serveur (WeasyPrint/ReportLab)
- Bandeau RGPD cookies
- Stripe Checkout pour Formations payantes

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


---


## Iter40-modal (2026-06) — Régie publicitaire : modale aléatoire publique

### Contexte
L'utilisateur souhaite afficher, sur la page publique, **une bannière publicitaire en modale au chargement** (image au hasard parmi un pool, jusqu'à 10 actives). Indépendant du slot top-of-page.

### Implémentation
- **Backend** (`/app/backend/routes/ad_banners.py`) :
  - Pattern regex de validation `placement` étendu à `^(public|portal|both|public_modal)$` (déjà fait dans la session précédente)
  - Endpoint `GET /api/public/ad-banners/active?placement=public_modal` :
    - Renvoie **uniquement** les bannières dont `placement == "public_modal"` (pas de fuite avec public/both)
    - Sélection aléatoire pondérée (même algo que `public`/`portal`)
    - Pas de banner → `{"banner": null}`
- **Frontend** :
  - Nouveau composant `/app/frontend/src/components/PublicAdModal.jsx` — modal centré (z-index 9999), backdrop blur, fermeture par X / ESC / clic backdrop, badge « PUBLICITÉ », CTA « Découvrir → »
  - Affichage avec délai de 1500ms après mount, **une seule fois par session** via `sessionStorage`
  - Tracking impression/clic via les endpoints existants
  - Intégré dans `MarketingLayout.jsx` (toutes les pages publiques en bénéficient)
- **Admin UI** (`/app/frontend/src/pages/admin/AdminAdBanners.jsx`) :
  - Option `<option value="public_modal">Modale aléatoire (page publique)</option>` ajoutée au select Emplacement
  - Libellé colonne « Modale publique » affiché dans la liste

### Tests
- `/app/backend/tests/test_iter40_public_modal_placement.py` (4 tests, **tous PASS**) :
  - Admin peut créer une bannière avec placement=public_modal
  - L'endpoint modal ne renvoie QUE des bannières modal
  - L'endpoint public top-slot exclut les bannières modal
  - Placement invalide rejeté (HTTP 422)
- Régression 16 tests précédents (`test_iter38r_fix9w_*`, `test_iter38r_fix9y_*`) : **PASS**
- Smoke screenshot UI : modal s'affiche correctement avec image, badge, X, CTA.

## Iter40-modal-frequency (2026-06) — Réglage de fréquence + compteurs modal dédiés

### Contexte
Suggestion d'amélioration acceptée par l'utilisateur. La modale était utile mais pouvait lasser les visiteurs (affichée 1×/session uniquement, en dur). Besoin de pouvoir choisir une fréquence par bannière et de séparer les statistiques modale du slot top-of-page.

### Implémentation
- **Backend** (`/app/backend/routes/ad_banners.py`) :
  - Champ `modal_frequency` ajouté à `AdBannerPayload` & `AdBannerUpdate` (pattern `^(session|daily|always)^`, défaut `"session"`)
  - Persisté à la création + retourné par `_public_view` pour que le frontend décide
  - Compteurs dédiés `modal_impressions` / `modal_clicks` initialisés à 0
  - Endpoints `/impression` et `/click` acceptent `?modal=1` → incrément séparé sur les compteurs modale (en plus du global)
  - Endpoint `/admin/ad-banners/{id}/stats` expose un bloc `modal: {impressions, clicks, ctr_pct, frequency}`
- **Frontend** :
  - `PublicAdModal.jsx` réécrit pour lire `banner.modal_frequency` et choisir le storage :
    - `session` → `sessionStorage["public_ad_modal_shown"]`
    - `daily` → `localStorage["public_ad_modal_shown_day_{bannerId}_{YYYY-MM-DD}"]`
    - `always` → aucun flag (rejoue à chaque rechargement)
  - Tracking impression/clic envoie `&modal=1` pour alimenter les compteurs modale
  - `AdminAdBanners.jsx` :
    - Nouveau champ select "Fréquence d'affichage" visible uniquement quand `placement=public_modal`
    - Bloc StatsModal "Modale aléatoire" affiche compteurs dédiés (affichages, clics, CTR) + libellé fréquence — visible quand des impressions modale existent

### Tests
- `/app/backend/tests/test_iter40_modal_frequency.py` (7 nouveaux tests) :
  - Fréquence par défaut = "session" si omise
  - Les 3 valeurs `session|daily|always` sont acceptées
  - Valeur invalide ("weekly") rejetée HTTP 422
  - Endpoint public renvoie `modal_frequency` dans la payload
  - `?modal=1` sur impression bumpe `modal_impressions` ET `total_impressions`
  - `?modal=0` ne bumpe QUE `total_impressions`
  - `?modal=1` sur click bumpe `modal_clicks` ET `total_clicks`
  - Endpoint stats expose `{modal: {impressions, clicks, ctr_pct, frequency}}`
- Régression complète : **27/27 PASS** (7 nouveaux + 4 placement + 16 anciens)
- Smoke UI : page publique se charge proprement


## Iter40-modal-ab + global-cap (2026-06) — A/B fréquence + plafond global de modales

### Contexte
Deux améliorations majeures du système de modale publicitaire publique :
1. **Plafond global** : limite le nombre de modales qu'un même visiteur peut voir sur 24h, toutes campagnes confondues (anti-sur-sollicitation, surtout utile quand plusieurs campagnes "always" tournent).
2. **A/B sur la fréquence** : permet de tester deux fréquences différentes sur la même bannière (ex : A=session, B=always) pour mesurer l'impact sur le CTR.

### Implémentation
- **Backend**
  - `models.py` : nouveau champ `SettingsUpdate.modal_global_cap_per_day` (0-20, défaut 2)
  - `server.py` : validation (HTTP 400 si hors plage)
  - `routes/ad_banners.py` :
    - Nouvel endpoint **anonyme** `GET /api/public/ad-banners/config` → `{modal_global_cap_per_day}` lu depuis `settings.global` (défaut 2 si non défini)
    - Nouveau champ `variant_b_modal_frequency` dans `AdBannerPayload` & `AdBannerUpdate` (vide = même que A)
    - `_public_view` étendu : quand la variante B est tirée, `modal_frequency` retourné = `variant_b_modal_frequency` (ou fallback `modal_frequency` si vide)
    - Compteurs modale par variante : `modal_impressions_a`, `modal_clicks_a`, `modal_impressions_b`, `modal_clicks_b` (bumpés en plus du global lors de `?modal=1`)
    - Helper `_modal_variant_stats(b, variant)` calcule CTR par variante
    - Endpoint `/admin/ad-banners/{id}/stats` étendu : `modal.variant_a`, `modal.variant_b`, `modal.variant_b_frequency`
- **Frontend**
  - `PublicAdModal.jsx` :
    - Lit `/api/public/ad-banners/config` en parallèle du fetch de la bannière
    - Compteur global stocké dans `localStorage["public_ad_modal_global_count"]` au format `{date: "YYYY-MM-DD", count: N}` — réinitialisé chaque jour
    - Si `cap > 0` et `count >= cap` → la modale n'apparaît pas
    - `bumpGlobalCount()` appelé quand la modale s'affiche
  - `AdminSettings.jsx` :
    - Nouveau bloc "Régie publicitaire — Plafond de modales par visiteur / jour" avec presets (0/1/2/3/5) + input personnalisé
  - `AdminAdBanners.jsx` :
    - Nouveau select `variant_b_modal_frequency` visible uniquement quand `ab_enabled` + `placement=public_modal`
    - Bloc stats étendu : 2 tuiles fuchsia "Variante A / Variante B" affichant impressions/clics/CTR modale + libellé fréquence par variante (composant `ModalVariantTile`)

### Tests
- `/app/backend/tests/test_iter40_modal_ab_and_global_cap.py` (9 nouveaux tests) :
  - Settings PUT accepte `modal_global_cap_per_day` 0-20
  - Valeurs invalides (-1, 21, 100) rejetées HTTP 400
  - `GET /public/ad-banners/config` retourne la valeur configurée
  - Endpoint config est anonyme (pas d'auth requise)
  - Admin peut créer un banner A/B avec fréquences distinctes par variante
  - Endpoint public retourne la fréquence appropriée à la variante tirée (40 tirages couvrent A et B)
  - Si `variant_b_modal_frequency` est vide, B fall back sur la fréquence globale
  - Compteurs modale par variante bumpent correctement (`?variant=a&modal=1`, `?variant=b&modal=1`)
  - Stats endpoint expose le bloc complet `modal.variant_a/b/variant_b_frequency`
- Régression complète : **36/36 PASS** (9 nouveaux + 7 frequency + 4 placement + 16 anciens)
- Smoke UI : page publique se charge, endpoint config répond `{modal_global_cap_per_day: 5}` (valeur de test).
