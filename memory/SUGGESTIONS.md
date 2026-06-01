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
