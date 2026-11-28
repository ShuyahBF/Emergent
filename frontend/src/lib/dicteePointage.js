// dicteePointage.js — Lot 496 : comprend une phrase dictée (ou tapée) au téléphone pendant le pointage d'inventaire.
// « ligne 245, 12, mars 2027, suivant » → { chrono: 245, qte: 12, peremption: "03/2027", commande: "suivant" }.
// AUCUNE IA : un simple analyseur des nombres et des mois en français (rapide, gratuit, fonctionne hors connexion).
// Parallèle WinDev : c'est une procédure qui découpe une chaîne avec ExtraitChaîne puis convertit chaque morceau avec Val().

// --- Vocabulaire ---------------------------------------------------------------------------------------------------
const UNITES = { zero: 0, un: 1, une: 1, deux: 2, trois: 3, quatre: 4, cinq: 5, six: 6, sept: 7, huit: 8, neuf: 9, dix: 10,
  onze: 11, douze: 12, treize: 13, quatorze: 14, quinze: 15, seize: 16 };
const DIZAINES = { vingt: 20, vingts: 20, trente: 30, quarante: 40, cinquante: 50, soixante: 60, septante: 70, huitante: 80, octante: 80, nonante: 90 };
const MOIS = { janvier: 1, fevrier: 2, mars: 3, avril: 4, mai: 5, juin: 6, juillet: 7, aout: 8, septembre: 9, octobre: 10, novembre: 11, decembre: 12 };
// Mots qui annoncent la valeur suivante (« quantité 12 ») ; sans eux, l'ordre fait foi : ligne, quantité, péremption
const ETIQUETTES = { ligne: "chrono", numero: "chrono", n: "chrono", no: "chrono", ordre: "chrono", produit: "chrono",
  quantite: "qte", qte: "qte", nombre: "qte", stock: "qte", peremption: "peremption", perime: "peremption", expire: "peremption",
  expiration: "peremption", date: "peremption", lot: "peremption" };
const SUIVANT = new Set(["suivant", "suivante", "valider", "valide", "enregistre", "enregistrer", "ok", "okay", "next"]);
const ANNULE = new Set(["annule", "annuler", "efface", "effacer", "corrige", "corriger", "supprime", "supprimer"]);
const IGNORES = new Set(["et", "de", "du", "la", "le", "les", "a", "au", "en", "fin", "boite", "boites", "unite", "unites", "pieces", "piece"]);

/** Minuscules, sans accents ; les signes deviennent des espaces, sauf « / » entre deux chiffres (« 03/27 »). */
export function normaliser(texte) {
  return String(texte || "")
    .normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
    .replace(/n°/g, " numero ")
    .replace(/(\d)\s*[/.-]\s*(\d)/g, "$1/$2")        // « 03 / 2027 » → « 03/2027 »
    .replace(/[^a-z0-9/]+/g, " ")
    .trim();
}

/**
 * Découpe la phrase en jetons : {t: "nombre", v} · {t: "mois", v} · {t: "date", mois, annee} · {t: "etiquette", v} · {t: "commande", v}.
 * Les nombres écrits en toutes lettres sont regroupés (« deux cent quarante cinq » → 245) ; deux unités qui se suivent
 * commencent deux nombres différents (« cinq douze » → 5 puis 12), sauf après « dix » (« soixante dix sept » → 77).
 */
export function jetons(texte) {
  const mots = normaliser(texte).split(/\s+/).filter(Boolean);
  const sortie = [];
  let total = null, courant = 0, dernier = null;           // nombre en toutes lettres en cours de lecture
  const finirNombre = () => {
    if (total !== null) sortie.push({ t: "nombre", v: total + courant });
    total = null; courant = 0; dernier = null;
  };
  for (const mot of mots) {
    if (mot === "et" && total !== null) continue;          // « vingt et un » : le « et » ne coupe pas le nombre
    if (mot in UNITES) {
      const v = UNITES[mot];
      const nouveau = total !== null && dernier !== null && dernier < 20 && !(dernier === 10 && v < 10) && dernier !== 100;
      if (nouveau) finirNombre();
      if (total === null) total = 0;
      courant += v; dernier = v;
    } else if (mot in DIZAINES) {
      if (total === null) total = 0;
      // « quatre vingt » = 4 × 20 ; sinon les dizaines s'ajoutent
      if (DIZAINES[mot] === 20 && courant % 100 === 4 && dernier === 4) courant = courant - 4 + 80;
      // une dizaine juste après une unité ou une autre dizaine commence un NOUVEAU nombre (« trois, vingt et un » → 3 puis 21)
      else if (dernier !== null && dernier !== 100) { finirNombre(); total = 0; courant = DIZAINES[mot]; }
      else courant += DIZAINES[mot];
      dernier = 20;
    } else if (mot === "cent" || mot === "cents") {
      if (total === null) total = 0;
      courant = (courant || 1) * 100; dernier = 100;
    } else if (mot === "mille") {
      if (total === null) total = 0;
      total += (courant || 1) * 1000; courant = 0; dernier = 100;
    } else {
      finirNombre();
      let m;
      if ((m = mot.match(/^(\d{1,2})\/(\d{2}|\d{4})$/))) sortie.push({ t: "date", mois: +m[1], annee: +m[2] });
      else if (/^\d+$/.test(mot)) sortie.push({ t: "nombre", v: parseInt(mot, 10), brut: mot });   // brut : garde le zéro de tête (« 062028 »)
      else if (mot in MOIS) sortie.push({ t: "mois", v: MOIS[mot] });
      else if (mot in ETIQUETTES) sortie.push({ t: "etiquette", v: ETIQUETTES[mot] });
      else if (SUIVANT.has(mot)) sortie.push({ t: "commande", v: "suivant" });
      else if (ANNULE.has(mot)) sortie.push({ t: "commande", v: "annule" });
      // les autres mots (« et », « boîtes », mots mal compris) sont ignorés
    }
  }
  finirNombre();
  return sortie;
}

/** Mois + année (année sur 2 ou 4 chiffres) → « MM/AAAA », ou null si invalide. */
export function dateMoisAnnee(mois, annee) {
  if (annee < 100) annee += 2000;
  if (!(mois >= 1 && mois <= 12 && annee >= 2000 && annee <= 2099)) return null;
  return `${String(mois).padStart(2, "0")}/${annee}`;
}

/**
 * Comprend une phrase. Renvoie { chrono, qte, peremption, commande, reste } : seuls les champs entendus sont remplis
 * (undefined sinon) ; `reste` = nombres non utilisés (signalés au téléphone).
 */
export function analyserDictee(texte) {
  const js = jetons(texte);
  const res = { chrono: undefined, qte: undefined, peremption: undefined, commande: null, reste: [] };
  let cible = null;                       // champ annoncé par une étiquette (« quantité … »)
  const ordre = ["chrono", "qte", "peremption"];
  const prochainLibre = () => ordre.find((c) => res[c] === undefined);
  for (let i = 0; i < js.length; i++) {
    const j = js[i];
    if (j.t === "commande") { res.commande = j.v; continue; }
    if (j.t === "etiquette") { cible = j.v; continue; }
    // Péremption : « mars 2027 », « 03/2027 », ou deux nombres (mois puis année) à la place de la péremption
    if (j.t === "mois" || j.t === "date") {
      const annee = j.t === "date" ? j.annee : js[i + 1]?.t === "nombre" ? js[++i].v : null;
      const mois = j.t === "date" ? j.mois : j.v;
      const d = annee !== null ? dateMoisAnnee(mois, annee) : null;
      if (d) res.peremption = d;
      cible = null;
      continue;
    }
    if (j.t !== "nombre") continue;
    const champ = cible || prochainLibre();
    cible = null;
    if (champ === "peremption") {
      const suivant = js[i + 1];
      const d = suivant?.t === "nombre" ? dateMoisAnnee(j.v, suivant.v) : null;
      if (d) { res.peremption = d; i++; }
      else if (/^\d{6}$/.test(j.brut || "")) res.peremption = dateMoisAnnee(+j.brut.slice(0, 2), +j.brut.slice(2)) || undefined;   // « 032027 »
      else res.reste.push(j.v);
    } else if (champ) res[champ] = j.v;
    else res.reste.push(j.v);
  }
  return res;
}
