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
  - **Notifications proactives** : Email + WhatsApp (canaux configurables, throttle 23h par niveau) envoyés dès passage en `warning` (par défaut 80%) ou `critical` (par défaut 95%). WA via `_wa_send_text` (numéro super-admin configuré).
  - **Configuration admin** : Nouvelle section `Universal Key Emergent — Seuils de consommation & alertes (S032)` dans `/admin/settings` (anchor `s-llm-budget-thresholds`) — 6 paramètres : `llm_budget_warning_pct`, `llm_budget_critical_pct`, `llm_budget_max_usd`, `llm_budget_notify_email`, `llm_budget_notify_wa`, `llm_budget_notify_wa_phone`. Validation stricte côté backend (50≤warn≤99, 60≤crit≤99, warn<crit, max>0).
- **Bénéfice** : élimine les coupures surprises du service IA — l'admin reçoit un préavis suffisant pour recharger la clé.
- **Endpoints** : `GET /api/admin/llm-health` enrichi des 13 nouveaux champs S032 (burn_rate_24h_usd, burn_rate_1h_usd, calls_24h, cumulative_month_usd, current_cost_usd, max_budget_usd, pct_used, projected_days_left, projected_exhaustion_at, warning_pct, critical_pct, status_level, cost_source).
- **Fichiers** : `backend/routes/llm_health.py` (compute_metrics + maybe_send_budget_warning_alerts), `backend/models.py:SettingsUpdate` (6 nouveaux champs), `backend/server.py` (validation + cron updated), `backend/routes/liluvine_pro.py` + `liluvine_wa_autoreply.py` (context propagé), `frontend/src/components/LlmHealthBanner.jsx` (4 niveaux visuels + métriques), `frontend/src/pages/admin/AdminSettings.jsx` (section S032).
- **Tests** : `backend/tests/test_siter39h_llm_burn_rate.py` (6/6 verts) — usage log + compute_metrics + bascule warning/critical/ok + endpoint exposes metrics + validation seuils + envoi email+WA + throttle 23h.

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
