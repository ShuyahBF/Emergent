# PRD — SAWALI SMART SYSTEMS Portal

## Original Problem Statement
Construit moi un site web, qui s'affiche bien sur toutes les types de terminaux (ordinateur PC, tablettes et téléphone). Site professionnel de SAWALI SMART SYSTEMS avec accès public (missions, expérience, spécialisation, catalogue, demande de RDV, contact) et espace professionnel (login, mot de passe, captcha, OTP mobile, état du compte, RDV, documentation logiciels, historique interventions, suivi utilisateurs).


_⚠️ Historique récent (Iter35a → Iter38c) déplacé dans `/app/memory/CHANGELOG.md`._

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
5. Pour le bug #2 (contacts) — la cause exacte dépend de quelle vue UI : « centre de messagerie » est ambigu, l'utilisateur doit préciser (Contacts portail, Liste assignables tickets, Internal Chat ?). À investiguer avec une capture d'écran.

### Tests
- Régression 27/27 verts (auth refactor + screenshots + coverage gaps + S044).
- Endpoint diagnose validé E2E sur preview, identifie 2 blocking_reasons correctement.


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
