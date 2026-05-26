# PRD — SAWALI SMART SYSTEMS Portal

## Original Problem Statement
Construit moi un site web, qui s'affiche bien sur toutes les types de terminaux (ordinateur PC, tablettes et téléphone). Site professionnel de SAWALI SMART SYSTEMS avec accès public (missions, expérience, spécialisation, catalogue, demande de RDV, contact) et espace professionnel (login, mot de passe, captcha, OTP mobile, état du compte, RDV, documentation logiciels, historique interventions, suivi utilisateurs).


_⚠️ Historique récent (Iter35a → Iter38) déplacé dans `/app/memory/CHANGELOG.md`._

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
- Actuellement >19 300 lignes — devient critique pour maintenabilité.
- Modules déjà extraits : `cashier.py` (2542 lignes), `hr.py` (375 lignes), `internal_chat.py`, `sms_dashboard.py`.

### 🟧 P0 — GRH Phases 4-6 (à reprendre après déploiement actuel + A/B)
- **Phase 4** : Absences/Déductions (jours/heures d'absence, seuils admin avant déduction).
- **Phase 5** : Taxes fiscales (5 configurables, global tenant avec override par employé) + Avances sur salaire (motifs).
- **Phase 6** : Synthèse mensuelle PDF (paie par employé ou par entreprise).

### 🟧 P0 — Cashier Trash UI (A.3) — UI en attente
- Backend complet (soft-delete + restore + permanent delete).
- Frontend `CashBilling.jsx` : ajouter toggle "Afficher la corbeille" + boutons restore/delete permanent.

### 🟧 P1 — B-list (à faire après déploiement actuel)
- **B.1** Indicateur résultat envoi WhatsApp (OK/KO toast après dispatch template).
- **B.2** Date "dernière utilisation" produit (basée sur **toute facture payée**, hors proformas).
- **B.3** Upload/génération AI icône PNG produit + toggle export catalogue public.
- **B.4** Auto-scroll bas pour WA Chat + Internal Chat.

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
