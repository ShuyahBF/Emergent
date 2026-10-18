# SAWALI Admin sur Android (lot 243)

L'espace d'**administration** de SAWALI devient une application Android (APK). Seule l'administration est concernée
(pas le portail client). Tout se fait avec des pages web, sans Python, sans PowerShell, sans Android Studio.

## 1. Installer tout de suite, sans APK
Sur le téléphone, avec Chrome : ouvrir `https://sawalismartsystems.com/admin`, se connecter, puis menu ⋮ → **Installer l'application**.
Ou : SAWALI → **Paramètres** → rubrique **📲 Application Android d'administration** → bouton **Installer l'application d'administration**.

## 2. Fabriquer l'APK avec PWABuilder
1. Ouvrir **https://www.pwabuilder.com**.
2. Saisir l'adresse : `https://sawalismartsystems.com` puis cliquer **Start**.
3. Vérifier que « Manifest » et « Service Worker » sont verts.
4. Cliquer **Package for stores** puis **Android**.
5. Remplir :
   - Nom : `SAWALI Admin`
   - Identifiant du paquet (package) : `com.sawali.admin` (à ne plus jamais changer)
   - Adresse de départ : laisser celle proposée (`/admin?source=application`)
   - Signature : choisir **Create new** (PWABuilder crée la clé de signature).
6. Cliquer **Generate** et **télécharger le fichier ZIP**.
7. **Garder précieusement le ZIP** : il contient la **clé de signature** (fichier `.keystore`) et ses mots de passe.
   Sans eux, on ne peut plus mettre l'application à jour. Faire une copie dans un endroit sûr.
8. Dans le ZIP, un fichier `signing-key-info.txt` indique l'**empreinte SHA-256** du certificat.
   **Donner cette empreinte (et seulement elle) à Claude** : elle est ajoutée dans
   `frontend/public/.well-known/assetlinks.json`. Sans elle, l'application affiche une barre d'adresse en haut.
9. Installer le fichier `.apk` du ZIP sur le téléphone (autoriser « sources inconnues » si Android le demande).

## 3. Ce qu'il ne faut JAMAIS faire
- Ne jamais envoyer le fichier de clé (`.keystore`) ni ses mots de passe dans un message, un e-mail ou GitHub.
- Ne jamais écrire ces mots de passe dans le dépôt. Seule l'empreinte SHA-256 (publique) est à communiquer.

## 4. Avertissement de sécurité
- **L'APK ne protège pas l'accès** : il ouvre simplement le site d'administration. C'est la **connexion administrateur**
  (compte et mot de passe) qui protège les données.
- **Ne pas distribuer l'APK en dehors de l'équipe** (pas de Play Store public, pas de lien ouvert).
- Aucune donnée d'administration n'est gardée sur le téléphone : seule la page « Pas de connexion » est mémorisée.

## Contenu technique (pour mémoire)
- `frontend/public/manifest.json` : nom « SAWALI Admin », démarrage sur `/admin`, portée `/` (la connexion `/login` en fait partie), icônes.
- `frontend/public/sw.js` + `offline.html` : page « Pas de connexion » ; rien d'autre en cache ; API et temps réel non touchés.
- `frontend/public/.well-known/assetlinks.json` : lien site ↔ application (`[]` tant que l'empreinte n'est pas fournie).
- `frontend/public/icone-admin-*.png` : icônes tirées du logo SAWALI (192, 512, 512 « maskable »).
- Paramètres → **📲 Application Android d'administration** : état et bouton d'installation.
