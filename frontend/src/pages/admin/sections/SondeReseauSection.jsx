// ============================================================================
// Lot 470 — Paramètres → « 📶 Sonde réseau — débit et stabilité de la connexion ».
// Cette page, laissée OUVERTE dans le navigateur d'un PC branché à la box (ou d'un téléphone), mesure toutes les 15 minutes la latence, la perte de paquets, les
// connexions HTTPS réelles, et une fois par heure les débits descendant / montant et la lecture d'un flux vidéo, VERS CLOUDFLARE (aucune charge pour SAWALI).
// Chaque mesure est envoyée à SAWALI en arrière-plan (jamais bloquant) ; en dessous : synthèse colorée, courbes, tableau triable, RAPPORT HTML à partager
// (par exemple avec l'opérateur) et export CSV.
// Backend : POST/GET/DELETE /api/sonde-reseau/mesures, GET /api/sonde-reseau/rapport (administrateur seul). Moteur : lib/sondeReseau.js.
// ============================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Download, Eraser, FileDown, Play, RefreshCw, Square, Wifi } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { executerCycle } from "@/lib/sondeReseau";
import { COULEUR_NIVEAU, doitMesurerDebit, enCsv, heureProchaine, niveauDebit, niveauPerte, pctPerte, SEUIL_PERTE_ATTENTION } from "@/lib/sondeReseauCalculs";

const INTERVALLES = [5, 15, 30, 60];                         // minutes
const PERIODES = [{ j: 1, l: "Dernières 24 h" }, { j: 7, l: "7 derniers jours" }, { j: 30, l: "30 derniers jours" }];
const lire = (cle, defaut) => { try { return window.localStorage.getItem(cle) ?? defaut; } catch { return defaut; } };
const ecrire = (cle, v) => { try { window.localStorage.setItem(cle, v); } catch { /* stockage indisponible : sans effet */ } };
const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
const num = (n, d = 1) => (n == null ? "—" : Number(n).toLocaleString("fr-FR", { maximumFractionDigits: d }));

// Petite courbe SVG d'une série de valeurs (une ligne, repère orange facultatif)
function Courbe({ titre, valeurs, couleur, unite, repere }) {
  const pts = valeurs.map((v, i) => ({ v, i })).filter((p) => p.v != null);
  if (pts.length < 2) return <div className="text-xs text-slate-500"><b>{titre}</b> : la courbe apparaît après 2 mesures.</div>;
  const L = 320, H = 70, max = Math.max(...pts.map((p) => p.v), repere || 0) || 1;
  const x = (i) => (i * L) / (valeurs.length - 1), y = (v) => H - (v / max) * (H - 8);
  return (
    <div>
      <p className="text-xs font-semibold text-slate-700">{titre} <span className="font-normal text-slate-500">(maximum {num(max)} {unite})</span></p>
      <svg viewBox={`0 0 ${L} ${H + 4}`} className="w-full max-w-sm" role="img" aria-label={titre}>
        {repere ? <line x1="0" x2={L} y1={y(repere)} y2={y(repere)} stroke="#d97706" strokeDasharray="4 3" strokeWidth="1" /> : null}
        <polyline fill="none" stroke={couleur} strokeWidth="2" points={pts.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")} />
      </svg>
    </div>);
}

function Carte({ titre, valeur, detail, niveau }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3 bg-white">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{titre}</p>
      <p className={`text-xl font-bold tabular-nums ${COULEUR_NIVEAU[niveau || "inconnu"]}`}>{valeur}</p>
      {detail && <p className="text-[11px] text-slate-500">{detail}</p>}
    </div>);
}

export default function SondeReseauSection() {
  // Réglages de CE navigateur (retenus d'une visite à l'autre)
  const [poste, setPoste] = useState(() => lire("sonde.poste", "PC box"));
  const [type, setType] = useState(() => lire("sonde.type", "pc"));
  const [intervalle, setIntervalle] = useState(() => Number(lire("sonde.intervalle", "15")));
  const [enMarche, setEnMarche] = useState(false);
  const [etat, setEtat] = useState("");                       // avancement affiché sous les boutons
  const [occupe, setOccupe] = useState(false);
  // Historique lu sur SAWALI
  const [jours, setJours] = useState(7);
  const [filtrePoste, setFiltrePoste] = useState("");
  const [d, setD] = useState(null);
  const [chargement, setChargement] = useState(false);

  const cycle = useRef(0);          // numéro du cycle (les débits ne sont mesurés qu'un cycle sur quatre)
  const minuteur = useRef(null);
  const verrou = useRef(null);      // verrou d'écran : empêche la mise en veille tant que la sonde tourne
  const enMarcheRef = useRef(false);
  const params = useRef({ poste, type, intervalle });
  params.current = { poste, type, intervalle };
  const occupeRef = useRef(false);  // une seule mesure à la fois, même si la boucle automatique et le bouton se croisent
  const chargerRef = useRef(null);  // dernière version de « charger » (la boucle automatique garde une ancienne copie de `mesurer`)

  // ---------- lecture de l'historique ----------
  const charger = useCallback(async (avecToast) => {
    setChargement(true);
    if (avecToast) toast("Actualisation de la sonde en cours…");
    try {
      const r = await apiClient.get("/sonde-reseau/mesures", { params: { jours, poste: filtrePoste } });
      setD(r.data);
      if (avecToast) toast.success(`${r.data.resume.mesures} mesure(s) relue(s).`);
    } catch (e) {
      setD({ erreur: e?.response?.data?.detail || "Lecture impossible" });
      if (avecToast) toast.error("Actualisation impossible");
    } finally { setChargement(false); }
  }, [jours, filtrePoste]);
  useEffect(() => { charger(false); }, [charger]);
  chargerRef.current = charger;

  // ---------- envoi d'une mesure (arrière-plan ; en cas d'échec réseau elle attend dans une file locale de 50 mesures) ----------
  const envoyer = useCallback(async (mesure) => {
    let file = [];
    try { file = JSON.parse(lire("sonde.file", "[]")); } catch { file = []; }
    file.push(mesure);
    const reste = [];
    for (const m of file.slice(-50)) {
      try { await apiClient.post("/sonde-reseau/mesures", m); }
      catch (e) { if (!e?.response || e.response.status >= 500) reste.push(m); }     // 4xx (trop rapprochée, incohérente) : abandonnée ; coupure réseau : on réessaie
    }
    ecrire("sonde.file", JSON.stringify(reste));
    return reste.length;
  }, []);

  // ---------- un cycle de mesure ----------
  const mesurer = useCallback(async (manuel) => {
    if (occupeRef.current) return;
    occupeRef.current = true;
    setOccupe(true);
    if (manuel) toast("Mesure en cours… (environ 30 secondes, 1 minute avec les débits)");
    try {
      const p = params.current;
      const avecDebit = manuel ? true : doitMesurerDebit(cycle.current, p.intervalle);
      const mesure = await executerCycle({ poste: p.poste, type: p.type, avecDebit, etape: setEtat });
      cycle.current += 1;
      const enAttente = await envoyer(mesure);
      setEtat(`Dernière mesure à ${new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}${enAttente ? ` — ${enAttente} mesure(s) en attente d'envoi (réseau coupé)` : ""}`);
      if (manuel) toast.success(enAttente ? "Mesure faite, envoi en attente (réseau indisponible)." : "Mesure enregistrée.");
      await chargerRef.current?.(false);
    } catch { setEtat("Mesure impossible"); if (manuel) toast.error("Mesure impossible"); }
    finally { occupeRef.current = false; setOccupe(false); }
  }, [envoyer]);

  // ---------- démarrage / arrêt ----------
  const demanderVerrou = useCallback(async () => {
    try { if (navigator.wakeLock) verrou.current = await navigator.wakeLock.request("screen"); } catch { /* refusé : la sonde tourne quand même */ }
  }, []);
  const boucle = useCallback(() => {
    const attendre = params.current.intervalle * 60000;
    minuteur.current = setTimeout(async () => {
      if (!enMarcheRef.current) return;
      await mesurer(false);
      if (enMarcheRef.current) { setEtat((e) => `${e} — prochaine mesure à ${heureProchaine(Date.now(), params.current.intervalle)}`); boucle(); }
    }, attendre);
  }, [mesurer]);
  const demarrer = useCallback(async () => {
    enMarcheRef.current = true; setEnMarche(true); ecrire("sonde.enmarche", "1");
    toast.success(`Sonde démarrée : une mesure toutes les ${params.current.intervalle} minutes. Laissez cette page ouverte.`);
    await demanderVerrou();
    await mesurer(false);
    if (enMarcheRef.current) { setEtat((e) => `${e} — prochaine mesure à ${heureProchaine(Date.now(), params.current.intervalle)}`); boucle(); }
  }, [mesurer, boucle, demanderVerrou]);
  const arreter = useCallback(() => {
    enMarcheRef.current = false; setEnMarche(false); ecrire("sonde.enmarche", "0");
    clearTimeout(minuteur.current);
    try { verrou.current?.release(); } catch { /* déjà libéré */ }
    verrou.current = null;
    setEtat("Sonde arrêtée");
    toast("Sonde arrêtée.");
  }, []);
  // Le navigateur libère le verrou quand l'onglet est masqué : on le redemande au retour sur l'onglet
  useEffect(() => {
    const retour = () => { if (document.visibilityState === "visible" && enMarcheRef.current) demanderVerrou(); };
    document.addEventListener("visibilitychange", retour);
    return () => { document.removeEventListener("visibilitychange", retour); clearTimeout(minuteur.current); enMarcheRef.current = false; };
  }, [demanderVerrou]);

  // ---------- rapport HTML et export CSV ----------
  const rapport = async () => {
    toast("Préparation du rapport en cours…");
    try {
      const r = await apiClient.get("/sonde-reseau/rapport", { params: { jours, poste: filtrePoste }, responseType: "blob" });
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(r.data);
      lien.download = `rapport-sonde-reseau-${new Date().toISOString().slice(0, 10)}.html`;
      document.body.appendChild(lien); lien.click(); lien.remove(); URL.revokeObjectURL(lien.href);
      toast.success("Rapport HTML téléchargé : joignez-le à un e-mail ou ouvrez-le pour l'imprimer en PDF.");
    } catch { toast.error("Rapport impossible"); }
  };
  const exporterCsv = () => {
    const blob = new Blob(["﻿" + enCsv(d?.mesures || [])], { type: "text/csv;charset=utf-8" });
    const lien = document.createElement("a");
    lien.href = URL.createObjectURL(blob); lien.download = `sonde-reseau-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(lien); lien.click(); lien.remove(); URL.revokeObjectURL(lien.href);
    toast.success(`${(d?.mesures || []).length} mesure(s) exportée(s).`);
  };
  const effacer = async () => {
    if (!window.confirm("Effacer TOUTES les mesures de la sonde ? Cette action est définitive.")) return;
    try { await apiClient.delete("/sonde-reseau/mesures"); toast.success("Mesures effacées."); await charger(false); } catch { toast.error("Effacement impossible"); }
  };

  // ---------- tableau triable ----------
  const lignes = [...(d?.mesures || [])].reverse();          // la plus récente d'abord
  const { lignes: triees, tri, basculer } = useTri(lignes, {
    le: (m) => m.le, poste: (m) => m.poste, type: (m) => m.type, essais: (m) => m.essais, perdus: (m) => m.perdus, perte: (m) => m.perte_pct,
    latence: (m) => m.latence_moy_ms, desc: (m) => m.debit_desc_mbps, mont: (m) => m.debit_mont_mbps, video: (m) => m.video_demarrage_ms,
  });
  const r = d?.resume;
  const chrono = (d?.mesures || []);
  const totalEssais = triees.reduce((a, m) => a + (m.essais || 0), 0);
  const totalPerdus = triees.reduce((a, m) => a + (m.perdus || 0), 0);
  const bandeau = { ok: "bg-emerald-50 text-emerald-800 border-emerald-200", attention: "bg-amber-50 text-amber-800 border-amber-200", critique: "bg-red-50 text-red-800 border-red-200", inconnu: "bg-slate-50 text-slate-700 border-slate-200" };
  const bouton = "inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm disabled:opacity-50";

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-sonde-reseau">
      <p className="flex items-start gap-2 text-xs text-slate-600">
        <Wifi className="mt-0.5 h-4 w-4 shrink-0" />
        <span>Laissez cette page <b>ouverte</b> sur le PC branché à la box (ou sur un téléphone) : elle mesure la latence et la perte toutes les {intervalle} minutes, puis une fois par heure les débits (≈ 12 Mo de données)
          et la lecture d'une vidéo, vers Cloudflare. Rien n'est installé et SAWALI n'est pas sollicité. Un navigateur ne peut pas faire de vrai « ping » : la perte est estimée par les requêtes sans réponse en 2 secondes.
          Sur un téléphone en données mobiles, préférez un intervalle de 60 minutes.</span>
      </p>

      {/* Réglages de ce poste : listes déroulantes (valeurs finies) */}
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block text-xs"><span className="font-semibold text-slate-700">Nom de ce poste</span>
          <input value={poste} maxLength={40} disabled={enMarche} onChange={(e) => { setPoste(e.target.value); ecrire("sonde.poste", e.target.value); }}
                 className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-100" data-testid="sonde-poste" /></label>
        <label className="block text-xs"><span className="font-semibold text-slate-700">Type de connexion</span>
          <select value={type} disabled={enMarche} onChange={(e) => { setType(e.target.value); ecrire("sonde.type", e.target.value); }}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-100" data-testid="sonde-type">
            <option value="pc">PC (box / Wi-Fi / câble)</option><option value="mobile">Mobile (données ou partage de connexion)</option></select></label>
        <label className="block text-xs"><span className="font-semibold text-slate-700">Une mesure toutes les</span>
          <select value={intervalle} disabled={enMarche} onChange={(e) => { setIntervalle(Number(e.target.value)); ecrire("sonde.intervalle", e.target.value); }}
                  className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-100" data-testid="sonde-intervalle">
            {INTERVALLES.map((m) => <option key={m} value={m}>{m} minutes</option>)}</select></label>
      </div>

      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        {!enMarche
          ? <button type="button" onClick={demarrer} className={bouton} data-testid="sonde-demarrer"><Play className="h-4 w-4" /> Démarrer la sonde</button>
          : <button type="button" onClick={arreter} className={bouton} data-testid="sonde-arreter"><Square className="h-4 w-4" /> Arrêter la sonde</button>}
        <button type="button" onClick={() => mesurer(true)} disabled={occupe} className={bouton} data-testid="sonde-mesurer"><Activity className="h-4 w-4" /> {occupe ? "Mesure en cours…" : "Mesurer maintenant"}</button>
        <button type="button" onClick={() => charger(true)} disabled={chargement} className={bouton} data-testid="sonde-actualiser"><RefreshCw className="h-4 w-4" /> Actualiser</button>
        <button type="button" onClick={rapport} className={bouton} data-testid="sonde-rapport"><FileDown className="h-4 w-4" /> Rapport HTML à partager</button>
        <button type="button" onClick={exporterCsv} disabled={!(d?.mesures || []).length} className={bouton} data-testid="sonde-csv"><Download className="h-4 w-4" /> Export CSV</button>
        <button type="button" onClick={effacer} className={bouton} data-testid="sonde-effacer"><Eraser className="h-4 w-4" /> Effacer les mesures</button>
      </div>
      {(enMarche || etat) && <p className="text-xs text-slate-600" data-testid="sonde-etat" aria-live="polite">{enMarche && <span className="mr-2 inline-block rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800">En marche</span>}{etat}</p>}

      {/* Période et poste affichés */}
      <div className="flex flex-wrap gap-3 border-t border-slate-100 pt-3">
        <label className="text-xs"><span className="mr-2 font-semibold text-slate-700">Période</span>
          <select value={jours} onChange={(e) => setJours(Number(e.target.value))} className="rounded border border-slate-300 px-2 py-1 text-sm" data-testid="sonde-jours">
            {PERIODES.map((p) => <option key={p.j} value={p.j}>{p.l}</option>)}</select></label>
        <label className="text-xs"><span className="mr-2 font-semibold text-slate-700">Poste</span>
          <select value={filtrePoste} onChange={(e) => setFiltrePoste(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" data-testid="sonde-filtre-poste">
            <option value="">Tous les postes</option>{(d?.postes || []).map((p) => <option key={p} value={p}>{p}</option>)}</select></label>
      </div>

      {d?.erreur && <p className="text-xs text-red-700">{d.erreur}</p>}
      {r && (
        <>
          <div className={`rounded-lg border px-3 py-2 text-sm font-semibold ${bandeau[r.niveau] || bandeau.inconnu}`} data-testid="sonde-verdict">{r.verdict}</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Carte titre="Perte de paquets" valeur={r.perte_pct == null ? "—" : `${num(r.perte_pct)} %`} detail={`${r.perdus} perdu(s) sur ${r.essais}`} niveau={niveauPerte(r.perte_pct)} />
            <Carte titre="Latence moyenne" valeur={r.latence_moy_ms == null ? "—" : `${num(r.latence_moy_ms)} ms`} detail={`95 % sous ${num(r.latence_p95_ms)} ms`} />
            <Carte titre="Débit descendant" valeur={r.debit_desc_moy == null ? "—" : `${num(r.debit_desc_moy)} Mb/s`} detail={`minimum ${num(r.debit_desc_min)} Mb/s`} niveau={niveauDebit(r.debit_desc_moy)} />
            <Carte titre="Débit montant" valeur={r.debit_mont_moy == null ? "—" : `${num(r.debit_mont_moy)} Mb/s`} />
            <Carte titre="Connexions HTTPS" valeur={r.https_pct == null ? "—" : `${num(r.https_pct)} %`} detail={`${r.https_ok}/${r.https_total} réussies`} niveau={r.https_pct != null && r.https_pct < 95 ? "attention" : "ok"} />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Courbe titre="Latence (ms)" valeurs={chrono.map((m) => m.latence_moy_ms)} couleur="#2563eb" unite="ms" />
            <Courbe titre="Perte de paquets (%)" valeurs={chrono.map((m) => m.perte_pct)} couleur="#dc2626" unite="%" repere={SEUIL_PERTE_ATTENTION} />
            <Courbe titre="Débit descendant (Mb/s)" valeurs={chrono.map((m) => m.debit_desc_mbps)} couleur="#059669" unite="Mb/s" />
          </div>
        </>)}

      {/* Tableau : colonnes triables, nombres à droite, ligne de totaux collée dessous (plus de 30 lignes : le défilement est automatique) */}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs" data-testid="table-sonde">
          <thead className="sticky top-0 bg-white">
            <tr className="text-left text-slate-600">
              <ThTri cle="le" tri={tri} onTri={basculer}>Date</ThTri>
              <ThTri cle="poste" tri={tri} onTri={basculer}>Poste</ThTri>
              <ThTri cle="type" tri={tri} onTri={basculer}>Type</ThTri>
              <ThTri cle="essais" tri={tri} onTri={basculer} droite>Essais</ThTri>
              <ThTri cle="perdus" tri={tri} onTri={basculer} droite>Perdus</ThTri>
              <ThTri cle="perte" tri={tri} onTri={basculer} droite>Perte (%)</ThTri>
              <ThTri cle="latence" tri={tri} onTri={basculer} droite>Latence (ms)</ThTri>
              <ThTri cle="desc" tri={tri} onTri={basculer} droite>Débit ↓ (Mb/s)</ThTri>
              <ThTri cle="mont" tri={tri} onTri={basculer} droite>Débit ↑ (Mb/s)</ThTri>
              <ThTri cle="video" tri={tri} onTri={basculer} droite>Vidéo : démarrage (ms)</ThTri>
            </tr>
          </thead>
          <tbody>
            {triees.map((m) => (
              <tr key={`${m.le}-${m.poste}`} className="border-t">
                <td className="p-2 whitespace-nowrap">{quand(m.le)}</td>
                <td className="p-2">{m.poste}</td>
                <td className="p-2">{m.type === "mobile" ? "Mobile" : "PC"}</td>
                <td className="p-2 text-right tabular-nums">{m.essais}</td>
                <td className={`p-2 text-right tabular-nums ${m.perdus ? "font-semibold text-red-700" : ""}`}>{m.perdus}</td>
                <td className={`p-2 text-right tabular-nums font-semibold ${COULEUR_NIVEAU[niveauPerte(pctPerte(m))]}`}>{num(m.perte_pct)}</td>
                <td className="p-2 text-right tabular-nums">{num(m.latence_moy_ms)}</td>
                <td className={`p-2 text-right tabular-nums ${COULEUR_NIVEAU[niveauDebit(m.debit_desc_mbps)]}`}>{num(m.debit_desc_mbps)}</td>
                <td className="p-2 text-right tabular-nums">{num(m.debit_mont_mbps)}</td>
                <td className="p-2 text-right tabular-nums">{num(m.video_demarrage_ms, 0)}</td>
              </tr>))}
            {triees.length === 0 && <tr><td colSpan={10} className="p-2 text-slate-500">Aucune mesure sur cette période : cliquez sur « Mesurer maintenant » ou « Démarrer la sonde ».</td></tr>}
          </tbody>
          {triees.length > 0 && (
            <tfoot className="sticky bottom-0 bg-slate-50 font-semibold">
              <tr className="border-t-2 border-slate-300" data-testid="sonde-totaux">
                <td className="p-2" colSpan={3}>Totaux · {triees.length} mesure(s)</td>
                <td className="p-2 text-right tabular-nums">{totalEssais}</td>
                <td className="p-2 text-right tabular-nums">{totalPerdus}</td>
                <td className="p-2" colSpan={5} />
              </tr>
            </tfoot>)}
        </table>
      </div>
    </div>
  );
}
