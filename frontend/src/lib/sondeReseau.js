// ============================================================================
// Lot 470 — Sonde réseau : MOTEUR DE MESURE exécuté dans le navigateur du poste (PC branché à la box, ou téléphone).
// Toutes les mesures vont VERS CLOUDFLARE et des services publics (jamais vers SAWALI : aucune charge pour le site). Rien n'est installé :
// l'écran « Sonde réseau » des Paramètres appelle `executerCycle` toutes les 15 minutes et envoie le résultat à SAWALI en arrière-plan.
// Un navigateur ne sait pas faire de vrai « ping » : la perte est estimée par les requêtes HTTPS sans réponse dans le délai (2 s).
// ============================================================================
import { statsLatence, debitMbps } from "@/lib/sondeReseauCalculs";

const CLOUDFLARE = "https://speed.cloudflare.com";
export const CIBLE_LATENCE = `${CLOUDFLARE}/__down?bytes=0`;          // réponse vide : mesure du seul aller-retour
export const CIBLE_DESCENDANT = `${CLOUDFLARE}/__down?bytes=10000000`; // 10 Mo
export const CIBLE_MONTANT = `${CLOUDFLARE}/__up`;                    // envoi de données
// Connexions HTTPS réelles : 3 services publics (les deux derniers sans lecture de la réponse, d'où « no-cors »)
export const CIBLES_HTTPS = [
  { url: `${CLOUDFLARE}/__down?bytes=1`, cors: true },
  { url: "https://www.google.com/generate_204", cors: false },
  { url: "https://1.1.1.1/", cors: false },
];
// Flux vidéo public de démonstration (lu en sourdine 6 s) ; à changer ici si l'adresse disparaît
export const CIBLE_VIDEO = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4";

export const DELAI_REQUETE_MS = 2000;       // sans réponse au bout de 2 s = paquet perdu
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

// Une requête chronométrée : { ok, ms }. Jamais d'exception : un échec ou un dépassement de délai est un résultat (« perdu »).
async function requeteChronometree(url, { cors = true, delai = DELAI_REQUETE_MS } = {}) {
  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), delai);
  const debut = performance.now();
  try {
    await fetch(`${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`, { cache: "no-store", mode: cors ? "cors" : "no-cors", signal: ctrl.signal });
    return { ok: true, ms: performance.now() - debut };
  } catch { return { ok: false, ms: null }; }
  finally { clearTimeout(minuteur); }
}

// 10 requêtes l'une après l'autre (un petit intervalle entre chacune) -> latence et perte
export async function mesurerLatence(n = 10) {
  const durees = []; let perdus = 0;
  for (let i = 0; i < n; i++) {
    const r = await requeteChronometree(CIBLE_LATENCE);
    if (r.ok) durees.push(r.ms); else perdus += 1;
    await dormir(200);
  }
  return statsLatence(durees, perdus);
}

// 3 essais vers chacun des 3 services : combien de connexions HTTPS réelles aboutissent
export async function mesurerHttps() {
  let ok = 0, total = 0;
  for (const c of CIBLES_HTTPS) {
    for (let i = 0; i < 3; i++) { total += 1; if ((await requeteChronometree(c.url, { cors: c.cors, delai: 4000 })).ok) ok += 1; }
  }
  return { https_ok: ok, https_total: total };
}

// Téléchargement de 10 Mo (10 s au plus) : débit calculé sur les octets effectivement reçus, à partir du premier octet
export async function mesurerDebitDescendant(maxMs = 10000) {
  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), maxMs);
  try {
    const rep = await fetch(`${CIBLE_DESCENDANT}&_=${Date.now()}`, { cache: "no-store", signal: ctrl.signal });
    const lecteur = rep.body.getReader();
    let octets = 0, debut = null;
    for (;;) {
      const { done, value } = await lecteur.read();
      if (done) break;
      if (debut === null) debut = performance.now();      // le chronomètre démarre au premier octet (hors latence de connexion)
      octets += value.length;
    }
    return debitMbps(octets, performance.now() - (debut ?? performance.now()));
  } catch {
    return null;                                           // échec ou délai dépassé : pas de débit pour ce cycle
  } finally { clearTimeout(minuteur); }
}

// Envoi de 2 Mo de données aléatoires (10 s au plus) : débit montant
export async function mesurerDebitMontant(octets = 2_000_000, maxMs = 10000) {
  const donnees = new Uint8Array(octets);
  for (let i = 0; i < octets; i += 65536) crypto.getRandomValues(donnees.subarray(i, Math.min(i + 65536, octets)));   // 65536 octets au plus par appel
  const ctrl = new AbortController();
  const minuteur = setTimeout(() => ctrl.abort(), maxMs);
  const debut = performance.now();
  try {
    await fetch(CIBLE_MONTANT, { method: "POST", body: donnees, headers: { "Content-Type": "text/plain" }, cache: "no-store", signal: ctrl.signal });
    return debitMbps(octets, performance.now() - debut);
  } catch { return null; }
  finally { clearTimeout(minuteur); }
}

// Lecture d'un flux vidéo en sourdine pendant 6 s : temps de démarrage et nombre d'arrêts de mise en mémoire (saccades) ; null si le navigateur refuse
export function mesurerVideo(dureeMs = 6000) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.muted = true; v.playsInline = true; v.preload = "auto"; v.src = `${CIBLE_VIDEO}`;
    let demarrage = null, saccades = 0, fini = false;
    const debut = performance.now();
    const terminer = (res) => { if (fini) return; fini = true; clearTimeout(minuteur); v.pause(); v.removeAttribute("src"); v.load(); resolve(res); };
    v.addEventListener("playing", () => { if (demarrage === null) demarrage = Math.round(performance.now() - debut); });
    v.addEventListener("waiting", () => { if (demarrage !== null) saccades += 1; });     // arrêt en cours de lecture
    v.addEventListener("error", () => terminer(null));
    const minuteur = setTimeout(() => terminer(demarrage === null ? { video_demarrage_ms: null, video_saccades: null } : { video_demarrage_ms: demarrage, video_saccades: saccades }), dureeMs + 4000);
    v.play().then(() => setTimeout(() => terminer(demarrage === null ? null : { video_demarrage_ms: demarrage, video_saccades: saccades }), dureeMs)).catch(() => terminer(null));
  });
}

// Un CYCLE complet : renvoie l'objet envoyé à POST /api/sonde-reseau/mesures. `etape(texte)` informe l'écran de l'avancement.
export async function executerCycle({ poste, type, avecDebit, etape = () => {} }) {
  etape("Mesure de la latence et des pertes…");
  const lat = await mesurerLatence();
  etape("Test des connexions HTTPS…");
  const https = await mesurerHttps();
  const mesure = {
    poste, type, essais: lat.essais, perdus: lat.perdus, latence_moy_ms: lat.moy, latence_min_ms: lat.min, latence_max_ms: lat.max, ...https,
    connexion: (typeof navigator !== "undefined" && navigator.connection && navigator.connection.effectiveType) || null,
  };
  if (avecDebit) {
    etape("Mesure du débit descendant (10 Mo)…");
    mesure.debit_desc_mbps = await mesurerDebitDescendant();
    etape("Mesure du débit montant (2 Mo)…");
    mesure.debit_mont_mbps = await mesurerDebitMontant();
    etape("Lecture d'un flux vidéo…");
    const v = await mesurerVideo();
    if (v) { mesure.video_demarrage_ms = v.video_demarrage_ms; mesure.video_saccades = v.video_saccades; }
  }
  return mesure;
}
