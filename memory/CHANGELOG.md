# CHANGELOG — SAWALI SMART SYSTEMS

Historique détaillé des iters récents. Voir `PRD.md` pour la spec statique.

## 2026-03 — Iter43-fix8 — Élargissement des droits d'édition Interventions

### Demande utilisateur
> « Pour /portal/interventions il faut que l'admin (en plus du superviseur) puisse aussi modifier la fiche d'intervention. »

### Backend
- `PUT /admin/interventions/{int_id}` → `get_admin_or_supervisor` (au lieu de `get_current_admin`).
- `POST /admin/interventions/{int_id}/unlock-invoice` → `get_admin_or_supervisor`.
- `PUT /admin/invoices/from-interventions/{inv_id}` (paiement) → `get_admin_or_supervisor`.

### Frontend
- `isAdminOrSup` dans `Interventions.jsx` étendu à `user.role in ('admin','superviseur')` **OU** `user.tracked_role in ('Administrateur','Superviseur')` (couvre les tracked-users promus admin/sup côté tenant).

### Tests
- Régression : 25/25 pytest PASS sur iter56 + iter43-fix6 + iter43-fix5.

---


## 2026-03 — Iter43-fix7 — Optimisation `last_interaction_at` + bug fix collection

### Bug critique fixé
- `me_list_contacts` scannait `db.wa_messages` mais la **vraie collection** est `db.whatsapp_messages` (utilisée à 9+ endroits dans server.py pour les inserts WA). Conséquence : le champ `last_interaction_at` retourné en iter43-fix5 était **TOUJOURS null** en production (sauf pour les SMS). 🐛
- Correctif : changement de collection + même logique d'enrichissement digits-10.

### Optimisations
- **Limite réduite** de 20 000 → 10 000 messages les plus récents scannés par appel.
- **Indexes ajoutés** (idempotent, créés au startup) :
  - `whatsapp_messages` : `created_at` desc, `timestamp` desc, `from`, `to`
  - `sms_messages` : `created_at` desc, `from`, `to`
  - `interventions_invoices` : `(tenant_id, created_at desc)`, `invoice_number`
- **Projection ciblée** : seuls `from/to/timestamp/created_at/received_at/sent_at` sont fetchés.

### Tests
- `test_iter43_fix5_last_interaction_at.py` mis à jour pour utiliser `whatsapp_messages` (3/3 PASS).
- Régression sur 25 tests (fix5 + fix6 + iter56) + 34 tests (error_registry + tenant_sharing + bulk + interventions_history) = **59/59 PASS**.

---


## 2026-03 — Iter43-fix6 — Suivi paiement factures interventions

### Contexte
Demande utilisateur : remplacer la suggestion d'envoi automatique par un suivi du **retard de paiement** calculé à partir de la **date/heure de dépôt** de la facture (par opposition à la date d'émission). Permet de tracer le délai client.

### Backend (`server.py`)
- `interventions_invoices` étendu avec : `deposited_at` (ISO), `paid_at` (ISO), `due_days` (int, 30 par défaut).
- **`PUT /api/admin/invoices/from-interventions/{inv_id}`** (admin/sup) — accepte `deposited_at`, `paid_at`, `due_days`, `clear_deposited_at`, `clear_paid_at`. Renvoie la facture enrichie.
- **`GET /api/me/invoices/from-interventions`** — chaque item enrichi avec `payment_status` (paid|unpaid|cancelled) et `days_overdue` (int ou null).
- **PDF facture** — affiche maintenant la ligne « Date/heure de dépôt » + tampon vert « PAYÉE le … » ou tampon rouge « EN RETARD DE N JOUR(S) ».
- Helper `_enrich_invoice_payment(inv)` mutualise le calcul.

### Frontend (`Interventions.jsx`)
- Nouveau panneau repliable **« Factures émises »** (admin/sup, `data-testid=invoices-panel`) avec badges « N en retard » (rouge), « N payée(s) », « N en attente ».
- Tableau : N° Facture, Tenant, Total, Dépôt, Échéance, Paiement, Retard, Actions.
- **EditInvoicePaymentModal** (`invoice-edit-modal`) avec datetime-local pour Dépôt/Paiement, boutons « Maintenant » et « Marquer payée ».
- Lignes en retard : pastille rouge animée + texte « X j de retard ».

### Bug critique fixé par testing agent
- MongoDB rejetait l'update simultané `$set: {field: None}` + `$unset: {field: ""}` sur le même champ (WriteError code 40). Correctif : ne pas inclure le champ dans `$set` quand `clear_*=true` ; seul `$unset` reste.

### Tests
- `/app/backend/tests/test_iter43_fix6_invoice_payment_tracking.py` — **12/12 PASS** + régression iter56 (10/10) = **22/22**.
- E2E UI : panneau visible, testids conformes, badges et colonnes OK (`iteration_58.json`).

---


## 2026-03 — Iter43-fix5 — UX Registre Erreurs + Tri Contacts

### Frontend
- **ErrorRegistry.jsx** — Les lignes non-lues (`acknowledged=false`) sont maintenant affichées en **rouge vif gras** (`text-rose-700 font-semibold`) avec une **pastille rouge** devant la date ; les lignes lues sont en **italique gris** (`italic text-slate-500`). Attribut `data-read="unread"|"read"` ajouté pour les tests.
- **Contacts.jsx** — Nouveau sélecteur de tri (`data-testid=contact-sort`) avec 3 options : **Interaction (plus récente) [défaut]**, Nom A→Z, Nom Z→A. Les contacts sans interaction tombent en fin de liste en mode interaction_desc.

### Backend
- **`GET /api/me/contacts`** — Enrichi avec un champ `last_interaction_at` calculé à partir de `wa_messages` + `sms_messages` (match sur les 10 derniers chiffres du numéro WA/téléphone). Null pour les contacts sans aucun message.

### Tests
- `test_iter43_fix5_last_interaction_at.py` — 3/3 PASS (field present, null fallback, populated for matched contact).
- Frontend E2E validé (iteration_57.json).

### À surveiller (commentaire test agent)
- Le scan complet `db.wa_messages.find({}).limit(20000)` à chaque appel `/me/contacts` peut devenir lent à grande échelle. Optimisation possible : pré-match sur les digits10 visibles via aggregate.

---


## 2026-03 — Iter43-fix4 — Facturation des Interventions

### Contexte
Demande utilisateur : permettre aux Admin/Superviseur (1) de corriger une intervention (tenant, durée, …), (2) sélectionner plusieurs interventions et générer une facture PDF groupée par tenant, (3) verrouiller (griser) les interventions facturées avec colonne « N° Facture ».

### Backend (`server.py`)
- **`POST /api/me/invoices/from-interventions`** (admin/sup) — groupe par `client_id`, auto-numérote `INV-YYYY-NNNNN`, calcule total au taux horaire tenant (fallback `settings.global.default_intervention_hourly_rate_xof`), insère dans `db.interventions_invoices`, verrouille les interventions avec `invoiced=True / invoice_id / invoice_number`. Devise **XOF** sans TVA.
- **`GET /api/me/invoices/from-interventions`** — admin voit tout (filtre `tenant_id` optionnel) ; tenant voit seulement les siennes.
- **`GET /api/me/invoices/from-interventions/{id}/pdf`** — PDF SAWALI Standard (en-tête, motif, taux horaire, tableau lignes, total, mention « ANNULÉE » si statut cancelled).
- **`PUT /api/admin/interventions/{id}`** — édition admin (tenant/durée/titre/statut/tech/date). Renvoie **409** si déjà facturée.
- **`POST /api/admin/interventions/{id}/unlock-invoice`** — déverrouille l'intervention (la facture reste valide).

### Frontend (`pages/portal/Interventions.jsx`)
- Colonne checkbox + master checkbox (`interventions-select-all`, `intervention-select-{id}`) — visibles admin/sup, désactivées sur lignes facturées.
- Bouton **« Générer facture(s) »** vert (`interventions-invoice-btn`) avec compteur dynamique → confirm → POST → téléchargement auto de chaque PDF → reload.
- Nouvelle colonne **« N° Facture »** : badge cliquable (`intervention-invoice-link-{id}`) re-télécharge le PDF.
- Lignes facturées **grisées** (`bg-slate-50 text-slate-400`), checkbox + boutons Modifier/Supprimer masqués, bouton **Déverrouiller** (`intervention-unlock-{id}`) visible.
- **EditInterventionModal** (`intervention-edit-modal`) admin/sup — édite tenant, titre, description, date, statut, technicien, durée. Save → PUT `/admin/interventions/{id}`.

### Tests
- `/app/backend/tests/test_iter56_intervention_invoicing.py` — **10/10 PASS** (403 client, 400 vide, 409 toutes facturées, génération multi-tenant, PDF, list, edit OK, edit 409 sur facturée, unlock, regression).
- E2E UI validé : login admin → Interventions → sélection 2 interventions de 2 tenants → 2 factures (INV-2026-00006/00007) → PDFs téléchargés → badges UI + boutons Déverrouiller affichés correctement.

### Modèle DB
- Collection nouvelle : `interventions_invoices` (id, invoice_number, tenant_id, tenant_name, motif, hourly_rate_xof, lines[], total_xof, currency='XOF', status, intervention_ids[], created_at, created_by_*).
- `interventions` : nouveaux champs `invoiced`, `invoice_id`, `invoice_number`, `invoiced_at`, `invoiced_by`, `unlocked_at`, `unlocked_by`.

---


## 2026-03 — Iter43-fix3 — Diagnostic & Monitoring WhatsApp

### Contexte
L'utilisateur reporte un pattern récurrent : *« les templates WhatsApp marchent 2 jours puis brusquement plus rien ne donne »*. Cause probable : **token utilisateur 24 h** copié depuis le dashboard Developers Meta (au lieu d'un token System User permanent).

### Backend
- **`GET /api/admin/whatsapp/token-health`** (admin) — appelle `debug_token` Meta + test fonctionnel sur le `phone_number_id`. Retourne :
  - `token_type` (USER vs **SYSTEM_USER**)
  - `expires_at` + `days_to_expiry` (null = permanent)
  - `is_valid`, scopes, app_id
  - `phone_check` : display_phone_number, verified_name, **quality_rating**
  - `warning` ergonomique si USER < 7 jours ou type USER tout court
- **Cron quotidien** (07:30 Africa/Abidjan) — `wa_token_health_daily` : envoie un email à TOUS les admins actifs si le token est invalide OU expire dans <7 jours.

### Frontend
- **AdminSettings → section WhatsApp** : nouveau `WaTokenHealthPanel` (testid `wa-token-health-panel`) — diagnostic visuel coloré (vert/rouge/ambre), tip pédagogique permanent pour passer en System User.

### Résultat attendu
L'admin sait à tout moment si le token va expirer, et est alerté par email 7 jours avant la coupure.

---

## 2026-03 — Iter43-fix2 — Registre des Erreurs UX & Notifications

### Backend
- **Filtre `status` désormais case-insensitive** (regex `^...$` /i) — corrige le bug où « Fatale » ≠ « fatale » ne matchait pas
- **Nouveau filtre `severity`** (`low|medium|high|critical`) basé sur `mapped_severity` + heuristique de secours sur StatutEnCours pour les entrées legacy
- **`POST /api/me/errors/bulk-acknowledge`** — marque une sélection comme lue (admin/sup)
- **`POST /api/me/errors/acknowledge-all`** — marque TOUTES les non-lues (admin/sup), indépendamment des filtres
- **Résolution Tenant** : pour chaque entrée listée, le backend lookup `Code_Client` dans `users.client_code` ou `users.company` et expose `tenant_id` + `tenant_name`
- **Liluvine PRO accède au Registre des Erreurs** : nouveau module `errors` dans `liluvine_business_rag.py`, détecté par les mots-clés (erreurs, exceptions, crashes, plantages, registre, fatales, critiques, bugs, stack traces). Snippet contextuel : compteurs Critical/High/Non-lues 30j + 5 dernières entrées.
- **Compteurs notifications mis à jour** : `errors_high` + `errors_critical` basés sur `mapped_severity` ; aliases `errors_exception` + `errors_fatale` conservés pour rétro-compat.

### Frontend
- **Composant Pagination réutilisable** : `« ‹ 1 2 3 4 5 › »` + page-size (25/50/100/200/500) + saut direct à la page N
- **Filtre Sévérité** dans la barre de filtres (🔴 Critical / 🟠 High / 🟡 Medium / ⚪ Low) — aligné avec les badges de la sidebar
- **Boutons Mark-as-Read** : bandeau de sélection + bouton header « Tout marquer comme lu (N) »
- **Colonne Code Client** : affiche le `Code_Client` + badge vert avec le **nom du tenant Sawali** résolu automatiquement
- **Hook `useErrorRegistryNotifier`** (poll 20 s) — toast + son d'alarme dédié (4 tons SOS pour critical, 3 tons descendants pour high) — distinct des tickets/WhatsApp ; respecte les flags `sawali_wa_notif_sound` / `..._desktop`

### Tests
- 50/50 tests verts (régression intacte)
- Tests live preview : severity=critical OK, severity=high OK, status=Fatale (ci) OK, bulk-acknowledge OK, acknowledge-all OK

---

## 2026-03 — Iter43-fix — Welcome Briefing scroll gate + PV PDF auth + Motif length

- **WelcomeBriefing** : bouton « J'ai lu » désactivé tant que l'utilisateur n'a pas scrollé jusqu'en bas (auto-activé si contenu sans scroll)
- **PV de réunion PDF** : `MeetingMinutes.jsx` télécharge désormais le PDF via `apiClient` (responseType blob) au lieu d'ouvrir l'URL nue → résout l'erreur « Token manquant » + « Impossible de charger le PDF »
- **ErrorPayload.Motif** : `max_length` passé de 2 000 à 200 000 caractères pour absorber les stack traces complètes Aizenta

---



> 🔁 **Auto-sync vers Admin Settings** (Iter38f) — Chaque section `## IterXXX (YYYY-MM-DD) — Title`
> est automatiquement scannée. Chaque sous-section `### emoji N) Title` est convertie en action
> `ACT-CL-IterXXX-NN` dans **Admin Settings → Suivi des actions**. Pour qu'une nouvelle entrée
> apparaisse automatiquement : ajoutez-la ici au format ci-dessus. Les sections "Tests",
> "Frontend", "Backend", "Prochaines …" et les notes "🚨/🟧/🟨/🟦" sont automatiquement ignorées.

## Iter41 Phase 4 (2026-02-06) — Dashboard VIDAL + API publique Officines HMAC + 3 nouveaux rôles + UX

### 🎨 UX — Fix confusion bouton « Enregistrer »
- Bannière jaune ajoutée au-dessus du bouton bleu global « Enregistrer les paramètres généraux » dans AdminSettings expliquant que S057/S058/S059 ont chacune leur propre bouton (fuchsia/rose/violet). Libellé du bouton bleu renommé en « Enregistrer les paramètres généraux ».

### 👥 Backend — 3 nouveaux rôles disponibles à la création client
- AdminClients.jsx : sélecteur de rôle étendu avec `regulateur` (💊 AMM), `pharmacien` (💊) et `medecin` (⚕️). Aucune validation backend stricte donc l'enregistrement passe directement.

### 📊 Backend — Dashboard usage VIDAL (`/api/admin/vidal/usage`)
- Nouveau module `routes/vidal_dashboard.py` :
  - `GET /api/admin/vidal/usage?days=N` (admin) — totaux 30j, série quotidienne, top 10 consommateurs (enrichis email/full_name/role/company), distribution mode test/prod sur les analyses Rx, taille du cache.
  - `GET /api/admin/officines/usage?days=N` (admin) — lookups portail, !aizenta WA, top produits recherchés, séries quotidiennes WA, nombre d'officines enrôlées.

### 🏪 Backend — API publique d'inscription Officines (HMAC)
- `POST /api/public/officines/register` — endpoint signé HMAC SHA256 pour que les officines déclarent leur inventaire :
  - Headers requis : `X-Officine-Id`, `X-Timestamp` (epoch ±5 min), `X-Signature` (hex digest)
  - Body : `{officine_name, address, phone, city, country, contact_email, inventory: [{product_name, cip, price, available, stock_qty}]}`
  - Persistance dans `officines_inventory` (upsert par `officine_id` + compteur `updates_count`)
  - Secret partagé stocké dans `settings.global.officines_register_hmac_secret` (masqué dans GET /admin/settings)
- 4 protections : (1) secret absent → 503, (2) timestamp >5min → 401, (3) signature invalide → 401, (4) cap 500 items/call.

### 🎨 Frontend — Widget Dashboard intégré à S058
- Nouveau composant `VidalUsageDashboard.jsx` chargé en bas de la section S058 VIDAL :
  - 4 StatCards (Appels, Users uniques, Analyses Rx, Cache)
  - Mini graphique SVG quotidien sur 30j
  - Top 5 consommateurs avec rôle + entreprise
  - Distribution mode test/prod
  - Section dédiée Officines (lookups portail, !aizenta, enrôlements, top 5 produits)
- Sélecteur 7/30/90 jours + bouton refresh.

### ✅ Tests
- `test_iter41_phase4.py` : 8/8 verts (dashboard VIDAL, dashboard Officines, RBAC, HMAC valid/invalid/old-timestamp, secret désactivé, masking)
- Régression complète Iter40+Iter41 : 77/77 verts
- Lint : 0 erreur sur VidalUsageDashboard, S058VidalSection mis à jour.

### 💼 Cas d'usage commercial du nouveau setup
La combinaison **API publique HMAC** + **dashboard usage** + **!aizenta public** permet désormais :
1. Inscription massive d'officines via leur propre logiciel de caisse (POST signé) — facturable par tranche d'usage.
2. Visibilité côté régulateurs SAWALI sur la disponibilité réseau en temps réel.
3. Service `!aizenta` monétisable côté grand public (push WA = 1 SMS facturable).
4. Dashboard pour démontrer la valeur lors des renouvellements de contrat.


## Iter41 Phase 3 (2026-02-06) — Synthèse + Officines + CIPs + Sidebar image + Hotfix Contact Groups

### 🐛 Hot-fix Contact Groups (bug signalé par utilisateur)
- Bug : ajouter un contact à un groupe renvoyait `added=[]` (toujours 0 contacts dans le groupe). Cause : `add_contacts` filtrait par `client_id` strict, ignorant les contacts partagés en *peer-sharing* (même `company`).
- Correctif : nouveau helper `_visible_contact_client_ids(db, user)` qui réplique la logique de `_resolve_visible_client_ids` (parent + peers du même `company`). Appliqué à `add_contacts`, `create_group`, `resolve_recipients`.
- Tests : 3/3 verts (`test_iter41_contact_groups_bugfix.py`).

### 📊 Synthèse Liluvine programmée + commande WA
- Nouveau module `routes/synthese.py` :
  - `_gather_kpis(db, scope, start, end)` — agrège counts (contacts, tickets, RDV, rapports, suivis, SMS, WA, factures, paiements) + top 5 derniers tickets
  - `_build_prompt(custom_prompt, kpis, start, end)` — hybride : prompt admin + bloc structuré
  - `_call_liluvine(prompt)` via EmergentIntegrations (Claude Sonnet 4.5)
  - `build_synthese(start, end)` exposé en helper
  - `parse_synthese_args(arg_string)` — accepte ISO (`2026-02-01`), français (`01/02/2026`), mots-clés (`aujourd'hui`, `hier`, `semaine`, `mois`)
  - `run_scheduled_synthese(db)` — cron entry point, dispatch email/WA/both selon `synthese_channels`
- Cron APScheduler : nouveau job `liluvine_synthese_minutely` qui vérifie chaque minute si `now == synthese_hour` et déclenche.
- Settings : `synthese_enabled`, `synthese_email_to`, `synthese_wa_to`, `synthese_hour`, `synthese_prompt`, `synthese_channels`.
- Commande WhatsApp `!synthese [début] [fin]` (case-insensitive, supporte `synthese` & `synthèse`) routée dans webhook AVANT auto-reply.

### 🏪 API Officines + commande WA `!aizenta`
- Nouveau module `routes/officines.py` :
  - `POST /api/officines/lookup` (admin/superviseur/regulateur/pharmacien/medecin) — POSTe le payload `{product_name, cip_codes, requester_role, requester_id}` sur l'URL configurée
  - Helper `lookup_for_wa_aizenta` + `format_officines_wa_reply` pour WhatsApp
  - Audit en `vidal_audit_officines` (à terme `officines_audit`)
  - Quota par numéro/jour stocké dans `officines_public_usage`
- Settings : `officines_api_url`, `officines_api_token` (masqué), `officines_api_timeout`, `officines_public_quota_per_day` (défaut 10).
- Commande WhatsApp publique `!aizenta <produit>` ou `!officine[s] <produit>` (case-insensitive, supporte `/`). Aucun gate tenant. Quota anti-abus.
- Bouton « Voir les officines » ajouté dans la modale fiche médicament `/portal/vidal` — appelle `/officines/lookup`.

### 🏥 Codes CIP1-CIP5 sur AMM
- `AmmCreatePayload` + `AmmUpdatePayload` : nouveaux champs `cip1`…`cip5`.
- AmmEditor UI : fieldset dédié sous Notes avec 5 inputs monospace.

### 🎨 Image de fond de sidebar
- Nouveau settings : `sidebar_bg_image_url`, `sidebar_bg_image_opacity`.
- `/api/public/ui-flags` expose les 2 nouvelles clés.
- `useUIFlags.js` injecte les CSS vars `--sidebar-bg-image` (URL absolue) et `--sidebar-bg-opacity`.
- `PortalLayout.jsx` applique `backgroundImage: var(--sidebar-bg-image, none)` + `backgroundBlendMode: multiply` pour mixer image+couleur.
- Upload via endpoint existant `/admin/upload` (limite 2 MB) — frontend stocke l'URL retournée.

### 🎨 Nouvelle section AdminSettings S059
- `S059SyntheseOfficinesSection.jsx` (anchor `s-s059-synthese-officines`) regroupe :
  - Bloc Synthèse (toggle, email, WA, heure, canaux, prompt textarea)
  - Bloc API Officines (URL, token Eye/EyeOff, timeout, quota)
  - Bloc Image sidebar (upload, preview, slider opacité, bouton retirer)
- Bouton « Enregistrer » sticky en bas. Token masqué `********`.

### ✅ Tests
- `test_iter41_phase3.py` : 14/14 verts (CIP fields, parsing dates 4 formats, casse-insensitive, RBAC officines, masking token, settings persistence, sidebar image)
- `test_iter41_contact_groups_bugfix.py` : 3/3 verts
- Régression complète Iter40+Iter41 : 69/69 verts
- Lint frontend : 0 erreur sur S059, Vidal, useUIFlags

### 🚧 Prochaines étapes (côté utilisateur)
1. Tester en preview : créer un groupe + ajouter contacts (bug fix #1) → redéployer
2. Configurer API Officines + tester depuis fiche VIDAL
3. Activer la synthèse + saisir prompt + envoyer `!synthese hier` pour validation
4. Tester `!aizenta doliprane` avec un numéro inconnu pour valider le quota anti-abus
5. Uploader une image sidebar (test visuel)


## Iter41 Phase 2 (2026-02-06) — VIDAL + Liluvine RAG + Commandes WA + Table AMM

### 🩺 Backend — Améliorations VIDAL
- `POST /api/admin/vidal/test-connection` retourne désormais un objet `debug` complet : URL appelée, params (avec `app_key` masqué en `***`), méthode, body éventuel, timeout, status code, content-type, elapsed_ms, body preview (2000 chars max). Permet à l'admin de débugger sans accès aux logs.
- Nouveau helper `_resolve_tenant_vidal(db, user)` qui résout le tenant via `parent_client_id` et lit `features.vidal_enabled` + `features.vidal_mode`. Le tenant peut FORCER son propre mode (`test`/`production`) ou hériter du global (`inherit`).
- Nouveau helper `_ensure_tenant_can_access(db, user)` qui combine la double-vérification : tenant_enabled (sauf admin/superviseur) + global enabled. Renvoie 403 si tenant désactivé, 503 si global désactivé/sans creds.
- `GET /vidal/quota/me` enrichi avec `access` (bool) + `tenant_type` pour permettre au frontend de masquer la sidebar.

### 🤖 Backend — Liluvine RAG VIDAL + Commandes WhatsApp
- Nouveau module `routes/vidal_rag.py` (Qdrant collection `VIDAL_db`):
  - `_ensure_vidal_collection(db)` crée la collection si absente
  - `index_product(db, pid, data)` — indexation lazy à chaque GET /vidal/product/{id}
  - `index_search_results(db, data)` — indexation lazy des hits de recherche
  - `build_vidal_rag_context(db, query, max_chars)` — RAG pour Liluvine
  - `scheduled_import_new_products(db, vidal_call_fn)` — cron nightly pour les nouveautés
- `_resolve_kb_context` de Liluvine (4 callers) intègre maintenant Qdrant `liluvine_kb` + Qdrant `VIDAL_db` en parallèle.
- Nouveau module `routes/liluvine_vidal_wa.py` — commandes WhatsApp :
  - `!vidal?` / `!vidal aide` → aide listant toutes les sous-commandes avec exemples
  - `!vidal fiche <nom>` → fiche complète (nom, substance, labo, AMM local/VIDAL, RCP extrait)
  - `!vidal amm <nom>` → numéro AMM uniquement (base SAWALI prioritaire, fallback VIDAL)
  - `!vidal interactions <id1> <id2>` → analyse via `/alerts/full`
  - `!vidal allergie <substance>` → liste produits référencés
  - Routage WhatsApp inséré dans `server.py` AVANT l'auto-reply Liluvine
  - Tenant gate + quota appliqués (la commande consomme du quota comme l'UI)

### 🏥 Backend — Table AMM (rôle `regulateur`)
- Nouveau rôle accepté : `regulateur` (au même niveau que `moderateur`)
- Nouvelle collection `amm_numbers` avec CRUD via `routes/amm.py`:
  - `GET /api/amm` (recherche + filtre statut) — lecture pour tous les utilisateurs authentifiés
  - `GET /api/amm/by-product/{vidal_id}` — utilisé par les commandes WA
  - `POST /api/amm` — création (réservé `admin|superviseur|regulateur`)
  - `PUT /api/amm/{id}` — modification (même RBAC)
  - `DELETE /api/amm/{id}` — suppression (même RBAC)
  - Champs : `vidal_product_id`, `product_name`, `amm_number` (unique), `laboratory`, `galenic_form`, `atc_class`, `status` (active|withdrawn|suspended), `granted_at`, `expires_at`, `notes`, `source`
- Helper `lookup_amm_for_product(db, vidal_id, name)` consommé par les fiches VIDAL et `!vidal fiche/amm`

### 🎨 Frontend — Section S058 (Debug verbose)
- Panneau « Debug verbose » s'ouvre automatiquement après chaque clic sur « Tester la connexion » :
  - Bloc requête : méthode + URL + mode (badge couleur) + timeout + params JSON + body éventuel
  - Bloc réponse : status code (vert si <400, rouge sinon) + content-type + elapsed_ms + body preview tronqué (formatted, scrollable)
  - Visible UNIQUEMENT à l'admin (page AdminSettings)

### 🎨 Frontend — Feature flag VIDAL par tenant
- `AdminClientFeatures.jsx` : nouvelle ligne « Module VIDAL France (médicaments) » (toggle `vidal_enabled`)
- Quand activé, apparition d'un sélecteur 3-options pour `vidal_mode` :
  - « Hériter du global » (recommandé) → utilise AdminSettings → S058
  - « 🧪 Test (sandbox) » → force en test pour ce tenant
  - « 🚀 Production » → force en prod pour ce tenant
- `DEFAULT_CLIENT_FEATURES` étendu : `vidal_enabled=False`, `vidal_mode="inherit"`

### 🎨 Frontend — Page AMM `/portal/amm`
- Nouveau composant `AmmEditor.jsx` — table + modale d'édition (CRUD)
- Réservé en écriture aux rôles `admin|superviseur|regulateur` (les autres voient une bannière « Vous êtes en lecture seule »)
- Filtre par nom/numéro + statut + boutons Editer/Supprimer + badge statut
- Sidebar portail : nouvelle entrée « Numéros AMM (régulateur) » gated par `vidal_enabled`

### 🎨 Frontend — Sidebar
- `/portal/vidal` et `/portal/amm` désormais gated par `featureGate: "vidal_enabled"` (masqué ou grisé selon UI)

### ✅ Tests
- `test_iter41_vidal_phase2.py` : 14/14 verts (détection commandes WA × 6, AMM CRUD × 4, tenant gate × 2, debug verbose × 2)
- Régression complète Iter40 + Iter41 : 52/52 verts
- Lint frontend : `S058VidalSection.jsx`, `Vidal.jsx`, `AmmEditor.jsx` — 0 erreur build (webpack compile + warnings exhaustive-deps pré-existants seulement)

### 🚧 Prochaines étapes
- Saisie des credentials VIDAL réels (renouvellement en cours côté VIDAL France) puis test live des commandes `!vidal*` via WhatsApp
- Pousser le rôle `regulateur` dans le sélecteur d'utilisateurs admin (création de compte)
- Tester l'enrichissement RAG : demander à Liluvine « parle-moi du Doliprane » sur le web chat après un appel `/vidal/product/11064` pour valider la chaîne Qdrant `VIDAL_db`


## Iter41 (2026-02-06) — Module VIDAL France + fix mémoire conversationnelle Liluvine

### 🩺 Backend — Module VIDAL France (REST API 2025.12 REV-03)
- Nouveaux champs `SettingsUpdate` : `vidal_enabled`, `vidal_mode` (test|production), `vidal_test_base_url`, `vidal_test_app_id`, `vidal_test_app_key`, `vidal_prod_base_url`, `vidal_prod_app_id`, `vidal_prod_app_key`, `vidal_cache_ttl_hours`, `vidal_quota_per_user_per_day`, `vidal_http_timeout`. Les `app_key` masquées dans GET /admin/settings (ajoutées à GET_MASK_FIELDS + SECRET_FIELDS).
- Nouveau module `routes/vidal.py` avec helpers `_load_config`, `_ensure_active`, `_cache_get/_set` (TTL configurable), `_quota_check_and_increment` (429 au-delà du plafond) et `_vidal_call` (httpx + auth via query params).
- 8 nouveaux endpoints :
  - `GET /api/admin/vidal/config` — masque les clés, lit la config courante
  - `PUT /api/admin/vidal/config` — bascule mode, met à jour creds, ignore les masques renvoyés
  - `POST /api/admin/vidal/test-connection` — ping VIDAL (`?q=doliprane&filter=product`) sur l'env actif
  - `DELETE /api/admin/vidal/cache` — purge du cache Mongo `vidal_cache`
  - `GET /api/vidal/quota/me` — compteur journalier du user
  - `GET /api/vidal/search?q=…&filter=product|package|ucd|vmp|all-packages`
  - `GET /api/vidal/product/{id}` + `/documents?type=RCP|FULL_MONO|PIL|INDICATIONS`
  - `GET /api/vidal/products/status?status=NEW|AVAILABLE|DELETED|PHARMACO`
  - `POST /api/vidal/prescription/analyze` (corps : patient + prescriptions + allergies + pathologies) → forwarde vers `/alerts/full` et persiste un audit dans `vidal_prescription_audit`.
- Collections nouvelles : `vidal_cache`, `vidal_usage_daily`, `vidal_prescription_audit`.

### 🩺 Frontend — Module VIDAL
- Nouvelle section AdminSettings `S058VidalSection.jsx` (anchor `s-s058-vidal`) : toggle `enabled`, sélecteur mode TEST/PROD (vert/rouge), 2 blocs de credentials (TEST + PROD avec base_url + app_id + app_key masquée + œil), TTL/quota/timeout, boutons « Enregistrer », « Tester la connexion » (avec résultat ✅/❌), « Vider le cache », « Recharger ». Tous les champs disposent de `data-testid`.
- Nouvelle page portail `/portal/vidal` (`Vidal.jsx`) avec 3 onglets :
  - **Recherche** : champ q + filtre (produit/présentation/UCD/VMP) + tableau résultats + bouton « Voir la fiche » qui ouvre une modale chargeant en parallèle `/vidal/product/:id` et `/vidal/product/:id/documents?type=RCP`.
  - **Catalogue** : sélecteur statut réglementaire (NEW/AVAILABLE/DELETED/PHARMACO) + liste.
  - **Analyse de prescription** : éditeur patient (date naissance, sexe, poids), répétiteur de prescriptions (ID VIDAL + posologie), allergies et pathologies en CSV → affichage JSON des alertes.
  - Badge quota du jour en haut + indicateur 🧪 TEST / 🚀 PROD.
- Sidebar portal : nouvelle entrée « VIDAL France (médicaments) » via icône `HeartPulse` pour TOUS les rôles authentifiés.

### 🤖 Backend — Fix mémoire conversationnelle Liluvine PRO
- `EmergentIntegrations LlmChat` est stateless entre instances → 3 endpoints n'injectaient PAS l'historique : `whatsapp_native` inbound (ligne 852), web chat POST non-streaming (ligne 996), vision chat avec capture d'écran (ligne 1182). Le streaming SSE l'avait déjà depuis Iter40.
- Nouveau helper `_build_memory_block(sid, current_text, limit=10)` dans `routes/liluvine_pro.py` : ramène les 10 derniers messages user/assistant de la session, retire le message courant, ordonne chronologiquement, encadre par `[HISTORIQUE DE LA CONVERSATION]…[FIN HISTORIQUE]`.
- Appliqué aux 3 callers concernés. Liluvine se souvient désormais des échanges précédents quel que soit le canal (WA, web non-stream, vision).

### ✅ Tests
- `test_iter41_vidal.py` : 9/9 verts (CRUD config, RBAC, quota 429, mode switch, cache TTL, masking)
- `test_iter40_liluvine_memory.py` : 4/4 verts (helper, ordre chronologique, limite, exposition module)
- Régression Liluvine + Iter40 + S057 : 145/146 verts (1 pré-existant `test_iter38r_fix9c_liluvine_kb::test_build_kb_context_respects_budget` non lié)
- Lint frontend : 0 issue sur les 2 nouveaux composants.

### 🚧 Prochaines étapes
- Validation E2E UI VIDAL une fois les vrais credentials saisis dans AdminSettings (le bouton "Tester la connexion" ping l'API VIDAL).
- ACL fine-grained par rôle si besoin (actuellement TOUS les utilisateurs authentifiés ont accès).
- Pipeline Liluvine ⇄ VIDAL : permettre à Liluvine d'appeler `/vidal/search` ou `/vidal/product/:id` dans le RAG (à câbler dans `liluvine_business_rag.py`).


## S057 Day 3+ (2026-02-06) — Habillage complet : Sidebar / Login / Blocs publics

### 🎨 Backend
- 15 nouvelles clés dans `SettingsUpdate` :
  - Sidebar : `sidebar_bg_color`, `sidebar_text_color`, `sidebar_accent_color`
  - Login : `login_bg_mode`, `login_bg_color`, `login_bg_image_url`, `login_text_color`, `login_card_bg`, `login_card_text_color`, `login_button_bg`, `login_button_text_color`
  - Blocs publics : `public_blocks_theme` (dict imbriqué — keys `hero/missions/specialisations/experience/about`, chaque bloc avec `bg_color?` + `text_color?`)
- Toutes les clés exposées via `/api/public/ui-flags` (anonyme, aucun secret leaké).

### 🎨 Frontend
- `useUIFlags.js` injecte 13 nouvelles CSS variables sur `documentElement` (`--sidebar-bg`, `--login-card-bg`, `--block-hero-bg`, etc.) — propagation live.
- `PortalLayout.jsx` : sidebar passe en `var(--sidebar-bg, #0E1F3D)` + `var(--sidebar-text, #fff)`.
- `Login.jsx` : 6 zones désormais themables (panneau gauche bg+texte, card, bouton de connexion).
- `Home.jsx` + `Missions.jsx` + `Specialisations.jsx` + `CaseStudies.jsx` : blocs `var(--block-X-bg)` / `var(--block-X-text)`.
- Nouvelle section `S057ThemingSection.jsx` dans `/admin/settings` (anchor `s-s057-theming`) :
  - 3 groupes pliables (Sidebar / Login / Blocs publics)
  - Pickers couleur + champ hex + bouton ✕ remettre au défaut
  - Bouton « Aperçu » → modal avec rendu visuel sans sauvegarder (sidebar miniature, login mini-card, blocs)

### ✅ Tests : 4/4 nouveaux + régression complète **116/116 verts**.


## Iter40 (2026-02-06) — Day 3 : Catégories formulaires + Registre erreurs + DocTech API

### 📁 P1-8 — Formulaires par catégorie
- Nouveau module `routes/form_categories.py` + collection `form_categories` (max 6 par tenant).
- Endpoints :
  - `GET/POST/PUT/DELETE /me/form-categories`
  - `POST /me/form-categories/{cid}/set-default` (exclusivité)
- Champ `category_id` ajouté à `FormCreate`/`FormUpdate` (Pydantic + persistance).
- Logique métier : 1ère catégorie créée auto-flaggée `is_default`. Suppression auto-promotion du suivant.
- UI : onglets pills sur `/portal/forms`, modal de gestion 6/6, dropdown dans `FormEditor`. Recherche full-text titre+description, tri date/auteur.

### 🚨 P2-7 — Registre des erreurs (Webhook + UI)
- Webhook public `POST /api/errors/ingest` avec auth Bearer (token `settings.errors_webhook_token`).
- 30 champs Pydantic conformes à la spec (IDTicketDemnde, Numéro_Généré, StatutEnCours, Code_Client, etc.).
- Auto-génération `ERR-YYYY-NNNNN` si pas fourni.
- Endpoints CRUD + filtres : `GET /me/errors` (status, code_client, search full-text, date_window today/7d/30d, active_only), `GET /me/errors/stats`, `POST /me/errors/{id}/acknowledge`, soft-delete, `POST /me/errors/purge` (Superviseur uniquement).
- ACL stricte : Modérateur/Admin/Superviseur (clients refusés).
- 2 badges sidebar séparés : exception (orange) + fatale (rouge pulsant) basés sur `StatutEnCours`. Intégration `/me/notifications/counts`.
- UI : `/portal/error-registry` tableau filtrable, 4 KPI cards, modal détails, modal purge Superviseur-only.

### 📚 P3-9 — Documentation Technique : Référence API
- Le générateur `generate_admin_settings_doc.py` introspecte maintenant la FastAPI app et ajoute en fin de PDF un tableau exhaustif :
  - Méthode HTTP (color-coded), Endpoint, Description (docstring 1ère ligne), Paramètres (extraits via inspect.signature)
  - Nombre total d'API affiché en gras au bas du tableau
- PDF passe de ~50 KB à ~127 KB avec ce nouvel index.

### ✅ Tests : 19 nouveaux verts (9 form_categories + 10 error_registry) + régression **112/112 ✅**

## Iter40 (2026-02-06) — Day 2 : Liluvine RAG fix + Filtre no-toast + !aide + Groupes contacts

### 🔍 1) Liluvine PRO + Qdrant RAG (bugfix critique)
- Le helper `_resolve_kb_context()` du streaming endpoint `/me/liluvine-pro/chat/stream` n'acceptait PAS de query → Qdrant ne s'activait jamais sur ce flux (les flux non-streaming étaient OK).
- Fix : signature `_resolve_kb_context(query="")` + appel `_resolve_kb_context(payload.text)` dans `_event_stream`.
- Test pytest qui inspecte la source pour garantir la non-régression.

### 🔇 2) Filtre no-toast WhatsApp (paramètres globaux)
- Nouveaux champs `settings.wa_silent_phones_enabled: bool` + `wa_silent_phones: list[str]`.
- Endpoint `GET /me/liluvine-pro/autoreply-feed` filtre désormais les items provenant des numéros silencieux (match sur les 9 derniers chiffres). Les messages restent en DB.
- UI : nouvelle section `WaSilentPhonesSection.jsx` dans `/admin/settings` (anchor `s-wa-silent-phones`).

### ❓ 3) Commande WhatsApp `!aide`
- Aliases reconnus : `!aide`, `!help`, `!commande`, `!commandes`, `!cmd`, `/aide` etc. (regex casse-insensible).
- Branchement dans le webhook AVANT le routage HR/ticket. Évite que Liluvine auto-réponde à la place.
- Liste toutes les commandes : `!absence`, `!avance`, `!ticket`, `!seuil`, plus une indication que les questions en langage naturel sont supportées.

### 👥 4) Groupes de contacts
- Nouveau module `routes/contact_groups.py` + collection `contact_groups` (id, client_id, name, description, color, contact_ids[]).
- Endpoints :
  - `GET    /me/contact-groups`
  - `POST   /me/contact-groups` (avec `contact_ids[]` initial validé contre `directory_contacts`)
  - `PUT    /me/contact-groups/{gid}` (rename/recolor, unicité du nom)
  - `DELETE /me/contact-groups/{gid}`
  - `POST   /me/contact-groups/{gid}/contacts` (ajout idempotent + filtrage IDs invalides)
  - `DELETE /me/contact-groups/{gid}/contacts/{cid}`
  - `POST   /me/contact-groups/resolve` (expanse `{group_ids, contact_ids}` → liste unique)
- UI nouvelle page `/portal/contact-groups` : cartes par groupe, picker contact avec recherche, modal édition couleur+nom+desc.
- Intégration dans `SmsBulk.jsx` + `WaBulk.jsx` : barre de pills « Groupes (N) » au-dessus des destinataires. Cliquer un pill résout via `/resolve` et fusionne avec la sélection manuelle.
- Lien sidebar (icône Users) ajouté sous « Centre de Messagerie ».
- Isolation tenant stricte (tests inclus).

### ✅ Tests : 10/10 verts (`test_iter40_day2_priorities.py`)
- regex !aide, filtre wa_silent (activé + désactivé), persistance via PUT settings, CRUD groupes (création/duplicate/add/remove/idempotency/invalid IDs), resolve mix groupes+individus, isolation tenant, signature `_resolve_kb_context`.
- Régression complète : **93/93 verts** (iter40 + S045 P2).


## S045 Phase 2.A (2026-02) — Extraction admin_settings (read-only routes)

### 🧹 Refactor
- Nouveau module `backend/routes/admin_settings.py` — factory `attach_admin_settings_routes(api, db, get_current_admin, get_settings_doc)`.
- 6 endpoints déplacés de `server.py` sans changement comportemental :
  - `GET /admin/settings` (avec masquage des secrets)
  - `POST /admin/settings/test-url` (ping dry-run + métriques)
  - `GET /admin/secrets/change-audit` (filtre `?key=`)
  - `GET /admin/incidents`
  - `DELETE /admin/incidents/{id}`
  - `GET /admin/incidents/export.csv`
- Constantes `GET_MASK_FIELDS` + `TESTABLE_URL_KEYS` co-localisées dans le module.
- `server.py` : -128 lignes (22223 → 22095). Reste à extraire le `PUT /admin/settings` (dépend de SettingsUpdate, _audit_secret_changes, _broadcast_incident_to_subscribers — phase 2.B).

### ✅ Tests : 10/10 verts (`test_s045p2_admin_settings_refactor.py`)
- Masquage sensitifs + 403 client + test-url 4xx/200 + audit shape & filter + incidents list/delete/csv + 403 cross-cutting.
- Régression complète Iter40 + S045 : **83/83 verts**.


## Iter40 (2026-02) — 🧠 Liluvine RAG modules métier + ✉ Signataires PV par email + 📱 Commandes WA GRH

### 🧠 1) Liluvine PRO Business RAG + ACL par module
- Nouveau module `backend/routes/liluvine_business_rag.py` : `build_business_rag_context(db, phone_digits, query)` injecte du contexte métier (RDV, Tickets, RH personnel, Caisse, Paiements, Contacts) dans les conversations WhatsApp.
- Détection d'intention par regex (`detect_intents`) + ACL : `settings.liluvine_module_acl` est un dict `module → [phone_digits]`. Matching sur les 9 derniers chiffres (le code pays est ignoré).
- Endpoints admin : `GET/PUT /api/admin/liluvine-pro/module-acl` (réservés admin/superviseur). Liste blanche par module.
- Branchement : `liluvine_wa_autoreply.py` enrichit son `sys_text` du `--- CONTEXTE MÉTIER ---` quand l'ACL passe.
- UI Admin : nouvelle section `LiluvineModuleAclSection.jsx` dans `/admin/settings` (anchor `s-liluvine-module-acl`) — 6 textareas (un par module) avec compteur live.
- Nouvelle action limitée : `!ticket <description>` ouvre un ticket support WhatsApp (gated par ACL `tickets`).

### ✉ 2) Signataires PV — Mix utilisateurs internes + emails externes
- `routes/meetings.py:_norm_id_list` accepte désormais les emails (normalisés lowercase, dédupliqués).
- Vérif de signature `/me/meetings/{id}/sign` : autorise si `user.id` OU `user.email` figure dans `signers`.
- PDF : résout les entrées email à `full_name` si un compte existe, sinon affiche l'email tel quel.
- Notifier `_meeting_signers_notifier` : envoie email aux signataires email-only (best-effort enrichissement WA si compte existant).
- UI `MeetingMinutes.jsx > MultiUserPicker` : nouveau bouton « + Ajouter email » qui apparaît dès qu'une chaîne `…@…` est saisie. Chips violettes pour les emails externes.

### 📱 3) Commandes WhatsApp GRH (absence + avance)
- Nouveau module `backend/routes/liluvine_hr_wa.py` : parser regex pour `!absence YYYY-MM-DD [au YYYY-MM-DD] [motif]` et `!avance MONTANT [motif]`.
- Lookup phone → user → hr_employees. Si pas employé : refus explicite avec message FR.
- Absence : status=`pending_approval`, désactive temporairement `account_status` du user + flag `wa_absence_request_id`.
- Avance : status=`pending_approval`, montant XOF, motif.
- Notification admins du tenant via WA (best-effort).
- Branché dans le webhook WA AVANT l'auto-reply (`hr_handled = True` court-circuite Liluvine).
- Nouveaux endpoints HR : `POST /api/hr/absences/{aid}/approve|reject` + `POST /api/hr/advances/{aid}/approve|reject` (admin/sup/comptable). L'approbation réactive le user.

### ✅ Tests : 21/21 verts
- `test_iter40_pv_email_signers.py` (4/4) : norm mixte, persistance, sign by email, refus si non-signataire.
- `test_iter40_liluvine_business_rag.py` (10/10) : ACL CRUD, normalisation, detect intents, _phone_in_acl, context empty/returned, !ticket detect/refuse/create.
- `test_iter40_hr_wa_commands.py` (7/7) : detect, unknown phone, absence create + disable, advance create, refus 0, approve, reject.
- Régression 58/59 verts (1 test ajusté pour exposer les nouveaux champs `bg_*` dans `/public/ui-flags`).


## Iter38r-fix7 (2026-05-28) — Toggle Liluvine PRO + Comptable hardening + Branding + n8n/WA/FB inbound + AI profile photo

### 🔒 1) Toggle Liluvine PRO dans Smart Communications
- Nouveau feature flag `ai_liluvine_pro` ajouté dans `DEFAULT_CLIENT_FEATURES` (backend) et `AdminClientFeatures.jsx` (UI).
- **Backend** : `POST /me/liluvine-pro/chat` retourne **403** quand `features.ai_liluvine_pro` est false sur le parent admin (résolu via `_client_scope`).
- **Frontend** : l'entrée menu « Liluvine PRO (Assistant IA) » reste **visible** mais grisée à 40% d'opacité avec badge OFF en gris quand le toggle est désactivé. Un clic sur le lien désactivé déclenche un toast d'information « Fonctionnalité non activée — contactez votre administrateur ».
- Mécanisme générique `featureGate` dans `clientLinks` réutilisable pour d'autres features à l'avenir.

### 👔 2) Comptable strict : Centre de Messagerie + Chat Direct verrouillés
- Le bouton/lien **« Ouvrir le centre de messagerie »** dans le `WelcomeBriefing` est masqué si `isComptaStrict=true`.
- Le badge cliquable **« X WhatsApp »** dans la section "depuis votre dernière connexion" est aussi masqué.
- La **bulle Chat Direct** (`InternalChatPanel` FAB) n'est plus rendue côté `PortalLayout` quand `isComptaStrict=true`.
- Cohérent avec la restriction menu déjà en place (Compta voit uniquement Caisse/Facturation + GRH).

### 🎨 3) Branding Liluvine PRO paramétrable
- 3 nouveaux champs `settings` : `liluvine_pro_name`, `liluvine_pro_avatar_url`, `liluvine_pro_color`.
- Nouvel endpoint `GET /me/liluvine-pro/branding` → expose nom + avatar + couleur au frontend.
- `LiluvinePro.jsx` charge le branding au mount et l'applique :
  - Avatar : image custom OU icône Bot par défaut, dans un cercle gradient `from-{color}-500 to-violet-600`.
  - Nom dans le header + dans le banner "non activé" + dans tooltips.
  - Couleur des boutons (Envoyer) dynamique.
- Le multi-tenant peut donc avoir son propre assistant (« Sawa », « Bot Yaouba », etc.) avec sa couleur et son avatar.

### 🔗 4) Liluvine PRO ↔ n8n / WhatsApp / Facebook (webhooks inbound + outbound)
- Nouveau endpoint webhook entrant `POST /api/webhooks/liluvine-pro/{source}/{secret}` où `source ∈ {n8n, whatsapp, facebook, custom}`.
- Protection par secret partagé `liluvine_pro_inbound_secret` (auto-généré si absent via `/admin/liluvine-pro/inbound-urls`).
- Le payload accepte `{ text, client_id, session_id?, from?, to?, metadata? }`.
- Création/réutilisation de session, fetch RAG context, appel Claude Sonnet 4.6, persistance des messages avec `external_source`.
- **Forward outbound automatique** : si `liluvine_pro_n8n_outbound_url` est défini dans settings, la réponse est POST-ée à n8n pour dispatch vers WhatsApp/Facebook/SMS via les workflows n8n.
- Endpoint admin `GET /api/admin/liluvine-pro/inbound-urls` retourne les 4 URLs prêtes à coller (n8n/whatsapp/facebook/custom).

### 📸 5) Génération photo de profil IA
- Nouveau endpoint `POST /me/ai/generate-profile-photo` accepte `{ prompt, style }` (5 styles : professional/creative/casual/artistic/avatar).
- Le prompt est enrichi côté serveur avec consignes de portrait carré, cadrage tête-épaules, regard sympathique, no text.
- Image générée via Gemini Nano Banana, sauvegardée, et `users.avatar_url` est **automatiquement mis à jour** → visible partout immédiatement.
- Logged dans `ai_generations` + tracking quota IA.
- **Frontend MyAccount.jsx** : bouton sparkle fuchsia à côté de l'avatar (existant et initials) → modal avec textarea + select style + boutons Annuler/Générer. Gère erreurs 429 (quota) et 403 (feature off).

### 🧪 6) Tests Pytest — `test_iter38r_fix7_liluvine_branding_gating.py` (7 tests, 100% pass)
- Feature gate 403 quand `ai_liluvine_pro=false`
- Branding endpoint retourne défauts puis valeurs customisées
- Inbound webhook : rejette mauvais secret + mauvaise source
- Inbound URLs endpoint auto-génère le secret
- Photo profil 403 quand `ai_image_gen=false` (via user tracked non-admin)

### 📊 Bilan Iter38r mis à jour
**63 tests pytest 100% pass** sur 8 sous-itérations (Iter38r + fix1-fix7).

## Iter38r-fix6 (2026-05-28) — UI Quotas IA + Liluvine PRO (Assistant SAWALI interne)

### 🎛️ 1) UI Quotas IA dans Admin → Clients → Fonctionnalités
- Nouvelle section `AiQuotasSection` dédiée dans `AdminClientFeatures.jsx` (sous PawaPay MSISDN policy).
- **Mode selector** : 3 boutons radio (Désactivé / Quotas par ressource / Budget global XOF).
- **Mode "quota"** : 4 inputs (Images / Vidéos / Transcription minutes / Chat tokens) avec icônes spécifiques.
- **Mode "budget"** : input unique en grand FCFA avec explication.
- **Alertes** : seuil warn % (input) + checkbox "Bloquer à 100%".
- **Tarifs effectifs** : section repliable avec 4 inputs d'override (placeholders = défauts globaux).
- **Consommation du mois** : 4 cartes (Images/Vidéos/Minutes/Tokens) qui virent à l'orange (warn) puis rouge (blocked) selon le statut.
- **Budget bar** : barre de progression colorée mauve→orange→rouge selon le % consommé.
- **Détail par Utilisateur Suivi** : tableau replié (collapse) avec colonnes Date, Images, Vidéos, Min., Tokens, Coût XOF.
- **2 boutons d'export** : CSV (vert) et PDF (rose) en haut de la section.

### 🤖 2) Liluvine PRO / Assistant SAWALI interne
**Backend** (`/app/backend/routes/liluvine_pro.py`) :
- Module isolé propulsé par **Claude Sonnet 4.6** via Emergent LLM Key.
- 5 endpoints : `POST /chat`, `GET /sessions`, `GET /sessions/{sid}`, `PATCH /sessions/{sid}`, `DELETE /sessions/{sid}`.
- Sessions et messages persistés dans MongoDB (`liluvine_pro_sessions`, `liluvine_pro_messages`).
- **Multi-tenant strict** : chaque user ne voit que ses sessions sous son admin parent. Admin/sup peuvent auditer toutes les sessions de leur tenant.
- **RAG par injection** : détection automatique de 5 mots-clés (contact/ticket/paiement/RDV/note) → fetch des 10 dernières lignes pertinentes en DB → injection dans le system message comme `--- CONTEXTE DB ---`. Plus simple que function calling, et 100% prévisible.
- **Tracking automatique** via `track_ai_usage(resource="chat", units=tokens_estimés)` : pré-check avant l'appel LLM (économise quota), log post-réponse avec tokens estimés (~4 chars/token).
- Bloque à 429 si quota dépassé.

**Frontend** (`/app/frontend/src/pages/portal/LiluvinePro.jsx`) :
- Page full chat : sidebar conversations (rename/delete) + zone chat principale + composer.
- Bot avatar gradient fuchsia→violet (distinct de Liluvine Jotform externe).
- **Suggestions de prompts** au démarrage (3 exemples cliquables).
- Auto-scroll au nouveau message, indicateur "typing" pendant la requête.
- **Toast warning à 80%** du quota (depuis flag `warn` de la réponse).
- Renommage et suppression de session via `window.prompt`/`confirm`.
- Affiche metadata du message assistant : tokens, contexte injecté ✓, modèle.

**Route + menu** :
- `/portal/liluvine` ajoutée dans `App.js`.
- Entrée "Liluvine PRO (Assistant IA)" avec icône `Bot` dans `clientLinks` (PortalLayout).

### 🧪 3) Tests Pytest — `test_iter38r_fix6_liluvine_pro.py` (9 tests, 100% pass)
- RAG context : contacts/tickets keywords déclenchent fetch DB, question hors-sujet ne déclenche rien.
- Session lifecycle : list/get/rename/delete + isolation multi-tenant (404 cross-tenant).
- Quota chat : 429 quand `chat_tokens` dépassé.

### 📦 Bilan Iter38r global
- **Iter38r** : PawaPay Hosted Page (14 tests)
- **fix1** : Body PawaPay v2 (1 test)
- **fix2** : Callbacks deposits/refunds + enrichissement MNO (8 tests)
- **fix3** : Routing webhook Meta/WhatsApp + Corbeille unlink + Donut MNO (8 tests)
- **fix4** : Compta strict + WhatsApp share + Forms visibility (4 tests)
- **fix5** : Backend AI Quotas (12 tests)
- **fix6** : UI Quotas IA + Liluvine PRO (9 tests)
- **TOTAL Iter38r : 56 tests pytest 100% pass** 🎯

## Iter38r-fix5 (2026-05-28) — Backend AI Quotas & Usage Tracking par Client Lié

### 🎯 1) Module backend complet `/app/backend/routes/ai_quotas.py`
Nouveau module isolé qui expose :
- **Helper public `track_ai_usage(db, user, resource, units, model, metadata, pre_check)`** importable depuis n'importe quel endpoint IA.
- 3 modes de quota par Client Lié (admin parent) :
  - `off` : aucune limitation (défaut).
  - `quota` : caps par ressource (images / vidéos / minutes transcription / tokens chat).
  - `budget` : cap global en XOF par mois.
- Devise par défaut **XOF** (FCFA) avec tarifs par défaut configurables (`ai_cost_image_xof=25`, `ai_cost_video_xof=1500`, `ai_cost_transcription_minute_xof=6`, `ai_cost_1k_tokens_xof=3`) override possible per-client.
- Alertes paramétrables : seuil warn (défaut 80%), blocage à 100% (toggle `block_on_limit`).

### 🛢️ 2) Schémas MongoDB
- `ai_quotas` : 1 doc par `client_id` (admin parent). Config mode + caps + overrides + alertes.
- `ai_usage_events` : append-only, 1 event par appel IA (user_id, user_label, tracked_role, resource, units, base, cost_xof, model, metadata, year_month, created_at). Source de vérité pour CSV/PDF.
- `ai_usage_monthly` : rollup `{client_id, year_month}` pour quota check rapide (images, videos, transcription_minutes, chat_tokens, total_xof).

### 🔌 3) Endpoints exposés
- `GET /api/admin/clients/{client_id}/ai-quota` → config + tarifs effectifs + défauts
- `PUT /api/admin/clients/{client_id}/ai-quota` → upsert config
- `GET /api/admin/clients/{client_id}/ai-usage?month=YYYY-MM` → rollup + breakdown par Utilisateur Suivi
- `GET /api/admin/clients/{client_id}/ai-usage/export.csv?date_from=&date_to=` → CSV UTF-8 BOM Excel-ready avec colonnes : Date/Heure, Utilisateur Suivi, Rôle, Ressource, Unités, Base, Coût (XOF), Modèle + ligne TOTAL
- `GET /api/admin/clients/{client_id}/ai-usage/export.pdf?date_from=&date_to=` → PDF paysage A4 (reportlab) avec en-tête bleu nuit + tableau + ligne TOTAL bleue.
- `GET /api/me/ai-usage` → vue read-only de la consommation pour l'utilisateur courant (résolu vers son admin parent).

### 🔗 4) Hooks dans les endpoints IA existants
- `POST /me/ai/generate-image` (Nano Banana) : pre-check avant l'appel Gemini (économise crédits), log après succès.
- `POST /me/ai/edit-image` : idem.
- `POST /me/ai/generate-video` (Sora 2) : pre-check + log (1 vidéo).
- `POST /transcribe` (Whisper) : estimation des minutes depuis la taille du buffer audio (~24 KB/s), log après transcription.

### 🧪 5) Tests Pytest — `test_iter38r_fix5_ai_quotas.py` (12 tests, 100% pass)
- GET retourne mode=off + tarifs effectifs par défaut.
- PUT persiste config quota et budget.
- `track_ai_usage` incrémente correctement le rollup et persiste l'event.
- Quota mode bloque dès le dépassement du cap.
- Budget mode bloque dès le dépassement budget XOF.
- Endpoint usage retourne breakdown par user.
- Export CSV contient les colonnes attendues + ligne TOTAL.
- `/me/ai-usage` résout vers le bon admin parent (cas Utilisateur Suivi).
- RBAC admin-only respecté sur les endpoints `/admin/...`.

### 🚧 6) Reste à faire (UI — quand l'utilisateur confirme)
- **Frontend** : Section « Quotas IA » dans `/admin/clients/{id}/features` avec toggle mode + caps + tarifs + 2 boutons « Export CSV » / « Export PDF ».
- **Toast d'alerte 80%** côté Portal client (depuis `useActivityFeedNotifier` ou nouveau hook `useAiQuotaWatcher`).
- **Branchement Chat IA** (résumés/Liluvine Pro futurs) : appeler `track_ai_usage(resource="chat", units=tokens)` avec le décompte tokens du provider.

## Iter38r-fix4 (2026-05-28) — Comptable strict + WhatsApp partager bibliothèque + Forms data visibility

### 🔒 1) Rôle Comptable strict — seulement Caisse/Facturation + GRH
**Demande** : « L'utilisateur avec rôle 'Compta' ne doit voir QUE les modules Caisse/Facturation et GRH-Ressources Humaines. Toutes les autres options du Menu sont invisibles. »

**Fix** : Dans `PortalLayout.jsx`, nouveau flag `isComptaStrict = isComptable && !isAdminOrSup`. Quand actif, un nouveau filtre `.filter(l => allowedComptaPaths.has(l.to))` est appliqué AVANT les autres, ne laissant passer que `/portal/cash` et `/portal/hr`. L'admin/superviseur reste non affecté (peut tout voir).

### 📎 2) WhatsApp Conversation — bouton « Partager » (bibliothèque / formulaire / catalogue)
**Demande** : « La fenêtre de conversations WhatsApp doit avoir un lien pour envoyer un fichier de la bibliothèque, un lien de formulaire, ou d'une fiche produit du catalogue. »

**Fix** : Nouveau bouton **Partager** (icône Share2 bleu) à côté du trombone, qui ouvre un modal `share-library-modal` avec 3 onglets :
- **Bibliothèque** (FolderOpen) — liste depuis `/me/media-library`, insère `public_url`.
- **Formulaire** (FileEdit) — liste depuis `/me/forms` (publics + miens), insère `{origin}/f/{form_id}`.
- **Catalogue** (ShoppingBag) — liste depuis `/public/products` (parcours catégories→produits), insère `{origin}/catalogue?product_id={id}`.

Au clic sur un item, un message formaté est inséré dans la zone de saisie (avec emoji 📝 / 🛍️ / 📎 + label + URL), prêt à envoyer (ou enrichir manuellement). Filtre de recherche live. Limite 100 items max par onglet.

### 📋 3) Formulaires — visibilité des soumissions
**Demande** : « 7 soumissions aujourd'hui mais `/portal/forms/` n'affiche que les vues, pas les données. »

**Constat après audit** : le compteur `uses_count` était bien incrémenté correctement à chaque soumission (vérifié via test pytest dédié — 3 soumissions → `uses_count=3` ✅). Le problème était **purement UX** : le label `« X utilisation(s) »` était ambigu (interprété comme "vues") et aucun bouton ne permettait d'accéder directement aux données.

**Fix** :
- Renommage : `« X utilisation(s) »` → `« X soumission(s) reçue(s) »` dans un **badge bleu sky** visible (avec icône Database).
- Nouveau bouton **« Données »** (sky-600) sur chaque carte de formulaire (avant le bouton Stats) qui pointe vers `/portal/forms/{id}/analytics#submissions`.
- Dans `FormAnalyticsDetail.jsx`, ajout d'un `id="submissions"` sur le bloc SubmissionsTable + auto-scroll smooth quand le hash `#submissions` est présent au montage.

### 🧪 4) Tests Pytest — `test_iter38r_fix4_compta_share_forms.py` (4 tests, 100% pass)
- `uses_count` reflète bien le nombre réel de submissions (3 submissions publiques → uses_count=3).
- Endpoints `/me/media-library`, `/me/forms`, `/public/products` (utilisés par le share modal) répondent 200.

## Iter38r-fix3 (2026-05-28) — Routing webhook unifié Meta/WhatsApp + Corbeille avec dé-liaison contact

### 🚨 1) BUG FIX P0 — WhatsApp ne recevait plus rien après l'installation des modules META
**Cause racine** : depuis l'install du module Meta (Iter38o), l'utilisateur configurait probablement chez Meta App l'URL unique `/api/meta/webhook`. Ce endpoint ne traitait QUE les payloads Messenger/Pages/Ads et ignorait silencieusement les payloads WhatsApp Cloud (`object='whatsapp_business_account'`).

**Fix** : Dans `/api/meta/webhook` POST, détection du type d'objet AVANT la vérification HMAC. Si `object == 'whatsapp_business_account'`, délégation vers le handler WhatsApp Cloud existant (`whatsapp_webhook_incoming`) qui persiste correctement dans `db.whatsapp_messages`. Le HMAC reste appliqué pour les autres types.

Côté `GET /api/meta/webhook` : accepte désormais soit `meta_webhook_verify_token`, soit `wa_verify_token` (fallback) — l'utilisateur peut donc configurer une URL unique chez Meta App avec n'importe lequel des 2 tokens.

### 🗑️ 2) Bug Corbeille tickets — modal de confirmation avec checkbox « Effacer aussi le lien contact ↔ ticket »
- L'utilisateur reportait une erreur "Ticket introuvable" lors de la corbeille de tickets orphelins.
- Cause : `window.confirm` brut + appel direct sans gestion des cas particuliers (ticket déjà archivé / déjà supprimé / lien contact orphelin persistant).
- **Backend** : `POST /me/tickets/{tid}/archive` accepte désormais un body optionnel `{ also_unlink: bool }`. Quand `true`, set `contact_id=None` + `archived_contact_id=<old>` + `unlinked_at` (audit). Idempotent : si le ticket est déjà archivé mais conserve son contact_id (cas legacy), passe en mode "release uniquement le contact" avec `already_archived=true, unlinked=true`.
- **Frontend** (`Contacts.jsx`) : remplacement du `window.confirm` par un vrai modal `archiveModal` avec :
  - Liste des risques (irréversible, IRRÉVERSIBLE).
  - Checkbox « Effacer aussi le lien contact ↔ ticket » expliquant son usage pour les tickets orphelins.
  - Gestion gracieuse du 404 (ticket déjà supprimé) → toast info + rafraîchissement de l'active-ticket.

### 📊 3) Donut « Répartition par opérateur Mobile Money » avec pourcentages
- Remplacement du BarChart par un PieChart donut (innerRadius=42, outerRadius=72).
- Légende verticale en dessous avec pourcentages explicites et nom complet de l'opérateur (`Orange Money`, `Moov Money`, `Telecel Cash`, `MTN Mobile Money`, `Airtel Money`).
- Couleurs MNO étendues (ajout MTN jaune, Airtel rouge) pour les futurs déploiements pan-africains.
- Tooltip enrichi : `"X transactions (Y%)"` au lieu de juste `X`.

### 🧪 4) Tests Pytest — `test_iter38r_fix3_archive_unlink_meta_routing.py` (8 tests, 100% pass)
- Archive sans `also_unlink` → contact_id intact (rétro-compat).
- Archive avec `also_unlink=true` → contact_id cleared, archived_contact_id preserved.
- Archive déjà archivé + also_unlink → mode "release contact seul" + flag `already_archived`.
- Archive déjà archivé sans also_unlink → 409 (comportement existant).
- Archive sans body → fonctionne (rétro-compat).
- Cycle complet : archive+unlink → fenêtre contact libérée → nouveau ticket créé immédiatement.
- `/api/meta/webhook` POST avec payload `whatsapp_business_account` → message persisté dans `whatsapp_messages`.
- `/api/meta/webhook` GET verify accepte `wa_verify_token` et `meta_webhook_verify_token`, rejette les tokens inconnus.

## Iter38r-fix2 (2026-05-28) — Callbacks deposits/refunds + enrichissement MNO

### 🔔 1) Endpoints callback distincts deposits/refunds
- Nouvelles routes : `POST /api/webhooks/pawapay/deposits/{secret}` et `POST /api/webhooks/pawapay/refunds/{secret}` (en plus du legacy `/api/webhooks/pawapay/{secret}` conservé pour rétro-compatibilité).
- Le legacy auto-détecte deposit vs refund via présence de `refundId` dans le payload.
- Helper interne `_pawapay_webhook_apply(payload, op_type)` partagé entre les 3 routes.

### 🧭 2) Endpoint admin `/api/admin/pawapay/callback-urls`
- Auto-génère `pawapay_callback_secret` (token urlsafe 32 chars) si absent, pour que les URLs soient toujours utilisables immédiatement.
- Retourne `deposits_url`, `refunds_url`, `legacy_url` + `secret_preview` masqué.
- Base host dérivée des headers `X-Forwarded-Host` / `X-Forwarded-Proto` → preview admins voient URLs preview, prod admins voient URLs prod.
- Section UI dédiée dans **Admin → Paramètres → Paiement PawaPay** avec boutons « Copier » + bouton « Rafraîchir ».

### 🏷️ 3) Enrichissement automatique du doc payment avec MNO + phoneNumber
- Helper `_pawapay_split_provider("ORANGE_BFA")` → `("ORANGE", "BFA")`, gère aussi `MTN_MOMO_ZMB` → `("MTN", "ZMB")` et `AIRTEL_MONEY_UGA` → `("AIRTEL", "UGA")`.
- Le polling `GET /me/payments/{deposit_id}` et les webhooks extraient `provider` (code complet, audit) + `mno` (code court matchant les labels frontend) + `phoneNumber` (si absent du doc initial).
- Conséquence : les paiements créés via Payment Page hébergée — où le client choisit son opérateur — ont désormais leur MNO renseigné dès que PawaPay répond.

### 📋 4) Frontend MyPayments — colonne « Motif » + opérateur garanti
- Nouvelle colonne « Motif » (visible ≥ lg) affichant `description` ou `reason`.
- L'opérateur affiché tombe sur `—` (gris) si vraiment inconnu (au lieu d'être vide).
- Vue mobile compactée : opérateur + numéro + motif empilés sous la date.

### 🧪 5) Tests Pytest — `test_iter38r_fix2_callbacks_and_enrichment.py` (8 tests, 100% pass)
- Provider parser (ORANGE_BFA, MTN_MOMO_ZMB, AIRTEL_MONEY_UGA, vide), endpoint callback-urls (auto-gen secret, RBAC admin), webhooks deposits/refunds avec enrichissement DB, rejet secret invalide, legacy fallback.

## Iter38r-fix1 (2026-05-28) — PawaPay v2 body shape fix

### 🐛 1) Correction du body envoyé à `/v2/paymentpage`
- L'erreur PawaPay « *please remove unsupported parameter from request body* » provenait de 3 paramètres en shape v1 :
  - `msisdn` → renommé **`phoneNumber`** en v2
  - `amount` (plat top-level) → doit être imbriqué dans **`amountDetails: { amount, currency }`**
  - Ajout de la **currency ISO-4217** dérivée du pays (XOF pour UEMOA, XAF pour CEMAC, KES/UGX/TZS/RWF/ZMW/GHS/NGN…)
- `reason` étendu à 50 chars (limite v2) au lieu de 22 (qui était la limite de `customerMessage`).
- Suppression de tout champ legacy (`statementDescription`, `correspondent`, `payer`) dans le body.

### 🧪 2) Test mock httpx — `test_iter38r_fix1_paymentpage_body_shape.py`
- Patche `httpx.AsyncClient` pour capturer le body sans appeler PawaPay.
- Vérifie : présence de `amountDetails`/`phoneNumber`, absence de `amount` plat et `msisdn`, `country` correct, `returnUrl` contient `depositId`, decimal amount rendu en 2 décimales, `amountDetails` absent si amount non fourni.

## Iter38r (2026-05-28) — PawaPay Hosted Payment Page (v2)

### 💳 1) Migration vers `/v2/paymentpage` (hosted page)
- L'ancien `/v2/deposits` direct (qui ne collectait pas l'OTP dans le CRM) est remplacé par la **PawaPay Payment Page hébergée** côté PawaPay : MSISDN + PIN/OTP saisis sur leur page sécurisée, conformément à la documentation officielle.
- Nouvel endpoint `POST /api/me/payments/pawapay/payment-page` qui retourne `redirect_url` + `deposit_id`.
- L'ancien `POST /api/me/payments/pawapay/deposit` est conservé en *forwarder* (deprecated) afin que les clients pré-Iter38r continuent de fonctionner ; il appelle désormais la même payment-page en interne.
- Persistance préalable du document `payments` (status=initiated, flow="payment_page") **avant** l'appel HTTP à PawaPay, pour garantir la réconciliation même en cas de timeout réseau (best-practice recommandée par PawaPay).

### 📲 2) Toggle MSISDN par client : `pawapay_fix_msisdn`
- Nouveau champ `users.pawapay_fix_msisdn` (`true` = pré-rempli ; `false` = laissé vide pour saisie libre sur la page PawaPay ; `null` = hérite de `settings.pawapay_fix_msisdn_default`).
- Réglage exposé dans **Admin → Clients → Fonctionnalités** (`/admin/clients/{id}/features`) : section dédiée « Politique MSISDN PawaPay » avec 3 boutons radio.
- GET/PUT `/api/admin/clients/{id}/features` étendus pour retourner et accepter ce champ.

### 🔄 3) Polling du statut via `/v2/deposits/{id}` (wrapper FOUND/NOT_FOUND)
- L'endpoint `GET /api/me/payments/{deposit_id}` interroge maintenant l'endpoint v2 (qui retourne `{status: "FOUND", data: {...}}`).
- Fallback défensif pour les anciennes réponses v1 (array ou objet plat).
- Mapping des statuts PawaPay (`COMPLETED`/`FAILED`/`REJECTED`/`ACCEPTED`/`PROCESSING`/`SUBMITTED`/`PENDING`) vers les statuts internes (`completed`/`failed`/`pending`).

### 🎯 4) Page retour `/portal/payments/return`
- Nouvelle page React `PaymentReturn.jsx` ouverte automatiquement par PawaPay après paiement/abandon.
- Poll automatique de 3 s × 25 tentatives (~75 s) jusqu'à statut final.
- Affiche le statut visuel (✅ confirmé / ❌ échoué / ⏳ en cours) + résumé deposit_id/montant/MNO/MSISDN.
- Bouton « Actualiser » manuel + « Voir mes paiements ».

### 🧪 5) Tests Pytest — `test_iter38r_pawapay_hosted.py` (14 tests, 100% pass)
- Couverture : 503 (PawaPay off), 503 (token vide), 403 (feature off), persistance doc même si PawaPay rejette, MSISDN pré-rempli quand `pawapay_fix_msisdn=true`, MSISDN vide quand `false`, return_url contient `/portal/payments/return`, forwarder legacy garde le shape v1, GET/PUT admin features, polling 404 sur deposit inconnu, polling rend doc final sans refresh, polling rejette accès cross-user.



### 🗑️ 1) Endpoint d'archivage `POST /me/tickets/{tid}/archive`
- Admin/Superviseur uniquement. Marque le ticket `archived_at` + `archived_by_id` + `archived_by_label`.
- Si le ticket est encore ouvert, le clôture également avec `outcome="archived_to_trash"`.
- **Action irréversible** : pas d'endpoint `/unarchive`. Réouverture refusée (409 « ticket dans la corbeille »).
- Trace dans le flux d'activité (`ticket.archived`).

### 👁️ 2) Endpoint de listing corbeille `GET /me/tickets/trash`
- Admin/Superviseur uniquement (403 sinon). Retourne uniquement les tickets `archived_at != null`, triés par date d'archivage descendante.
- Read-only — pas de restauration possible.

### 🚫 3) Exclusion globale des tickets archivés
- Tous les endpoints existants filtrent désormais `archived_at: {$in: [null, ""]}` :
  - `GET /me/tickets` (liste)
  - `GET /me/contacts/{cid}/active-ticket` (badge chat)
  - `POST /me/contacts/{cid}/ticket` (check de blocage à la création)
  - `POST /me/tickets/{tid}/reopen` (parent ET ticket bloqueur)
  - Compteurs de tickets ouverts
- Conséquence : un ticket archivé disparaît totalement de l'UI et ne bloque plus jamais la création d'un nouveau ticket.

### 🎨 4) Frontend
- **`Contacts.jsx`** (chat WA) : nouveau bouton 🗑️ rouge à côté de "Voir" (admin/sup uniquement) — affiche un `window.confirm()` d'avertissement "IRRÉVERSIBLE — Toutes les références seront supprimées". Au clic OK, archive le ticket et rafraîchit le badge actif.
- **`Tickets.jsx`** : nouveau bouton "Corbeille" dans le header (admin/sup) qui ouvre un modal listant tous les tickets archivés (N°, contact, motif, date d'archivage, par qui). Read-only avec bandeau d'avertissement.

### ✅ Tests
- 10 nouveaux pytest verts (`tests/test_iter38q_ticket_trash.py`) couvrant : archivage admin OK + sup OK + client refusé, exclusion des listings/active-ticket/blocage, refus de réouverture après archivage, idempotence (409 si déjà archivé), endpoint corbeille filtré par rôle.
- Régression iter38 (a→q) : **122/122 verts**.

## Iter38p (2026-05-27) — Auto-nettoyage des tickets orphelins (TKT-2026-0001)

### 🧹 1) Helper `_auto_close_orphan_ticket_if_contact_missing`
- Nouveau helper dans `server.py` qui vérifie si un ticket "ouvert" pointe sur un `contact_id` n'existant plus ni dans `directory_contacts` ni dans `contacts`. Si oui, le ticket est auto-fermé avec `outcome="orphan_contact_deleted"` + note explicative + entrée dans le flux d'activité (`ticket.orphan_closed`).
- Appelé depuis 3 endroits : (a) `POST /me/contacts/{cid}/ticket` (création), (b) `GET /me/contacts/{cid}/active-ticket` (chat UI), (c) `POST /me/tickets/{tid}/reopen` (réouverture).

### 🚨 2) Échappatoire `force_release` pour bloqueurs vivants
- `TicketOpenPayload` reçoit un nouveau champ `force_release: bool` (réservé admin/superviseur/modérateur).
- Quand un ticket bloque la création mais que le contact existe TOUJOURS (donc auto-cleanup ne s'applique pas), l'utilisateur peut renvoyer la requête avec `force_release=true` : le bloqueur est fermé avec `outcome="force_released"` et la création se poursuit.
- Headers de réponse 409 : `X-Blocking-Ticket-Id` + `X-Blocking-Ticket-Number` exposés via CORS pour permettre au frontend d'identifier le bloqueur sans avoir à le parser.
- Frontend `Contacts.jsx` : sur 409 avec headers présents, affiche un `window.confirm()` proposant "Clôturer automatiquement le ticket bloquant ?" — si OK, relance la requête avec `force_release=true`.

### ✅ Tests
- 7 nouveaux pytest verts (`tests/test_iter38p_orphan_ticket_cleanup.py`) couvrant : auto-cleanup via active-ticket, auto-cleanup via création, force_release admin, ticket vivant bloque toujours (no false-negative), reopen avec auto-cleanup.
- Régression iter38 (a→p) : **112/112 verts**.

## Iter38o (2026-05-27) — Backlog complet + Stripe + dépenses éditables

### ✏️ 1) Édition des dépenses non clôturées
- `PATCH /api/cashier/expenses/{eid}` : nouvelle gating — admin/sup peuvent toujours, créateur OU employé attribué peuvent éditer **tant que la dépense n'est pas justifiée**. Une fois clôturée (justifiée), seul l'admin peut modifier (force).
- Frontend `ExpensesTab.jsx` : nouveau bouton crayon par ligne + nouveau modal `ExpenseEditForm` complet (date, mode, montant, motif, attribution tiers/employé, note). Bandeau informatif "Modification autorisée uniquement tant que non clôturée".

### 🏝️ 2) Jours fériés excluent les heures déduites (paie)
- `_absence_hours_for_month` retourne désormais 4 buckets : `justified`, `unjustified`, `holiday`, `total`. Les absences tombant sur un jour férié `is_paid=true` sont reclassifiées dans `holiday` et **ne sont JAMAIS déduites du salaire**.
- Impact direct sur les fiches de paie : une journée prise pendant le 1er mai n'est plus pénalisée.

### 🤖 3) Toggle Génération Image/Vidéo IA (Smart Communications)
- 2 nouveaux feature flags client : `ai_image_gen` (Nano Banana) et `ai_video_gen` (Sora 2). Stockés dans `users.features` comme les autres, hérités par tous les utilisateurs suivis.
- Backend `routes/ai_media.py` : nouveau helper `_ensure_feature_enabled()` qui bloque `/me/ai/generate-image`, `/me/ai/edit-image` et `/me/ai/generate-video` avec un 403 explicite quand le flag est OFF (admin/sup bypassent).
- Frontend Admin → SMART Communications : 2 nouvelles cartes toggle "Génération d'Image IA" et "Génération de Vidéo IA".
- Frontend `MediaGenerator.jsx` : lit `/me/features`, masque les onglets désactivés, affiche un bandeau "Génération IA désactivée pour ce client" si les deux flags sont OFF.

### 🔔 4) Alerte demandes de devis non traitées (>10)
- `GET /me/catalog/stats` retourne désormais `pending_quotes_alerts: [{product_id, product_name, pending_count, oldest_at}]` pour tout produit dépassant le seuil de 10 clics "Demander un devis" non traités.
- Nouveau endpoint `POST /me/catalog/quotes/mark-treated` qui marque tous les clics non traités d'un produit comme traités (champ `treated_at` + `treated_by`).
- Frontend `CatalogStats.jsx` : nouveau bandeau ambré au-dessus du tunnel, listant chaque produit en alerte avec bouton "Marquer traitées".

### 📥 5) Export CSV événements catalogue
- `GET /me/catalog/export.csv?days=N&event_type=` retourne un fichier CSV (séparateur `;`, encodage UTF-8) avec les 5000 derniers événements de la période. Colonnes : date, event_type, product_id, sku, name, referrer, user_agent (IP exclue).
- Frontend `CatalogStats.jsx` : bouton "CSV" à côté du sélecteur de période, télécharge directement.

### 💳 6) Stripe Checkout pour Formations Payantes
- Nouveau module `routes/payments_stripe.py` qui expose 3 endpoints via `emergentintegrations.payments.stripe.checkout` (STRIPE_API_KEY=sk_test_emergent en .env) :
  - `POST /me/formations/{fid}/stripe/checkout` — crée une session Stripe Checkout (montant lu côté serveur depuis `formations.price`, jamais frontend). XOF converti en EUR (655.957) car Stripe Checkout ne supporte pas XOF.
  - `GET /payments/stripe/status/{session_id}` — polling status, crée l'enrollment de manière idempotente après confirmation.
  - `POST /webhook/stripe` — handler webhook qui crée également l'enrollment idempotent.
- Nouvelle collection `payment_transactions` `{session_id, kind, formation_id, user_id, amount, currency, amount_xof, payment_status, enrollment_created, ...}`.
- Frontend `Formations.jsx` : bouton orange/ambré "Acheter (X XOF)" pour formations `access=paid`, redirige vers Stripe. Au retour, polling de 5×2s + bandeau succès/échec affiché en haut de `/portal/formations/{fid}?session_id=...`.

### 🆕 7) Fix badge "Nouveau" pour sections Admin Settings extraites
- `MetaConfigSection` et `PayrollWebhooksSection` étaient extraites dans des fichiers séparés sans wrapping `Filterable`, donc invisibles au système de bulles "NOUVEAU".
- Fix : les 2 composants sont maintenant enveloppés dans `<Filterable title="...">` au point de mount dans `AdminSettings.jsx`, et leurs titres ajoutés à `NEW_SECTIONS` (badges 21 jours).

### 🪟 8) Catalogue public en multi-colonnes responsive
- Container élargi : `max-w-7xl` → `max-w-screen-2xl` (1280 → 1536px).
- Grilles produits + brochures : `sm:grid-cols-2 lg:grid-cols-3` → `sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5`. Visuellement vérifié avec 2 produits : 2 colonnes confirmées sur écran HD.

### ✅ Tests
- 10 nouveaux pytest verts (`tests/test_iter38o_edit_holiday_ai_csv.py`) : édition créateur/admin/employé attribué, lock après justification, exclusion jours fériés, gating AI image/vidéo, bypass admin, CSV export, alertes pending quotes + mark-treated.
- Test legacy `test_admin_can_edit_and_delete_only` mis à jour pour refléter la nouvelle gating.
- Régression iter38 (a→o) : **105/105 verts**. Cashier (Iter36u→Iter37h) : **91/91 verts**.

## Iter38n (2026-05-27) — Cockpit Statistiques Catalogue (vues / partages / devis)

### 📊 1) Backend `routes/catalog_analytics.py`
- Nouveau module (~270 lignes) qui capture 4 types d'événements anonymes sur le catalogue public : `catalog_view`, `product_og_fetch`, `product_share`, `product_quote_click`.
- Collection `db.catalog_events` `{id, event_type, tenant_id, product_id, product_sku, product_name, referrer, user_agent, ip_hash, created_at}` — IP hashée (SHA-256 tronqué) pour zéro PII stockée.
- Endpoint public `POST /api/public/catalog/track` (anonyme) — résolution automatique du tenant via `product.tenant_id`.
- Endpoint portail `GET /api/me/catalog/stats?days=N` — totaux par type, top 5 produits, tunnel de conversion (share_rate, quote_rate), timeline quotidienne dense.
- Endpoint portail `GET /api/me/catalog/history?days=N&event_type=` — flux des derniers événements (sans ip_hash).
- Gating multi-tenant : super-admin voit tout, sinon scoped au `tenant_id` (logique alignée sur cashier).
- Accès : Admin, Superviseur, et **tous les utilisateurs suivis** (tracked_user_id ou tracked_role). Refusé pour les clients réguliers (403).

### 🪝 2) Hooks dans server.py
- `GET /api/public/products` log `catalog_view` à chaque hit.
- `GET /api/public/og/product/{id}` log `product_og_fetch` avec le tenant du produit résolu.
- Tracking best-effort : un échec d'analytics ne casse jamais la requête utilisateur.

### 🛍️ 3) Frontend public — Catalogue.jsx
- Nouvelle fonction `trackCatalogEvent(eventType, product)` (fetch keepalive vers `/api/public/catalog/track`).
- Bouton "Partager" → fire `product_share`. Bouton "Demander un devis" → fire `product_quote_click` au clic Link.

### 🎛️ 4) Frontend portail `/portal/catalog-stats` — CatalogStats.jsx
- Nouvelle page (~280 lignes) avec :
  - 4 KPI cards (Vues catalogue, Aperçus produits, Partages, Devis demandés)
  - Tunnel de conversion avec barres proportionnelles
  - Top 5 produits (tableau Aperçus/Partages/Devis/Total)
  - 3 sparklines quotidiennes (Aperçus/Partages/Devis)
  - Historique filtrable des 100 derniers événements (filtre par type d'événement)
- Sélecteur de période (7/14/30/60/90 jours).
- Entrée sidebar "Statistiques catalogue" (icône BarChart3) visible pour admin/sup/tracked.
- Route React `/portal/catalog-stats` ajoutée dans `App.js`.

### ✅ Tests
- 14 nouveaux pytest verts (`tests/test_iter38n_catalog_analytics.py`) : tracking + résolution tenant, gating (admin/sup/tracked OK, regular client 403), top products, tenant isolation, funnel ratios, timeline dense, history avec filtre, exclusion ip_hash de la réponse, hooks implicites via /public/products & /public/og/product.
- Régression iter38 (a→n) : **82/82 verts**.

## Iter38m (2026-05-27) — Jours fériés GRH + Dépenses pour Employé + Aperçu/Renvoi WA

### 📅 1) Jours fériés (GRH) — Onglet complet avec import par pays
- Nouvelle collection `db.hr_holidays` `{tenant_id, date, label, holiday_type, is_paid}`.
- 5 nouveaux endpoints dans `routes/hr.py` : `GET /hr/holidays?year=`, `POST /hr/holidays`, `PATCH /hr/holidays/{hid}`, `DELETE /hr/holidays/{hid}`, `POST /hr/holidays/import?year=&country=`.
- Catalogue de jours fériés fixes par pays (BF, CI, SN, FR) — Burkina Faso par défaut (10 jours fériés nationaux + religieux : Nouvel An, Soulèvement populaire, Journée des femmes, Fête du Travail, Journée du 4 août, Indépendance, Assomption, Toussaint, Proclamation République, Noël).
- Bouton "Importer fêtes {ANNÉE} ({PAYS})" déclenche l'import idempotent + bandeau d'info pour les fêtes mobiles (Aïd, Mawlid) à saisir manuellement.
- Frontend : nouvel onglet "Jours fériés" dans le module GRH (entre Absences et Taxes). Tableau éditable avec date / jour de la semaine / libellé / type (national/religieux/local/autre) / payé. CRUD complet via modal.

### 💸 2) Dépenses Caisse → attribuables à un Employé
- `cashier_expenses` étendu : nouveaux champs `attribution_type` ("third_party" | "employee"), `employee_id`, `employee_user_id`, `employee_name_snapshot`.
- Nouveau endpoint `GET /cashier/expenses/employees-list` (admin/sup/caissier/Comptable) — liste légère des employés du tenant pour le dropdown.
- Le formulaire de création de dépense présente désormais un toggle "Tiers / Fournisseur" ↔ "Employé". Quand "Employé" est sélectionné, un dropdown liste les employés enrôlés du tenant.
- Backend `late_unjustified_for_employee` étendu : inclut les dépenses où `employee_user_id == user_id`, en plus de celles créées par l'utilisateur. Impact direct sur la fiche de paie (déduction visible).
- `GET /cashier/expenses/me/dashboard-card` étendu : retourne aussi les dépenses attribuées à l'utilisateur (employee_user_id), pas seulement les siennes.
- `GET /me/welcome-briefing` `expense_reminder` : étendu de la même façon — un employé voit le rappel dès qu'une dépense lui est attribuée, sans avoir besoin du flag `can_cash`.
- Frontend `ExpensesTab` : nouvelle colonne "Attribuée à" affichant le nom de l'employé concerné (badge rose). Carte dashboard désormais visible pour tout utilisateur ayant des dépenses en attente attribuées (gating élargi).

### 📩 3) Aperçu / Renvoi message WhatsApp (Reçus & Factures / Proformas)
- Nouveau composant `WaPreviewModal` dans `CashBilling.jsx` : ouvert via clic sur le badge WhatsApp dans les tables Caisse et Facturation.
- Affiche : statut dernier envoi (OK vert / KO rouge / Aucun envoi), date+heure, module utilisé (Meta Cloud API + nom template), destinataire E.164, PDF joint, erreur éventuelle, aperçu textuel du message.
- Bouton "Renvoyer le message" / "Envoyer maintenant" qui re-fire `POST /cashier/receipts/{id}/send-whatsapp` ou `/cashier/invoices/{id}/send-whatsapp` (idempotent — l'endpoint existant gère déjà la mise à jour des `whatsapp_last_*`).
- Accessible aux rôles admin, superviseur, **et caissier (can_cash=true)** — déjà permis par `_can_invoice` côté backend.

### ✅ Tests
- 12 nouveaux pytest verts (`tests/test_iter38m_holidays_employee_expense.py`) : holidays CRUD + import idempotent + isolation tenant + gating ; expenses employee attribution + validation + dashboard card + welcome briefing.
- Régression iter38 (a→m) : **81/81 verts**. Cashier régression Iter36u→Iter37h : **91/91 verts**.

## Iter38k (2026-05-27) — Nano Banana production-ready + SMS inbox + Meta webhook auto-subscribe

### 🎨 1) Gemini Nano Banana — Génération d'images IA (production)
- Nouveau module `routes/ai_media.py` (~200 lignes) utilisant `emergentintegrations.llm.chat.LlmChat` avec modèle `gemini-3.1-flash-image-preview`.
- 5 endpoints : POST `/me/ai/generate-image`, POST `/me/ai/edit-image`, GET `/me/ai/history`, GET `/files/ai/{tenant}/{filename}`, POST `/cashier/products/generate-icon` (version réelle, replaces stub 503).
- Stockage local `/app/backend/uploads/ai/{tenant_id}/...`. Historique dans `db.ai_generations`.
- Test E2E : icône laptop bleu générée en ~8s, PNG 639 KB.

### 🖼️ 2) Page Générateur d'Images (frontend)
- `MediaGenerator.jsx` complètement réécrite : prompt textarea + format (carré/portrait/paysage) + mode icône, upload image de référence, aperçu + télécharger, galerie historique 24 dernières.

### 📱 3) Canal SMS dans l'inbox unifiée
- `routes/unified_inbox.py` étendu : SMS = 3e canal (badge orange Smartphone).
- Helper `_inbox_sms_send_helper` réutilise `_sms_dispatch` (auto-routing Orange/Moov/Telecel).
- Frontend filtre, badge et composer mis à jour.

### 🔔 4) Meta webhook auto-subscribe après OAuth
- Callback OAuth `routes/meta.py` : auto-souscription `POST /{page_id}/subscribed_apps` avec `subscribed_fields=messages,messaging_postbacks,feed`. Best-effort.
- Plus besoin de configurer manuellement chaque Page dans Meta App Dashboard.

## Iter38j (2026-05-27) — Bug fix QR URL + Inbox unifiée complète (mini-Hootsuite)

### 🐛 1) Fix bug URL preview dans les QR codes
- Cashier.py `_public_base_url()` rejette automatiquement les URLs `*.preview.emergentagent.com` → fallback `https://sawalismartsystems.com`.
- Backfill endpoint `POST /admin/cashier/qr/rewrite-base-url` → 1091 documents corrigés (689 reçus + 402 factures).

### 📨 2) Inbox unifiée complète
- Backend `POST /me/inbox/send` + `POST /me/inbox/mark-read/{channel}/{thread_id}`.
- Frontend : composer (textarea + Entrée pour envoyer), mark-read auto à l'ouverture, polling 20s, titre onglet `(N) Inbox — SAWALI`, auto-scroll bottom.



### 🐛 1) Fix bug URL preview dans les QR codes (factures, proformas, reçus)
- **Bug** : Les QR codes des PDF/HTML générés pointaient vers `https://sawali-portal.preview.emergentagent.com/verify/...` au lieu de l'URL publique production.
- **Cause** : variable d'environnement `PUBLIC_BASE_URL` du conteneur `.env` était définie sur preview, et utilisée comme fallback par `cashier.py:_public_base_url()`.
- **Fix backend** (`routes/cashier.py`) : la fonction détecte et **ignore** les URLs `*.preview.emergentagent.com` / `*.localhost` → fallback automatique sur `https://sawalismartsystems.com`. L'admin peut toujours surcharger via setting DB `public_base_url`.
- **Backfill** : nouvel endpoint admin `POST /api/admin/cashier/qr/rewrite-base-url` qui réécrit les `qr_url` existants en remplaçant la base. **Exécuté** sur la BDD : **1 091 documents corrigés** (689 reçus + 402 factures) → tous maintenant en `https://sawalismartsystems.com/verify/{token}`.

### 📨 2) Inbox unifiée complète (envoi + marquer-lu + polling)
- **Backend** (`routes/unified_inbox.py`) :
  - `POST /api/me/inbox/send` — route vers WhatsApp ou Messenger selon `channel`, persiste outbound dans la collection ad hoc.
  - `POST /api/me/inbox/mark-read/{channel}/{thread_id}` — flag tous les messages inbound non-lus du thread avec `read_by_us_at`.
  - Calcul `unread_count` Messenger respecte maintenant `read_by_us_at`.
- **Frontend** (`UnifiedInbox.jsx`) :
  - **Composer fonctionnel** : textarea + bouton Envoyer, raccourci Entrée pour envoyer / Maj+Entrée saut de ligne, optimistic update.
  - **Marquer-lu auto** : à l'ouverture d'un thread, mark-read silencieux + refresh des compteurs.
  - **Polling 20s** : refresh automatique de la liste des threads.
  - **Titre onglet dynamique** : `(3) Inbox — SAWALI` quand 3 messages non-lus.
  - **Auto-scroll** vers le bas à chaque nouveau message.

## Iter38i (2026-05-27) — Inbox omnicanal unifiée (WhatsApp + Messenger) — première version

### 📥 1) Backend routes/unified_inbox.py
- Module agrégeant whatsapp_messages + meta_messenger_messages en threads recency-sorted.
- Endpoints GET pour lister threads et messages d'un thread.

### 🖼️ 2) Frontend UnifiedInbox.jsx
- Layout 2-pane (threads + messages), filtres par canal, badges colorés.

### 🧭 3) Sidebar + routes
- Entrée "Inbox unifiée (WA + Messenger)" + route /portal/inbox.



### 📥 1) Backend `routes/unified_inbox.py`
- Nouveau module (~150 lignes) agrégeant `db.whatsapp_messages` et `db.meta_messenger_messages` en threads recency-sorted.
- Endpoint `GET /api/me/inbox/unified` : retourne max 60 threads avec channel/peer_id/peer_name/preview/last_at/unread_count/total_count.
- Endpoint `GET /api/me/inbox/unified/{channel}/{thread_id}` : retourne les messages ordonnés d'un thread (50 par défaut), avec direction (inbound/outbound), texte, timestamp, media_url.
- Multi-tenant strict + gating Messenger (403 si `meta_messenger` désactivé).
- Compte agrégé : `totals.unread`, `totals.whatsapp`, `totals.messenger`.

### 🖼️ 2) Frontend `UnifiedInbox.jsx`
- Nouvelle page `/portal/inbox` (~180 lignes) avec layout 2-pane :
  - Gauche : liste threads avec badge canal coloré (vert WA / bleu MSG), compteur non-lus, dernière prévisualisation, horodatage.
  - Droite : messages du thread sélectionné avec bulles direction-aware (indigo→outbound, gris→inbound).
- Filtre par canal (Tous / WhatsApp / Messenger) avec compteurs.
- Bouton "Actualiser" + auto-fetch au montage.
- Pièces jointes (media_url) cliquables.

### 🧭 3) Sidebar + routes
- Nouvelle entrée "Inbox unifiée (WA + Messenger)" dans la sidebar portail.
- Route React `/portal/inbox` ajoutée.

## Iter38h (2026-05-27) — Implémentation Meta Graph API complète

### 🏛️ 1) Module backend routes/meta.py
- Nouveau module FastAPI (~470 lignes) : OAuth Facebook Login, Pages API, Messenger Platform, Marketing API, Webhook avec validation HMAC SHA256.
- 16 endpoints au total. Gating multi-tenant strict.
- Stockage : db.meta_integrations, db.meta_messenger_messages, db.meta_webhook_events.

### ⚙️ 2) Configuration admin Meta App
- Section MetaConfigSection.jsx (~150 lignes) dans Admin Settings.
- Champs : App ID, App Secret (masqué), Verify Token, Graph version, Redirect URI.
- Bandeau guide en 5 étapes côté Meta App Dashboard.

### 🌐 3) Page Portail /portal/meta
- Composant MetaIntegration.jsx (~360 lignes) avec 3 onglets : Pages, Messenger, Ads.
- OAuth connect/disconnect, composer post, uploader photo, conversations Messenger, stats Ads.

### 🧭 4) Sidebar + routes
- Entrée "Meta (Facebook/Messenger/Ads)" visible si au moins une feature Meta activée.

### ✅ 5) Tests pytest
- 11/11 tests passent (tests/test_iter38h_meta.py).



### 🏛️ 1) Module backend `routes/meta.py`
- Nouveau module FastAPI (~470 lignes) : OAuth Facebook Login, Pages API, Messenger Platform, Marketing API, Webhook avec validation HMAC SHA256.
- Endpoints : 16 routes au total (admin config, OAuth, status, pages CRUD, messenger conversations+send, ads accounts+insights+campaigns, webhook GET+POST).
- Gating multi-tenant strict : chaque endpoint vérifie `tenant_features.meta_pages/meta_messenger/meta_ads` avant de toucher Graph API → 403 sinon.
- Stockage : `db.meta_integrations` (1 doc par tenant avec user_token, pages, ads_accounts), `db.meta_messenger_messages` (inbox webhook), `db.meta_webhook_events` (autres événements).
- Sécurité : HMAC SHA256 sur webhook + signature de state OAuth + ttl 10 min sur state.

### ⚙️ 2) Configuration admin Meta App
- Nouvelle section `MetaConfigSection` extraite dans `/app/frontend/src/pages/admin/sections/MetaConfigSection.jsx` (~150 lignes, autonome).
- Affichée dans Admin Settings (anchor `s-meta-integration`).
- Champs : App ID, App Secret (masqué, vide = conserver), Verify Token Webhook, Graph version (défaut `v20.0`), Redirect URI auto-rempli.
- Bouton copier pour Redirect URI + URL Webhook (à coller dans Meta App Dashboard).
- Bandeau jaune avec les 5 étapes à suivre côté Meta (créer l'App, activer produits, configurer OAuth, configurer Webhook, demander permissions en App Review).

### 🌐 3) Page Portail `/portal/meta`
- Composant `MetaIntegration.jsx` (~360 lignes) avec 3 onglets gating-aware :
  - **Pages** : sélection de Page, lister derniers posts (avec réactions/commentaires), composer un nouveau post (texte + lien), publier une photo (URL).
  - **Messenger** : sélection de Page, lister conversations récentes avec participant + dernier message + horodatage.
  - **Ads** : sélection compte publicitaire + preset date, cartes statistiques (Impressions, Clics, Dépenses, Portée, CTR, CPC).
- Bouton "Connecter Facebook" → flow OAuth (popup Meta) ; "Déconnecter" pour révoquer.
- Retour OAuth via `?cb=1&status=success/error` : toast + reload du status.

### 🧭 4) Sidebar + routes
- Nouvelle entrée sidebar "Meta (Facebook/Messenger/Ads)" visible uniquement si au moins une feature Meta est activée (ou si admin/superviseur).
- Route React `/portal/meta` ajoutée dans `App.js`.

### ✅ 5) Tests pytest
- 11/11 tests passent : `tests/test_iter38h_meta.py` couvre :
  - Admin config GET/PUT (avec préservation des secrets si champ vide)
  - Status tenant par défaut (3 features OFF, connected=false)
  - OAuth URL 403 sans features activées
  - Pages endpoint 403 sans features
  - Webhook GET avec/sans bon verify token
  - Webhook POST avec mauvaise/bonne signature HMAC
  - Disconnect idempotent



### 🌐 1) Open Graph (preview riche social)
- `index.html` : meta-tags par défaut (og:type, og:site_name, og:title, og:description, og:image, twitter:card) avec logo SAWALI comme image partagée.
- Backend : nouvel endpoint `GET /api/public/og/product/{id}` qui sert un HTML statique avec OG tags spécifiques au produit (titre, prix HT, image produit, lien devis), avec auto-redirect humain vers `/catalogue` via meta-refresh. Conforme aux exigences des bots Facebook/WhatsApp/LinkedIn/Twitter (ils ne lisent pas le JS).
- Frontend : bouton "Partager" sur chaque card du catalogue → `navigator.share()` ou fallback clipboard. URL partagée : `/api/public/og/product/{id}`.
- `document.title` dynamique sur la page `/catalogue` pour l'expérience navigateur.

### 🏢 2) Toggles Intégration Meta dans SMART COMMUNICATIONS
- Backend : 3 nouveaux feature flags `meta_pages`, `meta_messenger`, `meta_ads` ajoutés à `DEFAULT_CLIENT_FEATURES` (server.py ~ligne 2912) et au modèle `ClientFeaturesUpdate` (ligne ~3225).
- Frontend `AdminClientFeatures.jsx` : 3 nouvelles entrées dans `FEATURE_META` avec icônes Facebook/MessageCircle/Megaphone (bleu Meta) — pattern identique aux toggles RGPD (anon_*).
- Section "SMART COMMUNICATIONS" / Fiche Client lié → onglet Features : 3 toggles ON/OFF — Meta Pages Facebook, Meta Messenger, Meta Ads Manager.
- Lorsque OFF (défaut) : aucun module Meta dans le portail utilisateur. Lorsque ON : module accessible (l'implémentation OAuth + API Meta complète sera dans Iter38h+ via playbook).

## Iter38f (2026-05-27) — Auto-sync CHANGELOG + Catalogue public + Meta-OG + Toggles Meta

> Note : iter38g (Meta-OG + toggles) a été fusionnée dans cette section après remaniement.

### 🌐 1) Open Graph (preview riche social)
- `index.html` : meta-tags par défaut (og:type, og:site_name, og:title, og:description, og:image, twitter:card).
- Backend `GET /api/public/og/product/{id}` : sert un HTML statique avec OG tags spécifiques au produit, auto-redirect humain vers `/catalogue`.
- Bouton "Partager" sur chaque card catalogue (`navigator.share()` ou clipboard).

### 🏢 2) Toggles Meta dans SMART COMMUNICATIONS
- 3 nouveaux feature flags `meta_pages`, `meta_messenger`, `meta_ads`.
- Visibles dans `AdminClientFeatures.jsx` (fiche Client lié → Features).




### 🔁 1) Auto-sync CHANGELOG → roadmap_actions
- Backend `server.py` : parser `_sync_roadmap_from_changelog()` qui scanne `/app/memory/CHANGELOG.md` à chaque GET `/api/admin/roadmap-actions`.
- Identifie les blocs `## IterXXX (date) — …` et extrait chaque `### emoji N) Title` comme action `ACT-CL-IterXXX-NN`.
- Filtre intelligent : ignore les sections "Tests", "Frontend", "Backend", "Prochaines …", "🚨", "🟧", "🟨", "🟦", "P0/P1/P2/P3".
- Cleanup des orphelins (entrées dont la section a été retirée).
- Backfill : 145 actions historiques du 13/05 → 27/05/2026 désormais visibles dans Admin Settings.

### ⏱️ 2) Estimation auto de durée/coût
- Heuristique `_estimate_duration_h(details)` basée sur la taille des détails (proxy de la complexité).
- Bornée 0.25h ↔ 3.0h. Coût XOF recalculé via `DEFAULT_ROADMAP_HOURLY_RATE_XOF` (25 000 XOF/h).
- Totalisation actuelle : 178 actions, 252.8h, 6 320 000 XOF.
- Editable manuellement par l'admin via PATCH `/admin/roadmap-actions/{code}`.

### 🛍️ 3) Catalogue public e-commerce
- Backend : nouvel endpoint `GET /api/public/products` (sans auth) renvoyant `{count, categories: [{label, items}]}` avec uniquement les produits `is_public=true && active=true && deleted_at=null`. Champs sensibles (stock, tenant_id, notes internes) exclus.
- Frontend `/catalogue` (Catalogue.jsx) refondue : 2 sections — **Produits & Services** (nouvelle, depuis `/public/products`) + **Brochures & Fiches produits** (existante).
- UX : recherche texte + pills de filtres par catégorie + grouping par catégorie + cards avec image, prix HT, unité, TVA, bouton "Demander un devis" → `/rdv?product=NAME&sku=SKU`.
- Page RDV (`RDV.jsx`) lit les params `product` et `sku` via `useSearchParams` et pré-remplit `subject` + `message` (sans écraser si l'utilisateur a déjà tapé quelque chose).

## Iter38e (2026-05-27) — UI Webhooks n8n + WhatsApp Status Badge + Catalog enrichments

### 🔧 1) Frontend Admin UI — Webhooks Paie (n8n)
- **Bloqueur P0 résolu** : erreur de syntaxe JSX dans `AdminSettings.jsx` (lignes 2229-2241, fragments orphelins laissés par un précédent `search_replace`).
- **Refactor** : `PayrollWebhooksSection` extrait dans `/app/frontend/src/pages/admin/sections/PayrollWebhooksSection.jsx` (composant autonome, ~225 lignes), pour alléger `AdminSettings.jsx` (5247 lignes au lieu de 5476).
- Section visible dans Admin Settings, configure outbound (URL n8n, secret HMAC, auto mensuel) + inbound (URL exposée, secret HMAC, format JSON) + journal d'audit (20 dernières entrées).
- Anchor : `s-webhooks-paie-n8n` (testid : `admin-payroll-webhooks`).

### 📲 2) B.1 — Indicateur de résultat WhatsApp (OK/KO persistant)
- **Backend** (`cashier.py`) :
  - Sur **KO** : persiste `whatsapp_last_attempt_at`, `whatsapp_last_status="ko"`, `whatsapp_last_error`, `whatsapp_last_to` dans `db.receipts` et `db.invoices`.
  - Sur **OK** : persiste les mêmes champs avec `status="ok"` et `last_error=None` (efface l'erreur précédente).
- **Frontend** : nouveau composant `/app/frontend/src/components/WaStatusBadge.jsx`.
  - Badge vert "✓ Envoyé → +226… (date)" quand `whatsapp_last_status="ok"` ou `whatsapp_sent_at` présent (legacy).
  - Badge rouge "⚠ KO — {message}" quand `whatsapp_last_status="ko"`.
  - Affiché dans `ReceiptPrint.jsx` et `InvoicePrint.jsx` à côté du bouton "Envoyer par WhatsApp".
  - Le doc est rechargé après chaque envoi pour rafraîchir le badge en temps réel.

### 📦 3) B.2 — Date de dernière utilisation des produits
- **Backend** (`cashier.py`) : helper `_bump_products_last_used(items, tenant_id)` qui met à jour `last_used_at` (ISO UTC) sur tous les produits référencés (via `product_id`) dans une **facture réelle** (jamais sur proforma).
- Hook posé à 2 endroits : (a) création d'invoice avec `kind=="invoice"`, (b) conversion proforma → invoice.
- **Frontend** : badge vert "🕒 {date}" affiché dans la liste du catalogue (CashBilling.jsx > tab "Catalogue") avec tooltip horodaté complet. Testid : `product-last-used-{id}`.

### 🖼️ 4) B.3 — Upload PNG/JPG d'icônes + toggle catalogue public
- **Backend** (`cashier.py`) :
  - Champ `is_public: bool = False` ajouté au modèle `ProductPayload`.
  - Nouvel endpoint `POST /api/cashier/products/generate-icon` (supervisor+) — stub graceful retournant 503 avec message clair (intégration Nano Banana en attente de playbook).
- **Frontend** (`CashBilling.jsx`) :
  - Nouveau type de champ `imageUpload` dans `CrudTab`.
  - Composant `ImageUploadField` : upload via `/me/upload` (multipart, max 5 Mo, PNG/JPG/WEBP), miniature 64×64, bouton "Retirer", input texte (URL manuelle), bouton "Générer IA" avec champ prompt.
  - Formulaire produit : remplace l'input `image_url` plain text par le widget complet. Nouvelle checkbox "Exporter au catalogue public" (`is_public`).

### ✅ Tests
- 35/35 tests caisse + webhooks payroll passent (test_iter36u, test_iter37d, test_iter37f, test_iter38d).
- Lint Python + JS : aucun problème.
- Smoke test frontend : page de login charge sans erreur de compilation.


## Iter38c (2026-05-26) — Caisse Dépenses + Matricule auto + Dashboard card

### 💸 1) Caisse — Module "Dépenses" (cash | chèque)
- **Backend** (`/app/backend/routes/cashier_expenses.py`, 380 lignes) :
  - Collection `db.cashier_expenses` : `amount`, `currency`, `method` (cash|check), `payee`, `motif`, `expense_date`, `note`, `is_justified`, `justified_at`, `justified_by`, `justification_text`, `justification_proof_url`, `forced_justification`, `deleted_at`.
  - **Permissions** :
    - Création : admin, sup, can_cash, ou Comptable.
    - Édition / suppression / `unjustify` : **admin uniquement** (sup/can_cash → 403).
    - `force=true` lors d'une justification : admin uniquement (pour outrepasser le délai).
- **Endpoints** :
  - `GET /api/cashier/expenses?month=&status=&user_id=` (filtres : `justified`, `unjustified`, `late_unjustified`, `all`).
  - `POST /api/cashier/expenses` (création — pas justifiée à la création).
  - `PATCH /api/cashier/expenses/{eid}` (admin).
  - `DELETE /api/cashier/expenses/{eid}` (admin, soft delete).
  - `POST /api/cashier/expenses/{eid}/justify` — **REFUSE 400 si délai dépassé** (sauf admin avec `force=true`). Enregistre `justified_at` (UTC ISO), `justified_by` (user_id), `justified_by_name`, `justified_by_email`, `justification_text`, `justification_proof_url`, `forced_justification` bool.
  - `POST /api/cashier/expenses/{eid}/unjustify` (admin) — annule la justification (en cas d'erreur).
  - `GET /api/cashier/expenses/monthly-summary?month=YYYY-MM` — totaux + ventilation par utilisateur (justified, unjustified, late_unjustified, count).
  - `GET /api/cashier/expenses/me/dashboard-card` — synthèse pour l'utilisateur courant.
- **Délai admin-configurable** (`settings.expense_justification_deadline_hours`) :
  - **72h par défaut**.
  - **0 = pas de limite** (toujours acceptable).
  - Modifiable via Admin Settings → section "Caisse — Délai de justification des dépenses".
- **Intégration paie** :
  - Helper `late_unjustified_for_employee(db, tenant_id, user_id, month)` calcule la somme des dépenses non justifiées au-delà du délai pour le mois.
  - `_compute_payslip` ajoute le champ `late_expenses_deduction` (déduit du net).
  - PDF de paie : nouvelle rubrique rouge "DÉPENSES CAISSE NON JUSTIFIÉES (EN RETARD)" affichée si > 0, déduite avant le NET À PAYER.

### 📊 2) Dashboard portail — Carte "Mes dépenses à justifier" (utilisateurs suivis)
- Composant `<UnjustifiedExpensesCard />` dans `Dashboard.jsx`.
- Affichée uniquement pour utilisateurs **tracked** (`tracked_user_id` ou `tracked_role` défini) **ET** avec accès Caisse (admin/sup/can_cash/Comptable).
- Affiche : `count`, `total_unjustified`, `late_unjustified` (en rouge), `deadline_hours`.
- Lien direct vers `/portal/cash` pour aller régulariser.
- `data-testid` : `dashboard-unjustified-expenses-card`, `dashboard-unjust-total`, `dashboard-unjust-late`.

### 🆔 3) Personnel GRH — Matricule auto-généré
- Compteur per-tenant : `db.employee_matricule_counters` `{tenant_id, seq}`.
- Format : `MAT-{prefix}-{seq:05d}` où `prefix` = 4 premiers caractères alphanumériques de la company tenant (uppercase).
- Exemple : `MAT-SAWA-00001`, `MAT-SAWA-00002`, …
- Généré automatiquement à la **création** d'un employé.
- **Endpoint backfill** : `POST /api/hr/employees/backfill-matricules` — attribue un matricule à tous les employés legacy (admin/sup/Comptable). Super-admin → opère sur tous les tenants.
- **Affichage** : colonne "Matricule" en première position de l'onglet Personnel + sur la fiche de paie PDF.

### 🧪 Tests
- `tests/test_iter38c_expenses_matricule.py` : **11/11 tests pytest verts** (création, perms admin-only, justification dans délai, refus hors délai, force admin, deadline=0 illimité, monthly-summary, isolation cross-tenant, dashboard-card, matricule auto + increment, backfill, payslip late deduction).
- **Régression iter38 : 56/56 verts** (11 iter38a + 14 iter38b + 11 iter38c + 9 iter38_comptable + 11 iter38_grh_redux).
- Testing agent : aucun bug.

### 🎨 Frontend
- **CashBilling.jsx** : nouvel onglet "Dépenses" entre Facturation et Catalogue. Visible pour admin/sup/can_cash/Comptable.
- **ExpensesTab.jsx** (nouveau, 380 lignes) : tableau, formulaire création, modal de justification avec preuve URL + alerte "délai dépassé" + checkbox force admin, 4 filtres de statut, 4 cards de synthèse.
- **Dashboard.jsx** : carte unjustified ajoutée (visible pour utilisateurs suivis Caisse).
- **HumanResources.jsx** : colonne Matricule (`hr-personnel-matricule-{id}`).
- **AdminSettings.jsx** : nouvelle Section pour `expense_justification_deadline_hours` (input number, défaut 72, 0 = illimité).


## Iter38b (2026-05-26) — GRH Phases 4+5+6 + Mini-graph + Pays/Indicatifs configurables

### 🌍 1) Pays & indicatifs téléphoniques configurables (par défaut Burkina Faso +226)
- **Nouveau module** `/app/backend/routes/tenant_meta.py` :
  - Endpoints publics : `GET /api/me/tenant-meta` (tous les users) — retourne `{country_code, country_name, dial_prefix, phone_example}`.
  - Endpoints admin : `GET/POST /api/admin/countries`, `PATCH/DELETE /api/admin/countries/{code}`, `GET/PATCH /api/admin/tenant-country`.
  - Catalogue seedé : Burkina Faso (par défaut), Côte d'Ivoire, Sénégal, Mali, Niger, Togo, Bénin, Guinée, France, Cameroun.
  - **BF non supprimable** (garde-fou).
- **Frontend** :
  - `AuthContext` étendu : récupère et stocke `tenantMeta` au login dans le state ET dans `localStorage["sawali_tenant_meta"]`.
  - Helper `/app/frontend/src/lib/tenantMeta.js` : `phonePlaceholder()` lit le localStorage et retourne l'exemple — utilisable depuis n'importe quel composant sans hook.
  - **Nouvelle section AdminSettings** : "Pays & indicatifs téléphoniques" — sélecteur de pays par défaut, liste avec suppression, formulaire d'ajout.
  - Placeholders dynamiques dans `Contacts.jsx` (3 inputs), `Subscriptions.jsx` (phone), `AdminSettings.jsx` (WhatsApp société).

### 📅 2) GRH Phase 4 — Absences / Déductions (choix 1.b + 2.c)
- Collection `db.hr_absences` : `start_date`, `end_date`, `hours_count`, `abs_type` (maladie | conge | non_justifiee | personnelle | autre), `is_justified`, `justification`, `auto_detected`.
- Endpoints :
  - `GET /api/hr/absences?employee_id=&month=YYYY-MM` (filtre tenant strict)
  - `POST /api/hr/absences` (valide end_date ≥ start_date)
  - `PATCH /api/hr/absences/{aid}` (toggle justifiée + édit)
  - `DELETE /api/hr/absences/{aid}`
  - **`POST /api/hr/absences/scan?employee_id=&month=YYYY-MM`** — auto-détection : jours ouvrés (lun-ven) sans aucun `access_log` → propose 8h "non_justifiee" par défaut, NON persistés (l'utilisateur valide en cliquant).
- **Seuil de tolérance** : `db.hr_settings.absence_threshold_hours` (global tenant) + override par employé via `employee.absence_threshold_hours_override`. Au-delà du seuil, l'excédent d'heures non justifiées est déduit au taux horaire de l'employé.

### 🧾 3) GRH Phase 5 — Taxes & Avances (choix 3.a + 4.b + 5.b)
- **Taxes** (collection `db.hr_taxes`) — max **5 par tenant**, configurables 100% :
  - `label`, `calc_type` (`percentage` | `fixed`), `value`, `applies_to` (`gross` | `net`), `active`, `sort_order`.
  - `GET /api/hr/taxes`, `PUT /api/hr/taxes` (remplace toutes — 400 si > 5).
  - Override par employé : `employee.tax_overrides = {tax_id: value}` (déjà côté backend, UI dans Phase 5 v2).
- **Avances** (collection `db.hr_advances`) :
  - `amount`, `currency`, `motive`, `granted_at`, `auto_deduct`, `repaid_amount`, `status` (`pending` → `partial` → `repaid`).
  - `POST /api/hr/advances`, `GET /api/hr/advances?employee_id=`, `POST /api/hr/advances/{aid}/repay`, `DELETE`.
  - **Auto-déduction** sur la paie suivante si `auto_deduct=true` et `status != repaid`.

### 💰 4) GRH Phase 6 — Synthèse mensuelle PDF de paie (choix 6.d)
- `GET /api/hr/employees/{eid}/payslip?month=YYYY-MM` → JSON complet (gross, absence_deduction, taxes, advances, **net**).
- `GET /api/hr/employees/{eid}/payslip.pdf?month=YYYY-MM` → PDF A4 propre (reportlab) :
  - Entête (entreprise, n° employeur, adresse — depuis `hr_settings.payslip_*`).
  - Identité employé, période.
  - GAINS, ABSENCES, RETENUES & TAXES, AVANCES, **NET À PAYER** en bandeau noir.
  - Mentions légales + pied de page (configurables).
- **Modèle configurable** via UI : Réglages → "Modèle de fiche de paie" (nom employeur, N° employeur, adresse, mentions légales, pied de page).
- Math validée par test : 16h travaillées → 16 000 brut → −8 000 (12h−4h seuil × 1000/h) → −1 200 (15% taxes) → −5 000 avance → **net 1 800**.

### 📊 5) Mini-graph "Présence cette semaine" (choix 7.c)
- `GET /api/hr/dashboard/weekly-presence` → top 5 employés (lun→dim courant, UTC) avec `hours` et `days`.
- Frontend : `<WeeklyPresenceCard />` affichée en haut de l'onglet **Personnel** du module GRH — barres horizontales animées (gradient bleu→émeraude) + heures + jours.

### 🎨 6) Frontend HR enrichi
- Nouvelle page jumelle `/app/frontend/src/pages/portal/HumanResourcesAdvanced.jsx` (composants : `WeeklyPresenceCard`, `AbsencesTab`, `TaxesTab`, `AdvancesTab`, `PayslipsTab`, `HrSettingsTab`).
- 7 onglets total : Personnel · Salaires · Présence · **Absences** · **Taxes** · **Avances** · **Paie** · **Réglages**.
- Tous les éléments interactifs ont des `data-testid` (`hr-tab-*`, `hr-absences-*`, `hr-tax-*`, `hr-advance-*`, `hr-payslip-*`, `hr-settings-*`, `hr-weekly-card`, etc.).
- Téléchargement du PDF de paie depuis l'onglet Paie via le bouton "Télécharger PDF".

### ✅ Tests
- **14/14 tests pytest verts** dans `tests/test_iter38b_grh_advanced.py` (couverture : tenant-meta, country CRUD, absences CRUD + scan, taxes limits, advances flow complet, payslip math + PDF, settings, weekly-presence).
- **Régression** : 50/50 iter37 (cashier), 20/20 iter38a (GRH base + Comptable), 14/14 iter38b → **84/84 verts**.
- Aucun bug remonté par le testing agent.

### 🔄 Prochaines étapes
- A.3 (Corbeille Caisse UI) et B.1→B.4 (suite Caisse) après votre déploiement.


## Iter38 (2026-05-26) — Module GRH (Ressources Humaines) Phases 1+2+3 + rôle Comptable

### 🧑‍💼 1) Nouveau rôle tracked `Comptable`
- Ajouté à `TRACKED_USER_ROLES` dans `models.py` (donc apparaît automatiquement dans le dropdown admin → Utilisateurs suivis → Rôle).
- **Permissions** :
  - GRH : lecture + écriture complète (CRUD employés + timesheet).
  - Caisse : lecture seule (GET business_clients, products, receipts, invoices, KPIs, exports, PDFs, tenant-info, etc.).
  - Tentative d'écriture sur Caisse → 401/403 (POST/PATCH/DELETE inchangés, restent restreints à admin/sup/can_cash).
- Helper `_can_view_cashier(user) = _can_invoice(user) OR _is_comptable(user)` ajouté dans `cashier.py`. 17 endpoints GET migrés vers ce helper.

### 📁 2) Module GRH — Nouveau router `/app/backend/routes/hr.py` (monté sur `/api/hr`)
**Phase 1 — Personnel** :
- Collection `db.hr_employees` (champs: `id`, `tenant_id`, `user_id`, `email_snapshot`, `name_snapshot`, `job_title`, `department`, `notes`, `created_at`, `updated_at`, `deleted_at`).
- Isolation tenant : même logique que Caisse (`parent_client_id` → `client_id` → canonical-by-company → self). Super-admin (`admin@sawalismartsystems.com`) voit tous les tenants.
- Endpoints :
  - `GET /api/hr/eligible-users` → utilisateurs du tenant non encore enrôlés.
  - `GET /api/hr/employees?include_deleted=bool` → liste enrichie avec user info.
  - `POST /api/hr/employees` → idempotent (409 si user_id déjà enrôlé en actif).
  - `PATCH /api/hr/employees/{eid}` → update partielle.
  - `DELETE /api/hr/employees/{eid}` → soft delete.
  - `POST /api/hr/employees/{eid}/restore` → restauration.

**Phase 2 — Salaires** :
- Champs sur la fiche employé : `base_salary`, `pay_type` (`monthly` | `hourly`), `currency` (défaut `XOF`), `hourly_rate`, `monthly_hours_baseline` (défaut 160h).

**Phase 3 — Présence (calculée à la volée)** :
- `GET /api/hr/employees/{eid}/timesheet?month=YYYY-MM` → calcule depuis `db.access_logs`.
- Pour chaque (employee.user_id OR email_snapshot, date), agrège `min(created_at)` et `max(created_at)` → "plage min(login)→max(dernière action) du jour" (choix utilisateur 3.c).
- Retourne `days[]` (date, first_seen, last_seen, presence_hours, hits) + `totals` (days_worked, hours_worked, expected_hours, pay_type, base_salary, hourly_rate, **computed_gross** estimé, currency).
- Calcul `computed_gross` :
  - `pay_type=hourly` : `hours_worked × hourly_rate`.
  - `pay_type=monthly` : `base_salary × min(1.0, hours_worked / monthly_hours_baseline)` (proratisation).

### 🖥️ 3) Frontend — Page `/portal/hr` (`HumanResources.jsx`)
- Visible dans la sidebar pour admin/superviseur/Comptable (lien `hrOnly: true` dans `PortalLayout.jsx`).
- 3 onglets : **Personnel** (CRUD + recherche + filtre "fiches supprimées") | **Salaires** (synthèse mensuelle, recalcul brut estimé pour tous les employés) | **Présence** (sélecteur employé + mois, 4 cards de totaux, tableau jour par jour).
- Modal de création/édition employé : choix utilisateur depuis liste tenant, type de paie, salaire base ou taux horaire, heures mensuelles, département, intitulé poste, notes.
- Tous les éléments interactifs ont des `data-testid` (`hr-page`, `hr-tabs`, `hr-tab-personnel/salaries/timesheet`, `hr-personnel-add-btn`, `hr-employee-*`, `hr-timesheet-*`, `hr-totals-*`, etc.).

### ✅ Tests
- **20/20 tests pytest verts** :
  - `tests/test_iter38_grh.py` : 11 tests (eligible-users, CRUD, soft-delete + restore, timesheet 9h+6h proratisé, hourly pay 4h×5000=20000, isolation cross-tenant, permission Comptable read Caisse, blocage write).
  - `tests/test_iter38_comptable_caisse_write_block.py` : 9 tests (créé par le testing agent — vérifie que Comptable est bloqué sur write Caisse).
- **Régression Caisse : 35/35 verts** (iter36u + iter37d + iter37e + iter37f).

### Prochaines phases GRH (P0, plus tard)
- **Phase 4** : Absences/Déductions (suivi des jours/heures d'absence, seuils admin avant déduction du net).
- **Phase 5** : Taxes fiscales (5 taxes globales tenant avec override par employé — choix 4.c) + Avances sur salaire (avec motifs).
- **Phase 6** : Synthèse mensuelle PDF (paie par employé ou par entreprise).


## Latest — Iter37h (2026-05-25) — Voix WA + Reply + Delete RBAC + Duplicate facture

### 🎙️ 1) Notes vocales + transcription dans la fenêtre de discussion WhatsApp
- Bouton micro (rose) ajouté dans le composer de la `ConversationModal` (à côté du Paperclip).
- Pendant l'enregistrement : barre rouge avec chronomètre + 3 boutons :
  - **Transcrire & insérer** → upload audio vers `/me/chat/transcribe` (Whisper), insère le texte dans le textarea (l'utilisateur peut éditer avant d'envoyer).
  - **Envoyer comme note vocale** → stage l'audio en `pendingFile` puis envoie via `/me/whatsapp/send-media`.
  - **Annuler** → arrête le micro et libère la stream.
- Utilise `MediaRecorder` avec négociation des formats (webm/opus → webm → mp4 → ogg).

### 💬 2) Répondre à un message (quote reply)
- Bouton "Répondre" (icône `CornerUpLeft`) sur chaque bulle (apparaît au hover).
- **Backend** : `WhatsAppSendTextRequest.reply_to_message_id` + `send-media` form field `reply_to_message_id`. Forwardé à `_wa_send_text` / `_wa_send_media` qui ajoutent `context.message_id` dans le payload Meta — WhatsApp affiche alors le message en quote.
- **Webhook inbound** capture désormais `msg.context.id` → `doc.reply_to_message_id` pour rendre les réponses du contact dans le thread.
- **UI** : bandeau sky au-dessus du composer pour visualiser le message cité + bouton Annuler. Chaque bulle affiche une "quote bar" si elle est une réponse, avec le texte du message d'origine résolu côté frontend par `message_id`/`wa_message_id`.

### 🗑️ 3) DELETE proforma / facture / reçu (admin ou superviseur uniquement)
- 2 nouveaux endpoints :
  - `DELETE /api/cashier/receipts/{rid}` → soft-delete avec `deleted_at + deleted_by`.
  - `DELETE /api/cashier/invoices/{iid}` → idem.
- Dependency : `get_current_supervisor` (admin ou superviseur). Plain cashier = 401/403.
- Documents soft-deleted exclus des listings, des KPIs, du compteur overdue, du flux auto-relance, des exports CSV/PDF et des endpoints publics PDF/verify.
- Frontend : bouton 🗑 conditionné par `user.role in ("admin", "superviseur")` dans ReceiptsTab et InvoicesTab.

### 📋 4) Dupliquer une facture/proforma (sans nom de client, juste les lignes)
- `POST /api/cashier/invoices/{iid}/duplicate` → retourne `{draft: {kind, business_client_id: null, items: [...], discount_*, notes, due_date: null}, source_id, source_number}`. Ne persiste rien.
- Frontend : bouton **Dupliquer** (icône `Copy`, violet) dans InvoicesTab → pré-remplit le formulaire de création + ouvre le modal, l'utilisateur choisit un client et enregistre.

### ✅ Tests : **129/129 pytest verts** (+8 nouveaux `test_iter37h_delete_duplicate.py`).
- DELETE reçu/facture/proforma : 5 tests (sup OK, plain cashier 401/403, PDF public 404 après delete).
- Duplicate : 3 tests (draft sans client, proforma, accessible aux can_cash).

### 🚨 Action utilisateur en production
1. **Save to GitHub** → **Redéployer** `sawalismartsystems.com`.
2. Vérifier le micro en ouvrant une conversation WA : bouton micro rose dans le composer.
3. Hover sur une bulle pour voir l'option "Répondre".
4. La suppression définitive d'un reçu/facture/proforma n'est visible **que** pour admin/superviseur.
5. Le bouton "Dupliquer" (icône violet) ouvre le formulaire pré-rempli sans client — choisir un nouveau client puis enregistrer.

---

## Latest — Iter37g (2026-05-24) — Templates WhatsApp internes + URLs bibliothèque + PRD split

### 📑 a/ PRD scindé
- `/app/memory/PRD.md` (93 lignes, spec statique : problem statement, architecture, roadmap, backlog).
- `/app/memory/CHANGELOG.md` (~3500 lignes) : tout l'historique Iter34 → Iter37g.

### 📤 b/ Envoi reçu/facture/proforma via templates Meta WhatsApp (avec PDF en pièce jointe)
- **PDF server-side** (`reportlab`) :
  - `build_receipt_pdf(receipt)` — A5 portrait, header tenant, table champs, QR.
  - `build_invoice_pdf(invoice)` — A4 portrait, items table, totaux, QR.
- **Endpoints** :
  - Auth : `GET /api/cashier/receipts/{rid}/pdf`, `GET /api/cashier/invoices/{iid}/pdf` (tenant-scoped).
  - Public (fetchable par Meta CDN) : `GET /api/public/receipt-pdf/{token}`, `GET /api/public/invoice-pdf/{token}` — token = `qr_token` (read-only).
- **Send-whatsapp refactored** : `POST /cashier/receipts/{rid}/send-whatsapp` et `/cashier/invoices/{iid}/send-whatsapp` utilisent désormais `wa_send_template` :
  - Reçu : template `confirmation_paiement_avecrecu` (fr) — header DOCUMENT (PDF) + body {1:client, 2:n°, 3:montant, 4:motif}.
  - Facture/Proforma : template `document_piecejointe_facturation` (fr) — header DOCUMENT (PDF) + body {1:client, 2:type, 3:n°, 4:montant}.
  - **Fallback gracieux** : si Meta refuse le template (params mismatch, non approuvé...), retry sans header, puis texte libre dans la fenêtre 24h.
- **Settings admin** (`PUT /admin/settings`) : `wa_template_receipt_name`, `wa_template_receipt_language`, `wa_template_invoice_name`, `wa_template_invoice_language` (avec UI dans Admin → WhatsApp).

### 🔗 c/ URLs bibliothèque mal formées (fichier introuvable)
- **Root cause** : `media_library.public_url` était stocké **absolu** au moment de l'upload (host de preview ou de prod selon où l'upload a eu lieu). Accédé depuis l'autre environnement, le fichier était introuvable.
- **Fix** : `GET /me/media-library` recalcule `public_url` à la volée en combinant le **host de la requête courante** + le **chemin relatif** de `db.files.url`. Aucune migration DB nécessaire. Compatibilité avec les anciens enregistrements.

### ✅ Tests : **+9 nouveaux pytest verts** (121/121 cumulés)
- `test_iter37g_pdfs_and_templates.py` : 7 tests (PDFs auth + public, send-whatsapp shape).
- `test_iter37g_media_url_rewrite.py` : 2 tests (rewrite host stale → current, filter source préservé).

### 🚨 Action utilisateur en production
1. **Save to GitHub** → **Redéployer** `sawalismartsystems.com`.
2. Admin → Paramètres → **WhatsApp** → vérifier que les 2 templates sont approuvés dans Meta Business Suite avec la structure body décrite ci-dessus.
3. Tester l'envoi d'un reçu et d'une facture → le PDF doit arriver en pièce jointe directe.

---

## Latest — Iter37f (durcissement tenant + admin toggle unread) — 2026-05-24

### 🔒 Durcissement tenant (audit complet Caisse demandé par utilisateur "sinon catastrophe")
- **`PATCH /admin/products/{pid}`** : ajouté contrôle tenant — un superviseur ne peut plus modifier un produit d'une autre société.
- **`DELETE /admin/products/{pid}`** : idem (était totalement non protégé).
- **`PATCH /admin/users/{uid}/can-cash`** : ajouté contrôle tenant — un superviseur ne peut plus activer/désactiver `can_cash` sur un utilisateur d'une autre société.
- **`GET /cashier/overdue/relance-history`** : filtré par tenant (super-admin voit tout, legacy runs sans tag inclus).
- **`POST /cashier/overdue/relance-auto-run`** : tague le run avec le tenant_id du déclencheur ; `run_auto_relance(tenant_id=…)` restreint les business_clients ciblés à ce tenant lors d'un trigger manuel.

### ⚙️ Setting admin paramétrable — Mode du compteur "non lus" du briefing
- `models.py SettingsUpdate.welcome_unread_mode: Optional[str]` (valeurs `"bounded"` | `"lifetime"`, défaut bounded).
- Validation 400 si valeur invalide dans `PUT /admin/settings`.
- `me_welcome_briefing` lit le setting global et applique la borne temporelle uniquement si `bounded`. Mode `lifetime` revient au comportement avant Iter37f (cumul depuis le début).
- **UI Admin Settings** : nouvelle Section "Briefing de bienvenue — Mode du compteur 'Non lus'" avec radios "Bornée / Cumulative" + explication des 2 sémantiques.

### 📊 Tests cumulés : **112/112 pytest verts** (+7 nouveaux Iter37f)
- `test_iter37f_product_user_tenant_acl.py` : 4 tests (patch/delete product cross-tenant, can_cash cross-tenant)
- `test_iter37f_welcome_unread_bound.py` : +3 tests (mode lifetime cumul, bounded explicite, mode invalide rejeté)

### 🚨 Action utilisateur en production
1. **Save to GitHub** → **Redéployer** `sawalismartsystems.com`.
2. La sécurité tenant est désormais durcie sur ALL endpoints Caisse de modification.
3. Le mode "non lus" du briefing peut être basculé entre "Bornée" et "Cumulative" depuis Admin → Paramètres.

---

## Latest — Iter37f (suite) — 2 fixes prod (Caisse RBAC GET + Compteur WA non lus borné)

### 🐛 Fix #1 — Listes vides pour utilisateurs `role=client, can_cash=true` (cas rabo.f@)
- **Symptôme prod** : Le badge tenant affiche bien "7 utilisateurs · 5 clients en compte · 1 produit" pour l'admin, mais `rabo.f@` (rôle `client`) voit toujours des listes vides en Caisse.
- **Root cause** : `GET /api/admin/business-clients` et `GET /api/admin/products` exigeaient `get_current_supervisor`. Un utilisateur avec `role=client` + `can_cash=true` tombait en 403 **silencieux** que le frontend transforme en liste vide.
- **Fix `/app/backend/routes/cashier.py`** : Les **GET** sont désormais ouverts à tout utilisateur avec `can_cash=true` (ou admin/superviseur). Les POST/PATCH/DELETE restent strictement supervisor-only.
- **Tests `test_iter37f_cashier_read_access.py`** : **4/4 verts** — cashier lit business_clients/products, mais ne peut pas en créer ; non-cashier client toujours 403.

### 🐛 Fix #2 — Compteur "messages WhatsApp non lus" cumulé à vie sur l'écran de bienvenue
- **Symptôme prod** : "J'ai 1 seul message aujourd'hui mais il m'affiche toujours [un compteur plus grand]". Les anciens messages legacy avec `read_by_us_at=null` s'accumulent éternellement.
- **Root cause** `/app/backend/server.py` `me_welcome_briefing` : la requête `unread_wa` n'avait pas de borne temporelle (`{"direction": "inbound", "read_by_us_at": None}` lifetime).
- **Fix Iter37f** : Borne désormais la requête par `received_at >= last_seen_at` (envoyé par le frontend depuis `localStorage`) ou par fallback "**7 derniers jours**" si jamais visité. Identique pour SMS. Le badge `/me/whatsapp/unread` (sidebar) garde la sémantique lifetime pour les pastilles par contact (UX collante OK jusqu'à ouverture du fil).
- **Tests `test_iter37f_welcome_unread_bound.py`** : **3/3 verts** — fenêtre 7j sans last_seen, borne dynamique avec last_seen, last_seen futur → 0.

### 📊 Tests cumulés : **105/105 pytest verts**
- Iter36u→Iter37d : 75
- Iter37e tenant_isolation + cost_export : 13
- Iter37f contact_photo_acl + company_tenant + tenant_badge + cashier_read_access + welcome_unread_bound : 17

### 🚨 Action utilisateur en production
1. **Save to GitHub** → **Redéployer** `sawalismartsystems.com`.
2. Pour `rabo.f@` : la connexion suivante affichera immédiatement les clients en compte + catalogue partagés (le fix RBAC s'applique sans backfill supplémentaire).
3. Pour le compteur WA : la prochaine ouverture du briefing ne comptera plus que les messages des 7 derniers jours (ou depuis la dernière visite).

---

## Latest — Iter37f (2026-05-24) — Tenant résolu par `company` + Recalibrage admin + Badge tenant + Fix ACL photo contact

### 🏢 Iter37f.1 — Résolution du tenant Caisse par champ `company` (fix prod)
- **Problème prod** : `support@sawalismartsystems.com` et `rabo.f@sawalismartsystems.com` ne partageaient pas les mêmes clients en compte / catalogue, alors qu'ils appartiennent tous deux à "SAWALI SMART SYSTEMS". Root cause : aucun n'avait de `parent_client_id` → chacun devenait son propre tenant.
- **Backend `/app/backend/routes/cashier.py`** : `_resolve_client_lie(user)` enrichi avec un fallback Iter37f — quand `parent_client_id` et `client_id` sont vides, lookup d'un utilisateur **canonique** partageant la même `company` (priorité : `admin` > `superviseur` > plus ancien utilisateur actif). 2 utilisateurs partageant la même société deviennent automatiquement le **même tenant**.
- Helper `backfill_tenant_ids(db, rewrite=False)` étendu : nouvelle logique cache `company → canonical_user_id`. Le mode `rewrite=True` recompute tous les `tenant_id` existants (consolide les tenants éclatés par les anciennes versions du code).

### 🔧 Iter37f.2 — Endpoint admin de recalibrage + UI
- `POST /api/admin/cashier/backfill-tenants` (body `{"rewrite": true}`, admin-only) : déclenche le backfill avec la dernière logique de résolution. Retourne `{rows_updated, canonical_users_sample}`.
- **Frontend `/app/frontend/src/pages/admin/AdminSettings.jsx`** : nouveau composant `<CashierTenantBackfillSection />` (encadré fuchsia) — toggle "Mode REWRITE", bouton "Lancer le recalibrage", résultat détaillé par collection + détection des utilisateurs canoniques. À utiliser **après chaque redéploiement** ou quand 2 utilisateurs de la même société voient des listes différentes.
- **Validation prod** (préparée) : backfill exécuté en preview a consolidé **1794 documents** (829 business_clients, 266 invoices, 505 payment_methods, 171 products, 14 legal_forms, 9 product_categories) sous l'admin SAWALI canonique.

### 🐛 Iter37f.3 — Fix ACL : photo contact + WA-sync (bouton "Modification non autorisée")
- **Bug rapporté par l'utilisateur** : "Bien que Admin ou Superviseur je n'arrive pas à modifier la photo d'un contact. Le bouton est actif mais quand je clique → 'Modification non autorisée'."
- **Root cause** : 3 endpoints (`POST /me/contacts/{cid}/photo`, `DELETE` idem, `POST /me/contacts/{cid}/wa-sync`) checkaient `owner_id OR user.role == "admin"` — donc **superviseurs rejetés** et utilisateurs admins par tracked role ignorés. Contradiction avec `PUT /me/contacts/{cid}` qui utilise correctement `_resolve_visible_client_ids` + `admin|superviseur`.
- **Fix** : alignement des 3 endpoints sur la même ACL collaborative que `PUT /me/contacts/{cid}` :
  ```python
  client_ids = await _resolve_visible_client_ids(user)
  if existing.get("client_id") not in client_ids and user.get("role") not in ("admin", "superviseur"):
      raise HTTPException(status_code=403, detail="Modification non autorisée")
  ```

### ✅ Tests pytest : **96/96 verts**
- 75 régression Iter36u → Iter37d
- 7 Iter37e tenant_isolation
- 6 Iter37e cost_export
- **+4 Iter37f contact_photo_acl** (superviseur peut upload/delete photo + wa-sync, outsider toujours 403)
- **+4 Iter37f company_tenant** (utilisateurs partageant `company` partagent business_clients/receipts/products via Caisse, autre société isolée, endpoint admin recalibre les tenants existants, non-admin refusé)

### 🚨 Action requise en production après redéploiement
1. Cliquer sur **Save to GitHub** puis redéployer `sawalismartsystems.com`.
2. Se connecter en admin → **Paramètres** → section fuchsia "Recalibrage des tenants Caisse/Facturation".
3. Cocher **Mode REWRITE** → bouton "Lancer le recalibrage".
4. Vérifier que `support@…` et `rabo.f@…` voient désormais les mêmes données Caisse.

---

## Latest — Iter37e (2026-05-24) — Caisse multi-tenant + Export PDF/CSV coût interventions

### 🔐 Iter37e.1 — Multi-tenant Caisse/Facturation
- **Backend `/app/backend/routes/cashier.py`** :
  - Nouveaux helpers `_is_super_admin(user)`, `_tenant_id_of(user)`, `_scoped_filter(user)`, `_ensure_tenant_access(user, doc)`.
  - Définition tenant : `user.parent_client_id || user.client_id || user.id` (alignée sur `_resolve_client_lie`).
  - Super-admin (`admin@sawalismartsystems.com`) bypasse le filtre → voit toutes les données tenants.
  - Champ `tenant_id` ajouté aux NEW docs : `business_clients`, `products`, `receipts`, `invoices`, `legal_forms`, `product_categories`, `payment_methods`.
  - Filtrage tenant appliqué sur : list/get/patch/delete business_clients, receipts (list+get+qr+send-wa), invoices (list+get+qr+send-wa+patch+receipt), KPIs, overdue/count, overdue/relance, exports CSV/PDF, legal-forms, product-categories, payment-methods, users/can-cash, CSV imports.
  - Dedup `business_clients`/`legal_forms`/`product_categories` désormais **per-tenant** (deux tenants peuvent porter la même "SARL").
  - **Backfill au démarrage** (`backfill_tenant_ids` au module-level, appelé depuis `on_startup` server.py) : a tagué 1376 docs legacy (646 clients, 217 factures, 403 modes paiement, 98 produits, 6 formes juridiques, 6 catégories).
  - `_resolve_payment_method(pm_id, user=)` strictement scoped au tenant lors d'un règlement de facture.

### 💼 Iter37e.2 — Export PDF + CSV du coût mensuel des interventions
- **Backend `/app/backend/server.py`** :
  - Helper `_tickets_cost_summary_data(user, months_back)` factorisé depuis l'endpoint JSON existant.
  - `GET /api/me/tickets/cost-summary.csv` : UTF-8 BOM, `;` séparateur, en-tête + totaux + breakdown par Client Lié + ligne TOTAL. Filename `cout-interventions-YYYY-MM.csv`.
  - `GET /api/me/tickets/cost-summary.pdf` : ReportLab A4 paysage, header SAWALI bleu, footer total ambre, colonnes alignées. Filename `cout-interventions-YYYY-MM.pdf`.
  - RBAC : 403 pour les regular clients (réutilise `_is_elevated_creator`).
- **Frontend `/app/frontend/src/pages/portal/Tickets.jsx`** :
  - Nouvelle fonction `downloadCostExport(fmt)` (axios `responseType=blob`, parse `Content-Disposition`, déclenche le téléchargement, toast success).
  - 2 boutons (`tickets-cost-export-csv`, `tickets-cost-export-pdf`) dans le panel indigo "Coût des interventions" à côté du selector de mois.
  - Boutons visibles uniquement quand `costSummary` est chargé (admin/sup), donc cachés pour regular clients.

### ✅ Tests pytest : **88/88 verts**
- 75 régression Iter36u→Iter37d (avec patch fixture `cashier_user`/`regular_user` désormais liés au tenant admin).
- **+7 Iter37e tenant_isolation** : business_clients shared parent↔employee, isolation cross-tenant (list+patch), receipts shared+isolated, KPIs scoped par tenant, dropdowns isolés par tenant (formes juridiques).
- **+6 Iter37e cost_export** : CSV UTF-8 BOM + structure, PDF magic bytes + size, months_back différencie filename, RBAC 403 sur les 2 formats, contenu agrégé visible.

### 🧪 Testing agent v3 : success_rate 100% backend (13/13), 100% frontend, **0 bug détecté**.

---

## Latest — Iter37d (2026-05-23) — Toggle Caissier UI + Agrégat mensuel coût interventions

### 💰 Iter37d — Visibilité du rôle Caissier + Cockpit coût mensuel
- **Backend** :
  - `UserUpdateAdmin` enrichi du flag `can_cash: Optional[bool]` → modifiable via `PUT /api/admin/clients/{uid}`.
  - Nouvel endpoint `GET /api/me/tickets/cost-summary?months_back=N` (admin/sup/mod uniquement). Retourne `{month, period_start, period_end, currency, grand_total, grand_hours, grand_count, by_client:[{client_id, client_name, total_cost, total_hours, count}]}` agrégé via `db.support_tickets.aggregate`.
- **Frontend `AdminClients.jsx`** :
  - Nouveau bloc fuchsia « 💰 Rôle Caissier » dans le formulaire utilisateur : case à cocher `can_cash` (avec helper text).
  - Badge « 💰 Caissier » affiché dans la cellule rôle de la liste utilisateurs.
- **Frontend `Tickets.jsx`** :
  - Panel gradient indigo « Coût des interventions · MM-YYYY » au-dessus de la liste : montant total + nb tickets + heures + breakdown top-6 clients. Selector mois (0/1/2/3/6/12 mois en arrière).
  - Panel auto-masqué pour les regular clients (endpoint renvoie 403 → `costSummary` reste null).
- **Tests pytest** : **75/75 verts** (69 régression + **6 Iter37d** : `can_cash` via PUT, auth/me reflète le flag, RBAC cost-summary, schema, agrégation closed tickets, months_back).

---

## Latest — Iter37c (2026-05-23) — Tickets : Numérotation {CLIENT_SLUG}-YYYY-NNNN + Coût intervention

### 🎟️ Iter37c — Numérotation chronologique par Client Lié + cost-on-close
- **Backend `server.py`** :
  - `_next_ticket_number(client_id)` étendu : préfixe lu depuis `db.users.company || full_name` (slug majuscules, espaces réduits, max 20 cars). Fallback `TKT` si vide. Compteur atomique inchangé `db.counters[_id=tickets_{client_id}_{YYYY}]`.
  - Sur clôture du ticket : calcul automatique du **coût d'intervention** (`active_hours`, `cost_amount`, `cost_mode`, `cost_hourly_rate`, `cost_flat_rate`, `cost_currency=XOF`). Le `flat_rate` (si > 0) est prioritaire sur le calcul horaire. `active_hours = (closed_at - opened_at - suspended_total) / 3600`.
  - Filtrage RBAC sur `GET /api/me/tickets` : nouveau helper `_strip_ticket_cost_fields()` applique l'opacification des champs `cost_*` + `active_hours` pour tout utilisateur non-élevé (regular client). Admin/Superviseur/Modérateur voient tout.
- **Modèle `UserUpdateAdmin`** : 2 nouveaux champs `hourly_rate: Optional[float]` + `flat_rate: Optional[float]`.
- **Frontend** :
  - `AdminClients.jsx` : nouveau bloc « 🎟️ Tarification des interventions (tickets) » avec 2 inputs (Taux horaire / Forfait) — `data-testid="ticket-pricing-section"`.
  - `Tickets.jsx` : nouvelle ligne « 💰 Coût » dans le détail du ticket, affichée uniquement si `t.cost_amount != null` (donc seulement pour les viewers élevés grâce au filtrage backend). Affiche `XX XXX XOF (forfait)` ou `XX XXX XOF (Nh × tarif)`.
  - Hint « Numérotation automatique `{CLIENT}-YYYY-NNNN` par Client Lié ».
- **Tests pytest** : **69/69 verts** (62 régression + **7 Iter37c** : format avec slug client, séquentialité, cost horaire = h*rate, cost forfait prioritaire, admin voit cost, client régulier ne voit pas cost, rates persistés via PUT /admin/clients).

---

## Latest — Iter37b (2026-05-23) — CHUNK 2 (Import CSV + Entête Client Lié sur pièces)

### 📤 Iter37b — Import CSV + Tenant snapshot sur pièces
- **Backend** (`/app/backend/routes/cashier.py`) :
  - 2 endpoints documentation : `GET /api/cashier/import/business-clients/fields` + `GET /api/cashier/import/products/fields` (renvoient `order`, `delimiter`, `sample`, `note`).
  - 2 endpoints d'import : `POST /api/cashier/import/business-clients` + `POST /api/cashier/import/products` (admin/superviseur).
  - Format CSV : UTF-8 (BOM accepté), séparateur `;` (auto-détection `,` ou `\t` aussi), première ligne optionnelle = header (ignorée si commence par `name`).
  - Ordres : `name;legal_form;nif;ifu;rccm;phone;whatsapp;email;billing_address;shipping_address;notes` (business) et `name;category;unit;unit_price_ht;tva_pct;stock;description;active` (products — SKU **non inclus**, auto-généré).
  - Produits : nom mis en MAJUSCULES auto, SKU généré `{TENANT_SLUG}-{N:08d}` via le compteur atomique existant.
  - Doublons business_clients (par `name`) → skipped (compteur dédié).
  - Réponse type : `{created, skipped_duplicates, errors:[{line, error}], total_lines}`.
  - **Entête tenant** : `tenant_snapshot` (id, name, logo_url, billing_address, phone, email) résolu via `_resolve_client_lie(user)` (lit `parent_client_id || client_id || self`) et **snapshoté** dans chaque reçu ET facture/proforma à la création.
- **Frontend** (`CashBilling.jsx`, `ReceiptPrint.jsx`, `InvoicePrint.jsx`) :
  - Nouveau composant `<CsvImportButton resourceKind={…}/>` : bouton « 📂 Importer CSV » avec **tooltip au survol** affichant l'ordre des colonnes (sample copy-paste-ready) + modal de sélection de fichier + toast détaillé (créés/doublons/erreurs).
  - `CrudTab` étendu : nouveau prop `extraHeaderButton` (function ou ReactNode) reçoit `{onRefresh}` pour rafraîchir la liste après import.
  - Boutons import branchés sur les onglets « Clients en compte » et « Catalogue produits/services ».
  - `ReceiptPrint.jsx` + `InvoicePrint.jsx` : entête utilise désormais `tenant_snapshot.logo_url`, `tenant_snapshot.name`, `tenant_snapshot.billing_address`, `tenant_snapshot.phone` (fallback aux constantes SAWALI si snapshot vide).
- **Tests pytest** : **62/62 verts** (53 régression Iter36u→Iter37a + **9 nouveaux Iter37b** : fields endpoints, import BOM/headers, duplicate skip, missing name, empty rejected, products auto-SKU+UPPERCASE, tenant_snapshot présent sur receipts+invoices).

---

## Latest — Iter37a (2026-05-23) — Quick wins Caisse (bug RBAC + dropdowns + SKU multi-tenant + WA fallback)

### 🔴 Iter37a — CHUNK 1 du plan correctif (Points 1, 2, 3, 4, 6, 9, 12)
- **#9 BUG RBAC** : nouveaux endpoints dédiés `GET/PUT /api/cashier/auto-relance/settings` accessibles à **admin ET superviseur** (le PUT /admin/settings strict reste pour SMTP/secrets). Le frontend AutoRelanceTab utilise désormais ces endpoints.
- **#2 Sidebar** : un seul lien « Caisse/Facturation » → `/portal/cash` (Facturation + Catalogue retirés du sidebar, routes conservées en interne).
- **#3 Refresh button** : bouton « 🔄 Actualiser » dans le formulaire Reçu ET Facture pour rafraîchir la liste des Clients en compte sans recharger la page.
- **#4 WhatsApp dédié** : nouveau champ `whatsapp` sur fiche Client en compte (en plus de `phone`). L'envoi WA (reçu, facture, relance) utilise désormais `whatsapp || phone` en priorité (snapshot puis live).
- **#6 Dropdowns admin-managed** :
  - 2 nouveaux endpoints CRUD : `GET /api/cashier/legal-forms` + `POST/DELETE /api/admin/legal-forms` (et idem `product-categories`).
  - 2 nouveaux onglets dans `/portal/cash` (admin) : « Formes juridiques » + « Catégories produits ».
  - Formulaire Client en compte → `legal_form` via dropdown remote. Formulaire Produit → `category` via dropdown remote.
- **#1 SKU multi-tenant auto** : SKU produit désormais auto-généré server-side sous forme `{TENANT_SLUG}-{N:08d}` (séquence atomique `db.product_sku_counters` par Client Lié = `user.client_id || user.id`). SKU **immutable** (le PATCH conserve toujours la valeur d'origine). Le nom du produit est automatiquement **mis en MAJUSCULES** (création + édition).
- **#12 Caissier** : flag `can_cash` reste accessible via `/admin/users/{uid}/can-cash` (déjà piloté depuis Admin → Utilisateurs). Pas de rôle dédié pour ne pas casser l'existant.
- Extension `CrudTab` : nouveau type de champ `remoteSelect` (auto-fetch des options depuis une URL) + `readonly` (champ griséparé non éditable) + `uppercase: true` (force MAJUSCULES en saisie).
- **Tests pytest** : **53/53 verts** (Iter36u→z + **9 nouveaux Iter37a** : RBAC auto-relance sup OK, dropdowns CRUD, WhatsApp fallback prefer whatsapp/fallback phone, SKU auto+immutable, nom UPPERCASE).

---

## Latest — Iter36z (2026-05-23) — Mini KPI panel Facturation (cashflow cockpit)

### 📊 Iter36z — Dashboard de trésorerie en haut de l'onglet Facturation
- **Backend** : nouvel endpoint `GET /api/cashier/kpis` (RBAC : `_can_invoice`).
  - **Encaissé ce mois** : somme `net_to_pay` des factures `status=paid` avec `paid_at >= 1er du mois` + count.
  - **Restant à encaisser** : somme `net_to_pay` des factures `status=issued` + count.
  - **Délai moyen de paiement (jours)** : moyenne `(paid_at - created_at) / 86400` sur les factures payées des 90 derniers jours (+ `delai_moyen_sample_size`).
  - **Top 3 mauvais payeurs** : agrégat `db.invoices.aggregate` par `business_client_id` (group sum `unpaid_amount`, count, name snapshot, earliest_due) trié desc, limit 3. Champ `oldest_overdue_days` calculé depuis `due_date`.
- **Frontend `CashBilling.jsx`** : nouveau composant `<InvoiceKpiPanel />` monté en haut de `InvoicesTab` (grid 4 cards responsive 1/2/4 cols) :
  - Card emerald « Encaissé · MM YYYY » avec `TrendingUp` + montant + count
  - Card amber « Restant à encaisser » avec `AlertOctagon`
  - Card sky « Délai moyen » avec `Clock` + jours + sample size
  - Card rose « Top 3 mauvais payeurs » avec ordered list (nom, jours de retard, montant)
  - États : loading skeleton, empty state (« Aucun impayé 🎉 ») géré.
- **Tests pytest** : **43/43 verts** (37 régression + **6 Iter36z** : RBAC, schema shape, paid this month, outstanding, top bad payers, avg delay nullable).

---

## Latest — Iter36y (2026-05-23) — Relance auto quotidienne + toggle par client + rapport email

### 🤖 Iter36y — Cron de recouvrement automatique
- **Backend**
  - `BusinessClientPayload` enrichi du champ `auto_relance_enabled` (par défaut `False`). Toggle par client en compte.
  - 4 nouveaux settings dans `SettingsUpdate` : `auto_relance_enabled` (master), `auto_relance_day_of_week` (0=Lundi..6=Dimanche), `auto_relance_grace_days` (défaut 30), `auto_relance_email_report_to`.
  - Fonction `run_auto_relance(triggered_by)` exposée par `make_router()` (signature retournant `(router, run_auto_relance)`). Logique :
    - Trigger manuel → bypass master + bypass weekday check.
    - Trigger cron → master ON requis ET aujourd'hui doit correspondre au day_of_week configuré.
    - Cible uniquement `business_clients` avec `auto_relance_enabled=True`.
    - Persistance par exécution dans `db.auto_relance_runs` (sans le `results[]` complet pour la taille).
    - Rapport HTML (table OK/KO) envoyé via `send_email` au destinataire configuré (best-effort).
  - `POST /api/cashier/overdue/relance-auto-run` (admin/superviseur) — trigger manuel + rapport.
  - `GET /api/cashier/overdue/relance-history?limit=20` (admin/superviseur).
  - **APScheduler** : nouveau job `cashier_auto_relance_daily` (CronTrigger hour=9 minute=0 Africa/Abidjan). Le job appelle `run_auto_relance(triggered_by="cron:daily-09")` qui vérifie le day_of_week en interne.
- **Frontend `CashBilling.jsx`** — nouvel onglet « Relance auto » (admin/superviseur uniquement) :
  - Master toggle + sélecteur jour de la semaine + grace_days + email destinataire + bouton « Enregistrer » + bouton « 🔔 Tester maintenant ».
  - Tableau historique des exécutions (date, déclencheur, # clients, # factures, ✓ OK / ✗ KO / ⊝ sans n°, statut email).
  - Onglet « Clients en compte » : nouvelle case à cocher full-width « 🔔 Relance automatique des impayés » dans le formulaire.
- **Tests pytest** : **37/37 verts** (11 Iter36u + 7 Iter36v + 7 Iter36w + 6 Iter36x + **6 Iter36y** : toggle persisté, default OFF, RBAC manuel, opt-in ciblé/opt-out exclu, history, cron skip logic).
- **Testing agent v3** : success_rate backend 100%, frontend 100%, aucun bug.

---

## Latest — Iter36x (2026-05-23) — Relance bulk des factures impayées

### 🔔 Iter36x — Recouvrement automatique des impayés
- **Backend** : 2 nouveaux endpoints
  - `GET /api/cashier/overdue/count?grace_days=30` → `{count, grace_days}`
  - `POST /api/cashier/overdue/relance` body `{grace_days?, dry_run?, ids?}` → `{total, sent_ok, sent_ko, skipped_no_phone, results: [...]}` ; persiste `last_reminder_at`, `last_reminder_message_id`, `last_reminder_to`, `reminders_count` sur chaque facture relancée avec succès.
- Critère « impayée » (cumulatif OR) : `kind=invoice` ET `status=issued` ET (`due_date` < aujourd'hui  OR  `due_date` manquant ET `created_at` > `grace_days` jours).
- Message rappel : ton poli, échéance rappelée, lien QR de vérification, signature SAWALI. Utilise `_wa_send_text` (fenêtre 24h Meta).
- **Frontend `CashBilling.jsx`** :
  - Bouton ambre pulsant « 🔔 Relancer N impayée(s) » dans l'en-tête Facturation (visible uniquement si count > 0), placé à côté des filtres avant les exports CSV/PDF.
  - Confirm modal → toast détaillé (envoyée(s)/échec(s)/sans n°) → refresh de la table + du compteur.
  - Badge ambre `🔔 N` à côté du badge WhatsApp dans la ligne facture (avec date du dernier rappel en tooltip).
- Paths choisis (`/cashier/overdue/...`) pour éviter collision avec `/cashier/invoices/{iid}`.
- **Tests pytest** : **31/31 verts** (11 Iter36u + 7 Iter36v + 7 Iter36w + **6 Iter36x** : RBAC, count overdue/fresh, dry-run sans persistance, persistance après envoi réussi, exclusion facture fraîche, skipped_no_phone).

---

## Latest — Iter36w (2026-05-23) — Indicateur WA + Export CSV/PDF de la Caisse

### 📊 Iter36w — Cockpit de suivi des reçus & factures
- **Frontend `CashBilling.jsx`** : nouvelle colonne « WhatsApp » dans les tables Caisse et Facturation. Si `whatsapp_sent_at` est posé, badge emerald `✓ DD/MM HH:MM` (avec tooltip sur le numéro). Sinon `—` slate.
- **Frontend** : nouveaux boutons « CSV » et « PDF » dans l'en-tête de chaque onglet. Téléchargement via axios authentifié (blob), filename récupéré depuis `Content-Disposition`, fallback nom local en cas d'erreur. Toast d'erreur si l'API refuse.
- **Backend** : 4 nouveaux endpoints (chemin distinct pour éviter la collision avec `{rid}`/`{iid}`) :
  - `GET /api/cashier/exports/receipts.csv` (UTF-8 BOM, séparateur `;`, prêt pour Excel FR)
  - `GET /api/cashier/exports/receipts.pdf` (ReportLab A4 paysage, total encaissé + nb actifs)
  - `GET /api/cashier/exports/invoices.csv` (paramètres `kind`/`status` filtrables, montants HT/TVA/TTC/Net)
  - `GET /api/cashier/exports/invoices.pdf` (totaux encaissé vs en attente)
- Permissions : même gating que la liste (`_can_invoice`), refus 401/403 sinon. Filtre `business_client_id` côté URL.
- **Tests pytest** : **25/25 verts** (11 Iter36u + 7 Iter36v + **7 Iter36w** : RBAC, BOM, headers CSV, magic bytes PDF, filtre kind).

---

## Latest — Iter36v (2026-05-23) — Reçu/Facture WhatsApp en 1 clic

### 📲 Iter36v — Envoi direct du document via Meta Cloud API
- **Backend** : 2 nouveaux endpoints dans `routes/cashier.py` :
  - `POST /api/cashier/receipts/{rid}/send-whatsapp`
  - `POST /api/cashier/invoices/{iid}/send-whatsapp`
- Le destinataire est résolu dans cet ordre : `payload.phone` (override) → `business_client_snapshot.phone` → `business_clients.phone` (live). 400 si aucun numéro.
- Le message WhatsApp est pré-formaté (numéro doc + montant + montant en lettres + mode/statut + URL QR de vérification).
- Utilise le helper `_wa_send_text` (free-form, soumis à la fenêtre 24h Meta). Si WA non configuré OU hors fenêtre 24h, l'endpoint répond **HTTP 200** avec `{ok:false, fallback_wa_link:"https://wa.me/<num>?text=..."}` que le frontend ouvre automatiquement en secours.
- Persistance : `whatsapp_sent_at`, `whatsapp_message_id`, `whatsapp_to`, `whatsapp_sent_by` posés sur le doc Mongo après envoi réussi.
- Snapshot reçu enrichi de `phone` + `email` (consistance avec invoice).
- **Frontend** : `ReceiptPrint.jsx` et `InvoicePrint.jsx` appellent les nouveaux endpoints au clic sur "Envoyer par WhatsApp", avec spinner, toast success/warning/error, et fallback `wa.me` automatique en cas d'échec backend.
- **Tests pytest** : **18/18 verts** (11 existants Iter36u + **7 nouveaux Iter36v** : RBAC, succès/échec gracieux, no_phone→400, 404, phone override).

---

## Latest — Iter36u (2026-05-23) — Caisse & Facturation MVP complet (E2E vert)

### 💵 Iter36u — Module Caisse & Facturation
- **Backend** `routes/cashier.py` (~674 lignes) déjà wired à `server.py`. Endpoints `/api/cashier/*` :
  - `GET/POST /receipts` (numérotation `R-YYYY-NNNN`, `amount_in_words` FR via num2words, snapshot client, payment_method snapshot).
  - `GET /receipts/{id}/qr.png` (QR code PNG via lib `qrcode`).
  - `GET/POST/PATCH /invoices` (proforma + facture, lignes + sous-totaux HT/TVA/TTC, conversion proforma→facture, paid→auto-receipt, cancel admin only, numérotation `FAC-YYYY-NNNN` / `PRO-YYYY-NNNN`).
  - `GET /invoices/{id}/qr.png`.
  - CRUD `/admin/business-clients`, `/admin/products` (SKU unique), `/admin/payment-methods`, `/payment-methods` (lecture tout auth).
  - `PATCH /admin/users/{uid}/can-cash` (admin/superviseur) flag bascule.
- **Modèle utilisateur** : champ `can_cash:bool` ajouté à `UserPublic` et `_to_user_public()`. `/api/auth/me` retourne désormais cette info pour le gating côté frontend.
- **Frontend** : routes branchées dans `App.js` :
  - `/portal/cash` → `<CashBilling defaultTab="receipts" />`
  - `/portal/cash/receipt/:id` → `<ReceiptPrint />`
  - `/portal/billing` → `<CashBilling defaultTab="invoices" />`
  - `/portal/billing/invoice/:id` → `<InvoicePrint />`
  - `/portal/catalog` → `<CashBilling defaultTab="catalog" />`
- **Sidebar PortalLayout** : flags `cashOnly` (Caisse, Facturation — visibles si `can_cash || admin || superviseur`) et `cashAdminOnly` (Catalogue — admin/superviseur uniquement). Plus de stubs "Bientôt".
- **CashBilling.jsx** (749 lignes) : 5 onglets (Caisse, Facturation, Catalogue, Clients en compte, Modes de paiement) avec garde-fou amber si pas autorisé. ReceiptPrint + InvoicePrint avec QR code, watermark SAWALI, actions WhatsApp + Print.
- **Tests pytest** : **11/11 verts** (`test_iter36u_cashier.py`), incluant RBAC (regular user 403, can_cash=true → 200), cycle de vie facture, SKU unicité, payment-methods CRUD.
- **E2E testing_agent_v3_fork** : success_rate backend 100%, frontend 100%, **aucun bug détecté**.

---

## Latest — Iter36n (2026-05-21) — Partage de photos dans le chat interne

### 📷 Iter36n — Photos depuis caméra mobile ou galerie/disque (MVP)
- **Backend** `POST /api/me/chat/{client_id}/messages/photo` (multipart) : JPEG/PNG/WebP/HEIC, max 10 Mo, stockage Emergent Object Storage sous `chat/{client_id}/{msg_id}.<ext>`. Le message créé porte `media_url`, `media_mime`, `media_size`, `media_kind=image`, `storage_path`, et un `text` optionnel (caption).
- **Backend** `GET /api/me/chat/media/{msg_id}` : retourne les bytes après revalidation stricte de l'appartenance (membre du client + admin override) ; refus 403 pour outsiders et tiers d'un DM.
- **Frontend** : 2 boutons dans le composer du chat — 📷 caméra (mobile only, `capture="environment"`) et 🖼️ galerie/disque (toutes plateformes). Compression côté client (canvas → JPEG 82%, max 1920px) avant upload, divisant le poids ×5-10. Progress bar pendant l'upload via `onUploadProgress`.
- **Frontend lightbox** : clic sur une vignette → overlay plein-écran cliquable pour fermer. `ChatMediaThumb` charge les bytes via axios authentifié et les expose en `URL.createObjectURL` (puis révoqué à l'unmount).
- **Conformité spec mobile-first** : la caméra s'ouvre nativement en un clic ; la galerie marche partout.
- Tests pytest : **11 verts** (upload general + DM, validation MIME/taille, sécurité fetch / outsider / tiers DM, 404).

---

## Latest — Iter36m (2026-05-21) — Compteur chat non-lu dans Welcome Briefing

### 🔔 Iter36m — Messages chat non lus depuis la dernière visite
- **Backend** : `GET /me/welcome-briefing` enrichi avec `since_last_visit.new_chat_messages_count` — compte les messages `internal_chat_messages` créés après `last_seen_at`, adressés au user (DM) ou au fil collectif (recipient_id=None, sender != user), et NON encore lus (user_id ∉ read_by).
- Le `total_count` agrège désormais tickets + WA + notes + **chat**.
- **Frontend** : nouveau badge violet "X message(s) de chat non lu(s)" dans la section "Depuis votre dernière visite" de la modale `WelcomeBriefing`. Cliquer le badge déclenche l'ouverture du panneau de chat (`internal-chat-fab`).
- Tests pytest : **5 nouveaux verts** (DM, fil général, déjà lus exclus, antérieurs à last_seen exclus, propres messages exclus).

---

## Latest — Iter36l (2026-05-21) — Badge présence publique + Transcription Whisper

### 🌐 Iter36l.1 — Badge "Équipe en ligne X/Y" (preuve sociale publique)
- **Endpoint public** `GET /api/public/team-presence` → `{online: N, total: M, ts}`. Aucune PII exposée (pas d'emails, noms ou IDs).
- **Définition** : `total` = comptes SAWALI staff actifs (admin/superviseur/moderateur), `online` = sous-ensemble actuellement connecté au WebSocket `/api/ws/chat`.
- **Composant** `TeamPresenceBadge.jsx` (tons light/dark, mode compact) avec dot pulsant vert + libellé "Équipe en ligne 2/3". Fallback "Équipe joignable 24/7" quand personne en ligne.
- **Intégration** : MarketingNav (nav supérieure, mode dark compact), Hero homepage, page Contact, Footer.
- Polling 30 s — overhead négligeable, pas d'auth nécessaire.

### 🎙️ Iter36l.2 — Transcription notes vocales chat (OpenAI Whisper)
- **Endpoint** `POST /api/me/chat/transcribe` (multipart/form-data, `audio` + `language=fr`). Limite 25 Mo, formats webm/wav/mp3/m4a/ogg/mp4.
- **Intégration Whisper-1** via `emergentintegrations.llm.openai.OpenAISpeechToText` (Emergent LLM Key).
- **Workflow UI** : bouton micro à gauche du composer du chat interne → enregistrement MediaRecorder (max 60 s, auto-stop) → upload → transcription FR → texte injecté dans le textarea → utilisateur édite/valide → envoi par le bouton Send normal.
- **États visuels** : indicateur rouge pulsant pendant l'enregistrement (avec chronomètre `00:42 / 01:00`), indicateur sky avec spinner pendant la transcription, restauration `idle` à la fin.
- **Conformité spec "chat texte seul"** : l'audio n'est jamais persisté, seul le texte transcrit devient un message.

### Tests pytest : **20 nouveaux verts** (3 presence WebSocket E2E + 4 transcribe validation + 13 chat existants).

---

## Latest — Iter36k (2026-05-21) — Bug Fix Ticket Dropdown + Chat Interne Temps Réel

### 🐛 Iter36k.1 — Bug fix : Ticket WhatsApp héritait du mauvais client lié
- **Avant** : `POST /me/contacts/{cid}/ticket` calculait `client_id = contact.client_id or user.client_id or user.id` → tous les tickets étaient attribués au même client (généralement l'ID du contact, souvent erroné).
- **Fix backend** : `TicketOpenPayload` gagne un champ `client_id` (str, **obligatoire**). Si absent → 400. Si non autorisé pour l'utilisateur → 403. Le ticket utilise désormais EXCLUSIVEMENT le `client_id` choisi via le dropdown.
- **Fix frontend** : la fenêtre WhatsApp ouvre une vraie modale (au lieu de `window.prompt`) avec :
  - dropdown obligatoire des clients liés (via `GET /me/clients`)
  - sélecteur de modèle de motif (existant)
  - textarea motif libre (200 chars max)
- Tests pytest : **18 verts** (13 existants régressifs adaptés + 5 nouveaux Iter36k validant la nouvelle logique).

### 💬 Iter36k.2 — Chat interne temps réel (WebSocket)
- **Activable par client** via toggle `features.internal_chat` (admin → `/admin/clients/{id}/features`).
- Hérité par tous les utilisateurs suivis du client + admins.
- **Modes** : fil collectif `#général` par client + conversations 1-à-1 entre membres.
- **Transport** : WebSocket `/api/ws/chat?token=<jwt>` (auth par JWT en query param) + REST fallback complet.
- **Backend** : module `/app/backend/routes/internal_chat.py` (~440 lignes) avec `ConnectionManager` in-memory, broadcast aux participants concernés (DM = 2 users, général = tous les membres), endpoints `/me/chat/clients`, `/me/chat/{cid}/threads`, `/me/chat/{cid}/messages`, `/me/chat/{cid}/members`, `/me/chat/messages/{id}/read`, `/me/chat/unread-count`.
- **Frontend** : composant `InternalChatPanel.jsx` (drawer flottant bas-droite avec FAB + badge non-lus), hook `useInternalChat.js` (WS auto-reconnect exp backoff, ping 30s), monté globalement dans `PortalLayout`. Notifications **son + toast** quand message reçu dans un autre fil.
- **Sécurité** : `_ensure_member()` valide que l'utilisateur fait partie du client cible, refus 403 sinon.
- Tests pytest : **13 verts** (10 REST + 3 WebSocket end-to-end via wss:// preview).

### ✅ Iter36i — Endpoint `/health` Kubernetes (déjà en place)
- `@app.get("/health")` + `/healthz` répondent `200 {status: ok, service: sawali-backend}`. Débloque les déploiements K8s.

### ✅ Iter36k.3 — Webhook WhatsApp Production résolu
- L'utilisateur a corrigé la **Callback URL** dans Meta Developer Dashboard (mauvaise URL Production). Messages de nouveau reçus.

---

## Latest — Iter36j (2026-05-19) — Levée du verrouillage 1h pour rôles élevés

### 🔓 Iter36j — Verrouillage 1h après descente : bypass pour admin/superviseur/modérateur
- **Avant** : `_check_descent_window()` levait HTTP 403 sur toute création de rapport/suivi/note/intervention au-delà de `descent_time + 1h`, sans exception.
- **Fix** : ajout du paramètre `user` au helper. Si `_is_elevated_creator(user)` retourne `True` (admin / superviseur top-level OU tracked `Moderation`/`Administrateur`/`Superviseur`), le contrôle est immédiatement bypassé.
- Les 3 call sites mis à jour : `POST /admin/interventions`, `POST /me/notes/{kind}`, `POST /me/interventions`.
- Les agents standards (tracked sans rôle élevé) restent verrouillés → comportement souhaité conservé.
- Tests pytest : 6/6 verts (admin/superviseur/Moderation/Administrateur bypass, agent toujours verrouillé, descent_time vide = pas de lock).

---

## Latest — Iter36h (2026-05-19) — Bouton "Importer" : unicité phone OU whatsapp

### 🐛 Iter36h — Bug fix unicité du bouton "Importer" sur "Top expéditeurs"
- **Avant** : le matching ne se faisait que sur le champ legacy `phone_digits` (rarement renseigné dans les vrais contacts). Résultat : un contact existant avec phone `+226 70 11 11 11` (formaté avec espaces et `+`) n'était PAS reconnu → le bouton "Importer" apparaissait à tort, créant un doublon.
- **Fix backend** : nouvelle logique côté Python (négligeable sur ~200 contacts) qui pré-charge tous les contacts du scope et indexe leurs `phone`, `whatsapp`, `phone_digits`, `whatsapp_digits` après normalisation (digits-only + suffixe 8 chiffres). Matching robuste à toutes les variantes de formatage (`+226 70...`, `0022670...`, `70 11 11 11`, etc.).
- **Idempotence import endpoint** : même algorithme pour `POST /me/wa-import-by-phone` → garantit qu'aucun doublon n'est créé même si l'admin clique 2 fois.
- Tests pytest : 11/11 verts (5 variantes de format phone + whatsapp + uniqueness import).
- Validation visuelle ✓ : "Ami(e) connu(e)" → ✓ Répertoire, "Inconnu CIV" → bouton Importer (comme attendu).

---

## Latest — Iter36g (2026-05-19) — "Depuis votre dernière visite"

### ✨ Iter36g — Mini-section "Depuis votre dernière visite" dans WelcomeBriefing
- Endpoint `/me/welcome-briefing` enrichi : accepte `?last_seen_at=ISO8601`, retourne un nouveau bloc `since_last_visit` avec `new_tickets` (liste détaillée), `new_whatsapp_count`, `new_notes`, `total_count`. Expose aussi `server_now` pour que le frontend rafraîchisse son stamp.
- Frontend : stockage `localStorage["sawali_portal_last_seen_at"]`, envoyé en query param, rafraîchi **uniquement** quand l'utilisateur clique "J'ai lu" (garantit qu'il a vu le briefing).
- UI : nouvelle section ambre dans la modale avec 3 badges cliquables (rose tickets, emerald WhatsApp, sky notes) + détail des 5 premiers nouveaux tickets inline.
- Tests pytest : 2/2 verts (diff correct entre old/new, retour `None` si pas de last_seen_at).

---

## Latest — Iter36f (2026-05-19) — Bouton "Rediffuser KO" sur Note de Service

### ✨ Iter36f — Rediffusion ciblée aux destinataires en échec
- Endpoint `POST /admin/note-service/{note_id}/retry-failed` : récupère pour la note les destinataires dont la dernière tentative est `failed`, retente uniquement ceux-là, marque les nouvelles lignes `whatsapp_messages` avec `is_retry=True`.
- Idempotent : les destinataires déjà OK ne sont JAMAIS retentés (pas de doublon de notification).
- UI : bouton jaune ambre "📢 Rediffuser N KO" dans le panneau expandable de chaque ligne, visible uniquement si `failed_count > 0`. Disabled pendant l'envoi avec spinner.
- Tests pytest : 3/3 verts (retente uniquement les KO + idempotency Alice/Bob/Carlos, "rien à retenter" si tout OK, 404 sur note inexistante).

---

## Latest — Iter36e (2026-05-19) — Panneau historique Note de Service

### ✨ Iter36e — Admin panel "Note de Service" (historique + template)
- Endpoint `GET /admin/note-service/history?limit=20` agrège `whatsapp_messages` par `source_note_id` : pour chaque note diffusée → `note_numero`, `note_title`, `template_name`, `last_sent_at`, `sent_count`, `failed_count`, liste détaillée des destinataires (avec status, error, phone).
- UI : section dédiée dans AdminSettings avec champ template name + langue (par défaut `notedeservice_fr` / `fr`), bloc explicatif des 3 paramètres du template, liste expandable des 20 dernières diffusions colorées selon le ratio OK/KO (emerald/amber/rose), détail destinataires inline avec messages d'erreur Meta.
- Test pytest : 1/1 vert (groupement par note + ordre tri par `last_sent_at` desc + recipients exposés correctement).

---

## Latest — Iter36a/b/c/d (2026-05-19) — 4 features portail

### ✨ Iter36a — Top expéditeurs enrichi (Portal/Dashboard)
- Endpoint `/me/dashboard/wa-media-summary` enrichi : pour chaque top contact, ajoute `in_directory`, `contact_id`, `last_message_preview` (160 car.), `last_message_at`, `last_message_direction`.
- Nouvel endpoint `POST /me/wa-import-by-phone` : import idempotent au répertoire directement depuis un numéro (re-link automatique des anciens messages).
- UI : composant `TopSendersList` avec bouton "Importer" (purple) si pas au répertoire, badge "✓ Répertoire" sinon, icône 👁️ Eye pour aperçu du dernier message inline (avec direction + horodatage), icône 💬 vers la conversation.

### ✨ Iter36b — Notifications sonores pour tickets
- Nouveau hook `useTicketNotifier` (poll 30s sur `/me/tickets/pending-count` + `/me/tickets?limit=50`).
- Détecte 2 cas : (1) nouveau ticket → toast warning + son "bing-bong" + notif desktop ; (2) changement de statut sur un ticket connu → toast colorisé (info/warning/success) + son court.
- Réutilise les toggles localStorage du `useWhatsAppNotifier` (1 seul réglage utilisateur).

### ✨ Iter36c — Clôture ticket → Intervention auto-générée
- `me_close_ticket` insère automatiquement une intervention dans `db.interventions` avec : numéro auto (`_next_intervention_number`), titre `Ticket <numéro> — <motif>`, description structurée (origine, contact, dates ouverture/clôture, résolution, suspensions), durée active en heures (durée totale moins temps suspendu), technicien = `closed_by_label`, `source_ticket_id` + `source_ticket_number` pour traçabilité.
- Si l'outcome est `cancelled` → statut intervention = `cancelled`, sinon `completed`.
- Activity log `intervention.auto_created`.

### ✨ Iter36d — Note de Service (broadcast WhatsApp)
- Nouveau endpoint `POST /me/notes/{kind}/{note_id}/note-de-service` : ne fonctionne que pour des notes **publiques + numérotées**. Strip HTML, dispatch un template WA à 3 paramètres (`numero`, `nom destinataire`, `contenu`) à tous les `tracked_users` actifs du client lié.
- Settings admin : `wa_template_note_service` (défaut `notedeservice_fr`) + `wa_template_note_service_language` (défaut `fr`).
- Chaque envoi crée une ligne `whatsapp_messages` outbound (la conversation par destinataire est ainsi peuplée) avec `source=note_de_service`, `source_note_id`, `source_note_numero`.
- UI : bouton "Note Service" emerald sur chaque NoteCard publique numérotée, avec confirmation inline, badge "x déjà envoyés" si historique.

✅ **Tests pytest** : 5/5 Iter36 verts (top senders enrichment, ticket close → intervention, note-de-service rejette privée/sans numéro, broadcast envoie à chaque suivi).

---

## Latest — Iter35y+z (2026-05-19) — Refactor amorce + Tableau de bord SMS

### ✨ Iter35y — Amorce refactor `server.py` (extraction modulaire)
- Création de `/app/backend/routes/` (FastAPI APIRouters) et `/app/backend/services/` (pure helpers).
- Premier module extrait : **`services/alexa.py`** (~80 lignes — Alexa Voice Monkey notifier).
- `server.py` ne garde que des wrappers minces qui réinjectent `db` → aucun appel existant cassé.
- Document `/app/backend/REFACTORING.md` : pattern + checklist + backlog des modules à extraire.

### ✨ Iter35z — Tableau de bord SMS temps réel (P1)
- Nouveau router **`routes/sms_dashboard.py`** (greenfield, suit le nouveau pattern).
- Endpoint `GET /api/admin/sms/dashboard?days=30` retourne : totaux (OK/KO/succès%/coût), détail par opérateur (Orange/Moov/Telecel/OVH avec coût unitaire configurable), jauge budget mensuel (ok/warning/over), top 10 erreurs, série quotidienne zéro-fillée.
- Settings ajoutés : `sms_orange_unit_cost_xof`, `sms_moov_unit_cost_xof`, `sms_telecel_unit_cost_xof`, `sms_ovh_unit_cost_xof`, `sms_monthly_budget_xof`.
- UI : `/admin/sms-dashboard` avec 4 stat cards, jauge budget colorée (vert/ambre/rose), 4 tuiles opérateurs (OK/KO/% réussite/coût), graphique en barres quotidien, top erreurs avec compteur.
- Tests pytest : 2/2 verts (schéma complet + warning budget dépassé).

✅ **Tests cumulés** : 16/16 verts (Iter35s/t/w/x/z).

---

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


---

# Historique antérieur

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

## Iter38r-fix8 (2026-05-28) — 🗂️
- ✅ **Persistance Object Storage finalisée** : tous les uploads (admin, media-library, photos contacts, médias WhatsApp inbound/outbound, pièces jointes de formulaires, médias IA) sont désormais **mirrorés sur Emergent Object Storage** dès l'enregistrement. La rehydratation au moment du `GET /api/files/{file_id}` couvre les redéploiements production qui vidaient le disque éphémère.
- ✅ **Helper `object_storage.py`** : nouveau module avec `save_and_log()` + collection `stored_objects` pour la traçabilité multi-tenant (utilisé par les générations IA Gemini Nano Banana / Sora 2).
- ✅ **Templates n8n** : `/app/memory/n8n_templates.md` documente 5 workflows clé-en-main (WhatsApp, Facebook Messenger, SMS, Email, Outbound Dispatcher) connectés à `/api/webhooks/liluvine-pro/{source}/{secret}`.
- ✅ **Iter38r — 90+/90+ tests pytest pass** (cumulatif sur 8 itérations).

## Iter38r-fix8b (2026-05-28) — 🎯
- ✅ **Régression écran de bienvenue corrigée** : la modale "Bienvenue 👋" affiche désormais une section "Synthèse de votre activité" avec compteurs cliquables Rapports / Suivis / Notes / Tâches (+ badge "X en retard" pour les tâches dépassées). Le Dashboard `/portal` affiche également toujours les 4 NoteCards (Rapports/Suivis si feature activée + Notes/Tâches systématiquement) quelle que soit la configuration features.
- ✅ **Badge "🔒 Persistant" + statistiques** : le générateur de médias `/portal/media-generator` affiche un compteur global `X fichier(s) protégé(s) · Y Mo` (depuis `stored_objects`) et chaque vignette de l'historique IA porte une pastille verte 🔒 lorsque le fichier est stocké sur Emergent Object Storage.
- ✅ **API enrichie** : `/me/welcome-briefing` retourne `notes_kpis` (counts + last_updated + overdue tasks). `/me/ai/history` retourne `persistent: bool` par item + `storage_stats: {files, bytes}`.

## Iter38r-fix8c (2026-05-28) — 🐛
- 🐛 **BUG PROD CORRIGÉ — Toggle Liluvine PRO ne persistait pas** : le modèle Pydantic `ClientFeaturesUpdate` ne déclarait pas le champ `ai_liluvine_pro`, donc Pydantic le supprimait silencieusement avant l'enregistrement en base. Activer le toggle dans SMART Communications n'avait aucun effet — l'écran Liluvine PRO disait "non activé". **Le champ est désormais ajouté au modèle**. ⚠️ **À redéployer en prod** pour que les utilisateurs puissent activer Liluvine PRO.
- ✅ **Test de régression statique** : nouveau test garantit que CHAQUE clé de `DEFAULT_CLIENT_FEATURES` doit exister dans `ClientFeaturesUpdate.model_fields`. Empêche toute future feature d'être oubliée du modèle Pydantic.

## Iter38r-fix9a (2026-05-29) — + fix9c 🤖📚

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

## Iter38r-fix9d (2026-05-29) — 🎉
- ✅ **Mini-compteur ROI Liluvine PRO** dans la modale de bienvenue : *« X WhatsApp pris en charge par Liluvine aujourd'hui 🎉 »*. Affiche aussi les minutes économisées, le compteur d'hier, le total 7 jours, et un badge "⏸ Désactivé" si le toggle est off.
- ✅ Section dédiée gradient fuchsia avec icône Bot. Apparaît dès qu'il y a au moins 1 message dans les 7 derniers jours.
- ✅ Endpoint `/me/welcome-briefing` enrichi avec `liluvine_autoreply_today: {today, yesterday, last_7d, minutes_saved_today, enabled}`. Scope tenant (admin/superviseur voient leur tenant, tracked users héritent du parent).
- ✅ **2 tests pytest** verts (structure + comptage par fenêtre temporelle).

## Iter38r-fix9e (2026-05-29) — 🎨🔔

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

## Iter38r-fix9f (2026-05-29) — 🤝🪟👁

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

## Iter38r-fix9g (2026-05-29) — 🔧

### 3 bugs corrigés
- 🐛 **Fix #1 — 👁 Œil sur "Partagés avec moi"** : maintenant **toujours visible** sur les notes/tâches/rapports/suivis dont vous n'êtes pas le propriétaire (admin inclus). Permet la consultation rapide sans entrer en mode édition.
- 🐛 **Fix #3 — Recherche AdminSettings trouve "Liluv"** : les 3 sections (Auto-réponse WhatsApp, Branding, Base de connaissance) sont maintenant enveloppées dans `<Filterable>` → indexées par la barre de recherche d'AdminSettings.
- 🐛 **Fix #4 — Cohérence multi-utilisateurs détecte les tracked_users** : `_scan_clients_consistency` étend désormais le scan aux utilisateurs trackés (avec `parent_client_id`), via une jointure sur l'admin parent de leur tenant. Les tracked users dont `client_id != parent_client_id` (admin canonique) sont maintenant correctement détectés et listés pour réalignement.

✅ **2 tests pytest** (détection de tracked user désaligné + structure de la réponse).
✅ **Total cumulé : 67/67 verts** + lint OK.

## Iter38r-fix9h (2026-05-30) — 🔥

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

## Iter38r-fix9i (2026-05-30) — 🤝🔍📅

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

## Iter38r-fix9j (2026-05-30) — 💸📧

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

## Iter38r-fix9k (2026-05-30) — 📋📄📝

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

## Iter38r-fix9l (2026-05-30) — 🎁 (Batch A : Bonus pack)

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

## Iter38r-fix9m (2026-05-30) — + fix9n 🎨🛒 (Batchs B + C)

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

## Iter38r-fix9o (2026-05-30) — 🎟️📱 (Items 6 + 8 + Coupons UI)

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

## Iter38r-fix9o (2026-05-30) — P1 ⚡ (Webhook Stripe)

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

## Iter38r-fix9o (2026-05-31) — v2 🎟️🏷️⚡

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

## Iter38r-fix9p (2026-05-31) — 📚 (Documentation)

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

## Iter40-modal (2026-06-04) — Régie publicitaire : modale aléatoire publique

### 🎯 1) Nouveau placement `public_modal`
- Backend `routes/ad_banners.py` : regex `placement` étendue à `^(public|portal|both|public_modal)$`.
- `GET /api/public/ad-banners/active?placement=public_modal` retourne uniquement les bannières `public_modal` (pas de fuite avec `public`/`both`).
- Sélection aléatoire pondérée par budget restant (même algo).

### 💫 2) Composant frontend `PublicAdModal.jsx`
- Modal centré (z-index 9999), backdrop blur, fermeture par X / ESC / clic backdrop.
- Badge "PUBLICITÉ", CTA "Découvrir →", responsive (max-h 70vh).
- Intégré dans `MarketingLayout.jsx` (toutes pages publiques).
- Tracking impression/clic via les endpoints existants.

### 🛠️ 3) Admin UI
- Option `<option value="public_modal">Modale aléatoire (page publique)</option>` ajoutée au select Emplacement.
- Libellé colonne « Modale publique » dans la liste.

### 🧪 4) Tests
- `test_iter40_public_modal_placement.py` (4 tests) + régression 16 anciens.

---

## Iter40-modal-frequency (2026-06-04) — Fréquence + compteurs modale dédiés

### ⏱️ 1) Champ `modal_frequency`
- Valeurs `session` | `daily` | `always`, défaut `session`.
- Validation regex + persistance + retour dans `_public_view`.

### 📊 2) Compteurs séparés
- `modal_impressions` / `modal_clicks` incrémentés en plus du global lors de `?modal=1`.
- Stats endpoint expose un bloc `modal: {impressions, clicks, ctr_pct, frequency}`.

### 🎨 3) Frontend
- `PublicAdModal.jsx` choisit le storage selon la fréquence (`sessionStorage` / `localStorage` daté / aucun).
- `AdminAdBanners.jsx` : nouveau select "Fréquence d'affichage" + bloc stats fuchsia modale.

### 🧪 4) Tests
- `test_iter40_modal_frequency.py` (7 tests) — défaut, validation, séparation des compteurs.

---

## Iter40-modal-ab + global-cap (2026-06-04) — A/B fréquence + plafond global

### 🛡️ 1) Plafond global anti-spam (`modal_global_cap_per_day`)
- Champ ajouté à `SettingsUpdate` (modèle), validation 0-20 dans `server.py`.
- Nouvel endpoint **anonyme** `GET /api/public/ad-banners/config` retourne le cap.
- `AdminSettings.jsx` : bloc "Régie publicitaire — Plafond de modales" avec presets 0/1/2/3/5.
- `PublicAdModal.jsx` : compteur dans `localStorage` daté (réinit auto chaque jour), modal ne s'affiche pas si plafond atteint.

### 🅰️🅱️ 2) A/B sur la fréquence modale
- Nouveau champ `variant_b_modal_frequency` dans `AdBannerPayload`/`Update`.
- `_public_view` : si variante B tirée + override défini, retourne la fréquence B (sinon fallback global).
- Compteurs par variante : `modal_impressions_a/b`, `modal_clicks_a/b`.
- `AdminAdBanners.jsx` : select visible quand A/B activé + placement=public_modal, tuiles de stats par variante (`ModalVariantTile`).

### 🧪 3) Tests
- `test_iter40_modal_ab_and_global_cap.py` (9 tests) — settings, cap, A/B variant frequency, fallback, compteurs, stats.
- **36/36 PASS** au total sur la régression ad-banners.

---

## Iter40-content-i18n (2026-06-04) — Contenus CMS multilingues

### 🌍 1) Modèle `ContentUpsert` enrichi
- Nouveau champ `translations: dict = {}` au format `{ "en": {"title", "body_html", "metadata"}, "ar": {...}, ... }`.
- Stockage MongoDB inchangé (collection `contents`).

### 🔗 2) Endpoints publics avec paramètre `?lang=`
- `GET /content?lang=xx` et `GET /content/{slug}?lang=xx` appliquent un deep-merge : override > default (metadata fusionnées key-by-key).
- Sans paramètre `lang`, les contenus par défaut (FR) sont retournés inchangés.
- Helper `_apply_content_lang(doc, lang)` réutilisable.

### 🎨 3) Admin UI multi-onglets
- `AdminContents.jsx` complètement réécrit avec :
  - Onglets de langues (FR base + langues chargées depuis `/i18n/languages`)
  - Indicateur ● vert quand une surcharge existe pour la langue
  - Bouton "Effacer les surcharges" pour revenir au défaut
  - Tous les champs (titre, kicker, body_html, metrics, items, JSON brut) gèrent la langue active
  - Fallback affichant la valeur par défaut quand l'override n'existe pas (UX claire)

### 🔄 4) Public pages réactives au changement de langue
- `Home.jsx`, `Missions.jsx`, `Specialisations.jsx` : `useI18n()` import + `lang` dans les dépendances de l'effet de fetch.
- Quand l'utilisateur change la langue dans le `LanguageSelector`, les contenus re-fetchent automatiquement avec la bonne traduction.

### 🧪 5) Tests
- `test_iter40_content_i18n.py` (6 tests) — upsert, fallback sans lang, override appliqué, lang inconnue, deep-merge metadata, list endpoint.
- **6/6 PASS**.


## Iter40-i18n-model (2026-06-04) — Sélecteur de modèle IA + traduction en lot

### 🤖 1) 6 modèles de traduction au choix
- Backend `routes/i18n.py` : registre `_TRANSLATE_MODELS` avec Claude Sonnet 4.5 / Haiku 4.5, GPT-4o / 4o-mini, Gemini 2.5 Pro / Flash.
- Nouvel endpoint `GET /api/admin/i18n/translate-models` (renvoie items + défaut).
- `POST /api/admin/i18n/translate-suggest` accepte désormais un champ `model` optionnel.

### ⚡ 2) Traduction en lot pour i18n
- Nouvel endpoint `POST /api/admin/i18n/translate-empty-bulk` :
  - Trouve toutes les lignes où FR est non-vide ET la langue cible vide
  - Lance le modèle sélectionné séquentiellement
  - Retourne un rapport `{translated, skipped, errors, total_candidates}`
- Frontend `AdminI18n.jsx` : nouveau bloc violet "Traducteur IA — réglages" avec dropdown modèle + select langue + bouton "Traduire toutes les cellules vides en XX".

### 📝 3) Traduction de contenu entier en une passe
- Nouvel endpoint `POST /api/admin/content/{slug}/translate` :
  - Extrait titre + body_html + metadata.kicker + metrics labels + items title/desc
  - Envoie en JSON au modèle avec prompt strict "préserver balises HTML, placeholders, marques (SAWALI, Liluvine, WhatsApp)"
  - Parse la réponse JSON et persiste dans `translations[<target_lang>]`
  - Préserve les `icons` des items (le LLM ne connaît pas notre vocabulaire d'icônes)
- Frontend `AdminContents.jsx` : dropdown modèle + bouton "Traduire ce contenu en XX" visible uniquement quand une langue ≠ défaut est sélectionnée.

### 🧪 4) Tests
- `test_iter40_i18n_model_selector.py` (9 tests) : liste des modèles, validation, refus de modèles/langues inconnus, refus de slug inconnu, refus de contenu vide.
- Régression Iter40 complète : **35/35 PASS** (9 model + 6 content + 9 modal-ab + 7 modal-freq + 4 placement).


## Iter40-hr-fixed (2026-06-04) — Type de paie « Forfaitaire »

### 💼 1) Nouveau pay_type="fixed" dans GRH
- Backend `routes/hr.py` :
  - `EmployeePayload.pay_type` et `EmployeeUpdate.pay_type` : pattern `^(monthly|hourly|fixed)$`
  - Calcul timesheet : `if pay_type == "fixed": computed = round(base_salary, 2)` (pas de ratio horaire, pas de proratisation)
  - Calcul payroll : `hourly_for_deduction = 0` pour `fixed` → **aucune déduction d'absence** (le forfait n'est pas amputé)

### 🎨 2) Frontend `HumanResources.jsx`
- Dropdown étendu : `Mensuel (prorata heures)` / `Horaire` / `Forfaitaire (montant fixe)`
- Encart d'information ambre affiché quand "fixed" est sélectionné : "L'agent recevra exactement {amount} {currency} chaque mois, indépendamment des heures travaillées ou des absences. Idéal pour les recrutements en fin de mois, périodes d'essai ou prestataires au forfait."
- Libellés "Forfaitaire" + suffixe "· forfait" dans toutes les tables : tableau de présence mensuel (totaux du mois), liste paie des salaires, liste employés
- Le champ "Heures mensuelles contractuelles" est masqué quand `fixed` (pas pertinent)

### 🧪 3) Tests
- `test_iter40_hr_fixed_pay_type.py` (5 tests) :
  - Création avec pay_type=fixed
  - Refus des valeurs invalides (HTTP 422)
  - PATCH d'un monthly vers fixed
  - Critère clé : `computed_gross == base_salary` même avec 0 heures travaillées
  - Régression : `monthly` continue de proratiser (=0 avec 0 heures)
- Tous **PASS**.


## Iter40-route-loader (S051) (2026-06-04) — Toggle GlobalRouteLoader

### 🎛️ 1) Endpoint anonyme `GET /api/public/ui-flags`
- Expose UNIQUEMENT `{global_route_loader_enabled, download_gauge_enabled}` — jamais de secrets
- Anonyme : aucun header d'auth requis (le loader monte avant l'authentification)

### 🛠️ 2) Backend `SettingsUpdate.global_route_loader_enabled`
- `models.py` : nouveau champ `Optional[bool] = None` (défaut conceptuel = `True`)
- Le défaut est appliqué dans l'endpoint public via `is not False`

### 🎨 3) Frontend `GlobalRouteLoader.jsx`
- Fetch le flag au mount via `/api/public/ui-flags`
- Cache dans `localStorage["ui_flag_global_route_loader_enabled"]` pour éviter un flash au prochain chargement
- Écoute `window.addEventListener("ui-flags-updated", ...)` pour réagir aux changements sans rechargement
- Early-return `null` quand désactivé (aucun interceptor axios, aucun event de route)

### 🎛️ 4) Frontend `AdminSettings.jsx`
- Nouveau bloc "Affichage — Jauge de transition entre pages" avec checkbox claire
- Au toggle, dispatch immédiat de `CustomEvent("ui-flags-updated")` pour propager sans reload

### 🧪 5) Tests
- `test_iter40_route_loader_toggle.py` (5 tests) :
  - Endpoint anonyme accessible sans auth
  - Défaut `true` quand le réglage n'est jamais écrit
  - Admin peut basculer ON/OFF
  - Aucune fuite de secrets (vérification de pattern de noms)
  - GET /admin/settings expose bien le flag
- **5/5 PASS**.


## Iter40-ui-flags (S052) (2026-06-05) — Identité publique (white-label branding)

### 🎨 1) 4 nouveaux champs Settings
- `models.py` : `public_brand_name`, `public_brand_color`, `public_logo_url`, `public_hero_tagline` (tous `Optional[str]`)

### 🌐 2) Endpoint anonyme étendu
- `GET /api/public/ui-flags` retourne désormais 6 clés (2 toggles + 4 branding)
- Chaînes vides/whitespace normalisées en `null` côté backend (validé par test)
- Toujours zéro secret exposé (whitelist explicite + test de garde)

### 🔧 3) Frontend `lib/useUIFlags.js`
- Nouveau hook React partagé : fetch les flags une fois au mount, cache en `localStorage["ui_flags_cache_v1"]`, écoute `window.addEventListener("ui-flags-updated")`
- Applique automatiquement :
  - `document.title = public_brand_name` (quand défini)
  - `document.documentElement.style.setProperty("--brand-primary", public_brand_color)` → utilisable comme `var(--brand-primary, #1E90FF)` dans tout le CSS
- Re-applique le branding à chaque changement de state (cohérence entre cache initial et flags fraîchement fetchés)

### 🎛️ 4) Frontend `AdminSettings.jsx`
- Nouvelle section "Identité publique — marque, logo, couleur"
- Champ texte (nom de la marque), color picker + input hex synchronisés, URL logo avec aperçu image, accroche du hero
- Chaque champ dispatch `ui-flags-updated` au changement → propagation instantanée sans rechargement

### 🔌 5) Frontend `App.js`
- Appel du hook `useUIFlags()` au niveau du composant racine → branding actif pour toutes les routes (publiques et portail)

### 🧪 6) Tests
- 3 nouveaux tests pytest (totaux : **8/8 PASS** dans `test_iter40_route_loader_toggle.py`) :
  - Présence des 4 champs branding (defaut `null`)
  - Admin peut set tous les champs (PUT + GET echo)
  - Normalisation `"   "` → `null` (whitespace strip)
- Test de garde "no secrets" mis à jour avec la nouvelle whitelist élargie.

### 🚀 Pistes pour la suite (futures itérations)
- Remplacer les couleurs hardcodées (`#1E90FF`, `bg-sawali-blue`) par `var(--brand-primary)` dans les composants Tailwind clés (CTA, headers)
- Afficher `public_logo_url` dans `MarketingNav.jsx` quand défini (sinon logo SAWALI par défaut)
- Override de `home_hero.title` par `public_hero_tagline` quand défini


## Iter40-ui-flags-tailwind (2026-06-05) — Propagation du branding dans toute la palette

### 🎨 1) Palette Tailwind résolue via CSS variables
- `tailwind.config.js` :
  - `sawali.blue` → `var(--brand-primary, #1E90FF)` (fallback = défaut SAWALI)
  - `sawali.blue-light` → `var(--brand-primary-light, #2BA4FF)`
  - Nouveau scope sémantique `brand: { DEFAULT, light, dark }` également câblé sur les CSS variables
- Conséquence : **TOUS** les `bg-sawali-blue`, `text-sawali-blue`, `border-sawali-blue`, `ring-sawali-blue`, `hover:bg-sawali-blue-light` etc. présents dans le code existant héritent automatiquement de la couleur définie en Admin. Zéro refactor nécessaire.

### 🌗 2) Light/Dark variants calculés automatiquement
- `lib/useUIFlags.js` : nouvelle fonction `shiftColor(hex, amount)` qui éclaircit (+12 %) ou assombrit (−18 %) une couleur hexa
- À chaque application, `--brand-primary-light` et `--brand-primary-dark` sont dérivés du `public_brand_color` choisi par l'admin → cohérence visuelle entre les 3 nuances

### 🧪 3) Validation visuelle
- Test in-browser : override de `--brand-primary` à `#FF3366` (rose vif) sur la page d'accueil
- Confirmation : badges header, boutons CTA, icônes horloge/visites, "Espace Loois", stats "10+/30+/24/7", lien "En savoir plus" dans le cookie banner → **TOUS passent instantanément en rose**
- Aucune régression sur les couleurs neutres (navy, gris, texte) — uniquement les éléments brandés sont retintés

### 🚀 Pistes restantes (encore à faire)
- Afficher `public_logo_url` dans `MarketingNav.jsx` quand défini (sinon logo SAWALI par défaut)
- Override de `home_hero.title` par `public_hero_tagline`


## Iter40-ui-flags-bugfix + logo + text-color + search (2026-06-05) — Itération polish

### 🐛 1) Bugfix branding live preview (S052 amendée)
- `lib/useUIFlags.js` exporte désormais `applyBrandingLocal` (alias de la fonction interne `applyBranding`)
- `AdminSettings.jsx` : tous les inputs de la section "Identité publique" appellent `applyBrandingLocal({...})` au `onChange` au lieu de dispatcher l'event (qui re-fetchait l'ancienne valeur de la DB)
- Le dispatch `ui-flags-updated` est désormais déclenché APRÈS un `PUT /admin/settings` réussi (bouton "Enregistrer") pour rafraîchir le cache localStorage des autres onglets/sessions
- Note d'aide mise à jour : « Aperçu en direct dans votre navigateur — cliquez sur Enregistrer pour persister et propager à tous les visiteurs. »

### 🎨 2) Couleur de texte personnalisable (S053)
- Backend `models.py` + `server.py` : nouveau champ `public_brand_text_color` exposé via `/api/public/ui-flags`
- Frontend `useUIFlags.js` : applique `--brand-text` au `:root` (défaut `#FFFFFF`)
- Frontend `tailwind.config.js` : nouveau scope `brand.text` câblé sur `var(--brand-text)`
- Frontend `AdminSettings.jsx` : 2ème color picker "Couleur du texte (sur fond brand)" + tuile d'aperçu de contraste live

### 🖼️ 3) Logo dynamique dans MarketingNav (S054)
- `components/MarketingNav.jsx` importe `useUIFlags`, lit `flags.public_logo_url` (fallback `LOGO_URL`) et `flags.public_brand_name` (fallback "SAWALI SMART SYSTEMS")
- Le logo téléversé en Admin Settings remplace désormais le logo SAWALI dans le header de toutes les pages publiques
- Data-testids ajoutés : `navbar-logo-img`, `navbar-brand-name`

### 🔍 4) Recherche full-text dans /admin/suggestions (S055)
- `AdminSuggestionsRegistry.jsx` : nouvelle barre de recherche violet
- Algo : tokenize (≥2 chars, lowercased, accent-insensible), split par `## ` headings, filtre AND sur tous les tokens, highlight `<mark>` jaune, compteur live "X / Y"
- Bouton "Effacer" + message "Aucune suggestion ne correspond..."

### 🏷️ 5) Renommage "Qdrant RAG" → "RAG (Qdrant)" (S056)
- `AdminSettings.jsx` : libellé de la section S038 modifié pour utiliser "RAG" comme mot-clé principal (cohérence vocabulaire métier)
- Recherche fonctionne avec "rag" OU "qdrant"


## Iter40-ui-flags-bg (S057) (2026-06-05) — Habillage du fond (événementiel / charte client)

### 🖼️ 1) 8 nouveaux champs Settings
- `models.py` : 4 par scope (public + portail) — `bg_mode`, `bg_color`, `bg_image_url`, `bg_image_position`
- `mode` peut être `default | color | image`
- `image_position` peut être `cover | contain | center | repeat`
- `/api/public/ui-flags` expose les 8 champs avec défauts (`mode=default`, `position=cover`)

### 🎨 2) Composant `BackgroundApplier.jsx` (App-level)
- Render-less, monté dans `App.js` à côté de `GlobalRouteLoader`
- Écoute `useLocation()` et `useUIFlags()`
- Détecte le scope actif via le pathname : `/portal*` ou `/admin*` → scope **portail**, sinon → scope **public**
- Applique les styles directement sur `<body>` :
  - mode=color → `backgroundColor`
  - mode=image → `backgroundImage` + `backgroundRepeat/Size/Position` selon la position choisie + `backgroundAttachment: fixed` (effet parallaxe)
  - mode=default → strip propre via `removeAttribute("data-bg-override-active")`
- Marqueur `data-bg-override-active="1"` sur `<body>` pour signaler aux layouts qu'ils doivent devenir transparents

### 🎭 3) `MarketingLayout.jsx` réactif
- Hook local `useBgOverrideActive()` via `MutationObserver` sur `data-bg-override-active`
- Quand override actif : classe `marketing-dark` (gradient sombre opaque) est remplacée par juste `min-h-screen flex flex-col overflow-x-hidden text-white` (transparent) → le fond `<body>` apparaît à travers
- Quand pas d'override : retour à la palette SAWALI sombre habituelle

### 🛠️ 4) Admin UI : composant `BgEditor` (dual scope)
- Nouvelle section "Habillage — fond de page (événementiel / charte client)" dans `AdminSettings.jsx`
- Deux blocs côte-à-côte (`lg:grid-cols-2`) : "Pages publiques" + "Espace Loois (Portail + Admin)"
- Chaque éditeur : mode select, color picker (mode=color OU image overlay), URL image (mode=image), position select, tuile aperçu live qui reproduit le style appliqué

### 🧪 5) Tests
- `test_iter40_bg_theming.py` (4 tests) : 8 champs exposés, set public color, set portal image avec position, normalisation chaînes vides. **4/4 PASS**.

### 📌 Note d'usage
Les pages avec hero illustratif (Home, certaines landing pages) ont leur propre visuel qui se superpose au fond global. Le fond personnalisé est plus dominant sur :
- Pages publiques sans hero illustré (Missions, Contact, Politique, Catalogue, etc.)
- Toutes les pages du portail (`/portal/*`, `/admin/*`)

