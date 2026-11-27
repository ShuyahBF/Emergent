# Loois Mobile — application Android de SAWALI Smart Systems

Application Kotlin / Jetpack Compose (minSdk 26, Android 8+). Publiée sur ShuyahStore.

## Ce qu'elle fait (version 1.0)
- **Appareil** : au premier lancement, elle s'enregistre auprès de SAWALI (état « Interdit »). L'administrateur la renseigne et l'autorise dans
  *Paramètres → « 📱 Appareils Android — Loois mobile »* (utilisateur, zone, base de données, code client, IP vue par le serveur).
- **Connexion** : identifiant et mot de passe Loois, vérifiés chez le client par SAWALI (zone et base imposées par l'administrateur). Aucun mot de passe n'est stocké.
- **Historique de Caisse** : reçus d'un jour (un caissier ne voit que les siens), détail d'un reçu, totaux, colonnes triables ; recherche par numéro (reçu « R-… » ou facture d'hospitalisation « 0461/2026 ») ; caissier, VID, réglé, visé. Le détail montre le montant total, le PPC et les parts assuré / assureur. Le SUPERVISEUR (administrateur de l'espace) peut changer « Réglé », « Visé », la date de vente (jamais après la date du jour, heure conservée) et les deux parts (aucun recalcul automatique : leur somme doit faire le montant total ; confirmation, écriture HFSQL, relecture, journal) : seule écriture de l'application.
- **Corrections de Reçus** (lecture seule) : reçus dont la validité propre à la prestation diffère de celle de la clinique, avec la date d'expiration effective.
- **Réseau** : Internet détecté → SQL distantes via SAWALI ; sinon les **passerelles locales** du client, dont SAWALI donne les adresses et un ticket de 72 h (version 1.1) ; une adresse saisie à la main reste possible. Voir `docs/PASSERELLE_MOBILE.md` du dépôt Loois.

## Architecture
`Stockage` (réglages + jeton chiffré par le Keystore Android) · `Reseau` (HTTP JSON, adresses autorisées) · `Modeles` (lecture des réponses, formats, tri) · `Etat` (ViewModel) ·
`Ecrans` (Compose). Côté SAWALI : `backend/routes/appareils_android.py` (registre) et `backend/routes/android_loois.py` (API ; requêtes HFSQL préparées côté serveur).
L'application ne contient AUCUNE clé SQL ni requête SQL libre (la seule écriture, « Réglé » / « Visée » / parts d'un reçu par le superviseur, est fabriquée par le serveur : `sql_modifier_recu`) : SAWALI fabrique les requêtes et les fait exécuter par une machine du client (file « SQL à distance »).

## Tests
Aucun test ne contacte SAWALI (`AppViewModel.sansDemarrageReseau`) : sinon chaque test enregistrerait un faux appareil « robolectric » dans le registre de production.
`gradle :app:testDebugUnitTest` — formats, tri, adresses, écrans (Robolectric, sans téléphone) et **contrat avec SAWALI** : les fichiers de `app/src/test/resources/contrat`
sont les vraies réponses du serveur (produites par `backend/tests/test_android_loois_lot475.py`).

## Construire l'APK
Kit Android (SDK 34) + Java 17+. Signature avec la clé PERMANENTE de ShuyahStore, lue dans les variables d'environnement
`ANDROID_KEYSTORE_FILE`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` (jamais dans le dépôt).
`gradle :app:assembleRelease` → `app/build/outputs/apk/release/app-release.apk`. Sans clé, l'APK est « unsigned » : ne jamais le livrer.
Numérotation : lots de SAWALI = nombres simples (477…) ; lots de Loois Mobile = préfixe M (M1, M2…) ; lots de Loois Windows = préfixe L. À chaque publication : `versionApp`, `codeVersion` et `lotApp` dans `app/build.gradle.kts` sont mis à jour (la date de compilation est automatique).

## Limites connues
- Mode « serveur local » : la passerelle est dans le service Windows Loois (lot L1) ; elle n'a pas encore tourné sur une vraie machine Windows avec HFSQL : à essayer chez un client après `maj.ps1`.
- Corrections de reçus : consultation des données ; pas d'affichage ni de régénération des PDF (champs mémo non transmis par le SQL à distance, PDF corrigés gardés en SQLite sur le réseau local).
- Zones prises en charge : Biolog (`docx=`) et Aizenta (`doc=`) pour la connexion ; la caisse n'existe que pour Biolog. e-Kol : pas encore.
