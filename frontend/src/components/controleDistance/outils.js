// =====================================================================
// Lot 135 — Contrôle à distance : outils de la visionneuse (sans affichage).
// Pour un développeur WinDev : ce sont les « procédures globales » partagées par la visionneuse, le volet du poste
// et le clavier virtuel (format des trames, découpage des fichiers, mise en forme des valeurs).
// =====================================================================

// Types des trames binaires (octet 0) — mêmes valeurs que Loois (ControleDistanceLogique.cs) et le serveur
export const TRAME_TUILE = 1;
export const TRAME_FICHIER_VERS_POSTE = 2;
export const TRAME_FICHIER_VERS_TECHNICIEN = 3;

// Morceau de fichier envoyé (256 Ko) et taille maximale (2 Go), comme sur le poste
export const TAILLE_MORCEAU = 256 * 1024;
export const TAILLE_MAX_FICHIER = 2 * 1024 * 1024 * 1024;

// File d'envoi du WebSocket au-delà de laquelle on attend (ne pas saturer une liaison lente)
const TAMPON_MAX = 4 * 1024 * 1024;

/** Trame d'un morceau de fichier : octet 0 = type, octets 1-4 = identifiant (u32 petit-boutiste), puis les données. */
export function trameFichier(type, id, donnees) {
  const octets = new Uint8Array(donnees);
  const trame = new Uint8Array(5 + octets.length);
  trame[0] = type;
  new DataView(trame.buffer).setUint32(1, id >>> 0, true);
  trame.set(octets, 5);
  return trame.buffer;
}

/** Lit l'en-tête d'une trame de fichier reçue (type 3) : { id, donnees } ou null. */
export function lireTrameFichier(tampon) {
  if (!tampon || tampon.byteLength < 5) return null;
  const vue = new DataView(tampon);
  return { type: vue.getUint8(0), id: vue.getUint32(1, true), donnees: tampon.slice(5) };
}

/** Attend que la file d'envoi du WebSocket se vide un peu (liaison lente). */
export async function attendreTampon(ws) {
  while (ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount > TAMPON_MAX) {
    await new Promise((ok) => setTimeout(ok, 50));
  }
}

/**
 * Envoie un fichier au poste par morceaux : « fichier_debut », trames binaires de type 2, « fichier_fin ».
 * `progression(octets)` est appelée après chaque morceau. Renvoie faux si la connexion s'est fermée en route.
 */
export async function envoyerFichier(ws, id, fichier, progression, dossier = "") {
  // `dossier` : dossier de base mémorisé pour ce poste (vide = « Reçu du support SAWALI » sur son Bureau)
  ws.send(JSON.stringify({ type: "fichier_debut", id, nom: fichier.name, taille: fichier.size, chemin: dossier || "" }));
  for (let debut = 0; debut < fichier.size; debut += TAILLE_MORCEAU) {
    if (ws.readyState !== WebSocket.OPEN) return false;
    const morceau = await fichier.slice(debut, Math.min(fichier.size, debut + TAILLE_MORCEAU)).arrayBuffer();
    await attendreTampon(ws);
    ws.send(trameFichier(TRAME_FICHIER_VERS_POSTE, id, morceau));
    progression?.(Math.min(fichier.size, debut + TAILLE_MORCEAU));
  }
  ws.send(JSON.stringify({ type: "fichier_fin", id }));
  return true;
}

/** Fait télécharger un Blob par le navigateur sous le nom donné. */
export function telecharger(blob, nom) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nom || "fichier";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

/** Taille lisible : « 850 Ko », « 3,2 Mo », « 1,4 Go ». */
export function tailleLisible(octets) {
  const o = Number(octets) || 0;
  if (o < 1024) return `${o} o`;
  if (o < 1024 * 1024) return `${Math.max(1, Math.round(o / 1024))} Ko`;
  if (o < 1024 * 1024 * 1024) return `${(o / 1024 / 1024).toFixed(1).replace(".", ",")} Mo`;
  return `${(o / 1024 / 1024 / 1024).toFixed(1).replace(".", ",")} Go`;
}

/** Durée lisible : « 45 s », « 12 min », « 1 h 05 ». */
export function dureeLisible(s) {
  if (s === null || s === undefined) return "—";
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")}`;
}

/** Date lisible « 12/10/2026 14:05 ». */
export const dateLisible = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

/** Moyenne d'une liste de nombres (null si vide). */
export function moyenne(valeurs) {
  const v = (valeurs || []).filter((x) => typeof x === "number" && Number.isFinite(x));
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

/**
 * Mesures de fin de session envoyées au serveur (item 8). `c` : compteurs de la visionneuse.
 * Les valeurs sont arrondies ; le serveur ignore ce qui est hors bornes.
 */
export function mesuresFinales(c, moteur, echelle) {
  const latences = c.latences || [];
  const m = {
    octets_recus: Math.round(c.octetsTotal || 0),
    duree_affichee_s: c.debutAffichage ? Math.round((Date.now() - c.debutAffichage) / 1000) : 0,
  };
  if (c.premiereImageMs !== null && c.premiereImageMs !== undefined) m.premiere_image_ms = Math.round(c.premiereImageMs);
  const lat = moyenne(latences);
  if (lat !== null) {
    m.latence_moy_ms = Math.round(lat);
    m.latence_max_ms = Math.round(Math.max(...latences));
  }
  const ips = moyenne(c.ips);
  if (ips !== null) m.ips_moyen = Math.round(ips * 10) / 10;
  if (m.duree_affichee_s > 0) m.debit_moy_ko = Math.round(m.octets_recus / 1024 / m.duree_affichee_s);
  if (moteur) m.capture = moteur;
  if (echelle) m.echelle = echelle;
  return m;
}

/** Libellés des actions système (confirmation demandée avant l'envoi). */
export const ACTIONS_SYSTEME = {
  ctrl_alt_suppr: { titre: "Ctrl+Alt+Suppr", texte: "Envoyer Ctrl+Alt+Suppr au poste (écran de sécurité de Windows) ?", danger: false },
  verrouiller: { titre: "Verrouiller", texte: "Verrouiller le poste ? L'utilisateur devra saisir son mot de passe.", danger: false },
  deconnecter: { titre: "Déconnecter l'utilisateur", texte: "Fermer la session Windows de l'utilisateur ? Les documents non enregistrés seront perdus.", danger: true },
  redemarrer: { titre: "Redémarrer", texte: "Redémarrer le poste dans 5 secondes ? Les applications seront fermées de force. Le service Windows Loois permet de reprendre la main après le redémarrage.", danger: true },
  eteindre: { titre: "Éteindre", texte: "Éteindre le poste dans 5 secondes ? Il faudra le rallumer sur place.", danger: true },
};

// ---------------------------------------------------------------------
// Lot 135 — TRANSFERT DE POSTE À POSTE : chaque visionneuse en mode « Contrôler » s'inscrit ici avec la fonction qui
// dépose un fichier sur SON poste. Le volet « Fichiers » d'un autre onglet peut ainsi copier un fichier d'un poste
// contrôlé vers un autre (le fichier passe par le navigateur du technicien, à travers SAWALI).
// ---------------------------------------------------------------------
export const registrePostes = new Map();   // posteId → { nom, recevoir(blob, nom) }

/** Postes contrôlés ouverts dans les autres onglets (destinations possibles d'une copie). */
export function autresPostes(posteId) {
  return [...registrePostes.entries()].filter(([id]) => id !== posteId).map(([id, p]) => ({ id, nom: p.nom, recevoir: p.recevoir }));
}
