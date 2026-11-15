# Idées à programmer plus tard

Liste tenue à jour avec le propriétaire. Chaque idée garde sa date, son besoin, ce qui existe déjà et les questions ouvertes.

---

## 1. Projeter l'écran d'un téléphone / d'une tablette Android sur un téléviseur (15/11/2026)

### Besoin (propriétaire)
Appliquer à un téléphone ou une tablette Android **le même principe que le contrôle à distance de SAWALI** (« Prendre la main » : tout l'écran de l'ordinateur distant s'affiche dans le navigateur) : **tout le contenu affiché sur le téléphone s'affiche en streaming dans le navigateur web d'un téléviseur** (page `/tv`, comme pour les vidéos), **sans appareil auxiliaire** (ni Chromecast, ni boîtier).

Usages visés :
1. **Confort visuel** : une personne âgée projette son téléphone sur la télé pour voir en grand.
2. **Contrôle à distance** d'un téléphone / d'une tablette (assistance, dépannage).
3. **Formation** sur les 3 plateformes mobiles (auRor, Concentration, Personnel de maison), avec affichage sur télé.

### Ce qui existe déjà (à réutiliser)
- `backend/routes/controle_distance.py` (lot 131 et suivants) : consentement explicite de l'utilisateur, jetons à usage unique (empreinte SHA-256), relais WebSocket chiffré (`wss://…/api/ws/controle-distance`), mode « voir seulement » imposé par le serveur, journal de chaque session, trames binaires (tuiles JPEG), transport isolé dans la classe `Relais` (prévu pour un futur pair-à-pair).
- Visionneuse web du contrôle à distance (`AdminControleDistance.jsx`).
- Écrans TV (`/tv`, `tv-ecran.html`) : appairage par code, page plein écran pour navigateurs de télé anciens (webOS, Tizen), ordres lus toutes les 2 s, streaming des vidéos (lot 412 et suivants).
- Application Android : service d'accessibilité déjà utilisé par auRor (saisie du code secret USSD) ; clé d'appareil et enregistrement de l'appareil (agenda).

### Principe proposé
1. **Agent Android** (bibliothèque commune aux 3 applications) : capture de l'écran avec l'API système **MediaProjection** (service au premier plan de type « mediaProjection »), compression en images JPEG, envoi sur le **même WebSocket** que le contrôle à distance.
2. **Appairage** : la télé (page `/tv`) affiche un code ; le téléphone saisit le code (ou l'administrateur choisit la télé) ; session « voir seulement » créée avec les mêmes jetons à usage unique.
3. **Visionneuse télé** : une couche dans `tv-ecran.html` (comme la couche vidéo) qui dessine les images reçues (canvas, JavaScript simple compatible télés anciennes).
4. **Phase contrôle** (plus tard) : gestes tactiles envoyés au téléphone et rejoués par le service d'accessibilité (`dispatchGesture`), seulement en mode « contrôler ».

### Phases suggérées
- **Phase 1 — Projection simple** : téléphone → télé, « voir seulement », une application (Personnel de maison, la plus utile aux personnes âgées), JPEG à 5-10 images/s, réglable.
- **Phase 2 — Les 3 applications** + choix de qualité automatique selon la connexion (échelle 100/75/50/25 déjà prévue dans le protocole).
- **Phase 3 — Contrôle à distance** d'un téléphone depuis le navigateur du technicien (assistance), avec le consentement du propriétaire du téléphone.
- **Phase 4 — Formation** : une session, plusieurs télés / navigateurs en spectateurs ; mode « pointeur » (le formateur montre sans toucher).

### Points d'attention connus
- **Consentement système obligatoire** : Android affiche lui-même « Commencer l'enregistrement ou la diffusion ? » à CHAQUE session de capture. C'est voulu par Android, non contournable ; il s'ajoute à notre propre accord.
- **Écrans protégés** : une application qui se déclare « sécurisée » (FLAG_SECURE : banque, code secret) apparaît noire dans la capture. Les écrans de paiement et d'empreinte d'auRor devront être **volontairement exclus** de la projection (confidentialité du code secret).
- **Débit** : le relais passe par le serveur SAWALI (Render) : surveiller la bande passante ; la télé et le téléphone sur le même Wi-Fi pourraient plus tard s'échanger les images directement (WebRTC) pour alléger le serveur.
- **Compatibilité des télés** : JPEG sur canvas fonctionne partout ; la vidéo compressée (H.264, WebCodecs) est plus fluide mais dépend du modèle de télé.
- **Son** : la capture du son interne est limitée par Android (Android 10+, selon les applications) ; à traiter après l'image.
- **Batterie** : la capture continue consomme ; prévoir un bandeau visible « Projection en cours » et un arrêt en un geste.
- **Vie privée** : tout ce qui est à l'écran (messages, photos) apparaît sur la télé : bandeau permanent, arrêt facile, journal des sessions, jamais d'enregistrement par le serveur (comme aujourd'hui).

### Questions ouvertes
1. Qui peut lancer une projection : l'utilisateur seul, ou aussi un administrateur à distance (avec accord) ?
2. Une télé par client / par foyer, ou n'importe quelle télé appairée ?
3. Priorité : confort visuel (phase 1) ou assistance / formation (phases 3-4) ?
4. Faut-il le son dès la première version ?

### Décision du propriétaire
« On va programmer cette idée pour plus tard » (15/11/2026). Aucun développement lancé.
