# Lot 53 — SAWALI sans Emergent (Render)

Depuis le lot 53, le site ne dépend plus d'aucun service Emergent : ni la bibliothèque privée
`emergentintegrations` (index privé, installation impossible sur Render), ni la clé universelle
`EMERGENT_LLM_KEY`, ni le stockage objet `integrations.emergentagent.com/objstore`, ni les
scripts et images servis par Emergent.

## 1. Correspondance des remplacements

| Avant (Emergent) | Après (lot 53) | Clé |
|---|---|---|
| `emergentintegrations.llm.chat` : `LlmChat`, `UserMessage`, `ImageContent` | `backend/ia_client.py`, même interface : `with_model`, `with_params`, `with_max_tokens`, `send_message`, `send_message_with_tools` (usage réel), `send_message_multimodal_response`, `get_messages`, `_add_user_message`, `_execute_completion` | — |
| fournisseur `anthropic` (Claude) | SDK officiel `anthropic` (`AsyncAnthropic`, API Messages) | `ANTHROPIC_API_KEY` |
| fournisseur `openai` (traductions GPT) | SDK officiel `openai` | `OPENAI_API_KEY` |
| fournisseur `gemini` (traductions, images Nano Banana) | SDK `google-genai` (déjà installé) | `GOOGLE_GEMINI_API_KEY` |
| `OpenAIImageGeneration` | `ia_client.OpenAIImageGeneration` (`generate_images`, et `text_to_image` / `generate` appelées par Story Studio) | `OPENAI_API_KEY` |
| `OpenAIVideoGeneration` (Sora 2) | `ia_client.OpenAIVideoGeneration` : API REST `/v1/videos` (httpx) ; sans clé, erreur claire « Génération vidéo indisponible » | `OPENAI_API_KEY` |
| `OpenAISpeechToText` (dictée) | `ia_client.OpenAISpeechToText` (Whisper, SDK `openai`) | `OPENAI_API_KEY` |
| `emergentintegrations.payments.stripe.checkout` | `backend/paiement_stripe.py` : `StripeCheckout`, `CheckoutSessionRequest`, mêmes réponses, bibliothèque officielle `stripe` | `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET` |
| `storage.py` / `object_storage.py` → objstore Emergent | mêmes fonctions publiques, octets dans **Cloudflare R2** (boto3) | `R2_FICHIERS_*` |
| `os.environ.get("EMERGENT_LLM_KEY")` dans 20 fichiers | `cle_ia(fournisseur)` (`ia_client`) : clé du fournisseur, "" si absente | — |

Le paramètre `api_key` passé par les appelants à `LlmChat(...)` est ignoré : la clé est toujours
celle du fournisseur choisi par `with_model(...)`. Les erreurs sont levées en `ChatError`
(« Échec de l'appel IA (anthropic/<modèle>) : … », ou « Clé IA absente : définir ANTHROPIC_API_KEY »).

`backend/ocr_core/` (autorisation exceptionnelle du propriétaire) : seul l'appel IA de
`engine.call_llm` change (import `ia_client`, clé `ANTHROPIC_API_KEY`). Le reste est inchangé ;
`send_message_with_tools` renvoie l'usage réel, donc le coût de chaque analyse reste exact.

Images et documents envoyés à Claude : blocs `image` (type détecté sur les premiers octets :
JPEG, PNG, WEBP, GIF ; préfixe `data:…;base64,` accepté) et blocs `document` pour les PDF. Les
images passent avant le texte. Au-delà de 16 000 tokens de sortie (import de formulaires), la
réponse est reçue en flux. L'historique d'une conversation est gardé par instance de `LlmChat`.

## 2. Fichiers : convention des clés R2 (identique à « Migration vers Render »)

L'outil de migration (`backend/routes/migration_render.py`, lots 44 à 47) a copié les fichiers
d'Emergent dans R2 ainsi :

| Source chez Emergent | Clé R2 écrite par la migration |
|---|---|
| objet du stockage, chemin `<chemin>` (`stored_objects.storage_path`, `files.storage_path`, toute valeur `storage_path` ou `/api/files/...` de la base) | `<prefixe>/objets/<chemin>` |
| fichier du disque `UPLOAD_DIR/<rel>` (ex. `uploads/ai/<client>/<image>.png`) | `<prefixe>/uploads/<rel>` |
| fichier du disque `SNAPSHOTS_DIR/<rel>` | `<prefixe>/snapshots/<rel>` |

`<prefixe>` = `migration-AAAAMMJJ-HHMMSS` (affiché dans l'écran Migration, et en tête de
`manifest.json`). `<chemin>` = la valeur trouvée en base, sans `/` initial ni paramètres d'URL ;
normalement `sawali/...` (préfixe `APP_STORAGE_NAME`), parfois sans ce préfixe (la migration
garde la première forme rencontrée).

Le nouveau `storage.py` lit et écrit EXACTEMENT là :

- écriture : `R2_FICHIERS_PREFIXE/objets/<chemin de stockage>` (le chemin enregistré en base
  reste `sawali/...`, comme avant) ;
- lecture : `R2_FICHIERS_PREFIXE/objets/<chemin>` tel quel, puis avec et sans `sawali/`, puis
  dans les préfixes de `R2_FICHIERS_PREFIXES_SECONDAIRES` ;
- fichier absent du disque de Render (`/api/files/<id>`, `/api/files/ai/...`) : recherché dans
  `R2_FICHIERS_PREFIXE/uploads/<rel>` puis réécrit sur le disque.

Preuve : `tests/test_lot53_sans_emergent.py::test_convention_identique_a_la_migration_render`
exécute le VRAI code de migration (`_executer`) vers un bucket simulé, puis relit chaque fichier
avec le nouveau stockage, sans retraitement (objets avec et sans `sawali/`, fichiers du disque).

Repli de migration (paresseux) : si un objet manque dans R2 ET que `EMERGENT_LLM_KEY` est
encore définie, il est lu chez Emergent puis recopié dans R2 à la même clé. Sans cette clé,
aucun appel à Emergent (aucun blocage). À retirer une fois Emergent arrêté.

## 3. Variables du service backend (Render → sawali-backend → Environment)

Obligatoire = le site ne fonctionne pas correctement sans elle.

| Variable | Rôle | Obligatoire | Où l'obtenir |
|---|---|---|---|
| `MONGO_URL` | Base MongoDB Atlas | oui | Atlas → Database → Connect → Drivers (URI `mongodb+srv://…`) ; Network Access : 0.0.0.0/0 |
| `DB_NAME` | Nom de la base | oui (`smartsystems`) | celui de la base migrée |
| `JWT_SECRET` | Signature des sessions ; dérive aussi le chiffrement des clés e-mail et Story Studio, et signe les sauvegardes | oui, IDENTIQUE à l'ancien serveur | fichier chiffré des secrets de la migration (`secrets/env-secrets.enc.json`) |
| `LINK_JWT_SECRET` | Liens visiteurs / formations signés | conseillé (sinon dérivé de `JWT_SECRET`) | fichier des secrets |
| `JWT_ALGORITHM`, `JWT_EXPIRE_HOURS` | Algorithme et durée des sessions | non | fichier des secrets |
| `MIGRATION_COFFRE_CLE` | Clé du coffre des sauvegardes programmées | non (sinon `JWT_SECRET`) | fichier des secrets |
| `WA_PLANNING_RECAP_SECRET` | Liens des récapitulatifs de planning | non | fichier des secrets |
| `ANTHROPIC_API_KEY` | Claude : OCR des pièces et des listes de pointage, Liluvine, synthèses, traductions Claude, import de formulaires, santé IA | **oui** | console.anthropic.com → Settings → API Keys (et crédit : Settings → Billing) |
| `OPENAI_API_KEY` | Dictée (Whisper), images GPT et vidéos Sora (Story Studio, Médias IA), traductions GPT | non (fonctions indisponibles sans elle) | platform.openai.com → API keys |
| `GOOGLE_GEMINI_API_KEY` | Images Gemini (Nano Banana), traductions Gemini, `ai_media_9m` | non | aistudio.google.com → Get API key |
| `OCR_DEFAULT_MODEL` | Modèle OCR par défaut | non (`claude-sonnet-5`) | — |
| `R2_FICHIERS_BUCKET` | Bucket des fichiers (celui de la migration) | **oui** | Cloudflare → R2 ; nom saisi dans « Migration vers Render » |
| `R2_FICHIERS_PREFIXE` | Préfixe de la migration retenue (`migration-AAAAMMJJ-HHMMSS`) | **oui** | écran Migration (dernière sauvegarde terminée) ou `manifest.json` |
| `R2_FICHIERS_ACCOUNT_ID` | Compte Cloudflare | oui, sauf si `R2_SAUVEGARDES_*` ou `R2_STOCKS_*` du même compte | Cloudflare → R2 → Account ID |
| `R2_FICHIERS_ACCESS_KEY_ID`, `R2_FICHIERS_SECRET_ACCESS_KEY` | Jeton R2 (lecture ET écriture sur ce bucket) | idem | Cloudflare → R2 → Manage API tokens |
| `R2_FICHIERS_PREFIXES_SECONDAIRES` | Autres préfixes de migration, en lecture seule (virgules) | non | écran Migration |
| `R2_FICHIERS_ENDPOINT` | Point d'accès S3 particulier | non | — |
| `EMERGENT_LLM_KEY` | Repli de migration : lit chez Emergent un fichier absent de R2 puis le recopie | non — **à retirer après la bascule** | ancien serveur |
| `APP_STORAGE_NAME` | Préfixe des chemins de stockage | non (`sawali`, ne pas changer) | — |
| `SAUVEGARDE_AUTO_PHRASE` | Phrase de chiffrement de la sauvegarde quotidienne vers R2 | oui pour la sauvegarde quotidienne | à choisir et conserver hors ligne |
| `R2_SAUVEGARDES_ACCOUNT_ID`, `R2_SAUVEGARDES_ACCESS_KEY_ID`, `R2_SAUVEGARDES_SECRET_ACCESS_KEY` | Identifiants R2 des sauvegardes (repli : `R2_STOCKS_*`) | oui pour la sauvegarde quotidienne | Cloudflare → R2 |
| `R2_SAUVEGARDES_BUCKET`, `R2_SAUVEGARDES_PREFIXE` | Bucket et dossier des sauvegardes | non (`sawali-sauvegardes`, `sauvegardes-completes/`) | — |
| `PUBLIC_BASE_URL` | Adresse publique (liens, QR des reçus, OAuth) | oui : `https://sawalismartsystems.com` | — |
| `PUBLIC_APP_URL`, `REACT_APP_BACKEND_URL`, `BACKEND_PUBLIC_URL`, `PUBLIC_BACKEND_URL`, `SAWALI_PUBLIC_BASE_URL` | Mêmes usages (anciens noms lus par certains modules) | conseillé : même valeur | — |
| `CORS_ORIGINS` | Origines autorisées (virgules) | conseillé | domaine + `www` + adresse onrender du frontend |
| `SUPER_ADMIN_EMAIL` | Super-admin (maintenance, e-mails, alertes) | non (`admin@sawalismartsystems.com`) | — |
| `ADMIN_INIT_EMAIL`, `ADMIN_INIT_PASSWORD`, `ADMIN_INIT_NAME` | Premier compte, sur une base VIDE seulement | non | — |
| `RESEND_API_KEY` + `RESEND_EXPEDITEUR`, `BREVO_API_KEY`, `ZEPTOMAIL_API_KEY` (+ `ZEPTOMAIL_HOTE`), `EMAIL_EXPEDITEUR`, `PLATEFORME_SMTP_*` / `SMTP_*` (HOST, PORT, USER, PASSWORD, FROM_EMAIL, FROM_NAME, USE_TLS) | Repli d'envoi des e-mails si rien n'est réglé dans Paramètres (lot 52). Render bloque SMTP sur les offres gratuites | non (le réglage en base suffit) | resend.com, brevo.com, zeptomail.zoho.com |
| `STRIPE_API_KEY` (repli `STRIPE_SECRET_KEY`) | Paiements Stripe Checkout | oui si Stripe est utilisé | dashboard.stripe.com → Developers → API keys |
| `STRIPE_WEBHOOK_SECRET` | Signature des webhooks (`/api/webhook/stripe`) | oui si Stripe est utilisé (repli : réglage en base) | Stripe → Developers → Webhooks → endpoint → Signing secret |
| `ELEVENLABS_API_KEY` | Voix de synthèse | non | elevenlabs.io |
| `FAL_KEY` | Vidéos fal.ai (Story Studio) | non | fal.ai → Keys |
| `QDRANT_URL`, `QDRANT_API_KEY` | Recherche vectorielle Liluvine | non | cloud.qdrant.io |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STOCK_TABLE` | Synchronisation des stocks | non | supabase.com → Project Settings → API |
| `R2_STOCKS_*`, `R2_VIDAL_*` (ACCOUNT_ID, ACCESS_KEY_ID, SECRET_ACCESS_KEY, BUCKET) | Buckets stocks et Vidal | non | Cloudflare → R2 |
| `STOCK_SYNC_TOKEN` | Jeton de la synchronisation des stocks | non | fichier des secrets |
| `USD_TO_XOF_RATE` | Taux de change du coût OCR | non | — |
| `DISABLE_SCHEDULER` | `1` coupe le planificateur (répétition seulement) | non — NE PAS mettre le jour de la bascule | — |
| `CAPTCHA_BYPASS_HOSTS` | Hôtes dispensés de reCAPTCHA (tests) | non | — |
| `UPLOAD_DIR`, `UPLOAD_AI_DIR`, `SNAPSHOTS_DIR`, `EXPORTS_DIR`, `MEMORY_DIR`, `DOCS_DIR` | Dossiers (lot 49) ; par défaut dans le projet | non | — |
| `APP_VERSION`, `DEPLOY_ID` | Affichage de la version | non | — |
| `PYTHON_VERSION` | `3.11.11` (dans le Blueprint) | oui | — |

Frontend (sawali-frontend) : `REACT_APP_BACKEND_URL=https://sawalismartsystems.com` (figée au
build), `NODE_VERSION=22`.

## 4. Autres traces d'Emergent retirées

- `frontend/public/index.html` : script `assets.emergent.sh/scripts/emergent-main.js` et
  traceur PostHog du modèle Emergent (clé d'Emergent, enregistrement des sessions) retirés.
- `frontend/craco.config.js` / `package.json` : greffon « visual edits » (`@emergentbase`,
  téléchargé depuis `assets.emergent.sh`) retiré.
- `frontend/src/lib/brand.js` : logo et images de fond servis par le site (`/logo.png`,
  `/brand/*.jpg`) au lieu des serveurs d'images d'Emergent.
- Page produit partagée (aperçu) : logo par défaut `/logo.png` (l'ancienne image Emergent
  n'existe plus).
- `recaptcha.py` : plus de dispense automatique pour `*.preview.emergentagent.com` (en-têtes
  falsifiables) ; seule `CAPTCHA_BYPASS_HOSTS` compte.
- Bannière santé IA : instructions de recharge Anthropic au lieu de « Universal Key ».

## 5. Correctif OCR (listes de pointage)

`POST /api/ocr-pieces` déclarait `photos: Optional[List[UploadFile]]` : avec FastAPI 0.110,
cette forme n'est pas lue comme une liste et TOUT dépôt de photos était refusé (422).
Déclaré désormais `List[UploadFile] = File(None)` ; les tests `test_parcours_photos_telephone`
et `test_photos_refusees` (en échec au lot 52) passent.

## 6. Bascule : points de contrôle

1. Dernière « Migration vers Render » terminée → noter bucket et préfixe → `R2_FICHIERS_BUCKET`,
   `R2_FICHIERS_PREFIXE`.
2. Appliquer le Blueprint, renseigner les secrets (section 3), déployer.
3. `GET https://<backend>.onrender.com/api/health` → `{"status":"ok"}` ; journal :
   « [storage] R2 actif : bucket …, préfixe « migration-… » ».
4. Admin → santé IA → « Tester maintenant » : statut `ok` (sinon clé ou crédit Anthropic).
5. Ouvrir une pièce OCR existante (téléchargement) et une image de la médiathèque : lues depuis R2.
6. Déposer une liste de pointage (photos + JSON) : analyse, compte rendu, JSON complété.
7. Pointer le domaine sur sawali-frontend ; retirer `EMERGENT_LLM_KEY` dès qu'Emergent est arrêté.
