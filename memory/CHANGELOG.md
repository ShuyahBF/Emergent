# 📒 SAWALI SMART SYSTEMS — Journal des évolutions

> **Document de synthèse** consultable et exportable.
> Toutes les itérations livrées sur ce CRM/Portail, classées par date, avec leurs réalisations, leurs suggestions et leurs prochaines actions.
> Disponible aussi en ligne dans **Admin → Paramètres → 📒 Journal des évolutions** (avec bouton « Télécharger »).

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

## 📥 Comment exporter ce document

- **Depuis l'application** : Admin → Paramètres → « 📒 Journal des évolutions » → bouton **« Télécharger (Markdown) »**
- **Depuis le code** : fichier `/app/memory/CHANGELOG.md`
- **Endpoint API** (admin authentifié) : `GET /api/admin/changelog`

---

*Dernière mise à jour : 2026-05-10*
