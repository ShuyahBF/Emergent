// ============================================================================
// VolumetrieHfsqlSection.jsx — Lot 482 : Paramètres → « 📊 Volumétrie des tables HFSQL — cache Atlas ».
// But : dimensionner un cache MongoDB Atlas d'une semaine pour des tables d'Aizenta, Biolog et e-Kol. On choisit un CLIENT (en ligne), une PLATEFORME, une durée en jours et les TABLES
// (liste déroulante à choix multiples : 803 tables Biolog, 549 Aizenta, 89 e-Kol) ; « Compter » demande à la machine du client, table par table, deux comptages en LECTURE SEULE
// (total et N derniers jours). Le tableau donne les lignes, la taille estimée du cache (lignes des N jours × taille d'un document Atlas) et leurs totaux ; export CSV.
// Backend : GET /api/admin/volumetrie/plateformes, /tables ; POST /api/admin/volumetrie/compter (administrateur seul).
// ============================================================================
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileSpreadsheet, Play, RefreshCw, Square } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import ListeMultiChoix from "@/components/ListeMultiChoix";

const nombre = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("fr-FR"));
const octets = (n) => {
  if (n === null || n === undefined) return "—";
  for (const [u, s] of [["Go", 2 ** 30], ["Mo", 2 ** 20], ["Ko", 2 ** 10]]) if (n >= s) return `${(n / s).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} ${u}`;
  return `${n} o`;
};
// Tables proposées au départ (les plus utiles par Loois) : on peut en cocher d'autres dans la liste
const PAR_DEFAUT = { biolog: ["VenteClinique", "A_Acheté", "Prestations", "Clinique", "ProduitClinique", "MédecinT", "UtilisateurBlg"], aizenta: [], ekol: [] };

export default function VolumetrieHfsqlSection() {
  const [plateformes, setPlateformes] = useState([]);
  const [clients, setClients] = useState([]);
  const [client, setClient] = useState("");
  const [plateforme, setPlateforme] = useState("biolog");
  const [jours, setJours] = useState(7);
  const [tables, setTables] = useState([]);
  const [choisies, setChoisies] = useState([]);
  const [lignes, setLignes] = useState([]);
  const [enCours, setEnCours] = useState(false);
  const arret = useRef(false);

  const charger = useCallback(async (avecToast) => {
    if (avecToast) toast("Lecture des clients et des plateformes en cours…");
    try {
      const r = await apiClient.get("/admin/volumetrie/plateformes");
      setPlateformes(r.data.plateformes || []); setClients(r.data.clients || []);
      setClient((c) => c || (r.data.clients || []).find((x) => x.en_ligne)?.code || "");
      if (avecToast) toast.success(`${(r.data.clients || []).length} client(s) connu(s).`);
    } catch (e) { if (avecToast) toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);

  useEffect(() => {
    setChoisies([]); setLignes([]);
    apiClient.get("/admin/volumetrie/tables", { params: { plateforme } }).then((r) => {
      const t = r.data.tables || []; setTables(t); setChoisies(t.filter((x) => (PAR_DEFAUT[plateforme] || []).includes(x.nom)).map((x) => x.nom));
    }).catch(() => setTables([]));
  }, [plateforme]);

  const options = useMemo(() => tables.map((t) => ({ id: t.nom, label: t.nom, detail: `${t.colonnes} col. · ${octets(t.octets_atlas)}/ligne${t.colonne_date ? ` · date : ${t.colonne_date}` : ""}` })), [tables]);

  // Comptage table par table (une demande à la fois : la machine du client traite une requête après l'autre) ; on peut arrêter
  const compter = async () => {
    if (!client) { toast.error("Choisissez un client."); return; }
    if (!choisies.length) { toast.error("Cochez au moins une table."); return; }
    setEnCours(true); arret.current = false; setLignes([]);
    toast(`Patientez… comptage de ${choisies.length} table(s) chez ${client}`);
    let erreurs = 0;
    for (let i = 0; i < choisies.length; i += 1) {
      if (arret.current) break;
      try {
        const r = await apiClient.post("/admin/volumetrie/compter", { client, plateforme, table: choisies[i], jours: Number(jours) || 7 });
        setLignes((l) => [...l, r.data]);
        if (r.data.erreur_total) erreurs += 1;
      } catch (e) { erreurs += 1; setLignes((l) => [...l, { table: choisies[i], erreur_total: e?.response?.data?.detail || "Comptage impossible" }]); }
    }
    setEnCours(false);
    (erreurs ? toast.error : toast.success)(`Comptage terminé${arret.current ? " (arrêté)" : ""} : ${erreurs} erreur(s).`);
  };

  const { lignes: triees, tri, basculer } = useTri(lignes, { table: (l) => l.table, total: (l) => l.total ?? -1, recents: (l) => l.recents ?? -1, octets: (l) => l.octets_atlas ?? -1, cache: (l) => l.taille_cache ?? -1, totale: (l) => l.taille_totale ?? -1, ms: (l) => l.ms ?? -1 });
  const totaux = useMemo(() => lignes.reduce((a, l) => ({ total: a.total + (l.total || 0), recents: a.recents + (l.recents || 0), cache: a.cache + (l.taille_cache || 0), totale: a.totale + (l.taille_totale || 0) }), { total: 0, recents: 0, cache: 0, totale: 0 }), [lignes]);

  const exporterCsv = () => {
    const ent = ["Table", "Lignes (total)", `Lignes (${jours} j)`, "Colonne de date", "Octets/ligne HFSQL", "Octets/document Atlas", `Cache estimé (${jours} j)`, "Taille totale estimée", "Champs mémo", "Temps (ms)", "Erreur"];
    const l = lignes.map((x) => [x.table, x.total ?? "", x.recents ?? "", x.colonne_date || "", x.octets_hfsql ?? "", x.octets_atlas ?? "", x.taille_cache ?? "", x.taille_totale ?? "", x.memos ?? "", x.ms ?? "", [x.erreur_total, x.erreur_recents].filter(Boolean).join(" | ")]);
    const texte = [ent, ...l].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\r\n");
    const url = URL.createObjectURL(new Blob(["﻿" + texte], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = `volumetrie-${client || "client"}-${plateforme}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
    toast.success("Fichier CSV exporté.");
  };

  return (
    <div className="space-y-3" data-testid="volumetrie">
      <p className="text-sm text-slate-600">Combien de lignes, et quelle place dans Atlas pour un cache d'une semaine ? Comptages en <b>lecture seule</b> chez le client choisi (une machine de ce client doit être en ligne). Le cache estimé = lignes des N derniers jours × taille d'un document Atlas ; comparez-le à la jauge « Base Atlas ».</p>
      {/* Mise en page (27/11/2026, propriétaire : « durée du cache plus petite, liste des tables 4 à 5 fois plus large ») : client, plateforme et durée gardent une largeur fixe, la liste des tables prend TOUTE la place restante */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[11rem_13rem_6.5rem_minmax(0,1fr)]">
        <label className="text-sm font-semibold text-slate-700">Client
          <select value={client} onChange={(e) => setClient(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal" data-testid="volu-client">
            <option value="">Choisir un client…</option>
            {clients.map((c) => <option key={c.code} value={c.code}>{c.code}{c.en_ligne ? " — en ligne" : " — hors ligne"}</option>)}</select></label>
        <label className="text-sm font-semibold text-slate-700">Plateforme
          <select value={plateforme} onChange={(e) => setPlateforme(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal" data-testid="volu-plateforme">
            {plateformes.map((p) => <option key={p.cle} value={p.cle}>{p.libelle} ({p.tables} tables)</option>)}</select></label>
        <label className="text-sm font-semibold text-slate-700" title="Durée du cache en jours">Cache <span className="font-normal text-slate-500">(jours)</span>
          <input type="number" min={1} max={60} value={jours} onChange={(e) => setJours(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" data-testid="volu-jours" /></label>
        <div className="min-w-0 text-sm font-semibold text-slate-700 sm:col-span-2 lg:col-span-1">Tables <span className="font-normal text-slate-500">({choisies.length})</span>
          <div className="mt-1 font-normal"><ListeMultiChoix options={options} valeur={choisies} onChange={setChoisies} vide="Cocher des tables…" pluriel="tables choisies" testid="volu-tables" /></div></div>
      </div>
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <button type="button" onClick={compter} disabled={enCours} data-testid="volu-compter" className="inline-flex items-center gap-1 rounded-full bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Play className="h-4 w-4" /> Compter</button>
        {enCours && <button type="button" onClick={() => { arret.current = true; }} className="inline-flex items-center gap-1 rounded-full border border-red-300 px-4 py-2 text-sm font-semibold text-red-800"><Square className="h-4 w-4" /> Arrêter</button>}
        <button type="button" onClick={() => charger(true)} disabled={enCours} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50"><RefreshCw className="h-4 w-4" /> Actualiser les clients</button>
        <button type="button" onClick={exporterCsv} disabled={!lignes.length} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50"><FileSpreadsheet className="h-4 w-4" /> Exporter CSV</button>
        {enCours && <span className="text-sm text-slate-600">{lignes.length}/{choisies.length} table(s)…</span>}
      </div>
      {lignes.length > 0 && (
        <div className="max-h-[32rem] overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm" data-testid="volu-table">
            <thead className="sticky top-0 bg-slate-50"><tr className="text-left text-slate-600">
              <ThTri cle="table" tri={tri} onTri={basculer}>Table</ThTri>
              <ThTri cle="total" tri={tri} onTri={basculer} droite>Lignes (total)</ThTri>
              <ThTri cle="recents" tri={tri} onTri={basculer} droite>Lignes ({jours} j)</ThTri>
              <ThTri cle="octets" tri={tri} onTri={basculer} droite>Octets / document</ThTri>
              <ThTri cle="cache" tri={tri} onTri={basculer} droite>Cache estimé ({jours} j)</ThTri>
              <ThTri cle="totale" tri={tri} onTri={basculer} droite>Taille totale estimée</ThTri>
              <ThTri cle="ms" tri={tri} onTri={basculer} droite>Temps</ThTri><th className="p-2">État</th></tr></thead>
            <tbody>{triees.map((l) => (
              <tr key={l.table} className="border-t align-top">
                <td className="p-2 font-semibold text-sky-800">{l.table}{l.colonne_date && <span className="block text-[11px] font-normal text-slate-500">date : {l.colonne_date}</span>}</td>
                <td className="p-2 text-right tabular-nums">{nombre(l.total)}</td>
                <td className="p-2 text-right tabular-nums text-indigo-800">{l.colonne_date ? nombre(l.recents) : <span className="text-slate-400">sans date</span>}</td>
                <td className="p-2 text-right tabular-nums">{l.octets_atlas ? `${nombre(l.octets_atlas)} o` : "—"}</td>
                <td className="p-2 text-right font-semibold tabular-nums text-emerald-700">{octets(l.taille_cache)}</td>
                <td className="p-2 text-right tabular-nums">{octets(l.taille_totale)}</td>
                <td className="p-2 text-right tabular-nums">{l.ms != null ? `${(l.ms / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s` : "—"}</td>
                <td className="p-2 text-xs">{l.erreur_total || l.erreur_recents ? <span className="text-red-700">✖ {l.erreur_total || l.erreur_recents}</span> : <span className="text-emerald-700">✔ ok</span>}{l.memos > 0 && <span className="block text-amber-700">{l.memos} champ(s) mémo non mis en cache</span>}</td>
              </tr>))}</tbody>
            <tfoot className="sticky bottom-0 bg-indigo-50 font-semibold"><tr><td className="p-2">Total : {lignes.length} table(s)</td><td className="p-2 text-right tabular-nums">{nombre(totaux.total)}</td><td className="p-2 text-right tabular-nums">{nombre(totaux.recents)}</td>
              <td /><td className="p-2 text-right tabular-nums text-emerald-700" data-testid="volu-total-cache">{octets(totaux.cache)}</td><td className="p-2 text-right tabular-nums">{octets(totaux.totale)}</td><td colSpan={2} /></tr></tfoot>
          </table>
        </div>)}
    </div>
  );
}
