/*
  Lot 313 — Image des disponibilités à envoyer par WhatsApp (au lieu d'un lien que personne n'ouvre).
  Pour chaque jour ouvré : une barre horaire (vert = libre, gris = occupé) et, en gros caractères, les créneaux LIBRES.
  Même règle que le lien partagé : tous les évènements (rendez-vous, planning, Google, créneaux bloqués) comptent comme « occupé »,
  sans titre ni nom de client.
  - calculerLibres()         : calcul pur des créneaux libres d'un jour (testé dans calendrierImage.test.js) ;
  - genererImageDisponibilites() : dessine l'image dans un canvas et renvoie un fichier PNG (File).
*/

const JOURS_COURTS = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
const MIN_CRENEAU_MIN = 20;                       // un trou de moins de 20 minutes n'est pas annoncé comme « libre »

const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}h${String(min % 60).padStart(2, "0")}`;
const heureNum = (txt, defaut) => {
  const [h, m] = String(txt || "").split(":").map((x) => parseInt(x, 10));
  return Number.isFinite(h) ? h * 60 + (Number.isFinite(m) ? m : 0) : defaut;
};

/** Plages occupées d'un jour, en minutes depuis minuit, fusionnées et limitées à [ouv, fer]. */
export function plagesOccupees(jour, occupations, ouv, fer) {
  const j0 = new Date(jour); j0.setHours(0, 0, 0, 0);
  const plages = [];
  for (const o of occupations || []) {
    const d = (new Date(o.debut) - j0) / 60000, f = (new Date(o.fin) - j0) / 60000;
    if (!(f > ouv && d < fer)) continue;
    plages.push([Math.max(d, ouv), Math.min(f, fer)]);
  }
  plages.sort((a, b) => a[0] - b[0]);
  const fusion = [];
  for (const p of plages) {
    if (fusion.length && p[0] <= fusion[fusion.length - 1][1]) fusion[fusion.length - 1][1] = Math.max(fusion[fusion.length - 1][1], p[1]);
    else fusion.push([p[0], p[1]]);
  }
  return fusion;
}

/** Créneaux libres d'un jour : le complémentaire des plages occupées dans les horaires d'ouverture. */
export function calculerLibres(jour, occupations, ouv, fer) {
  const libres = [];
  let curseur = ouv;
  for (const [d, f] of plagesOccupees(jour, occupations, ouv, fer)) {
    if (d - curseur >= MIN_CRENEAU_MIN) libres.push([Math.round(curseur), Math.round(d)]);
    curseur = Math.max(curseur, f);
  }
  if (fer - curseur >= MIN_CRENEAU_MIN) libres.push([Math.round(curseur), Math.round(fer)]);
  return libres;
}

export const texteLibres = (libres) => (libres.length ? libres.map(([d, f]) => `${hhmm(d)} – ${hhmm(f)}`).join("   ·   ") : "Complet");

/** Libellé de la période : « Jeudi 29/10 », « Du 29/10 au 31/10 » ou « Semaine du … au … » */
export function libellePeriode(t0, fin, jours, fr) {
  if (jours === 1) return `${["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"][t0.getDay()]} ${fr(t0)}`;
  if (jours <= 3) return `Du ${fr(t0)} au ${fr(fin)}`;
  return `Semaine du ${fr(t0)} au ${fr(fin)}`;
}

/** Dessine l'image (PNG) des disponibilités de la semaine et la renvoie sous forme de fichier. */
export async function genererImageDisponibilites({ debut, jours = 7, horaires, occupations = [], titre = "Mes disponibilités" }) {
  const ouv = heureNum(horaires?.ouverture, 7 * 60), fer = heureNum(horaires?.fermeture, 19 * 60);
  const ouvres = horaires?.jours_ouvres?.length ? horaires.jours_ouvres : [1, 2, 3, 4, 5, 6];   // 1 = lundi … 6 = samedi (0 = dimanche)
  const t0 = new Date(debut);
  const colonnes = Array.from({ length: jours }, (_, i) => new Date(t0.getTime() + i * 86400000)).filter((j) => ouvres.includes(j.getDay()));
  // Lot 318 : période choisie = 1 jour, 3 jours ou la semaine ; si tous les jours sont fermés (ex. un dimanche), pas d'image
  if (!colonnes.length) throw new Error("Aucun jour ouvré sur cette période (dimanche ?) : choisissez un autre jour");

  const L = 1080, marge = 36, hauteurLigne = 168, hautEntete = 190, hautPied = 140;
  const H = hautEntete + colonnes.length * hauteurLigne + hautPied;
  const canvas = document.createElement("canvas");
  canvas.width = L; canvas.height = H;
  const c = canvas.getContext("2d");
  const police = (px, gras = true) => `${gras ? "bold " : ""}${px}px Arial, Helvetica, sans-serif`;

  c.fillStyle = "#ffffff"; c.fillRect(0, 0, L, H);
  // En-tête
  c.fillStyle = "#0f4c81"; c.fillRect(0, 0, L, 150);
  c.fillStyle = "#ffffff"; c.font = police(54); c.fillText(titre, marge, 70);
  const fin = new Date(t0.getTime() + (jours - 1) * 86400000);
  const fr = (d) => d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
  c.font = police(34, false);
  c.fillText(libellePeriode(t0, fin, jours, fr), marge, 118);
  c.fillStyle = "#334155"; c.font = police(30, false);
  c.fillText("Vert = libre · Gris = déjà occupé", marge, 176);

  // Une ligne par jour : nom du jour, barre horaire, créneaux libres en gros caractères
  const xBarre = 190, largeurBarre = L - xBarre - marge;
  const xDe = (min) => xBarre + ((min - ouv) / (fer - ouv)) * largeurBarre;
  colonnes.forEach((jour, i) => {
    const y = hautEntete + i * hauteurLigne;
    const occ = plagesOccupees(jour, occupations, ouv, fer);
    const libres = calculerLibres(jour, occupations, ouv, fer);
    if (i % 2 === 0) { c.fillStyle = "#f8fafc"; c.fillRect(0, y, L, hauteurLigne); }
    c.fillStyle = "#0f172a"; c.font = police(44); c.fillText(JOURS_COURTS[jour.getDay()], marge, y + 62);
    c.fillStyle = "#475569"; c.font = police(32, false); c.fillText(fr(jour), marge, y + 104);
    // barre : fond vert (libre), blocs gris (occupé)
    c.fillStyle = "#86efac"; c.fillRect(xBarre, y + 24, largeurBarre, 46);
    c.fillStyle = "#94a3b8";
    for (const [d, f] of occ) c.fillRect(xDe(d), y + 24, Math.max(3, xDe(f) - xDe(d)), 46);
    c.strokeStyle = "#e2e8f0"; c.lineWidth = 2; c.strokeRect(xBarre, y + 24, largeurBarre, 46);
    // repères d'heures (toutes les 2 heures)
    c.fillStyle = "#64748b"; c.font = police(22, false);
    for (let h = Math.ceil(ouv / 60); h * 60 <= fer; h += 2) c.fillText(`${h}h`, xDe(h * 60) - 10, y + 94);
    // créneaux libres en gros
    c.fillStyle = libres.length ? "#15803d" : "#b91c1c"; c.font = police(libres.length > 2 ? 30 : 36);
    c.fillText(texteLibres(libres), xBarre, y + 140, largeurBarre);
  });

  // Pied de page
  const yPied = hautEntete + colonnes.length * hauteurLigne;
  c.fillStyle = "#0f4c81"; c.fillRect(0, yPied + 20, L, hautPied - 20);
  c.fillStyle = "#ffffff"; c.font = police(36); c.fillText("Répondez avec le créneau qui vous convient", marge, yPied + 76);
  c.font = police(26, false); c.fillText("Horaires : " + hhmm(ouv) + " – " + hhmm(fer), marge, yPied + 114);

  const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
  if (!blob) throw new Error("Image impossible à générer");
  return new File([blob], `disponibilites-${t0.toISOString().slice(0, 10)}.png`, { type: "image/png" });
}
