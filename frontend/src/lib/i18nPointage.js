// i18nPointage.js — Lot 499 : textes du POINTAGE en français ou en anglais, selon la langue choisie pour le commerce.
// Principe (le plus simple à maintenir) : le texte français EST la clé ; `traduire("en", "Suivant")` → « Next ».
// Un texte absent du dictionnaire reste en français (jamais d'écran vide). Valeurs variables : « {n} » remplacé par vars.n.
// Parallèle WinDev : l'équivalent des « messages multilingues » (fonction Nation / ChaîneConstruit avec %1).

const EN = {
  // --- Téléphone (page /pointage/<jeton>)
  "Pointage d'inventaire": "Stock count",
  "Mot de passe du commerce": "Shop password",
  "Clé de pointage {cle}. Demandez le mot de passe à votre responsable.": "Count key {cle}. Ask your manager for the password.",
  "Valider": "Confirm",
  "{n} saisie(s) en attente : elles partiront après le mot de passe.": "{n} entry(ies) waiting: they will be sent after the password.",
  "Commerce reconnu : vous pouvez pointer.": "Shop recognised: you can start counting.",
  "Vérification impossible sans réseau.": "Cannot check without network.",
  "Mot de passe du commerce à ressaisir.": "Please enter the shop password again.",
  "Votre prénom": "Your first name",
  "Affiché au responsable à côté de vos saisies.": "Shown to the manager next to your entries.",
  "Lieu que vous comptez": "Location you are counting",
  "Commencer le pointage": "Start counting",
  "Changer de lieu ou de prénom": "Change location or name",
  "{n} en attente": "{n} waiting",
  "Tout est envoyé": "Everything sent",
  "Hors connexion": "Offline",
  "Dites ou tapez le N° de ligne": "Say or type the line number",
  "Ligne {n} inconnue": "Line {n} unknown",
  "Ligne": "Line", "Quantité": "Quantity", "Péremption": "Expiry", "Qté": "Qty", "MM/AA": "MM/YY",
  "Entendu : « {texte} »": "Heard: “{texte}”",
  "Annuler la dernière": "Undo last",
  "J'écoute… (toucher pour couper)": "Listening… (tap to stop)",
  "Dicter": "Dictate", "Suivant": "Next", "Voix active": "Voice on", "Voix coupée": "Voice off",
  "Dites « ligne 245, 12, mars 2027, suivant » — ou tapez puis touchez ✓. « Annule » efface la dernière.":
    "Say “line 245, 12, March 2027, next” — or type then tap ✓. “Undo” removes the last one.",
  "Aucune saisie pour l'instant.": "No entries yet.",
  "en attente": "waiting", "reçue": "received", "additionnée": "added up", "refusée": "rejected", "annulée": "undone",
  "Ligne {n} inconnue dans cet inventaire.": "Line {n} is not in this count.",
  "Quantité manquante.": "Quantity missing.",
  "Ligne {n} enregistrée : {q}": "Line {n} saved: {q}",
  "Enregistré. Suivant.": "Saved. Next.",
  "Aucune saisie à annuler.": "Nothing to undo.",
  "Annulation impossible sans réseau : réessayez dans un instant.": "Cannot undo without network: try again shortly.",
  "Ligne {n} annulée.": "Line {n} undone.",
  "Dictée non disponible sur ce navigateur : utilisez Chrome, ou le clavier.": "Dictation not available in this browser: use Chrome, or the keyboard.",
  "Micro refusé : autorisez-le dans le navigateur.": "Microphone blocked: allow it in the browser.",
  "Dictée impossible sans réseau : utilisez le clavier.": "Dictation needs a network: use the keyboard.",
  "Ligne {n} déjà comptée dans ce lieu : quantités ADDITIONNÉES.": "Line {n} already counted in this location: quantities ADDED UP.",
  "Saisie refusée : {e}": "Entry rejected: {e}",
  "QR code expiré ou inventaire clôturé : les saisies restantes ne peuvent plus être envoyées.": "QR code expired or count closed: remaining entries can no longer be sent.",
  "Inventaire inaccessible.": "Count not available.",
  "Télécharger l'application Android (pointage hors connexion)": "Download the Android app (offline counting)",
  // --- Espace pointage du responsable (/pointage-espace)
  "Espace pointage": "Count area",
  "Inventaires de votre commerce, comptés au téléphone.": "Your shop's stock counts, done on phones.",
  "Clé de pointage": "Count key", "Mot de passe": "Password", "Se connecter": "Sign in", "Se déconnecter": "Sign out",
  "La clé et le mot de passe sont remis par SAWALI à chaque commerce autorisé au pointage.": "The key and password are given by SAWALI to each shop allowed to count.",
  "Bienvenue, {nom}.": "Welcome, {nom}.", "Connexion impossible.": "Sign-in failed.", "Patientez…": "Please wait…", "Déconnecté.": "Signed out.",
  "Session expirée ou clé révoquée : reconnectez-vous.": "Session expired or key revoked: please sign in again.",
  // --- Inventaires (rubrique et Espace pointage)
  "Pour tout lieu de commerce : les auxiliaires scannent le QR code avec leur téléphone, puis dictent « ligne, quantité, péremption, suivant ». Le résultat s'exporte en JSON pour Aizenta ou en CSV pour Excel.":
    "Staff scan the QR code with their phone, then say “line, quantity, expiry, next”. Results export to CSV for Excel (or JSON for Aizenta).",
  "Nouvel inventaire": "New count", "Actualiser la liste": "Refresh list", "Actualisation en cours…": "Refreshing…",
  "{n} inventaire(s) relu(s).": "{n} count(s) loaded.", "Lecture impossible.": "Cannot load.",
  "N°": "No.", "Structure": "Shop", "Inventaire": "Count", "Lignes": "Lines", "Comptées": "Counted", "Avancement": "Progress",
  "État": "Status", "Créé le": "Created", "Actions": "Actions", "● En cours": "● Open", "■ Clôturé": "■ Closed", "Liste CSV": "CSV list",
  "Suivre / QR code / exporter": "Follow / QR code / export",
  "Aucun inventaire : créez-en un avec le pictogramme +.": "No count yet: create one with the + icon.",
  "{n} inventaire(s)": "{n} count(s)",
  "Nouvel inventaire par téléphone": "New phone count",
  "Liste des produits : JSON d'Aizenta ou CSV (Excel : colonnes « Libellé » ou « Désignation », et si possible « N° », « Code », « Stock »)":
    "Product list: CSV (Excel: a “Product” column, and if possible “No.”, “Code”, “Stock”) or Aizenta JSON",
  "{n} produits": "{n} products", "Lieux de stockage": "Storage locations",
  "Pour Aizenta, chaque lieu s'ajoute à l'une de ses deux colonnes (INV SV ou INV Mag). L'export CSV garde une colonne par lieu.":
    "For Aizenta, each location is added to one of its two columns (INV SV or INV Mag). The CSV export keeps one column per location.",
  "Ajouter un lieu": "Add a location", "Retirer ce lieu": "Remove this location", "Fermer": "Close", "Créer l'inventaire": "Create the count",
  "Création de l'inventaire en cours…": "Creating the count…", "Inventaire {n} créé ({l} lignes).": "Count {n} created ({l} lines).",
  "Création impossible.": "Cannot create.", "Fichier refusé : {e}": "File rejected: {e}",
  "{f} lignes comptées": "{f} lines counted", "Actualiser": "Refresh",
  "Exporter le JSON complété (à réimporter dans Aizenta)": "Export completed JSON (for Aizenta)",
  "Exporter en CSV (Excel : une colonne par lieu, écart, péremption)": "Export to CSV (Excel: one column per location, difference, expiry)",
  "Nouveau QR code (l'ancien ne marche plus)": "New QR code (the old one stops working)", "Clôturer l'inventaire": "Close the count",
  "Rouvrir l'inventaire": "Reopen the count", "Suivi": "Progress", "Alertes ({n})": "Alerts ({n})",
  "Valable jusqu'au {d}. À montrer aux auxiliaires : un scan avec le téléphone ouvre le pointage.": "Valid until {d}. Show it to staff: scanning it with a phone opens the count.",
  "Inventaire clôturé : le QR code ne fonctionne plus.": "Count closed: the QR code no longer works.",
  "Copier le lien": "Copy link", "Lien copié.": "Link copied.",
  "Par lieu": "By location", "Lieu": "Location", "Colonne": "Column", "Saisies": "Entries", "Par auxiliaire (prénom déclaré, non vérifiable)": "By staff member (declared name, not verified)",
  "Prénom": "Name", "Dernière": "Last", "Aucune alerte.": "No alerts.", "Lignes non comptées": "Lines not counted", "Lignes comptées": "Counted lines",
  "Toutes les lignes": "All lines", "Produit": "Product", "Avant": "Expected", "Écart": "Diff.", "Pérempt.": "Expiry", "Par": "By",
  "{n} ligne(s)": "{n} line(s)", "En cours…": "Working…", "Action impossible.": "Action failed.", "Export impossible.": "Export failed.",
  "Nouveau QR code créé.": "New QR code created.", "Inventaire clôturé.": "Count closed.", "Inventaire rouvert : nouveau QR code.": "Count reopened: new QR code.",
  "Clôturer ? Les téléphones ne pourront plus saisir.": "Close? Phones will no longer be able to enter counts.",
  "Préparation du fichier CSV…": "Preparing the CSV file…", "Préparation du JSON complété…": "Preparing the JSON file…",
  "{nom} téléchargé : à ouvrir avec Excel.": "{nom} downloaded: open it with Excel.", "{nom} téléchargé : à réimporter dans Aizenta.": "{nom} downloaded: import it into Aizenta.",
  "{c} ligne(s) comptée(s) sur {t}, {a} alerte(s).": "{c} line(s) counted out of {t}, {a} alert(s).",
  // --- Souscription (lot 500)
  "Ma souscription au pointage": "My stock count subscription", "Souscription illimitée": "Unlimited subscription",
  "Souscription valide jusqu'au {d}": "Subscription valid until {d}", "Sans souscription valide": "No valid subscription",
  "{n} demande(s) en attente": "{n} request(s) pending", "Souscription relue.": "Subscription reloaded.",
  "Sans souscription vérifiée, ni l'Espace ni les téléphones ne peuvent pointer. Les saisies déjà comptées pendant une période payée peuvent encore être envoyées.":
    "Without a verified subscription, neither the Count area nor phones can count. Entries counted during a paid period can still be sent.",
  "Prolonger la souscription": "Extend the subscription", "Souscrire": "Subscribe", "Formule": "Plan", "Opérateur": "Operator",
  "Semaine": "Week", "Mois": "Month", "Année": "Year", "Illimité": "Unlimited",
  "Composer sur ce téléphone": "Dial on this phone", "Copier la séquence": "Copy the code", "Séquence copiée.": "Code copied.",
  "Payez avec cette séquence, puis saisissez la référence (ID) de la transaction reçue par SMS.": "Pay with this code, then enter the transaction reference (ID) received by SMS.",
  "Référence de la transaction": "Transaction reference", "Envoyer la référence pour vérification": "Send the reference for checking",
  "Vérification du paiement en cours…": "Checking the payment…", "Paiement vérifié : souscription active.": "Payment verified: subscription active.",
  "Demande enregistrée : elle sera vérifiée dès réception du SMS de paiement, ou par SAWALI.": "Request saved: it will be checked as soon as the payment SMS arrives, or by SAWALI.",
  "Envoi impossible.": "Cannot send.", "Les formules ne sont pas encore proposées : contactez SAWALI.": "Plans are not available yet: contact SAWALI.",
  "En attente de vérification": "Awaiting verification", "Vérifiée": "Verified", "Refusée": "Rejected",
  "Le pointage de ce commerce est suspendu : souscription expirée ou pas encore vérifiée. Prévenez votre responsable.":
    "Counting is suspended for this shop: subscription expired or not yet verified. Tell your manager.",
};

/** Texte dans la langue demandée (« fr » par défaut), avec remplacement des {variables}. */
export function traduire(langue, fr, vars = {}) {
  const modele = langue === "en" ? (EN[fr] ?? fr) : fr;
  return modele.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}

/** Fonction de traduction liée à une langue : `const t = traducteur("en"); t("Suivant")`. */
export const traducteur = (langue) => (fr, vars) => traduire(langue, fr, vars);

/** Langue de la reconnaissance et de la synthèse vocales. */
export const langueVoix = (langue) => (langue === "en" ? "en-US" : "fr-FR");

/** Page de Loois mobile dans ShuyahStore (bouton « Télécharger l'application Android »). */
export const URL_APP_ANDROID = "https://shuyahstore.store/app/bf.sawali.loois.mobile";
