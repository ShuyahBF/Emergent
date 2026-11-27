// ============================================================================
// Lot 463 — Paramètres → « ⏱️ Performance du serveur — mémoire et appels lents ».
// Même principe que la jauge « Base Atlas » : une jauge circulaire (mémoire utilisée / limite, repère du seuil d'alerte), « Mesurer », mesure automatique toutes
// les heures, alerte WhatsApp au-delà du seuil (une fois par jour). En dessous : les APPELS LES PLUS LENTS (règle 7 « mesurer d'abord ») : par route, nombre d'appels,
// durée moyenne, 5 derniers, dernier, maximum, appels de plus d'1 s, erreurs 5xx. Colonnes triables (règle 19), nombres à droite (règle 3).
// Backend : GET /api/admin/performance/memoire, GET /api/admin/performance/appels, POST /api/admin/performance/appels/reinitialiser (administrateur seul).
// Réglages (limite en Mo, seuil en %) : champs `perf_memoire_limite_mo` / `perf_memoire_seuil_pct` des réglages généraux (enregistrés avec la page).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Download, Eraser, FileDown, RefreshCw, Gauge as IcoGauge } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { appelsEnCsv, appelsEnJson } from "@/lib/exportAppelsLents";   // lot 470 : export complet du tableau
import { COULEURS as COULEURS_ATLAS, Jauge } from "@/pages/admin/sections/QuotaAtlasSection";

// Même couleurs que la jauge des collections, libellés propres à la mémoire (vert < 70 %, orange ≥ 70 %, rouge ≥ 90 %)
const COULEURS = {
  ok: { ...COULEURS_ATLAS.ok, libelle: "Marge confortable" },
  attention: { ...COULEURS_ATLAS.attention, libelle: "Plus de 70 % utilisés" },
  plein: { ...COULEURS_ATLAS.plein, libelle: "Il reste 10 % ou moins : le serveur va ralentir" },
};
const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
const nombre = (n) => Number(n || 0).toLocaleString("fr-FR");

// Petite courbe des échantillons horaires de mémoire (SVG) : une ligne bleue, la limite en haut, le seuil en pointillé orange
function Courbe({ historique, limite, seuilMo }) {
  const pts = (historique || []).filter((h) => h.utilise_mo != null);
  if (pts.length < 2) return <p className="text-xs text-slate-500">La courbe apparaît après 2 relevés horaires.</p>;
  const L = 320, H = 70, x = (i) => (i * L) / (pts.length - 1), y = (v) => H - Math.min(1, v / limite) * H;
  return (
    <svg viewBox={`0 0 ${L} ${H + 4}`} className="w-full max-w-md" role="img" aria-label={`Mémoire utilisée sur ${pts.length} relevés horaires`} data-testid="courbe-memoire">
      <line x1="0" x2={L} y1={y(seuilMo)} y2={y(seuilMo)} stroke="#d97706" strokeDasharray="4 3" strokeWidth="1" />
      <polyline fill="none" stroke="#2563eb" strokeWidth="2" points={pts.map((p, i) => `${x(i)},${y(p.utilise_mo)}`).join(" ")} />
    </svg>
  );
}

function Memoire({ reglages, maj }) {
  const [m, setM] = useState(null);
  const [enCours, setEnCours] = useState(false);
  const mesurer = useCallback(async (avecToast) => {
    setEnCours(true);
    if (avecToast) toast("Mesure de la mémoire en cours…");
    try {
      const r = await apiClient.get("/admin/performance/memoire");
      setM(r.data);
      if (avecToast) toast.success(r.data.lisible ? `Mémoire : ${r.data.utilise_mo} Mo sur ${r.data.limite_mo} Mo (${r.data.pourcentage} %).` : "Mémoire illisible sur ce serveur.");
    } catch (e) { setM({ erreur: e?.response?.data?.detail || "Mesure indisponible" }); if (avecToast) toast.error("Mesure impossible"); }
    finally { setEnCours(false); }
  }, []);
  useEffect(() => { mesurer(false); }, [mesurer]);
  return (
    <div className="space-y-3" data-testid="bloc-memoire">
      <h4 className="text-sm font-semibold text-slate-800">Mémoire du serveur</h4>
      {!m && <p className="text-sm text-slate-500">Patientez…</p>}
      {m?.erreur && <p className="text-xs text-red-700">{m.erreur}</p>}
      {m && m.lisible === false && <p className="text-xs text-slate-600">La mémoire n'est pas lisible sur ce serveur (poste de développement).</p>}
      {m?.lisible && (() => {
        const c = COULEURS[m.niveau] || COULEURS.ok;
        return (
          <div className="flex flex-col sm:flex-row items-center gap-5">
            <Jauge total={Math.round(m.utilise_mo)} limite={Math.round(m.limite_mo)} seuil={Math.round(m.seuil_mo)} niveau={m.niveau} unite="Mo" libelle={`${m.utilise_mo} Mo sur ${m.limite_mo} Mo`} />
            <div className="flex-1 space-y-2 w-full">
              <div className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${c.fond} ${c.texte}`} data-testid="niveau-memoire">{c.libelle} · {m.pourcentage} %</div>
              <p className="text-sm text-slate-700">
                <b>{m.utilise_mo} Mo</b> utilisés sur <b>{m.limite_mo} Mo</b> (limite {m.origine_limite === "réglage" ? "réglée ci-dessous" : m.origine_limite === "conteneur" ? "du serveur Render" : "par défaut"}) — encore <b>{m.restant_mo} Mo</b>.
                {m.processus_mo != null && <> Le programme SAWALI seul en occupe {m.processus_mo} Mo.</>} Alerte WhatsApp au-delà de <b>{m.seuil_pct} %</b> ({m.seuil_mo} Mo).
              </p>
              <Courbe historique={m.historique} limite={m.limite_mo} seuilMo={m.seuil_mo} />
              <p className="text-[11px] text-slate-500">
                Mesuré le {quand(m.le)} · mesure automatique toutes les heures (courbe : les 72 derniers relevés).
                <button type="button" onClick={() => mesurer(true)} disabled={enCours} className="ml-2 inline-flex items-center gap-1 rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-50">
                  <RefreshCw className="h-3 w-3" /> {enCours ? "Patientez…" : "Mesurer"}</button>
              </p>
            </div>
          </div>);
      })()}
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="block text-xs"><span className="font-semibold text-slate-700">Limite de mémoire en Mo (vide = celle du serveur Render)</span>
          <input type="number" min="1" value={reglages.perf_memoire_limite_mo ?? ""} placeholder="automatique"
            onChange={(e) => maj("perf_memoire_limite_mo", e.target.value === "" ? null : Number(e.target.value))} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="memoire-limite" /></label>
        <label className="block text-xs"><span className="font-semibold text-slate-700">Seuil d'alerte en % (WhatsApp au super-admin, une fois par jour)</span>
          <input type="number" min="1" max="100" value={reglages.perf_memoire_seuil_pct ?? 85}
            onChange={(e) => maj("perf_memoire_seuil_pct", e.target.value === "" ? null : Number(e.target.value))} className="mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="memoire-seuil" /></label>
      </div>
    </div>
  );
}

function AppelsLents() {
  const [d, setD] = useState(null);
  const [enCours, setEnCours] = useState(false);
  const charger = useCallback(async (avecToast) => {
    setEnCours(true);
    if (avecToast) toast("Lecture des appels en cours…");
    try {
      const r = await apiClient.get("/admin/performance/appels", { params: { limite: 60 } });
      setD(r.data);
      if (avecToast) toast.success(`${r.data.routes} route(s) mesurée(s), ${nombre(r.data.appels)} appel(s), ${nombre(r.data.lents)} de plus d'1 s.`);
    } catch (e) { setD({ erreur: e?.response?.data?.detail || "Lecture impossible" }); if (avecToast) toast.error("Lecture impossible"); }
    finally { setEnCours(false); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);
  const remettre = async () => {
    if (!window.confirm("Remettre les compteurs à zéro ? Les mesures reprendront à partir de maintenant.")) return;
    toast("Remise à zéro en cours…");
    try { await apiClient.post("/admin/performance/appels/reinitialiser"); toast.success("Compteurs remis à zéro."); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Remise à zéro impossible"); }
  };
  // Lot 470 — EXPORT COMPLET du tableau (toutes les routes, pas seulement les 60 affichées) dans un format qu'une machine lit sans ambiguïté :
  // JSON (contexte + description des champs + mémoire) ou CSV (Excel). Toast « en cours » puis toast de résultat (règle 17).
  const exporter = async (format) => {
    toast("Préparation de l'export en cours…");
    try {
      const [a, m] = await Promise.all([
        apiClient.get("/admin/performance/appels", { params: { limite: 500 } }),
        apiClient.get("/admin/performance/memoire").catch(() => ({ data: null })),     // la mémoire est un plus : son échec n'empêche pas l'export
      ]);
      const maintenant = new Date();
      const json = format === "json";
      const contenu = json ? appelsEnJson(a.data, m.data, maintenant.toISOString()) : "\ufeff" + appelsEnCsv(a.data);
      const blob = new Blob([contenu], { type: json ? "application/json;charset=utf-8" : "text/csv;charset=utf-8" });
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(blob);
      lien.download = `appels-lents-${maintenant.toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-")}.${json ? "json" : "csv"}`;
      document.body.appendChild(lien); lien.click(); lien.remove(); URL.revokeObjectURL(lien.href);
      toast.success(`${(a.data.classement || []).length} route(s) exportée(s) en ${json ? "JSON" : "CSV"}.`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Export impossible"); }
  };
  const lignes = (d?.classement || []).map((l) => ({ ...l, cle: `${l.methode} ${l.route}` }));
  const { lignes: triees, tri, basculer } = useTri(lignes, {
    route: (l) => l.route, appels: (l) => l.appels, moyenne: (l) => l.moyenne_ms, ops: (l) => l.ops_moy, base: (l) => l.base_ms_moy, dernier: (l) => l.dernier_ms, maximum: (l) => l.maximum_ms, lents: (l) => l.lents, erreurs: (l) => l.erreurs,
  });
  const objectif = d?.objectif_ms || 1000;
  return (
    <div className="space-y-2 border-t border-slate-100 pt-4" data-testid="bloc-appels-lents">
      <h4 className="text-sm font-semibold text-slate-800">Appels les plus lents</h4>
      {d?.erreur && <p className="text-xs text-red-700">{d.erreur}</p>}
      {d && !d.erreur && (
        <p className="text-xs text-slate-600">
          {d.source === "releve" ? <span className="text-amber-700">Le serveur vient de redémarrer : dernier relevé horaire du {quand(d.releve_le)} (mesure en direct dès les premiers appels). </span> : null}
          {d.source === "vide" ? "Aucun appel mesuré pour le moment. " : null}
          Depuis {quand(d.depuis)} : <b>{nombre(d.appels)}</b> appels sur <b>{d.routes}</b> routes, dont <b className="text-orange-700">{nombre(d.lents)}</b> de plus d'{objectif / 1000} s et <b className="text-red-700">{nombre(d.erreurs)}</b> en erreur serveur.
          Objectif : toute route d'affichage répond en moins d'{objectif / 1000} s ; c'est la route la plus lente qu'on corrige, jamais au hasard. « Requêtes base / appel » : chaque requête à MongoDB coûte environ 10 ms d'aller-retour (serveur à Francfort, Atlas à Paris) : une route à 25 requêtes ou plus (en rouge) est à corriger en priorité ; le temps base est cumulé (il peut dépasser la durée de l'appel si les requêtes se chevauchent).
        </p>)}
      {d?.boucle && d.boucle.mesures > 0 && (
        <p className={`text-xs ${d.boucle.retard_max_ms >= 500 ? "text-red-700 font-semibold" : d.boucle.blocages_100ms > 0 ? "text-orange-700" : "text-slate-600"}`} data-testid="reactivite-serveur">
          Réactivité du serveur : retard moyen <b>{nombre(d.boucle.retard_moy_ms)} ms</b>, maximum <b>{nombre(d.boucle.retard_max_ms)} ms</b>, <b>{nombre(d.boucle.blocages_100ms)}</b> blocage(s) de plus de 100 ms
          sur {nombre(d.boucle.mesures)} relevés. Près de zéro : tout va bien ; plusieurs centaines de ms : un calcul bloque le serveur et ralentit TOUTES les routes en même temps.</p>)}
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <button type="button" onClick={() => charger(true)} disabled={enCours} data-testid="appels-actualiser" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm disabled:opacity-50"><RefreshCw className="w-4 h-4" /> Actualiser</button>
        <button type="button" onClick={remettre} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Eraser className="w-4 h-4" /> Remettre à zéro</button>
        <button type="button" onClick={() => exporter("json")} data-testid="appels-export-json" title="Tout le tableau, avec la description de chaque champ et la mémoire du serveur : le format le plus facile à analyser" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><FileDown className="w-4 h-4" /> Exporter tout (JSON)</button>
        <button type="button" onClick={() => exporter("csv")} data-testid="appels-export-csv" title="Tout le tableau pour Excel" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Download className="w-4 h-4" /> Exporter tout (CSV)</button>
      </div>
      <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
        <table className="min-w-full text-xs" data-testid="table-appels-lents">
          <thead className="sticky top-0 bg-white">
            <tr className="text-left text-slate-600">
              <ThTri cle="route" tri={tri} onTri={basculer}>Route</ThTri>
              <ThTri cle="appels" tri={tri} onTri={basculer} droite>Appels</ThTri>
              <ThTri cle="moyenne" tri={tri} onTri={basculer} droite>Moyenne (ms)</ThTri>
              <ThTri cle="ops" tri={tri} onTri={basculer} droite>Requêtes base / appel</ThTri>
              <ThTri cle="base" tri={tri} onTri={basculer} droite>Temps base (ms)</ThTri>
              <th className="p-2 text-right">5 derniers (ms)</th>
              <ThTri cle="dernier" tri={tri} onTri={basculer} droite>Dernier (ms)</ThTri>
              <ThTri cle="maximum" tri={tri} onTri={basculer} droite>Maximum (ms)</ThTri>
              <ThTri cle="lents" tri={tri} onTri={basculer} droite>&gt; 1 s</ThTri>
              <ThTri cle="erreurs" tri={tri} onTri={basculer} droite>Erreurs 5xx</ThTri>
            </tr>
          </thead>
          <tbody>
            {triees.map((l) => (
              <tr key={l.cle} className="border-t align-top">
                <td className="p-2 font-mono break-all"><span className="mr-1 font-semibold text-blue-700">{l.methode}</span>{l.route}</td>
                <td className="p-2 text-right tabular-nums">{nombre(l.appels)}</td>
                <td className={`p-2 text-right tabular-nums font-semibold ${l.moyenne_ms >= objectif ? "text-red-700" : l.moyenne_ms >= objectif / 2 ? "text-orange-700" : "text-emerald-700"}`}>{nombre(l.moyenne_ms)}</td>
                {/* Lot 472 : nombre de requêtes à MongoDB par appel (chacune coûte ~10 ms d'aller-retour Francfort ↔ Paris) et temps cumulé passé dans la base */}
                <td className={`p-2 text-right tabular-nums font-semibold ${l.ops_moy >= 25 ? "text-red-700" : l.ops_moy >= 10 ? "text-orange-700" : "text-slate-700"}`} data-testid="cellule-ops">{nombre(l.ops_moy)}</td>
                <td className="p-2 text-right tabular-nums text-slate-700">{nombre(l.base_ms_moy)}</td>
                <td className="p-2 text-right tabular-nums text-slate-600">{(l.derniers_ms || []).join(" · ")}</td>
                <td className="p-2 text-right tabular-nums">{nombre(l.dernier_ms)}</td>
                <td className="p-2 text-right tabular-nums">{nombre(l.maximum_ms)}</td>
                <td className="p-2 text-right tabular-nums">{l.lents ? <span className="font-semibold text-orange-700">{nombre(l.lents)}</span> : "0"}</td>
                <td className="p-2 text-right tabular-nums">{l.erreurs ? <span className="font-semibold text-red-700">{nombre(l.erreurs)}</span> : "0"}</td>
              </tr>))}
            {triees.length === 0 && <tr><td colSpan={10} className="p-2 text-slate-500">Aucune route mesurée.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function PerformanceServeurSection({ reglages, maj }) {
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-performance-serveur">
      <p className="flex items-center gap-2 text-xs text-slate-600"><IcoGauge className="h-4 w-4" /> Mesure de la mémoire du serveur et de la durée de chaque appel. Les compteurs d'appels sont en mémoire : ils repartent de zéro à chaque redémarrage du serveur (le relevé horaire garde le dernier classement).</p>
      <Memoire reglages={reglages} maj={maj} />
      <AppelsLents />
    </div>
  );
}
