# Instructions pour Mettre à Jour la Base de Données en Ligne

## 🎯 Objectifs
1. Rendre votre compte `jfrancois.ouoba@gmail.com` superviseur
2. Créer/mettre à jour le compte `admin.test@comptable.fr` comme superviseur

## 📋 Étapes à Suivre

### ÉTAPE 1 : Redéployer l'Application (OBLIGATOIRE)

**Pourquoi ?** Le code a été modifié pour que `admin.test@comptable.fr` soit automatiquement superviseur lors de l'inscription.

1. Dans Emergent, cliquez sur **"Deploy"**
2. Confirmez le redéploiement
3. Attendez 10-15 minutes
4. Votre site https://ledger-justifier.emergent.host sera mis à jour

### ÉTAPE 2 : Mettre à Jour Votre Compte Existant

Vous avez **3 options** pour mettre à jour `jfrancois.ouoba@gmail.com` :

#### Option A : Via l'interface (après redéploiement)

1. Sur https://ledger-justifier.emergent.host, créez un compte avec `admin.test@comptable.fr` / `Admin2024!`
2. Ce compte sera automatiquement **superviseur**
3. Connectez-vous avec ce compte
4. Allez dans **Paramètres > Utilisateurs**
5. Changez le rôle de `jfrancois.ouoba@gmail.com` en **Superviseur**

#### Option B : Script MongoDB (si vous avez accès à la base de données de production)

Si vous avez accès à votre base MongoDB en ligne via shell ou interface graphique :

```javascript
// Commande à exécuter dans le shell MongoDB
use votre_nom_de_base_de_donnees

db.users.updateOne(
  { email: "jfrancois.ouoba@gmail.com" },
  { $set: { role: "superviseur" } }
)

// Vérifier
db.users.findOne(
  { email: "jfrancois.ouoba@gmail.com" },
  { email: 1, nom: 1, role: 1, _id: 0 }
)
```

Ou utilisez le fichier `/app/update_superviseur_production.js` :

```bash
mongosh "votre_connection_string_production" < /app/update_superviseur_production.js
```

#### Option C : Contacter le support Emergent

Si vous n'avez pas accès direct à la base de données :

1. Contactez **support@emergent.sh**
2. Demandez-leur de mettre à jour le rôle de votre compte
3. Fournissez : email (`jfrancois.ouoba@gmail.com`), nouveau rôle (`superviseur`)

### ÉTAPE 3 : Créer le Compte Admin (après redéploiement)

1. Allez sur https://ledger-justifier.emergent.host
2. Cliquez sur **"Inscrivez-vous"**
3. Remplissez :
   - Nom : Administrateur Test
   - Email : `admin.test@comptable.fr`
   - Mot de passe : `Admin2024!`
4. ✅ Ce compte sera **automatiquement superviseur** grâce au code mis à jour

### ÉTAPE 4 : Vérifier

1. Déconnectez-vous
2. Reconnectez-vous avec `jfrancois.ouoba@gmail.com`
3. Vous devriez voir le bouton **"Paramètres"** en haut à droite
4. Si oui : ✅ Tout fonctionne !

## 🔑 Comptes Superviseurs Disponibles

Après redéploiement et mise à jour :

| Email | Mot de passe | Statut |
|-------|--------------|--------|
| jfrancois.ouoba@gmail.com | (votre mot de passe) | Nécessite mise à jour manuelle |
| admin.test@comptable.fr | Admin2024! | Superviseur automatique après création |

## ⚠️ Important

- **Sans redéploiement**, le compte `admin.test@comptable.fr` ne sera PAS automatiquement superviseur
- **Le redéploiement est OBLIGATOIRE** pour que les changements prennent effet
- Après redéploiement, videz le cache de votre navigateur (Ctrl+Shift+Suppr)

## 📞 Besoin d'Aide ?

Si vous rencontrez des problèmes, contactez-moi ou le support Emergent à support@emergent.sh
