// ============================================================================
// Lot 470 — Paramètres → « 📶 Sonde réseau — débit et stabilité de la connexion ».
// Cette page, laissée OUVERTE dans le navigateur d'un PC branché à la box (ou d'un téléphone), mesure toutes les 15 minutes la latence, la perte de paquets, les
// connexions HTTPS réelles, et une fois par heure les débits descendant / montant et la lecture d'un flux vidéo, VERS CLOUDFLARE (aucune charge pour SAWALI).
// Chaque mesure est envoyée à SAWALI en arrière-plan (jamais bloquant) ; en dessous : synthèse colorée, courbes, tableau triable, RAPPORT HTML à partager
// (par exemple avec l'opérateur) et export CSV.
// Backend : POST/GET/DELETE /api/sonde-reseau/mesures, GET /api/sonde-reseau/rapport (administrateur seul). Moteur : lib/sondeReseau.js.
// ============================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Activity, BarChart3, Gauge, CloudUpload, Download, Eraser, Eye, EyeOff, FileDown, KeyRound, Play, RefreshCw, SlidersHorizontal, Square, Table2, TriangleAlert, Wifi } from "lucide-react";
import { toast } from "sonner";
import { API, apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { executerCycle } from "@/lib/sondeReseau";
import { messageAlerte, viderFile } from "@/lib/sondeEnvoi";
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

// Boutons d'action = PICTOGRAMMES (règle du propriétaire, 27/11/2026) : ronds, colorés, avec info-bulle et libellé d'accessibilité (zone tactile de 44 px)
const pico = "inline-flex h-11 w-11 items-center justify-center rounded-full border-2 disabled:opacity-50";
const COULEURS = { vert: "border-emerald-500 text-emerald-700 hover:bg-emerald-50", rouge: "border-red-400 text-red-700 hover:bg-red-50", bleu: "border-sky-500 text-sky-700 hover:bg-sky-50",
  orange: "border-amber-500 text-amber-700 hover:bg-amber-50", violet: "border-violet-400 text-violet-700 hover:bg-violet-50", gris: "border-slate-400 text-slate-700 hover:bg-slate-50" };
const Pico = ({ onClick, disabled, titre, couleur, id, children }) => (
  <button type="button" onClick={onClick} disabled={disabled} title={titre} aria-label={titre} data-testid={id} className={`${pico} ${COULEURS[couleur]}`}>{children}</button>);

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
  // Lot 471 — clé de la sonde : l'envoi ne dépend plus de la session de l'administrateur (qui expire) ; retenue dans CE navigateur seulement
  const [cle, setCle] = useState(() => lire("sonde.cle", ""));
  const [cleVisible, setCleVisible] = useState(false);          // masquée par défaut (règle 22 : œil sur toute saisie secrète)
  const [cleServeur, setCleServeur] = useState(null);           // la clé est-elle configurée sur le serveur ? (jamais sa valeur)
  const [alerteEnvoi, setAlerteEnvoi] = useState("");           // bandeau rouge : mesures en attente d'envoi
  const cleRef = useRef(cle);
  cleRef.current = cle;

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
  // La clé est-elle configurée sur le serveur ? (lecture administrateur ; sans effet sur les mesures)
  useEffect(() => { apiClient.get("/sonde-reseau/cle-etat").then((r) => setCleServeur(!!r.data?.configuree)).catch(() => setCleServeur(null)); }, []);

  // ---------- envoi d'une mesure (arrière-plan ; en cas d'échec réseau elle attend dans une file locale de 50 mesures) ----------
  // Avec la clé de la sonde : POST /sonde-reseau/envoi (aucune session nécessaire). Sans clé : route administrateur (session). Les réponses sont classées par
  // lib/sondeEnvoi.js : une session expirée ou une clé fausse GARDE les mesures et l'écran le dit (plus aucune mesure n'est perdue en silence).
  const envoyer = useCallback(async (mesure) => {
    let file = [];
    try { file = JSON.parse(lire("sonde.file", "[]")); } catch { file = []; }
    file.push(mesure);
    const avecCle = !!cleRef.current.trim();
    const envoyeur = async (m) => {
      if (avecCle) {
        const r = await fetch(`${API}/sonde-reseau/envoi`, { method: "POST", headers: { "Content-Type": "application/json", "X-Cle-Sonde": cleRef.current.trim() }, body: JSON.stringify(m) });
        return { status: r.status };
      }
      try { await apiClient.post("/sonde-reseau/mesures", m); return { status: 200 }; }
      catch (e) { return { status: e?.response?.status || 0 }; }
    };
    const { reste, alerte } = await viderFile(file, envoyeur);
    ecrire("sonde.file", JSON.stringify(reste));
    setAlerteEnvoi(messageAlerte(alerte, reste.length, avecCle));
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
  const onglet = "rounded-md px-3 py-1.5 text-sm font-semibold data-[state=active]:bg-sky-700 data-[state=active]:text-white";

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-sonde-reseau">
      {/* Barre d'actions toujours visible : démarrer / arrêter, mesurer, actualiser (pictogrammes) + état */}
      <div className="flex flex-wrap items-center gap-2 boutons-distincts" data-testid="sonde-actions">
        {!enMarche
          ? <Pico onClick={demarrer} titre="Démarrer la sonde" couleur="vert" id="sonde-demarrer"><Play className="h-5 w-5" /></Pico>
          : <Pico onClick={arreter} titre="Arrêter la sonde" couleur="rouge" id="sonde-arreter"><Square className="h-5 w-5" /></Pico>}
        <Pico onClick={() => mesurer(true)} disabled={occupe} titre={occupe ? "Mesure en cours…" : "Mesurer maintenant"} couleur="bleu" id="sonde-mesurer"><Activity className={`h-5 w-5 ${occupe ? "animate-pulse" : ""}`} /></Pico>
        <Pico onClick={() => charger(true)} disabled={chargement} titre="Actualiser" couleur="violet" id="sonde-actualiser"><RefreshCw className={`h-5 w-5 ${chargement ? "animate-spin" : ""}`} /></Pico>
        {(enMarche || etat) && <p className="text-xs text-slate-600" data-testid="sonde-etat" aria-live="polite">{enMarche && <span className="mr-2 inline-block rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-800">En marche</span>}{etat}</p>}
      </div>
      {alerteEnvoi && (
        <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-800" data-testid="sonde-alerte-envoi">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" /> {alerteEnvoi}</div>)}


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

      <Tabs defaultValue={lire("sonde.onglet", "graphiques")} onValueChange={(v) => ecrire("sonde.onglet", v)} data-testid="sonde-onglets">
        <TabsList className="h-auto flex-wrap gap-1 bg-slate-100 p-1">
          <TabsTrigger value="graphiques" className={onglet} data-testid="onglet-graphiques"><BarChart3 className="mr-1 h-4 w-4" /> Graphiques</TabsTrigger>
          <TabsTrigger value="reglages" className={onglet} data-testid="onglet-reglages"><SlidersHorizontal className="mr-1 h-4 w-4" /> Réglages</TabsTrigger>
          <TabsTrigger value="mesures" className={onglet} data-testid="onglet-mesures"><Gauge className="mr-1 h-4 w-4" /> Mesures</TabsTrigger>
          <TabsTrigger value="tableau" className={onglet} data-testid="onglet-tableau"><Table2 className="mr-1 h-4 w-4" /> Tableau</TabsTrigger>
          <TabsTrigger value="envois" className={onglet} data-testid="onglet-envois"><CloudUpload className="mr-1 h-4 w-4" /> Sauvegardes Et Envois</TabsTrigger>
        </TabsList>

        {/* Onglet 1 : courbes */}
        <TabsContent value="graphiques" className="space-y-4">
      {r && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Courbe titre="Latence (ms)" valeurs={chrono.map((m) => m.latence_moy_ms)} couleur="#2563eb" unite="ms" />
            <Courbe titre="Perte de paquets (%)" valeurs={chrono.map((m) => m.perte_pct)} couleur="#dc2626" unite="%" repere={SEUIL_PERTE_ATTENTION} />
            <Courbe titre="Débit descendant (Mb/s)" valeurs={chrono.map((m) => m.debit_desc_mbps)} couleur="#059669" unite="Mb/s" />
          </div>
        </>)}

          {!r && <p className="text-sm text-slate-500">Aucune courbe pour l'instant : lancez une mesure (pictogramme bleu) ou démarrez la sonde.</p>}
        </TabsContent>

        {/* Onglet 2 : réglages des mesures, de la surveillance et des tests */}
        <TabsContent value="reglages" className="space-y-4">
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

          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <span className="font-semibold text-slate-700">Surveillance et tests :</span>
            {!enMarche
              ? <Pico onClick={demarrer} titre="Démarrer la sonde" couleur="vert" id="sonde-demarrer-reglages"><Play className="h-5 w-5" /></Pico>
              : <Pico onClick={arreter} titre="Arrêter la sonde" couleur="rouge" id="sonde-arreter-reglages"><Square className="h-5 w-5" /></Pico>}
            <Pico onClick={() => mesurer(true)} disabled={occupe} titre="Lancer un test maintenant" couleur="bleu" id="sonde-test"><Activity className="h-5 w-5" /></Pico>
            <span>{enMarche ? "La sonde tourne : arrêtez-la pour modifier le poste, le type ou l'intervalle." : "Réglez le poste, le type et l'intervalle, puis démarrez la sonde."}</span>
          </div>
        </TabsContent>

        {/* Onglet 3 : synthèse des mesures (verdict et cartes colorées) */}
        <TabsContent value="mesures" className="space-y-4">
          {r ? (
            <>
          <div className={`rounded-lg border px-3 py-2 text-sm font-semibold ${bandeau[r.niveau] || bandeau.inconnu}`} data-testid="sonde-verdict">{r.verdict}</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Carte titre="Perte de paquets" valeur={r.perte_pct == null ? "—" : `${num(r.perte_pct)} %`} detail={`${r.perdus} perdu(s) sur ${r.essais}`} niveau={niveauPerte(r.perte_pct)} />
            <Carte titre="Latence moyenne" valeur={r.latence_moy_ms == null ? "—" : `${num(r.latence_moy_ms)} ms`} detail={`95 % sous ${num(r.latence_p95_ms)} ms`} />
            <Carte titre="Débit descendant" valeur={r.debit_desc_moy == null ? "—" : `${num(r.debit_desc_moy)} Mb/s`} detail={`minimum ${num(r.debit_desc_min)} Mb/s`} niveau={niveauDebit(r.debit_desc_moy)} />
            <Carte titre="Débit montant" valeur={r.debit_mont_moy == null ? "—" : `${num(r.debit_mont_moy)} Mb/s`} />
            <Carte titre="Connexions HTTPS" valeur={r.https_pct == null ? "—" : `${num(r.https_pct)} %`} detail={`${r.https_ok}/${r.https_total} réussies`} niveau={r.https_pct != null && r.https_pct < 95 ? "attention" : "ok"} />
          </div>
            </>) : <p className="text-sm text-slate-500">Aucune mesure pour l'instant : lancez une mesure (pictogramme bleu) ou démarrez la sonde.</p>}
        </TabsContent>

        {/* Onglet 4 : tableau des mesures (colonnes triables, totaux) */}
        <TabsContent value="tableau" className="space-y-4">
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
        </TabsContent>

        {/* Onglet 5 : tout ce qui est sauvegardé, exporté ou envoyé à SAWALI */}
        <TabsContent value="envois" className="space-y-4">
      {/* Lot 471 — clé de la sonde (œil afficher / masquer) et état sur le serveur */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-2" data-testid="sonde-cle-bloc">
        <label className="block text-xs"><span className="flex items-center gap-1 font-semibold text-slate-700"><KeyRound className="h-3.5 w-3.5" /> Clé de la sonde (pour un envoi sans session)</span>
          <span className="mt-1 flex items-center gap-2">
            <input type={cleVisible ? "text" : "password"} value={cle} autoComplete="off" placeholder="Collez ici la valeur de SONDE_RESEAU_CLE" data-testid="sonde-cle"
                   onChange={(e) => { setCle(e.target.value); ecrire("sonde.cle", e.target.value); }}
                   className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
            <button type="button" onClick={() => setCleVisible((v) => !v)} aria-label={cleVisible ? "Masquer la saisie" : "Afficher la saisie"} title={cleVisible ? "Masquer la saisie" : "Afficher la saisie"}
                    className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded border border-slate-300 bg-white" data-testid="sonde-cle-oeil">
              {cleVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>
          </span></label>
        <p className="text-[11px] text-slate-600">
          {cleServeur === true && <span className="font-semibold text-emerald-700">Clé configurée sur le serveur. </span>}
          {cleServeur === false && <span className="font-semibold text-orange-700">Clé non configurée sur le serveur : dans Render → sawali-backend → Environment, ajoutez la variable SONDE_RESEAU_CLE (une longue valeur de votre choix), puis saisissez la même ici. </span>}
          Avec la clé, la page continue d'envoyer ses mesures même après l'expiration de votre session (12 h ou inactivité) ; elle reste dans ce navigateur et n'est jamais affichée par SAWALI.</p>
      </div>
          <div className="flex flex-wrap items-center gap-2 boutons-distincts">
            <Pico onClick={rapport} titre="Rapport HTML à partager" couleur="orange" id="sonde-rapport"><FileDown className="h-5 w-5" /></Pico>
            <Pico onClick={exporterCsv} disabled={!(d?.mesures || []).length} titre="Export CSV" couleur="vert" id="sonde-csv"><Download className="h-5 w-5" /></Pico>
            <Pico onClick={effacer} titre="Effacer les mesures" couleur="rouge" id="sonde-effacer"><Eraser className="h-5 w-5" /></Pico>
            <span className="text-xs text-slate-500">Rapport HTML à partager · Export CSV · Effacer les mesures</span>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
