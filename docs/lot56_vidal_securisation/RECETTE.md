# Lot 56 — Sécurisation VIDAL v2 : fiche de recette

Page concernée : **Portail → Sécurisation** (`/portal/vidal-securisation`).
Module porté depuis Ster (« Sécurisation VIDAL v2 »). Les § cités renvoient au
manuel d'intégration VIDAL, qui n'est pas reproduit ici.

## Avant de commencer

1. **AdminSettings → VIDAL** : module activé, identifiants de **production**
   renseignés (le mode validation appelle toujours la production).
2. **Clients → Fonctionnalités** : VIDAL activé pour le client (établissement)
   du médecin ou du pharmacien qui fait la recette.
3. Se connecter avec le compte du praticien (rôle médecin, pharmacien…) et,
   pour les réglages, avec le compte du client (gestionnaire de l'établissement).

## 1. Mode « Validation VIDAL » (activé par défaut)

- [ ] Le bandeau orange « Mode validation VIDAL — patients fictifs uniquement —
      appels réels (production) » s'affiche en haut de la page.
- [ ] Ouvrir **Paramètres VIDAL** en bas de la page → **Créer / remettre à neuf
      les patients fictifs de validation**. Le message indique 45 patients
      (15 profils × 3) et le nombre de références VIDAL trouvées, « à choisir »
      ou « à rechercher ».
- [ ] Relancer le bouton : « 0 créé(s), 45 remis à neuf », aucun doublon.
- [ ] Saisir un patient réel (sans choisir de patient fictif), ajouter un
      médicament et cliquer **Sécuriser** : message « Mode validation VIDAL :
      seuls les patients fictifs peuvent être envoyés à VIDAL. » — rien n'est
      envoyé (le journal ne reçoit aucune ligne).
- [ ] Avec un compte praticien, le bouton « Désactiver… » n'apparaît pas
      (« réglé par le gestionnaire de l'établissement »).
- [ ] Avec le compte client : **Désactiver…** demande de saisir `DESACTIVER` ;
      une autre saisie ne change rien.

## 2. Patient fictif et données cliniques

- [ ] Dans le cadre **Patient**, liste « Choisir un patient fictif » : choisir
      « FICTIF – Femme enceinte 3 ». Badge **FICTIF**, nom et WhatsApp grisés.
- [ ] Données cliniques importées : date de naissance, sexe Femme, poids et
      taille avec la pastille « Saisi le … », bloc **Grossesse et allaitement**
      ouvert avec la date des dernières règles et les SA (≈ 34).
- [ ] Changer le sexe en Homme : le bloc grossesse/allaitement disparaît.
- [ ] Saisir une créatininémie (µmol/L ou mg/dL) : clairance et DFG sont
      demandés aux calculateurs VIDAL ; en mode validation, en cas d'erreur
      VIDAL, le message réel s'affiche et **aucune valeur locale** n'est mise.
- [ ] Choisir le **Groupe de référence du DFG** : l'appréciation (Normal /
      Légèrement diminué / Diminué, % de la référence) change ; le DFG non.
- [ ] Allergies : un seul champ cherche classes (en italique) et substances ;
      pathologies CIM-10 dans le second champ.
- [ ] « Références VIDAL à résoudre » (patients allergiques) : choisir dans la
      liste des résultats réels ou rechercher dans les champs.

## 3. Prescription et prescriptions de test

- [ ] Encadré **Prescriptions de test** : « Ajouter à la prescription » crée
      une ligne **vide** (seul le produit, ou la recherche du nom, est repris).
- [ ] **Copier** : le presse-papiers contient le médicament et la posologie de
      test, **jamais** le nom du patient.
- [ ] **Coller dans la ligne** : dose, fréquence, durée et unité de durée de
      test remplissent la ligne ajoutée.
- [ ] Choisir un médicament : les listes Unité de prise, Voie (voies hors AMM
      signalées) et Indication se remplissent depuis VIDAL ; rien n'est
      présélectionné.
- [ ] Contrôles : dose sans unité ou sans fréquence, durée décimale, fin avant
      début, ALD sans code, intervalle sans unité → messages rouges, la
      sécurisation est bloquée.
- [ ] « FICTIF – Polymédiqué 1 » : **Traitements en cours** proposés depuis
      l'ordonnance antérieure fictive (à choisir / à rechercher dans VIDAL).

## 4. Sécurisation, rapport HTML, ordonnance

- [ ] Données manquantes utilisées par un médicament (ex. poids) : alerte
      « Données patient manquantes » ; **Compléter** ou **Passer outre**.
- [ ] **Sécuriser** : pastilles de synthèse par gravité, alertes détaillées
      (médicaments non sécurisés en tête) ; un clic sur une pastille ouvre la
      rubrique du rapport HTML.
- [ ] **Rapport HTML complet** : navigation par rubriques, filtre
      « Complet / Filtré », impression.
- [ ] **Imprimer l'ordonnance** puis **Envoi WA** (patient réel avec n°
      WhatsApp, hors mode validation) : inchangés.

## 5. Historique

- [ ] **Enregistrer** (patient réel, mode validation désactivé) puis modifier
      le poids et Enregistrer : message « nouvelle version de l'historique
      clinique ». Ré-enregistrer sans changement : « déjà à jour ».
- [ ] **Historique clinique** : courbes (poids, créatininémie, clairance, DFG
      avec la référence du groupe), versions avec champs modifiés surlignés,
      sécurisations avec « Détail » (données réellement envoyées, groupe DFG
      local non transmis), **Exporter en PDF**.
- [ ] Bouton **Historique** (en haut) : patients enregistrés (badge FICTIF) et
      toutes les sécurisations ; recharger un patient reprend ses données et
      ses traitements en cours.

## 6. Journal de validation et paramètres

- [ ] **Paramètres VIDAL → Validation VIDAL** : chaque appel est listé (date,
      type, URL avec `app_id=***` et `app_key=***`, statut, délai, patient
      fictif et profil, observations).
- [ ] **Détail** : en-têtes, body XML et réponse formatés, bouton Copier,
      observation manuelle enregistrée.
- [ ] Filtres (dates, profil, type, statut), **Export XLSX** (ouvrable dans
      Excel / LibreOffice) et **Synthèse imprimable**.
- [ ] Un autre praticien du même établissement ne voit que ses propres appels ;
      le client (gestionnaire) voit tous ceux de l'établissement.
- [ ] **Groupes de référence du DFG** : modifiables par le client seulement
      (lecture seule pour le praticien) ; un seul groupe par défaut, valeur
      normale entre 1 et 200, seuils cohérents.
- [ ] **Supprimer les patients fictifs** : les patients réels restent, le
      journal est conservé.

## Non-régression

- [ ] Fiche produit VIDAL, Posologie, Analyse prescription, Liluvine VIDAL
      (WhatsApp `!doc` / `!rech`) et Ordonnances & stock fonctionnent comme avant.
