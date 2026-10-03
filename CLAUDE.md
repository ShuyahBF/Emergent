# Règles permanentes du propriétaire (ShuyahBF)

Ces règles s'appliquent à TOUS les sites, projets et applications, existants
(SAWALI, Ster, adLyn, beAuthentik, …) et futurs. Elles font partie de la
méthode de travail par défaut, sans qu'il soit nécessaire de les redemander.

## Livraison et déploiement
- Après chaque mise à jour prête pour Render : fusionner automatiquement,
  puis informer le propriétaire dans le chat ET par e-mail HTML
  (jfrancois.ouoba@gmail.com) : date et heure, identification (dépôt, branche,
  commit, version, lot), périmètre, comment vérifier, à activer, points
  d'attention, reste à faire.
- Commits : auteur ET committer `ShuyahBF <jfrancois.ouoba@gmail.com>`,
  messages et commentaires en français, aucune mention d'IA ni de Co-Authored-By.
- Commentaires clairs sur chaque bloc de code (le propriétaire vient de WinDev).
- Ne jamais commiter, afficher ni envoyer de secret (clés, mots de passe,
  chaînes de connexion) : ils vont uniquement dans les variables
  d'environnement, saisies par le propriétaire.

## Version et lot (règles 1 et 2)
1. À chaque déploiement, le numéro de version ET le numéro de lot sont mis à
   jour (jamais une constante figée qui n'est plus incrémentée).
2. Version et lot sont toujours affichés sur les pages de connexion et dans
   le portail (barre latérale, en-tête ou pied de page de toutes les pages
   connectées), au format « Version X · Lot N (commit) ».
- Une seule source par plateforme :
  - SAWALI : `backend/lot.py` (LOT, LOT_LIBELLE), exposé par `/api/version` ;
    version = compteur de déploiements `1.N`. Modifier `lot.py` à chaque
    déploiement force aussi le redéploiement du serveur (Render ne redéploie
    un service à `rootDir` que si un fichier de son dossier change).
  - Ster : `frontend/src/version.js` (VERSION +1 à chaque déploiement,
    LOT = numéro de la PR fusionnée).
  - adLyn, beAuthentik : même principe (lot = numéro de la PR fusionnée).
- Nouveau projet : prévoir dès le départ cette source unique et l'affichage.

## Tableaux (règle 3)
- Sur TOUT tableau : ligne survolée = fond bleu clair transparent
  (`rgba(56, 189, 248, 0.16)`) ; ligne sélectionnée = fond orange clair
  (`#f6a35b`) avec police blanche.
- Mise en œuvre globale dans le CSS de chaque plateforme ; une ligne est
  sélectionnée si elle porte `ligne-selectionnee`, `aria-selected="true"`,
  `data-selected="true"`, ou si la case à cocher de sa première cellule est cochée.

## Attentes et chargements
- Toute attente longue (connexion, recherche…) affiche un toast « Patientez… »
  et une jauge circulaire transparente (arc qui tourne), comme sur SAWALI.
