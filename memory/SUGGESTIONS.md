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

## S025 — Workflow d'approbation pour télécharger des documents (REPORTÉ — à scoper)
- **Demande directe utilisateur** : 2026-02 (post-handoff)
- **Statut** : 🟡 REPORTÉE — scope à valider
- **Détail demandé** : Documents non-publics → jauge « En attente d'approbation… », WhatsApp template avec 2 boutons (Autoriser/Refuser) au numéro paramétré, réponse débloque ou annule le téléchargement.
- **Pourquoi reporter** : nécessite (a) un template Meta WhatsApp approuvé pour boutons quick-reply (délai de validation Meta), OU (b) un fallback via magic links texte WA. Touche à plusieurs intégrations (settings, WA send, webhook réception, collection `download_approvals`, frontend gate sur BrochuresWidget + PdfViewer + MeetingPDF). À chiffrer/scoper avec l'utilisateur (template Meta vs liens, durée d'expiration, audit log, multi-approbateurs ?).
- **Action attendue** : décision utilisateur entre template Meta officiel (officiel mais bloquant) ou magic links (rapide et fonctionnel sans validation Meta).

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
