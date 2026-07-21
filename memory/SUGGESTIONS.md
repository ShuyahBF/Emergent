# Registre des suggestions — SAWALI Smart Systems CRM

Toutes les suggestions d'amélioration proposées par l'assistant IA durant la vie du projet, avec numérotation unique persistante (S001, S002, …).
Ce fichier est mis à jour à chaque nouvelle suggestion ou changement de statut.

## Légende des statuts
- 🟢 **IMPLÉMENTÉE** — feature livrée, testée et en production / preview
- 🟡 **ACCEPTÉE** — validée par l'utilisateur, en cours de développement
- 🔵 **PROPOSÉE** — suggestion formulée, en attente de décision
- ⚪ **DIFFÉRÉE** — acceptée mais reportée
- 🔴 **REFUSÉE** — explicitement écartée par l'utilisateur

## Convention de numérotation
- ID immuable : `S` + 3 chiffres (S001, S002, … S999)
- Une suggestion peut générer plusieurs fonctionnalités → ID parent + bullet enfants
- Référencer dans le code via commentaire : `# Suggestion S008 — bouton Appliquer le plan IA`

---

## S001 — Onglet « Conversion en ligne » sur le rapport public + widget Renouveler la campagne
- **Proposée le** : 2026-05-31 (après fix9z4)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z5
- **Détail** : Graphique 30j d'impressions vs clics + widget « Renouveler la campagne » pré-rempli, accessible depuis `/ads/{slug}?token=…`
- **Bénéfice** : boucle le funnel publicitaire — l'annonceur peut renouveler en 1 clic
- **Fichiers** : `PublicAdReport.jsx` (`ConversionTrend` + `RenewCampaignWidget`), `ad_banners.py` (endpoint `/renew`)

## S002 — Test A/B sur les bannières
- **Proposée le** : 2026-05-31 (après fix9z5, suggestion P5 du backlog)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z6
- **Détail** : 2 variantes par bannière (média + URL cible distincts), rotation 50/50 à chaque affichage, stats séparées, badge GAGNANTE automatique au-delà de 30 affichages par variante
- **Bénéfice** : justifie un prix premium par campagne (optimisation continue) — vend à plus cher
- **Fichiers** : `ad_banners.py` (champs `ab_enabled`/`variant_b_*`, endpoints variant=a/b), `AdminAdBanners.jsx` (`BannerABBlock` + `ABBreakdown`)

## S003 — Email automatique de rappel d'expiration de campagne
- **Proposée le** : 2026-05-31 (après fix9z5)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z6
- **Détail** : Cron 09h30 Africa/Abidjan envoie un email N jours avant l'expiration (1-30, défaut 3) avec bilan campagne + lien renouvellement
- **Bénéfice** : best practice régies pub — 30-40% des fins de campagne transformées en renouvellements
- **Fichiers** : `ad_banners.py` (`process_expiration_reminders`), `server.py` (cron `_scheduled_ad_banner_reminders`)

## S004 — Notification WhatsApp en plus de l'email pour le rappel
- **Proposée le** : 2026-05-31 (backlog après fix9z6)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z7
- **Détail** : Réutilise `_wa_send_text` ; toggle indépendant de l'email ; un annonceur peut activer email seul, WA seul, ou les deux
- **Bénéfice** : touche les annonceurs qui ne lisent pas leurs emails — taux d'ouverture WA bien supérieur en Afrique
- **Fichiers** : `ad_banners.py` (`send_whatsapp_fn` injecté), `AdminAdBanners.jsx` (toggle `reminder_wa_enabled`)

## S005 — Dashboard temps-réel des bannières actives (WebSocket)
- **Proposée le** : 2026-05-31 (backlog après fix9z6)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z7
- **Détail** : WebSocket `/api/ws/ad-banners-live` diffuse snapshot initial + events impression/click à chaque hit public ; panel live en haut de `/admin/ad-banners` avec compteurs animés et feed des 5 derniers événements
- **Bénéfice** : feedback instantané pour l'admin lors de campagnes intensives (events, lancements produit)
- **Fichiers** : `ad_banners.py` (`AdLiveHub` + endpoint WS), `AdBannersLivePanel.jsx`

## S006 — Portail libre-service annonceur (paiement Stripe + maj média sans login)
- **Proposée le** : 2026-05-31 (après fix9z6)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z8
- **Détail** : 3 endpoints publics validés par slug+token — paiement Stripe (extension auto expiration + crédit budget atomique) + mise à jour média (whitelist stricte) + status polling
- **Bénéfice** : transforme la régie pub en SaaS auto-service — libère le temps admin
- **Fichiers** : `ad_banners.py` (`/checkout`, `/payment-status`, `/media`), `PublicAdReport.jsx` (`OnlineRenewalCheckout` + `SelfServiceMediaUpdate`)

## S007 — Plan de campagne IA (Claude Haiku 4.5)
- **Proposée le** : 2026-05-31 (après fix9z8)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : fix9z9
- **Détail** : Endpoint analyse les stats (CTR, A/B, budget) et renvoie 4 recommandations (visuel, slogans, budget optimal, justification). Cache 6h.
- **Bénéfice** : option premium facturable (+30% du coût campagne) — l'annonceur reçoit un audit marketing instantané
- **Fichiers** : `ad_banners.py` (endpoint `/ai-plan`), `PublicAdReport.jsx` (`AICampaignPlan`)

## S008 — Bouton « Appliquer le plan IA » en 1 clic
- **Proposée le** : 2026-05-31 (après fix9z9)
- **Statut** : 🔵 PROPOSÉE
- **Détail** : Combiner les 3 étapes du plan IA en 1 action : (1) génération visuel via Gemini Nano Banana → upload → maj `image_url` ; (2) maj `target_url` avec slogan choisi ; (3) checkout Stripe pré-rempli avec budget recommandé
- **Bénéfice** : 20 min → 30 sec — taux de conversion renouvellement nettement supérieur
- **Dépendances** : génération directe Gemini depuis le client public (anonyme) — pose une question de coût IA à protéger

## S009 — Auto-déconnexion par inactivité
- **Demande directe utilisateur** : 2026-05-31
- **Statut** : 🟡 ACCEPTÉE (en cours d'implémentation)
- **Fix associé** : fix9z10
- **Détail** : Délai configurable 5-10-15-30 min via `/admin/settings`. Modal de warning 30s avant la déconnexion avec bouton « Rester connecté ». À expiration → logout auto + toast « Session expirée par inactivité ».
- **Bénéfice** : sécurité — empêche les sessions ouvertes oubliées en fin de journée
- **Fichiers** : `useIdleTimer.js` (frontend hook), `AuthContext.jsx` (intégration), `AdminSettings.jsx` (paramètre)

## S010 — Carte Liluvine visible par les modérateurs sur l'écran de bienvenue
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39a
- **Détail** : Le compteur « WhatsApp pris en charge par Liluvine aujourd'hui » s'affichait à 0 pour les utilisateurs avec `tracked_role="Moderation"` car le calcul utilisait `user.id` (UUID du tracked-user) au lieu du `parent_client_id` du tenant. Bascule sur `_resolve_visible_client_ids(user)` pour couvrir admin/superviseur/moderateur/clients suivis.
- **Bénéfice** : les modérateurs voient enfin le ROI de Liluvine PRO sur leur écran d'accueil
- **Fichiers** : `backend/server.py:_build_liluvine_autoreply_stats`, test `test_siter39a_moderator_liluvine_and_link.py`

## S011 — Édition du « Client lié canonique » depuis la fiche d'un tenant
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39a
- **Détail** : Nouveau menu déroulant « Client lié canonique » dans la fiche d'édition d'un compte (Admin → Clients). Permet à Admin/Superviseur de rattacher/détacher un compte d'un client parent. Met à jour `parent_client_id` + `client_id` côté backend ; la nouvelle valeur se propage automatiquement à toutes les UI (Centre Messagerie header, Contacts, briefing, RGPD, facturation WhatsApp…). Validations : refus self-link, 404 si canonique introuvable, chaîne vide = détacher.
- **Bénéfice** : corrige rapidement les anciens rattachements erronés sans recréer le compte
- **Fichiers** : `backend/models.py:UserUpdateAdmin`, `backend/server.py:admin_update_client`, `frontend/src/pages/admin/AdminClients.jsx` (dropdown `link-to-client-section`)

## S012 — Bug fix : modal de consultation de tâche affichait du vide
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39b
- **Détail** : Le viewer de tâches lisait uniquement `content_html` (legacy). Les tâches ayant migré vers le format `task_items[]` (Google-Keep-style checklist) restaient donc vides. Ajout du rendu de la checklist (avec compteur fait/total) dans le modal `viewing`.
- **Fichiers** : `frontend/src/pages/portal/UserNotes.jsx` (viewer modal)

## S013 — Brochures & Guides visibles aux modérateurs (lecture en ligne)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39b
- **Détail** : Nouvelle entrée sidebar « Brochures & Guides » pour les tracked_role="Moderation". Téléchargement masqué sauf Admin/Superviseur ; à la place les modérateurs cliquent sur « Consulter en ligne » qui ouvre la visionneuse PDF interne.
- **Fichiers** : `frontend/src/components/PortalLayout.jsx` (gate `moderationOnly`), `frontend/src/components/BrochuresWidget.jsx` (canSee inclut Moderation), nouvelle page `frontend/src/pages/portal/PortalBrochures.jsx`

## S014 — Visionneuse PDF interne (recherche + sommaire + zoom)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39b
- **Détail** : Composant `<PdfViewer>` basé sur react-pdf 9 + pdf.js 4. Fonctions : navigation page, zoom +/-, sommaire cliquable (TOC pdf.js outline), recherche plein-texte avec aperçu (jusqu'à 200 occurrences). Téléchargement gated par rôle (admin/superviseur uniquement) + désactivation du menu contextuel + interception Ctrl/Cmd+S. Bandeau « Lecture en ligne uniquement » affiché aux autres.
- **Bénéfice** : permet de partager brochures/guides/PV en lecture seule, anti-fuite documentaire
- **Fichiers** : `frontend/src/components/PdfViewer.jsx` (nouveau), utilisé dans `PortalBrochures.jsx` + `MeetingMinutes.jsx`

## S015 — PV de réunions internes (autonumérotés + impression + PDF)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39b
- **Détail** : Nouveau module `/portal/meetings`. Backend `routes/meetings.py` (CRUD + export PDF reportlab). Numérotation `PV-YYYY-NNN` atomique par tenant et par année. Éditeur riche (réutilise `RichEditor` de UserNotes avec bouton **Dicter** Whisper). `ended_at` fixé automatiquement au clic « Enregistrer ». Suppression réservée admin/superviseur ; édition autorisée à l'auteur + admin/sup. PDF généré à la volée avec table récap (Titre/Date/Début/Fin/Auteur/Participants) + corps HTML nettoyé.
- **Bénéfice** : centralisation des PV, recherche, archivage, traçabilité
- **Fichiers** : `backend/routes/meetings.py` (nouveau), `frontend/src/pages/portal/MeetingMinutes.jsx` (nouveau), entrée sidebar dans `PortalLayout.jsx`
- **Tests** : `backend/tests/test_siter39b_meetings.py` (CRUD + PDF + autonumérotation + soft-delete + auth)

## S016 — Liluvine PRO : filtre « 3 dernières conversations » + Reprendre pour modérateurs
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39b
- **Détail** : Nouvelle bascule « 🕒 3 dernières conversations » TOUJOURS visible dans la sidebar Liluvine PRO. Tri par `updated_at desc` + slice(0,3). Côté RBAC : ajout de `moderation` et `administrateur` (valeurs réelles stockées en DB) à `_TAKEOVER_ROLES` côté backend ET à `canTakeover` côté frontend → un modérateur (tracked_role="Moderation") peut maintenant cliquer sur le bouton **Reprendre** (qui était silencieusement rejeté en 403 avant).
- **Bénéfice** : accès rapide aux conversations en cours pour la prise en main par les modérateurs
- **Fichiers** : `frontend/src/pages/portal/LiluvinePro.jsx`, `backend/routes/liluvine_pro.py:_TAKEOVER_ROLES`
- **Tests** : `backend/tests/test_siter39b_takeover_moderator.py`

## S017 — Signature électronique du PV (verrouillage post-signature)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39c
- **Détail** : Bouton « Valider et signer » (admin/superviseur uniquement) sur la fiche d'un PV. À la signature : `signed_at` / `signed_by_id|name|email` sont persistés, le PUT et le DELETE renvoient **HTTP 423 LOCKED**, l'édition est masquée côté UI, et un bandeau emerald « PV signé électroniquement par … le … » apparaît dans le PDF généré ainsi qu'un badge SIGNÉ sur la carte. Annulation possible (admin/sup) via « Annuler la signature » → le PV redevient modifiable. Rejet 403 pour les modérateurs non-admins. Signature idempotente.
- **Bénéfice** : valeur légale (PV opposable, anti-falsification), traçabilité
- **Fichiers** : `backend/routes/meetings.py` (POST `/sign` + `/unsign` + verrou PUT/DELETE + bloc PDF signature), `frontend/src/pages/portal/MeetingMinutes.jsx` (badge SIGNÉ, boutons sign/unsign, masquage des actions verrouillées)
- **Tests** : `backend/tests/test_siter39c_sign_meeting.py` (cycle sign/lock/unsign + idempotence + modérateur refusé + PDF — 2/2 verts)

## S018 — Signataires obligatoires (ligne 1) + Participants (ligne 2) via dropdowns d'utilisateurs du tenant
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 1 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : 2 nouveaux multi-select dropdowns dans l'éditeur PV — alimentés par le nouvel endpoint `GET /api/me/tenant-users` (users + tracked du tenant). Ligne 1 = signataires obligatoires (signature requise). Ligne 2 = autres participants (sans signature). Les listes sont disjointes : un id ajouté en ligne 1 est retiré automatiquement de la ligne 2. Signature : si la liste de signataires est non vide, seul un user présent dans cette liste peut signer (sinon 403). PDF montre les 2 lignes en clair avec résolution id → nom (full_name / email).
- **Bénéfice** : PV formels avec signataires identifiés (président, secrétaire, …)
- **Fichiers** : `backend/routes/meetings.py` (MeetingCreate/Update + sign check), `backend/server.py` (`GET /api/me/tenant-users`), `frontend/src/pages/portal/MeetingMinutes.jsx` (composant `MultiUserPicker` réutilisable)
- **Tests** : `backend/tests/test_siter39d_eight_features.py::test_pv_signers_persistence_and_sign_check`

## S019 — Liluvine PRO Historique accessible aux modérateurs
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 2 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : Nouvelle route `/portal/liluvine-history` (miroir de `/admin/liluvine-history`) accessible aux modérateurs (gate `moderationOnly`). RBAC élargi : `TAKEOVER_ROLES` côté frontend de la page Historique inclut désormais `moderation`/`administrateur`.
- **Fichiers** : `frontend/src/App.js`, `frontend/src/components/PortalLayout.jsx`, `frontend/src/pages/admin/AdminLiluvineHistory.jsx`

## S020 — Bug fix : modal Bienvenue + auto-déconnexion ne ferme pas la page
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 3 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : Quand la modal WelcomeBriefing était ouverte et l'idle timer expirait, `navigate("/login")` ne démontait pas correctement les modales persistantes (Welcome briefing rendu dans PortalLayout). Bascule sur `window.location.assign("/login")` qui force le démontage complet de l'arbre.
- **Fichiers** : `frontend/src/components/AutoLogoutGate.jsx`

## S021 — Registre des suggestions consultable depuis l'UI admin
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 4 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : Nouvelle page `/admin/suggestions` (lecture seule) qui rend `/app/memory/SUGGESTIONS.md` avec rendu markdown basique (titres, listes, gras, code inline). Endpoint backend `GET /api/admin/suggestions-registry` retourne le markdown brut + taille + mtime. Bouton Copier (clipboard) + Rafraîchir.
- **Fichiers** : `backend/server.py` (endpoint), `frontend/src/pages/admin/AdminSuggestionsRegistry.jsx`, lien sidebar dans `PortalLayout.jsx`
- **Tests** : `backend/tests/test_siter39d_eight_features.py::test_suggestions_registry`

## S022 — Centre de Messagerie trié par dernier contact WA/SMS (par défaut)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 5 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : Le sélecteur de tri par défaut bascule sur « Dernier contact récent » au lieu de « Tri par défaut ». Le endpoint backend `/admin/messaging/audience` est enrichi avec `last_message_at` calculé sur les collections `wa_messages` + `sms_messages` (best-effort, fuzzy match sur les 10 derniers digits du téléphone).
- **Bénéfice** : les contacts récemment importés ou contactés remontent automatiquement en tête de liste
- **Fichiers** : `backend/server.py:admin_messaging_audience`, `frontend/src/pages/admin/AdminMessaging.jsx`
- **Tests** : `backend/tests/test_siter39d_eight_features.py::test_messaging_audience_has_last_message_at`

## S023 — Jauge circulaire animée entre chaque chargement de page
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 7 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : Nouveau composant `<GlobalRouteLoader>` monté à la racine. S'affiche au changement de route (`useLocation`) ET dès qu'une requête backend est en vol (axios interceptors sur `apiClient`). Courbe de progression asymptotique vers 90 % puis 100 % à la réponse. Anti-flicker (MIN_VISIBLE_MS = 350 ms).
- **Bénéfice** : feedback visuel constant sur connexions lentes
- **Fichiers** : `frontend/src/components/GlobalRouteLoader.jsx`, monté dans `frontend/src/App.js`

## S024 — Vidéos/bannières publiques : toggle son activable/désactivable
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE (item 8 du paquet S-iter39d)
- **Fix associé** : siter39d
- **Détail** : Bouton volume sur les bannières vidéo (data-testid `ad-banner-sound-toggle-{id}`). Démarre muet (contrainte autoplay navigateur) mais un seul clic active le son et l'état est mémorisé en `sessionStorage`. Sur les chargements suivants la vidéo respecte la préférence utilisateur.
- **Note** : Les navigateurs (Chrome/Safari/Firefox) bloquent l'autoplay non-muté. On démarre muté pour respecter cette contrainte, l'utilisateur unmute en 1 clic.
- **Fichiers** : `frontend/src/components/AdBannerSlot.jsx`

## S025 — Workflow d'approbation pour télécharger des documents (✅ IMPLÉMENTÉE)
- **Demande directe utilisateur** : 2026-02 (post-handoff) — option (a) template Meta privilégiée
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39e
- **Détail** :
  - Admin/Superviseur → bypass direct (téléchargement immédiat).
  - Non-admin → `POST /me/download-requests` crée une approbation en `pending`, envoie WA :
    - **Si template Meta configuré** (`download_approval_template_name`) → message interactif avec 2 boutons `QUICK_REPLY` ; payloads `download_approve_{token}` et `download_deny_{token}` interceptés par le webhook Meta.
    - **Sinon** → fallback texte avec 2 magic links cliquables (variables `{requester}`, `{label}`, `{approve}`, `{deny}`).
  - Frontend `<DownloadGate>` + hook `useDownloadGate()` : jauge circulaire animée (gradient bleu→fuchsia) + polling toutes 2 s.
  - Statuts terminaux : `approved` (téléchargement déclenché), `denied` (toast « Désolé, l'opération n'a pas été confirmée »), `expired` (24 h sans réponse), `cancelled` (annulé par le demandeur).
  - Public endpoint `GET /api/wa-action/{token}/{approve|deny}` (HTML page de confirmation) pour le fallback magic links.
- **Configuration** : nouvelle section `Sécurité — Approbation WhatsApp pour téléchargements (S025)` dans `/admin/settings` (anchor `s-download-approval`).
- **Fichiers** : `backend/routes/download_approvals.py` (nouveau), `backend/models.py:SettingsUpdate` (6 nouveaux champs), `backend/server.py` (webhook hook + notifier + router mounting), `frontend/src/components/DownloadGate.jsx` (nouveau), `frontend/src/pages/portal/PortalBrochures.jsx` (wire to gate), `frontend/src/pages/admin/AdminSettings.jsx` (config UI).
- **Tests** : `backend/tests/test_siter39e_approval_signers_docs.py::test_*` (admin bypass + magic-link approve/deny/cancel + settings validation — 4/4 verts).

## S026 — Notification automatique des signataires de PV (Email + WhatsApp)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39e
- **Détail** : À la création d'un PV avec signataires obligatoires déclarés (ligne 1 du formulaire), chaque signataire reçoit une notification l'invitant à consulter et signer le document. **Canal paramétrable globalement par l'admin** :
  - `none` (par défaut) — aucune notification
  - `email` — uniquement par email
  - `wa` — uniquement par WhatsApp
  - `both` — email + WhatsApp
- Le contenu inclut : numéro du PV, titre, date de réunion, auteur, lien vers `/portal/meetings/{id}`.
- Échecs d'envoi (SMTP/WA indisponibles) n'interrompent jamais la création du PV.
- **Configuration** : nouvelle section `PV de réunions — Notification automatique des signataires (S026)` dans `/admin/settings` (4 boutons : Aucun / Email / WhatsApp / Les deux).
- **Fichiers** : `backend/routes/meetings.py` (signers_notifier dependency), `backend/server.py` (`_meeting_signers_notifier`), `backend/models.py:SettingsUpdate.meeting_signers_notify_channel`, `frontend/src/pages/admin/AdminSettings.jsx`.

## S027 — Référence technique PDF des paramètres AdminSettings
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39e
- **Détail** : Nouveau PDF généré `D_Documentation_Technique_AdminSettings.pdf` (26 KB) liste **toutes les sections** de la page Admin → Paramètres et tous les **paramètres** exposés (nom, type, description courte) **SANS les valeurs** — sert de guide d'auto-remplissage. Téléchargeable via `/api/public/docs/admin-settings-reference`, visible dans BrochuresWidget et PortalBrochures (carte violet/indigo).
- **Sections documentées** : Identité, URL publique, S025 Approbation, S026 Signataires PV, Briefing bienvenue, Caisse, Caissier RBAC, PawaPay, Stripe, SMTP, WhatsApp Cloud, SMS, Liluvine PRO, Régie publicitaire, Object Storage, Voice Notifications, Audit sécurité, RGPD, Webhooks, OpenAI/Gemini/Claude, Quotas IA, Voice Studio, Meta, Google, Suggestions, Diagnostics (24 sections).
- **Fichiers** : `docs/generate_admin_settings_doc.py` (nouveau), `backend/routes/public_docs.py` (slug `admin-settings-reference`), `frontend/src/components/BrochuresWidget.jsx` + `frontend/src/pages/portal/PortalBrochures.jsx` (META).
- **Régénération** : bouton dédié dans Admin → Paramètres / depuis Brochures, ou commande `python /app/docs/generate_admin_settings_doc.py`.

## S028 — Vidéos publiques : son activé au démarrage (auto-unmute au 1er geste)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39e
- **Détail** : Les bannières vidéo démarrent mutées (contrainte autoplay des navigateurs Chrome/Safari/Firefox) puis sont **automatiquement réactivées dès le premier geste de l'utilisateur sur la page** (click / touchstart / keydown) via des event listeners passifs avec `{ once: true }`. Si l'utilisateur clique explicitement sur l'icône volume pour muter, sa préférence est mémorisée en `sessionStorage` et l'auto-unmute n'a plus lieu.
- **Bénéfice** : son effectivement activé dès que le visiteur interagit, sans frustrer l'expérience par un autoplay sonore intrusif (qui serait bloqué par le navigateur).
- **Fichiers** : `frontend/src/components/AdBannerSlot.jsx`

## S029 — Journal d'audit des demandes de téléchargement
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39f
- **Détail** : Nouvelle page admin `/admin/download-audit` qui liste TOUTES les demandes d'approbation de téléchargement (S025). Pour chaque demande : date, demandeur, document, status final, date de décision, canal (bouton template Meta / lien magique / override admin), numéro de l'approbateur, statut d'envoi WhatsApp. Filtre par status (5 KPI cards cliquables + bouton « Tout »), recherche plein-texte sur demandeur/document. Backend endpoint `GET /api/me/download-requests/admin/audit` (admin/sup uniquement, 403 sinon, 500 lignes max).
- **Bénéfice** : traçabilité opposable des accès aux documents confidentiels, audit de conformité
- **Fichiers** : `backend/routes/download_approvals.py` (endpoint `admin_audit`), `frontend/src/pages/admin/AdminDownloadAudit.jsx` (nouveau), entrée sidebar admin dans `PortalLayout.jsx`, route dans `App.js`
- **Tests** : `backend/tests/test_siter39f_audit.py` (counters + filtres status/q + 400 status invalide + 403 modérateur — 2/2 verts)

## S031 — Bannière d'alerte « Universal Key Emergent épuisée » (super-admin)
- **Demande directe utilisateur** : 2026-02 (post-handoff) — restreint à `admin@sawalismartsystems.com`
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39g
- **Détail** : Monitoring temps réel de la santé Universal Key :
  - Helper `record_llm_outcome(db, ok, error)` appelé après chaque appel LLM (intégré dans `liluvine_pro.py` chat + `liluvine_wa_autoreply.py`).
  - Regex `BUDGET_ERROR_RE` détecte l'erreur exacte d'Emergent (« Budget has been exceeded! Current cost: X, Max budget: Y ») → extrait les chiffres + bascule en status `budget_exceeded`.
  - Détecte aussi `key_missing` (EMERGENT_LLM_KEY absente) et `unknown_error`.
  - Cron 15 min : `ping_emergent_llm` envoie un message minimaliste à Claude Haiku 4.5 → mise à jour automatique du status (rétablit l'état `ok` dès recharge).
  - Email quotidien (throttlé 23 h) à `admin@sawalismartsystems.com` tant que le status reste `budget_exceeded`.
  - Bannière sticky en haut du portail (gradient ambre→rose, animation pulse) avec : titre + chiffres `cost/max`, instructions de recharge, bouton « Re-tester » (ping immédiat), bouton dismiss (jusqu'au prochain check 15 min).
  - **Visible uniquement pour `admin@sawalismartsystems.com`** (gate frontend strict sur l'email).
- **Endpoints** : `GET /api/admin/llm-health` (state) + `POST /api/admin/llm-health/ping` (force probe).
- **Fichiers** : `backend/routes/llm_health.py` (nouveau), wrappers dans `backend/routes/liluvine_pro.py` + `backend/routes/liluvine_wa_autoreply.py`, cron dans `backend/server.py`, `frontend/src/components/LlmHealthBanner.jsx` (nouveau), monté dans `frontend/src/App.js`.
- **Tests** : `backend/tests/test_siter39g_llm_health.py` (regex parsing + admin read + 403 non-admin + state transitions + ping endpoint — 5/5 verts).

## S032 — Vitesse de consommation Universal Key + alertes proactives (80% / 95%)
- **Demande directe utilisateur** : 2026-02 (post-handoff) — « oui va avec s032 »
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39h
- **Détail** : Anticipe l'épuisement de la Universal Key Emergent en mesurant la vitesse de consommation et en alertant l'admin **avant** la coupure :
  - **Source double** : (a) Chaque appel LLM appelle `record_llm_outcome(..., context=...)` qui ajoute une ligne dans `llm_usage_log` avec coût estimé par contexte (`liluvine_chat`=$0.004, `wa_autoreply`=$0.002, `health_probe`=$0.0001, etc. — basé sur la grille de tarifs Claude Haiku 4.5). (b) Lorsque Emergent renvoie une erreur de budget, la valeur réelle `current_cost` est extraite et utilisée comme vérité terrain.
  - **Fonction `compute_metrics(db)`** : agrège `llm_usage_log` sur 24h et 1h + cumul mensuel, calcule `pct_used = cost/max`, projette la date d'épuisement (`projected_days_left`) et classe l'état en `ok` / `warning` / `critical` / `exhausted` / `error`.
  - **Bannière 4 niveaux** : la `LlmHealthBanner` change de couleur selon `status_level` (ambre/orange/rose) et affiche en mode warning/critical la vitesse 24h, la projection d'épuisement et le nombre d'appels IA.
  - **Bannière restreinte** : visible uniquement pour `admin@sawalismartsystems.com` ET uniquement sur les routes `/admin/*` (gate `useLocation()`).
  - **Notifications proactives** : Email + WhatsApp (canaux configurables, throttle 23h par niveau) envoyés dès passage en `warning` (par défaut 80%) ou `critical` (par défaut 95%). WA via `_wa_send_text` (numéro super-admin configuré).
  - **Configuration admin** : Nouvelle section `Universal Key Emergent — Seuils de consommation & alertes (S032)` dans `/admin/settings` (anchor `s-llm-budget-thresholds`) — 6 paramètres : `llm_budget_warning_pct`, `llm_budget_critical_pct`, `llm_budget_max_usd`, `llm_budget_notify_email`, `llm_budget_notify_wa`, `llm_budget_notify_wa_phone`. Validation stricte côté backend (50≤warn≤99, 60≤crit≤99, warn<crit, max>0).
- **Bénéfice** : élimine les coupures surprises du service IA — l'admin reçoit un préavis suffisant pour recharger la clé.
- **Endpoints** : `GET /api/admin/llm-health` enrichi des 13 nouveaux champs S032 (burn_rate_24h_usd, burn_rate_1h_usd, calls_24h, cumulative_month_usd, current_cost_usd, max_budget_usd, pct_used, projected_days_left, projected_exhaustion_at, warning_pct, critical_pct, status_level, cost_source).
- **Fichiers** : `backend/routes/llm_health.py` (compute_metrics + maybe_send_budget_warning_alerts), `backend/models.py:SettingsUpdate` (6 nouveaux champs), `backend/server.py` (validation + cron updated), `backend/routes/liluvine_pro.py` + `liluvine_wa_autoreply.py` (context propagé), `frontend/src/components/LlmHealthBanner.jsx` (4 niveaux visuels + métriques + gate `/admin/*`), `frontend/src/pages/admin/AdminSettings.jsx` (section S032).
- **Tests** : `backend/tests/test_siter39h_llm_burn_rate.py` (6/6 verts) — usage log + compute_metrics + bascule warning/critical/ok + endpoint exposes metrics + validation seuils + envoi email+WA + throttle 23h.

## S033 — Bouton « Tester maintenant » du solde Universal Key + requête WhatsApp par mot-clé
- **Demande directe utilisateur** : 2026-02 (post-handoff) — « Il me faut un bouton test pour interroger manuellement le solde restant de ma LLM key. Par action du bouton dans le AdminSettings à côté des paramètres ou par WhatsApp avec un numéro configurable »
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39i
- **Détail** : Deux modes de consultation à la demande du solde Universal Key Emergent :
  - **Mode 1 — Bouton dans AdminSettings (S032 section)** : Nouveau bouton « 🧪 Tester maintenant » dans `/admin/settings#s-llm-budget-thresholds`. Force un `ping_emergent_llm` (vérifie la clé est joignable) puis affiche un panneau récap avec : niveau (badge coloré OK/Avertissement/Critique/Épuisée), consommation USD, vitesse 24h, vitesse 1h, projection d'épuisement, seuils et source du coût. Le panneau contient également un `<details>` repliable montrant le texte WhatsApp exact qui serait envoyé en réponse à un déclencheur (mode 2 ci-dessous).
  - **Mode 2 — Requête WhatsApp par mot-clé** : Quand `llm_budget_wa_query_enabled=true`, le numéro autorisé (`llm_budget_notify_wa_phone`, déjà utilisé pour les alertes S032) peut envoyer le mot-clé (par défaut « SOLDE », configurable jusqu'à 32 caractères) au numéro WA du bot. Le webhook Meta intercepte le message AVANT persistance/auto-reply Liluvine et répond automatiquement avec le résumé du solde (même contenu que le bouton). Comparaison case-insensitive et tolérante aux différences de format (+ / 00 / leading zeros) via match sur les 10 derniers chiffres.
- **Bénéfice** : check du solde en 1 clic depuis l'admin OU en 1 message WhatsApp (utile en mobilité, sans ordinateur).
- **Endpoints** : `POST /api/admin/llm-health/test-summary` (force ping + retourne `summary_text` + métriques S032).
- **Settings** : `llm_budget_wa_query_enabled` (bool, default false), `llm_budget_wa_query_keyword` (str, default "SOLDE", uppercase auto, max 32 chars).
- **Fichiers** : `backend/routes/llm_health.py` (`build_budget_summary_text`, `handle_wa_budget_query`, endpoint `/test-summary`), `backend/server.py` (hook webhook WA inbound type=text + validation keyword), `backend/models.py:SettingsUpdate` (2 nouveaux champs), `frontend/src/components/LlmBudgetTestButton.jsx` (nouveau composant), `frontend/src/pages/admin/AdminSettings.jsx` (intégration section S032).
- **Tests** : `backend/tests/test_siter39i_budget_test_button.py` (6/6 verts) — endpoint `/test-summary` admin/non-admin + handler WA authorized/disabled/unauthorized phone + normalisation uppercase et validation longueur du keyword.

## S034 — Cockpit WhatsApp Admin (mini-menu de commandes mobiles)
- **Demande directe utilisateur** : 2026-02 (post-handoff) — « ok implémente S034 »
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39j
- **Détail** : Étend le déclencheur WhatsApp S033 en un véritable « cockpit mobile » pour l'admin. Le numéro autorisé peut envoyer l'un des mots-clés suivants (case-insensitive) au bot WhatsApp et reçoit instantanément un résumé formaté :
  - **`SOLDE` / `BUDGET`** → Consommation Universal Key (délégué à S032/S033 via `build_budget_summary_text`)
  - **`STATS` / `KPI`** → KPI temps réel sur 24h : WhatsApp reçus, WhatsApp envoyés, SMS envoyés, RDV du jour, tickets ouverts, contacts en base
  - **`INCIDENTS` / `TICKETS`** → Top 5 tickets ouverts (priorité 🔴/🟠/🟡/🔵 + numéro + titre + contact + date d'ouverture). Affiche un message rassurant « Aucun ticket ouvert » quand la liste est vide
  - **`AIDE` / `HELP` / `MENU`** → Menu listant toutes les commandes disponibles
  - L'authentification réutilise les mêmes garde-fous que S033 : (a) toggle master `llm_budget_wa_query_enabled` actif (b) numéro émetteur match sur les 10 derniers chiffres avec `llm_budget_notify_wa_phone`.
  - Les messages déclencheurs ne sont **ni stockés ni transmis à Liluvine PRO** (le webhook fait un `continue` immédiat).
- **Bénéfice** : véritable cockpit de supervision mobile — l'admin peut consulter l'état critique du système depuis n'importe où sans ouvrir un navigateur. Particulièrement utile lors de déplacements ou hors heures de bureau.
- **Fichiers** : `backend/routes/wa_admin_cockpit.py` (nouveau — dispatcher + builders STATS/INCIDENTS/HELP), `backend/server.py` (hook webhook remplace S033 par le dispatcher S034), `frontend/src/pages/admin/AdminSettings.jsx` (UI section S032 listant les 4 commandes + alias).
- **Tests** : `backend/tests/test_siter39j_wa_admin_cockpit.py` (8/8 verts) — HELP/STATS/INCIDENTS/BALANCE delegation + unknown keyword + master toggle off + unauthorized phone + tous les alias (BUDGET/KPI/TICKETS/HELP/MENU).

## S035 — Commandes d'action du Cockpit WhatsApp (fermeture ticket + mute alertes)
- **Demande directe utilisateur** : 2026-02 (post-handoff) — « ok implémente S035 »
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39k
- **Détail** : Étend le cockpit S034 avec des **commandes d'action** (et plus seulement de consultation) :
  - **`RESOLU #1234` / `FERMER #1234`** → Ferme le ticket de support dont le numéro est passé en argument. Match par `number` (regex case-insensitive) ou par `id` (UUID/préfixe). Le ticket bascule en `status="resolved"` + champs `resolved_at` / `closed_at` / `closed_by_wa` (téléphone E.164) / `closed_via="wa_cockpit_s035"`. Réponse différenciée si ticket introuvable / déjà clôturé.
  - **`MUTE` / `NOTIF STOP` / `NOTIF OFF`** → Persiste `settings.llm_alerts_muted_until` à `now + 24h`. Les alertes S031 (email épuisement) et S032 (warning/critical) honorent ce champ via le helper `alerts_are_muted(db)`.
  - **`UNMUTE` / `NOTIF ON` / `NOTIF START` / `NOTIF RESUME`** → Unset du champ `llm_alerts_muted_until`. Les alertes reprennent au prochain cron 15 min.
  - Menu `AIDE` mis à jour avec les nouvelles sections « Consultation » et « Actions ».
  - L'auth reste identique à S034 (toggle + match 10 derniers chiffres).
- **Bénéfice** : permet à l'admin de gérer son CRM en mobilité — fermer un incident ou couper temporairement les alertes pendant une réunion, depuis un simple message WhatsApp.
- **Fichiers** : `backend/routes/wa_admin_cockpit.py` (regex `RE_CLOSE_TICKET`/`RE_NOTIF_*` + handlers `_close_ticket_action`/`_mute_alerts_action`/`_unmute_alerts_action` + helper `alerts_are_muted`), `backend/models.py:SettingsUpdate.llm_alerts_muted_until`, `backend/routes/llm_health.py` (S031 email + S032 warning_alerts honorent le mute).
- **Tests** : `backend/tests/test_siter39k_actions_and_escalation.py` (10/10 verts dont 4 dédiés S035) — fermeture ticket OK + ticket introuvable + mute/unmute (MUTE/NOTIF STOP/UNMUTE/NOTIF ON) + email S031 skippé pendant mute.

## S036 — Liluvine PRO appelle l'admin via WhatsApp quand elle est bloquée
- **Demande directe utilisateur** : 2026-02 (post-handoff) — « permet à Liluvine PRO d'envoyer un message à l'admin dont on pourra définir le numéro en paramètre lorsqu'elle a besoin d'aide en expliquant le contexte et pourquoi elle est bloquée »
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39k
- **Détail** : Quand Liluvine PRO ne sait pas répondre à un contact via WhatsApp auto-reply, elle peut s'auto-déclarer en demande d'aide et déclencher une notification WhatsApp contextuelle à l'admin :
  - **Mécanisme d'auto-détection** : Le system prompt d'auto-reply est étendu avec `ESCALATE_PROMPT_HINT` qui demande explicitement à Liluvine de terminer son message par `[ESCALATE: <raison brève>]` lorsqu'elle est bloquée, qu'elle détecte de la frustration/urgence, ou que la demande dépasse ses compétences.
  - **Strip + escalade** : Après réception de la réponse LLM, la regex `ESCALATE_RE` extrait la raison et nettoie le message (le client final ne voit jamais le marqueur). Si la réponse devient vide après nettoyage, un fallback « un agent humain va vous recontacter » est utilisé.
  - **Notification WhatsApp** : `notify_admin(db, contact_name, contact_phone_digits, last_user_message, reason, send_wa, ...)` envoie un message structuré à `liluvine_escalation_wa_phone` (fallback `llm_budget_notify_wa_phone`) contenant : 👤 nom contact · 📱 téléphone · 🧠 raison · 💬 dernier message · extrait de conversation · lien vers l'historique Liluvine.
  - **Anti-spam** : 1 escalade max par contact tous les `liluvine_escalation_cooldown_minutes` (défaut 30 min, configurable 1-1440), persisté dans `db.liluvine_escalations`.
  - **Configuration admin** : nouvelle section `Liluvine PRO — Demande d'aide WhatsApp à l'admin (S036)` dans `/admin/settings` (anchor `s-liluvine-escalation`) — 3 paramètres : `liluvine_escalation_enabled` (toggle), `liluvine_escalation_wa_phone` (E.164), `liluvine_escalation_cooldown_minutes` (1-1440). Bouton « Envoyer un test à l'admin » qui appelle `POST /api/admin/liluvine-escalation/test` (synthetic notification).
- **Bénéfice** : Liluvine devient un assistant intelligent qui sait demander de l'aide — l'admin n'est jamais surpris de découvrir un mécontent 24h après. Temps de réaction divisé par 10 sur les cas difficiles.
- **Endpoints** : `POST /api/admin/liluvine-escalation/test` (admin/sup uniquement).
- **Fichiers** : `backend/routes/liluvine_escalation.py` (nouveau — `ESCALATE_RE`, `ESCALATE_PROMPT_HINT`, `strip_escalation_marker`, `notify_admin`), `backend/routes/liluvine_wa_autoreply.py` (injection du hint + parsing + appel notify_admin), `backend/models.py:SettingsUpdate` (3 nouveaux champs + validation cooldown 1-1440), `backend/server.py` (endpoint `/admin/liluvine-escalation/test`), `frontend/src/components/LiluvineEscalationTestButton.jsx` (nouveau), `frontend/src/pages/admin/AdminSettings.jsx` (section S036 + filterable + NEW badge).
- **Tests** : `backend/tests/test_siter39k_actions_and_escalation.py` (10/10 verts dont 6 dédiés S036) — strip marker (basique + spacing tolérant) + disabled skip + no_phone skip + envoi + contexte présent + throttle 30min + endpoint admin /test.

## S042 — Toggle global d'auto-enrichissement Claude Vision des images Qdrant
- **Demande directe utilisateur** : 2026-02 (post-S041) — « exposer le toggle global » pour activer/désactiver l'analyse Claude Vision en masse depuis les Réglages
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39s
- **Détail** : Nouveau toggle `qdrant_image_auto_describe` dans `/admin/settings` → section Qdrant RAG. Active par défaut. Chaque upload d'image (via `POST /api/admin/qdrant/collections/{name}/points/image`) qui laisse `auto_describe=auto` lit ce setting global. Le toggle par-upload du UI Qdrant > Image reste prioritaire pour les exceptions.
- **Bénéfice** : permet de couper Claude Vision en masse pour économiser sur la Universal Key (~$0.001/image), sans toucher au code.
- **Fichiers** : `backend/models.py:SettingsUpdate`, `backend/routes/qdrant_rag.py` (déjà câblé en S041), `frontend/src/pages/admin/AdminSettings.jsx`.

## S043 — GRH : Primes (variables/mois) & Indemnités (fixes)
- **Demande directe utilisateur** : 2026-02 — « Dans le module GRH permettre d'ajouter ou supprimer des primes ou indemnités. Pour les primes elles sont variables d'un mois à l'autre… alors que pour les indemnités elles ne changent pas »
- **Statut** : 🟢 IMPLÉMENTÉE
- **Fix associé** : siter39s
- **Détail** : Deux nouvelles collections `hr_allowances` (indemnités fixes par employé, récurrentes, toggle active/inactive) et `hr_bonuses` (primes variables, rattachées à un mois YYYY-MM précis). CRUD complets. Le calcul `_compute_payslip` ajoute désormais `total_allowances + total_bonuses` au brut avant déduction d'absence (`gross_with_gains = gross + allowances + bonuses`). Les taxes s'appliquent sur le nouveau brut. Nouvel onglet « Primes & Indemnités » dans `/portal/hr` avec 2 cartes (Indemnités fixes / Primes du mois) + sélecteur d'employé. La fiche de paie (UI + PDF) affiche le détail ligne par ligne.
- **Endpoints** : `GET/POST /api/hr/employees/{eid}/allowances`, `PATCH/DELETE /api/hr/allowances/{aid}`, `GET/POST /api/hr/employees/{eid}/bonuses?month=YYYY-MM`, `PATCH/DELETE /api/hr/bonuses/{bid}`.
- **Tests** : `backend/tests/test_siter39s_primes_indemnites.py` (5/5 verts) — CRUD allowances + CRUD bonuses + filter par mois + intégration payslip.
- **Fichiers** : `backend/routes/hr.py` (modèles + endpoints + intégration _compute_payslip + PDF), `frontend/src/pages/portal/HrPrimesIndemnites.jsx` (nouveau), `frontend/src/pages/portal/HumanResources.jsx` (nouvel onglet), `frontend/src/pages/portal/HumanResourcesAdvanced.jsx` (PayslipsTab).

## S044 — Liluvine compare une capture d'écran client avec la base d'images SAWALI
- **Proposée par l'assistant** : 2026-02 (suite de S041)
- **Statut** : 🔵 PROPOSÉE — utilisateur a confirmé qu'il veut l'implémenter, à faire au prochain sprint
- **Détail** : Quand un client envoie une capture d'écran via WhatsApp ou le chat portail, Liluvine pourra (a) extraire l'OCR + description via Claude Vision, (b) faire une recherche sémantique dans Qdrant images, (c) identifier l'écran SAWALI le plus probable et proposer la procédure correspondante directement.
- **Bénéfice** : transforme Liluvine en assistant capable de « voir » l'écran du client, accélère la résolution support de plusieurs minutes par ticket.
- **Dépendances** : S041 (Qdrant images) + S042 (Claude Vision enrichment) — toutes deux livrées.

## S045 — Refactor `server.py` (21 800+ lignes) vers modules /backend/routes/
- **Demande directe utilisateur** : 2026-02 — « P2 »
- **Statut** : 🟡 ACCEPTÉE — à découper en plusieurs PR, démarrage prochain sprint
- **Détail** : Extraire progressivement les blocs monolithiques de `server.py` vers `/app/backend/routes/` (déjà bien entamé : qdrant_rag.py, media_library.py, liluvine_pro.py, wa_admin_cockpit.py, hr.py, cashier.py, ad_banners.py, etc.). Cibles prioritaires : routes auth, routes settings, routes WhatsApp, routes payments, routes notifications. À faire avec test de non-régression à chaque extraction.
- **Bénéfice** : code maintenable, tests plus rapides, isolation des bugs, onboarding facilité.

## S046 — Internationalisation (i18n) FR / EN + 4 langues à définir
- **Demande directe utilisateur** : 2026-02 — « Plus tard ; comme suggestion à noter, on va mettre le site en 5 langues en plus du français »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02)
- **Fix associé** : S046 Phase 1 (i18n module + sélecteur public + RTL Arabic + auto-detect + CSV import/export + auto-translate via Anthropic) + **S046 Phase 2 — Contenus CMS multilingues** (Iter40-content-i18n)
- **Détail** : Table MongoDB `i18n_strings` + collection `contents.translations` (par slug). Sélecteur public, switch instantané. `AdminI18n.jsx` pour gestion UI strings + `AdminContents.jsx` avec onglets de langues pour gérer les contenus longs (Hero, Mission, Spécialisations, etc.). Re-fetch automatique côté pages publiques (`Home.jsx`, `Missions.jsx`, `Specialisations.jsx`) lors d'un changement de langue.
- **Bénéfice** : ouverture du portail SAWALI à des clients hors francophonie (Afrique anglophone, Europe…). Contenus longs traduisibles sans toucher au code.

## S047 — Modale publicitaire publique avec fréquence & A/B
- **Demande utilisateur** : 2026-06 — « Affiche une image au hasard parmi 10 sur la page publique »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-modal + Iter40-modal-frequency + Iter40-modal-ab + global-cap
- **Détail** : Nouveau placement `public_modal` côté admin avec fréquence configurable (`session` | `daily` | `always`), A/B test possible sur la fréquence (variant_b_modal_frequency), compteurs séparés modale (`modal_impressions/clicks` global + par variante A/B). Plafond global anti-spam (`modal_global_cap_per_day`, 0–20) configurable dans Admin Settings, enforcé côté client via localStorage daté. Composant `PublicAdModal.jsx` intégré dans `MarketingLayout`.
- **Bénéfice** : nouvelle source de revenu publicitaire (régie) avec contrôle fin de l'agressivité d'affichage et mesure indépendante du slot top-of-page.
- **Tests** : 36 tests pytest passants (placement, frequency, A/B, global cap, stats).

## S048 — Gestion multilingue des contenus longs (CMS i18n)
- **Demande utilisateur** : 2026-06 — « Pour la page admin/contents, affiche la liste des langues et permet de saisir les champs spécifiques »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-content-i18n
- **Détail** : Le modèle `ContentUpsert` gagne un champ `translations: {<lang>: {title, body_html, metadata}}`. Endpoints `GET /content?lang=xx` et `GET /content/{slug}?lang=xx` font un deep-merge (override > default). Admin UI : onglets de langues (FR base + langues définies dans `/i18n/languages`) avec indicateur ● vert quand une surcharge existe + bouton "Effacer surcharges". Pages publiques re-fetchent quand la langue change via `useI18n().lang` dans les dépendances `useEffect`.
- **Bénéfice** : permet à l'admin de localiser les textes longs (Hero, Mission, descriptions de spécialisations) sans dupliquer la structure, tout en gardant les chiffres clés et la structure JSON cohérents.
- **Tests** : 6 tests pytest (`test_iter40_content_i18n.py`) couvrant upsert, no-lang fallback, override, unknown lang, deep-merge metadata, list endpoint.

## S049 — Sélecteur de modèle IA + Traduction en lot (i18n + contents)
- **Demande utilisateur** : 2026-06 — « Au niveau de régionalisation et de /admin/contents il serait bien de sélectionner le modèle du générateur. En régionalisation, toutes les lignes vides sont traduites par le traducteur sélectionné. Dans admin/contents chaque onglet ayant un contenu est traduit en une seule passe (en conservant les balises) »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-i18n-model
- **Détail** :
  - 6 modèles disponibles : Claude Sonnet 4.5 (défaut), Claude Haiku 4.5, GPT-4o, GPT-4o mini, Gemini 2.5 Pro, Gemini 2.5 Flash
  - Nouvel endpoint `GET /admin/i18n/translate-models` retourne la liste + défaut
  - `POST /admin/i18n/translate-suggest` accepte désormais un champ optionnel `model`
  - Nouvel endpoint `POST /admin/i18n/translate-empty-bulk` qui traduit en une passe toutes les cellules vides d'une langue cible avec le modèle sélectionné (préserve les balises HTML et placeholders)
  - Nouvel endpoint `POST /admin/content/{slug}/translate` qui traduit l'intégralité d'un contenu (titre + body_html + metadata.kicker + metrics labels + items title/desc) en UN SEUL appel LLM (préserve les balises) et le persiste dans `translations[<target_lang>]`
  - Frontend `AdminI18n.jsx` : nouveau bloc violet "Traducteur IA — réglages" avec dropdown modèle + select langue cible + bouton "Traduire toutes les cellules vides"
  - Frontend `AdminContents.jsx` : dans le bloc langues, dropdown modèle + bouton "Traduire ce contenu en XX" (visible uniquement quand une langue autre que défaut est sélectionnée)
- **Bénéfice** : permet d'industrialiser la traduction (gain de temps massif), tester plusieurs modèles pour comparer le coût/qualité, et garder un contrôle fin via la relecture admin avant sauvegarde.
- **Tests** : 9 tests pytest (`test_iter40_i18n_model_selector.py`) couvrant liste des modèles, validation, rejection des modèles inconnus, endpoint content/translate (validation lang/model, 404 slug inconnu, refus contenu vide).

## S050 — Type de paie « Forfaitaire » (montant mensuel fixe, indépendant des heures)
- **Demande utilisateur** : 2026-06 — « Où trouve-t-on dans GRH pour éditer le montant mensuel de base à payer à l'agent qui sera payé sans tenir compte des heures travaillées ? (Cas d'agents venant d'avoir un accès en fin de mois) »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-hr-fixed
- **Détail** :
  - Nouveau `pay_type="fixed"` (en plus de `monthly` et `hourly`) sur `EmployeePayload` et `EmployeeUpdate` (pattern regex étendu)
  - Lorsque `pay_type=fixed`, le calcul `computed_gross = base_salary` (pas de proratisation, pas de coefficient horaire)
  - Sur le payroll, `absence_deduction = 0` pour les forfaitaires (logique métier : un forfait n'est pas amputé pour absences)
  - Frontend `HumanResources.jsx` : option `<option value="fixed">Forfaitaire (montant fixe)</option>` dans le dropdown "Type de paie", encart d'information ambre quand sélectionné, libellés "Forfaitaire" et "· forfait" dans toutes les tables (timesheet, liste salaires, employés)
- **Bénéfice** : couvre 3 cas concrets — (1) agent recruté en fin de mois qui doit recevoir un montant fixe pour le mois en cours, (2) prestataires au forfait, (3) périodes d'essai. Évite le contournement par création manuelle de bonus.
- **Où le trouver** : `/portal/hr` (module GRH) → bouton "Nouvel employé" ou édition d'un existant → champ "Type de paie" → choisir "Forfaitaire (montant fixe)". Le montant sera celui saisi dans "Salaire base".
- **Tests** : 5 tests pytest (`test_iter40_hr_fixed_pay_type.py`) : création, refus type invalide, mise à jour PATCH, computed_gross == base_salary avec 0 heures, régression monthly toujours proratisé.

## S051 — Toggle Admin pour désactiver le GlobalRouteLoader
- **Demande utilisateur** : 2026-06 — « Ajoute un toggle dédié dans Admin Settings pour aussi désactiver le GlobalRouteLoader. Pour cette suggestion, met à jour mon historique des suggestions, on y reviendra plus tard. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-route-loader
- **Détail** :
  - Backend `models.py` : champ `SettingsUpdate.global_route_loader_enabled: Optional[bool] = None`
  - Backend `server.py` : nouvel endpoint **anonyme** `GET /api/public/ui-flags` retournant uniquement `{global_route_loader_enabled, download_gauge_enabled}` (jamais de secrets)
  - Frontend `GlobalRouteLoader.jsx` : lit le flag au mount via `/api/public/ui-flags`, le cache dans `localStorage["ui_flag_global_route_loader_enabled"]` pour un comportement instantané au prochain chargement, écoute l'event `ui-flags-updated` pour réagir aux changements sans rechargement
  - Frontend `AdminSettings.jsx` : nouveau bloc "Affichage — Jauge de transition entre pages" avec checkbox et explication. Au toggle, dispatch `CustomEvent("ui-flags-updated")` pour propager immédiatement
- **Bénéfice** : option pour les utilisateurs/clients trouvant la jauge intrusive. Préserve la flexibilité de réactivation rapide. Cache localStorage évite un flash entre le rendu initial et la réception du flag.
- **Tests** : 5 tests pytest (`test_iter40_route_loader_toggle.py`) : endpoint anonyme, défaut true, toggle on/off, aucune fuite de secrets, GET /admin/settings retourne le flag.

## S052 — Identité publique (white-label : marque, logo, couleur, accroche)
- **Demande utilisateur** : 2026-06 — « Oui vas-y » (réponse à la suggestion d'étendre `/api/public/ui-flags` avec des flags de branding pour clients revendeurs)
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-ui-flags
- **Détail** :
  - Backend `models.py` : 4 nouveaux champs dans `SettingsUpdate` : `public_brand_name`, `public_brand_color` (hex), `public_logo_url`, `public_hero_tagline`
  - Backend `server.py` : `GET /api/public/ui-flags` étendu pour exposer ces 4 fields (anonyme, jamais de secrets). Valeurs vides normalisées en `null`.
  - Frontend `lib/useUIFlags.js` : nouveau hook qui fetch les flags une fois, cache en `localStorage` (anti-flash), écoute `ui-flags-updated` pour propagation instantanée, applique automatiquement `document.title` (brand name) et `--brand-primary` (CSS variable) sur `:root`
  - Frontend `App.js` : appel du hook au niveau racine → branding appliqué app-wide
  - Frontend `AdminSettings.jsx` : nouvelle section "Identité publique" avec champ texte (nom), color picker + hex, URL logo avec aperçu, accroche du hero. Tous les champs dispatchent `ui-flags-updated` au changement pour propagation immédiate.
- **Bénéfice** : permet à un client revendeur (white-label) de personnaliser instantanément l'identité visuelle sans toucher au code ni redéployer. Préserve les défauts SAWALI quand les champs sont vides.
- **Tests** : 3 nouveaux tests pytest dans `test_iter40_route_loader_toggle.py` : présence des 4 champs (defaut null), set+echo via PUT/GET, normalisation des chaînes vides/whitespace en null. **8/8 PASS**.
- **Où le trouver dans l'UI** : `/admin/settings` → faire défiler jusqu'à la section bleu/violet **« Identité publique — marque, logo, couleur »** (juste après *« Affichage — Jauge de transition entre pages »* et avant *« Régie publicitaire — Plafond de modales »*). 4 champs alignés en grille 2 colonnes : Nom de la marque + Couleur primaire (color picker + hex), URL du logo + bouton *« Téléverser »* (drag-drop fichier), Accroche du hero. Aperçu du logo affiché en dessous quand un URL est défini.
- **Pistes pour la suite** : ~~utiliser `var(--brand-primary)` dans les composants Tailwind~~ ✅ **FAIT en Iter40-ui-flags-tailwind (2026-06-05)** — la palette Tailwind `sawali.blue` et `sawali.blue-light` sont maintenant résolues via `var(--brand-primary)` et `var(--brand-primary-light)`, donc TOUS les `bg-sawali-blue`, `text-sawali-blue`, `border-sawali-blue`, `ring-sawali-blue` héritent automatiquement de la couleur choisie en Admin. Light/dark variants sont calculés automatiquement (shift de luminosité de ±12-18 %). Validé visuellement : changement de #1E90FF → #FF3366 dans la console, tous les boutons CTA, badges, accents, icônes du site public passent instantanément en rose. Aussi exposée comme `brand: { DEFAULT, light, dark }` pour les nouveaux composants qui voudraient un nom sémantique.
- **Pistes restantes** : afficher `public_logo_url` dans `MarketingNav.jsx` quand défini ; appliquer `public_hero_tagline` dans `Home.jsx` (override de `home_hero.title`).

## S053 — Couleur de texte personnalisable (sur fond brand)
- **Demande utilisateur** : 2026-06 — « Il faudrait un 2ème picker supplémentaire (pour le texte). Le premier servira pour le fond et le second pour le texte. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-ui-flags-text
- **Détail** : Nouveau champ `public_brand_text_color` dans `SettingsUpdate` + endpoint public `/api/public/ui-flags`. Applique `--brand-text` (CSS variable) au `:root`. Nouveau scope Tailwind `brand.text` câblé sur la variable. Admin UI : deuxième color picker juste sous le picker de fond, avec tuile aperçu de contraste en temps réel.
- **Bénéfice** : permet d'ajuster le contraste texte/fond selon la couleur choisie (ex : fond jaune → texte noir).
- **Où le trouver** : `/admin/settings` → section *« Identité publique »* → ligne *« Couleur du texte (sur fond brand) »*.

## S054 — Logo personnalisable propagé au header public
- **Demande utilisateur** : 2026-06 — « Dans tous les 2 cas le logo ne change pas »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-ui-flags-logo
- **Détail** : `components/MarketingNav.jsx` consomme `useUIFlags()` et utilise `flags.public_logo_url` (fallback `LOGO_URL` SAWALI) ainsi que `flags.public_brand_name` (fallback "SAWALI SMART SYSTEMS"). Le logo téléversé dans Admin Settings remplace désormais le logo SAWALI dans le header de toutes les pages publiques. Le `useUIFlags()` au niveau racine de l'app garantit que le changement est appliqué immédiatement après "Enregistrer".
- **Bénéfice** : white-label complet — un client revendeur peut changer logo + couleur + nom de marque depuis Admin Settings sans aucune intervention dev.

## S055 — Recherche full-text dans /admin/suggestions
- **Demande utilisateur** : 2026-06 — « Permettre dans /admin/suggestions de pouvoir faire une recherche full-text »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-suggestions-search
- **Détail** : Barre de recherche violet en haut de `/admin/suggestions`. Tokenize la requête (mots ≥ 2 chars, lowercased, accent-insensible). Splitte le markdown en blocs `## ...`, filtre les blocs où **TOUS** les tokens sont présents (sémantique AND), highlight les matches via `<mark class="bg-yellow-200">` en jaune, compteur "X / Y suggestions" en temps réel, bouton "Effacer" pour vider. Message "Aucune suggestion ne correspond..." si zéro résultat.
- **Bénéfice** : retrouver instantanément une suggestion par numéro (S046), mot-clé (qdrant, rag, traduction), statut (implémentée, différée) ou nom de fix (Iter40).
- **Où le trouver** : `/admin/suggestions` → barre de recherche violet en haut, juste sous le titre.

## S056 — Renommer "Qdrant RAG" → "RAG (Qdrant)" dans Admin Settings
- **Demande utilisateur** : 2026-06 — « C'est comme quand tu parles de Qdrant dans les paramétrages de la KB. Ça ne donne pas le bon résultat. Il faut plutôt rechercher avec RAG »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-suggestions-search (cosmétique)
- **Détail** : Dans `/admin/settings`, la section "Qdrant RAG — Base de connaissance vectorielle (S038)" devient "RAG — Base de connaissance vectorielle (Qdrant) (S038)". Le mot-clé principal devient "RAG" pour aligner avec le vocabulaire métier utilisateur. La barre de filtre intégrée à AdminSettings et la barre de recherche AdminSuggestionsRegistry trouvent maintenant la section sur "rag" ou "qdrant" indifféremment.

## S057 — Habillage du fond (couleur unie ou image, public + portail)
- **Demande utilisateur** : 2026-06 — « Toujours pour l'identité peut-on avoir un paramètre pour modifier aussi le fond par une couleur unie ou une image (centré ou répétée) sur la page publique ou le portail. On habillera le site aux couleurs d'un évènement ou la charte graphique demandée par un de nos clients »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter40-ui-flags-bg
- **Détail** :
  - Backend `models.py` : 8 nouveaux champs (4 par scope) — `public_bg_mode/color/image_url/image_position` et `portal_bg_mode/color/image_url/image_position`
  - Backend `/api/public/ui-flags` expose les 8 champs avec défauts (`mode=default`, `position=cover`)
  - Frontend nouveau composant `BackgroundApplier.jsx` (render-less) monté dans `App.js` : écoute `useLocation` et `useUIFlags`, applique le mode approprié à `<body>` selon que la route est `/portal*` ou `/admin*` (= scope portail) ou autre (= scope public). Strip propre des overrides quand `mode=default`.
  - Frontend `MarketingLayout.jsx` : hook `useBgOverrideActive()` via `MutationObserver` qui surveille `data-bg-override-active` sur `<body>` ; rend le layout transparent quand un override est actif (sinon `marketing-dark` couvrirait le fond).
  - Frontend `AdminSettings.jsx` : nouvelle section "Habillage — fond de page (événementiel / charte client)" avec un composant `BgEditor` dual (côte à côte : public / portail). Pour chaque scope : sélecteur de mode, color picker, URL image, sélecteur de position (cover/contain/center/repeat) et tuile aperçu live.
  - 4 modes d'affichage d'image :
    - `cover` (recommandé) : remplit l'écran, peut rogner
    - `contain` : image entière visible, possibles bandes
    - `center` : taille originale, centrée, sans répétition (pour logos discrets)
    - `repeat` : mosaïque (pattern / motif)
  - L'image utilise `background-attachment: fixed` → effet parallaxe au scroll
- **Bénéfice** : habillage saisonnier (Noël, anniversaire SAWALI), thèmes événementiels client, charte graphique blanche. Pages publiques et portail théméables indépendamment.
- **Où le trouver** : `/admin/settings` → faire défiler jusqu'à la section *« Habillage — fond de page (événementiel / charte client) »* (juste après *« Identité publique »*). Deux blocs côte-à-côte : pages publiques à gauche, portail à droite.
- **Note** : certains heros illustrés (ex : carte d'Afrique sur la page d'accueil) ont leur propre visuel illustratif et continuent de se superposer au fond global. Le fond personnalisé sera plus dominant sur les pages sans hero illustratif (Missions, Contact, Catalogue, Policies, etc.) et sur tout le portail.
- **Tests** : 4 tests pytest (`test_iter40_bg_theming.py`) : exposition des 8 champs, set/get public color, set/get portal image avec position, normalisation chaînes vides → null. **4/4 PASS**.

## S058 — Commandes WhatsApp publiques `!Garde` et `!Météo` (sans LLM)
- **Demande utilisateur** : 2026-06 — « Quand un client WhatsApp envoie !Garde il doit recevoir la liste des officines de garde de la semaine. !Meteo doit retourner les prévisions »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix22
- **Détail** : Court-circuit Claude dans `liluvine_wa_autoreply.py` — détection par prefix `!garde`/`!pharmacie`/`!meteo`/`!météo`, dispatch direct vers `_build_garde_reply(db)` ou `_build_meteo_reply(db, cmd, phone)`. La météo utilise Open-Meteo API (geocoding + forecast) sans clé. Le planning de garde lit `db.garde_planning` + `db.officines` (collection groupe_garde).
- **Bénéfice** : économie tokens LLM (~3 c$/commande), réponse instantanée (~300 ms vs ~2 s LLM).
- **Fichiers** : `routes/liluvine_wa_autoreply.py` lignes 230-266 + 521-684.

## S059 — Audit des `!commandes` inconnues + bouton "Générer handler IA"
- **Demande utilisateur** : 2026-06 — « Quand quelqu'un envoie une commande inconnue (ex. !Aizenta) il faut qu'on sache combien de fois cela arrive et qu'on puisse y répondre. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24d + fix24e
- **Détail** :
  - Nouvelle collection `liluvine_exclamations` qui stocke TOUTE exclamation `!xxx` (connue ou non) avec body, command, args, contact, timestamp
  - Page admin `/admin/liluvine-pro/requests` regroupe par commande et par fréquence
  - Bouton "Auto-générer handler IA" qui appelle Claude Sonnet (via emergent_llm_key) pour proposer du code Python drop-in respectant le pattern `_build_<cmd>_reply(db, args)`
  - 3 exemples concrets reçus sont injectés dans le prompt système
- **Fichiers** : `routes/liluvine_wa_requests.py`, `pages/admin/AdminLiluvineWaRequests.jsx`

## S060 — Migration SMS bidirectionnels d'Africa's Talking vers Bird.com
- **Demande utilisateur** : 2026-06 — « Je voudrais utiliser Bird au lieu d'Africa's Talking pour les SMS entrants/sortants. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24a/b/c
- **Détail** :
  - Suppression du SDK Africa's Talking
  - Nouvelle route `routes/bird_sms.py` avec `send_bird_sms(db, to, text, sender)` (Bird Channels API direct via httpx + AccessKey)
  - Webhook `POST /api/webhooks/bird/incoming-sms` pour réceptionner les SMS entrants
  - Intégration au Unified Inbox (`/portal/inbox`) avec channel `sms_bird` + threading par numéro
  - Settings Admin : 5 champs éditables (bird_api_base_url, bird_workspace_id, bird_channel_id, bird_access_key, bird_default_sender)
- **Fichiers** : `routes/bird_sms.py`, `routes/unified_inbox.py`

## S061 — Page de coût SMS Bird (chart historique)
- **Demande utilisateur** : 2026-06 — « Combien j'ai dépensé en SMS sur Bird ? Faut un graphique sur 7/30/90 jours. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24f
- **Détail** : Page admin `/admin/bird-cost` avec 5 KPI cards (aujourd'hui / hier / 7j / 30j / total) + graphique barres horizontales CSS pur (pas de lib). Endpoint backend `GET /api/admin/bird/cost-daily-series?days=1-365`. Aujourd'hui mis en avant en sky-600.
- **Fichiers** : `pages/admin/AdminBirdCost.jsx`, `server.py` (endpoint cost-daily-series).

## S062 — Page admin Handler Suggestions (historique du code IA)
- **Demande utilisateur** : 2026-06 — « Je veux voir tout l'historique des handlers que l'IA a générés, leur statut (appliqué/en attente), avec notes éditables. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24f
- **Détail** : Page `/admin/handler-suggestions` avec table filtrable (par commande + par statut), modal `CodeViewerModal` pour visualiser le code Python généré, notes éditables inline, bouton "Appliqué"/"En attente", suppression avec confirmation. 3 endpoints backend (GET liste, PATCH toggle/notes, DELETE).
- **Fichiers** : `pages/admin/AdminHandlerSuggestions.jsx`, `routes/liluvine_wa_requests.py` lignes 252-305.

## S063 — Bird.com comme provider SMS sélectionnable dans le portail
- **Demande utilisateur** : 2026-06 — « Dans la liste déroulante 'Fournisseur' de /portal/sms, 'SMS Bird' est absent »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24g
- **Détail** :
  - Backend `_sms_active_providers(s)` retourne maintenant `'bird'` quand `bird_enabled=true` ET `bird_workspace_id`, `bird_channel_id`, `bird_access_key` sont tous non-vides
  - `_sms_dispatch` route automatiquement vers `routes/bird_sms.send_bird_sms` quand `cfg["kind"] == "bird"` (persiste dans `bird_sms_messages` pour cohérence avec l'inbox)
  - Frontend `SmsBulk.jsx`, `Contacts.jsx`, `WaBulk.jsx` : option `📡 Bird.com` visible dans les dropdowns SMS provider quand Bird est configuré
  - `LiluvinePro.jsx` : nouveau filtre channel `📡 Bird` + badge orange pour sessions `sms:bird:*`
- **Bénéfice** : un opérateur peut désormais choisir Bird comme provider d'envoi pour ses campagnes SMS bulk ou ses envois individuels, en plus d'Orange/Telecel/Moov/OVH.
- **Tests** : 3 tests pytest `test_iter43_fix24g_bird_provider.py`. **3/3 PASS**.

## S064 — Bouton "Tester en dry-run" (sandbox) sur les handlers générés
- **Demande utilisateur** : 2026-06 — « Implémenter un bouton 'Tester ce handler en dry-run' sur /admin/handler-suggestions. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24g
- **Détail** :
  - Backend `POST /api/admin/liluvine-pro/handler-suggestions/{id}/dry-run` qui extrait le bloc ```python contenant `async def _build_<cmd>_reply`, compile + exec dans un sandbox restreint (builtins minimaux ~30 noms, `__import__` whitelisté sur 17 modules safe : datetime/asyncio/json/math/re/typing/uuid/hashlib/base64/calendar/collections/itertools/functools/statistics/decimal/html/urllib.parse).
  - Timeout configurable 0,5 à 15 s (default 5 s) via `asyncio.wait_for`
  - Logue chaque exécution dans `liluvine_handler_dry_runs` (audit)
  - Frontend : panneau pliable dans `CodeViewerModal` avec input args + bouton "Exécuter le dry-run" + affichage du résultat (vert si OK + reply / rouge si erreur)
- **Bénéfice** : on peut valider le comportement d'un handler généré par Claude SANS avoir à le copier-coller dans `liluvine_wa_autoreply.py` ni redéployer. Cycle de validation : génération IA → dry-run → ajustement notes → marquer "appliqué" → push code → redeploy.
- **Tests** : 8 tests pytest `test_iter43_fix24g_dry_run.py` (happy path, args vides, SyntaxError, timeout, import bloqué, fonction manquante, 404, log audit). **8/8 PASS**.

## S065 — Catch-all `…` pour toute `!commande` inconnue (WhatsApp)
- **Demande utilisateur** : 2026-06 — « Quand j'envoie !garde ou !meteo il n'y a aucune réponse. Toujours répondre au moins '...' même si elle ne comprend rien. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24h
- **Détail** :
  - Avant : pour toute exclamation `!xxx` non reconnue (ex. `!Aizenta`), `maybe_handle_liluvine_wa_command` retournait silencieusement `{"ok": False, "reason": "command_prefix"}` — l'utilisateur n'avait aucun feedback.
  - Maintenant : envoie systématiquement une réponse de fallback (`…` par défaut, personnalisable via le nouveau réglage `liluvine_wa_unknown_cmd_reply`) en respectant le gate `enabled` + `denylist`. Marque l'exclamation comme `handled=True, fallback=True` dans `liluvine_exclamations`.
  - En plus : les handlers `_build_garde_reply` et `_build_meteo_reply` sont désormais wrappés dans un try/except — si le builder lève (DB down, API météo HS, etc.) on envoie `⚠️ Désolé, je n'arrive pas à traiter cette commande pour le moment.` au lieu d'un silence.
- **Bénéfice** : Liluvine ne paraît jamais "muette" sur WhatsApp. L'utilisateur sait toujours que son message a été reçu, et l'admin peut suivre les commandes inconnues pour décider lesquelles automatiser ensuite.
- **Fichiers** : `routes/liluvine_wa_autoreply.py` lignes 192-238 + 233-251.

## S066 — 3 commandes WhatsApp publiques étendues : `!adresse`, `!horaires`, `!stock`
- **Demande utilisateur** : 2026-06 — « Implémente l'idée d'enhancement avec aussi la commande !adresse (téléphone+whatsapp+géolocalisation accessible sous whatsapp comme quand on envoie sa géolocalisation) et localisation dans le champ de 'indication de localisation' de la fiche officine, etc »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24j
- **Détail** :
  - **`!adresse`** (alias `!contact`) : envoie un message texte avec nom + adresse + ville + pays + indication de localisation + téléphone + WhatsApp + email + lien Google Maps + horaires, PUIS envoie un message WA de type `location` (carte cliquable avec preview map) si lat/lon configurés. Helper privé `_wa_send_location` ajouté.
  - **`!horaires`** (alias `!horaire`) : lit le champ `liluvine_wa_brand_hours` (texte libre multi-lignes), met en évidence (➡️) la ligne correspondant au jour courant (lundi-dimanche en français). Message friendly si non configuré.
  - **`!stock <médicament>`** (alias `!dispo`) : recherche regex case-insensitive dans `officine_inventory_items.product_name`, filtre `available=True` + `quantity>0` + officine `status != "suspended"`, trié par quantité décroissante, top 5 résultats. Affiche pour chaque match : nom officine, indication de localisation/ville, nom produit, quantité, prix, téléphone/WhatsApp. Helper `_build_stock_reply`.
- **Nouvelle UI Admin** : section "Profil enseigne" dans `LiluvineWaAutoreplySection.jsx` avec 12 champs éditables (name, phone, whatsapp, email, address, city, country, location_hint, latitude, longitude, hours, maps_url) + section dédiée "Fallback `…`" (toggle on/off + texte personnalisé).
- **API étendue** : `GET/PUT /api/admin/liluvine-pro/wa-autoreply` étendu avec 14 nouveaux champs validés (lat ∈ [-90,90], lon ∈ [-180,180]).
- **Bénéfice** : les clients WhatsApp obtiennent en libre-service les infos de contact, horaires d'ouverture, et la disponibilité produits — sans nécessiter d'opérateur humain ni d'appel LLM. Diminue le volume de tickets entrants tout en améliorant la satisfaction client.
- **Tests** : 12 tests pytest `test_iter43_fix24j_public_commands.py` (adresse avec/sans config, alias !contact, horaires avec mise en évidence du jour, !horaire singulier, !stock match/empty/usage, !dispo alias, exclusion suspended, sanity disabled-toggle). **12/12 PASS**.
- **Fichiers** :
  - Backend : `routes/liluvine_wa_autoreply.py` lignes 756-1009 (helpers) + lignes 195-275 (dispatch)
  - Backend : `routes/liluvine_pro.py` (payload + endpoint étendu)
  - Frontend : `pages/admin/sections/LiluvineWaAutoreplySection.jsx` (nouvelle section "Profil enseigne")

## S067 — Story Studio : résilience aux redéploiements (Object Storage + fallback CDN)
- **Demande utilisateur** : 2026-06 — « Concernant Story Studio, la bibliothèque est vide (cadre image vide mais aucun contenu) et l'historique affiche [fb_feed/ig_reel — Fichier vidéo introuvable] »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24k
- **Cause racine** : Les vidéos générées étaient stockées **uniquement** sur le disque local `/app/backend/uploads/stories/` du container. À chaque redéploiement Kubernetes (Save to Github → Deploy), un nouveau container est créé et **tous les fichiers locaux sont perdus**. Les entrées BDD `story_assets` conservaient `file_path` mais le fichier n'existait plus → "Fichier vidéo introuvable" sur publication + cadre vide en bibliothèque.
- **Fix architecture** (3 niveaux de résilience en cascade) :
  1. **Stockage primaire** : disque local (rapide, garde le comportement existant)
  2. **Stockage de backup persistant** : Emergent Object Storage (`object_storage.save_and_log`) au moment de la génération. Persiste indéfiniment, indépendant du container. Métadonnées dans `stored_objects` collection.
  3. **Stockage de secours** : URL CDN d'origine (`source_url` Fal.ai). Re-download possible 24-72h après génération.
  4. **Helper unifié** `_ensure_local_file(asset_doc)` qui essaie les 3 sources en cascade et auto-marque l'asset `status="expired"` si rien ne fonctionne.
  5. **Endpoints résilients** : `stream_asset_media`, `signed_public_media` (utilisé par Meta), `_publish_single_target` utilisent tous le helper. Plus de "Fichier introuvable" sans tentative de restauration.
- **UI** : `AssetCard` affiche désormais les assets `expired` avec un badge ambré « ⚠️ Vidéo expirée — Régénérez l'asset » au lieu d'un cadre vide.
- **Bénéfice** : Les vidéos générées **survivent maintenant aux redéploiements**. Les anciens assets cassés sont visibles et clairement marqués pour régénération (au lieu d'un échec silencieux).
- **Tests** : 4 tests pytest `test_iter43_fix24k_story_studio_resilience.py` (fichier présent / 410 si tout échoue / restoration source_url / bibliothèque liste les expired). **4/4 PASS**.
- **Fichiers** :
  - Backend : `routes/story_studio.py` (+import object_storage, +helper `_ensure_local_file` 90 lignes, +upload backup à la génération, +tuple return `_generate_with_fal`, +cascade dans stream + publish + signed-media)
  - Frontend : `pages/admin/StoryStudio.jsx` (variable `isExpired`, badge ambré dans `AssetCard`)

## S068 — Délégation menu Officines à des comptes non-admin (RBAC champ par champ)
- **Demande utilisateur** : 2026-06 — « Permettre de configurer dans Admin Settings les comptes des utilisateurs pouvant afficher le menu officine. Ces utilisateurs ne pourront modifier dans la fiche individuelle des pharmacies : l'intitulé, les numéros de téléphone et WhatsApp, la géolocalisation, mes indication de localisation, et l'activité principale. Les autres champs restant grisés. Par contre pour l'ajout des nouvelles officines tous les champs sont actifs. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24n
- **Détail** :
  - Nouveau setting `officines_menu_allowed_emails: List[str]` éditable dans Admin → Paramètres → « 🏥 Délégation menu Officines (comptes autorisés) »
  - Backend : helper `_get_officines_menu_user(user) → (user, edit_mode)` qui retourne `"full"` pour admin/supervisor, `"limited"` pour email autorisé, sinon HTTP 403
  - Nouvel endpoint `GET /api/me/officines-permissions` → `{can_view, edit_mode, editable_fields}` utilisé par le frontend pour route-guard et grisage
  - Endpoints `/admin/officines-registry`, `/admin/officines-registry/{id}` (GET + PUT) acceptent désormais admin ET utilisateur délégué
  - En mode `limited`, le PUT filtre payload : seuls `intitule, phone, whatsapp, latitude, longitude, location_hint, activite_principale` peuvent être modifiés. Les autres champs sont ignorés silencieusement (UX : grisés côté UI)
  - POST création officine : un délégué peut créer avec TOUS les champs (la restriction limited ne s'applique qu'à l'édition d'une fiche existante)
- **Frontend** : `EditOfficineModal` reçoit `editMode` ; banner ambré affiché en mode limited ; helper `canEdit(field)` ; `Field` composant accepte `disabled` (background slate-100 + readonly) ; les selects Activité / Rôle / Groupe garde + l'upload logo sont également désactivés ; le bouton "Détecter ma position" est disabled si latitude lock
- **Tests** : 7 tests pytest `test_iter43_fix24n_officines_delegation.py` (admin full / non-admin 403 / délégué limited / liste autorisée / PUT filtré server-side / admin keeps full / création avec tous les champs). **7/7 PASS**.

## S069 — Bouton test SMS Bird + Fix critique webhook !commandes
- **Demande utilisateur** : 2026-06 — « Place moi un bouton 'test' à la configuration de BIRD dans Admin settings pour tester l'envoie de message à un numéro et afficher le code retour. Puis les commandes '!' ne marchent toujours pas. elles ne sont pas suivies de réponses. Est ce la bonne table qui est utilisée ? »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24l
- **Bug racine `!commandes` muettes** : le webhook WhatsApp (`server.py:16986`) avait une exclusion explicite `... and not (text.startswith("!") or text.startswith("/"))` qui bypass `autoreply_to_inbound` pour TOUTES les commandes `!`. Donc seuls `!absence`/`!avance`/`!ticket`/`!aide` (gérés par leur propre handler HR) répondaient. `!garde`/`!meteo`/`!adresse`/`!horaires`/`!stock`/`!Aizenta` restaient muets MÊME AVEC les fix24h/i/j en place.
- **Fix appliqué** : suppression de l'exclusion `!`/`/`. Toutes les commandes `!` non HR passent désormais au dispatcher centralisé `autoreply_to_inbound`.
- **Bouton test Bird** : endpoint `POST /admin/bird/test-sms` qui envoie un vrai SMS et retourne HTTP status + latency + headers + corps Bird complets. Bypass `bird_enabled` toggle pour valider la config avant activation. Pas de persistance dans `bird_sms_messages` (mode test). UI : bloc vert "🧪 Tester l'envoi SMS Bird" dans Admin → Paramètres → Bird Channels SMS.

## S070 — Suppression TeamPresenceBadge du top menu public
- **Demande utilisateur** : 2026-06 — « Supprimer totalement de la page publique le lien "équipe joignable 24/7" se trouvant dans le menu du haut. uniquement là bas »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06)
- **Fix associé** : Iter43-fix24m
- **Détail** : Retrait du composant `<TeamPresenceBadge>` de `MarketingNav.jsx` uniquement. Le badge reste visible en `Home.jsx`, `Contact.jsx`, `MarketingFooter.jsx` (comme demandé : "uniquement là bas").

## S071 — VIDAL : « Copier le code » + Favoris persistés
- **Demande utilisateur** : 2026-02-26 — Faciliter la recherche VIDAL : pouvoir copier le code médicament et bookmarker les favoris persistés en DB (au lieu de localStorage volatile).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24au-VIDAL
- **Détail** :
  - Backend : `routes/vidal_favorites.py` (CRUD `/api/vidal/favorites/*` lié au user_id), masquage uuid → titre/picked_id
  - Frontend : `pages/portal/Vidal.jsx` ajoute un bouton 📋 sur chaque résultat (copy code) et une icône ⭐ pour toggle favori (cloud sync)
  - Liste des favoris affichée en tête de page avec recherche/suppression
- **Tests** : 5 pytest `test_iter43_fix24au_vidal_favorites.py` (CRUD complet, isolation par user_id). **5/5 PASS**.

## S072 — LinkedIn OAuth + Auto-post hebdomadaire (Claude 4.5)
- **Demande utilisateur** : 2026-02-26 — « On veut pouvoir poster automatiquement sur LinkedIn une fois par semaine, avec validation par WhatsApp avant publication. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24au + Iter43-fix24av
- **Détail** :
  - OAuth 2.0 standard (openid + profile + email + w_member_social + w_organization_social) avec refresh token rotation
  - Backend : `routes/linkedin.py` (config + authorize + callback + post + list), `routes/linkedin_autopost.py` (cron weekly avec Claude Sonnet 4.5)
  - Frontend : `pages/admin/sections/LinkedInSection.jsx` (config UI, composer, feed, scheduler hebdomadaire avec validation WA)
  - Cron : `_scheduled_linkedin_autopost` minute-check (publie au jour/heure configurés)
  - Validation WhatsApp : Liluvine envoie brouillon → user répond OK/STOP/REGEN
- **Tests** : 8 pytest. **8/8 PASS**.

## S073 — Twitter (X) OAuth + posts
- **Demande utilisateur** : 2026-02-26 — « On peut faire la même chose sur X et Facebook comme tu le suggères »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ax
- **Détail** :
  - OAuth 2.0 **avec PKCE** (S256), scopes `tweet.read tweet.write users.read offline.access`
  - Backend : `routes/twitter.py` (~330 LOC). Post text ≤ 280 chars + image optionnel via v1.1 media/upload. Refresh token rotation (tokens valides 2h).
  - Frontend : `pages/admin/sections/TwitterSection.jsx` (config, composer, feed récent)
- **Tests** : 6 pytest. **6/6 PASS**.

## S074 — Facebook Page OAuth + posts
- **Demande utilisateur** : 2026-02-26 — Idem S073
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ax
- **Détail** :
  - OAuth standard + **Long-lived token exchange** (60 jours) + **Page Access Token** via `/me/accounts`
  - Backend : `routes/facebook.py` (~290 LOC). Post text via `/{page-id}/feed`, photo via `/{page-id}/photos`
  - Frontend : `pages/admin/sections/FacebookSection.jsx` (config, list pages, pick active page, composer, feed)
  - Scopes : `pages_show_list pages_manage_posts pages_read_engagement public_profile email`
- **Tests** : 7 pytest. **7/7 PASS**.

## S075 — Multi-canal cross-posting Liluvine (LinkedIn → X + FB)
- **Demande utilisateur** : 2026-02-26 — « Cross-poster automatiquement le post LinkedIn généré aussi sur X et Facebook »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ax (extension de S072)
- **Détail** :
  - 2 checkboxes dans `LinkedInSection` : `also_post_twitter` (texte tronqué à 270 chars), `also_post_facebook` (texte intégral)
  - Le cron `_scheduled_linkedin_autopost` publie sur LinkedIn d'abord, puis cross-poste sur les canaux activés. Échec d'un canal n'empêche pas les autres.
  - Audit complet dans `db.linkedin_autopost_history` avec statut par canal.
- **Tests** : 4 pytest. **4/4 PASS**.

## S076 — Officines Geolocation via OpenStreetMap Nominatim
- **Demande utilisateur** : 2026-02-26 — « Géolocaliser automatiquement nos officines à partir de leur nom + ville pour les afficher sur une carte »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24aw
- **Détail** :
  - Backend : `routes/officines_geocode.py`. Cascade Google Places API (si `google_maps_api_key` configuré) → fallback OSM Nominatim (gratuit, 1 req/sec, real User-Agent)
  - Endpoints : `GET /admin/geocode/config`, `POST /admin/officines-registry/geocode-batch`, `POST /admin/officines-registry/{id}/geocode`
  - Country bias configurable (`geocode_country_bias`, défaut `BF`)
  - Settings stockent `latitude_source` (`google_places` | `osm_nominatim` | `manual`) pour audit
- **Tests** : 8 pytest. **8/8 PASS**.

## S077 — Google Calendar Watch API (Phase 2 push sync)
- **Demande utilisateur** : 2026-02-26 — « Nous finirons par Google Watch API » (sync temps réel)
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ay
- **Détail** :
  - Backend : `routes/google_calendar_watch.py` (~280 LOC). `events.watch` + webhook public `/api/google/calendar/webhook` avec validation `X-Goog-Channel-ID` + `X-Goog-Channel-Token`
  - Sync incrémental via `syncToken`. Gestion `410 Gone` (syncToken expired → réinit)
  - Cron `_scheduled_gcal_watch_renewal` toutes les 6h (renouvelle si expiration < 24h)
  - Frontend : `pages/admin/sections/GoogleCalendarWatchPanel.jsx` (status, start/stop/force-sync)
- **Tests** : 7 pytest. **7/7 PASS**.

## S078 — 3 bugfix P0 : Liluvine KPIs / LinkedIn 500 / Facebook redirect URI
- **Demande utilisateur** : 2026-02-26 — 3 bugs signalés en PROD : (1) synthèse Liluvine à 0 partout, (2) LinkedIn callback 500, (3) Facebook redirect URI bloqué sur preview.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az (round 1)
- **Détail** :
  - **Liluvine** : `routes/synthese.py` — noms de collections corrigés (`tickets`→`support_tickets`, `sms_outbox`→`sms_messages`, `wa_outbox`→`whatsapp_messages`, `suivis`→`user_suivis`, `payments`→`payment_transactions`). Champ `opened_at` pour tickets. Nouveau KPI `bird_sms_sent`. Prompt reformaté en liste FR lisible. `run_synthese_test` expose `kpis` pour debug.
  - **LinkedIn** : callback enveloppé dans `try/except` global. `_userinfo` et `_list_admin_organizations` tolérants à toute exception (pas seulement HTTPException).
  - **Facebook** : callback aussi wrappé. UI `FacebookSection.jsx` rendu éditable (input `redirect_uri` + boutons Auto / Cet env).
- **Tests** : 10 pytest `test_iter71_bugfixes.py`. **10/10 PASS**.

## S079 — Datetime tz fix LinkedIn + Twitter/LinkedIn boutons Auto/Cet env
- **Demande utilisateur** : 2026-02-26 — « Erreur inattendue durant la callback LinkedIn : can't subtract offset-naive and offset-aware datetimes » + Twitter redirect URI figé sur preview.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az (round 2)
- **Détail** :
  - **LinkedIn datetime bug** : `created_at` lu depuis Mongo est tz-naive par défaut (motor `tz_aware=False`). Promu en UTC-aware avant subtraction avec `_now_dt()`.
  - **Twitter UI** : ajout `<input>` éditable pour `redirect_uri` + boutons **Auto** (clear override) + **Cet env** (préremplit avec `window.location.origin`).
  - **LinkedIn UI** : mêmes boutons ajoutés pour cohérence (avant : seul un bouton Copy existait).
- **Tests** : validation curl (override save/clear, datetime tz-naive accepté).

## S080 — Google Maps API Key UI dans Admin Settings
- **Demande utilisateur** : 2026-02-26 — « Où se configure l'API KEY Google Maps ? » (le champ existait en backend mais n'avait pas d'UI)
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az (round 3)
- **Détail** :
  - Nouvelle section « Google Maps (Géocodage des Officines) » dans `AdminSettings.jsx` après Google Calendar
  - Input masqué pour `google_maps_api_key` (déjà dans `GET_MASK_FIELDS`)
  - Input pour `geocode_country_bias` (défaut `BF`)
  - Lien vers console GCP avec instructions (activer Geocoding API + Places API)

## S081 — Facebook « Tester App ID/Secret » (validation pré-OAuth)
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-c
- **Détail** : Endpoint POST /api/admin/facebook/test-config qui appelle `grant_type=client_credentials` avec les creds enregistrés → renvoie l'App Access Token si valide, sinon fb_error_message exact. Bouton vert 🧪 dans FacebookSection.jsx.

## S082 — Rotation garde Samedi 12h00 + toggle Admin Settings
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-d
- **Détail** : `garde_rotation_mode` ∈ {saturday_noon (défaut), monday_midnight (legacy)}. `_saturday_noon_week_year`, `_next_rotation_iso`, `_current_garde_week`. Toggle dans `AdminGardePlanning.jsx`. **Bug critique de dates** (affichait Mon→Sun au lieu de Sat→Sat) fixé en Iter43-fix24az-e.

## S083 — ContactGroupChips dans WA/SMS unitaire + conversation
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-d / e
- **Détail** : Composant réutilisable dans SendModal WA/SMS et dans ConversationModal (fenêtre 24h). Multi-toggle immédiat pour admin/superviseur/moderateur, lecture seule sinon. Bordure rouge.

## S084 — Reset planning année + filtre groupe garde + suppression groupe vide
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-e
- **Détail** :
  - Backend : `DELETE /admin/officines-registry/garde-planning/year/{year}` (déclaré AVANT la route `{year}/{week}` — sinon shadow → 422) ; `DELETE /admin/officines-registry/garde-groups/{N}` avec 409 si non vide.
  - Frontend : bouton `garde-reset-year-btn` dans AdminGardePlanning ; dropdown `filter-garde-group` (groupe en garde marqué rouge) + `delete-empty-garde-group` dans AdminOfficinesRegistry.
  - Bornes de période affichées correctement en table (Début/Fin au lieu de Du lundi/Au dimanche).

## S085 — Module Production pour tenants Fabricant
- **Demande utilisateur** : 2026-02-26 — « Nouveau rôle 'Fabricant' avec sidebar réduite (Caisse, GRH, Officines RO, Catalogue, Production). Module Production : intrants (matières premières, eau, électricité, main d'œuvre, amortissement…), recettes multi-variantes, prix de revient auto, marge 42% par défaut, marge↔prix bidirectionnel, export PDF. Simple à utiliser pour des personnes d'un certain âge. »
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26) — testing_agent 100% backend + 100% frontend
- **Fix associé** : Iter43-fix24az-f
- **Détail** :
  - **Backend** : nouveau `routes/production.py` (~500 LOC). Collections `production_intrants` + `production_recipes`. 7 catégories d'intrants (raw_material, packaging, water, electricity, labor, amortization, other). Endpoints CRUD + settings + 2 exports PDF (reportlab). Access control `_require_fabricant_admin` : role admin/superviseur ET business_type=fabricant du tenant primaire (via lookup parent client_id).
  - **Modèle** : `User.business_type` ajouté à `UserCreateAdmin`, `UserUpdateAdmin`, `UserPublic`. Persisté dans `admin_create_client`. `SettingsUpdate.production_default_margin_pct`.
  - **Frontend** : nouveau `Production.jsx` (~600 LOC) avec 3 tabs (Recettes, Intrants, Paramètres). Calcul temps réel `useMemo` (coût batch, coût unitaire, marge, prix public, bénéfice). Toggle bidirectionnel marge↔prix. Modal Recette avec sélection cochable d'intrants + qté. Modal Intrant avec catégorie+unité+coût.
  - **Sidebar Fabricant** : `PortalLayout.jsx` — `fabricantAllowedPaths` (allowlist stricte : /portal/cash, catalog, hr, production, /admin/officines-registry). Redirection non-admin autorisée pour fabricant superviseur sur officines-registry.
  - **Admin Clients** : dropdown `business-type-select` dans AdminClients.jsx.
- **Tests** : 6/6 pytest (`test_iter43_fix24az_f_production.py`) : 403 non-fabricant, CRUD intrants, calcul recette, settings, export PDF, /auth/me expose business_type. Testing agent : Fabricant sidebar 5 links strictement, non-fabricant admin 29 links sans Production, /portal/production 3 tabs OK, calcul temps réel validé, PDF exports OK.

## S105 — Badge sidebar live "WhatsApp Silent Drops" (indicateur santé en un coup d'œil)
- **Proposée le** : 2026-07-22 (finish Iter43-fix24az-w)
- **Statut** : 🔵 PROPOSÉE (en attente décision utilisateur — utilisateur a demandé de la noter)
- **Détail** :
  - Ajouter un badge discret dans `SidebarNav.jsx` qui clignote en rouge (petit dot + counter) lorsque `GET /api/admin/wa-silent-drops/stats` retourne `threshold_reached === true`.
  - Polling léger toutes les 60 s sur l'endpoint (déjà admin-only, très rapide car COUNT sur `wa_silent_drops`).
  - Click sur le badge → navigation directe vers `/admin/settings#s-wa-silent-drops` pour investigation.
- **Bénéfice** : évite à l'admin de devoir ouvrir AdminSettings pour vérifier l'état. Signal immédiat quand Meta rejette silencieusement des messages (token expiré, quota, template non approuvé).
- **Estimation** : ~15 min (nouveau composant `<WaDropsBadge />` + fetch + navigate). Zéro impact perf (polling admin only).
- **Fichiers à toucher** : `SidebarNav.jsx` (ou composant équivalent qui affiche la nav admin), nouveau `WaDropsBadge.jsx`.

## S104 — WhatsApp Silent Drops : surveillance + alertes email/WA
- **Demande utilisateur** : 2026-07-22 — « oui implémente dans une section de AdminSettings » (validation de la suggestion post-fix S103).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-07-22)
- **Fix associé** : Iter43-fix24az-w
- **Détail** :
  - **Backend** : nouveau module `routes/wa_silent_drops.py` avec 5 endpoints admin (`list`, `stats`, `config`, `test-alert`, `purge`) + observer callback `record_and_notify` injecté dans `attach_whatsapp_helpers(on_silent_drop=…)`.
  - **Logique** : quand `_wa_send_text` détecte un 2xx sans `message_id` (silent drop Meta), le ctx est enregistré dans `db.wa_silent_drops` (TTL 30 jours). Si `wa_alert_enabled=True` ET `count(drops_in_window) >= threshold` ET cooldown écoulé → alerte email + WhatsApp envoyée à tous les destinataires configurés.
  - **Config persistée** (`settings.global`) : `wa_alert_enabled` (bool), `wa_alert_threshold` (default 5), `wa_alert_window_minutes` (default 15), `wa_alert_cooldown_minutes` (default 60), `wa_alert_emails` (liste), `wa_alert_wa_phones` (liste E.164 digits-only), `wa_alert_last_sent_at` (auto).
  - **Sanitisation** : emails invalides droppés, phones normalisés en digits-only ≥ 6 chars.
  - **Frontend** : `WaSilentDropsSection.jsx` intégrée dans `AdminSettings.jsx` sous ancre `s-wa-silent-drops`. UI : 3 stat cards (15m/1h/24h avec highlight rouge si seuil atteint), toggle activation, 3 champs numériques (threshold/window/cooldown), 2 textareas destinataires, boutons Save/Test-alert/Refresh/Purge, table des 20 derniers drops.
- **Tests** : 11 pytest (`test_iter43_fix24az_w_wa_silent_drops.py`) : stats defaults, config PUT sanitise/valide/reject-empty, list ordering, test-alert (0 + N destinataires), purge, observer insert, threshold trigger (spies mockés), cooldown short-circuit, disabled short-circuit. **Testing agent iteration_88 = 100% (39/39), 0 issue**.

## S103 — Safety net auto-split WhatsApp (>4096 chars silent-drop Meta)
- **Demande utilisateur** : 2026-07-22 — « on doit le faire pour tous les messages retournés/envoyés par Liluvine sous WhatsApp » (post prod bug `!garde` texte vide).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-07-22)
- **Fix associé** : Iter43-fix24az-v
- **Détail** :
  - **Root cause** : WhatsApp Cloud API cappe le body texte à 4096 chars. Meta renvoyait `200 OK` avec `message_id: null` (silent drop) pour les payloads plus longs → utilisateurs recevaient un message VIDE. Symptôme sur `!garde` en prod (>30 officines → seule l'image arrivait).
  - **Fix centralisé** (couvre tous les callers WA) : nouveau helper `_wa_split_long_text(text, max_len=3800)` dans `routes/whatsapp_helpers.py` avec priorité de split (a) marqueur invisible `_WA_SPLIT_HINT = "\u2063\u2063"` (hint sémantique inséré par le caller) → (b) paragraphes `\n\n` → (c) lignes `\n` → (d) hard cut au max_len.
  - **`_wa_send_text()` auto-split** : tout message > 3800 chars est découpé en envois séquentiels ; seul le premier chunk porte `reply_to_message_id`. Log `logger.warning` si l'API renvoie `2xx` sans `message_id` (télémétrie pour S104). Retourne un dict enrichi avec `message_ids: [...]`, `parts_sent`, `parts_failed`, `parts_total`.
  - **`_build_garde_reply()`** : insère le `_WA_SPLIT_HINT` entre bloc principal et bloc d'appui pour un split sémantique. Budget dynamique par section (~3200 chars) → ajoute `_…et N autre(s) — liste complète :_ {site_url}/garde` quand dépassé.
- **Bénéfice** : plus jamais de silent drop >4096 sur WhatsApp. Le safety net couvre TOUS les callers sans modification côté caller (`cashier`, `ad_banners`, `download_approvals`, `liluvine_hr_wa`, `liluvine_reactions`, `liluvine_pro`, `liluvine_business_rag`, `liluvine_wa_autoreply`).
- **Tests** : 7 pytest (`test_iter43_fix24az_v_wa_text_truncation.py`) : short=1 chunk, hint respecté, split \n\n / \n / hard cut, préservation contenu, hint inséré par `_build_garde_reply`, lien site appendé quand budget dépassé. **Testing agent iteration_87 = 100% (28/28)**.

## S102 — Liluvine Extended : Native WA Media + Contact Timeline + CSV Bulk + Auto-suggest + TikTok Privacy toggle
- **Demande utilisateur** : 2026-07-22 — « où trouver le toggle 'privé' pour publier sur TikTok en privé? » + 4 tâches liées Liluvine Reactions (médias natifs WA, historique templates par contact, création templates Meta + upload CSV, auto-suggestion depuis messages non-traités).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-07-22)
- **Fix associé** : Iter43-fix24az-p
- **Détail** :
  - **Native WA Media** : `try_reply_ad_template` appelle désormais `_wa_send_media(from, kind, public_url=url, caption=text)` quand un template a `response_media_url`. Rendu pro dans WhatsApp mobile (image/vidéo directement affichée, plus de lien à cliquer). Fallback texte+URL si l'envoi natif échoue.
  - **Contact Timeline** : nouvelle collection `liluvine_contact_interactions` (kind ad_template / fuzzy_cmd, template info, matched_score, inbound/response text, timestamps). Endpoint `GET /api/me/contacts/{cid}/liluvine-history`. UI : bouton `contact-liluvine-<id>` sur chaque contact ouvre `LiluvineTimelineModal` avec badges par type + score.
  - **CSV Bulk Upload** : `POST /admin/liluvine/reactions-templates/bulk-csv {csv, dry_run?}` — colonnes name/trigger_text/response_text/trigger_variations(|)/response_media_url/response_media_kind/active. Détection auto `,` ou `;` (Excel FR). UI `LiluvineReactionsSection.jsx` : panneau CSV avec file input + textarea + template exemple + prévisualiser/importer.
  - **Meta Template Guide** : bloc collapsible dans LiluvineReactionsSection avec instructions détaillées pour créer le template Meta `rdv_reminder_1h_fr` (UTILITY, fr, 4 vars patient/médecin/heure/motif).
  - **Auto-suggest** : hook `record_unmatched_message` dans `autoreply_to_inbound` capture les messages entrants free-text non-matchés (dédup par `normalized_body`, count incrémenté). Endpoints `GET /admin/liluvine/unmatched-suggestions`, `POST .../{sid}/convert`, `DELETE .../{sid}`. Toggle `unmatched_capture_enabled`. UI : panneau Suggestions (ambre) avec Convert (inline form) + Dismiss.
  - **TikTok Privacy Toggle** : panneau `tiktok-privacy-panel` (Story Studio → Paramètres) avec 4 radio SELF_ONLY/MUTUAL_FOLLOW_FRIENDS/FOLLOWER_OF_CREATOR/PUBLIC_TO_EVERYONE + badge dynamique. Badge `tiktok-current-privacy-badge` dans le panneau "Comptes TikTok" affiche le mode actif avec libellé explicite.
- **Tests** : 11 nouveaux pytest (`test_iter43_fix24az_p_liluvine_reactions_ext.py`) : native media call assertion + text-only fallback + contact-history 200/404 + suggestions CRUD lifecycle + CSV comma/semicolon/dry_run/missing-cols + config toggle + auth gates. **Total 45/45 PASS**. Testing agent iteration_85 : 100% backend + 100% frontend.

## S101 — Liluvine Reactions & Ad Auto-Replies (fuzzy + templates + auto-contact)
- **Demande utilisateur** : 2026-07-21 — « détection floue des commandes WhatsApp (faute de frappe), réponses automatiques aux publicités Facebook, ajout automatique des nouveaux contacts au groupe par défaut ».
- **Statut** : 🟢 IMPLÉMENTÉE (2026-07-21)
- **Fix associé** : Iter43-fix24az-o
- **Détail** :
  - **Fuzzy command matching** (`/app/backend/routes/liluvine_reactions.py`) : détecte les intents malgré fautes/espaces/ponctuation (`! garde`, `pharmacies de garde`, `garde pharmacie`) via normalisation NFD sans accent + regex ponctuation + `difflib.SequenceMatcher`. Bonus +90 si synonyme contenu littéralement. Seuil configurable (50-95%, défaut 70%). 7 commandes connues avec synonymes.
  - **Ad reply templates** (collection `liluvine_ad_templates`) : CRUD `/api/admin/liluvine/reactions-templates` + variations pour matcher plusieurs formulations. Match exact prioritaire, puis fuzzy. Compteurs `received_count`/`replied_count` atomiques. Support media URL (v1 concat, v2 native → S102). Commande `!reactions` renvoie stats formatées.
  - **Auto-add contacts** : config `auto_add_new_contacts` + `default_new_contact_group_id`. Insertion silencieuse dans `directory_contacts` avec `tags=["auto-liluvine"]`, `source="liluvine_auto"`. Skip si numéro déjà existant.
  - **Frontend** : `LiluvineReactionsSection.jsx` (~400 LOC) : toggles config + slider seuil + sélecteur groupe + CRUD templates + modal éditeur + table stats live.
- **Tests** : 13 pytest (`test_iter43_fix24az_o_liluvine_reactions.py`) : unit fuzzy/normalisation/matching + integration CRUD admin. 13/13 PASS.

## S100 — Module Planning consultations médecins avec SSE temps réel + rappels WA 1h avant RDV
- **Demande utilisateur** : 2026-07-18 — « Module Planning avec calendar temps réel pour les médecins » + upgrade Uvicorn PROD pour éviter CF 520.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-07-18 → 2026-07-21)
- **Fix associé** : Iter43-fix24az-m + Iter43-fix24az-n
- **Détail** :
  - **Backend Planning** (`/app/backend/routes/planning.py`, ~330 LOC) : webhook public `/api/webhooks/planning/{secret}` (upsert idempotent), endpoints admin config (secret + URL + payload sample), `/me/planning/doctors` + `/me/planning/appointments`.
  - **SSE Server-Sent Events** (remplace polling 15s) : `GET /api/me/planning/stream?token=<JWT>&medecin_id=` avec auth query param. Envoie `hello`, `ping` toutes les 20s, `created`/`updated` sur webhook insertion. Reconnexion auto avec backoff (2s/4s/8s), fallback polling 30s après 3 échecs. Badge visuel Live/Off.
  - **Rappels WA 1h** : cron `planning_wa_reminders_5min` toutes les 5min. Fenêtre `[now+55min, now+65min]` + `patient_phone` + pas de `reminder_sent_at`. Template avec placeholders `{patient}` `{medecin}` `{start_time}` `{motif}`. Endpoint admin `/admin/planning/reminders/run` pour trigger manuel.
  - **Frontend** : `Planning.jsx` (~340 LOC) — grille horaire 08h-20h UTC + liste RDV, filtre médecin, ligne rouge live, RDV passés grisés, SSE badge, toast sur nouveau RDV. `PortalLayout.jsx` : sidebar réduite à Planning uniquement pour `tracked_role="Médecin"`. Route `/portal/planning`.
  - **Uvicorn PROD tuning** : `--timeout-keep-alive 65 --limit-concurrency 1000` ajouté dans `/etc/supervisor/conf.d/supervisord.conf`.
- **Compte test** : `medecin-test@sawali-test.com` / `Medecin@2026` + 4 RDVs seedés du jour.
- **Tests** : 27 pytest planning + 20 pytest SSE/rappels = **47 tests PASS**. Index Mongo : unique `(tenant_id, code_clinique, medecin, patient, start_at)`.

## S099 — Fix cross-tenant leak P0 + WhatsApp dedup + Cloudflare 520 mitigation + Local Media Import
- **Demande utilisateur** : 2026-07-18 — retest bugs P0/P1 (cross-tenant leak, duplication recette copie-3) + diagnostic CF 520 + import local médias dans StoryStudio/MetaIntegration/MediaGenerator.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-07-18)
- **Fix associé** : Iter43-fix24az-l retest
- **Détail** :
  - **Cross-tenant leak fix (P0)** : `admin_appointments`, `admin_interventions`, `admin_documents` (server.py lignes 7768/7822/7920) reçoivent désormais le branchement `_is_super_admin` ↔ `_resolve_visible_client_ids`. Chaque tenant ne voit que ses propres données.
  - **Duplication recette « (copie 2) »** : `create_recipe`/`update_recipe`/`duplicate_recipe` dans `production.py` wrappent le nom dans `re.escape()` avant le `$regex` (parenthèses = littéral).
  - **WhatsApp inbound deduplication** : `whatsapp_webhook_incoming` (server.py:16895) court-circuite lorsqu'un `wa_message_id` est déjà présent en base. Index sparse `wa_message_id_sparse` au boot.
  - **Cloudflare 520 mitigation** : middleware `request_timing_middleware` (server.py:305-355) log tout endpoint > 5s + header `X-Process-Time`. PDF exports (`production.py::export_recipes_pdf`, `export_single_recipe_pdf`) passent par `asyncio.to_thread` pour ne pas bloquer l'event loop.
  - **Local media import** : composant `LocalMediaImporter.jsx` (~195 LOC) intégré dans `MediaGenerator.jsx`, `MetaIntegration.jsx`, `StoryStudio.jsx`. Endpoint admin `POST /api/admin/story-studio/library/upload` (~100 LOC) mirror vers Emergent Object Storage.
- **Tests** : 48 pytest cumulés (validation cross-tenant 18 + wa-dedup 3 + story-upload 5 + validation 18 + iter79 dup 1 + me-media-library 7) — 100% PASS.

## S098 — Google Calendar Watch API (Phase 2 push sync temps réel)
- **Demande utilisateur** : 2026-02-26 — « Nous finirons par Google Watch API » (synchronisation temps réel des changements externes).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ay
- **Détail** :
  - **Backend** (`/app/backend/routes/google_calendar_watch.py`, ~280 LOC) : `GET/POST/DELETE /admin/google/calendar/watch` (status/start/stop), `POST /admin/google/calendar/sync-now` (force sync incrémental via `syncToken`), `POST /api/google/calendar/webhook` (endpoint public Google, vérifie `X-Goog-Channel-ID`/`Token`, 403 si mismatch, retourne toujours 200). Gère `sync_token expired (410 Gone)`. Cron 6h `_scheduled_gcal_watch_renewal` renouvelle si expiration < 24h. Mappe les events Google vers `db.appointments` avec `google_event_id`, `attendees`, `status=cancelled` pour suppressions.
  - **Frontend** (`GoogleCalendarWatchPanel.jsx`, ~200 LOC) : badge Active/Inactive, expiration + heures restantes, webhook URL avec bouton Copier, boutons Démarrer/Arrêter/Forcer un sync, affichage dernier résultat (créés/MAJ/supprimés).
- **Tests** : 7 pytest (`test_iter43_fix24ay_gcal_watch.py`) : status initial, auth admin, webhook rejette sans/mauvais headers, start/sync fail sans connexion.

## S097 — Résolution GPS officines (Google Maps API + OSM Nominatim fallback)
- **Demande utilisateur** : 2026-02-26 — « Bouton Résoudre géolocalisation, parcours Google Maps pour chaque pharmacie sélectionnée et récupère ses coordonnées GPS ».
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24aw
- **Détail** :
  - **Backend** (`/app/backend/routes/officines_geocode.py`, ~250 LOC) : 2 providers automatiques — **Google Places API** si `google_maps_api_key` configurée (meilleure couverture pharmacies) sinon **OSM Nominatim** (gratuit, 1 req/sec respecté). Endpoints `GET /admin/geocode/config`, `POST /admin/officines-registry/geocode-batch`, `POST /admin/officines-registry/{id}/geocode`. Persistence : `latitude`, `longitude`, `latitude_source`, `latitude_resolved_at`, `latitude_resolved_query`, `latitude_resolved_formatted_address`.
  - **Frontend** (`AdminOfficinesRegistry.jsx`) : bouton CYAN « 🌍 Résoudre géoloc (N) » (visible si >0 officines sélectionnées) + checkbox overwrite + `GeocodeResultModal` (stats Traitées/Résolues/Échecs/Ignorées + liste détaillée).
- **Tests** : 7 pytest.
- **Note importante** : OSM a peu de pharmacies en Afrique de l'Ouest. Recommandation : configurer une clé Google Maps.

## S096 — Twitter (X) + Facebook + Multi-canal auto-post Liluvine (LinkedIn → X → FB)
- **Demande utilisateur** : 2026-02-26 — « On peut faire la même chose sur X et Facebook comme tu le suggères ».
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ax
- **Détail** :
  - **Twitter OAuth 2.0 avec PKCE S256** (`twitter.py`, ~330 LOC) : config admin, authorize/callback, `/tweets` (text ≤280 + image via v1.1 upload), `/tweets` list 10 derniers, refresh token rotation 2h. Scopes `tweet.read tweet.write users.read offline.access`.
  - **Facebook Long-lived Token** (`facebook.py`, ~290 LOC) : OAuth standard + exchange 60j + Page Access Token via `/me/accounts`. `/pages` list, `/active-page` selection, `/posts` create (text via `/{page-id}/feed` ou photo via `/photos`). Scopes `pages_show_list pages_manage_posts pages_read_engagement public_profile email`.
  - **Multi-canal** (`linkedin_autopost.py`) : toggles `linkedin_autopost_also_post_twitter`/`_also_post_facebook`. Helper `_publish_multi_channel` publie LinkedIn (toujours) + Twitter/FB (si activés). `_shorten_for_twitter` tronque à 270 chars. WhatsApp reply OK résume LinkedIn URN + tweet_id + fb post_id.
  - **Frontend** : `TwitterSection.jsx` + `FacebookSection.jsx` + toggles multi-canal dans `LinkedInSection.jsx`.

## S095 — LinkedIn OAuth complet + Auto-post hebdomadaire (Liluvine) + UX redirect_uri
- **Demande utilisateur** : 2026-02-26 — « Pour LinkedIn implémente c et d » + « OK implémente cette suggestion d'engagement marketing » (auto-post hebdo).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24au + Iter43-fix24av + Iter43-fix24au-fix1
- **Détail** :
  - **LinkedIn OAuth** (`linkedin.py`, ~520 LOC) : config admin, authorize/callback, member + organization posts, refresh auto, cleanup states. Scopes `openid profile email w_member_social r_member_social w_organization_social r_organization_social`.
  - **UX redirect_uri fix** : endpoint `/preview-redirect-uri` + bandeau ambre `linkedin-redirect-warning` affichant le URI EXACT calculé côté serveur + bouton Copier — évite le mismatch `sawalismartsystems.com` vs preview.
  - **Auto-post hebdomadaire** (`linkedin_autopost.py`, ~440 LOC) : Claude Sonnet 4.5 génère un post promotionnel chaque semaine. 2 modes — `auto` (publie immédiat) ou `wa_approval` (envoi brouillon WhatsApp → réponse OK/STOP/REGEN). Cron minutely timezone Africa/Abidjan + idempotency guard 60 min. Hashtags fallback si Claude omet.
  - **Frontend** : `LinkedInSection.jsx` (~600 LOC) — config, connexion pop-up, composer, historique, auto-post hebdo.
- **Credentials user** : LinkedIn App ID `77rg7lu8v2hd3w` (masked secret).
- **Tests** : 8 pytest LinkedIn + 7 pytest + 1 skip LLM auto-post.

## S094 — VIDAL Favoris par utilisateur + Copier le code
- **Demande utilisateur** : 2026-02-26 — « Bouton 📋 Copier le code sur chaque ligne VIDAL + liste Favoris ».
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24at
- **Détail** :
  - **Backend** (`vidal_favorites.py`) : collection `vidal_favorites` unique `(user_id, vidal_id)`. Endpoints `GET/POST/DELETE /api/vidal/favorites`.
  - **Frontend** (`Vidal.jsx`) : `FavoritesProvider` (Context), `CopyCodeButton` + `FavoriteToggle` sur AtomFeedViewer + ResultTable, nouvel onglet **Favoris** (5e tab) avec Copier + Fiche + Retirer.
- **Tests** : 3 pytest.

## S093 — Validation TikTok App `sawalismartsystems` : Privacy/TOS + Title exact
- **Demande utilisateur** : 2026-02-26 — TikTok a rejeté l'app (titre non exact + Privacy/TOS doivent être des URLs séparées).
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24as
- **Détail** :
  - **Titres exacts** : `<title>sawalismartsystems — SAWALI SMART SYSTEMS Software Engineering</title>` + meta `og:site_name="sawalismartsystems"` + `Home.jsx` `document.title` + `Privacy.jsx` `sawalismartsystems Privacy Policy` + nouvelle page `TermsOfService.jsx` `sawalismartsystems Terms of Service`.
  - **Routes** : `/privacy-policy` + `/terms-of-service` (+ alias `/privacy` + `/terms`).
  - **Footer** : liens + « App ID : sawalismartsystems ».
- **Action utilisateur** : Save to GitHub + redéployer PROD + resoumettre app TikTok.

## S092 — Diagnostic Webhook Meta amélioré + Simulateur pipeline inbound
- **Demande utilisateur** : 2026-02-26 — « Diagnostic souscription Webhook Meta retournait 'subscribed_apps exception:' sans détail + messages WA entrants de certains utilisateurs ne sont plus reçus + centre messagerie manque des messages traités par l'AI ».
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24ar
- **Détail** :
  - **Token probe préalable** : `GET /me` (cheap) détecte immédiatement un token expiré/invalide (code 190). Court-circuite avec message actionnable « 🔑 Régénérez un System User Token permanent ». Retourne `token_probe.ok`, `http_status`, `raw_response_preview`, `error_type`.
  - **Bouton Re-souscrire désactivé** si token invalide (tooltip explicatif).
  - **Simulateur inbound** : `POST /admin/whatsapp/simulate-inbound` synthétise un payload Meta valide et route via le VRAI handler `whatsapp_webhook_incoming`. Vérifie le pipeline `webhook → whatsapp_messages → inbox → notifications` SANS dépendre de Meta. Retourne `inserted`, `webhook_log`, `ai_reply`, `hint`.
  - **UI** : panneau `WaSimulateInboundPanel` dans Admin Settings.
- **Tests** : 8 pytest (token 190, exception réseau, 0 apps, config manquante, non-JSON, persistance, diagnostic, validation E.164).

## S091 — Google Calendar OAuth PKCE fix + Test connexion + Health Monitor cron
- **Demande utilisateur** : 2026-06-17 — Après validation consentement Google : « Aucun refresh_token reçu. (Détail Google : Missing code verifier.) » + besoin d'un bouton pour tester la connexion + monitoring périodique.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06-17)
- **Fix associé** : Iter43-fix24an + Iter43-fix24ao + Iter43-fix24ap
- **Détail** :
  - **PKCE fix** (`google_calendar.py`) : `get_auth_url()` persiste `flow.code_verifier` dans `settings.google_oauth_code_verifier`. `exchange_code()` le lit et l'inclut dans le POST `/token`. Cleanup one-shot après succès. Surface `error_description` Google.
  - **Test Connexion** : `GET /api/admin/google/test-connection` appelle `gcal.list_upcoming_events(3)` → retourne `{ok, events_count, events, calendar_id}` ou `{ok:false, reason, message, error_type}`. UI : bouton 🧪 « Tester connexion » (visible si connecté).
  - **Health Monitor cron 4h** : `_scheduled_integration_health` (à *:35 Africa/Abidjan) teste GCal + Meta Webhook subscribed_apps. Persiste dans `integration_health_checks`. Alerte WhatsApp au `integration_health_alert_wa_phone` avec throttle 12h. Endpoints `/admin/integrations/health-check` + `/history`.
  - **UI** : `IntegrationHealthSection.jsx` — bouton « Lancer un check », toggle alertes, historique 10 derniers.
- **Tests** : 3 pytest PKCE + 3 pytest test-connection + 5 pytest health monitor.

## S090 — `!garde` footer/image/URL site + Code produit VIDAL entre parenthèses + Images par commande WA
- **Demande utilisateur** : 2026-06-17 — « Bouton `!garde` doit afficher footer + URL site + image capture » + « Code produit VIDAL absent des résultats WhatsApp/UI » + « Image ne doit plus être jointe à toutes les commandes WhatsApp ».
- **Statut** : 🟢 IMPLÉMENTÉE (2026-06-17)
- **Fix associé** : Iter43-fix24al + Iter43-fix24am + Iter43-fix24aq
- **Détail** :
  - **`!garde` footer/URL/image** : `_build_garde_reply` lit `garde_reply_footer` + `garde_reply_site_url` + URL toujours ajoutée. Helper `_wa_send_image` (2ème message type=image) accepte URL HTTPS OU base64. 4 nouveaux settings `garde_reply_footer/site_url/image_url/image_caption`.
  - **VIDAL parser robuste** : `_parseAtomEntries` avec 4 stratégies en cascade (`getElementsByTagName("vidal:id")` → localName scan → URN digits → regex outerHTML). Affichage code entre parens **uniquement si numérique**.
  - **WA VIDAL results** : `_format_vidal_data_for_wa` extrait `(title, vidal_id)` par entry via regex. Affichage `1. DOLIPRANE 100 mg pdre p sol buv en sachet-dose (*5485*)`.
  - **Images WA per-command** : dispatcher reconnaît `wa_cmd_<id>_image_url` (override), `wa_default_cmd_image_url` (défaut), `garde_reply_image_url` (legacy compat). Priorité per-command > legacy garde > default. `SettingsUpdate` en `extra="allow"` (Pydantic v2).
  - **UI** : `WaCommandImagesSection.jsx` (Admin Settings S058f) — image par défaut + image spécifique par commande (auto-listée depuis `/admin/vidal/actions` + 4 builtins). Badge « ✓ configurée » par override.
- **Tests** : 7 pytest backend + 6 jest frontend (parser multi-stratégies).



## S089 — VIDAL Webhook Proxy (mode passerelle bidirectionnel)
- **Demande utilisateur** : 2026-02-26 — « Toutes les requêtes VIDAL (même celles reçues de Liluvine) exécutent un webhook paramétrable en POST et retournent un JSON résultat. La requête POST envoie à une URL externe (sortant) un JSON dont le body contient l'URL exécutée par la requête (POST/GET) et reçoit sur un webhook dédié (entrant) la réponse JSON de ce Webhook externe. »
- **Choix utilisateur** :
  - 1.a (synchrone bloquant, timeout configurable)
  - 2.c (pas de signature HMAC pour le moment)
  - 3.c (pas de sécurité entrante pour le moment)
  - 4.a (fallback direct VIDAL quand webhook désactivé)
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-k
- **Détail** :
  - **Backend** `/app/backend/routes/vidal.py` :
    - Ajout de 3 champs dans `settings.global` : `vidal_webhook_enabled`, `vidal_webhook_outbound_url`, `vidal_webhook_timeout_seconds` (default 30, plage 5-300 s).
    - `_load_config()` retourne les 3 champs + `_dispatch_callback_url()` retourne l'URL absolue de callback dynamiquement (priorité : `PUBLIC_APP_URL` > `PUBLIC_BASE_URL` > `SAWALI_PUBLIC_BASE_URL` > fallback `https://sawalismartsystems.com`).
    - `_dispatch_via_webhook(cfg, method, path, params, body, ...)` :
      1. Génère un `correlation_id` (UUID)
      2. Enregistre une entrée `asyncio.Event` dans le map `_correlations` (in-memory)
      3. POST une enveloppe JSON à `webhook_outbound_url` : `{correlation_id, tenant_id, user_email, method, url, path, params, body, headers, callback_url, timestamp, vidal_mode}`
      4. `await asyncio.wait_for(ev.wait(), timeout)` — bloque jusqu'à callback ou timeout
      5. Retourne la réponse (`{_data|raw|_error}`) mise dans le map par le callback endpoint
    - `_vidal_call()` route vers `_dispatch_via_webhook` quand `cfg.webhook_enabled=True`, sinon fallback direct comportement existant.
    - Nouveau endpoint `POST /api/vidal/webhook/callback` : body `{correlation_id, status_code, content_type, body|raw, error}` ; look-up + `event.set()` ; renvoie 404 si correlation inconnue, 422 si champ manquant.
    - Nouveau endpoint `POST /admin/vidal/webhook/test` : déclenche un aller-retour de test (GET /products?q=doliprane via webhook) pour valider la config.
    - `_correlations` in-memory + `_correlation_lock` asyncio (adapté single-instance ; multi-instance = future work).
  - **Frontend** `S058VidalSection.jsx` :
    - Nouveau panneau « Proxy Webhook (mode passerelle) » avec checkbox Activer, URL sortante, Timeout callback, et URL de callback (readonly + bouton copier).
    - Bouton « Tester le webhook » (dégrisé quand webhook activé) — affiche le résultat inline (succès/erreur).
    - Icônes Webhook + Info depuis lucide-react.
    - data-testids : `vidal-webhook-panel`, `vidal-webhook-enabled`, `vidal-webhook-outbound-url`, `vidal-webhook-timeout`, `vidal-webhook-callback-url`, `vidal-test-webhook-btn`, `vidal-webhook-test-result`.
- **Tests** :
  - Pytest backend 6/6 PASS (`test_iter43_fix24az_k_vidal_webhook.py`) : config exposée, persistence, callback rejette correlation inconnue (404) ou champ manquant (422), aller-retour bout-en-bout avec serveur echo Python local, timeout après webhook_timeout_seconds sans callback.
  - Aucune régression : 23 tests VIDAL + Production PASS.
- **Note pour l'utilisateur** :
  - L'URL de callback affichée est absolue et se met à jour automatiquement selon l'environnement (preview vs prod).
  - Sécurité entrante à ajouter : HMAC-SHA256 sur `X-SAWALI-Signature` en itération suivante (S089-P2).
  - Multi-instance : la map `_correlations` étant in-memory, si le backend a plusieurs pods et que la callback tombe sur un pod différent de celui qui a émis, la callback ne trouvera pas la corrélation. Solution future : persistance MongoDB + polling au lieu d'asyncio.Event (S089-P3).

## S088 — Fabricant landing + logo local (fix CDN 403) + og:image
- **Demande utilisateur** : 2026-02-26 — Trois observations après tentative de déploiement TikTok :
  1. Le fabricant n'a pas de dashboard, il faut donc atterrir directement sur `/portal/cash` au lieu de `/portal`.
  2. L'URL du logo TikTok (aprzh1m4_LogoSawaliSmartSystems-removebg.png) retourne HTTP 403 « Access Denied » — le logo n'est pas visible sur Privacy/Terms/browser tab.
  3. Recommandation TikTok : le logo doit aussi s'afficher dans l'onglet de navigation. Idéalement hébergé sur sawalismartsystems.com plutôt qu'une CDN externe.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-i
- **Détail** :
  - Nouveau composant `PortalIndex` dans `App.js` — redirige les fabricants vers `/portal/cash` via `<Navigate>` avant d'atteindre `ClientDashboard`.
  - Téléchargement local du logo qui fonctionne (`2bjpkh5i_Autre Logo SAWALI.png`, 1024×1024) et hébergement dans `/app/frontend/public/{logo.png,favicon.ico,logo192.png,logo512.png}` — servis désormais depuis `https://sawalismartsystems.com/*` en prod.
  - `index.html` : `<link rel="icon">` pointant vers les fichiers locaux avec plusieurs tailles (16/32/48/64/192/512). `og:image` et `twitter:image` mis à jour vers `https://sawalismartsystems.com/logo512.png`.
  - `Privacy.jsx` + `TermsOfService.jsx` : `<img src="/logo.png">` (path relatif).
- **Tests** :
  - Curl HTTP 200 sur les 3 assets (`logo.png`, `favicon.ico`, `logo192.png`).
  - Playwright : `document.querySelector("[data-testid='app-icon-logo']").naturalWidth === 1024` et `complete === true` sur les 2 pages légales.
  - Fabricant landing : navigation vers /portal termine à /portal/cash (URL finale confirmée).

## S087 — TikTok App Icon + Privacy/TOS visibility + Dosage-based cost model + Officines greyed for Fabricant
- **Demande utilisateur** : 2026-02-26 — 3 demandes combinées :
  1. TikTok review a rejeté l'app parce que l'icône n'est pas visible dans le browser tab ni en haut des pages Privacy/Terms.
  2. Les coûts d'intrants sont donnés par unités de 100 ml — refactoring : dosage_number+dosage_unit sur la recette, multiplier appliqué à tous les intrants, 4 décimales.
  3. Griser l'option « Officines » de la sidebar du Fabricant.
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-h
- **Détails** :
  - **Task 1 (TikTok)** :
    - `/app/frontend/public/index.html` — ajout de `<link rel="icon">`, `<link rel="shortcut icon">`, `<link rel="apple-touch-icon">` pointant vers le logo SAWALI officiel (Emergent CDN).
    - `/app/frontend/src/pages/public/Privacy.jsx` — nouveau bloc `<div data-testid="app-icon-header">` avec `<img data-testid="app-icon-logo">` + label « sawalismartsystems » en haut de l'en-tête.
    - `/app/frontend/src/pages/public/TermsOfService.jsx` — même bloc en haut.
    - Résultat : favicon visible sur tous les onglets, et l'icône + le nom sont affichés en haut des 2 pages légales, conformément à l'exigence TikTok.
  - **Task 2 (Dosage)** :
    - Backend `/app/backend/routes/production.py` :
      - `RecipePayload` : ajout de `dosage_number` (Optional[float]) + `dosage_unit` (Optional[str] default "ml"). `variant_label` devient auto-dérivé.
      - `RecipeIntrantIn` : `quantity` conservé pour rétrocompat mais ignoré si `dosage_number > 0`.
      - `_compute_recipe` : deux branches — NEW (`unit_cost × dosage_number` par intrant) vs LEGACY (`quantity × unit_cost` ancien).
      - `create_recipe` + `update_recipe` : persistent dosage_number/dosage_unit, auto-génèrent variant_label = "N unit".
      - Précision : arrondi cost_price/intrants_total_batch à 4 décimales, public_price/margin_pct à 2.
      - PDF exports : quantité affichée = dosage_number pour recettes new-model, sinon quantité legacy. Coût unitaire affiché à 4 décimales.
    - Frontend `/app/frontend/src/pages/portal/Production.jsx` :
      - `RecipeModal` : nouveau champ « Dosage (volume) » (input numérique, step=0.0001) + « Unité » (dropdown ml/g/L/kg/unit). `variant_label` retiré (auto-dérivé côté backend).
      - Suppression du champ per-intrant `quantity`. Chaque intrant sélectionné affiche sa contribution live `= unit_cost × dosage_number`.
      - Migration douce : si on ouvre une recette legacy, `variant_label` est parsé (regex `50 ml`) pour pré-remplir dosage_number/dosage_unit.
      - `IntrantModal` : `step="0.0001"` sur le champ coût unitaire, label « CFA / 1 unité » (précision 4 décimales).
      - `IntrantsTab` : coût unitaire affiché à 4 décimales.
      - `LiveKpi` : affichage à 4 décimales.
      - `AnalyticsTab` : PieChart dosage-aware — pour chaque recette, contribution catégorie = `unit_cost_snapshot × dosage_number` (new) ou `quantity × unit_cost_snapshot` (legacy).
  - **Task 3 (Officines grisée)** :
    - `PortalLayout.jsx` : le lien Officines pour tenants Fabricant reçoit `disabled: true` + `disabledReason` au lieu d'être cliquable.
    - Nouveau flag générique `disabled` dans le loop `links.map` — applique `opacity-40 cursor-not-allowed`, empêche la navigation (`e.preventDefault()`), affiche un toast d'information, ajoute un badge **N/A** gris.
    - `data-testid="badge-disabled--admin-officines-registry"` posé automatiquement.
- **Tests** :
  - Pytest backend 8/8 PASS (7 anciens + nouveau `test_dosage_based_cost_model` qui vérifie : dosage×unit_cost×3 intrants, précision 4 décimales, auto-dérivation variant_label "50 ml"/"100 ml", branche legacy si pas de dosage_number).
  - Smoke screenshot preview OK : modal recette montre Dosage 100 + ml + contribution live par intrant (= 3.1 pour PEG7 à 0.031 CFA/ml × 100 ml).
  - Privacy + Terms : favicon dans le head + icône visible en tête de page.
  - Sidebar Officines : badge N/A + curseur interdit visible.
- **Note importante** : le multiplicateur est le volume du produit directement (option b confirmée par l'utilisateur). Cela suppose que les coûts d'intrants sont saisis comme prix par 1 unité (ex : 3,5 CFA/ml pour ICARIDINE). Les intrants « fixes » comme les flaconnages ne doivent PAS être cochés dans la recette (ils ne scalent pas avec le volume). Le user est libre d'organiser sa data en conséquence.

## S086 — Onglet Analyses (Recharts) dans le module Production
- **Demande utilisateur** : 2026-02-26 — « oui implémente cette suggestion » (après proposition d'ajouter des graphiques Recharts au module Production)
- **Statut** : 🟢 IMPLÉMENTÉE (2026-02-26)
- **Fix associé** : Iter43-fix24az-g
- **Détail** :
  - Nouveau 3ème onglet `Analyses` dans `/app/frontend/src/pages/portal/Production.jsx` avec 4 blocs de visualisation :
    - **6 KPI cards** : recettes, coût moyen, prix public moyen, marge moyenne, intrants distincts, coût cumulé batches.
    - **3 Highlight cards** : recette la plus rentable (bénéfice/unité), coût de revient le plus élevé, marge la plus faible.
    - **BarChart** (Recharts) : coût de revient vs prix public vs bénéfice par recette, avec **sélecteur multi-toggle** (chips cochables) + boutons Tout/Aucune. Défaut : top-10 les plus coûteuses cochées.
    - **PieChart** donut : répartition **agrégée** des coûts d'intrants par catégorie (7 catégories) sur toutes les recettes, avec pourcentages sur le donut + panneau « Détail par catégorie » listant montants CFA et pourcentages exacts.
    - **LineChart** : évolution des coûts de revient + prix public dans le temps (recettes triées par `created_at`), utile pour détecter l'inflation ou l'amélioration des marges.
  - Composants extraits : `AnalyticsTab`, `HighlightCard`, `ChartTooltip`, `LineChartTooltip`.
  - Data-testids : `production-tab-analytics`, `production-analytics`, `analytics-empty`, `analytics-bar-chart`, `analytics-pie-chart`, `analytics-line-chart`, `analytics-highlight-{top|expensive|low}`, `analytics-select-{all|none}`, `analytics-recipe-toggle-{id}`, `analytics-category-list`.
  - **Note** : le LineChart utilise `created_at` (proxy chronologique) car les coûts historisés ne sont pas conservés — un vrai historique de snapshots serait une feature future (P3).
- **Tests** :
  - Pytest `test_analytics_payload_shape` (nouvelle) — valide que `list_recipes` expose `intrants[].category_snapshot`, `quantity`, `unit_cost_snapshot`, `intrants_total_batch`, `created_at` et `summary.{avg_cost_price, avg_public_price, avg_margin_pct}`. → 7/7 tests production pytest passent.
  - Smoke screenshot preview OK — les 3 charts se rendent correctement avec 5 recettes seed (fab-analytics@sawali-test.com / Analytics@2026).
  - Testing agent frontend (à lancer post-implémentation) — vérifie navigation entre les 4 tabs, sélecteur BarChart interactif, coupure gracieuse quand 0 recette (empty state).



---

## Comment référencer une suggestion
- **Dans le code** : `// Suggestion S007 — Plan IA (Claude Haiku 4.5)` ou `# Suggestion S007 — Plan IA`
- **Dans une PR/commit** : `S007: implement AI campaign plan`
- **Dans une demande utilisateur** : « j'aimerais qu'on revoie la suggestion S008 » ou « pour S007 j'aimerais aussi… »

## Comment ajouter une nouvelle suggestion
Lorsque l'assistant propose une nouvelle suggestion, il doit :
1. Incrémenter le compteur (S010, S011, …)
2. Ajouter une nouvelle section ici avec : date, statut (PROPOSÉE), détail, bénéfice, dépendances éventuelles
3. Référencer ce numéro dans la suggestion (ex : « Voici la suggestion S010 : … »)
4. Au moment de l'implémentation, basculer le statut à IMPLÉMENTÉE et noter le fix associé
