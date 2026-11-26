// ============================================================================
// Lot 470 — Sonde réseau : petits calculs PURS (sans réseau, sans écran), testés dans sondeReseauCalculs.test.js.
// Utilisés par le moteur de mesure (lib/sondeReseau.js) et par l'écran des Paramètres (SondeReseauSection.jsx).
// ============================================================================

// Seuils d'affichage : mêmes valeurs que le rapport HTML du serveur (backend/sonde_reseau.py)
export const SEUIL_PERTE_ATTENTION = 2;      // % de perte : au-delà, connexion « instable » (orange)
export const SEUIL_PERTE_CRITIQUE = 10;      // % de perte : au-delà, connexion « très dégradée » (rouge)
export const DEBIT_FAIBLE_MBPS = 5;          // sous ce débit descendant : lent

// Latence : durées (en ms) des requêtes réussies + nombre de requêtes perdues -> synthèse envoyée au serveur
export function statsLatence(durees, perdus) {
  const ok = (durees || []).filter((d) => Number.isFinite(d));
  const essais = ok.length + (perdus || 0);
  if (!ok.length) return { essais, perdus: perdus || 0, moy: null, min: null, max: null };
  const somme = ok.reduce((a, b) => a + b, 0);
  return { essais, perdus: perdus || 0, moy: Math.round((somme / ok.length) * 10) / 10, min: Math.round(Math.min(...ok) * 10) / 10, max: Math.round(Math.max(...ok) * 10) / 10 };
}

// Débit en Mb/s (mégabits par seconde) à partir d'un nombre d'octets et d'une durée en millisecondes ; null si la mesure est inexploitable
export function debitMbps(octets, ms) {
  if (!(octets > 0) || !(ms > 0)) return null;
  return Math.round(((octets * 8) / 1e6 / (ms / 1000)) * 10) / 10;
}

// Les débits (téléchargement de 10 Mo + envoi de 2 Mo) ne sont mesurés qu'UNE FOIS PAR HEURE pour ne pas saturer la ligne ni consommer les données mobiles :
// avec une mesure toutes les 15 minutes, un cycle sur quatre (le premier, puis le 5e, le 9e…) mesure aussi les débits et la vidéo.
export function doitMesurerDebit(numeroCycle, intervalleMin) {
  const tous = Math.max(1, Math.round(60 / Math.max(1, intervalleMin)));
  return numeroCycle % tous === 0;
}

// Perte en % d'une mesure (null si aucun essai)
export function pctPerte(m) {
  return m && m.essais > 0 ? Math.round((m.perdus / m.essais) * 1000) / 10 : null;
}

// Couleur de la perte : jamais la couleur seule dans l'écran (le chiffre est toujours écrit), mais elle guide l'œil
export function niveauPerte(pct) {
  if (pct == null) return "inconnu";
  if (pct >= SEUIL_PERTE_CRITIQUE) return "critique";
  if (pct >= SEUIL_PERTE_ATTENTION) return "attention";
  return "ok";
}

export function niveauDebit(mbps) {
  if (mbps == null) return "inconnu";
  return mbps < DEBIT_FAIBLE_MBPS ? "attention" : "ok";
}

// Classes de couleur (texte) par niveau
export const COULEUR_NIVEAU = { ok: "text-emerald-700", attention: "text-orange-700", critique: "text-red-700", inconnu: "text-slate-500" };

// Heure de la prochaine mesure : « HH:MM »
export function heureProchaine(maintenantMs, intervalleMin) {
  return new Date(maintenantMs + intervalleMin * 60000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

// Export CSV des mesures (séparateur « ; » et virgule décimale : s'ouvre directement dans Excel en français)
export function enCsv(mesures) {
  const nb = (v) => (v == null ? "" : String(v).replace(".", ","));
  const entetes = ["Date (UTC)", "Poste", "Type", "Essais", "Perdus", "Perte %", "Latence moy ms", "Latence min ms", "Latence max ms", "HTTPS ok", "HTTPS total", "Débit descendant Mb/s", "Débit montant Mb/s", "Démarrage vidéo ms", "Saccades vidéo"];
  const lignes = (mesures || []).map((m) => [m.le, m.poste, m.type, m.essais, m.perdus, nb(pctPerte(m)), nb(m.latence_moy_ms), nb(m.latence_min_ms), nb(m.latence_max_ms),
    m.https_ok, m.https_total, nb(m.debit_desc_mbps), nb(m.debit_mont_mbps), nb(m.video_demarrage_ms), m.video_saccades ?? ""]);
  const protege = (c) => { const t = c == null ? "" : String(c); return /[;"\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  return [entetes, ...lignes].map((l) => l.map(protege).join(";")).join("\r\n");
}
