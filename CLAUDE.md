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
2. Affichage de la version (règle du 04/10/2026) :
   - page de connexion ET portail (barre latérale, en-tête ou pied de page de
     toutes les pages connectées) : « Version X · déployée le JJ/MM/AAAA HH:MM »
     (ex. « Version 1.84 · déployée le 04/10/2026 01:35 »), sans lot ni commit ;
   - pages d'administration / paramétrage : libellé complet
     « Version X · Lot N · commit · déployée le JJ/MM/AAAA HH:MM »
     (ex. « Version 1.84 · Lot 57.1 · 252c6a7 · déployée le 04/10/2026 01:35 ») ;
   - date/heure au format français court
     (`toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })`).
   - SAWALI : fonction `libelleVersion(version, detaille)` et composant
     `BandeauVersion` dans `frontend/src/components/EtatConnexion.jsx`
     (libellé détaillé affiché en haut de /admin/settings).
- Une seule source par plateforme :
  - SAWALI : `backend/lot.py` (LOT, LOT_LIBELLE), exposé par `/api/version` ;
    version = compteur de déploiements `1.N`. Modifier `lot.py` à chaque
    déploiement force aussi le redéploiement du serveur (Render ne redéploie
    un service à `rootDir` que si un fichier de son dossier change).
  - Ster : `frontend/src/version.js` (VERSION +1 à chaque déploiement,
    LOT = numéro de la PR fusionnée).
  - adLyn, beAuthentik : même principe (lot = numéro de la PR fusionnée).
- Nouveau projet : prévoir dès le départ cette source unique et l'affichage.

## Nouveautés à chaque lot (règle 5, 06/10/2026 : « Ça doit être systématique ! »)
- À CHAQUE lot déployé, la page Paramètres (AdminSettings) présente sa carte « Nouveautés » :
  - SAWALI : ajouter une entrée dans `backend/nouveautes.py` avec le MÊME numéro que `backend/lot.py`
    (titre, description d'une ligne, date, `rubrique` = titre exact de la rubrique des Paramètres ou
    `lien` = écran à ouvrir). Le test `tests/test_regle_nouveautes.py` échoue si le lot courant n'a pas sa carte.
  - Une nouveauté située sur un autre écran a aussi sa carte (clic = ouverture de l'écran).
- Même principe sur toute plateforme qui possède une page de paramètres / nouveautés.

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

## Présence auprès de SAWALI (règle 4)
- Toute plateforme ou application que nous créons et déployons (application
  Windows / WinDev, service Windows, serveur web…) a l'OBLIGATION de déclarer
  sa présence à SAWALI, dès sa première version :
  - `POST https://api.sawalismartsystems.com/api/presence-logiciel` au
    démarrage puis toutes les 5 minutes ;
  - corps JSON : `application`, `version`, `deploye_le`, `machine`,
    `utilisateur`, `site`, `systeme`, `demarre_le` (seuls `application`,
    `version` et `machine` sont obligatoires) ;
  - en-tête facultatif `X-Cle-Loois` (clé du support, `LOOIS_SUPPORT_CLE`)
    pour un poste « vérifié » ;
  - envoi en arrière-plan, JAMAIS bloquant ; aucun secret ni donnée
    patient / élève dans le signal.
- Suivi : SAWALI → Plateformes en temps réel → « Postes Windows — versions
  déployées » (poste en ligne si signal < 12 min, version à mettre à jour).
- Modèles : Loois `Loois/Services/PresenceLoois.cs` (C#) ; WinDev : procédure
  `SignalPresenceSawali` + `TimerSys` (envoyée par e-mail le 06/10/2026).
