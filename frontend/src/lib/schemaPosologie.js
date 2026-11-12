// Lot 377 (remarques VIDAL 4 et 6) — schéma de prise complexe, dégressif ou progressif : logique pure, miroir de
// backend/vidal_v2/posologie.py (mêmes règles : à VIDAL on n'envoie que le palier à la dose journalière la PLUS ÉLEVÉE).
// Un schéma = liste de paliers { debut_jour, fin_jour|null, prises: [{ moment, heure, quantite, repas }] }.

// Moments de la journée (liste finie -> liste déroulante).
export const MOMENTS = [
  { value: "matin", label: "Matin" }, { value: "midi", label: "Midi" }, { value: "soir", label: "Soir" },
  { value: "coucher", label: "Coucher" }, { value: "heure", label: "À une heure précise" },
];
// Position par rapport au repas.
export const REPAS = [
  { value: "indifferent", label: "Indifférent" }, { value: "avant", label: "Avant le repas" },
  { value: "pendant", label: "Pendant le repas" }, { value: "apres", label: "Après le repas" },
];

const nombre = (v) => { const n = parseFloat(String(v ?? "").replace(",", ".")); return Number.isFinite(n) ? n : 0; };

export const nouvellePrise = () => ({ moment: "matin", heure: "", quantite: "1", repas: "indifferent" });
export const nouveauPalier = (debut = 0) => ({ debut_jour: debut, fin_jour: null, prises: [nouvellePrise()] });

// Dose par 24 h d'un palier = somme des quantités de ses prises.
export const doseJournaliere = (palier) => (palier?.prises || []).reduce((t, p) => t + nombre(p.quantite), 0);

// Palier à la dose la plus élevée (le premier en cas d'égalité) : c'est lui qui part à VIDAL.
export function palierMaximal(schema) {
  let meilleur = null;
  for (const p of schema || []) if (doseJournaliere(p) > 0 && (!meilleur || doseJournaliere(p) > doseJournaliere(meilleur))) meilleur = p;
  return meilleur;
}

// constant / progressif / degressif / variable
export function tendance(schema) {
  const d = (schema || []).map(doseJournaliere).filter((x) => x > 0);
  if (d.length <= 1 || new Set(d).size === 1) return "constant";
  if (d.every((x, i) => i === 0 || x >= d[i - 1])) return "progressif";
  if (d.every((x, i) => i === 0 || x <= d[i - 1])) return "degressif";
  return "variable";
}
export const LIBELLE_TENDANCE = { constant: "", progressif: "Posologie progressive", degressif: "Posologie dégressive", variable: "Posologie variable" };

const fmt = (n) => String(n).replace(".", ",");

// « 2 comprimés le matin avant le repas »
export function libellePrise(prise, unite = "") {
  const m = MOMENTS.find((x) => x.value === prise.moment)?.label.toLowerCase() || "";
  const moment = prise.moment === "heure" ? (prise.heure ? `à ${prise.heure}` : "") : prise.moment === "matin" ? "le matin" : prise.moment === "midi" ? "à midi" : prise.moment === "soir" ? "le soir" : prise.moment === "coucher" ? "au coucher" : m;
  const repas = { avant: "avant le repas", pendant: "pendant le repas", apres: "après le repas" }[prise.repas] || "";
  return [fmt(nombre(prise.quantite)), unite, moment, repas].filter(Boolean).join(" ");
}

// Texte imprimable : un palier par ligne.
export function libelleSchema(schema, unite = "") {
  return (schema || []).map((p) => {
    const prises = (p.prises || []).filter((x) => nombre(x.quantite) > 0).map((x) => libellePrise(x, unite)).join(" ; ");
    if (!prises) return null;
    const d = parseInt(p.debut_jour || 0, 10);
    let quand = d === 0 ? "Dès aujourd'hui" : `À partir du jour ${d + 1} (dans ${d} jour${d > 1 ? "s" : ""})`;
    if (p.fin_jour !== null && p.fin_jour !== "" && p.fin_jour !== undefined) quand += `, jusqu'au jour ${parseInt(p.fin_jour, 10) + 1}`;
    return `${quand} : ${prises}`;
  }).filter(Boolean).join("\n");
}

// Erreurs lisibles (liste vide = correct) : chevauchement, fin avant début.
export function validerSchema(schema) {
  const erreurs = []; let finPrec = null;
  (schema || []).forEach((p, i) => {
    const d = parseInt(p.debut_jour || 0, 10); const f = p.fin_jour === null || p.fin_jour === "" || p.fin_jour === undefined ? null : parseInt(p.fin_jour, 10);
    if (f !== null && f < d) erreurs.push(`Palier ${i + 1} : le jour de fin précède le jour de début.`);
    if (finPrec !== null && d <= finPrec) erreurs.push(`Palier ${i + 1} : chevauche le palier précédent.`);
    finPrec = f === null ? 1e6 : f;
  });
  return erreurs;
}

// Champs de la ligne de prescription déduits du palier maximal (dose par 24 h) — null si schéma vide.
export function champsLigneDepuisSchema(schema) {
  const p = palierMaximal(schema);
  return p ? { dose: String(doseJournaliere(p)), frequencyType: "PER_DAY" } : null;
}
