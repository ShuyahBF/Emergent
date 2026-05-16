# 📒 SAWALI SMART SYSTEMS — Journal des évolutions

> **Document de synthèse** consultable et exportable.
> Toutes les itérations livrées sur ce CRM/Portail, classées par date, avec leurs réalisations, leurs suggestions et leurs prochaines actions.
> Fichier de référence : `/app/memory/CHANGELOG.md`

---

## 🛡️ Couche de défense « cohérence des clients » (5 itérations consécutives)

Pour bien comprendre l'enchaînement, voici comment les itérations 28 à 32 se complètent :

| Itération | Rôle | Activation |
|---|---|---|
| **iter28** | Récupère les données historiques orphelines | Auto au boot + bouton manuel |
| **iter29** | Rend tous les contacts collaboratifs par client | Auto au boot |
| **iter30** | Diagnostic ciblé par email + réalignement | UI Paramètres |
| **iter31** | Canari panoramique au boot + UI globale | Auto au boot + UI Paramètres |
| **iter32** | Prévention à la création d'utilisateur | Bandeau dans le formulaire admin |

---

## ✅ Réalisations chronologiques

### 2026-04-25 — MVP initial
- Backend FastAPI complet (auth, public, portal, admin, documents, settings, NPS feedback)
- Frontend marketing + portal client + admin console
- Google Calendar OAuth, reCAPTCHA v2, SMTP OTP
- Auto-seed admin + contenus par défaut

### 2026-05-09 — Iter24 : 4 derniers feedbacks utilisateur
- **Code Unique inaltérable** par contact (`YYYY-CLIENTPREFIX-NNNN`, ex. `2026-SAWALISM-0001`) — généré via compteur Mongo atomique, backfill startup, immuable au PUT, affiché avec icône cadenas
- **RGPD `anon_company`** — toggle masquant la société sous forme `A*** C***` pour les non-privilégiés
- **Toggle `wa_sound_alerts` par client** — kill switch admin du son WhatsApp
- **Restriction photo contact** aux rôles `admin`/`superviseur`/`moderateur`
- **Auto-sync nom WhatsApp** via webhook (Meta n'expose pas la photo de profil)
- 🛠️ Bug fix : `client_id` mirroré sur les comptes utilisateurs suivis

### 2026-05-09 — Iter25 : WhatsApp Bulk
- Module `/portal/whatsapp-bulk` : envoi de templates Meta approuvés à plusieurs contacts en une fois
- Endpoint `POST /api/me/whatsapp/bulk` (cap 500 contacts), validation +30 s, RBAC
- Personnalisation par jetons : `{{name}}`, `{{company}}`, `{{phone}}`, `{{email}}`, `{{client_code}}`
- Aperçu personnalisé sur 3 destinataires + planification + historique
- Sidebar « WhatsApp — Masse & Planif. »

### 2026-05-09 — Iter26 : 3 fixes UI + WhatsApp→SMS fallback
- 🐛 **Bug Subscriptions** : double header corrigé (MarketingLayout doublonné supprimé)
- ✨ **Header sticky avec jauge intégrée** : bandeau « 🎧 Support |||| Charge modérée 4/7 » centré, sticky pendant le défilement
- 🐛 **Sidebar admin tronquée** : passage en *fixed-shell pattern* (`h-screen overflow-hidden`)
- 🚨 **Bug critique pré-existant** : intercepteur axios 401 redirigeait tous visiteurs anonymes vers `/login` (site marketing cassé)
- ✨ **WhatsApp→SMS fallback** : nouveau toggle dans `/portal/whatsapp-bulk`, retente automatique en SMS si WA échoue, traçabilité via `wa_fallback:true`

### 2026-05-09 — Iter27 : Campaign Efficiency Dashboard
- Endpoint `GET /api/admin/campaign-efficiency?days=N` (1-90 jours)
- Section « ⚡ Efficacité de campagne » dans `/admin/usage` : 4 KPI cards (Délivrance WA, Délivrance SMS, Repli SMS, Économie estimée) + BarChart empilé sur 30 jours
- Re-fetch automatique au changement de période

### 2026-05-09 — Iter28 : 🚨 HOTFIX prod — récupération des contacts orphelins
- Récupération des contacts/messages/SMS/schedules/payment-links tagués avec l'`id` de l'utilisateur au lieu du `parent_client_id` (bug iter24)
- Migration auto au boot + endpoints admin `GET/POST /api/admin/migrate-orphan-data`
- Conservation de l'ancien `client_id` dans `client_id_legacy` (rollback possible)
- Idempotente

### 2026-05-09 — Iter28b : UI admin + canari de régression
- Section UI **« 🔧 Diagnostic des données orphelines »** dans Paramètres avec dry-run automatique, compteurs, liste des affectés, bouton « Appliquer »
- Canari de régression au boot : log `WARNING` si nouveaux orphelins détectés

### 2026-05-10 — Iter29 : Modèle collaboratif des contacts
- Tous les contacts du Centre de Messagerie sont désormais visibles ET modifiables par tous les utilisateurs du même client
- `GET /me/contacts` ne filtre plus que sur `client_id`
- `PUT/DELETE /me/contacts/{cid}` autorisés à tout user du même client
- Audit `last_edited_by_id/label/at` quand l'éditeur ≠ propriétaire
- Migration startup `iter29` : normalise tous les contacts à `shared:true`
- UI : badge « 🤝 Équipe » + sous-titre « par {owner_label} »

### 2026-05-10 — Iter30 : Diagnostic & réalignement par utilisateur
- `GET /admin/client-data-diagnostic?email=…` : résout le client canonique (parent_client_id → admin de même company → self), liste pairs, plan détaillé
- `POST /admin/realign-user-to-client {email}` : applique le plan (idempotent, conserve `client_id_legacy`)
- Section UI **« 🔍 Diagnostic visibilité par utilisateur »** dans Paramètres

### 2026-05-10 — Iter31 : Canari de cohérence multi-utilisateurs
- `_scan_clients_consistency()` : groupe les users par `company`, identifie le canonique, liste les désalignés
- Boot canary : log `WARNING` au démarrage avec résumé + jusqu'à 10 groupes détaillés
- `GET /admin/clients-consistency` (vue panoramique JSON)
- Section UI **« 🟣 Cohérence multi-utilisateurs »** dans Paramètres : bandeau vert si tout OK, sinon liste des groupes désalignés avec bouton « Réaligner » par utilisateur

### 2026-05-10 — Iter32 : Auto-link à la création (prévention à la source)
- `UserCreateAdmin` étendu avec `link_to_client_id` optionnel
- `GET /admin/resolve-company?company=...` : retourne le canonique d'un nom d'entreprise
- `POST /admin/clients` honore `link_to_client_id` → mirrore `parent_client_id` + `client_id`
- Frontend `AdminClients.jsx` : bandeau violet **« Une entreprise X existe déjà »** avec checkbox **« Lier au client canonique »** à la sortie du champ Entreprise

---

## 💡 Suggestions d'amélioration encore en attente

Ces idées ont été proposées au fur et à mesure des itérations. Vous pouvez en sélectionner une et me dire « Vas-y, implémente-la » quand vous serez prêt(e).

| # | Itération source | Suggestion | Effort estimé |
|---|---|---|---|
| 1 | Iter24 | Afficher le **Code Unique** sur les liens de paiement PawaPay et les futures factures PDF | Faible (1-2h) |
| 2 | Iter25 | (Idée non explicite, déjà couverte par iter26 — repli SMS) | — |
| 3 | Iter26 | (Couvert par iter27) | — |
| 4 | Iter27 | **Rapport mensuel automatique par e-mail** envoyé chaque 1er du mois aux Admin/Superviseur avec les 4 KPIs + mini-graphique du mois écoulé | Moyen (4-6h) |
| 5 | Iter28b | Étendre le diagnostic en **« Santé des données »** (contacts sans `unique_code`, messages sans `client_id`, payment_links expirés non purgés, users avec `tracked_user_id` cassé) | Moyen (3-5h) |
| 6 | Iter29 | **Flux d'activité par contact** : qui a édité quoi, quand, depuis quel appareil — mini-historique sous chaque fiche | Moyen (4h) |
| 7 | Iter32 | **Auto-link à la modification** d'un user existant (`PUT /admin/clients/{id}`) : si on change la `company`, re-proposer la bannière de liaison + alerter si désalignement | Faible (2h) |
| 8 | (sur demande) | Intégration **Transkribus.org** — OCR de l'écriture manuscrite (fiches d'intervention, devis scannés, archives papier) | Important (1-2j) |

---

## 🆕 Iter35n — Version stamp + Réactivité WA + Filtre/Nettoyage médias WA — 2026-05-16

**Livré** :
- **Version stamp** sur la page de connexion (`/login`) — affiche `iter35n · {git_sha} · {build_date}` en bas de la carte, lu via le nouvel endpoint **public** `GET /api/version`. Permet à l'utilisateur de confirmer la version déployée avant de se connecter.
- **Score réactivité WhatsApp** — chaque envoi (texte/média) qui répond à un inbound encore non répondu stamp `reply_to_inbound_id` + `reply_seconds` sur le message outbound. Nouveau bloc "⚡ Mon score réactivité WhatsApp" dans la carte dashboard avec : temps moyen, médiane, plus rapide, nombre de réponses (sur 7/30/90j). Pour les rôles élevés (admin/superviseur/admin-tracked) : classement de l'équipe (top 10 par temps moyen). Fenêtre de validité = 7 jours (au-delà, n'est plus considéré comme une "réponse"). Endpoint : `GET /api/me/dashboard/wa-reply-stats?days=N`.
- **Filtre "WhatsApp" + Nettoyage** sur la bibliothèque partagée — boutons "Tous / WhatsApp" en haut. Pour admin/superviseur : bouton "Nettoyer les inutilisés" en mode WhatsApp qui dry-run d'abord (liste des médias WA non référencés par aucun rapport/suivi/note/intervention) puis confirme. Endpoints : `GET /api/me/media-library?source=whatsapp_inbound`, `POST /api/me/media-library/wa-cleanup?dry_run=true|false`.

**Tests** : 6 nouveaux pytest verts (`tests/test_iter35n_version_reply_cleanup.py`). Cumul iter35l+m+n = **32 tests verts**.

---

## 🆕 Iter35m — Réutilisation médias WA + Synthèse Dashboard + Notes ciblées — 2026-05-16

**Livré (P0)** :
- **Bouton "Sauvegarder dans la bibliothèque"** sur les bulles d'images reçues dans le chat WhatsApp. Un clic enregistre l'image dans la bibliothèque partagée du client (`media_library`) sans dupliquer le binaire (réutilise l'asset `files`). Idempotent : double-clic = même entrée. Endpoint : `POST /api/me/whatsapp/messages/{msg_id}/save-to-library`.
- **Synthèse "Médias WhatsApp reçus"** sur le dashboard `/portal` avec sélecteur 7/30/90 jours, comptages par type (image/audio/vidéo/PDF), top 5 expéditeurs, et 5 dernières miniatures cliquables. Endpoint : `GET /api/me/dashboard/wa-media-summary?days=7|30|90`.
- **Notes & Tâches ciblées** : nouveau champ `target_user_ids` sur les modèles Note. Quand `is_private=True` ET `target_user_ids` non vide, les utilisateurs ciblés voient la note (en plus de l'auteur et admin/superviseur). UI dans `UserNotes.jsx` : multi-select des destinataires (avec "Moi-même" en premier) qui apparaît uniquement quand "Note privée" est cochée. Nouvel endpoint `/api/me/notes-targets` retournant la liste filtrée par client effectif.

**Tests** : 7 tests pytest verts (`tests/test_iter35m_targeting_and_dashboard.py`).
- TestNotesTargets (Moi-même en premier)
- TestSaveToLibrary (création + idempotence + 404)
- TestWaMediaSummary (counts/top/last + validation days)
- TestNotesTargeting (target_user_ids persisté en DB)

---

## 🆕 Iter35l — Médias WhatsApp (réception + envoi + filigrane + transcription) — 2026-05-16

**Livré (P0)** :
- **Réception médias WA** : le webhook Meta télécharge automatiquement les images/audio/vidéo/PDF (via `/v21.0/{media_id}` puis l'URL signée), persiste le binaire dans `UPLOAD_DIR` + collection `files`, et l'expose via `/api/files/{id}.ext`. Champs DB ajoutés sur `whatsapp_messages` : `media_id`, `media_url`, `media_mime_type`, `media_filename`, `media_size_bytes`, `media_kind`, `media_caption`, `voice_note_transcript`.
- **Envoi médias WA** : nouvel endpoint `POST /api/me/whatsapp/send-media` (multipart : `to`, `contact_id`, `caption`, `file`). Validations : 403 si toggle off, 409 hors fenêtre 24h, 413 si > 16 Mo, 400 si vide. Format Meta : `type=image|document|audio|video`, body `{link, caption?, filename?}` via `_wa_send_media`.
- **Filigrane + QR sur images sortantes** : `_wa_apply_image_watermark_qr` ajoute un texte semi-transparent en bas à droite + un QR code en haut à gauche, sur fond blanc/sombre arrondi, avant l'envoi. Configurable globalement.
- **Transcription auto Whisper sur notes vocales reçues** : si toggle `wa_voice_transcribe_enabled` ON, `_wa_transcribe_audio_file` invoque OpenAI Whisper sur le binaire téléchargé et stocke le texte dans `voice_note_transcript`.
- **Admin toggles RGPD** : nouvelle section "Médias WhatsApp" dans `/admin/settings` avec 4 toggles (`wa_allow_terminal_media`, `wa_voice_transcribe_enabled`, `wa_watermark_enabled`, `wa_qr_enabled`) + 2 champs texte (`wa_watermark_text`, `wa_qr_payload`).
- **UI Contacts (chat 1:1)** : bouton 📎 "Joindre" dans le composer (image/audio/vidéo/PDF, ≤16 Mo) avec aperçu + légende, et bulles enrichies pour rendre images (thumbnail cliquable), audio (player HTML5), vidéo (player), PDF (lien téléchargeable). Transcript en italique sous le player audio.

**Tests** : 19 tests pytest verts (`tests/test_iter35l_wa_media.py` — 8 unit + `tests/test_iter35l_wa_media_http.py` — 11 HTTP intégration, incluant régressions sur `send-text`, webhook inbound et webhook-logs).

**Dépendance ajoutée** : `qrcode==8.2` (Pillow déjà présent).

---

## 🔭 Backlog priorisé (Next Actions)

### 🟡 P1 — Refactoring technique
- **Refactor `server.py`** (> 12 600 lignes) vers `/app/backend/routes/` (auth, sms, whatsapp, payments, admin) — session dédiée recommandée

### 🟢 P2 — Modules métier
- **Caisse / Facturation / Catalogue / Tickets** (actuellement stubs `ComingSoon`)

### 🔵 P3 — Améliorations longue traîne
- **Génération PDF côté serveur** (devis / factures)
- **Stripe Checkout** pour Formations payantes
- **Export CSV** des interventions / RDV
- **Liluvine intelligent** couplé à la jauge support
- **Audit régulier des interfaces et de la cohérence des données** : se réserver des sessions de revue pure (sans implémentation) pour parcourir chaque écran admin et portail, vérifier les données affichées, les filtres, les permissions, et la cohérence visuelle après chaque vague de fonctionnalités. _(Préoccupation utilisateur du 2026-05-10 : « à force d'implémenter, j'en oublie de contrôler les interfaces et la cohérence des données ».)_

### 🔴 BLOQUÉ
- **QR Code "encodePCS"** (en attente de la lib C# de votre côté)

---

## 🧪 Comment vérifier chaque fonctionnalité majeure

| Fonctionnalité | Comment tester |
|---|---|
| Code Unique des contacts | Centre de Messagerie → cliquer sur une fiche → voir « Code: 2026-XXXX-NNNN » sous l'avatar |
| RGPD `anon_company` | Admin → Clients → cliquer ⚙️ d'un client → « Anonymiser les sociétés » → se connecter en utilisateur tracked → voir les sociétés masquées |
| WhatsApp Bulk | Sidebar « WhatsApp — Masse & Planif. » → choisir un template → cocher des contacts → Aperçu / Envoyer |
| WA→SMS fallback | Dans WaBulk → cocher « Repli SMS automatique en cas d'échec WhatsApp » → saisir message + sélectionner provider |
| Campaign Efficiency | Admin → Usage → faire défiler à « ⚡ Efficacité de campagne » |
| Diagnostic orphelins | Admin → Paramètres → « 🔧 Diagnostic des données orphelines » |
| Diagnostic ciblé | Admin → Paramètres → « 🔍 Diagnostic visibilité par utilisateur » → entrer un email → Diagnostiquer |
| Cohérence multi-users | Admin → Paramètres → « 🟣 Cohérence multi-utilisateurs (panoramique) » |
| Auto-link création | Admin → Clients → Nouveau → saisir Entreprise → quitter le champ → bandeau violet |
| Sticky header public | https://sawalismartsystems.com → faire défiler la page d'accueil — header reste visible |
| Sidebar admin (anti-troncature) | Admin → Paramètres → faire défiler vers le bas puis remonter — sidebar gauche reste pleine hauteur |

---

## 📥 Comment consulter / exporter ce document

- **Dans le code** : fichier `/app/memory/CHANGELOG.md` (Markdown lisible directement)
- **Depuis votre poste** : ouvrez le fichier avec n'importe quel éditeur Markdown (VS Code, Typora, GitHub) ou copiez-collez le contenu dans Word/Google Docs
- **Conversion PDF/Word** : Pandoc (`pandoc CHANGELOG.md -o CHANGELOG.pdf`) ou copier-coller dans un traitement de texte avec format Markdown

---

*Dernière mise à jour : 2026-05-10*
