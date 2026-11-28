# Loois Mobile — application Android de SAWALI Smart Systems

Application Kotlin / Jetpack Compose (minSdk 26, Android 8+). Publiée sur ShuyahStore.

## Ce qu'elle fait (version 1.0)
- **Appareil** : au premier lancement, elle s'enregistre auprès de SAWALI (état « Interdit »). L'administrateur la renseigne et l'autorise dans
  *Paramètres → « 📱 Appareils Android — Loois mobile »* (utilisateur, zone, base de données, code client, IP vue par le serveur).
- **Connexion** : identifiant et mot de passe Loois, vérifiés chez le client par SAWALI (zone et base imposées par l'administrateur). Aucun mot de passe n'est stocké.
- **Historique de Caisse** : reçus d'un jour (un caissier ne voit que les siens), détail d'un reçu, totaux, colonnes triables ; recherche par numéro (reçu « R-… » ou facture d'hospitalisation « 0461/2026 ») ; caissier, VID, réglé, visé. Le détail montre le montant total, le PPC et les parts assuré / assureur. Le SUPERVISEUR (administrateur de l'espace) peut changer « Réglé », « Visé », la date de vente (jamais après la date du jour, heure conservée) et les deux parts (aucun recalcul automatique : leur somme doit faire le montant total ; confirmation, écriture HFSQL, relecture, journal) : seule écriture de l'application.
- **Corrections de Reçus** (lecture seule) : reçus dont la validité propre à la prestation diffère de celle de la clinique, avec la date d'expiration effective.
- **Réseau** : Internet détecté → SQL distantes via SAWALI ; sinon les **passerelles locales** du client, dont SAWALI donne les adresses et un ticket de 72 h (version 1.1) ; une adresse saisie à la main reste possible. Voir `docs/PASSERELLE_MOBILE.md` du dépôt Loois.

## Pointage d'inventaire hors connexion (lot M9, version 1.8.0)
Ouvert depuis le premier écran (« Pointage d'inventaire »), SANS autorisation de l'appareil ni compte Loois : le commerce est reconnu par le QR code
de l'inventaire (créé sur SAWALI ou dans l'Espace pointage) et par son mot de passe.
- **Une connexion, une seule fois** : scanner le QR code (lecteur intégré, zxing) → mot de passe du commerce → l'inventaire (lieux, produits, langue)
  est gardé dans le téléphone (`filesDir/pointage/<jeton>.json`).
- **Comptage sans Internet** : prénom + lieu, puis dictée (reconnaissance vocale d'Android, hors connexion si le pack de langue est installé ;
  français ou anglais selon le commerce) ou clavier ; le nom du produit s'affiche ; « Suivant » enregistre dans le téléphone, « Annule » retire la dernière.
- **Fichiers** : « Exporter » partage le fichier de pointage du téléphone (Bluetooth, WhatsApp, câble, Fichiers) ; le responsable « Importe » les
  fichiers des autres téléphones : fusion SANS doublon (chaque saisie a un uid), fichier d'un autre inventaire refusé.
- **Envoi à SAWALI** quand une connexion existe : par paquets de 200, chaque saisie garde le prénom, l'appareil et l'heure de qui a compté.
- **Souscription** (lot M9.1, SAWALI lot 500) : le comptage n'est permis que pendant une souscription vérifiée du commerce (semaine, mois, année,
  illimité) ; l'écran « Ma souscription » (clé + mot de passe du commerce) montre l'état, ouvre le clavier du téléphone avec la séquence USSD et envoie
  la référence de la transaction ; expirée : export, fusion et envoi des saisies déjà faites restent possibles.
Code : `Pointage.kt` (logique pure, dictée, fichiers, fusion, textes FR / EN), `PointageVM.kt` (stockage, réseau), `EcransPointage.kt` (écrans).
Tests : `PointageTest.kt` ; contrat `contrat/pointage_acces.json` et `pointage_saisies.json` produits par
`ECRIRE_CONTRAT_ANDROID=1 pytest backend/tests/test_pointage_telephone_routes_lot496.py`.

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
