// lib/vidalReferentiels.js
// -----------------------------
// Lot 56 (SAWALI) — repris de Ster (miroir de backend/vidal_v2/referentiels.py) ;
// seule adaptation : couleurs de fond translucides (lisibles en mode sombre).
//
// § Revue d'implémentation VIDAL (reproches n°1, 2 et 3) — miroir frontend
// de backend/vidal_v2/referentiels.py : listes de valeurs VIDAL avec
// libellés français (pour les listes déroulantes), bornes de saisie,
// conversions (SA <-> date des dernières règles, mg/dL <-> µmol/L),
// calculs locaux de la fonction rénale (Cockcroft & Gault, CKD-EPI 2009)
// et contrôles de saisie IDENTIQUES à la validation serveur
// (backend/vidal_v2/modeles.py).
//
// Fichier sans dépendance React : réutilisable tel quel dans un autre
// portail (SAWALI) — voir docs/vidal-securisation/README.md.

// ---------------------------------------------------------------------------
// Listes de valeurs (code VIDAL -> libellé français)
// ---------------------------------------------------------------------------

// § MI VIDAL §6.2.3 : UNKNOWN = sexe INDÉTERMINÉ (alertes des deux sexes) ;
// "" = NON RENSEIGNÉ (balise nil, aucune alerte liée au sexe).
export const SEXES = { MALE: "Homme", FEMALE: "Femme", UNKNOWN: "Indéterminé" };
export const LIBELLE_SEXE_NON_RENSEIGNE = "Non renseigné";
/** Options du sélecteur Sexe : "Non renseigné" puis les valeurs VIDAL. */
export function optionsSexe() {
  return [{ value: "", label: LIBELLE_SEXE_NON_RENSEIGNE }, ...optionsDepuis(SEXES)];
}
/** § MI §6.2.6/6.2.7 : grossesse/allaitement pour une patiente ou un sexe non renseigné. */
export function donneesFemmeAutorisees(gender) {
  return gender === "FEMALE" || !gender;
}

// § "ALL" = allaitement en cours, durée non renseignée. MI §6.2.7 :
// <breastFeeding> est déprécié au profit de la date de début (saisie privilégiée).
export const ALLAITEMENTS = {
  NONE: "Pas d'allaitement",
  LESS_THAN_ONE_MONTH: "Depuis moins d'un mois",
  MORE_THAN_ONE_MONTH: "Depuis plus d'un mois",
  ALL: "Non renseignée",
};

export const INSUFFISANCES_HEPATIQUES = { NONE: "Aucune", MODERATE: "Modérée", SEVERE: "Sévère" };
/** § aucune valeur par défaut : "" = non renseignée (balise omise). */
export function optionsInsuffisanceHepatique() {
  return [{ value: "", label: "Non renseignée" }, ...optionsDepuis(INSUFFISANCES_HEPATIQUES)];
}

export const TYPES_DUREE = {
  MINUTE: "Minute(s)", HOUR: "Heure(s)", DAY: "Jour(s)", WEEK: "Semaine(s)", MONTH: "Mois", YEAR: "Année(s)",
};
export const UNITES_DUREE_LIBELLE_CHAMP = {
  MINUTE: "minutes", HOUR: "heures", DAY: "jours", WEEK: "semaines", MONTH: "mois", YEAR: "années",
};

export const TYPES_FREQUENCE = { THIS_DAY: "Ce jour (prise unique)", PER_DAY: "Par jour", PER_24_HOURS: "Par 24 heures" };

export const TYPES_MEDICAMENT = {
  PRODUCT: "Spécialité (produit)",
  PACK: "Présentation (package)",
  VMP: "Produit virtuel (VMP)",
  UCD: "Unité commune de dispensation (UCD)",
  PRESCRIBABLE: "Prescriptible",
  COMMON_NAME_GROUP: "Groupe de dénomination commune",
};
// § MI §6.3 : types dont les unités/voies/indications/indicateurs sont lisibles dans l'API.
export const TYPES_AVEC_LISTES = ["PRODUCT", "PACK", "VMP", "UCD"];

export const STATUTS_LIGNE = { ACTIVE: "En cours", COMPLETED: "Terminée" };

export const TYPES_GROUPE = {
  SAME_ORDER: "Même prescription",
  PREVIOUS_ORDER: "Prescription précédente (traitement en cours)",
  INFUSION: "Perfusion",
};

// § <interval><unitId> d'un <dosage> (identifiants VIDAL de la doc).
export const UNITES_INTERVALLE = {
  169: "Seconde", 59: "Minute", 41: "Heure", 15: "3 heures", 11: "12 heures",
  14: "24 heures", 44: "Jour", 77: "Semaine", 62: "Mois", 22: "Année",
};
export const UNITES_INTERVALLE_LIBELLE_CHAMP = {
  169: "secondes", 59: "minutes", 41: "heures", 15: "× 3 heures", 11: "× 12 heures",
  14: "× 24 heures", 44: "jours", 77: "semaines", 62: "mois", 22: "années",
};
// § aucune unité d'intervalle par défaut (le médecin la choisit). Pas
// d'endpoint VIDAL documenté pour ces unités : la liste ci-dessus est celle
// des valeurs AUTORISÉES décrite par la documentation.
// Ordre d'affichage logique (de la plus courte à la plus longue).
export const ORDRE_UNITES_INTERVALLE = ["169", "59", "41", "15", "11", "14", "44", "77", "62", "22"];

// § filtre "forme recherchée" de la recherche médicament (codes identiques au backend).
export const FORMES_GALENIQUES = {
  comp: "Comprimé (comp, cp)",
  gel: "Gélule (gél)",
  sol_buv: "Solution buvable (sol buv)",
  susp_buv: "Suspension buvable (susp buv)",
  sirop: "Sirop",
  pdre: "Poudre / sachet (pdre, sach)",
  inj: "Injectable (inj)",
  bain_bouche: "Bain de bouche",
  gel_buccal: "Gel / pâte buccale ou gingivale",
  creme: "Crème / pommade (cr, pom)",
  suppo: "Suppositoire (suppos)",
  collyre: "Collyre",
  spray: "Pulvérisation / spray (pulv)",
  cp_eff: "Comprimé effervescent (cp eff)",
  cp_orodisp: "Comprimé orodispersible (cp orodisp)",
};

// ---------------------------------------------------------------------------
// Bornes (identiques à BORNES côté backend)
// ---------------------------------------------------------------------------
export const BORNES = {
  semaines_amenorrhee: { min: 2, max: 42 },
  // § MI §6.2.6 : 41 SA = durée théorique — avertir au-delà ; §6.2.7 : faire confirmer un allaitement de plus de 2 ans.
  semaines_amenorrhee_alerte: 41,
  allaitement_jours_alerte: 730,
  // § MI §6.2.8 : clairance en ENTIER, jamais 0 (= insuffisance sévère pour VIDAL).
  clairance_ml_min: { min: 1, max: 120 },
  creatininemie_umol_l: { min: 10, max: 3000 },
  creatininemie_mg_dl: { min: 0.1, max: 34 },
  dfg_ml_min_173: { min: 0, max: 200 },
  poids_kg: { min: 0.3, max: 350 },
  taille_cm: { min: 20, max: 250 },
  age_ans: { min: 0, max: 130 },
  dose: { min_exclu: 0, max: 100000 },
  duree: { min: 1, max: 1000 },
  intervalle: { min: 0, max: 100000 },
  code_ald_longueur_max: 20,
};
export const FACTEUR_MG_DL_VERS_UMOL_L = 88.4;
export const JOURS_SEUIL_ALLAITEMENT_UN_MOIS = 30;

// § ancres du rapport HTML /alerts/full/html (doc VIDAL, "HTML V2").
export const ANCRES_RAPPORT_HTML = {
  menu_global: "Tout",
  menu_synthesis: "Synthèse",
  sommaire_precautions: "Sommaire des précautions",
  menu_posology: "Posologies",
  menu_allergy: "Allergies",
  menu_contraindications_precautions: "Contre-indications / précautions",
  menu_drugs_interaction: "Interactions médicamenteuses",
  menu_pregnancy: "Grossesse / allaitement / procréation",
  menu_side_effects: "Effets indésirables",
  menu_phy_chm_interaction: "Interactions physico-chimiques",
  menu_warning: "Mises en garde",
  menu_observation: "Surveillance",
  menu_dispensing_risk: "Risques lors de la dispensation",
  menu_substance_redundancy: "Redondance de substance",
  menu_profile: "Rappel du dossier patient",
  menu_prescription: "Prescription",
};

// § MI §6.5.5 : rubriques du rapport HTML filtré (<alert-display-types>).
export const RUBRIQUES_RAPPORT_HTML = {
  POSOLOGY: "Posologie",
  ALLERGY: "Allergies",
  CONTRA_INDICATION_PRECAUTION: "Contre-indications / précautions d'emploi",
  DRUG_INTERACTION: "Interactions médicamenteuses",
  REPRODUCTIVE_HEALTH: "Grossesse / allaitement / procréation",
  SIDE_EFFECT: "Effets indésirables",
  PHYSICO_CHEMICAL_INTERACTION: "Incompatibilités physico-chimiques",
  WARNING: "Mises en garde",
  SURVEILLANCE: "Surveillances",
  DISPENSING: "Risques lors de la dispensation",
  DUPLICATE: "Redondances",
};

// § MI §4.7.1 : indicateurs d'un médicament signalant qu'une donnée patient
// sert au calcul de ses alertes. Les 5 premiers (âge, poids, rénal, sexe,
// taille) manquants déclenchent une alerte INTERRUPTIVE (clic pour passer outre).
export const INDICATEURS_DONNEES_PATIENT = {
  26: "Âge", 27: "Poids", 28: "Grossesse", 29: "Allaitement", 30: "Fonction rénale (clairance)", 31: "Sexe", 36: "Taille",
};
export const INDICATEURS_INTERRUPTIFS = ["26", "27", "30", "31", "36"];

// § types d'alerte de /alerts/full (partagés page + modale).
export const LIBELLES_TYPES_ALERTE = {
  CONTRA_INDICATION: "Contre-indication", ALLERGY: "Allergie",
  DRUG_INTERACTION: "Interaction médicamenteuse", POSOLOGY: "Posologie",
  PRECAUTION: "Précaution", WARNING: "Mise en garde", SIDE_EFFECT: "Effet indésirable",
  PHYSICO_CHEMICAL_INTERACTION: "Interaction physico-chimique", SURVEILLANCE: "Surveillance",
  REDUNDANT_ACTIVE_INGREDIENT: "Principe actif redondant", SAME_DRUG: "Même médicament",
  FOOD_INTERACTION: "Interaction alimentaire", DISPENSING_RISK: "Risque de dispensation",
  PRESCRIPTION_CONTEXT: "Contexte patient", EXONERATION: "Exonération",
  INDICATOR: "Indicateur", FOCUS: "Point de vigilance", HAS: "Alerte HAS (SAM)",
};
export const TYPES_ALERTE_DEFAUT = ["CONTRA_INDICATION", "ALLERGY", "DRUG_INTERACTION", "POSOLOGY"];

export const META_SEVERITE = {
  LEVEL_4: { label: "Critique", couleur: "#e11d48" },
  LEVEL_3: { label: "Élevée", couleur: "#f97316" },
  LEVEL_2: { label: "Modérée", couleur: "#f59e0b" },
  LEVEL_1: { label: "À prendre en compte", couleur: "#0ea5e9" },
  INFO: { label: "Info", couleur: "#94a3b8" },
  NO_ALERT: { label: "Aucune alerte", couleur: "#10b981" },
};
export function fondSeverite(severite) {
  const c = { LEVEL_4: "rgba(225,29,72,0.08)", LEVEL_3: "rgba(249,115,22,0.08)", LEVEL_2: "rgba(245,158,11,0.10)" }[severite];
  return c || "var(--vidal-gris-clair)";
}

/** {code: libellé} -> [{value, label}] pour un <select>. */
export function optionsDepuis(referentiel, ordre) {
  return (ordre || Object.keys(referentiel)).map((code) => ({ value: String(code), label: referentiel[code] }));
}

// ---------------------------------------------------------------------------
// Dates (toujours en "AAAA-MM-JJ", calculées en heure locale)
// ---------------------------------------------------------------------------
function versDateLocale(iso) {
  if (!iso) return null;
  const [a, m, j] = String(iso).slice(0, 10).split("-").map(Number);
  if (!a || !m || !j) return null;
  return new Date(a, m - 1, j);
}
function versIso(d) {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const j = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${j}`;
}
export function aujourdhuiISO() {
  return versIso(new Date());
}
export function ajouterJours(iso, jours) {
  const d = versDateLocale(iso);
  if (!d) return "";
  d.setDate(d.getDate() + jours);
  return versIso(d);
}
/** Nombre de jours entiers de `debut` à `fin` (fin - debut). */
export function joursEntre(debutIso, finIso) {
  const a = versDateLocale(debutIso), b = versDateLocale(finIso);
  if (!a || !b) return null;
  return Math.round((b.getTime() - a.getTime()) / 86400000);
}
export function ageEnAnnees(dobIso, refIso = aujourdhuiISO()) {
  const d = versDateLocale(dobIso), r = versDateLocale(refIso);
  if (!d || !r) return null;
  let age = r.getFullYear() - d.getFullYear();
  if (r.getMonth() < d.getMonth() || (r.getMonth() === d.getMonth() && r.getDate() < d.getDate())) age -= 1;
  return age;
}
export function formatDateISO(dateheure) {
  return dateheure ? String(dateheure).slice(0, 10) : "";
}
/** "2026-09-09" -> "09/09/2026" */
export function formatDateFr(iso) {
  if (!iso) return "";
  const [a, m, j] = String(iso).slice(0, 10).split("-");
  return a && m && j ? `${j}/${m}/${a}` : "";
}
/** Sexe de la fiche patient -> <gender> ; absent = "" (non renseigné, balise nil). */
export function mapperGenreVidal(sexe) {
  if (sexe === "Masculin") return "MALE";
  if (sexe === "Féminin") return "FEMALE";
  return "";
}

// ---------------------------------------------------------------------------
// Grossesse : semaines d'aménorrhée <-> date des dernières règles
// ---------------------------------------------------------------------------
/** SA révolues depuis la date des dernières règles (null si date invalide/future). */
export function saDepuisDdr(ddrIso, refIso = aujourdhuiISO()) {
  const jours = joursEntre(ddrIso, refIso);
  if (jours == null || jours < 0) return null;
  return Math.floor(jours / 7);
}
/** Date des dernières règles correspondant à un nombre de SA révolues aujourd'hui. */
export function ddrDepuisSa(sa, refIso = aujourdhuiISO()) {
  const n = Number(sa);
  if (!Number.isInteger(n) || n < 0) return "";
  return ajouterJours(refIso, -7 * n);
}

// ---------------------------------------------------------------------------
// Allaitement : catégorie VIDAL déduite d'une date de début
// ---------------------------------------------------------------------------
export function categorieAllaitementDepuisDate(debutIso, refIso = aujourdhuiISO()) {
  const jours = joursEntre(debutIso, refIso);
  if (jours == null || jours < 0) return null;
  return jours < JOURS_SEUIL_ALLAITEMENT_UN_MOIS ? "LESS_THAN_ONE_MONTH" : "MORE_THAN_ONE_MONTH";
}

// ---------------------------------------------------------------------------
// Fonction rénale — mêmes formules que backend/vidal_v2/fonction_renale.py
// ---------------------------------------------------------------------------
export function mgDlVersUmolL(v) { return Number(v) * FACTEUR_MG_DL_VERS_UMOL_L; }
export function umolLVersMgDl(v) { return Number(v) / FACTEUR_MG_DL_VERS_UMOL_L; }

function coefficientCockcroft(sexe) {
  return { MALE: 1.23, FEMALE: 1.04 }[sexe] ?? null;
}
/** Cockcroft & Gault : k × (140 − âge) × poids / créatininémie (µmol/L). */
export function clairanceCockcroftGault(age, poids, sexe, creatUmol) {
  const k = coefficientCockcroft(sexe);
  if (k == null || age == null || !poids || !creatUmol) return null;
  return Math.max(0, (k * (140 - age) * poids) / creatUmol);
}
/** Inverse de Cockcroft & Gault — mêmes conditions que VIDAL : > 15 ans, 40 à 100 kg. */
export function creatininemieDepuisClairance(age, poids, sexe, clairance) {
  const k = coefficientCockcroft(sexe);
  if (k == null || age == null || age >= 140 || !poids || !clairance) return null;
  if (age <= 15 || poids < 40 || poids > 100) return null;
  return (k * (140 - age) * poids) / clairance;
}
/** CKD-EPI 2009, sans coefficient ethnique (ml/min/1,73 m²) — adulte (≥ 18 ans), comme le calculateur VIDAL. */
export function dfgCkdEpi2009(age, sexe, creatUmol) {
  if ((sexe !== "MALE" && sexe !== "FEMALE") || age == null || age < 18 || !creatUmol) return null;
  const scr = umolLVersMgDl(creatUmol);
  const femme = sexe === "FEMALE";
  const kappa = femme ? 0.7 : 0.9;
  const alpha = femme ? -0.329 : -0.411;
  const ratio = scr / kappa;
  let dfg = 141 * Math.min(ratio, 1) ** alpha * Math.max(ratio, 1) ** -1.209 * 0.993 ** age;
  if (femme) dfg *= 1.018;
  return dfg;
}
export function arrondi2(v) {
  return v == null || Number.isNaN(v) ? null : Math.round(v * 100) / 100;
}
/** Valeur de <creatin> : entier arrondi, borné de 1 à 120 ml/min (MI §6.2.8). */
export function clairanceTransmise(cl) {
  if (cl == null || Number.isNaN(cl)) return null;
  return Math.min(Math.max(Math.floor(cl + 0.5), BORNES.clairance_ml_min.min), BORNES.clairance_ml_min.max);
}
// § MI §5.2.2.1 : ≥ 90 aucune, 60–90 légère, 30–60 modérée, < 30 sévère.
export const INSUFFISANCES_RENALES = { NONE: "Pas d'insuffisance rénale", MILD: "Insuffisance rénale légère", MODERATE: "Insuffisance rénale modérée", SEVERE: "Insuffisance rénale sévère" };
export function categorieInsuffisanceRenale(cl) {
  if (cl == null) return null;
  if (cl >= 90) return "NONE";
  if (cl >= 60) return "MILD";
  if (cl >= 30) return "MODERATE";
  return "SEVERE";
}
/** Équivalent de calculer_fonction_renale_locale (backend) : {creatin, creatin_calculee, plafonnee, serumCreatinine, glomerularFiltrationRate}. */
export function calculerFonctionRenaleLocale({ dateOfBirth, gender, weight, creatUmol, clairance }) {
  const age = ageEnAnnees(dateOfBirth);
  const poids = Number(weight);
  let creat = creatUmol ? Number(creatUmol) : null;
  let cl = clairance ? Number(clairance) : null;
  if (creat) cl = clairanceCockcroftGault(age, poids, gender, creat);
  else if (cl) creat = creatininemieDepuisClairance(age, poids, gender, cl);
  const dfg = creat ? dfgCkdEpi2009(age, gender, creat) : null;
  const max = BORNES.clairance_ml_min.max;
  return {
    creatin: clairanceTransmise(cl),
    creatin_calculee: arrondi2(cl),
    plafonnee: cl != null && cl > max,
    serumCreatinine: arrondi2(creat),
    glomerularFiltrationRate: arrondi2(dfg),
    insuffisanceRenale: categorieInsuffisanceRenale(cl),
  };
}

// ---------------------------------------------------------------------------
// Libellés de champs avec unité entre parenthèses (exigence utilisateur)
// ---------------------------------------------------------------------------
export function libelleChampDuree(durationType) {
  return `Durée (${UNITES_DUREE_LIBELLE_CHAMP[durationType] || "unité à choisir"})`;
}
/** § MI §6.4.4 : <dose> = dose CUMULÉE par 24 h (avec sa fréquence) ; dose par prise dans <dosage>. */
export function libelleChampDose(unitLabel, frequencyType) {
  const unite = unitLabel || "unité de prise";
  if (frequencyType === "PER_DAY" || frequencyType === "PER_24_HOURS") return `Dose par 24 h (${unite})`;
  if (frequencyType === "THIS_DAY") return `Dose, prise unique (${unite})`;
  return `Dose (${unite})`;
}
export function libelleChampDoseParPrise(unitLabel) {
  return `Dose par prise (${unitLabel || "unité de prise"})`;
}
export function libelleChampIntervalle(prefixe, unitId) {
  return `${prefixe} (${UNITES_INTERVALLE_LIBELLE_CHAMP[unitId] || "heures"})`;
}

/** Dernier jour d'administration (début + durée − 1 jour) ; mois/année approchés à 30/365 jours. */
export function calculerDateFin(debutIso, duree, durationType) {
  const n = Number(duree);
  if (!debutIso || !Number.isInteger(n) || n < 1) return "";
  const jours = { MINUTE: 0, HOUR: 0, DAY: 1, WEEK: 7, MONTH: 30, YEAR: 365 }[durationType];
  if (jours == null) return "";
  return ajouterJours(debutIso, Math.max(n * jours - 1, 0));
}

// ---------------------------------------------------------------------------
// Contrôles de saisie — mêmes règles que la validation serveur
// ---------------------------------------------------------------------------
function estVide(v) {
  return v === null || v === undefined || v === "";
}
function controlerBorne(erreurs, champ, valeur, cle, libelle, { entier = false, messageHorsBornes = null } = {}) {
  if (estVide(valeur)) return;
  const n = Number(String(valeur).replace(",", "."));
  if (Number.isNaN(n)) { erreurs[champ] = `${libelle} doit être un nombre.`; return; }
  if (entier && !Number.isInteger(n)) { erreurs[champ] = `${libelle} doit être un nombre entier (sans décimales).`; return; }
  const b = BORNES[cle];
  if (b.min_exclu != null && n <= b.min_exclu) { erreurs[champ] = `${libelle} doit être strictement supérieur(e) à ${b.min_exclu}.`; return; }
  const min = b.min ?? b.min_exclu ?? 0;
  if ((b.min != null && n < b.min) || n > b.max) erreurs[champ] = messageHorsBornes || `${libelle} doit être compris(e) entre ${min} et ${b.max}.`;
}
function controlerDateNonFuture(erreurs, champ, valeur, libelle) {
  if (!estVide(valeur) && joursEntre(aujourdhuiISO(), valeur) > 0) erreurs[champ] = `${libelle} ne peut pas être dans le futur.`;
}

/**
 * Contrôle l'état clinique saisi (voir cliniqueVide dans
 * components/vidal/DonneesCliniquesPatient.jsx). Retourne {champ: message}
 * — objet vide si tout est correct.
 */
export function validerPatient(c) {
  const e = {};
  controlerDateNonFuture(e, "dateOfBirth", c.dateOfBirth, "La date de naissance");
  const age = ageEnAnnees(c.dateOfBirth);
  if (!e.dateOfBirth && age != null && age > BORNES.age_ans.max) e.dateOfBirth = `La date de naissance correspond à un âge supérieur à ${BORNES.age_ans.max} ans.`;
  controlerBorne(e, "weight", c.weight, "poids_kg", "Le poids (kg)");
  controlerBorne(e, "height", c.height, "taille_cm", "La taille (cm)");
  controlerDateNonFuture(e, "weightDate", c.weightDate, "La date de saisie");
  if (donneesFemmeAutorisees(c.gender)) {
    if (c.grossesse) {
      if (estVide(c.weeksOfAmenorrhea) && estVide(c.lastMenstrualPeriodDate)) {
        e.weeksOfAmenorrhea = "Saisissez la date des dernières règles ou les semaines d'aménorrhée (SA).";
      }
      controlerDateNonFuture(e, "lastMenstrualPeriodDate", c.lastMenstrualPeriodDate, "La date des dernières règles");
      if (!e.lastMenstrualPeriodDate && c.lastMenstrualPeriodDate && c.dateOfBirth && joursEntre(c.dateOfBirth, c.lastMenstrualPeriodDate) <= 0) {
        e.lastMenstrualPeriodDate = "La date des dernières règles doit être postérieure à la date de naissance.";
      }
      if (!e.weeksOfAmenorrhea) controlerBorne(e, "weeksOfAmenorrhea", c.weeksOfAmenorrhea, "semaines_amenorrhee", "Les semaines d'aménorrhée (SA)", {
        entier: true,
        messageHorsBornes: `Les semaines d'aménorrhée (SA) doivent être comprises entre ${BORNES.semaines_amenorrhee.min} et ${BORNES.semaines_amenorrhee.max}.`,
      });
      if (!e.lastMenstrualPeriodDate && !e.weeksOfAmenorrhea && c.lastMenstrualPeriodDate) {
        const sa = saDepuisDdr(c.lastMenstrualPeriodDate);
        if (sa != null && (sa < BORNES.semaines_amenorrhee.min || sa > BORNES.semaines_amenorrhee.max)) {
          e.lastMenstrualPeriodDate = `Cette date correspond à ${sa} SA : la grossesse doit être comprise entre ${BORNES.semaines_amenorrhee.min} et ${BORNES.semaines_amenorrhee.max} SA.`;
        }
      }
    }
    if (c.allaitement && c.breastFeedingStartDate) {
      controlerDateNonFuture(e, "breastFeedingStartDate", c.breastFeedingStartDate, "La date de début d'allaitement");
      if (!e.breastFeedingStartDate && c.dateOfBirth && joursEntre(c.dateOfBirth, c.breastFeedingStartDate) <= 0) {
        e.breastFeedingStartDate = "La date de début d'allaitement doit être postérieure à la date de naissance.";
      }
    }
  }
  if (c.creatinineUnite === "mg_dl") controlerBorne(e, "creatinineSaisie", c.creatinineSaisie, "creatininemie_mg_dl", "La créatininémie (mg/dL)");
  else controlerBorne(e, "creatinineSaisie", c.creatinineSaisie, "creatininemie_umol_l", "La créatininémie (µmol/L)");
  controlerBorne(e, "creatin", c.creatin, "clairance_ml_min", "La clairance de la créatinine (ml/min)", {
    entier: true,
    messageHorsBornes: "La clairance de la créatinine (ml/min) doit être un entier compris entre 1 et 120 (au-delà de 120 : saisir 120 ; inconnue : laisser vide, jamais 0).",
  });
  controlerBorne(e, "glomerularFiltrationRate", c.glomerularFiltrationRate, "dfg_ml_min_173", "Le débit de filtration glomérulaire (ml/min/1,73 m²)");
  controlerDateNonFuture(e, "renalDate", c.renalDate, "La date du bilan rénal");
  return e;
}

/** Contrôle une ligne de prescription (état de LignePrescriptionVidal). Retourne {champ: message}. */
export function validerLigne(l) {
  const e = {};
  if (!l.vidal_id) e.medicament = "Choisissez le médicament dans la recherche VIDAL.";
  controlerBorne(e, "dose", l.dose, "dose", "La dose");
  if (!e.dose && !estVide(l.dose) && !l.unitId) e.unitId = "Choisissez l'unité de la dose (comprimé, ml...).";
  if (!e.dose && !estVide(l.dose) && !l.frequencyType) {
    e.frequencyType = "Choisissez la fréquence de la dose par 24 h (ou laissez la dose vide et utilisez dose par prise + intervalle pour des prises espacées de plus de 24 h).";
  }
  controlerBorne(e, "duration", l.duration, "duree", "La durée", { entier: true });
  if (!e.duration && !estVide(l.duration) && !l.durationType) e.durationType = "Choisissez l'unité de la durée.";
  if (l.startDate && l.endDate && joursEntre(l.startDate, l.endDate) < 0) e.endDate = "La date de fin doit être postérieure ou égale à la date de début.";
  if (l.ald) {
    if (!String(l.aldCode || "").trim()) e.aldCode = "Le code ALD est obligatoire quand la ligne est prise en charge en ALD.";
    else if (String(l.aldCode).trim().length > BORNES.code_ald_longueur_max) e.aldCode = `Le code ALD ne doit pas dépasser ${BORNES.code_ald_longueur_max} caractères.`;
  }
  (l.dosages || []).forEach((d, i) => {
    controlerBorne(e, `dosages.${i}.dose`, d.dose, "dose", "La dose");
    controlerBorne(e, `dosages.${i}.intervalMin`, d.intervalMin, "intervalle", "L'intervalle minimum");
    controlerBorne(e, `dosages.${i}.intervalMax`, d.intervalMax, "intervalle", "L'intervalle maximum");
    if (!estVide(d.intervalMin) && !estVide(d.intervalMax) && Number(d.intervalMin) > Number(d.intervalMax)) {
      e[`dosages.${i}.intervalMax`] = "L'intervalle maximum doit être supérieur ou égal à l'intervalle minimum.";
    }
    if ((!estVide(d.intervalMin) || !estVide(d.intervalMax)) && !d.intervalUnitId) {
      e[`dosages.${i}.intervalUnitId`] = "Choisissez l'unité de l'intervalle entre les prises.";
    }
  });
  return e;
}

// ---------------------------------------------------------------------------
// Payloads envoyés au backend
// ---------------------------------------------------------------------------
function nombreOuNull(v) {
  if (estVide(v)) return null;
  const n = Number(String(v).replace(",", "."));
  return Number.isNaN(n) ? null : n;
}

/** Ligne (état du composant) -> ligne du payload /vidal/securisation/analyze. */
export function versPayloadLigne(l) {
  return {
    drugRef: l.vidal_id || null, drugType: l.drugType || "PRODUCT", label: l.label || null,
    dose: nombreOuNull(l.dose), unitId: l.unitId || null, unitLabel: l.unitLabel || null,
    duration: nombreOuNull(l.duration), durationType: estVide(l.duration) ? null : l.durationType || null,
    frequencyType: l.frequencyType || null, route: l.route || null, indication: l.indication || null,
    dosages: (l.dosages || [])
      .filter((d) => !estVide(d.dose) || !estVide(d.intervalMin) || !estVide(d.intervalMax))
      .map((d) => ({ dose: nombreOuNull(d.dose), unitId: l.unitId || null, intervalMin: nombreOuNull(d.intervalMin), intervalMax: nombreOuNull(d.intervalMax), intervalUnitId: d.intervalUnitId || null })),
    startDate: l.startDate || null, endDate: l.endDate || null,
    status: l.status || "ACTIVE", groupType: l.groupType || null,
    ald: !!l.ald, aldCode: l.ald ? String(l.aldCode || "").trim() || null : null,
  };
}

/** Message lisible d'une erreur API (422 détaillé {message, erreurs[]} ou texte simple). */
export function messageErreurApi(err, defaut = "Erreur inconnue.") {
  const detail = err?.response?.data?.detail;
  if (!detail) return err?.message || defaut;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || String(d)).join(" ; ");
  if (Array.isArray(detail.erreurs) && detail.erreurs.length) return detail.erreurs.map((e) => e.message).join(" ; ");
  return detail.message || defaut;
}

// ---------------------------------------------------------------------------
// Avertissements non bloquants (MI §6.2.6 / §6.2.7)
// ---------------------------------------------------------------------------
export function avertissementsCliniques(c) {
  const a = {};
  if (!donneesFemmeAutorisees(c.gender)) return a;
  const sa = Number(c.weeksOfAmenorrhea);
  if (c.grossesse && Number.isInteger(sa) && sa > BORNES.semaines_amenorrhee_alerte && sa <= BORNES.semaines_amenorrhee.max) {
    a.weeksOfAmenorrhea = `${sa} SA : au-delà de la durée théorique de ${BORNES.semaines_amenorrhee_alerte} SA — vérifiez que la grossesse est toujours en cours.`;
  }
  const jours = c.allaitement && c.breastFeedingStartDate ? joursEntre(c.breastFeedingStartDate, aujourdhuiISO()) : null;
  if (jours != null && jours > BORNES.allaitement_jours_alerte) {
    a.breastFeedingStartDate = "Allaitement de plus de 2 ans : confirmez qu'il est toujours en cours.";
  }
  return a;
}

// ---------------------------------------------------------------------------
// § MI §4.7.1 — données patient requises par les médicaments prescrits
// ---------------------------------------------------------------------------
function donneePresente(c, indicateur) {
  switch (String(indicateur)) {
    case "26": return !!c.dateOfBirth;
    case "27": return !estVide(c.weight);
    case "36": return !estVide(c.height);
    case "31": return !!c.gender;
    case "30": return !estVide(c.creatin);
    default: return true;
  }
}
/**
 * À partir des indicateurs chargés sur chaque ligne (`ligne.indicateurs`),
 * liste les données patient manquantes. `interruptives` : âge, poids,
 * taille, sexe, fonction rénale (le médecin doit cliquer pour passer
 * outre) ; `informations` : grossesse/allaitement (risque à signaler).
 */
export function donneesPatientManquantes(c, lignes) {
  const interruptives = {};
  const informations = {};
  lignes.filter((l) => l.vidal_id && Array.isArray(l.indicateurs)).forEach((l) => {
    l.indicateurs.forEach(({ id }) => {
      const cle = String(id);
      if (INDICATEURS_INTERRUPTIFS.includes(cle) && !donneePresente(c, cle)) {
        (interruptives[cle] = interruptives[cle] || []).push(l.label);
      } else if ((cle === "28" && c.grossesse) || (cle === "29" && c.allaitement)) {
        (informations[cle] = informations[cle] || []).push(l.label);
      }
    });
  });
  const versListe = (o) => Object.entries(o).map(([id, medicaments]) => ({ id, libelle: INDICATEURS_DONNEES_PATIENT[id], medicaments: [...new Set(medicaments)] }));
  return { interruptives: versListe(interruptives), informations: versListe(informations) };
}

// ---------------------------------------------------------------------------
// § demande utilisateur — groupes de référence du DFG (aide d'interprétation
// LOCALE, jamais transmise à VIDAL ; même logique que
// backend/vidal_v2/groupes_dfg.py). Seuils par défaut : ≥ 90 % de la
// référence = normal, 60–89 % = légèrement diminué, < 60 % = diminué.
// ---------------------------------------------------------------------------
export const SEUILS_DFG_DEFAUT = { normal_pct: 90, leger_pct: 60 };
export const GROUPES_DFG_DEFAUT = [
  { id: "groupe_a", libelle: "Groupe A (référence 84)", valeur_normale: 84, actif: true, ordre: 1, par_defaut: true },
  { id: "groupe_b", libelle: "Groupe B (référence 74)", valeur_normale: 74, actif: true, ordre: 2, par_defaut: false },
];
export const NIVEAUX_DFG = {
  NORMAL: { libelle: "Normal", couleur: "#2fa84f", fond: "rgba(47,168,79,0.10)" },
  LEGEREMENT_DIMINUE: { libelle: "Légèrement diminué", couleur: "#d97706", fond: "rgba(217,119,6,0.10)" },
  DIMINUE: { libelle: "Diminué", couleur: "#e0392b", fond: "rgba(224,57,43,0.10)" },
};
export function groupeDfgParDefaut(groupes) {
  const actifs = (groupes || []).filter((g) => g.actif).sort((a, b) => (a.ordre || 0) - (b.ordre || 0));
  return actifs.find((g) => g.par_defaut) || actifs[0] || null;
}
export function interpreterDfg(dfg, valeurNormale, seuils = SEUILS_DFG_DEFAUT) {
  const d = Number(dfg), ref = Number(valeurNormale);
  if (estVide(dfg) || Number.isNaN(d) || !ref) return null;
  const pourcentage = Math.round((d / ref) * 1000) / 10;
  const niveau = pourcentage >= seuils.normal_pct ? "NORMAL" : pourcentage >= seuils.leger_pct ? "LEGEREMENT_DIMINUE" : "DIMINUE";
  return { pourcentage, niveau, ...NIVEAUX_DFG[niveau] };
}
