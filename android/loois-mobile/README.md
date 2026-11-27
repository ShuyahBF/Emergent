# Loois Mobile — application Android de SAWALI Smart Systems

Application Kotlin / Jetpack Compose (minSdk 26, Android 8+). Publiée sur ShuyahStore.

## Ce qu'elle fait (version 1.0)
- **Appareil** : au premier lancement, elle s'enregistre auprès de SAWALI (état « Interdit »). L'administrateur la renseigne et l'autorise dans
  *Paramètres → « 📱 Appareils Android — Loois mobile »* (utilisateur, zone, base de données, code client, IP vue par le serveur).
- **Connexion** : identifiant et mot de passe Loois, vérifiés chez le client par SAWALI (zone et base imposées par l'administrateur). Aucun mot de passe n'est stocké.
- **Historique de Caisse** : reçus d'un jour (un caissier ne voit que les siens), détail d'un reçu, totaux, colonnes triables.
- **Corrections de Reçus** (lecture seule) : reçus dont la validité propre à la prestation diffère de celle de la clinique, avec la date d'expiration effective.
- **Réseau** : Internet détecté → SQL distantes via SAWALI ; sinon adresse du serveur local définie dans les Paramètres (passerelle Loois, voir « Limites »).

## Architecture
`Stockage` (réglages + jeton chiffré par le Keystore Android) · `Reseau` (HTTP JSON, adresses autorisées) · `Modeles` (lecture des réponses, formats, tri) · `Etat` (ViewModel) ·
`Ecrans` (Compose). Côté SAWALI : `backend/routes/appareils_android.py` (registre) et `backend/routes/android_loois.py` (API ; requêtes HFSQL préparées côté serveur).
L'application ne contient AUCUNE clé SQL ni requête SQL libre : SAWALI fabrique les requêtes et les fait exécuter par une machine du client (file « SQL à distance »).

## Tests
`gradle :app:testDebugUnitTest` — formats, tri, adresses, écrans (Robolectric, sans téléphone) et **contrat avec SAWALI** : les fichiers de `app/src/test/resources/contrat`
sont les vraies réponses du serveur (produites par `backend/tests/test_android_loois_lot475.py`).

## Construire l'APK
Kit Android (SDK 34) + Java 17+. Signature avec la clé PERMANENTE de ShuyahStore, lue dans les variables d'environnement
`ANDROID_KEYSTORE_FILE`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` (jamais dans le dépôt).
`gradle :app:assembleRelease` → `app/build/outputs/apk/release/app-release.apk`. Sans clé, l'APK est « unsigned » : ne jamais le livrer.
Numérotation : lots de SAWALI = nombres simples (477…) ; lots de Loois Mobile = préfixe M (M1, M2…) ; lots de Loois Windows = préfixe L. À chaque publication : `versionApp`, `codeVersion` et `lotApp` dans `app/build.gradle.kts` sont mis à jour (la date de compilation est automatique).

## Limites connues
- Mode « serveur local » : l'application sait l'appeler (même API), mais la **passerelle HTTP du service Windows Loois** qui l'expose n'existe pas encore : à développer dans le dépôt Loois.
- Corrections de reçus : consultation des données ; pas d'affichage ni de régénération des PDF (champs mémo non transmis par le SQL à distance, PDF corrigés gardés en SQLite sur le réseau local).
- Zones prises en charge : Biolog (`docx=`) et Aizenta (`doc=`) pour la connexion ; la caisse n'existe que pour Biolog. e-Kol : pas encore.
