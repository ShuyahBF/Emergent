# PRD — SAWALI SMART SYSTEMS Portal

## Original Problem Statement
Construit moi un site web, qui s'affiche bien sur toutes les types de terminaux (ordinateur PC, tablettes et téléphone). Site professionnel de SAWALI SMART SYSTEMS avec accès public (missions, expérience, spécialisation, catalogue, demande de RDV, contact) et espace professionnel (login, mot de passe, captcha, OTP mobile, état du compte, RDV, documentation logiciels, historique interventions, suivi utilisateurs).

## Latest — Iter35x (2026-05-19) — Implémentation des 3 P2

### ✨ Iter35x — P2-1 : Versioning + email notif sur modif coffre-fort
- Collection `db.secret_change_audit` : `{id, key, action, actor_email, actor_id, ts, fingerprint (SHA-256 16 car.), is_secret}`. **Aucune valeur stockée.**
- Helper `_audit_secret_changes()` wired dans `admin_update_settings` → trace toute modif de clé incluse dans `VAULT_KEYS`.
- Email best-effort à `secret_audit_email_to` (toggle `secret_audit_email_enabled`) avec tableau HTML détaillant qui/quand/quelle clé/empreinte.
- Endpoint `GET /admin/secrets/change-audit?key=X&limit=N`.
- UI : section "Historique des modifications de clés" dans le Coffre-fort (filtre par clé + toggle email + tableau audit).

### ✨ Iter35x — P2-2 : Alexa Echo via Voice Monkey
- Settings : `alexa_enabled`, `alexa_webhook_url`, `alexa_events` (liste : sms_inbound, wa_inbound, appointment_due, support_load_critical).
- Helper `_alexa_notify(event_type, message)` + wrapper sync `_alexa_notify_async()` (fire-and-forget).
- Wired dans : WhatsApp webhook inbound, support load level >= 6 (POST + webhook), appointment reminder cron 24h.
- UI : section dédiée "Notifications vocales Alexa (Voice Monkey)" avec toggle, URL, 4 checkboxes événements, bouton "Tester l'annonce".
- `alexa_webhook_url` ajouté à `TESTABLE_URL_KEYS` (réutilise l'endpoint `/admin/settings/test-url`).

### ✨ Iter35x — P2-3 : Fix badge "Nouveau" disparition après 3 jours
- `NEW_WINDOW_DAYS` : 14 → **3** jours. Le badge disparaît automatiquement 3 jours après l'ajout, point.
- Ajout des sections récentes au registre `NEW_SECTIONS` (Alexa, Historique modifications clés).

✅ **Tests** : 14/14 verts (`test_iter35x_p2` + `test_iter35w_test_url` + `test_iter35t_welcome_daily_health` + `test_iter35s_sms_generic_routing`).

---

## Latest — Iter35r+s+t+u+v+w (2026-05-19) — Welcome Briefing + Bug critique SMS + URLs critiques

### ✨ Iter35w — Bouton "Tester" pour chaque URL critique
- Nouveau endpoint `POST /admin/settings/test-url` qui envoie un payload `{dry_run:true, source:"sawali-coffre-fort-test"}` à l'URL configurée (GET pour `public_base_url`, POST pour les webhooks).
- UI : bouton "Tester" à côté de chaque URL testable (6/7, `tracking_endpoint` omis), désactivé si la valeur n'a pas encore été enregistrée.
- Affiche : status HTTP, temps de réponse en ms, méthode, URL finale, réponse brute (expandable). Toast success/error.
- Tests pytest verts (3/3) — rejet clé inconnue, rejet clé vide, ping réel vers httpbin.org.

### ✨ Iter35v — Section "URLs critiques" dans le Coffre-fort
- Toutes les URLs sortantes critiques (public_base_url, tracking_base_url, tracking_endpoint, webhook_base_url, notes_webhook_url, health_webhook_url, n8n_webhook_url) regroupées dans une mini-section éditable du panneau Coffre-fort.
- 7 champs avec validation (http(s):// pour les URLs, / pour les paths), bouton "Enregistrer" individuel par champ, badge "✓ Renseigné" pour les valeurs présentes, chevron pour replier/déplier.
- Compteur visuel `N/7` dans l'entête (5/7 actuellement).

### ✨ Iter35u — `public_base_url` éditable depuis le Coffre-fort
- DB-backed override de `PUBLIC_BASE_URL` env var. Hot-reload de la cache après chaque PUT `/admin/settings`.
- Valeur production `https://sawalismartsystems.com` enregistrée.
- Ajouté à `VAULT_KEYS` → inclus dans les exports/imports chiffrés.

### ✨ Iter35t — Mini-dashboard "Santé quotidienne" dans WelcomeBriefing
- Endpoint `/me/welcome-briefing` enrichi du bloc `daily_health` : `tickets_resolved_yesterday`, `tickets_opened_today`, `wa_response_rate_24h` (avec wa_inbound/outbound 24h), `messages_sent_today`.
- UI : 4 tuiles colorées (Tickets clos hier, Ouverts aujourd'hui, % Réponse WA 24h, Messages envoyés) avec code couleur dynamique selon performance (>=80% emerald, >=50% amber, <50% rose).
- 2 tests pytest (`test_iter35t_welcome_daily_health.py`) verts → bloc présent + schéma + `wa_response_rate_24h=None` quand aucun inbound.

### ✨ Iter35r — Welcome Briefing modal intégrée
- `WelcomeBriefing.jsx` désormais affichée 1× par session après login (`PortalLayout` enveloppe la modale en lecture conditionnelle via `sessionStorage`).
- Affiche : tickets ouverts/suspendus, WA+SMS non lus, notes personnelles récentes (fenêtre paramétrable, défaut 3 jours).
- Auto-dismiss silencieux si tout est vide → zéro friction.
- Test screenshot validé avec injection ticket de test → modale rendue correctement.

### 🐛 Iter35s — Bug critique `_sms_send_generic` manquante (P0)
- **Root cause** : le `async def _sms_send_generic(...)` avait été accidentellement supprimé (probablement par un `search_replace` raté), transformant tout le corps de la fonction en code mort à l'intérieur de `_sms_send_via_webhook`. Résultat : `NameError` à l'exécution sur **tout** envoi SMS via Orange/Moov/Telecel (y compris via webhook n8n).
- **Fix** : restauration de la signature `async def _sms_send_generic(cfg, msisdn, message, sender)` + maintenance de la routing logic (orange_oauth, webhook, générique HTTP).
- L'URL du webhook custom n8n est désormais utilisée **brute** (aucun suffixe ajouté).
- Tests : `test_iter35s_sms_generic_routing.py` (3/3 verts) + `test_iter35k_sms_webhook.py` (4/4 verts) = **7/7**.

---

## Latest — Iter35f+g+h (2026-05-15) — Batches 1+2+3 (60/60 tests verts)

### 🐛 Iter35f — Batch 1 : 4 bugs production fixés
- Édition contact RGPD : ne sauvegarde plus les valeurs masquées (`**`) → ne clobber plus la vraie valeur
- Email admin client : `UserUpdateAdmin` accepte enfin `email` (lowercase + unique check + 409 sur conflit)
- Fenêtre 24h WhatsApp : `_wa_last_inbound_iso` accepte liste de client_ids (élargi via `_resolve_visible_client_ids`)
- Bulk WhatsApp "0 envoyé" : scope élargi + fail-fast 404 si aucun contact résolu

### ✨ Iter35g — Batch 2 : Transferts multi-utilisateurs + Notes/Tâches personnels
- `POST /admin/tracked-users/bulk-transfer` : transfère jusqu'à 200 tracked users vers un autre client en une opération, persiste l'historique dans `db.tracked_user_transfers`
- UI : checkboxes par ligne + dropdown sticky + bouton "Transférer la sélection"
- Nouveaux kinds `notes` & `tasks` dans `/me/notes/{kind}` (mêmes endpoints que reports/suivis → voix + Whisper inclus)
- 4 tuiles dashboard : Rapports / Suivis / Notes / Tâches
- `client_notes` / `client_tasks` (admin per-client) gagnent aussi `voice_note_url` + `voice_note_transcript`
- Préfixe NTE-xxxx pour Notes, TSK-xxxx pour Tâches
- Snapshot collections étendues

### 🎯 Iter35h — Batch 3 : Rôle `demo` complet
- Nouveau rôle `demo` (USER_ROLES) avec quotas par défaut : WA 2 / SMS 1 / IA 1 / Whisper 2 / Contacts 5 / Paiements 0 / Stockage 5 Mo / expire 14 jours
- Helper `_enforce_demo_quota(user, key, increment)` — atomique, raise 403 explicite si quota dépassé
- Wired sur 7 endpoints : `/me/whatsapp/send-text`, `/me/whatsapp/bulk`, `/me/sms/send`, `/transcribe`, `/me/ai/summarize`, `/me/contacts`, `/me/payment-links`, `/me/upload`
- Compte expiré → `account_status="expired"` + log dans `db.demo_expiry_events` + 403 sur chaque appel API
- Nouveau endpoint `GET /me/demo/status` : countdown jours + jauges de tous les quotas (utilisé par la bannière)
- Nouveau composant frontend `DemoBanner.jsx` collé en haut du portail (PortalLayout) — countdown + gauges expandables, refresh 60 s
- Admin Clients : pill filtre `Démos` ajoutée + form étendu (date d'expiration + 7 inputs quotas) quand role=demo sélectionné
- Endpoints admin pour gérer les expirations : `GET /admin/demo/expiry-events`, `POST /admin/demo/expiry-events/{id}/resolve`

✅ **Tests** : 24 nouveaux (7 iter35f + 10 iter35g + 7 iter35h) + 36 régressions = **60/60 verts**

🚨 **Save to GitHub requis** pour déployer en production.

---



🟢 **Nouvelle fonctionnalité majeure** :
- **Export chiffré** des tokens API + paramètres associés via `POST /api/admin/secrets/export` (body `{password, comment}`) — AES-256-GCM + PBKDF2-HMAC-SHA256 (200 000 itérations), salt + nonce aléatoires, ciphertext base64. Le fichier JSON téléchargé est **inutilisable sans le mot de passe**.
- **Restauration** via `POST /api/admin/secrets/import` (file + password + dry_run + overwrite_filled). Le mode **dry-run** liste ce qui serait restauré sans rien modifier. Le mode `overwrite_filled=false` (défaut) ne touche pas aux clés déjà renseignées (protection contre l'écrasement involontaire d'un token fraîchement saisi).
- **Liste des clés** via `GET /api/admin/secrets/keys` — retourne le statut populé/vide de chaque clé du coffre (sans révéler les valeurs).
- **Audit trail** via `GET /api/admin/secrets/audit` — chaque export/import est journalisé (acteur, date, nb clés, **jamais** le mot de passe).
- **49 clés vaultables** : tous les tokens secrets (`SENSITIVE_SETTINGS_KEYS`) + les IDs non-secrets pénibles à ressaisir (WABA ID, SMTP host, Google client_id, URLs des webhooks, méthodes/auth_type SMS, environment PawaPay, modèles OpenAI, etc.).
- **UI Admin Settings** : nouveau panneau "Coffre-fort des secrets (Iter35e)" en haut, juste après "Sauvegarde DB". Permet :
  - Vue d'ensemble (clés renseignées/vides/total) avec détail expandable
  - Création d'un coffre (champ + confirmation mot de passe + commentaire, téléchargement direct)
  - Restauration (sélection fichier + mot de passe + dry-run + écraser-ou-non + résultat détaillé par clé)
  - Journal d'activité expandable
- **Tests** : `backend/tests/test_iter35e_secrets_vault.py` — 11/11 verts (RBAC, roundtrip, mauvais mot de passe, format corrompu, audit, etc.).



## Iter35c (2026-05-13) — Snapshot import recap (email + WhatsApp)
  - **📧 Email récapitulatif** au destinataire configuré (`auto_snapshot_email_to` ou `health_email_to` ou super-admin) avec un tableau HTML détaillant chaque collection impactée (avant/après/entrants/action), surligné en vert si OK, orange si erreurs.
  - **💬 WhatsApp** (best-effort) à chaque numéro admin déclaré dans `liluvine_remote_admin_phones` (jusqu'à 5), via `_wa_send_text` — fonctionne uniquement dans la fenêtre 24h de service client de Meta.
- **Toast frontend** plus riche : indique le nombre de collections impactées, statut email, statut WhatsApp.
- **Bannière de confirmation prominente** sous le bouton d'import : couleur verte (succès), ambre (erreurs partielles), rose (échec). Chaque statut de notification (email/WA) affiché avec destinataire et erreur éventuelle.
- **Réponse API enrichie** : `{ok, dry_run, mode, summary, import_id, notifications: {email, whatsapp, has_error, rows_count}}`.
- **Tests** : `backend/tests/test_iter35c_import_recap.py` (3/3 verts).

## Iter35b (2026-05-13) — WhatsApp silence detector

🟢 **Nouvelle alerte automatique** :
- Cron `_run_wa_silence_check` lancé toutes les 4 h (Africa/Abidjan, minute 20).
- Compare le nombre de messages WhatsApp **sortants** (24 h glissantes par défaut) au nombre de webhooks Meta reçus.
- Si outbound ≥ seuil ET webhooks reçus = 0 → envoie un email + Discord (optionnel) à l'admin pour le prévenir.
- Throttle : une seule alerte par fenêtre pour éviter le spam (`wa_silence_alert_last_fired_at`).
- Audit trail dans `db.wa_silence_alerts`.
- **Endpoints admin** : `POST /api/admin/whatsapp/silence-check` (manuel), `GET /api/admin/whatsapp/silence-alerts` (historique).
- **UI** : Admin Settings → WhatsApp → "Détecteur de silence WhatsApp" (Iter35b). Toggle, seuil, fenêtre, email, webhook Discord, bouton de test manuel, historique.
- **Tests** : `backend/tests/test_iter35b_wa_silence.py` (4 tests verts).

## Iter35a (2026-05-13) — 3 P0 production bug fixes

🔴 **Fixed (production-impacting)** :
- **Snapshot Import** (`POST /api/admin/snapshots/import`) :
  - Now preserves `settings._id="global"` singleton anchor in REPLACE mode (was wiping it → all subsequent settings lookups returned None, breaking WhatsApp/SMTP/payment config).
  - Partial snapshots no longer cascade-wipe unrelated collections (only acts on collections actually present in the payload).
  - Per-collection try/except surfaces `action: "error"` with reason instead of HTTP 500.
  - `insert_many(ordered=False)` + chunked batches of 500 → resilient against duplicate-key & validation errors.
- **WhatsApp Webhook** (`POST /api/whatsapp/webhook`) :
  - Persists EVERY hit (raw payload + extraction summary) to `db.wa_webhook_logs` (capped to 200 entries).
  - Handles `button`, `interactive`, `reaction`, `location`, `contacts` message types explicitly (was missing reaction/location/contacts).
  - Status updates match by both `wa_message_id` and legacy `message_id`; unmatched statuses go to `wa_pending_statuses` for later reconciliation.
  - New admin endpoints: `GET /api/admin/whatsapp/webhook-logs?limit=N` + `DELETE /api/admin/whatsapp/webhook-logs`.
  - New UI panel in Admin Settings → WhatsApp section: "Inspecter les payloads Meta entrants" (collapsible, JSON-pretty, error-highlighted).
- **Scheduled WhatsApp sends** (`_run_scheduled_whatsapp`) :
  - `result_summary.error` now surfaces a human-readable reason when sent_ok=0 (was silent "failed").
  - Top-level scheduler crash now releases stuck `running` schedules back to `failed` with the error.

✅ **Tests**: `backend/tests/test_iter35a_critical_bugs.py` — 6 new tests, all pass. Existing `test_iter34_snapshots.py` (12 tests) still passes.

🚨 **Production deployment required** : Click "Save to GitHub" in this conversation to push these fixes to your live site.

---

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

### 🟧 P0 — Refactor `server.py`
- Découpage en `/app/backend/routes/` : `auth.py`, `admin.py`, `me.py`, `public.py`, `webhooks.py`, `payments.py`, `sms.py`, `whatsapp.py`, `dashboard.py`, `formations.py`…
- Actuellement >10 300 lignes — devient critique pour maintenabilité.

### 🟦 Future
- **🔔 Versioning + Notification email à chaque modification de secret (P2)** — Plutôt qu'un rappel mensuel, déclencher à chaque création/modification d'un secret API : (a) email à l'admin avec qui/quand/quelle clé (jamais la valeur), (b) versioning des secrets (rollback possible vers une version précédente). À combiner avec le coffre-fort iter35e.
- **🔊 Notifications vocales Alexa Echo — Option 1 Voice Monkey (P2)** — Ajouter dans Admin Settings un bloc "Notifications vocales Alexa Echo" : toggle + URL webhook Voice Monkey + checkboxes des événements déclencheurs (SMS reçu, WhatsApp reçu, RDV imminent, niveau support critique). Quand un événement choisi survient, faire un `POST` vers le webhook Voice Monkey → Alexa joue un son + énonce le message. Travail estimé : ~2-3 h. Coût : 0 €/5 €/mois selon volume.
- **🔊 Notifications vocales Alexa Echo — Option 3 Home Assistant (P3, après Option 1)** — Évolution de l'option ci-dessus : remplacer Voice Monkey par une instance Home Assistant locale (intégration `alexa_media_player`). Plus puissant et sans dépendance tierce, mais nécessite que le client ait HA déployé chez lui (Raspberry Pi). Le champ admin devient "URL Home Assistant + token long-lived".
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

## CHANGELOG

### 2026-05-13 — Itération 34z : Transcription automatique des notes vocales (Whisper)
✅ Le composant `VoiceNoteRecorder` appelle automatiquement `/transcribe` (Whisper) après chaque upload réussi. Textarea éditable affichée sous le lecteur audio + bouton "Re-transcrire" (réutilise le blob en mémoire). Le texte est sauvegardé dans `voice_note_transcript` (nouveau champ ajouté à `InterventionCreate/Update` + `UserNoteCreate/Update`). Toast Info dégradé si OpenAI non configuré (HTTP 503) — la note vocale est conservée même sans transcription. Sur la liste des interventions, le transcript est affiché en italique sous le player (line-clamp-2 + tooltip pour voir le texte complet).

### 2026-05-13 — Itération 34y : Toasts élargis + Interventions (Client lié + note vocale) + Filtres Suivis
✅ **Activity feed élargi** : `_log_activity` désormais wired sur `appointments` (création), `interventions` (création + suppression), `payment_links` (création). 3 nouveaux libellés FR dans `useActivityFeedNotifier.js` (Rendez-vous, Intervention, Paiement) → toasts live multi-utilisateurs.
✅ **Page Interventions refondue** : (1) en-tête de colonne **Client lié** avec dropdown filtre + compteurs par client. (2) Colonne dédiée **Note vocale** avec lecteur audio inline. (3) Modal de création avec **select Client lié** (chargé depuis `/me/clients`) + composant `VoiceNoteRecorder` (MediaRecorder → `/me/upload` → URL renvoyée dans `voice_note_url`). Modèles `InterventionCreate/Update` enrichis du champ `voice_note_url`.
✅ **Suivis** : nouveau **select "Tous les clients liés"** dans la barre de filtre des suivis avec compteurs par client. `useMemo` filtre l'affichage instantanément.
✅ Modèles `UserNoteCreate/Update` enrichis de `voice_note_url` (note vocale facultative déjà supportée par les suivis via transcription).
✅ Tests 31/31 maintenus verts.

### 2026-05-12 — Itération 34t-x : 6 demandes utilisateur (Anonymisation contenus, Exports, Toasts live, Anti-doublon formulaires)
✅ **#1 Anonymisation contenus** : 3 nouveaux flags `anon_rapports`, `anon_suivis`, `anon_communications` ajoutés à `DEFAULT_CLIENT_FEATURES`. Helper `_resolve_content_restrictions()` + enforcement sur `me_list_notes` (rapports/suivis), `me_contact_messages` (WhatsApp), `me_sms_messages`. Quand activé → seuls le créateur et les admins/superviseurs voient le contenu. UI : 3 toggles bleus dans SMART Communications avec descriptions claires.
✅ **#2 Code unique en bleu** : `text-sky-600 font-bold` sur les codes 2026-SAWALISM-XXXX dans le Centre de Messagerie.
✅ **#3 Export contacts** : 3 nouveaux endpoints `/me/contacts/export.csv` (avec BOM UTF-8 pour Excel), `.json`, `.pdf` (ReportLab landscape A4 avec en-tête SAWALI bleu). Dropdown UI dans Contacts.jsx avec téléchargement direct via Blob.
✅ **#4 Toasts temps réel** : collection `activity_events` + endpoint `/me/recent-activity?since=...`. Helper `_log_activity()` wiré sur 7 mutations critiques (contact create/update/delete, note create/update/delete, SMS sent, WA sent, WA received). Hook frontend `useActivityFeedNotifier.js` polle toutes les 8s, affiche un toast Sonner par event (avec icône d'action), suppress les actions du viewer lui-même. Cursor persisté en sessionStorage.
✅ **#5 Tableau des soumissions** : endpoint `/me/forms/{form_id}/submissions-table` + composant `SubmissionsTable` dans FormAnalyticsDetail.jsx avec tableau brut, en-tête sticky, hover sky, troncature `max-w-[220px]`.
✅ **#6 Anti-doublon formulaires** : check 409 en cas de titre déjà utilisé (case-insensitive) sur POST et PUT. Endpoint `/me/forms/title-suggestions` + modal de création avec `<datalist>` autocomplete + détection live du conflit (bordure rose + bouton désactivé).
✅ **Tests** : 31/31 iter34 verts. Roadmap `ACT-0032`.

### 2026-05-11 — Itération 34s : Raccourci SMART Communications dans 'Mon compte' + titres bleus groupes Clients
✅ `/portal/my-account` : nouvelle carte cliquable **SMART Communications** (visible uniquement pour `admin`/`superviseur`) avec gradient fuchsia/sky, icône ShieldCheck, badge "ADMIN", flèche → mène vers `/admin/clients/{user.id}/features`. Permet à l'admin SAWALI de paramétrer ses propres flags RGPD/WA/SMS/IA/paiements depuis sa fiche personnelle. Ces réglages sont **hérités par tous ses utilisateurs liés** (logique de résolution `parent_client_id` livrée en iter34p).
✅ `/admin/clients` : les en-têtes des groupes (ADMINS CLIENTS, CLIENTS, MODÉRATEURS, etc.) passent en `text-sawali-blue` avec gradient `from-sky-100/80 via-sky-50/60 to-transparent` — beaucoup plus visibles que le slate précédent.

### 2026-05-11 — Itération 34r : Filtres rapides "Partagés/Privés/Non-lus" au Centre de Messagerie
✅ 4 pills cliquables (Tous / Partagés équipe / Privés / Non-lus) au-dessus du tableau de contacts avec compteurs vivants. Compteurs respectent les autres filtres (recherche texte + société). Couleurs slate/emerald/amber/rose, état actif fort, inactif subtil avec hover coloré. Toggle 100% client-side via useMemo.

### 2026-05-11 — Itération 34q : Filtres rapides par rôle dans le module Clients
✅ Pills cliquables au-dessus du tableau (Tous / Admins clients / Superviseurs / Clients / Modérateurs / Autres) avec compteurs en direct. Pills colorées par rôle (sky/amber/fuchsia/slate) avec état actif distinct. Empty-state contextualisé quand filtre vide.
✅ Implémenté via `useMemo` + `roleFilter` state, sans appel réseau supplémentaire. Toggle instantané.

### 2026-05-11 — Itération 34p : Visibilité cross-scope + Héritage RGPD + UI Centre Messagerie/Clients
✅ **Bug critique #6** : "Contact introuvable" au clic sur l'historique. Cause : `/me/contacts/{cid}/messages` et 3 autres endpoints filtraient sur `client_id=client_scope` exclusivement, sans utiliser `_resolve_visible_client_ids`. Fix : 4 endpoints désormais sur la résolution visible-scope (`me/contacts/{cid}/messages`, `mark-read`, `me/whatsapp/unread`, `me/sms/messages`). Plus jamais de 404 après une migration/réalignement.
✅ **Bug #3 Héritage RGPD** : `/me/features` et `_resolve_anon_flags` utilisent désormais `parent_client_id → client_id → id` (au lieu de `client_id → id`). Les flags anon_* du Client lié sont correctement hérités pour tous les utilisateurs enfants.
✅ **UI Centre de Messagerie** : header affiche maintenant Société (pill bleu sky) + Client lié (pill emerald) à côté du titre. Colonne email rétrécie à 140px (le bouton Historique s'affiche). Numéros de téléphone & WhatsApp en `text-sky-600`. Hover highlight (`hover:bg-sky-50` + ring) sur lignes contacts et bulles de messages.
✅ **Module Clients** : `GET /admin/clients` inclut désormais `admin + moderateur` (sauf l'admin seed SAWALI). UI groupée par rôle avec en-têtes colorés (Admins / Superviseurs / Clients / Modérateurs). Hover highlight sur lignes.
✅ **Tests** : 3 nouveaux tests (`test_iter34p_visibility_rgpd.py`) — admin/clients roles, cross-scope messages, RGPD inheritance via JWT forge. **31/31 tests iter34 verts**.
✅ **Roadmap** : `ACT-0028` seedée.

### 2026-05-11 — Itération 34o : Bug fix critique — Retag trop large (post-déploiement rabo.f)
🚨 **Cause racine identifiée en production** : après le réalignement de rabo.f, **tous** les contacts/messages WA/SMS de Clinique CMCO ont été migrés vers SAWALI (pas seulement ceux de rabo.f). Le code retaguait `directory_contacts WHERE client_id=CMCO_id → SAWALI_id` sans filtre d'appartenance.
✅ **Fix prospectif** : le retag filtre désormais par `owner_id/sender_id/created_by/author_id/user_id == user.id`. Seules les rows démontrablement appartenant à l'utilisateur réaligné bougent. Les contacts des autres utilisateurs de la même société source restent intacts.
✅ **Fix rétroactif** : nouvel endpoint `POST /admin/contacts/revert-retag` qui restaure `client_id ← client_id_legacy` sur toutes les collections (idempotent, dry-run par défaut, filtres `from_client_id`/`to_client_id`/`collections`). Restaure également `users.parent_client_id_legacy`.
✅ **UI** : nouvelle section "Restauration des contacts/messages (revert retag)" dans `/admin/settings` avec checkboxes par collection + aperçu obligatoire avant application + confirm modal.
✅ **Bonus UX chat** : la fenêtre de conversation WhatsApp dans `/portal/contacts` auto-scrolle désormais sur le dernier message (initial `auto`, mises à jour `smooth`), comme dans WhatsApp/Messenger.
✅ **Tests** : 4 nouveaux tests pytest (`test_iter34o_revert_retag.py`) + tests iter34m mis à jour pour `owner_id` ; **16/16 verts**.
✅ **Roadmap** : `ACT-0027` seedée.
ℹ️ **Action requise en production** :
   1. Déployer cette correction (Save to GitHub).
   2. `/admin/settings` → "Restauration des contacts/messages" → cocher au moins `directory_contacts` et `whatsapp_messages` → "Aperçu (dry-run)" → vérifier le total → "Appliquer la restauration".
   3. Recommencer le réalignement de rabo.f si nécessaire (la nouvelle version ne touchera que ses propres contacts).

### 2026-05-11 — Itération 34n : Garde-fou automatique sur changement de `company`
✅ **PUT /admin/clients/{id}** : quand l'admin modifie le champ `company` d'un utilisateur, le backend déclenche automatiquement la même logique que `/admin/realign-user-to-client` (relink_parent + retag rows + set client_id). Empêche définitivement la réapparition de la classe de bugs rabo.f.
✅ Le payload de réponse expose maintenant :
   - `auto_realign: {applied: true, to_company, to_canonical_id, actions_count}` quand le système a auto-corrigé,
   - `auto_realign: {applied: false, reason: 'no_canonical_for_company', typed_company}` quand la société typée ne matche aucun admin/primaire (typo probable),
   - `auto_realign: null` quand rien à faire.
✅ Frontend `AdminClients.jsx` : toast vert "Pointeur parent recalibré automatiquement…" ou toast warning "Société sans canonique" pendant 7-9s.
✅ Tests : `test_iter34n_company_guard.py` (3/3 verts) — auto-fix complet, détection typo, no-op si autre champ.
✅ Roadmap : `ACT-0026` seedée.

### 2026-05-11 — Itération 34m : Bug fix — Détection du pointeur `parent_client_id` périmé
✅ **Cas réel signalé** : `rabo.f@sawalismartsystems.com` affichait dans sa page **Mon compte** un "Client lié = Clinique CMCO", alors que dans la liste admin des clients il apparaissait sous "SAWALI SMART SYSTEMS". L'admin avait modifié son champ `company` mais le pointeur `parent_client_id` continuait de viser le client CMCO.
✅ **Root cause** : le diagnostic `/admin/client-data-diagnostic` faisait confiance au `parent_client_id` comme source canonique, donc il déclarait "Aucun désalignement détecté" même quand la société typée différait de la société du parent. L'admin ne pouvait pas réaligner.
✅ **Fix backend** :
   - Cross-check de la société du parent canonique vs la société typée du user (case-insensitive, trim).
   - Si mismatch ET un admin/superviseur (ou client primaire) porte exactement la société typée → bascule du canonique vers ce dernier, nouvelle action `relink_parent` ajoutée au plan.
   - Si mismatch mais pas de canonique trouvé → flag `parent_company_mismatch` exposé (UI affiche un message pour corriger l'orthographe ou désigner un client primaire).
   - `POST /admin/realign-user-to-client` applique `relink_parent` (set `parent_client_id`+`client_id` au nouveau canonique, conservation legacy).
✅ **Fix frontend** : `ClientDataDiagnosticSection` affiche un encart rose "Pointeur parent périmé détecté" + ligne dédiée pour `relink_parent` dans le plan de réalignement.
✅ **Tests** : `test_iter34m_stale_parent.py` reproduit le scénario rabo.f en BDD (CMCO + SAWALI + child user stale) et valide diagnostic+repair. 2/2 verts.
✅ **Roadmap** : `ACT-0025` seedée. Version auto-bumpée à 1.23.
ℹ️ **Action requise en production** : déployer cette correction (Save to GitHub), puis dans `/admin/settings` → "Diagnostic visibilité par utilisateur", entrer `rabo.f@sawalismartsystems.com`, vérifier l'alerte rose, et cliquer "Appliquer le réalignement".

### 2026-05-11 — Itération 34l : Admin UI — Demandes de modification de profil
✅ **Backend (server.py + 60 lignes)** :
   - `GET /api/admin/profile-requests?status=pending|processed|all` (liste + `pending_count`)
   - `PATCH /api/admin/profile-requests/{id}` : `status` (pending|processed) + `admin_note` (≤2000). Auto-rempli `resolved_at` & `resolved_by_email` quand traitée.
   - Compteur `admin_profile_requests` ajouté à `/me/notifications/counts` (admin only, basé sur `status=pending`).
✅ **Frontend** :
   - Nouvelle section `ProfileRequestsSection` dans `AdminSettings.jsx` (border rose, badge "X en attente" pulsé, 3 onglets de filtre, refresh, lignes expandables avec champs ciblés en chips, message complet, textarea note interne, boutons "Marquer comme traitée" / "Enregistrer la note" / "Rouvrir").
   - Badge rouge `admin_profile_requests` ajouté au lien sidebar **Paramètres** (`noMarkSeen: true` — clear uniquement quand une demande est traitée).
   - Title bubble "• NOUVEAU" pour 14 jours.
✅ **Tests** : `backend/tests/test_iter34l_profile_requests.py` (7/7 passants) — list/filter, mark processed + note + reopen, badge count, 400 (status invalide / note >2000), 404 (id inexistant).
✅ **Roadmap** : entrée `ACT-0024` ajoutée au seed `ROADMAP_SEED`. Version auto-bumpée à 1.22.

### 2026-05-09 — Itération 54 : Audit RGPD Preview + Filtre par Client dans SMS Bulk
✅ **Endpoint `GET /admin/rgpd-preview/{client_id}`** : retourne 5 échantillons de chaque collection anonymisable (contacts, appointments, interventions, documents) avec le couple `{original, masked}` côte à côte. Utilise les flags actuels du parent client. Permet à l'admin d'auditer la configuration RGPD avant de déployer en production.
✅ **Page `/admin/clients/:client_id/rgpd-preview`** : panneau "Audit RGPD" avec :
   - Bandeau rose listant les 4 flags actifs (Eye/EyeOff icons, "Anonymisé" / "Visible")
   - Si aucun flag : bandeau ambre invitant à activer depuis Fonctionnalités
   - 4 sections (Contacts, Rendez-vous, Interventions, Documents) avec table comparative double-ligne par enregistrement : ligne verte "Admin (clair)" + ligne rose "Utilisateur (anonyme)". Les cellules différentes sont surlignées en rose pour mise en évidence.
   - Bouton "Audit RGPD" rose ajouté à côté de "Enregistrer" dans `AdminClientFeatures`.
✅ **Filtre par Client dans `SmsBulk.jsx`** : nouveau dropdown "Tous les clients" + bouton "✕ Effacer" qui filtre la liste des destinataires par `c.company`. Les options listent le roster admin (`/me/clients-roster`) en priorité, complétées par les sociétés ad-hoc présentes dans les contacts (mémoïsé pour ne pas re-calculer à chaque caractère tapé).
✅ Note : la page Centre de Messagerie (`Contacts.jsx`) avait déjà ce filtre. Aucune page WhatsApp Bulk distincte n'existe — le multi-envoi WA passe par les schedules per-contact (Mess. Program. dans Contacts.jsx).
✅ Tests curl : `/admin/rgpd-preview/{me}` retourne 3 contacts avec original/masked corrects (Jean Dupont → J*** D***, +22507123456 → +22 ** ** ** 56). Validation Playwright : SmsBulk affiche bien le dropdown "Tous les clients".

### 2026-05-09 — Itération 53 : RGPD anonymisation étendue (Rendez-vous, Interventions, Documents)
✅ **5 nouveaux helpers backend** : `_apply_anon_to_appointment`, `_apply_anon_to_intervention`, `_apply_anon_to_document`, `_apply_anon_to_access_log`, et un wrapper générique `_maybe_anon_list(viewer, items, applier)` qui no-op si aucun flag n'est ON.
✅ **Endpoints couverts** :
   - `GET /me/appointments` : anonymise `name`, `email`, `phone`, `company` du client RDV.
   - `GET /me/interventions` : anonymise le `technician`.
   - `GET /me/documents` : anonymise `uploaded_by_email/name`, `client_name`.
✅ **Logs admin** : `/admin/access-logs` est restreint à `admin/superviseur` (rôles privilégiés) → l'anonymisation serait un no-op par construction. Conservé tel quel.
✅ Tests curl : tracker (utilisateur) voit RDV `J*** S*** T*** / j***@test.com / +22 ** ** ** 11 / A*** C***` et intervention technician `P*** D***`. Admin voit tout en clair sur les mêmes endpoints.

### 2026-05-09 — Itération 52 : PawaPay auto sur souscription + Web Notifications WA + Stats SMS + ErrorBoundary global
✅ **PawaPay auto-link sur souscription publique** : `POST /public/subscriptions/order` crée désormais un `payment_links` avec slug aléatoire, montant pré-rempli, `prefill_phone`, `prefill_name`, expire à J+7, max 1 utilisation. Le lien est attaché à l'order et retourné dans la réponse. Le modal frontend affiche un encart vert "Régler maintenant via Mobile Money" → `/pay/{slug}` (ouvre dans un nouvel onglet). Activé seulement si `pawapay_enabled=true` dans les settings + montant > 0. Fallback sur le premier admin si aucun superviseur configuré.
✅ **Web Notifications API + son sur nouveaux WA** : nouveau hook `useWhatsAppNotifier` qui poll `/me/whatsapp/unread` toutes les 15s, joue un blip 880 Hz → 1320 Hz (Web Audio, sans asset), affiche une notification desktop si le compteur croît ET si l'onglet est en arrière-plan, et badge le favicon avec un point rouge. Toggles persistés dans localStorage : `sound_on` (par défaut ON) et `desktop_on` (par défaut ON). Bouton "Autoriser les notifications" si la permission est `default`. Click sur la notif → focus tab + redirection vers `/portal/contacts`.
✅ **UI sidebar PortalLayout** : nouveau bloc "🔔 Alerte WhatsApp" dans le footer de la sidebar avec badge unread + 2 toggles (Notif + Son).
✅ **Stats SMS dans `/admin/usage`** :
   - Backend : `admin_usage_summary` agrège désormais `sms_messages` par client × fournisseur (`sent_ok`, `sent_ko`, `total`). Ajoute aux totaux : `sms_sent_ok/ko/total/cost`. Nouvelle clé top-level `sms_by_provider`. Daily series étendue de 2 → 3 séries (`wa`, `ai`, `sms`).
   - Frontend : 4 KPIs (WA env., WA reçus, **SMS envoyés**, **Coût total estimé**), nouvelle section "Répartition SMS par fournisseur" en grid 4 cards (avec ratio succès), 3 colonnes ajoutées au tableau par client (SMS ✓, Coût SMS, IA), CSV export enrichi de 5 colonnes SMS. Graph stacked WhatsApp + SMS + IA.
✅ **ErrorBoundary global** : `<ErrorBoundary resetKey={location.pathname}>` enveloppe désormais le `<Outlet />` du `PortalLayout` (couvre toutes les routes `/portal/*` et `/admin/*` sans exception). Reset auto à la navigation grâce à `componentDidUpdate(prevProps)` — un crash sur `/portal/payments` ne bloque plus l'app entière. Bouton "Réessayer" pour rejouer le rendu sans recharger. Suppression des wrappers redondants dans `App.js`.
✅ Tests curl : `/admin/usage/summary` retourne désormais sms_sent_ok/ko/cost/total, sms_by_provider {ORANGE,...}, daily_series avec clé `sms`. `/public/subscriptions/order` retourne `payment_link_url:/pay/{slug}` quand pawapay_enabled.

### 2026-05-09 — Itération 51 : Bug SMS fix + WhatsApp Profile Sync + Module Abonnements + RGPD anonymisation
✅ **Bug SMS résolu** : `_sms_send_generic` et `_sms_send_ovh` retournaient un dict dans `api_message` quand `resp.get("message")` était lui-même un objet (Orange/Moov/Telecel parfois). Frontend rendait directement `result.error` → crash React → page blanche identique à PawaPay. Fix double couche :
   - **Backend** : nouveau helper `_safe_text(field, max_len=300)` qui coerce dict/list en string. Appliqué aux 3 retours `api_message` SMS + au champ `error` final de `me_sms_send`.
   - **Frontend** : helper `safeText()` dans `Contacts.jsx` et `SmsBulk.jsx`, utilisé sur `result.error/.provider/.http_status` + tous les `toast.error(err?.response?.data?.detail)`.
✅ **WhatsApp Profile Sync** :
   - Webhook `/whatsapp/webhook` lit désormais `entry[].changes[].value.contacts[].profile.name` et le stocke (`from_profile_name` sur le message + `wa_profile_name` sur le contact).
   - Nouveau bouton vert **« Synchro WA »** dans le modal Modifier le contact → `POST /me/contacts/{cid}/wa-sync` lit le dernier inbound stocké et propose le nom (avec confirmation avant écrasement).
   - Auto-import sur première réception : numéros inconnus accumulés dans `wa_pending_imports`, exposés via `GET /me/wa-pending-imports`. Bandeau ambre `<PendingImportsBanner>` en haut de la page Contacts → bouton 1-clic "Importer" qui crée le contact + rattache les messages passés. Bouton "Ignorer" supprime l'entrée.
   - **Limitation Meta documentée** : photo de profil et statut/about ne sont PAS exposés par Cloud API → upload manuel reste la seule voie.
✅ **Module Abonnements** (remplace Blog en navigation publique, Blog admin reste accessible) :
   - 3 collections Mongo : `subscription_categories` (4 max, label/color/position/animated), `subscription_plans` (auto-code FMLYYYYNNNN, prix mensuel + annuel, featured, automation_url, whatsapp_notify_to), `subscription_orders` (leads publics).
   - Helper `_next_subscription_code()` génère séquence par année.
   - 11 endpoints : 5 CRUD admin catégories + 5 CRUD admin plans + 1 admin orders + 2 publics (`GET /public/subscriptions` filtre les champs sensibles, `POST /public/subscriptions/order` valide → notifie WhatsApp + hit webhook automation).
   - **Pages frontend** : `/admin/subscriptions` (3 onglets : Formules, Catégories, Souscriptions, modals édition complets), `/subscriptions` publique (toggle Mensuel/Annuel avec économie calculée, filtres par catégorie, animations CSS hover scale-1.025 si `cat.animated=true`, badge "★ Recommandée" pour `featured`, modal souscription → `submit` → confirmation 24h).
   - Nav publique : `/blog` → `/subscriptions` dans `MarketingNav` + `MarketingFooter`. Blog admin & blog routes publiques préservés.
✅ **RGPD anonymisation par-client** :
   - 4 nouveaux flags : `anon_name`, `anon_email`, `anon_phone`, `anon_whatsapp` ajoutés à `DEFAULT_CLIENT_FEATURES`.
   - Helpers backend `_anon_name` (`J*** D***`), `_anon_email` (`j***@gmail.com`), `_anon_phone` (`+22 ** ** ** 56`), `_apply_anon_to_contact`, et `_resolve_anon_flags(viewer)` qui retourne tout `False` pour les rôles privilégiés (`admin`, `superviseur`, `moderateur`).
   - Hérité automatiquement : un utilisateur suivi voit l'anonymisation appliquée si son client parent l'a activée.
   - Endpoint `GET /me/contacts` applique les flags via `_apply_anon_to_contact`.
   - UI : 4 nouveaux tiles "RGPD —" rose dans `/admin/clients/{id}/features`.
✅ **CRITIQUE — bug `app.include_router(api)` déplacé** : la fonction était appelée à la ligne 10764 mais les nouveaux endpoints subscriptions/wa-sync/wa-pending étaient ajoutés APRÈS → 404 sur tous. Déplacé tout en bas du fichier (avec commentaire explicatif).
✅ Tests curl complets : webhook avec `contacts[]` → `wa_pending_imports` upserté, import → contact créé avec wa_profile_name + tag `wa-import`, wa-sync retourne suggestion. Subscriptions : catégorie + plan créés (code `FML20260001` généré), public list filtre les champs sensibles. RGPD : tracker (utilisateur) voit `J*** D***` + `j***@acme.fr` + `+22 ** ** ** 56`, admin (privilégié) voit en clair.
✅ Validation Playwright : page admin Abonnements avec 3 onglets, page publique `/subscriptions` avec H1 "Choisissez votre formule" + toggle, modal Modifier contact avec bouton vert "Synchro WA".

### 2026-05-09 — Itération 50 : Liens stubs Caisse/Facturation/Catalogue/Tickets + Webhook par-client + Pictogramme auteur + Photo contact
✅ **Liens stubs** : 4 nouveaux liens sidebar portail (Caisse, Facturation, Catalogue, Tickets) avec badge "Bientôt" doré. Page partagée `ComingSoon.jsx` qui affiche un descriptif différent selon le path et 3 bullets de fonctionnalités prévues.
✅ **Visibilité retours de webhook par-client** : ajout de la feature `webhook_returns` dans `DEFAULT_CLIENT_FEATURES` + `ClientFeaturesUpdate`. `WebhookResultModal.jsx` consulte `/me/features` au mount + refresh toutes les 5 min. Si `webhook_returns=false` → tous les events `sawali:webhook-result` sont ignorés (pas de modal). Hérité automatiquement par les utilisateurs suivis du client. UI : 5e tile violet "Retours de Webhook" dans `/admin/clients/{id}/features`.
✅ **Pictogramme auteur** sur Rapports/Suivis : nouveau composant `<AuthorAvatar>` dans `UserNotes.jsx` — avatar circulaire avec initiales (2 lettres) + couleur déterministe (10 couleurs basées sur hash de l'email). Placé en bas de chaque card à côté du nom de l'auteur (vs ancien texte "par email@…").
✅ **Photo contact (avatar à la WhatsApp)** :
   - Backend : champ `photo_url` ajouté à `ContactCreate`/`ContactUpdate`. Endpoints `POST /me/contacts/{cid}/photo` (upload PNG/JPEG/WEBP, max 5 Mo, validation chunked) + `DELETE /me/contacts/{cid}/photo`.
   - Frontend : composant `<ContactAvatar>` réutilisable avec fallback initiales + couleur déterministe ; affiché dans la liste contacts (taille 36) + en-tête `ConversationModal` (40) + section "Photo de profil" du modal édition (56) avec boutons "Remplacer" / "Retirer".
   - L'upload est désactivé tant que le contact n'a pas été enregistré — bandeau ambre invitant à sauvegarder d'abord.
✅ Tests curl : `/me/features` retourne `webhook_returns:true`, `PUT /admin/clients/{id}/features {webhook_returns:true,whatsapp:true}` enregistre correctement, upload PNG 1×1 → `photo_url:/api/files/...`, contact retournée avec le nouveau champ.
✅ Validation Playwright : sidebar avec 4 badges "Bientôt", Mes Rapports avec pictos AS/AD colorés, Centre de Messagerie avec avatars JD/TE/WI, modal édition contact avec section photo, page admin features avec 5 tiles dont la nouvelle violette "Retours de Webhook".

### 2026-05-07 — Itération 49 : Responsive multi-tableaux (Paiements, SMS Bulk, Trafic & Visites)
✅ Pattern responsive de l'itération 48 appliqué à 3 nouveaux tableaux :
   - **`MyPayments.jsx`** (Mes paiements) : Date toujours visible (avec MNO + numéro empilés en mobile <sm), Référence cachée <lg, Opérateur caché <sm, Numéro caché <md, label Statut + label "Renvoyer" cachés <sm. Wrapper passé `max-w-6xl` → `max-w-full` pour utiliser toute la largeur disponible.
   - **`SmsBulk.jsx`** (SMS — Masse & Planif.) : tableau planifications — Programmé pour toujours visible (avec Message tronqué + dest+provider empilés en mobile <md), Message caché <md, Destinataires <sm, Provider <lg, label Statut + label "Annuler" cachés <sm. Wrapper `max-w-7xl` → `max-w-full`.
   - **`AdminVisits.jsx`** (Trafic & Visites) : Date toujours visible (avec Pays/Ville + IP empilés en mobile <md), IP cachée <md, Pays/Ville cachée <sm, Page tronquée 200px, Référent caché <lg.
✅ Validation Playwright : `docW=winW=390` à 390px sur les 3 pages, idem à 1280px → zéro overflow horizontal.

### 2026-05-07 — Itération 48 : Responsive Centre de Messagerie + Fix overflow mobile global
✅ **Renommage** : "Répertoire & WhatsApp" → **"Centre de Messagerie"** dans la sidebar et l'en-tête de page (sous-titre "Répertoire de contacts unifié — WhatsApp, SMS & planifications").
✅ **Tableau Contacts.jsx — responsive multi-breakpoints** :
   - Mobile (<640px) : 2 colonnes uniquement (Nom + WhatsApp + Actions). Société + téléphone affichés sous le nom en muted text. Boutons WhatsApp/SMS/Schedule/Hist./Éditer en **icônes seules**.
   - sm (≥640px) : ajout colonne Société, labels sur boutons WhatsApp/SMS.
   - md (≥768px) : ajout colonne Téléphone.
   - xl (≥1280px) : labels sur Mess. Program. + Hist. Mess. + bouton "Éditer" textuel.
   - 2xl (≥1536px) : ajout colonnes Email (truncate 220px) + Partage.
   - Min-width Actions réduit 340→180px, padding cellules réduit. Bouton Hist. Mess. désormais 100% visible sur tous les breakpoints.
✅ **Overflow horizontal global** : `overflow-x-hidden` ajouté à `html`+`body` (index.css) + `flex-1 min-w-0 overflow-x-hidden` sur le `<main>` du `PortalLayout` + `overflow-x-hidden` sur `MarketingLayout`. Plus de scroll horizontal parasite sur mobile (`docW=winW=390` validé Playwright).
✅ Validation Playwright : screenshots à 390 / 768 / 1280 / 1440px → 0 overflow horizontal sur tous, 5 boutons d'action visibles, badge "1" non lu correctement positionné dans la sidebar.

### 2026-05-07 — Itération 47 : Réponses WhatsApp libres (fenêtre 24h Meta) + Badges messages non lus
✅ **Backend** :
   - Nouveau helper `_wa_send_text(to, text)` : envoi free-form via Meta Graph (`type=text`, `preview_url=true`). Même structure de retour que `_wa_send_template`.
   - Helpers `_wa_last_inbound_iso()` + `_wa_window_open(iso)` : calculent si la dernière réception du contact se situe dans la fenêtre des 24h Meta.
   - `POST /me/whatsapp/send-text` : envoi texte libre. Vérifie la fenêtre 24h → 409 explicite sinon. Logge dans `whatsapp_messages` (direction=outbound, message_type=text, body=text).
   - `GET /me/whatsapp/unread` : agrégat MongoDB par `contact_id` des inbounds avec `read_by_us_at=null` → `{total, by_contact}`.
   - `POST /me/contacts/{cid}/messages/mark-read` : marque tous les inbounds du contact comme lus (matching par `contact_id` OR `phone_digits`).
   - Enrichissement `GET /me/contacts/{cid}/messages` : retourne désormais `can_send_text` (bool), `last_inbound_at`, `window_expires_at` (ISO).
   - `GET /me/notifications/counts` : ajoute la clé `contacts_unread` (basée sur `read_by_us_at IS NULL`, indépendante de `last_visited_at`).
✅ **Frontend** :
   - **Sidebar `PortalLayout.jsx`** : badge rouge sur "Répertoire & WhatsApp" alimenté par `counts.contacts_unread`. Flag `noMarkSeen=true` ajouté pour ce module → la navigation NE remet PAS le badge à zéro (seul le mark-read par contact le fait).
   - **`Contacts.jsx`** : nouveau state `unread.{total, by_contact}` rafraîchi au mount + polling 30s. Pastille rouge animate-pulse à côté du nom du contact + sur le bouton "Hist. Mess." (corner badge). Données passées via prop `unreadCount` à `ContactRow`.
   - **`ConversationModal`** :
     - Auto `POST /me/contacts/{cid}/messages/mark-read` à l'ouverture → décrémente le badge.
     - Si `can_send_text=true` → composer texte libre (textarea 4096 char + bouton Envoyer + badge "Fenêtre 24h ouverte" + indicateur d'expiration). Raccourci Cmd/Ctrl+Entrée.
     - Sinon → bandeau ambre "Fenêtre 24h fermée — utilisez un template Meta approuvé" avec lien vers le bouton WhatsApp template.
     - Recharge + remontée du compteur unread vers parent au close.
✅ Tests curl : webhook simulé (inbound `Bonjour, j-ai une question`) → contact résolu via `phone_digits` → `can_send_text:true`, `window_expires_at:+24h`, `messages_count:1`. `mark-read` retourne `updated:1`. `send-text` retourne `ok:false` avec erreur claire "WhatsApp non configuré" (env preview), pas de 409. Hors fenêtre → 409 attendu.
✅ Validation Playwright : sidebar affiche bien "1" en badge rouge, modal affiche conversation avec bulles entrantes/sortantes + composer vert "Réponse libre autorisée" + textarea + bouton Envoyer.
✅ 7 nouveaux data-testid : `contact-unread-{id}`, `contact-history-unread-{id}`, `conversation-composer-open`, `conversation-composer-closed`, `conversation-text-input`, `conversation-text-send`, `conversation-window-expires`.

**Cas d'usage** : un client envoie "Bonjour, j'ai un souci" sur le WhatsApp Business du compte → la jauge Liluvine reste verte mais l'icône Hist. Mess. du contact gagne une **pastille rouge** + le menu sidebar affiche "1". L'agent ouvre la conversation : le compteur est mis à zéro automatiquement, et il peut répondre librement avec du texte libre durant 24h **sans avoir besoin d'un template Meta approuvé** — Meta n'autorise le free-form qu'à l'intérieur de cette fenêtre. Passé 24h, l'UI affiche un bandeau ambre invitant à utiliser un template.

### 2026-05-07 — Itération 46 : Liluvine intelligent + Contrôle distant HMAC + Commandes WhatsApp
✅ **Backend** :
   - `/public/support-load` enrichi → retourne `liluvine.{alert_enabled, threshold, alert_active, label, message}` (alert_active = level ≥ threshold ET les deux features activées).
   - `POST /admin/liluvine/remote-link` : génère un token HMAC-SHA256 signé (payload `{scope, issued_at, issued_by, exp}`) encodé URL-safe base64. TTL configurable (1h..1 an, défaut 30 jours). Auto-génération du secret côté DB si absent.
   - `GET/POST /public/remote/support/{token}` (no-auth) : valide le token HMAC + signature, expose lecture/écriture du level/threshold/label. Audit log dans `api_traces` à chaque update.
   - `_try_handle_liluvine_wa_command` : parser regex (`!seuil N`, `!niveau N [label]`, `!load N`) déclenché dans le webhook Meta WA inbound. Allow-list des numéros admin (`liluvine_remote_admin_phones`). Numéro non listé → rejet silencieux + trace.
   - 6 nouveaux champs Settings : `liluvine_alert_enabled`, `liluvine_alert_threshold` (0..7), `liluvine_alert_message` (250 char), `liluvine_alert_label` (60 char), `liluvine_remote_secret` (HMAC), `liluvine_remote_admin_phones` (list).
✅ **Frontend** :
   - **`VirtualAssistant.jsx`** : poll `/public/support-load` toutes les 60s. Quand `alert_active=true` → bouton devient **rouge** avec icône triangle, label change vers le custom (`liluvine_alert_label`), animation pulse, **bulle tooltip auto-affichée 12s** une fois par session avec message + CTA "Démarrer le chat".
   - **`/remote/support/:token`** (`RemoteSupportConsole.jsx`) : page mobile-first brandée SAWALI. Aperçu jauge live (couleurs dégradées vert→rouge) + badge "ALERTE ACTIVE" si applicable. 3 sections : sélecteur niveau 0..7 (one-tap save), sélecteur seuil ≥1..≥7, libellé personnalisé. Validation HMAC côté serveur, traçage dans `api_traces`.
   - **Admin Settings** → bloc rose "Liluvine — Redirection intelligente" : toggle activation, sélecteur seuil 7 boutons, label custom (60 char) + textarea message (250 char), **bouton "Générer un lien (30 jours)"** avec URL prête à copier, bloc émeraude "Contrôle via WhatsApp" avec exemples de commandes + champ allow-list multi-numéros.
✅ Tests Playwright : home en niveau 7/seuil 5 → jauge rouge + Liluvine rouge "🔴 Très occupé — chat" + bulle d'alerte auto-affichée. Console distante : aperçu live, click level 2 → toast "Mis à jour" + aperçu passe instantanément à 2/7 vert.
✅ 14 nouveaux data-testid : `virtual-assistant-{alert|alert-close|alert-cta}`, `remote-current-preview`, `remote-{level|threshold}-picker`, `remote-{level-{0..7}|threshold-{1..7}}`, `remote-label-{input|save}`, `remote-refresh`, `liluvine-alert-block`, `liluvine-alert-{enabled|label|message}`, `liluvine-threshold-{1..7}`, `liluvine-{gen-link|copy-link|remote-url|admin-phones}`.

**Cas d'usage final** : depuis votre téléphone, vous bookmarkez une URL signée HMAC, et en 2 taps vous changez le niveau d'occupation + le seuil. Quand vos clients arrivent sur le site et que la jauge est rouge, Liluvine les redirige automatiquement vers le chat plutôt que le téléphone. Vous pouvez aussi envoyer `!niveau 6 Forte affluence` depuis votre WhatsApp (depuis un numéro admin allow-listé) pour la même action.

### 2026-05-07 — Itération 45 : Jauge d'occupation Support Technique (style signal cellulaire)
✅ **Backend** : 3 endpoints + helper de validation 0..7
   - `GET /public/support-load` (no-auth) → `{enabled, level, label, updated_at}`
   - `POST /admin/support-load` (admin) → push immédiat avec stamp `updated_by`/`updated_at`
   - `POST/GET /webhooks/support-load/{secret}` → mise à jour automatique depuis monitoring externe (Zabbix/Grafana/n8n…). Accepte `?level=N&label=...` en GET ou `{level, label}` en POST JSON. Active automatiquement la jauge à réception.
   - Ajout 4 champs dans `Settings` model : `support_load_enabled`, `support_load_level` (0..7), `support_load_label` (140 char), `support_load_webhook_secret`.
✅ **Composant `SupportLoadGauge.jsx`** : sticky banner en haut du `MarketingLayout` (donc présent sur **toutes** les pages publiques), centré, fond gradient slate-900→slate-800, polling auto toutes les 60s.
   - **7 barres** style signal cellulaire (hauteurs croissantes 4→16px) avec couleurs distinctes par barre : vert / vert-clair / lime / jaune / amber / orange / rouge. Glow shadow sur barres actives.
   - Icône casque (Headphones) + label "Support Technique" + libellé contextuel (custom ou auto selon niveau : "Très disponible", "Charge légère", …, "Saturé") + ratio `N/7`.
   - Caché si `enabled=false` (zéro footprint sur les pages publiques quand désactivé).
   - Accessibilité : `role="status"` + `aria-label` détaillé.
✅ **Admin Settings UI** (`SupportLoadSection`) : aperçu live de la jauge, toggle d'activation, **8 boutons cliquables** (0..7) avec couleurs correspondantes pour push immédiat (sans bouton "Enregistrer"), champ libellé personnalisé, **générateur de secret** pour le webhook avec URL prête à copier (ex: `https://sawalismartsystems.com/api/webhooks/support-load/{secret}?level=4&label=…`).
✅ Tests : `POST /admin/support-load level=5` → `level=5` propagé au public ; `GET /webhook/support-load/{secret}?level=6&label=...` → niveau 6 + auto-activation ; reset à 0/disabled OK.
✅ Validation Playwright : jauge visible sur la home, 7 barres rendues, label "Test webhook 6/7" affiché en haut centré.
✅ 8 nouveaux data-testid : `support-load-gauge`, `support-load-bars`, `support-bar-{1..7}`, `support-load-section`, `support-load-{preview|enabled|levels|level-{0..7}|label|secret|gen-secret|copy-url}`.

**Cas d'usage** : votre équipe support voit "rouge 7/7" → réduit les appels entrants en redirigeant vers WhatsApp/email. Outils monitoring (FreshDesk/Zendesk file d'attente) peuvent pousser le niveau automatiquement via webhook → expérience client transparente.

### 2026-05-07 — Itération 44 : 🐛 FIX P0 — Crash React sur paiement PawaPay
✅ **Cause root identifiée** grâce au système de télémétrie ajouté en itération 43 : ErrorBoundary a capturé l'erreur exacte
> `Objects are not valid as a React child (found: object with keys {rejectionCode, rejectionMessage})`

PawaPay v2 a changé son schéma : `failureReason` et `rejectionReason` sont désormais des **objets** `{failureCode, failureMessage}` ou `{rejectionCode, rejectionMessage}` (au lieu de simples chaînes en v1). Le frontend tentait de rendre ces objets directement → crash React fatal.

✅ **Fix backend** : nouveau helper `_pawapay_str()` dans `server.py` qui coerce tout résultat PawaPay (`None`/`str`/`dict`) en chaîne lisible (`"CODE — Message"` ou `Message` ou `Code` selon dispo). Appliqué aux **6 emplacements** où PawaPay renvoie failure/rejection :
   - `POST /me/payments/pawapay/deposit` (api_message + reason)
   - `GET /me/payments/{deposit_id}` (polling)
   - `POST /webhooks/pawapay/{secret}` (callback)
   - `POST /public/pay/{slug}/deposit` (api_message + reason)
   - `GET /public/pay/{slug}/status/{deposit_id}` (polling)
✅ **Fix frontend** : nouveau helper `safeText()` dans `MyPayments.jsx` qui rend défensivement n'importe quel `api_message`/`reason` même s'il vient de la DB en format objet (legacy). Appliqué dans le tableau transactions + le toast d'erreur du modal submit. Helper similaire intégré dans `PayLink.jsx` (page publique).
✅ **Test unitaire** du helper : `_pawapay_str({rejectionCode:'INVALID_AMOUNT', rejectionMessage:'Le montant est invalide'})` → `"INVALID_AMOUNT — Le montant est invalide"` ✅
✅ Backend redémarré, lint clean.

**Impact production** : après redéploiement, le clic « Lancer le paiement » affichera désormais un toast d'erreur clair (ex : `"INVALID_AMOUNT — Le montant est invalide"`) au lieu de crasher la page. Les paiements rejetés / échoués s'afficheront correctement dans le tableau.

### 2026-05-07 — Itération 43 : Hardening Paiements + Telemetry crash production
✅ **ErrorBoundary global** (`/app/frontend/src/components/ErrorBoundary.jsx`) appliqué autour de `MyPayments` et `SmsBulk` dans `App.js`. Affiche un panneau rouge avec stack + bouton « Copier les détails » + « Recharger la page » au lieu d'une page blanche en cas d'exception React.
✅ **Global error reporter** (`window.error` + `unhandledrejection`) installé dans `App.js` → poste un breadcrumb à `/me/api-trace` (kind, msg, stack, ua, path) pour les crashs hors-arbre React (event handlers, async, libs).
✅ **Submit PawaPay durci** dans `MyPayments.jsx` :
   - Pre-flight breadcrumb (`CLIENT_DEBUG`) envoyé à `/me/api-trace` avec amount/mno/msisdn_len/has_description avant l'appel à `/me/payments/pawapay/deposit`.
   - **Toast loading** ("Envoi de la demande à PawaPay…") avec timeout 35s.
   - **Timeout HTTP client** explicite à 32s (axios) — évite les hangs muets sur connexions lentes.
   - **Toast error** détaillé (`detail` ou `message`) avec duration 8s, traçabilité maximale.
   - Catch global → `CLIENT_ERROR` posté avec status, error, stack vers `api_traces`.
✅ **Bouton « Nouveau paiement »** instrumenté pareillement (try/catch + breadcrumbs avec features/mnos_len/items_len/tab) pour diagnostiquer toute exception même hors-render.
✅ Tests Playwright preview : submit avec montant 1500 + MSISDN valide → toast d'erreur clair « Erreur : PawaPay non activé », modale reste ouverte, aucun crash, aucune ErrorBoundary déclenchée.
✅ 1 nouveau data-testid : `error-boundary`.

### 2026-05-07 — Itération 42 : SMS Phase 2 (bulk + planification) + WA statuts retour
✅ **Backend SMS Phase 2** :
   - `POST /me/sms/bulk` : envoi en masse jusqu'à 500 contacts. Personnalisation via `{{name}}/{{company}}/{{phone}}/{{whatsapp}}/{{email}}/{{tag}}` substitué par contact. Si `scheduled_at` (ISO8601) fourni → planification (refus si <30s dans le futur).
   - `GET /me/sms/schedules` + `DELETE /me/sms/schedules/{id}` : liste + annulation des envois planifiés.
   - **Cron APScheduler** `_run_scheduled_sms` (toutes les minutes, Africa/Abidjan, misfire_grace_time=120s). Pattern claim atomique (status=pending → running) puis envoi par contact + log dans `sms_messages`. Final status `done|failed`.
   - Indices Mongo ajoutés : `sms_messages.client_id/created_at/payment_link_slug`, `sms_schedules.status/scheduled_at`, `payment_links.slug unique`, `payments.deposit_id unique`.
✅ **Persistence du `payment_link_slug`** dans `sms_messages` (envoi unitaire + bulk + scheduled) et `whatsapp_messages` (extrait via `_extract_pay_slug` qui matche `/pay/{slug}` dans le body SMS ou dans le JSON des components WA template). Dashboard 360° utilise désormais ce champ persistant au lieu d'un regex sur le body → attribution canal **fiable**.
✅ **Frontend** `/portal/sms` (`SmsBulk.jsx` ~340 lignes, lazy via App.js + entrée sidebar « SMS — Masse & Planif. ») :
   - **Sélecteur multi-contacts** avec recherche live (nom, téléphone, tag, company), checkbox + « Tout sélectionner » sur le filtre courant. Affichage du nombre de contacts sélectionnés en badge.
   - **Composer** : sélecteur fournisseur (auto + actifs), expéditeur 11-char, **chips d'insertion** des 6 tokens + textarea max 800 char avec compteur (warning >160 sur facturation multi-SMS).
   - **Datepicker datetime-local** pour planifier l'envoi (si vide → envoi immédiat).
   - **Bouton Aperçu** : modal montrant les 3 premiers messages personnalisés tels qu'ils seront envoyés (substitution live des tokens).
   - **Tableau des planifications** : programmé pour, message tronqué, destinataires N (+ ✓ envoyés une fois fait), provider, badge statut animé (pending/running spinning/done/failed/cancelled), action « Annuler » pour les `pending`.
✅ **WA Statuts retour** : webhook Meta `/api/whatsapp/webhook` parse déjà `statuses[]` (sent/delivered/read/failed) et persiste `wa_status`, `sent_at`, `delivered_at`, `read_at`, `failed_at`, `wa_error_code/message`. Frontend `Contacts.jsx` `MessageBubble` affiche déjà les ticks colorés (Check / CheckCheck slate / CheckCheck sky / AlertCircle rose). Test simulé OK : status=read → `wa_status=read`, `read_at` correctement renseigné.
✅ Tests curl + Playwright : `POST /me/sms/bulk` avec `scheduled_at` futur retourne `{ok:true, scheduled:true, recipients:1}` + persiste dans `sms_schedules`. UI `/portal/sms` rendue : 3 contacts listés, token `{{name}}` cliqué et inséré, planification existante affichée dans le tableau.
✅ 18 nouveaux data-testid : `sms-bulk-page`, `sms-contacts-block`, `sms-contacts-search`, `sms-contact-{id}`, `sms-toggle-all`, `sms-compose-block`, `sms-bulk-{provider|sender|message|schedule-at|preview|send-btn}`, `sms-token-{name}`, `sms-schedules-block`, `sms-sched-{id}`, `sms-sched-cancel-{id}`, `sms-preview-modal`, `sms-preview-{i}`.

### 2026-05-07 — Itération 41 : Dashboard Encaissements 360°
✅ **Backend** : `GET /me/payments-dashboard?days=N` — agrégation cross-source (payments + payment_links + whatsapp_messages + sms_messages). Retourne :
   - `totals` : amount_completed, payments {count, completed, pending, failed}, links {total, active, disabled, expired, exhausted}.
   - `by_status` (pending / completed / failed), `by_mno` (ORANGE / MOOV / TELECEL / OTHER).
   - `channels` : `sent` (whatsapp+sms ayant un `/pay/{slug}` dans le body), `payments_attributed` (par source PawaPay), `conversion_rate_pct`.
   - `daily` : 30 jours zero-fill avec count + amount.
   - `top_links` : top 5 par uses_count (avec status calculé live).
   - **Heuristique d'attribution canal** : regex sur `whatsapp_messages.message_text` et `sms_messages.message` cherchant `/pay/{slug}` → comptabilise les envois liés à un lien.
   - Note : route `/me/payments-dashboard` (sans `/`) pour ne pas entrer en conflit avec `/me/payments/{deposit_id}`.
✅ **Frontend** `PaymentsDashboard.jsx` (`recharts`) — onglet **Dashboard 360°** par défaut dans `/portal/payments` :
   - 4 KPIs : Encaissements (montant XOF) / Liens actifs / En attente / Conversion %.
   - **AreaChart** des encaissements quotidiens (gradient emerald, tooltip XOF).
   - 3 charts compacts en grille : `PieChart` statuts, `BarChart` MNO (couleurs Orange/Moov/Telecel), `BarChart` canaux (Envoyés vs Payés WhatsApp/SMS/Direct).
   - Tableau Top 5 liens : libellé + slug + montant + utilisations N/M + badge statut coloré.
   - Sélecteur période : 7j / 30j / 90j / 6 mois / 1 an.
✅ Tests curl + Playwright : 9 sections rendues, top_links peuplé (3 entrées présentes), AreaChart visible avec 30 jours.
✅ 11 nouveaux data-testid : `payments-dashboard`, `dashboard-period`, `dashboard-kpis`, `kpi-{cash|links|pending|conversion}`, `dashboard-chart-daily`, `chart-{status|mno|channels}`, `dashboard-top-links`, `top-link-{slug}`, `tab-dashboard`.

### 2026-05-07 — Itération 40 : Module SMS multi-fournisseurs (Phase 1 — envoi unitaire)
✅ **Backend** (4 nouveaux endpoints + dispatcher) :
   - `_sms_dispatch(provider, msisdn, message, sender)` : dispatcher routant vers OVH ou un webhook HTTP générique selon le fournisseur.
   - **OVH** : intégration officielle via API REST signée HMAC-SHA1 (`/sms/{serviceName}/jobs`), gestion `invalidReceivers`, fallback sur `auth/time` pour éviter les rejets de skew d'horloge.
   - **Orange / Moov / Telecel BFA** : provider générique HTTP — URL/method/auth (none/bearer/basic/header)/payload template avec placeholders `{phone}` `{message}` `{sender}`. Content-Type configurable (json|form).
   - Sélection auto du fournisseur par défaut : préfixe `+226` → Burkina, sinon OVH (sinon premier actif).
   - `GET /me/sms/providers`, `POST /me/sms/send`, `GET /me/sms/messages`, `POST /admin/sms/test`. Stockage dans `db.sms_messages` (id, provider, msisdn, status, http_status, raw_response…). Feature gating via `/me/features.sms`.
✅ **Settings model** étendu : `sms_{orange|moov|telecel}_payload_template`, `_content_type`, `sms_default_provider` (auto|orange|moov|telecel|ovh).
✅ **Admin Settings UI** : pour chaque provider Burkina → champ textarea « Template du payload » + sélecteur JSON/Form + **bouton « Tester l'envoi {NAME} »** qui ouvre une modal compacte (numéro + message + résultat HTTP brut). OVH : même bouton de test. Sélecteur global « Fournisseur SMS par défaut ».
✅ **Portal Contacts** : nouveau bouton **SMS** (orange) à côté de WhatsApp sur chaque ligne. Modal `SmsModal` avec sélecteur de fournisseur (auto + actifs), expéditeur optionnel, textarea (max 800 char) avec compteur, intégration **`PaymentLinkInserter`** réutilisé : insertion d'un lien `/pay/{slug}` directement dans le corps SMS via callback.
✅ **`PaymentLinkInserter`** rendu polymorphique : prop `insertCallback` (utilisé par SMS, contournant le slot-picker {{N}} qui s'applique uniquement au flux WA template).
✅ Tests curl : `GET /me/sms/providers` → `active=[]` ; `POST /me/sms/send` → `403 SMS non autorisé` (gating OK) puis `failed: Aucun fournisseur SMS disponible` (admin) ; `POST /admin/sms/test` provider=orange → `failed: Fournisseur 'orange' non activé` (logique OK).
✅ Validation Playwright : 3 boutons SMS visibles dans `/portal/contacts`, modal SMS s'ouvre avec bandeau « Aucun fournisseur configuré » (UI conditionnelle correcte). Section Admin Settings : `sms-orange-block`, `sms-orange-payload-template`, `sms-orange-test-btn`, `sms-default-provider`, `sms-ovh-test-btn` tous présents et la modal Test SMS Orange s'ouvre correctement.
✅ 14 nouveaux data-testid : `contact-sms-{id}`, `sms-modal`, `sms-provider-select`, `sms-sender`, `sms-message`, `sms-send-btn`, `sms-result`, `sms-{provider}-payload-template`, `sms-{provider}-content-type`, `sms-{provider}-test-btn(-modal/-to/-message/-result/-send)`, `sms-default-provider`.
✅ **À venir Phase 2** : envoi en masse (bulk avec personnalisation par contact), planification SMS (cron), stats SMS dans `/admin/usage` (déjà partiellement préparé via `db.sms_messages`).

### 2026-05-07 — Itération 39 : Liens de paiement intégrés dans WhatsApp
✅ **Composant `PaymentLinkInserter`** ajouté dans le modal WhatsApp de `/portal/contacts` :
   - Bouton « 🔗 Insérer un lien de paiement » visible dès qu'un template a des variables `{{N}}`.
   - Sub-modal à 2 onglets : **Liens actifs** (liste cliquable des liens `status=active`) ou **Nouveau lien rapide** (libellé + montant fixe/libre, MNOs hérités du client → `POST /me/payment-links`).
   - Étape 2 : grille `{{1}} {{2}} {{3}}…` pour choisir dans quelle variable du corps coller l'URL `https://…/pay/{slug}`. Toast confirme « Lien collé dans la variable {{N}} ».
   - Réutilise `/me/features` (gating paiements) + `/me/payment-links` (CRUD existant) — zéro nouvel endpoint backend.
✅ Permet à un utilisateur portal d'envoyer une **facture WhatsApp avec lien de paiement Mobile Money cliquable** en quelques secondes : ouvrir le modal WA → choisir un template avec une variable URL → cliquer « Insérer un lien » → créer ou choisir → coller dans `{{3}}` → envoyer. Le client paie en 2 tap depuis WhatsApp via PawaPay.
✅ 7 nouveaux data-testid : `wa-payment-link-inserter`, `wa-pay-link-btn`, `wa-pay-link-modal`, `wa-pay-tab-{existing|quick}`, `wa-pay-pick-{slug}`, `wa-pay-quick-{label|amount|open|create-btn}`, `wa-pay-target-var-{i}`, `wa-pay-back-btn`.
✅ Lint clean. Validation Playwright : button correctement caché sans WA configuré (logique fonctionnelle).

### 2026-05-07 — Itération 38 : Liens de paiement partageables (Mobile Money sans login)
✅ **Backend** : nouveau modèle `payment_links` (slug 8 chars, owner, allowed_mnos, montant fixe ou libre, expires_at, max_uses, uses_count, disabled). Endpoints :
   - `POST /me/payment-links` (créer), `GET /me/payment-links` (lister), `PATCH /me/payment-links/{id}` (toggle disabled), `DELETE /me/payment-links/{id}`.
   - `GET /api/public/pay/{slug}` (public, retourne label, montant, MNOs, branding du client), `POST /api/public/pay/{slug}/deposit` (déclenche PawaPay sans auth, incrémente uses_count, lie le `payments.row` au lien via `payment_link_id/_slug`), `GET /api/public/pay/{slug}/status/{deposit_id}` (polling public — refresh PawaPay live si pending).
   - Re-use du flow PawaPay existant (`_pawapay_active_token`, `_pawapay_correspondent`, host sandbox/prod). Statut auto : active / disabled / expired / exhausted.
✅ **Frontend Portal** (`/portal/payments`) : système d'onglets « Transactions » / « Liens de paiement » (composant extrait `MyPaymentLinks.jsx`).
   - Création : modal complet (libellé, montant fixe OU libre, choix multi-MNO, expiration datetime, max_uses, description). À la création → modal QR auto-affiché.
   - Liste : table avec libellé+slug+description, montant ou « libre », badges MNO, compteur usages (0/N ou ∞), badge statut coloré.
   - Actions par ligne : Copier le lien / QR / Partager via WhatsApp (`wa.me/?text=…`) / Ouvrir / Activer-Désactiver (toggle) / Supprimer.
   - QR Modal : génération via `qrcode.toDataURL` 320×320 + bouton « Télécharger PNG ».
✅ **Page publique** (`/pay/:slug` — `pages/public/PayLink.jsx`) : landing brandée (logo + nom du client), affichage du montant fixe ou champ saisie libre, sélecteur MNO coloré, MSISDN international, nom optionnel, bouton « Payer maintenant ».
   - Écran résultat (success / pending / failed) avec polling auto toutes les 5s pendant `pending` jusqu'à confirmation finale.
   - Gère 4 états : actif / désactivé / expiré / épuisé (avec messages FR explicites).
   - Footer : « Powered by SAWALI SMART SYSTEMS × PawaPay » + cadenas.
✅ Tests curl : 3 liens créés (5000 fixe + 2500 fixe + libre), `GET /public/pay/{slug}` retourne le payload public correctement, branding client résolu (logo_url, company).
✅ 17 nouveaux data-testid : `payments-tabs`, `tab-transactions`, `tab-links`, `payment-links-tab`, `links-new-btn`, `link-{row|copy|qr|wa|open|toggle|delete}-{slug}`, `link-new-modal`, `link-{label|amount|open-amount|description|expires-at|max-uses|mno-X|submit-btn}`, `link-qr-modal`, `pay-link-page`, `pay-{amount|mno-X|msisdn|name|submit-btn|retry-btn}`, `pay-result`.

### 2026-05-07 — Itération 37 : PawaPay Mobile Money UI (Portal)
✅ **Page `/portal/payments`** complète : KPIs (Complétés / En attente / Échoués / Total transactions avec montants), filtres (Statut, Opérateur, période Du/Au, reset), table responsive avec polling automatique des paiements `pending` toutes les 20s et bouton « Vérifier » manuel.
✅ **Modal Nouveau paiement** : montant XOF, sélecteur 3 MNO colorés (Orange Money / Moov Money / Telecel Cash), MSISDN format international, description ≤22 car. Validation côté client + serveur.
✅ **Renvoyer un paiement échoué** : bouton sur chaque ligne `failed` qui pré-remplit le modal avec les infos précédentes (montant, MNO, MSISDN, description) et un bandeau d'avertissement.
✅ **Export CSV** (BOM UTF-8 / séparateur `;` / Excel FR-friendly) sur la liste filtrée.
✅ **Sidebar** : nouvelle entrée « Mes paiements » (icône Wallet, module=`payments` pour les badges de notifications).
✅ **Feature gating** : page lit `/me/features` ; bouton « Nouveau paiement » désactivé si `features.payments=false` ou `pawapay_mnos=[]`. Bandeau d'info pour l'utilisateur. Admins/superviseurs voient tout (héritage backend déjà en place).
✅ Backend `POST /me/payments/pawapay/deposit` validé (503 quand non configuré, accepté quand clés sandbox/prod renseignées). Webhook `/webhooks/pawapay/{secret}` déjà présent pour finaliser le statut.
✅ 11 data-testid : `my-payments-page`, `payments-new-btn`, `payments-refresh`, `payments-export-csv`, `kpi-{completed|pending|failed|total}`, `payments-filters`, `filter-{status|mno|date-from|date-to|reset}`, `payment-row-{id}`, `payment-{refresh|resend}-{id}`, `payment-new-modal`, `payment-{amount|mno-{X}|msisdn|description|submit-btn|cancel-btn|modal-close}`.

### 2026-05-06 — Itération 36 : Lot B-2 — Formulaires enrichis (3 nouveaux types + Print PDF + QR)
✅ **3 nouveaux types de champs** : `table` (colonnes paramétrables + lignes dynamiques), `file` (≤1 Mo, accept configurable), `signature` (canvas signature_pad, 1 par formulaire). Modèle `FormField` étendu avec `columns?` et `accept?`.
✅ **Endpoint upload** : `POST /me/forms/{form_id}/upload` (multipart, ≤1Mo, 413 si dépassement, réutilise infra `/api/files/{id}` existante).
✅ **Print PDF** : nouveau bouton violet sur le runner. Ouvre une page imprimable avec titre + numéro + QR du lien (public/privé) + table de toutes les données (signature comme image, tableau imbriqué, fichier comme lien).
✅ **QR des données** : bouton fuchsia → modal avec QR encodant `{form_id, numero, title, data, generated_at}` en JSON brut + bouton télécharger PNG.
✅ **Editor** : config UI dédiée par type (éditeur de colonnes pour table, accept pour file, warning anti-doublon signature).
✅ Tests : 8/8 pytest iter23 (~2.6s) + 17 testids Playwright. Aucun bug.


✅ **RDV partagés par client** : `me_appointments` + `me_create_appointment` utilisent `client_id || id` → tous les utilisateurs suivis d'un même client voient les mêmes RDV. Admin/superviseur voient tout.
✅ **Webhook sortant n8n** : `_fire_agenda_n8n(action, appointment, user)` fire-and-forget sur create/update/delete manuel. Auth none/bearer/basic, timeout 10s, payload `{type:agenda, action, appointment, user, fired_at}`.
✅ **Webhook entrant n8n** : `POST /api/webhooks/agenda/{secret}` non-authentifié (secret = path token). Actions : list/create/update/delete. Validation slot disponible. Tag `source:'n8n'`. 503 si désactivé, 403 si secret faux.
✅ **Settings agenda** : `agenda_n8n_outbound_*` (enabled/url/auth_type/token/basic_user/basic_pass) + `agenda_n8n_inbound_*` (enabled/secret). 3 secrets masqués.
✅ Coexiste avec Google Calendar (gcal_event_id null pour RDV créés par n8n).
✅ Tests : 14/14 pytest iter22 (~5.2s). Toutes les UI Playwright vérifiées (login OTP/Plateforme Interne, /admin/usage 11 testids, /admin/settings agenda+OTP).


✅ **`/admin/usage`** : nouvelle page admin avec 4 KPI cards (WA envoyés/reçus, Synthèses IA, Coût WA estimé), graphique stacked Recharts 30j, tableau triable par client (8 colonnes : WA OK/KO/Reçus/Coût, IA, dots fonctionnalités), sélecteur période (7j/30j/90j/6mois), export CSV avec BOM UTF-8, lien rapide vers timeline CRM. Endpoint `GET /admin/usage/summary?days=N`.
✅ **OTP par domaine** : `/auth/login` détecte le domaine de l'email (vs `internal_domains` dans settings) → si interne, OTP affiché ("Plateforme Interne"), sinon envoi par email. Idem `/auth/resend-otp`. Plus de mention "Mode Développement". Notification toast harmonisée.
✅ **Settings "Authentification"** : nouveau champ texte CSV (`internal_domains`) éditable par admin avec aide contextuelle. Défaut : `sawalismartsystems.com`.
✅ **Login UX** : encart OTP coloré bleu (interne) ou ambre (SMTP HS), libellé adapté au cas. Testid `login-otp-inline-notice` + `login-dev-otp`.
✅ Validation : `/admin/usage/summary?days=7` retourne `period:7, totals:{wa_sent_ok:0, wa_total:1, ai_count:0}, clients:8, daily_len:7`. Login admin renvoie `Plateforme Interne : code OTP affiché directement sur la page.` et `dev_otp:True`. Frontend Playwright : page rendue + 4 KPIs + chart + 8 lignes clients.


✅ **Per-client SMART Communications** : nouvelle page `/admin/clients/{id}/features` avec 4 toggles (WhatsApp / SMS / IA / Paiements). Endpoints `GET/PUT /admin/clients/{id}/features` + `GET /me/features` (admin/superviseur=tout activé, tracked-user hérite du parent). Frontend grise les boutons inactifs (Dashboard AI, Contacts WhatsApp/Schedule).
✅ **Notes privées** : nouveau champ `is_private` sur reports/suivis. Si `true` → seul l'auteur + admins voient. Si `false` → partage avec utilisateurs suivis du même client. Toggle dans le formulaire + badge fuchsia "privée" sur la carte. Logique de scoping mise à jour côté backend (`me_list_notes`).
✅ **Synthèse → Rapport** : `POST /me/ai/summaries/{id}/to-report` convertit une synthèse archivée en rapport (`is_private` au choix). Bouton "Rapport" sur chaque ligne de l'onglet "Mes synthèses" du Dashboard. Le contenu HTML est échappé puis paragraphé + footer d'attribution (date + provider + modèle).
✅ **SMS Burkina (Orange/Moov/Telecel)** : 3 blocs admin/settings indépendants (URL + méthode GET/POST + auth none/bearer/basic/header personnalisé + sender_id). 30+ champs ajoutés, 9 secrets masqués.
✅ **OVH SMS** : intégration officielle prête (endpoint ovh-eu/ovh-ca + AK/AS/CK + service_name + sender). 2 secrets masqués (AS, CK).
✅ **PawaPay** : api_token (masqué) + environnement (sandbox/production) + country code (BFA par défaut).
✅ **Aide transcription** : bandeau d'information dans le formulaire de création de Rapport/Suivi pointant vers l'icône micro de la barre d'outils.
✅ **Synthèse IA enrichie** : nouveau system_prompt orienté CONTENU (5 axes : thèmes, décisions, demandes, blocages, prochaines étapes).
✅ Tests : 9/9 pytest iter21 (~3.3s). 14/15 testids frontend validés Playwright. Bouton AI Dashboard confirmé visuel.


✅ **Persistence automatique** : chaque appel réussi à `POST /me/ai/summarize` insère dans `db.ai_summaries` `{id, user_id, user_email, client_id, provider, model, context, target, messages_count, summary, created_at}`. Best-effort (échec DB ne casse pas la réponse utilisateur).
✅ **2 nouveaux endpoints** : `GET /me/ai/summaries?limit=` (admin voit tout, user filtré par user_id, capé 200) + `DELETE /me/ai/summaries/{id}` (RBAC : owner ou admin uniquement).
✅ **Onglets dans le modal Dashboard** : "Générer" / "Mes synthèses (N)". Liste les synthèses passées avec badge provider colorisé (emerald=openai, violet=n8n), date, contexte, cible, count, bouton copier + supprimer par ligne.
✅ Index MongoDB : `user_id`, `(user_id, created_at desc)`, `created_at`. Whitelist DB Explorer + lien sidebar admin (à créer si besoin).
✅ Validé visuel : bouton "Synthèse IA" → modal → onglet "Mes synthèses" → "Aucune synthèse enregistrée…" rendu correctement.


✅ **Bug fix politiques** : `/api/public/policies/{slot}` accepte maintenant `GET + HEAD` (api_route). L'iframe d'aperçu sur `/politiques/{slug}` se charge directement, plus besoin de télécharger le PDF d'abord. Vérifié : `curl -I` retourne 200 (vs 405 avant).
✅ **Endpoint `POST /api/me/ai/summarize`** : moteur dual OpenAI ChatGPT / webhook n8n (AgentAI-style), routé via `ai_summary_provider`. 503 si non-configuré (message FR explicite), 502 sur erreur amont, 504 sur timeout. Parsing n8n robuste : accepte `summary | text | output | message` ou JSON brut.
✅ **Settings IA** : 8 nouveaux champs (`ai_summary_provider`, `openai_chat_api_key`, `openai_chat_model`, `n8n_webhook_url`, `n8n_webhook_auth_type`, `n8n_webhook_token`, `n8n_webhook_basic_user`, `n8n_webhook_basic_pass`). Masking automatique des 3 secrets en GET. Section dédiée dans `/admin/settings` avec sélecteur de moteur + bloc OpenAI + bloc n8n (auth conditionnelle bearer/basic).
✅ **Bouton "Synthèse IA" sur Dashboard** : gradient fuchsia→violet en haut à droite. Modal avec filtres (période 24h/3j/7j/14j/30j/90j, client, sens), inputs cible/contexte facultatifs, bouton "Générer la synthèse". Affiche le résultat dans un encart vert + bouton "Copier".
✅ Tests : 9/9 pytest iter20 (~4.5s). Backend OK 100%. 14 testids frontend validés via grep + visuel iframe vérifié.


✅ **Bug fix Admin WhatsApp** : Helper `_normalize_wa_phone(raw)` filtre digits-only avant l'envoi à Meta Graph. Plus de "Vérifier le numéro" sur les `+`, espaces, tirets, points, parenthèses. `admin_messaging_bulk_send` renvoie maintenant `error_summary[]` (3 erreurs Meta uniques max, 240 car. chacune) — la toast frontend affiche le détail Meta du 1er échec.
✅ **Planification WhatsApp côté Portail** : 3 endpoints `GET/POST/DELETE /api/me/messaging/schedules`. POST valide future date + recipients + template. Le cron `_run_scheduled_whatsapp` (existant) traite indifféremment admin + portal. `Contacts.jsx` : nouveau bouton bleu "Mess. Program." (CalendarClock) par contact + `ScheduleModal` complet (template, langue, date, heure, variables, header, liste des planifs). Renommage "Messages" → "Hist. Mess."
✅ **Transcription audio Whisper** : `POST /api/transcribe` accepte un audio multipart (≤25 Mo), proxy vers `https://api.openai.com/v1/audio/transcriptions` avec la clé stockée dans settings. Sans clé → HTTP 503 français explicite. `UserNotes.jsx` (RichEditor toolbar) : bouton micro 3-états (idle/recording/processing), MediaRecorder API, fallback gracieux si navigateur incompatible.
✅ **Sélecteur client Admin pour Media Library** : `POST /me/media-library` accepte `target_client_id` (ignoré si non-admin). `MediaLibrary.jsx` : dropdown "Pour mon espace (admin)" / "<client>" qui n'apparaît que pour les admins.
✅ **Tableau messages WA dans Rapports/Suivis** : composant `WaMessagesPicker` sous l'éditeur, fetch `/me/whatsapp/history` (filtré client_id pour suivis), checkboxes + bouton "Insérer dans le contenu" qui append un `<h3>+<ul>` formaté au HTML du rapport.
✅ **Version stamp configurable** : 4 champs dans settings (`version_stamp_color/size/opacity/style`) exposés dans `/api/company-info`. `AdminSettings` : color picker + dropdown taille (XS/SM/MD/LG) + slider opacité 10–100% + dropdown style (normal/bold/italic/bold_italic) + aperçu en direct. `VersionStamp.jsx` consomme la conf et applique en temps réel.
✅ **OpenAI key masking** : `openai_api_key` ajouté à la liste des champs masqués (`********` en GET) + traité comme placeholder no-change en PUT. Pattern aligné avec `wa_access_token`, `smtp_password`, etc.
✅ Tests : 18/18 pytest iter19 (~5s) + 12 testids frontend validés. Backend OK 100%, Frontend OK 100%.

### 2026-05-03 — Itération 29 : Politiques publiques (RGPD / Services / Suppression)
✅ Backend : 4 endpoints (3 admin + 1 public) sur 3 slots fixes (`privacy`, `services`, `deletion`).
- `GET /api/admin/policies` → liste avec public_url dynamique (auto-résout via x-forwarded-host pour ingress K8s).
- `POST /api/admin/policies/{slot}/upload` (multipart) → validation : slot ∈ {privacy, services, deletion}, PDF only (content-type ou filename.pdf), max 15 Mo (413), non vide. Écriture atomique via `.pdf.tmp` + rename. Upsert dans `db.policies` avec metadata (filename, size, uploaded_at, uploaded_by, source IP).
- `DELETE /api/admin/policies/{slot}` → unlink fichier + delete doc.
- `GET /api/public/policies/{slot}` → **NO auth required**, sert le PDF inline avec Content-Disposition + X-Robots-Tag:all pour autoriser Google/Facebook crawlers.
✅ Frontend `AdminPolicies.jsx` : 3 cards colorées (emerald/sky/rose) avec gradient header, métadonnées (filename + size + date + auteur), bandeau "Publiée"/"Non publiée", input file caché + bouton "Charger/Remplacer le PDF" avec barre de progression, copy + open du lien public, delete button. Bandeau d'aide en bas explique comment partager les liens à Google/Facebook. Footer marketing public élargi : 3 liens vers les politiques accessibles depuis n'importe quelle page publique du site.
✅ 3 PDFs initiaux uploadés depuis les artefacts utilisateur (privacy 1.5 Mo, services 957 Ko, deletion 536 Ko). URLs publiques actives :
- https://sawali-portal.preview.emergentagent.com/api/public/policies/privacy
- https://sawali-portal.preview.emergentagent.com/api/public/policies/services
- https://sawali-portal.preview.emergentagent.com/api/public/policies/deletion
✅ Tests : 15/15 pytest iter18 + 123/123 cumulé (iter12+13+14+15+16+17+18, ~24s). Couvre auth (401/403), 6 paths de validation, écriture atomique (re-upload), bytes match disk + DB upsert, public route sans auth, 404 sur slot inconnu / non publié, frontend 18 testids + clipboard mock + sidebar nav + footer absolute href.

### 2026-05-03 — Itération 28 : Notes & Tâches CRM par client
✅ Backend : 2 nouvelles collections `client_notes` et `client_tasks`. 7 endpoints admin (3 notes : list/create/delete ; 4 tasks : list/create/update/delete). Validation : note text required + ≤5000 car. ; task title required + due_at ISO valide + status ∈ {open, done}. Auteur (admin) capturé sur création.
✅ Timeline élargie : 7 types désormais (ajout `note` + `task`), counts dict élargi, filtres CSV pré-query intacts. Notes affichent un preview 160 car. ; tasks affichent due_at + statut + flag rappel WhatsApp.
✅ Nouvel événement automation `task.reminder` (SUPPORTED_AUTOMATION_EVENTS étendu). Cron horaire `_task_reminder_cron` (minute=20) qui scanne les tâches `remind_via_whatsapp=true` + `due_at ∈ [now, now+1h]` + `reminder_sent_at=None`, émet l'event puis stamp `reminder_sent_at` (idempotent — pas de double rappel).
✅ Frontend `AdminClientTimeline.jsx` : 2 panels côte à côte au-dessus de la timeline. Notes panel (amber, textarea + add). Tasks panel (fuchsia, title + date + time + checkbox "Rappel WhatsApp 1h avant" + add). Toggle done avec line-through, overdue rose-tinted, suppression avec confirmation. 7 filtres pills colorés (Note amber + Tâche fuchsia ajoutés).
✅ Polish UX (post-test) : boutons delete passent de `opacity-0` à `opacity-60` pour améliorer la découvrabilité tactile.
✅ Tests : 24/24 pytest iter17 + 108/108 cumulé (iter12+13+14+15+16+17, ~23s). Couvre auth, validation, CRUD complet, timeline avec note/task, automation event, cron idempotent (1ère invocation envoie + stamp, 2e invocation no-op). Frontend create→toggle→delete e2e validé. Test iter14 corrigé (`issubset` au lieu d'égalité stricte sur les events).

### 2026-05-03 — Itération 27 : Timeline CRM unifiée par client
✅ Backend : `GET /api/admin/clients/{id}/timeline?types=...&limit=...` (admin-only). Aggregator unifié sur 5 collections (`appointments`, `interventions`, `whatsapp_messages`, `form_submissions`, `documents`). Chaque event normalisé en `{id, type, ts, title, summary, status?, payload}`, tri ISO desc, filtres pré-query par CSV de types, counts calculés après le cap pour refléter ce qui est retourné. 404 sur client inconnu, batch lookup des forms pour résoudre les titres.
✅ Frontend `AdminClientTimeline.jsx` : route `/admin/clients/:id/timeline`. Header client (logo, email, téléphone, code, ville/pays), 5 filtres pills colorés avec compteurs (RDV bleu, Intervention orange, WhatsApp emerald, Formulaire sky, Document slate), groupement par mois avec barre verticale + markers ronds colorés, status pills (emerald/rose/slate selon le statut), bouton "Retour aux clients".
✅ Bouton "Timeline" (icône Activity) ajouté dans `/admin/clients` sur chaque ligne (testid `timeline-client-<id>`).
✅ Tests : 11/11 pytest iter16 + 84/84 cumulé (iter12+13+14+15+16, ~20s). Couvre auth (401/403), shape body, 5 collections sources, sort ISO desc, filtres pré-query, limit, 404. Frontend bouton dans table, 5 filtres avec toggle, navigation back, rendering complet avec 2 interventions seedées.

### 2026-05-03 — Itération 26 : Éditeur de templates Meta WhatsApp
✅ Backend : 2 nouveaux endpoints admin
- `POST /api/admin/whatsapp/templates` (name + language + category + body_text + body_examples + header_text + footer_text). Ordre de validation strict : name regex `^[a-z0-9_]{2,512}$` (auto-lowercase) → catégorie {UTILITY, MARKETING, AUTHENTICATION} → body requis + ≤1024 car. → exemples si `{{N}}` détectés → header/footer ≤60 car. → enfin check Meta config. Soumission via Graph API v21.0 avec components correctement formés (HEADER, BODY+example, FOOTER).
- `DELETE /api/admin/whatsapp/templates/{name}` — supprime toutes les langues du template via Graph API.
✅ Frontend `AdminWaTemplates.jsx` (`/admin/whatsapp-templates`) : liste avec stats par statut (APPROVED/PENDING/REJECTED), filtres pills, modal de création avec auto-transform du nom (lowercase + underscores), détection live des `{{N}}` qui spawn les inputs d'exemples (Meta exige des valeurs réelles), aperçu live coloré, modal de prévisualisation pour chaque template existant. Lien sidebar admin "Templates WhatsApp" (icône FileEdit).
✅ Tests : 20/20 pytest iter15 + 70/70 cumulé (iter12+13+14+15, ~17s). Couvre validation 400, ordre input-first, happy-path POST + DELETE avec monkeypatch httpx.AsyncClient capturant la requête envoyée à Meta, frontend modal complet (10 data-testids vérifiés), auto-transform du nom, toast d'erreur quand exemples manquants.

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

### 2026-05-09 — Iter24 : 4 derniers feedbacks utilisateur
- **Code Unique inaltérable** par contact : helper `_next_contact_unique_code` (compteur Mongo atomique par client/année). Format `YYYY-CLIENTPREFIX-NNNN` (ex. `2026-SAWALISM-0001`). Backfill au démarrage pour tous les contacts existants. Champ ignoré silencieusement par PUT (immutabilité). Affiché en lecture seule dans la fiche contact + dans la ligne du tableau (icône cadenas).
- **RGPD `anon_company`** : nouveau toggle dans `/admin/clients/{id}/features` qui masque la société sous forme `A*** C***` pour les non-privilégiés. Inclus dans `/api/admin/rgpd-preview/{client_id}`.
- **Toggle `wa_sound_alerts` par client** : kill switch admin pour l'alerte sonore WhatsApp. `useWhatsAppNotifier` lit `/me/features` et expose `soundAllowedByAdmin`. PortalLayout grise le bouton + affiche `Bloqué` si désactivé côté client.
- **Restriction photo de contact** : les boutons « Ajouter / Remplacer / Retirer » sont désactivés pour les rôles standards (`client`, tracked) ; seuls `admin/superviseur/moderateur` peuvent modifier. Tooltip explicatif.
- **Auto-sync nom WA via webhook** : à la réception d'un message WA, si `contact.name` est vide ou n'est qu'un numéro de téléphone, il est automatiquement remplacé par `profile.name`. ⚠️ Meta n'expose **pas** la photo de profil via Cloud API — seul le nom est synchronisable, ce qui est désormais documenté en infobulle.
- **Bug fix tracked-user inheritance** : la création/mise à jour des comptes utilisateurs suivis copie désormais `parent_client_id` également dans `client_id` (legacy field utilisé par 50+ endpoints). Migration startup pour les comptes existants. Effet : les utilisateurs suivis héritent désormais réellement des flags RGPD + features de leur client parent.
- Tests : `/app/backend/tests/test_sawali_iter24.py` (10 tests, 100% pass).

### 2026-05-09 — Iter25 : P1 WhatsApp Bulk
- **Nouveau module `/portal/whatsapp-bulk`** : envoi de templates Meta WhatsApp Business approuvés à plusieurs contacts en une fois, avec personnalisation par destinataire.
- Endpoint `POST /api/me/whatsapp/bulk` (model `MeWaBulkRequest`) : prend `contact_ids[]`, `template_name`, `language_code`, `variables[]` (corps), `header_text`, `header_media`, `button_vars[][]`, `scheduled_at?`. Cap 500 destinataires, validation +30 s.
- Branche **envoi immédiat** : itère les contacts dans le scope client, construit un `ctx` par contact (`{{name}}`, `{{company}}`, `{{phone}}`, `{{email}}`, `{{client_code}}` = `unique_code`), appelle `_wa_send_template`, log dans `whatsapp_messages` avec `bulk: true`.
- Branche **planification** : insère un doc dans `whatsapp_schedules` avec `recipients[].kind='contact'`, `bulk: true`. Le cron `_run_scheduled_whatsapp` reconnaît désormais le kind `contact` (en plus de `client` et `tracked`).
- UI `WaBulk.jsx` (~530 lignes) : sélecteur de template avec aperçu de la structure parsée, génération automatique des champs variables (header/corps/boutons) selon le template, barre d'insertion de jetons (`{{name}}`, `{{client_code}}`…), filtres contacts (recherche + société), aperçu personnalisé sur 3 destinataires, planification, historique des envois groupés. Lien sidebar « WhatsApp — Masse & Planif. ».
- Tests : `/app/backend/tests/test_sawali_iter25.py` (10 tests, 100% pass) + Playwright frontend (9/9 testids).

### 2026-05-09 — Iter26 : 3 fixes UI + WhatsApp→SMS fallback
- **BUG fix Subscriptions double header** : retiré le `<MarketingLayout>` interne dans `Subscriptions.jsx` (PublicRoute fournit déjà le layout).
- **FEATURE Header sticky avec jauge intégrée** : ajout d'un bandeau fin au sommet de `MarketingNav` (sticky) contenant la jauge de Support technique (`SupportLoadGauge inline`) avec barres cellulaires colorées et label centré (« 🎧 Support |||| Charge modérée 4/7 »). Disparaît automatiquement quand l'admin désactive la jauge.
- **BUG fix sidebar tronquée** : `PortalLayout` passé en *fixed-shell pattern* — outer div en `h-screen flex overflow-hidden`, sidebar `h-screen overflow-y-auto`, main aussi `h-screen overflow-y-auto`. Le bug `position:sticky` dans flex-row qui causait la troncature après scroll est éliminé.
- **CRITICAL bug fix** : axios interceptor 401 ne forçait plus le redirect vers `/login` que si un token était présent en localStorage. Avant, tout visiteur anonyme des pages publiques (`/`, `/subscriptions`, etc.) était immédiatement renvoyé vers `/login` dès qu'un composant tapait `/me/*` — site marketing inutilisable pour les nouveaux visiteurs.
- **FEATURE WhatsApp→SMS fallback** : `MeWaBulkRequest` étendu avec `sms_fallback`, `sms_fallback_message`, `sms_fallback_provider`, `sms_fallback_sender`. En cas d'échec WA (numéro non WA, hors fenêtre 24h, erreur Meta…), tentative automatique en SMS via `_sms_dispatch` avec personnalisation par destinataire. Les logs `sms_messages` créés portent `wa_fallback: true` pour traçabilité. Réponse enrichie : `fallback_used`, `fallback_results[]`, `fallback_ok`. Le cron runner applique aussi le repli pour les envois planifiés.
- UI `WaBulk.jsx` enrichie : bloc « Repli SMS automatique » avec toggle, sélecteur de fournisseur SMS, expéditeur, message-template (avec jetons), désactivé si `features.sms === false`.
- Tests : iter26 backend (3/3 pass), frontend Playwright bloqué par bug pré-existant axios → corrigé dans cette même itération.

### 2026-05-09 — Iter27 : Campaign Efficiency Dashboard
- **Nouveau endpoint** `GET /api/admin/campaign-efficiency?days=N` (admin only, days clamped 1-90) : agrège WA outbound (en excluant `direction:inbound`), SMS, et SMS de repli (`wa_fallback:true`). Retourne taux de délivrance WA & SMS, taux de repli (succès + déclenchement sur échecs WA), économie estimée (`wa.sent_ok × sms_unit_cost_avg`), et série quotidienne strictement de N jours.
- **Nouvelle section dans `/admin/usage`** : « ⚡ Efficacité de campagne — stratégie WhatsApp-first » avec 4 KPI cards (Délivrance WA, Délivrance SMS, Repli SMS, Économie estimée) + BarChart empilé (3 stack groups : WA, SMS, fallback) sur 30 jours glissants. Re-fetch automatique au changement de période.
- Tests : `/app/backend/tests/test_sawali_iter27.py` — 9/9 pytest pass + frontend confirmé live (4 KPIs + chart + re-fetch sur sélection de période).

### 2026-05-09 — Iter28 : 🚨 HOTFIX production — récupération des contacts orphelins
- **Root cause** : la migration iter24 (mirror `client_id ← parent_client_id` sur les comptes bridgés) a déplacé le scope de lecture des utilisateurs suivis. Les contacts/messages créés AVANT iter24 étaient tagués `client_id = user.id` (fallback du legacy code) et sont devenus invisibles après iter24 (le scope filtre maintenant sur `parent_client_id`).
- **Fix** : nouvelle fonction `_migrate_orphan_client_data(dry_run)` qui re-tague les rows orphelines vers le `parent_client_id`, en conservant l'ancien `client_id` dans `client_id_legacy` (traçabilité + rollback). Couvre `directory_contacts`, `whatsapp_messages`, `sms_messages`, `whatsapp_schedules`, `payment_links`. Idempotente (guard `client_id_legacy: $exists:false`).
- **Auto au startup** : la migration s'exécute automatiquement au prochain boot (logguée si `total_migrated > 0`).
- **Endpoint admin** : `GET /api/admin/migrate-orphan-data` (dry-run, prévisualise) et `POST /api/admin/migrate-orphan-data` (apply). Permet le contrôle manuel sans redémarrer.
- **Bug Mongo collatéral** : `{"$ne": None, "$ne": ""}` (dict-key collision) remplacé par `{"$nin": [None, ""]}` dans 2 endroits.
- Tests : reproduction réelle en preview (3 contacts orphelins + WA + SMS d'un user bridgé synthétique) → migration recovers 5/5 docs, idempotence vérifiée (2e dry-run = 0).

### 2026-05-09 — Iter28b : UI admin migration + canari de régression
- **Section UI dans `/admin/settings`** : « 🔧 Diagnostic des données orphelines » avec dry-run automatique au chargement, compteurs par collection, liste des utilisateurs affectés, bouton « Appliquer la migration » (avec confirm) et bouton « Actualiser ».
- **Canari de régression au boot** : après l'auto-migration, un dry-run vérifie qu'aucun orphelin ne subsiste. Log `WARNING` immédiat si détection (futur changement de code introduisant un nouveau cas).
- Test reproducer : 5 contacts orphelins synthétiques → dry-run via endpoint admin → `total_migrated: 5` détecté correctement.

### 2026-05-10 — Iter29 : Modèle collaboratif des contacts (shared by default)
- **Changement de modèle** : tous les contacts du Centre de Messagerie sont désormais visibles ET modifiables par tous les utilisateurs du même client (cohérent avec la Bibliothèque de Médias).
- **Backend** :
  - `GET /api/me/contacts` ne filtre plus que sur `client_id` (suppression du filtre `shared:true`/`owner_id`).
  - `PUT /api/me/contacts/{cid}` autorise tout user du même client (plus seulement le propriétaire ou admin).
  - `DELETE /api/me/contacts/{cid}` même règle.
  - `POST /api/me/contacts` force `shared:true` à la création (cohérence des futures lectures par d'éventuels filtres legacy).
  - Audit : champs `last_edited_by_id`, `last_edited_by_label`, `last_edited_at` stampés quand l'éditeur n'est pas le propriétaire.
- **Migration startup `iter29`** : normalise tous les contacts existants à `shared:true` (idempotent — testé : « 1 row normalized » sur un contact legacy `shared:false`).
- **Frontend `Contacts.jsx`** : badge « 🤝 Équipe » + sous-titre « par {owner_label} », encart explicatif « Visible par toute l'équipe », default `shared:true`.
- **Bibliothèque de Médias** : déjà entièrement partagée par client.
- Tests reproducteurs : 2 users (Alice, Bob) du même client → contact privé créé par Alice → Bob LE VOIT, L'ÉDITE avec succès.

### 2026-05-10 — Iter30 : Diagnostic & réalignement client par utilisateur
- **Constat** : iter29 ne suffit pas si deux users d'un même client n'ont pas le même `client_id` en base (cas réel signalé : `jfrancois.ouoba@gmail.com` et `ines.zoundi@sawalismartsystems.com` du client SAWALI-2S avaient des scopes séparés).
- **Backend** :
  - `GET /api/admin/client-data-diagnostic?email=…` — résout le client canonique d'un user via priorité : `parent_client_id` → admin de même `company` → self si admin/superviseur. Retourne pairs, scopes effectifs, plan de réalignement détaillé (set_user_client_id + retag par collection).
  - `POST /api/admin/realign-user-to-client {email, dry_run?}` — applique le plan, conserve l'ancien `client_id` dans `client_id_legacy`. Idempotent.
- **Frontend `AdminSettings.jsx`** : nouvelle section bordée bleue « 🔍 Diagnostic visibilité par utilisateur » avec input email, bouton diagnostiquer, affichage user/canonique/pairs/plan, bouton « Appliquer le réalignement ».
- **Test E2E** : reproducer scenario prod (Ines admin SAWALI-2S, JF tracked sans `parent_client_id`, contacts éparpillés sur 2 ids) → diagnostic identifie le canonique via `company match`, applique le plan, JF passe de 2 à 5 contacts visibles, Ines passe à 5 aussi, ownership préservé.

### 2026-05-10 — Iter31 : Canari de cohérence multi-utilisateurs
- **Helper** `_scan_clients_consistency()` — groupe les users par `company` (case-insensitive, trim, exclut comptes désactivés), résout le canonique (admin/superviseur > client_id majoritaire), liste les membres dont le scope effectif diffère du canonique.
- **Boot canary** : log `WARNING` au démarrage si des désalignements sont détectés (résumé global + jusqu'à 10 groupes détaillés). Aucune donnée modifiée — read-only.
- **Endpoint** `GET /api/admin/clients-consistency` — vue panoramique pour l'UI.
- **Section UI dans `/admin/settings`** : « 🟣 Cohérence multi-utilisateurs (panoramique) » bordée violette, affiche le résumé scanné/aligné/désaligné, déroule chaque groupe désaligné avec un bouton « Réaligner » par utilisateur (qui appelle `/admin/realign-user-to-client`). Bandeau vert si tout est cohérent.
- **Test E2E** : 3 users SAWALI-2S (Ines admin + JF désaligné + Sara alignée) → canary boot logue exactement « 1 user(s) misaligned across 1 company group(s) » + endpoint retourne le détail correct.

### 2026-05-10 — Iter32 : Auto-link à la création (prévention à la source)
- **Constat** : iter31 détecte les désalignements après coup. Iter32 les empêche dès la création d'un nouvel utilisateur dans `/admin/clients`.
- **Backend** :
  - Champ optionnel `link_to_client_id` ajouté à `UserCreateAdmin` (models.py).
  - Endpoint `GET /api/admin/resolve-company?company=...` — retourne `{found, canonical_user, member_count}` pour suggérer le client canonique d'un nom d'entreprise.
  - `POST /api/admin/clients` honore `link_to_client_id` : mirrore `parent_client_id` et `client_id` sur le canonique → l'utilisateur hérite immédiatement des contacts, médias, RGPD, features, facturation.
- **Frontend `AdminClients.jsx`** : à la sortie du champ « Entreprise » (onBlur), appel `/admin/resolve-company`. Si une entreprise existe déjà → bandeau violet **« Une entreprise X existe déjà (N membres) »** avec checkbox **« Lier ce nouvel utilisateur au client canonique »** (recommandé, coché par l'admin). Affiche le canonique (nom, email, rôle).
- **Test E2E** : création admin TEST-IT32 → resolve-company détecte canonique → création membre AVEC link → `parent_client_id`+`client_id` mirrorés correctement → création UNLINKED → désaligné → iter31 canary détecte 1/3 misaligned.

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

## Iter34 (2026-05-10) — DB Snapshots + Visibilité contacts + Société autocomplete + Auto-snapshot hebdo + Email + Rapport PDF
- **Backend** : 6 endpoints `/api/admin/snapshots*` pour exporter/importer/lister/modifier/supprimer des snapshots de toutes les collections métier. Fichier `.json.gz` téléchargeable, masquage des secrets API par défaut. Mode import : `replace`, `merge`, ou `dry_run`. Tous les imports loggés dans `db_snapshot_imports`.
- **Backend (Iter34b)** : Cron hebdomadaire `db_auto_snapshot_weekly` + endpoint `POST /api/admin/snapshots/auto-run`. Rotation configurable (1..52, défaut 4). `kind="auto"` rotent, `kind="manual"` jamais purgés.
- **Backend (Iter34c)** : Envoi email automatique du snapshot en pièce jointe (`.json.gz`). `email_service.send_email()` accepte désormais `attachments=[]` (liste, anciennement `attachment={}` toujours supporté). Timeout SMTP étendu à 45s avec pièces jointes.
- **Backend (Iter34d)** : Module `/app/backend/health_report.py` génère un rapport PDF hebdomadaire via **reportlab 4.5**. Contenu : KPIs 7 jours avec **arrows WoW ↑/↓/= et "vs S-1"** (Iter34f), 3 graphiques de tendance 30 jours (sparklines), **section "Connexions & pages visitées"** (Iter34f, top 5 utilisateurs + top 5 pages), état plateforme, 5 derniers contacts, fiche snapshot. Endpoint `GET /api/admin/snapshots/weekly-report-preview`.
- **Backend (Iter34f)** : Nouvel endpoint `GET /api/admin/user-activity` avec filtres `period` + `company`. Renvoie `last_logins`, `top_pages`, `totals` + `company_options`. Lit `db.access_logs` agrégé via Mongo aggregation pipelines.
- **Backend (Iter34g)** : Nouvel endpoint `GET /api/admin/user-activity/heatmap` qui retourne une matrice 7×24 (Mon→Sun × 0h→23h, UTC) des hits cumulés. Filtres `period` + `company`. Bucket en mémoire via `datetime.weekday()` + `.hour`.
- **Backend (Iter34g)** : Heatmap aussi rendue dans le PDF hebdomadaire avec coloration RGB pré-mélangée sur blanc (alpha-blending opaque pour compatibilité PDF readers), texte blanc en gras pour les cellules denses, "·" gris clair pour les cellules vides, marqueurs d'heure tous les 3h.
- **Frontend (Iter34f+g)** : `UserActivityCard` étendu avec 3 mini-KPIs + 2 tables (logins / pages) + **carte de chaleur 7×24 interactive** (cellules cliquables avec tooltip "Jeu 21h — 49 visites", légende Faible→Élevée). Filtres période + société.
- **Bug fix mobile (Iter34g)** : La jauge support technique disparaissait sur mobile à cause de `hidden md:block` dans `MarketingNav.jsx`. Fix : suppression du `hidden`, gauge inline rendue plus compacte (`px-2 sm:px-4`, label tronqué à 150px max sur mobile, hour markers avec icône Headphones toujours visible).

## Iter34h (2026-05-10) — Suivi des actions + Bugfix RGPD SMS/WA

## Iter34i (2026-05-10) — CSV export + Pipeline admin + Version auto-bump + Reset usage
- **Backend** : `POST /api/admin/roadmap-actions` (création auto-numérotée par admin) + `DELETE` (protège les 16 entrées seed historiques HTTP 403) + `PATCH` étendu pour toggler `done` (auto-rempli `done_at`) et éditer title/backlog_ref/details/duration_h. Cost auto-recalculé via `duration_h × 25 000 XOF/h`.
- **Backend** : `/api/version` calcule dynamiquement `1.<N>` où N = `count(roadmap_actions, done=true)`. Auto-bump à chaque livraison sans redéploiement.
- **Backend** : `POST /api/admin/visits/reset` accepte `{purge_access_logs: bool}`. Mode `false` (défaut) → offset only. Mode `true` → suppression définitive des `visits` + `access_logs` + reset offset.
- **Frontend** : Bouton "Nouvelle action" (form inline), toggle ✓ FAIT/À FAIRE cliquable, bouton suppression, et "Exporter CSV" (RFC 4180 + BOM UTF-8).
- **Frontend** : Composant `ResetUsageButton` dans `/admin/usage` avec panneau de confirmation (checkbox "Purge complète" + confirm fort).

## Iter34j (2026-05-10) — Vue Kanban À faire / En cours / Réalisée

## Iter34k (2026-05-10) — Page "Mon compte" + Demande de modification
- **Backend** : `GET /api/me/account-detail` retourne identity (nom, email, role, phone, whatsapp, avatar, company, birth_date), parent_client (employer rattaché), last_seen_at (avant-dernière connexion, pas la session courante), et counters (reports, suivis, contacts visibles via `_resolve_visible_client_ids`).
- **Backend** : `POST /api/me/profile-update-request` enregistre une demande de modification (message + liste de champs ciblés) dans `db.profile_update_requests` avec status=pending. Validation message obligatoire et ≤1500 caractères.
- **Frontend** : Nouvelle page `/portal/my-account` avec avatar/initiales gradient, sections Identité + Société & rattachement (toutes en **lecture seule** avec icône cadenas), bandeau "Dernière connexion", 3 KPI cards (Rapports/Suivis/Contacts), et formulaire "Demande de modification" (6 checkboxes pré-définies + textarea + bouton "Envoyer à l'admin").
- **Frontend** : Link `account-menu-link` ajouté au pied de la sidebar du portail (clic sur "Connecté en tant que" → ouvre `/portal/my-account`).
- **Validation** : 4 tests curl ✓ (account-detail retour complet, post request OK, message vide → 400, fields filtré à 10 max). Screenshot UI confirme tous les blocs rendus avec icônes cadenas visibles et données réelles de l'admin.
- **Backend** : Nouveau champ `status` sur `roadmap_actions` (enum `todo|in_progress|done`). Backfill automatique au prochain `GET /admin/roadmap-actions` (rows pré-existantes héritent `status` depuis `done`). PATCH `{status}` sync auto le boolean `done` + `done_at`. Validation HTTP 400 sur status invalide.
- **Backend** : Totaux étendus : `done`, `in_progress`, `pending` (auparavant seulement done/pending). `POST /admin/roadmap-actions` accepte `status` optionnel à la création.
- **Frontend** : Switcher **Tableau / Kanban** dans la section Suivi. Vue Kanban 3 colonnes (amber/sky/emerald) avec compteurs, cartes (code+titre+backlog+durée+coût), boutons "Déplacer →" pour basculer vers les 2 autres colonnes en 1 clic, et icône suppression sur chaque carte (seed protégé HTTP 403).
- **Frontend** : Filtres étendus à 4 onglets (Toutes / Réalisées / En cours / À faire), synchronisés entre vue Tableau et Kanban.
- **Validation curl** : 5 transitions testées (in_progress → done → todo + status invalide → 400). Backend retourne `status: "done"` pour tous les seeds après backfill. Screenshot UI confirme 3 colonnes rendues avec 23 cartes correctement réparties (1/1/21). ✓
- **Backend** : `POST /api/admin/roadmap-actions` (création auto-numérotée par admin) + `DELETE` (protège les 16 entrées seed historiques HTTP 403) + `PATCH` étendu pour toggler `done` (auto-rempli `done_at`) et éditer title/backlog_ref/details/duration_h. Cost auto-recalculé via `duration_h × 25 000 XOF/h`.
- **Backend** : `/api/version` calcule dynamiquement `1.<N>` où N = `count(roadmap_actions, done=true)`. Auto-bump à chaque livraison sans redéploiement.
- **Backend** : `POST /api/admin/visits/reset` accepte `{purge_access_logs: bool}`. Mode `false` (défaut) → offset only (données conservées, compteur affiché 0). Mode `true` → suppression définitive des `visits` + `access_logs` + reset offset.
- **Frontend** : Section Suivi étendue avec bouton "Nouvelle action" (form inline : titre + backlog_ref + détails + durée), bouton toggle ✓ FAIT/À FAIRE sur chaque ligne, bouton suppression (corbeille) sur chaque ligne, et bouton "Exporter CSV" (RFC 4180 + BOM UTF-8).
- **Frontend** : Composant `ResetUsageButton` dans `/admin/usage` avec panneau de confirmation (checkbox "Purge complète" + confirm fort).
- **Validation curl** : `/version` → "1.16" puis "1.17" après création d'une action done, retour "1.16" après suppression. Seed protégé : DELETE ACT-0001 → HTTP 403. Purge complète : 1735 visits + 608 access_logs supprimés ✓.
- **Backend** : Nouvelle collection `db.roadmap_actions` (auto-numérotation `ACT-0001…`) avec seed initial de 16 actions livrées dans cette session. Endpoints : `GET /api/admin/roadmap-actions` (liste + totals) et `PATCH /api/admin/roadmap-actions/{code}` (seul `observations` modifiable, autres champs verrouillés HTTP 400).
- **Frontend** : Composant `RoadmapTrackerSection` dans `/admin/settings` (bulle NOUVEAU). 4 KPI cards (total/réalisées/durée cumulée/coût cumulé @ 25 000 XOF/h), filtre Toutes/Réalisées/À faire, tableau avec N°, dates, action+backlog+détails, durée, coût, état, et zone Observations éditable inline (textarea → bouton Enregistrer).
- **Backend BugFix RGPD** : Helper `_resolve_real_phone(contact_id, field, fallback)` qui restaure le numéro réel depuis `db.directory_contacts` quand un contact_id est fourni. Évite que les numéros masqués par l'anonymisation arrivent jusqu'aux providers SMS/WA. Appliqué à `/me/whatsapp/send`, `/me/whatsapp/send-text`, `/me/sms/send`.
- **Validation curl** : Envoi SMS avec `to="+225 ** *** ****"` + contact_id valide → backend résout et stocke `msisdn="+22507123456"` (numéro réel) ✓. Roadmap : 16 entrées seedées, PATCH observations OK, PATCH champ verrouillé rejeté ✓.
- **Snapshot** : `roadmap_actions` ajoutée à la liste des collections exportées (donc l'historique est inclus dans le `.json.gz`).

- **Backend** : Helper `_resolve_visible_client_ids(user)` bridge automatiquement les contacts entre utilisateurs partageant le même `company` (case-insensitive, regex échappé). Appliqué à `me_list_contacts`, `me_update_contact`, `me_delete_contact`.
- **Frontend** : Section "Sauvegarde de la base (Snapshot)" dans `/admin/settings` avec UI d'export, historique éditable + badges AUTO/MANUEL, import (replace/merge + dry-run), bloc auto-snapshot (toggle + rotation + run-now + dernière exécution), bloc email (toggle + adresse + bouton **"Aperçu du rapport PDF"** + statut dernier envoi).
- **Frontend (Iter34f)** : Nouveau composant `UserActivityCard` dans `/admin/usage` (placé sous les KPI totaux). Affiche 3 mini-KPIs (visites/utilisateurs actifs/sociétés actives), tableau "Derniers utilisateurs connectés" (nom + email, société, dernière activité, nombre de visites), tableau "Top pages visitées" (module, page, visites, utilisateurs uniques). Filtres période (Aujourd'hui / 7j / 30j / 90j / 1 an) + dropdown société.
- **Frontend** : Champ "Société (client)" dans la modale Contacts → `<input list>` + `<datalist>` HTML5 (autocomplete natif).
- **Validation** : 12/12 backend pytest, 8/8 frontend criteria, 3 scénarios email curl-testés, PDF généré 3.2 kB (`%PDF-1.4`), `pdf_attached:True` confirmé dans la réponse de auto-run.
- **Suite régression** : `/app/backend/tests/test_iter34_snapshots.py`.

## Iter35 / Backlog suite
### 🟧 P1 (prochaine session)
- Snapshot v2 : validation de `version` au moment de l'import (future-proof)
- UX merge : ajouter un confirm doux pour le mode `merge` (actuellement seul `replace` confirme)

### 🟨 P3 (Actions futures)
- **"Aperçu rapide" drawer Contacts** — drawer latéral cliquable sur chaque ligne avec info contact + 3 derniers WA/SMS + actions rapides (envoyer WA/SMS/email, créer RDV, voir documents).

### 🟦 P0 technique persistant
- **Refactor `server.py`** (>12 900 lignes) → modules `/app/backend/routes/*.py` — session dédiée requise

## Backlog priorisé (mise à jour 2026-05-10)
### 🟧 P1 (à faire prochainement)
1. **Export/Import snapshot DB** (Production → Preview) : créer `GET /api/admin/export-snapshot` (gzip JSON anonymisé) + `POST /api/admin/import-snapshot`. UI dans `/admin/settings` ou `/admin/usage`.
2. **Dropdown autocomplete "Société"** dans `Contacts.jsx` (remplacer le champ texte libre par un sélecteur basé sur les sociétés existantes).
3. **Issue 3 — Visibilité partagée des contacts** entre utilisateurs de la même société : auditer `get_contacts` / `me_contacts` pour garantir que tous les users du même `client_id` / `parent_client_id` voient et éditent les mêmes contacts.

### 🟦 P0 technique
- **Refactor du monolithe `server.py`** (>12 500 lignes) → `/app/backend/routes/` modulaire. Session dédiée requise.

### 🟨 P2 / P3
- **Drag & drop HTML5 sur le Kanban** (P3) — déplacer les cartes entre colonnes par glisser-déposer en plus des boutons actuels. Améliore l'UX fluide sans casser la simplicité existante (~30 min).
- Transkribus OCR (manuscrits)
- Caisse, Facturation, Catalogue, Tickets
- Génération PDF côté serveur, Stripe Checkout
- **Notifications proactives heatmap** (Iter34g sugg.) — détecter les pics d'activité anormaux (Mardi 14h +200% vs habitude) en comparant la heatmap courante à un baseline historique, et alerter l'admin via webhook Discord ou email
- **Intégration Meta — Facebook Pages + Messenger + Ads** (P2, ~2-3 semaines) :
   - Pages : publication, scheduler, lecture commentaires/likes/insights
   - Messenger : webhook + envoi messages + bot conversationnel (architecture similaire à WhatsApp existant)
   - Marketing API : campagnes pub, audiences custom depuis contacts CRM, reporting consolidé
   - Pré-requis : Meta Business Manager vérifié, App Meta Developer + App Review, permissions `pages_manage_posts`, `pages_messaging`, `ads_management`, tokens longue durée
   - Démarrage recommandé : Pages + Messenger d'abord (effort modéré, ROI immédiat), Ads en seconde phase
