# PRD — SAWALI SMART SYSTEMS Portal

## Original Problem Statement
Construit moi un site web, qui s'affiche bien sur toutes les types de terminaux (ordinateur PC, tablettes et téléphone). Site professionnel de SAWALI SMART SYSTEMS avec accès public (missions, expérience, spécialisation, catalogue, demande de RDV, contact) et espace professionnel (login, mot de passe, captcha, OTP mobile, état du compte, RDV, documentation logiciels, historique interventions, suivi utilisateurs).


_⚠️ Historique récent (Iter35a → Iter38c) déplacé dans `/app/memory/CHANGELOG.md`._

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

**P1.1 — Onglet "Jours fériés" dans configuration paie (GRH)**
- Ajouter un onglet "Jours fériés" dans le module GRH/HR (à côté de Personnel, Salaires, Taxes, Absences, etc.)
- CRUD liste de jours fériés : date, libellé, type (national/religieux/local), payé/non payé.
- Bouton "Importer les fêtes de l'année" qui peuple automatiquement la liste pour l'année en cours selon le pays défini dans `tenant_meta.company_country` (défaut Burkina Faso).
- Liste **éditable** : possibilité de modifier les dates en cours d'année (les fêtes musulmanes mobiles bougent chaque année).
- Pré-peupler avec les jours fériés du Burkina Faso connus : 1er janvier (Nouvel an), 11 mars (Soulèvement populaire 1966 — selon source), 1er mai (Fête du travail), 5 août (Indépendance), 15 août (Assomption), 1er novembre (Toussaint), 11 décembre (Proclamation République), 25 décembre (Noël), + fêtes musulmanes mobiles (Aïd el-Fitr, Aïd el-Kébir, Mawlid).
- Backend : nouvelle collection `hr_holidays` + endpoints `GET/POST/PATCH/DELETE /api/hr/holidays`.
- Impact paie : si un employé prend une absence sur un jour férié, soit ne pas le déduire, soit le surligner dans la fiche.

**P1.2 — Dépenses caisse : tiers OU employé**
- Modifier le module Caisse → Dépenses pour permettre de choisir entre "Tiers libre" et "Employé" lors de la création.
- Si "Employé" : dropdown des employés du tenant (réutiliser le composant déjà créé dans `HumanResources.jsx`).
- Quand l'expense est créée pour un employé et qu'elle dépasse le délai de justification (72h) :
  - ✅ Rappel dans le chat direct (DÉJÀ FAIT — Iter38c)
  - ➕ Ajouter le rappel sur **l'écran de bienvenue** de l'utilisateur (dashboard portail)
  - ➕ Ajouter le rappel sur **son chat direct** (notification badge dans la sidebar Chat)
- Backend : étendre `cashier_expenses` collection avec champ `employee_id` (FK vers hr_employees) + endpoint qui retourne la liste des dépenses en retard pour `user_id` courant.

**P1.3 — Aperçu/Relance message WhatsApp pour Reçus/Factures/Proformas**
- Sur chaque ligne reçu/facture/proforma dans CashBilling.jsx (et ReceiptPrint.jsx / InvoicePrint.jsx), ajouter un bouton "📩 Aperçu envoi WhatsApp" qui ouvre un modal montrant :
  - Module utilisé (WhatsApp Cloud API / fallback wa.me)
  - Numéro destinataire (E.164)
  - Statut dernier envoi (OK / KO + erreur)
  - Date du dernier envoi
  - Preview du message (template name + variables, ou texte)
  - **Bouton "Renvoyer le message"** si non-distribué ou destinataire se plaint
- Accessible aux rôles : Admin, Superviseur, et **Caissier** (nouveau — actuellement seulement Admin/Superviseur).
- Backend : étendre l'endpoint `GET /api/cashier/receipts/{id}` et `GET /api/cashier/invoices/{id}` pour inclure `whatsapp_last_*` fields (déjà persistés via Iter38e B.1). Ajouter endpoint `POST /api/cashier/receipts/{id}/resend-whatsapp` (idempotent).

**P1.4 — (déjà fait, juste à confirmer)**
- ~~Fix bug ArrowDown not defined dans UnifiedInbox.jsx~~ ✅ FAIT (Iter38l)
- ~~Fix dropdown "Comptable" manquant dans AdminTrackedUsers + AdminContacts~~ ✅ FAIT (Iter38l)
- ~~Implémentation Sora 2 (génération vidéo) dans MediaGenerator~~ ✅ FAIT (Iter38l)

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
