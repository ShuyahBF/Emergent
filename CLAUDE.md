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
- Règle du 29/10/2026 : les NOMBRES (quantités, montants, pourcentages) sont TOUJOURS alignés à DROITE, en-tête de colonne compris (écran : `text-right tabular-nums` ; PDF reportlab : style de paragraphe `alignment=2`).
- Sur TOUT tableau : ligne survolée = fond bleu clair transparent
  (`rgba(56, 189, 248, 0.16)`) ; ligne sélectionnée = fond orange clair
  (`#f6a35b`) avec police BLEU NUIT (`#0A1E3D`, contraste 7,7:1) — règle modifiée le 28/10/2026 : l'ancienne police blanche n'avait que 2:1
  de contraste (illisible).
- Mise en œuvre globale dans le CSS de chaque plateforme ; une ligne est
  sélectionnée si elle porte `ligne-selectionnee`, `aria-selected="true"`,
  `data-selected="true"`, ou si la case à cocher de sa première cellule est cochée.

## Boutons côte à côte (règle 8, 15/10/2026 : « Tous les boutons se ressemblent… La mise en évidence des boutons de cette manière devient une règle »)
- Des boutons placés côte à côte se distinguent par un MINCE FILET de couleur différente qui entoure chaque bouton
  (bleu, vert, orange, violet, rose, cyan, à tour de rôle) ; un bouton seul n'est pas concerné.
- Mise en œuvre (SAWALI) : classe `boutons-distincts` sur le conteneur de la rangée (règle dans `frontend/src/index.css`,
  enfants directs `button` / `a[role="button"]`). Toute rangée de boutons créée ou modifiée la reçoit ; les rangées
  d'icônes, d'onglets ou de pagination n'en ont pas besoin. Même principe sur toute autre plateforme.
- Les écrans importants (alertes à traiter, encadrés d'action) se placent EN HAUT de la page, jamais enfouis dans une section.

## Collections MongoDB : nouvelles collections PERMISES (propriétaire, 28/11/2026 : « Pour les collections MongoDB tu peux en créer des nouvelles. Depuis cette règle j'ai changé mon service MongoDB »)
- L'ancienne contrainte « aucune nouvelle collection (cluster MongoDB plein) » est LEVÉE : le service MongoDB a changé. Une fonction qui a besoin de
  ses propres données crée ses collections (avec leurs index : règle 7) au lieu de ranger des fiches dans `settings`.
- Les mentions « aucune nouvelle collection » des lots plus anciens (ci-dessous) décrivent le choix fait à l'époque ; elles ne s'imposent plus aux nouveaux lots.
- Premier lot concerné : 497 (pointage d'inventaire par téléphone : `pointage_inventaires`, `pointage_saisies`, `pointage_structures`).

## Outils de maintenance et d'analyse (règle 9, 17/10/2026 : « règle ultra importante »)
Le propriétaire vient de WinDev : il ne maîtrise ni Python ni PowerShell et préfère les interfaces graphiques.
- NE JAMAIS lui concevoir d'outil de maintenance ou d'analyse qui demande le moins du monde de manipuler Python, PowerShell ou Visual Studio.
- Privilégier une INTERFACE GRAPHIQUE dans la plateforme : rubrique des Paramètres avec un bouton, puis tableau, graphiques et export CSV.
  Calcul en arrière-plan (règle 7), lecture seule par défaut, accès réservé au bon rôle.
  Modèle : « Audit des collections MongoDB » (lot 225, `backend/routes/audit_collections_mongo.py`).
- Si PowerShell est vraiment inévitable (action sur un poste Windows, sans interface possible) : TOUT dans UN SEUL fichier de commandes
  (.ps1) prêt à l'emploi, commenté bloc par bloc, accompagné d'un mode d'emploi détaillé (où l'enregistrer, comment le lancer,
  ce qu'il affiche, que faire en cas d'erreur). Secrets saisis à l'écran, jamais écrits dans un fichier ni dans le chat.
- Un outil à usage unique (script Python, suite de commandes à enchaîner) n'est PAS une réponse acceptable.

## Listes finies = listes déroulantes (règle 10, 17/10/2026)
- Dès que l'ensemble des valeurs possibles est fini et connu (opérateurs, pays, rôles, statuts, catégories, devises, modes de
  paiement…), le champ est une LISTE DÉROULANTE, jamais une saisie libre ni une grille de grosses cartes.
- Si un nouveau choix doit rester possible, ajouter en fin de liste « Autre… » qui ouvre une saisie libre, seulement dans ce cas.
- Une valeur déjà enregistrée mais absente de la liste reste sélectionnable (jamais de perte de donnée à l'édition).
- Même principe sur toute plateforme, existante ou à venir.

## Fenêtres modales dimensionnées (règle 11, 17/10/2026 : « comme pour beAuthentik et adLyn »)
- Sur PC comme sur mobile, une fenêtre modale n'est jamais exagérément grande : largeur 28 rem au plus (`max-w-md`), 36 rem pour un
  formulaire à plusieurs colonnes (`max-w-xl`), hauteur 85 % de l'écran au plus (`max-h-[85dvh]`) avec défilement DANS la fenêtre.
- Sur mobile : feuille collée en bas ou fenêtre centrée avec marge, jamais plein écran sauf besoin réel (scanner, aperçu).
- Un seul composant de modale par plateforme (ex. `components/Modal.jsx`) porte ces dimensions ; les écrans ne les redéfinissent pas.

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

## Dépôts GitHub des plateformes (règle permanente du propriétaire, 14/10/2026 : « rends-les permanents quelles que soient les sessions »)
Tous les dépôts sont sous le compte GitHub `ShuyahBF`. Quand une demande nomme une plateforme, utiliser CE tableau sans
le redemander. Dépôt absent de la session : `list_repos` (requête « ShuyahBF »), puis `add_repo` (accès « push » pour
modifier), cloner UNE fois (`git clone --depth 1`, délai généreux), puis `register_repo_root`.

| Plateforme | Dépôt | Branche de base / déploiement |
|---|---|---|
| SAWALI | `ShuyahBF/Emergent` | PR vers `render-production` (Render y déploie) |
| ZandGo | `ShuyahBF/zandgo` | `main` |
| Portail e-Kol (élèves et parents) | `ShuyahBF/ekol-portail` | `main` |
| adLyn | `ShuyahBF/telecom-boutique` | `main` |
| beAuthentik | `ShuyahBF/site-meetafrican` | `main` |
| ALBARKA | `ShuyahBF/albarka-portal` | PR vers `render-production` (Render y déploie) |
| Ster (= DentalCare, confirmé par le propriétaire le 14/10/2026) | `ShuyahBF/dentalcare` | `main` |
| Loois (logiciel Windows) et sa mise à jour | `ShuyahBF/Loois`, `ShuyahBF/Loois-MAJ` | `main` |
| Aizenta (analyse qualité des stocks) | `ShuyahBF/Aizenta-Analyse-Qualit-Gestion-Stocks` | voir ses règles |
| BF Mobility (VTC) | `ShuyahBF/sawali-bfmobility` | `main` |
| auRor (= mobile-payments : paiements mobiles, séquences USSD des opérateurs) | `ShuyahBF/Claude` (dossiers `mobile-payments-web` et `mobile-payments-app`) | voir ses règles |

auRor et mobile-payments désignent la MÊME plateforme (précisé par le propriétaire le 14/11/2026) : ses séquences USSD sont la source de référence ; toute copie dans une autre plateforme (ex. SAWALI, paiement au comptoir des officines) doit être corrigée en même temps.

Autres dépôts utiles : `ShuyahBF/Claude` (règles techniques, `TECHNICAL_RULES.md`), `ShuyahBF/reglesmetier_claude` (règles métier).
Dépôt refusé par le contrôle d'accès de la session (ex. `shuyah-mirror`) : ne pas insister, le dire au propriétaire.

## Chargement des pages et gros calculs (règle 7, 15/10/2026 : « C'est une RÈGLE ! »)
Constat e-Kol (lots 33 à 36) : le tableau de bord mettait 37 s en moyenne (jusqu'à 87 s) ; après correction, moins de 1 s.
Cette méthode s'applique à TOUTES les plateformes et à tout projet à venir, dès la première version.
- **Mesurer d'abord** : chaque appel au serveur note sa durée (journal des accès, route « Appels les plus lents » : moyenne,
  5 derniers, dernier, maximum). On corrige la route réellement lente, jamais au hasard. Tout nouveau projet prévoit cette mesure.
- **Jamais d'appel à un service externe lent ou limité DANS la requête d'une page** (géolocalisation d'IP, SMS, WhatsApp, API
  tierce, envoi d'e-mail…) : il part en ARRIÈRE-PLAN (`asyncio.create_task`, tâche planifiée), la page répond tout de suite avec
  la valeur connue ou « en cours d'identification », et le résultat est gardé en cache pour l'affichage suivant.
- **Jamais de boucle N+1** (une lecture de base PAR élève / client / ligne) : lire EN BLOC (une requête par collection, ou une
  agrégation) puis regrouper en mémoire.
- **Gros calculs** (statistiques, totaux, situations, tableaux de bord) : lectures indépendantes lancées EN PARALLÈLE
  (`asyncio.gather`) ; calcul lourd (> 1 s) = cache court (ex. 60 s) ou pré-calcul planifié, jamais refait à chaque clic.
- **Authentification et droits** : lire compte et droits en même temps, pas l'un après l'autre.
- **Index** sur tout filtre fréquent (école/site, type, date) : jamais de parcours complet d'une collection dans une requête de page.
- **Objectif** : toute route d'affichage répond en moins de 1 s côté serveur. Au-delà, on corrige AVANT de livrer ; un appel
  externe en arrière-plan reçoit un test qui prouve que la requête n'attend pas.
- **Écran** : afficher d'abord ce qui est prêt ; une section lente ne doit pas bloquer le reste de la page (chargement séparé).

## Outils de la session et comptes rendus par e-mail (règle 12, 17/10/2026 : « ajoute cette règle partout »)
- **Outils différés** : dans une session, les outils des connecteurs (Gmail, Google Drive, Agenda, Render, GitHub…) apparaissent par leur NOM
  seulement ; ils ne sont utilisables qu'après les avoir chargés avec ToolSearch. AVANT de dire qu'un outil manque, le CHERCHER avec ToolSearch
  (ex. « gmail send message », « google drive create file »). Ne jamais conclure « je n'ai pas l'outil » sans cette recherche.
- **Compte rendu par e-mail** : après chaque livraison, envoyer l'e-mail HTML à jfrancois.ouoba@gmail.com avec l'outil Gmail
  (`mcp__Gmail__send_message`, champ `htmlBody`) : date et heure, identification (dépôt, lot, commit), périmètre, comment vérifier, à activer,
  points d'attention, reste à faire. Ce n'est pas un envoi « à un tiers » : le propriétaire l'a demandé de façon permanente (règle « Livraison et déploiement »).
- **Google Drive** : disponible pour déposer ou lire des documents si le propriétaire le demande ; jamais de secret dans un document.

## Exemples d'identification dans les formulaires (règle 13, 06/11/2026)
- Dans TOUT formulaire où la personne s'identifie (nom, e-mail), les exemples affichés sont LOCAUX : nom « BADINI Awa » (NOM puis prénom) et
  e-mail Gmail « awa.badini@gmail.com ». Jamais « Jean Dupont », « Prénom Nom » ni « @entreprise.fr / @exemple.com ».
- SAWALI : constantes uniques `EXEMPLE_NOM` / `EXEMPLE_EMAIL` dans `frontend/src/lib/exemplesIdentite.js`, importées par chaque formulaire.
  Même principe sur toute plateforme (une seule source par plateforme).

## Compte rendu par e-mail : TOUJOURS, même pour un ajout ou une correction insignifiante (règle du propriétaire, 14/11/2026)
- Après CHAQUE livraison, sans exception de taille (petite correction, changement de libellé, simple règle ajoutée au CLAUDE.md), envoyer l'e-mail HTML de
  compte rendu à jfrancois.ouoba@gmail.com (`mcp__Gmail__send_message`, champ `htmlBody`) : date et heure, identification (dépôt, branche, commit, lot),
  périmètre, comment vérifier, à activer, points d'attention, reste à faire. Ne jamais attendre que le propriétaire le demande.
- Cette règle précise la règle « Livraison et déploiement » ; elle vaut aussi pour les recettes et vérifications faites sans changement de code.

## Pictogrammes sur toutes les actions et enregistrement jamais « deviné » (règle 15, 14/11/2026 : « C'est une règle importante »)
- **Toute action possible** dans un bloc, une page ou une fenêtre (enregistrer, modifier, supprimer, annuler, fermer, ouvrir, actualiser, ajouter, choisir, utiliser, exporter…)
  porte un **PICTOGRAMME** accompagné d'une légende courte. Jamais de bouton sans pictogramme, ni d'action cachée dans un simple texte souligné. Dans une ligne de tableau
  répétée, le pictogramme seul est admis s'il a une info-bulle et un libellé d'accessibilité.
- **Ne JAMAIS laisser l'utilisateur deviner** qu'en changeant de champ (sortie du champ, bascule, liste) les données sont enregistrées. Deux seules façons admises :
  1. **bouton « Enregistrer » avec pictogramme** (✓ / disquette), actif seulement quand la valeur a changé, avec la mention « modifié, non enregistré » ; ou
  2. si l'enregistrement est AUTOMATIQUE par choix, une indication visible à côté du champ (pictogramme + « enregistré automatiquement ») et une confirmation après
     chaque enregistrement (toast, coche) — jamais un enregistrement silencieux.
- Mise en œuvre : web = `lucide-react` ; Android Compose = `Icons` + libellé ; WinForms = image sur le bouton. Valable pour toute plateforme, existante ou à venir.

## Écrans colorés, conviviaux et guidés (règle 16, 14/11/2026 : « ce qui retient l'attention de l'utilisateur, ce sont des écrans riches et pas monotones »)
- **Couleurs sobres et différentes** pour mettre en valeur ce qui est important : champs clés, montants, états, échéances, références, boutons d'action. **Jamais un tableau tout en noir** :
  par exemple identifiant / référence en bleu, montants en vert (reçu) ou rouge (dû), échéances et retards en orange / rouge, action principale en bouton de couleur pleine avec son pictogramme.
- Couleurs **modestes**, juste pour attirer l'œil sur l'essentiel (pas d'arc-en-ciel) ; contraste lisible (≥ 4,5:1) et **jamais la couleur seule** : toujours aussi un pictogramme ou un texte.
- Des interfaces **plus conviviales, intuitives et marquantes, sans ajouter de complexité** : les actions importantes (imprimer, enregistrer, payer…) sont **visibles dans le tableau** (colonne d'action
  avec pictogramme coloré), jamais cachées dans un détail ou un menu replié ; l'utilisateur n'a ni à chercher ni à deviner.
- Pensée **support** : chaque action importante doit pouvoir être décrite par sa couleur et son pictogramme (« dans la colonne du bouton bleu en forme d'imprimante, cliquez dessus »).
- Cette règle complète les règles « Tableaux » (survol bleu clair, sélection orange) et « Pictogrammes » (règle 15).

## Boutons « Actualiser » et toasts (règle 17, 14/11/2026 : « C'est une règle. Ne suppose pas »)
- Après TOUTE correction ou nouveauté qui change des RÉSULTATS présentés (graphique, totaux, liste, statut, calcul), l'écran concerné a un bouton « Actualiser » (avec pictogramme,
  règle 15) que l'utilisateur peut actionner : on ne suppose jamais qu'il verra la correction apparaître tout seul.
- TOUTE actualisation affiche un TOAST « … en cours » dès l'appui, puis un toast de résultat (ce qui a été relu, nombre d'éléments, erreurs éventuelles). Jamais d'actualisation silencieuse.
- On ne suppose pas non plus ce que montre l'écran de l'utilisateur : si un résultat ne change pas après une correction, demander la capture et la version affichée, et vérifier avec les valeurs réelles.
- Mise en œuvre : Concentration = `Avis.enCours` / `Avis.resultat` ; web = `toast` de l'application ; WinForms = infobulle ou message d'état.

## Menus et sous-menus : majuscule à chaque mot (règle 18, 14/11/2026 : « chaque 1ère lettre des mots est en majuscule sauf si le contraire est précisé. Valable pour toutes les plateformes »)
- Dans TOUS les menus et sous-menus (barre latérale, groupes dépliables, onglets de navigation, menus d'application), **chaque mot du libellé commence par une majuscule** :
  « Gestion Des Contacts », « Demandes À SAWALI », « Contacts Clients ». Seule exception : quand le propriétaire précise le contraire pour un libellé.
- Seule la première lettre de chaque mot est forcée en majuscule : les sigles et noms déjà en majuscules (SAWALI, DG, OHADA, PI-SPI) ne sont jamais abaissés ; un mot qui suit une apostrophe garde sa casse (« L'ordre »).
- Mise en œuvre : UNE fonction par plateforme, appliquée au dessin des libellés (web : `titreMenu` ; WinForms / Android : équivalent), avec une option « casse libre » pour une exception. On n'écrit pas les majuscules à la main libellé par libellé.
- Valable pour toutes les plateformes, existantes ou à venir.

## Tableaux : toutes les colonnes triables (règle 19, 15/11/2026 : « pour tout tableau présentant des données, rends toutes les colonnes triables si les types de champs le permettent »)
- Sur TOUT tableau qui présente des données (écran, application, état), **chaque colonne est triable** d'un clic sur son en-tête dès que le type de champ le permet (texte, nombre, montant, date) :
  1er clic = croissant (▲), 2e clic = décroissant (▼), 3e clic = ordre d'origine. L'en-tête de la colonne triée est mis en évidence (orange) avec son pictogramme ▲ / ▼ ; les autres colonnes portent un pictogramme ⇅ discret.
- Les valeurs VIDES restent toujours en dernier, quel que soit le sens. Les textes se comparent sans accents ni majuscules, les nombres et montants numériquement, les dates chronologiquement (jamais comme du texte).
- Tableau PAGINÉ ou chargé par morceaux : le tri se fait côté SERVEUR, sur toutes les lignes filtrées, AVANT la pagination (trier seulement les lignes affichées donnerait un faux classement). Petit tableau entièrement chargé : tri dans le navigateur.
- Seules les colonnes d'ACTIONS (boutons) et les colonnes sans valeur comparable (case à cocher de sélection, pictogramme seul) ne sont pas triables.
- Mise en œuvre : SAWALI = `frontend/src/lib/tri.js` (`useTri`, `trierLignes`) et `frontend/src/components/ThTri.jsx` (en-tête triable), tri serveur de Transactions SMS dans `backend/routes/transactions_sms.py` (`trier`) ; e-Kol = `triTableaux.js` ; WinForms = `DataGridView` avec `SortMode = Automatic` ; Android Compose = en-tête cliquable. Même règle sur toute plateforme, existante ou à venir.
- Cette règle complète la règle 3 « Tableaux » (survol, sélection, nombres à droite).

## Détails et corrections : fenêtre modale, pas d'allongement de la page (règle 20, 15/11/2026 : « utilise une fenêtre modale plutôt que allonger le contenu des pages comme tu le fais souvent sauf informations contraires de ma part »)
- Pour afficher les DÉTAILS d'une ligne de tableau ou faciliter une CORRECTION, ouvrir une FENÊTRE MODALE (dimensions de la règle 11 : `max-w-md` / `max-w-xl`, `max-h-[85dvh]`, défilement dans la fenêtre), jamais un panneau qui allonge la page sous le tableau ni une ligne dépliée.
- Les décisions possibles (accepter, refuser, enregistrer…) sont proposées dans la modale, avec pictogramme et légende (règle 15) ; « Fermer » toujours présent.
- Exception seulement si le propriétaire demande le contraire pour un écran précis. Android : feuille ou dialogue ; WinForms : fenêtre de dialogue.
- SAWALI : composant `components/ui/dialog.jsx` ; exemple : dossier du demandeur dans `FamilleTvSection.jsx`.

## Sécurité, authenticité, détournement et bonne foi : à penser AVANT d'implémenter (règle 21, 15/11/2026 : « sauf instructions contraires de ma part, pense à l'aspect sécurité, authenticité des informations, que les usages ne soient pas détournés, à la bonne foi »)
- Pour toute fonction (demande d'accès, inscription, paiement, partage…), se poser AVANT d'écrire le code : qui peut mentir, qui peut détourner l'usage, que peut-on VRAIMENT prouver ?
- **Ne jamais s'appuyer sur la seule bonne foi de l'utilisateur.** Distinguer trois degrés et les afficher à l'administrateur : « vérifié » (prouvé : code reçu par e-mail ou WhatsApp), « relevé par le serveur » (adresse IP, localisation, ancienneté), « déclaré, non vérifiable » (saisie libre, détails du téléphone : simple indice, jamais une preuve).
- **Demander peu à l'utilisateur** : ne demander que ce qui sera prouvé ; une saisie non vérifiable décourage sans protéger. Collecter automatiquement ce qui est utile (jamais d'identifiant personnel inutile) et informer dans la politique de confidentialité.
- **Ancrer la confiance sur ce que le serveur voit lui-même** (ex. la télé : son adresse IP à l'appairage, puis à chaque interrogation ; un autre pays la bloque jusqu'à confirmation de SAWALI), pas sur ce que le téléphone déclare. Prévoir le déplacement, la revente, le partage et le vol d'un appareil.
- **Limiter les abus** : captcha à usage unique, limites par compte et par adresse IP, délai après refus, jetons signés à durée courte, codes à essais limités, aucun secret dans les journaux. Un service externe de contrôle indisponible ne bloque jamais l'utilisateur honnête (échec ouvert) ni ne s'exécute dans la requête de la page (règle 7).
- Un indicateur de risque AIDE la décision de l'administrateur, il ne décide pas seul ; chaque blocage automatique est levable par un administrateur (bouton avec pictogramme).


## Pictogramme œil sur toute saisie secrète (règle 22, 16/11/2026 : « pour toute saisie d'un mot de passe, pin ou passphrase mettre un pictogramme œil pour afficher ou masquer. Applique cela à tous nos projets, web comme Android »)
- **Toute saisie d'un mot de passe, d'un code PIN, d'une phrase secrète, d'un jeton ou d'une clé secrète** (connexion, création, confirmation, changement, ouverture d'un coffre, fenêtre de sécurité d'un paiement, paramètres…) porte un **pictogramme œil** : œil ouvert = saisie masquée (un clic l'affiche), œil barré / singe = saisie visible (un clic la masque). **Masquée par défaut** à chaque ouverture.
- Le pictogramme est **dans le champ** (à droite), avec une description d'accessibilité (« Afficher la saisie » / « Masquer la saisie ») et une zone tactile d'au moins 44 px.
- **Un seul composant par plateforme**, utilisé partout (jamais un `<input type="password">` nu) : web = `ChampMotDePasse` / `MotDePasse` / `PasswordInput` (ou le champ de base de l'interface qui l'intègre quand `type="password"`) ; Android Compose = champ avec `trailingIcon` (`Visibility` / `VisibilityOff`) ; Android à vues = `FrameLayout` + œil ; WinForms = case ou bouton œil qui bascule `UseSystemPasswordChar`.
- Un nouvel écran, un nouveau projet : le champ secret reçoit l'œil dès la première version. Exception : la saisie d'un code à usage unique (code reçu par e-mail ou SMS, code de l'application d'authentification), qui n'est pas un secret durable.

## Tableaux de plus de 30 lignes : barre de défilement (règle 24, 18/11/2026 : « C'est une règle à considérer partout sur toutes les plateformes »)
- Tout tableau qui présente PLUS DE 30 LIGNES défile dans son cadre (hauteur = 30 lignes + l'en-tête) au lieu d'allonger la page ; l'en-tête reste visible en haut pendant le défilement ;
  à l'impression, toutes les lignes sortent. Exception possible : `<table data-sans-defilement>`.
- SAWALI : module global `frontend/src/lib/defilementTableaux.js` (installé dans `index.js`, règles CSS dans `index.css`, test `defilementTableaux.test.js`) : rien à ajouter tableau par tableau.
  Autres sites web : même module copié. Android Compose : liste de plus de 30 lignes dans une `LazyColumn` à hauteur bornée. WinForms : `DataGridView` à hauteur fixe (défilement natif).

## Git en session cloud : alerte « commits non poussés » à tort (propriétaire, 18/11/2026 : « fais tout pour que ce problème ne revienne plus. Beaucoup de prudence »)
- **Cause** : dans un dépôt cloné en superficiel, seule `main` est suivie (`remote.origin.fetch`). Une branche poussée n'a donc AUCUNE référence locale `origin/<branche>` : le garde-fou de fin de session compare alors à `origin/HEAD` et annonce des commits « non poussés » (2, puis 5…) alors que tout est sur GitHub. Après une fusion « squash », les commits d'origine ne sont jamais « fusionnés » au sens de git : l'alerte persiste.
- **Avant le premier push** d'une branche : `git config --add remote.origin.fetch '+refs/heads/<branche>:refs/remotes/origin/<branche>'`, puis `git push -u origin <branche>`. Branche déjà poussée sans cela : `git update-ref refs/remotes/origin/<branche> $(git ls-remote origin refs/heads/<branche> | cut -f1)`.
- **Après la fusion** : récupérer la référence de la branche de base (`git fetch --depth=1 origin +refs/heads/<base>:refs/remotes/origin/<base>`, ex. `render-production`), se placer dessus sans rien écrire (`git checkout --detach origin/<base>`), puis supprimer la branche locale UNIQUEMENT si son commit est identique à celui de la branche distante (`git ls-remote origin <branche>`). Jamais de `git branch -D` sans cette vérification, jamais de push forcé ni de commit vide pour « faire taire » l'alerte, jamais de modification du script du garde-fou.

## Totaux sous les colonnes numériques (règle 25, 18/11/2026 : « je veux que cela soit une règle pour toutes les plateformes sauf pour ALBARKA »)
- Sur TOUTES les plateformes SAUF ALBARKA (existantes ou à venir : SAWALI, Loois, Aizenta, e-Kol, adLyn, beAuthentik, Ster, ZandGo, BF Mobility, auRor…), tout tableau qui présente des colonnes de MONTANTS ou de QUANTITÉS porte, collée dessous, une ligne de TOTAUX toujours visible : somme de chaque colonne numérique des lignes AFFICHÉES (donc filtrées), nombre de lignes dans la première colonne, nombres alignés à DROITE. Jamais de somme sur un pourcentage ou une moyenne.
- ALBARKA est EXCLUE de cette règle : aucun total ajouté sous ses tableaux, sauf demande contraire du propriétaire.
- Mise en œuvre : web = ligne de pied collée en bas du cadre défilant (règle 24), un seul composant par plateforme ; WinForms (Loois) = `PiedTotauxGrille` ; Android Compose = ligne fixe sous la liste. Les tableaux existants suivent, lot par lot.

## Recherche plein texte du tableau de bord (lot 451, propriétaire 19/11/2026)
- Tableau de bord du portail → « Rechercher dans mes rapports, suivis, notes et tâches » (`frontend/src/components/RechercheDocuments.jsx`) : liste type / date et heure / extrait surligné / auteur, colonnes triables ; un clic ouvre le document dans une modale en LECTURE SEULE (contenu nettoyé par `lib/htmlLectureSeule.js`).
- Serveur : `GET /api/me/recherche-documents?q=&types=` et `GET /api/me/recherche-documents/{kind}/{id}` (`server_parts/p08`), logique pure dans `backend/recherche_documents.py` (sans casse ni accents, 50 résultats au plus par type, 4 lectures en parallèle, aucune nouvelle collection).
- DROITS : `_base_visibilite_notes(user)` est la source UNIQUE des droits de lecture de ces quatre types ; la liste `/me/notes/{kind}` ET la recherche l'utilisent. Toute nouvelle lecture de ces documents passe par elle (tests `tests/test_recherche_documents.py`).

## Compte rendu par e-mail AUTOMATIQUE après toute livraison (règle du propriétaire, 19/11/2026 : « L'envoi de l'e-mail doit être automatique »)
- L'e-mail HTML à jfrancois.ouoba@gmail.com (outil Gmail, voir règle 12) part TOUT SEUL à la fin de CHAQUE livraison, sans que le
  propriétaire ait à le demander ni à le rappeler, et sans demander confirmation avant l'envoi.
- « Livraison » = tout ce qui atteint le propriétaire ou les utilisateurs, même sans fusion ni déploiement Render : dépôt d'un APK ou d'une
  nouvelle version dans ShuyahStore, publication d'une version, correction, changement de libellé, simple règle ajoutée au CLAUDE.md, fichier
  envoyé au propriétaire. Aucune exception de taille.
- Ne pas conclure « la règle ne s'applique pas, rien n'a été déployé sur Render » : en cas de doute, envoyer l'e-mail.
- Contenu : date et heure, identification (dépôt, branche, commit, version, lot), périmètre, comment vérifier, à activer, points
  d'attention, reste à faire. Jamais de secret (clé, mot de passe, chaîne de connexion) dans l'e-mail.
- Charger l'outil Gmail avec ToolSearch AVANT de dire qu'il manque ; s'il est vraiment indisponible, le dire dans le chat et ne pas clore la livraison.


## Signature et publication des APK : clé permanente seulement, publication directe dans ShuyahStore (règle du propriétaire, 19/11/2026)
- **Plus JAMAIS la clé de test** (option `-PsignerAvecCleLocale=true`, clé « Android Debug ») pour un APK livré au propriétaire, **sauf demande EXPRESSE** de sa part dans la conversation. Cette règle remplace toute consigne plus ancienne qui l'autorisait.
- Tout APK est signé avec la clé PERMANENTE de ShuyahStore (variables `ANDROID_KEYSTORE_FILE` / `_PASSWORD` / `ANDROID_KEY_ALIAS` / `ANDROID_KEY_PASSWORD`). Avant de livrer, vérifier avec `apksigner verify --print-certs` que le certificat est celui de ShuyahStore (« CN=ShuyahStore »), jamais « Android Debug ».
- **Fichier de clé absent** (chemin de `ANDROID_KEYSTORE_FILE` introuvable : c'est le cas dans une session neuve) : ne construire AUCUN APK de remplacement. Le dire au propriétaire et lui demander de joindre `cle-shuyahstore-shuyahstore.p12` à la conversation (pièce jointe, jamais collé dans le texte) ; le recopier à l'emplacement attendu, sans l'afficher ni le commiter.
- **Publication DIRECTE dans ShuyahStore à CHAQUE livraison** (`POST https://shuyahstore-api.onrender.com/api/dev/depot`, jeton injecté par le secret réseau « Jeton de dépôt ShuyahStore »), en plus de l'envoi de l'APK dans le chat. Dire dans le compte rendu si la version a été publiée directement ou mise en validation.

## Pastilles de notifications dans le menu (RÈGLE PERMANENTE du propriétaire, 19/11/2026 : « pour toutes les plateformes disposant d'une sidebar »)
- Chaque lien de menu (sidebar, barre de navigation) qui reçoit des notifications affiche une BULLE avec le NOMBRE d'éléments non encore lus / traités : Centre de Messagerie, Réservations, Alertes, Stock, Demandes… Le nombre est écrit (jamais la couleur seule), plafonné à « 99+ », avec une étiquette d'accessibilité.
- Une seule route légère de compteurs par plateforme (filtrée par droits), relue périodiquement (30 s) et après chaque action qui change un compteur ; calculs lourds gardés quelques dizaines de secondes (règle 7). Tout NOUVEAU lien qui reçoit des notifications ajoute sa clé et sa pastille.
- Modèle : Dialyse, `GET /notifications/compteurs` (`backend/app/notifications.py`) et `frontend/src/composants/MiseEnPage.jsx`.

## Recherche du client lié et curseur en majuscules (lot 451.1, propriétaire 23/11/2026)
- « Nouvelle intervention », « Modifier intervention » (`pages/portal/Interventions.jsx`) et la bulle « Nouveau ticket d'intervention » (`components/TicketsBubble.jsx`) : le « Client lié » (premier champ) n'est plus une longue liste déroulante mais un champ de RECHERCHE
  (`components/ChampClientRecherche.jsx`, logique pure `lib/rechercheClients.js` testée) : tout ou partie du code, du nom complet, de la société ou du nom, sans tenir compte des majuscules ni des accents, plusieurs mots = tous doivent se retrouver ; flèches + Entrée au clavier.
- Un champ saisi en MAJUSCULES ne doit JAMAIS faire sauter le curseur à la fin : on n'écrit plus `onChange={(e) => setX(e.target.value.toUpperCase())}` (React réécrit la valeur et replace le curseur) mais `onChange={(e) => saisieMajuscules(e, setX)}` (`lib/saisieMajuscules.js` : valeur rangée tout de suite par `flushSync`, puis curseur remis en place).
  Vérifié dans un vrai navigateur (curseur resté à la position 7 au lieu de 16). Les ~25 autres champs en majuscules de l'application suivent cette règle lors de leur prochaine modification.

## Client lié canonique : « Client canonique introuvable » à l'enregistrement d'une fiche (lot 451.2, propriétaire 23/11/2026 : « c'est quelque chose que j'avais autorisé »)
- Cause : la CRÉATION d'un client accepte n'importe quel compte comme client canonique (suggestion « cette société existe déjà »), mais la MISE À JOUR re-vérifiait le lien à chaque enregistrement avec une liste de rôles plus étroite : si le client canonique avait un autre rôle, la fiche ne s'enregistrait plus, même sans toucher au lien.
- Règle (`backend/liens_clients.py`, `lien_a_valider`, tests `tests/test_liens_clients.py`) : un lien INCHANGÉ n'est jamais re-vérifié ; un lien CHANGÉ doit viser un compte existant (tout rôle, comme à la création) ; le client lié déjà enregistré reste toujours dans la liste déroulante de la fiche (`AdminClients.jsx`).
  Le message ne reste que pour un compte réellement supprimé, et le dit clairement.

- Lot 451.3 (23/11/2026) : les 20 autres champs en majuscules de l'application (devises, codes coupon, codes téléphone TV, pays, motifs et étiquettes de tickets, nom d'officine, initiales de suivi de RDV…) utilisent aussi `saisieMajuscules` : plus aucun `e.target.value.toUpperCase()` dans un `onChange`.
  Tout NOUVEAU champ saisi en majuscules utilise `saisieMajuscules` dès sa création.

## Connexion par compte Google (lot 452, propriétaire 24/11/2026)
- Flux OpenID Connect « à code » serveur → Google → serveur (`backend/google_auth.py` logique pure, `backend/routes/google_connexion.py`, test `backend/tests/test_google_connexion.py`, aucun accès réseau) ; routes `/api/auth/google/{config,demarrer,lier-url,retour,echange,etat,delier}` et `/api/admin/google-connexion` (admin).
- SÉCURITÉ : aucun compte n'est créé ni rapproché par e-mail ; seul un compte DÉJÀ LIÉ (« Mon compte » → Compte Google, connecté) ouvre une session par Google ; une identité Google = un seul compte (index `google.sub`). Google remplace le mot de passe, PAS le code de vérification : `/auth/google/echange` rend la réponse de `/auth/login` (`_emettre_otp`, extrait de `routes/auth.py`) puis `/auth/verify-otp` ouvre la session ; `_controles_connexion` (statut du compte, maintenance, cycle de vie, IP bloquée) s'applique.
- Client Google : le MÊME que Google Agenda (`google_client_id` / `google_client_secret` des Paramètres, ou GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET) ; il reste à déclarer chez Google l'adresse de retour `https://<api>/api/auth/google/retour` (affichée et copiable dans Paramètres → « 🔗 Connexion par compte Google », avec le nombre de comptes liés). GOOGLE_RETOUR_SITE / GOOGLE_REDIRECT_URI : réglages facultatifs.
- Site : `lib/googleConnexion.js`, `pages/auth/ConnexionGoogle.jsx` (route `/connexion-google`, renvoie à `/login` à l'étape « code »), `pages/portal/sections/GoogleSection.jsx`, `pages/admin/sections/GoogleConnexionAdminSection.jsx`.
- Modèles Pydantic des routes : au NIVEAU DU MODULE (FastAPI ne retrouve pas ceux déclarés dans une fonction : 422).

## Liste noire WhatsApp et notifications désactivables (lot 453, propriétaire 24/11/2026)
- **Liste noire, toutes lignes** (`backend/liste_noire_wa.py`, routes `backend/routes/liste_noire_wa.py`, test `tests/test_liste_noire_wa_lot453.py`) : un contact bloqué ne reçoit AUCUN message de SAWALI (donc ni « distribué » ni « lu ») : garde dans les 4 expéditeurs de `routes/whatsapp_helpers.py` (texte, modèle, boutons, média), les réponses de Liluvine (`_wa_send_location`, `_wa_send_image`) et les demandes d'autorisation d'appel ; ses messages reçus sont ENREGISTRÉS mais retenus (`liste_noire`, pas de non-lu, pas de notification, AUCUNE réponse d'agent IA) ; il n'est plus relayé (`decision_relais` du propriétaire, `liluvine_relais.traiter_message_entrant`, statuts « distribué / lu » non relayés aux plateformes).
- Numéro reconnu par ses 8 derniers chiffres ; stockage dans UNE fiche de `settings` (`_id = "wa_liste_noire"`), aucune nouvelle collection (cluster MongoDB plein) ; 2000 numéros au plus. BLOQUER, LISTE et DÉBLOCAGE : administrateur ET SUPERVISEUR (lots 453.1 et 453.2 : le Centre de Messagerie est celui du superviseur) ; la liste n'est visible que dans les Paramètres. Lot 453.3 : un contact bloqué DISPARAÎT de la liste du Centre de Messagerie (`GET /me/contacts` le retire par `liste_noire_wa.sans_bloques`) jusqu'à son déblocage ; la liste se relit dès le blocage.
- BLOQUER : bouton « Bloquer » (`components/BoutonBloquerWa.jsx`) dans la LISTE des contacts du Centre de Messagerie, SANS ouvrir la conversation, et dans l'en-tête d'une conversation ; la LISTE et le déblocage ne sont visibles que dans Paramètres → « ⛔ Liste noire WhatsApp (contacts bloqués) » (`pages/admin/sections/ListeNoireWaAdminSection.jsx`).
- **Notifications désactivables** (`notifier_contact`, `notifier_responsable`, absent = oui) sur les tickets et les interventions (`components/OptionsNotifWa.jsx`, `NotifWaTicket` dans `pages/portal/Tickets.jsx`) : le contact concerné ; son responsable = contact « décisionnaire » (`is_decision_maker`) de l'entreprise liée. Appliqué : message d'ouverture du ticket (`p18`), destinataires des rappels et fermetures de session (`tickets_clients.notification_autorisee`), notification « intervention créée » (client = responsable, `p14._emit_event`). Les automatisations à numéro fixe (relais admin) ne sont pas concernées.

## Consignes à Liluvine (lot 454, propriétaire 24/11/2026 : « donner des instructions à certains moments à Liluvine comme à une vraie secrétaire »)
- Menu Liluvine → « Consignes » (`pages/admin/LiluvineConsignes.jsx`, `/admin/liluvine-consignes` et `/portal/liluvine-consignes`, SUPERVISEUR compris : élément partageable « consignes » de `liluvine_partage`). On écrit une phrase ; `POST /admin/liluvine-consignes/interpreter` la fait comprendre (IA qui TRANSCRIT, le code valide nature / dates / texte : `consignes_liluvine.valider_proposition`) et la MONTRE ; RIEN n'est actif avant « Valider et activer » (dates modifiables). Heures en UTC = heure du Burkina Faso.
- Stockage : deux fiches de `settings` (`liluvine_consignes`, `liluvine_consignes_acces`), aucune nouvelle collection. Portée : les données de SAWALI (clients, contrats, tarifs, services installés, contacts, factures, reçus, RDV, bases documentaires), pas les autres plateformes.
- Trois natures : « reponse » (APPLIQUÉE : bloc « CONSIGNES DU MOMENT » ajouté au prompt de Liluvine par `liluvine_pro._resolve_base_system_prompt` et aux prompts prospect de `liluvine_wa_autoreply`, `liluvine_decroche`, `liluvine_agenda` : WhatsApp, appels, agenda, chat) ; « blocage » de créneaux et « masse » (message à un groupe, toujours confirmé avant l'envoi) : REFUSÉES à l'activation tant que le serveur ne les applique pas (jamais « acceptée mais ignorée »).
- Paramètres → « 💬 Consignes à Liluvine — numéros WhatsApp autorisés » (administrateur seul) : numéros (8 derniers chiffres), nom, client / tenant, actif. Servira au lot « consignes données par WhatsApp ». Tests : `tests/test_consignes_liluvine_lot454.py`.
- Reste (lots suivants) : application des blocages de créneaux côté serveur (interventions), envois en masse confirmés, consignes données par WhatsApp depuis un numéro autorisé.

- Lot 455 (24/11/2026) : consignes de BLOCAGE de créneaux appliquées (`consignes_liluvine.creneau_bloque` / `verifier_demande`) : une consigne « aucune demande d'intervention entre 12h et 13h jusqu'à lundi » fait refuser (HTTP 409 + message) l'ouverture d'un ticket par le site ET par la commande WhatsApp de Liluvine ; administrateur et superviseur ne sont jamais bloqués ; fin du créneau exclue. L'activation exige un créneau HH:MM–HH:MM. Reste : lot 456 (envois en masse confirmés), lot 457 (consignes par WhatsApp). Tests : `tests/test_consignes_creneaux_lot455.py`.

- Lot 456 (24/11/2026) : ENVOIS EN MASSE des consignes (`backend/consignes_masse.py`, routes `/admin/liluvine-consignes/masse/{apercu,confirmer,envois}`) : 1) APERÇU = destinataires choisis parmi les RDV de la période (non annulés, numéro valable, hors liste noire, un par numéro, 200 au plus, 31 jours au plus), numéros masqués ; 2) CONFIRMATION liée à l'aperçu VU (empreinte message + liste, valable 15 min, usage unique) ; 3) envoi en ARRIÈRE-PLAN (règle 7), texte libre seulement dans la fenêtre de 24 h, les autres sont listés « non envoyé » (jamais de modèle choisi à notre place). Stockage : fiche `settings` `liluvine_masse`. Tests : `tests/test_consignes_masse_lot456.py`. Reste : lot 457 (consignes données par WhatsApp).

- Lot 456.1 (24/11/2026) : modèle Meta des envois en masse hors fenêtre de 24 h (`consignes_masse.MODELE_NOM / MODELE_CORPS / MODELE_BOUTON`) : catégorie UTILITY, langue fr, nom `information_rdv`, corps « Bonjour {{1}}, une information concernant votre rendez-vous : {{2}} Merci de confirmer la bonne réception en appuyant sur le bouton ci-dessous. », bouton de réponse rapide « Bien reçu » (exemples : « Awa », « Votre rendez-vous de demain est décalé d'une heure. »). Le nom du modèle APPROUVÉ se règle dans Paramètres → « 💬 Consignes à Liluvine — numéros WhatsApp autorisés » (`GET/PUT /admin/liluvine-consignes/masse/modele`, écriture administrateur seul) ; sans modèle, les contacts hors fenêtre restent « non envoyé ». Suivi : carte « Envois en masse » de l'écran Consignes (texte libre / modèle / non envoyés / échecs, détail, Actualiser).

- Lot 457 (24/11/2026) : CONSIGNES PAR WHATSAPP (`backend/consignes_whatsapp.py`, branchée au début de `autoreply_to_inbound`) : seul un numéro ACTIF de la liste (Paramètres → « Consignes à Liluvine — numéros WhatsApp autorisés ») est écouté, et seulement avec le déclencheur explicite « consigne… » ; Liluvine répond par ce qu'elle a compris et n'active qu'après « OUI » (« NON » annule ; proposition valable 15 min, un « OUI » sans proposition récente est ignoré). Envoi en masse = DEUX « OUI » (1er : liste des destinataires, 2e : envoi) ; refusé à un numéro lié à un client (tenant). Stockage : fiche `settings` `liluvine_consignes_wa`. Les fonctions d'envoi réelles sont partagées avec l'écran (`consignes_masse.envoyeurs_serveur`). Tests : `tests/test_consignes_whatsapp_lot457.py`. Consignes à Liluvine : tous les lots prévus (454 à 457) sont livrés.

- Lot 458 (25/11/2026) : COMMANDE HFSQL DISTANTE VIA LILUVINE (`backend/commande_hfsql_wa.py`, branchée au début de `autoreply_to_inbound`, routes `/admin/liluvine-hfsql-acces` administrateur SEUL) : un numéro ACTIF de la liste (Paramètres → « 📡 Commande HFSQL distante via Liluvine », zones permises facultatives) écrit « hfsql docx=CMC <requête> » ; la commande passe par la file des requêtes SQL distantes (`loois_sql_distant.INTERNE`, mêmes contrôles « Prudent » `verifier`), UNE machine du client l'exécute (le service Windows ; Loois sur PC n'a pas besoin d'être ouvert) et la réponse revient sur WhatsApp : zone, base (et machine), commande rappelée, résultat du moteur HFSQL (15 lignes au plus). SELECT = tout de suite ; INSERT / UPDATE / DELETE = Liluvine répète la commande et attend « OUI » (5 min) ; une modification n'est déposée que si le client est EN LIGNE ; 20 commandes par heure et par numéro ; journal consultable (commande gardée, jamais le résultat). Tests : `tests/test_commande_hfsql_wa_lot458.py`. Pas de raccourci « SUP <n° de reçu> » : la commande SQL complète est envoyée (reste à voir avec le propriétaire).

- Lot 459 (25/11/2026) : RACCOURCIS DE COMMANDES HFSQL AVEC PARAMÈTRES (`backend/raccourcis_hfsql.py`) : une commande SQL distante réussie devient un raccourci ; les valeurs qui changent s'écrivent entre accolades comme dans HFSQL (`UPDATE VenteClinique SET Mag = {vStatut} WHERE Référence = {RefNum}`). Par WhatsApp : « hfsql » = liste numérotée, « hfsql 1 » (ou le nom ; zone autre : « hfsql 1 docx=PHL ») = Liluvine demande chaque valeur DANS L'ORDRE d'apparition (un paramètre répété = une seule valeur ; « annuler » arrête), exécute et renvoie zone, base, commande, résultat. SÛRETÉ : hors apostrophes un nombre reste un nombre, NULL reste NULL, tout autre texte est mis entre apostrophes (doublées) ; dans des apostrophes du modèle, celles de la valeur sont doublées ; 200 caractères, ni retour à la ligne ni accolade ; chaque valeur est validée dès sa réception ; la commande RÉSOLUE repasse par `verifier` (Prudent). Case « Demander OUI avant d'exécuter » par raccourci (décochée par défaut : fournir les valeurs vaut confirmation, voulu par le propriétaire). 20 raccourcis au plus (≥ 10 demandés), nom unique. Création : Loois (historique des requêtes → ⭐ Créer un raccourci, clé SQL à distance : `/api/loois-sql/raccourcis` GET / POST / DELETE) ou Paramètres → « 📡 Commande HFSQL distante via Liluvine » (`/admin/liluvine-hfsql-raccourcis`, administrateur seul). Tests : `tests/test_raccourcis_hfsql_lot459.py`, `tests/test_lot439_loois_sql_distant.py`. Prochaines étapes annoncées par le propriétaire : « parfaire pour que ce soit encore plus puissant ».

## Boutons d'action = pictogrammes, pas de gros boutons (règle du propriétaire, 27/11/2026 : « les pictogrammes remplacent les gros boutons… j'en ai fait une règle »)
- Sur tout écran, les actions (démarrer, arrêter, mesurer, actualiser, exporter, effacer, rapport…) sont des **boutons ronds à pictogramme seul**, colorés (règle 16), zone tactile d'au moins 44 px, avec **info-bulle (`title`) et libellé d'accessibilité (`aria-label`)** : jamais un gros bouton à texte.
- Une courte légende discrète peut accompagner une rangée de pictogrammes ; le pictogramme reste l'élément principal (règle 15 : pictogramme usuel et intuitif).
- Pages à nombreux blocs (ex. Sonde réseau) : les regrouper en **onglets** (Graphiques, Réglages, Mesures, Sauvegardes Et Envois) plutôt qu'une longue page. Modèle : `frontend/src/pages/admin/sections/SondeReseauSection.jsx` (lot 485).

- Lot 489.1 (27/11/2026) : « Volumétrie des tables HFSQL — cache Atlas » (`VolumetrieHfsqlSection.jsx`) : client, plateforme et durée du cache gardent une largeur fixe (`lg:grid-cols-[11rem_13rem_6.5rem_minmax(0,1fr)]`), la liste des tables prend toute la largeur restante (4 à 5 fois plus large) ; libellé « Cache (jours) » sur une ligne pour garder les champs alignés.

## Pointage d'inventaire par téléphone (lots 496 et 497, propriétaire 28/11/2026)
- Paramètres → « 📱 Pointage d'inventaire par téléphone » (`PointageInventaireSection.jsx`, administrateur) ; page du téléphone `/pointage/<jeton>` (`pages/public/PointageTelephone.jsx`, sans compte, QR code expirant en 3 jours) ; analyseur de dictée sans IA `lib/dicteePointage.js`.
- Structure = TOUT lieu de commerce (« une officine ou n'importe quel lieu de commerce ») : client Loois, officine, ou commerce déclaré (clé de suivi « CS-… », `pointage_structures`). Liste des produits : JSON d'Aizenta ou CSV (Excel). Lieux de stockage rattachés à INV SV / INV Mag (Aizenta n'a que ces deux colonnes, choix fait à la création).
- Même ligne saisie deux fois dans le même lieu = quantités ADDITIONNÉES + alerte (choix du propriétaire) ; péremption : la plus proche est gardée ; export JSON WinDev (Aizenta) ou CSV.
- Lot 498 (« chaque commerce même nouveau doit avoir sa clé pour le pointage… et un mot de passe pour être autorisé ») : collection `pointage_acces`, clé « CP-… » + mot de passe (bcrypt, montré UNE fois,
  « nouveau mot de passe » possible, révocation), générés UN À UN par l'administrateur pour un commerce connu, aussitôt pour un commerce déclaré. Sans clé active : ni création ni pointage.
  « Les deux » : Espace pointage du responsable (`/pointage-espace`, `pages/public/PointageEspace.jsx`, jeton 12 h en en-tête `X-Pointage-Jeton`, ne voit QUE son commerce) ET mot de passe sur chaque téléphone
  (`POST /public/pointage/{jeton}/acces` → en-tête `X-Pointage-Telephone`, lié à la version du mot de passe). 5 essais faux → 15 min de blocage ; 20 échecs par IP en 15 min → 429.
  C'est un SITE WEB (Chrome sur Android, iPhone aussi), pas une application Android.
- Logique pure `backend/pointage_telephone.py`, routes `backend/routes/pointage_telephone.py`, tests `tests/test_pointage_telephone_lot496.py` et `tests/test_pointage_telephone_routes_lot496.py`.
