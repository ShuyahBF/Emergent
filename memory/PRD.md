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
✅ **Rôles utilisateur suivi (enum)** : Consultation / Edition / Moderation / Administrateur / Superviseur. Validation backend. Liste exposée via GET /admin/meta/tracked-roles. Note UI : seul Superviseur a accès aux Paramètres (gating à appliquer côté front quand login tracked-user sera ouvert).
✅ **Filtre + groupement par client** sur /admin/tracked-users. Colonne "Mis à jour".
✅ **Code client** (`client_code`) sur les fiches clients (utilisé pour la numérotation des interventions).
✅ **Numérotation des interventions** : `INT-AAAA-CODE-NNNN` séquentiel par (client_id, année). Compteurs dans `db.counters`.
✅ **Webhook Interventions** : à chaque create/update, POST fire-and-forget vers `{base_url}/{action}/{client_code}/{numero}` avec body JSON intervention complète. Auth : Aucune | Bearer | Basic. UI dans /admin/settings.
✅ **Horodatages** : `created_at` + `updated_at` sur Interventions, Clients, Tracked Users (les autres collections les avaient déjà).

## Test Credentials
- Admin: `admin@sawalismartsystems.com` / `Admin@Sawali2026` (auto-seeded)

## Backlog (P1/P2)
- P1 : Connecter SMTP (Gmail App Password) pour réellement envoyer les OTP
- P1 : Connecter Google reCAPTCHA (créer clés site/secret)
- P1 : Connecter Google Calendar (créer projet GCP, OAuth 2.0 client, autoriser le compte sup.alphasofti@gmail.com)
- P2 : Editeur Rich Text plus complet (TipTap) au lieu de l'éditeur HTML basique
- P2 : Notifications email/SMS lors d'un RDV (statut changements)
- P2 : Pagination & recherche avancée sur les listes admin
- P2 : Export CSV des interventions / RDV
