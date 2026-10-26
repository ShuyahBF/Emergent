/*
  Lot 314 — Image « Niveaux de service » à envoyer au contact par WhatsApp : la disponibilité vendue comme un ENGAGEMENT de prise en
  charge (contrat / standard / EXPRESS), pas comme un créneau horaire. Même image pour tous les contacts. Aucun titre d'évènement,
  aucun nom de client ; le tarif EXPRESS n'apparaît que si le propriétaire a coché « Afficher le tarif » (sinon il se traite en conversation).
  - genererImageNiveaux()    : dessine l'image dans un canvas et renvoie un fichier PNG (File).
*/

export const COULEURS_NIVEAUX = {
  contrat: { fond: "#dcfce7", bord: "#16a34a", texte: "#14532d" },
  standard: { fond: "#e0f2fe", bord: "#0284c7", texte: "#0c4a6e" },
  express: { fond: "#fef3c7", bord: "#d97706", texte: "#78350f" },
};

function lignes(c, texte, largeurMax) {
  const mots = String(texte || "").split(" ");
  const sortie = [];
  let ligne = "";
  for (const m of mots) {
    const essai = ligne ? `${ligne} ${m}` : m;
    if (c.measureText(essai).width > largeurMax && ligne) { sortie.push(ligne); ligne = m; } else ligne = essai;
  }
  if (ligne) sortie.push(ligne);
  return sortie;
}

export async function genererImageNiveaux({ config }) {
  const L = 1080, marge = 40, hauteurCarte = 270, ecart = 28, hautEntete = 190, hautPied = 130;
  const ordre = ["contrat", "standard", "express"];
  const H = hautEntete + ordre.length * (hauteurCarte + ecart) + hautPied;
  const canvas = document.createElement("canvas");
  canvas.width = L; canvas.height = H;
  const c = canvas.getContext("2d");
  const police = (px, gras = true) => `${gras ? "bold " : ""}${px}px Arial, Helvetica, sans-serif`;

  c.fillStyle = "#ffffff"; c.fillRect(0, 0, L, H);
  c.fillStyle = "#0f4c81"; c.fillRect(0, 0, L, 170);
  c.fillStyle = "#ffffff"; c.font = police(56); c.fillText(config.societe || "Prise en charge", marge, 84, L - 2 * marge);
  c.font = police(36, false); c.fillText("Nos engagements de prise en charge", marge, 134);

  ordre.forEach((cle, i) => {
    const n = config.niveaux[cle], col = COULEURS_NIVEAUX[cle];
    const y = hautEntete + i * (hauteurCarte + ecart);
    c.fillStyle = col.fond; c.beginPath(); c.roundRect(marge, y, L - 2 * marge, hauteurCarte, 28); c.fill();
    c.lineWidth = 5; c.strokeStyle = col.bord; c.stroke();
    c.fillStyle = col.texte; c.font = police(46); c.fillText(n.libelle, marge + 36, y + 76, L - 2 * marge - 300);
    c.font = police(30, false);
    lignes(c, n.description, L - 2 * marge - 72).slice(0, 2).forEach((t, k) => c.fillText(t, marge + 36, y + 124 + k * 38));
    // délai : en très gros, c'est l'information qui compte
    c.font = police(String(n.delai).length > 20 ? 42 : 64); c.fillStyle = col.bord;      // délai long (« Selon disponibilité… ») : plus petit pour tenir sur la carte
    c.fillText(`⏱ ${n.delai}`, marge + 36, y + 224, L - 2 * marge - 72 - (cle === "express" && n.afficher_tarif && n.tarif ? 330 : 0));
    if (cle === "express" && n.afficher_tarif && n.tarif) {
      c.font = police(44); c.textAlign = "right"; c.fillStyle = col.texte;
      c.fillText(n.tarif, L - marge - 36, y + 224, 310); c.textAlign = "left";
    }
  });

  const yPied = hautEntete + ordre.length * (hauteurCarte + ecart);
  c.fillStyle = "#475569"; c.font = police(28, false);
  lignes(c, config.mention, L - 2 * marge).slice(0, 2).forEach((t, k) => c.fillText(t, marge, yPied + 34 + k * 36));
  c.fillStyle = "#0f4c81"; c.fillRect(0, H - 56, L, 56);
  c.fillStyle = "#ffffff"; c.font = police(30); c.fillText("Répondez à ce message pour demander une intervention", marge, H - 18);

  const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
  if (!blob) throw new Error("Image impossible à générer");
  return new File([blob], "niveaux-de-service.png", { type: "image/png" });
}
