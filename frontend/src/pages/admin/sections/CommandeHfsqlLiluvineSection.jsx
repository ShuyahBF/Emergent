// ============================================================================
// Lot 458 — Paramètres → « 📡 Commande HFSQL distante via Liluvine ».
// L'administrateur (SEUL : une commande SQL touche des données réelles) règle QUI peut envoyer une commande HFSQL à Liluvine par WhatsApp :
//   « hfsql docx=CMC SELECT … » ou « hfsql docx=CMC UPDATE … » (une modification demande « OUI »). Une machine du client l'exécute ; la réponse (zone, base, commande, résultat du moteur) revient sur WhatsApp.
// Un numéro peut être limité à certaines zones (codes de clients, ex. CMC, PHL). Journal des dernières commandes ci-dessous. Enregistrement explicite (règle 15).
// Backend : GET/PUT /api/admin/liluvine-hfsql-acces (administrateur seul).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Pencil, Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Lot 459 — RACCOURCIS de commandes avec paramètres {nom} (créés depuis l'historique de Loois ou ici ; lancés par WhatsApp : « hfsql 1 »).
const PARAM = /\{([A-Za-z_][A-Za-z0-9_]{0,29})\}/g;
const parametresDe = (sql) => [...new Set([...String(sql || "").matchAll(PARAM)].map((m) => m[1]))];

function RaccourcisHfsql() {
  const [liste, setListe] = useState(null);
  const [max, setMax] = useState(20);
  const [edition, setEdition] = useState(null);          // { id?, nom, zone, sql, confirmer } : fenêtre de création / modification (règle 20)
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(async () => {
    toast("Lecture des raccourcis en cours…");
    try { const r = await apiClient.get("/admin/liluvine-hfsql-raccourcis"); setListe(r.data.raccourcis); setMax(r.data.maximum); toast.success(`${r.data.raccourcis.length} raccourci(s).`); }
    catch (e) { setListe([]); toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const enregistrer = async () => {
    setEnCours(true); toast("Enregistrement du raccourci en cours…");
    try {
      const corps = { nom: edition.nom, sql: edition.sql, zone: edition.zone, confirmer: !!edition.confirmer };
      if (edition.id) await apiClient.put(`/admin/liluvine-hfsql-raccourcis/${edition.id}`, corps); else await apiClient.post("/admin/liluvine-hfsql-raccourcis", corps);
      toast.success("Raccourci enregistré."); setEdition(null); await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnCours(false); }
  };
  const supprimer = async (r) => {
    if (!window.confirm(`Supprimer le raccourci « ${r.nom} » ?`)) return;
    toast("Suppression en cours…");
    try { await apiClient.delete(`/admin/liluvine-hfsql-raccourcis/${r.id}`); toast.success("Raccourci supprimé."); await charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Suppression impossible"); }
  };

  if (liste === null) return null;
  const params = edition ? parametresDe(edition.sql) : [];
  return (
    <div className="space-y-2 rounded-xl border border-slate-200 p-3" data-testid="raccourcis-hfsql">
      <h4 className="font-semibold">⭐ Raccourcis de commandes ({liste.length} / {max})</h4>
      <p className="text-xs text-slate-600">
        Une commande déjà réussie devient un raccourci : les valeurs qui changent s'écrivent entre accolades, ex. <code>UPDATE VenteClinique SET Mag = {"{vStatut}"} WHERE Référence = {"{RefNum}"}</code>.
        Par WhatsApp : « <b>hfsql</b> » liste les raccourcis, « <b>hfsql 1</b> » lance le n° 1, Liluvine demande chaque valeur dans l'ordre, exécute et renvoie le résultat. On les crée aussi dans Loois
        (Requête SQL distante → Dernières requêtes → ⭐ Créer un raccourci).
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead><tr className="text-left text-slate-600"><th className="px-1">N°</th><th className="px-1">Nom</th><th className="px-1">Zone</th><th className="px-1">Paramètres (ordre demandé)</th><th className="px-1">OUI avant ?</th><th /></tr></thead>
          <tbody>
            {liste.map((r, i) => (
              <tr key={r.id} className="border-t align-top">
                <td className="px-1 py-1 tabular-nums">{i + 1}</td><td className="px-1 py-1 font-semibold">{r.nom}</td><td className="px-1 py-1">{r.zone || <span className="text-amber-700">à préciser</span>}</td>
                <td className="px-1 py-1">{(r.parametres || []).join(", ") || "aucun"}</td><td className="px-1 py-1">{r.confirmer ? "oui" : "non"}</td>
                <td className="px-1 py-1 whitespace-nowrap">
                  <button type="button" onClick={() => setEdition({ ...r })} className="mr-2 inline-flex items-center gap-1 text-slate-700" aria-label={`Modifier ${r.nom}`}><Pencil className="w-4 h-4" /> Modifier</button>
                  <button type="button" onClick={() => supprimer(r)} className="inline-flex items-center gap-1 text-red-700" aria-label={`Supprimer ${r.nom}`}><Trash2 className="w-4 h-4" /> Supprimer</button>
                </td>
              </tr>))}
            {liste.length === 0 && <tr><td colSpan={6} className="px-1 py-2 text-slate-500">Aucun raccourci.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={liste.length >= max} onClick={() => setEdition({ nom: "", zone: "docx=", sql: "", confirmer: false })} data-testid="raccourci-nouveau" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Plus className="w-4 h-4" /> Nouveau raccourci</button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
      </div>
      {edition && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-3" role="dialog" aria-modal="true">
          <div className="w-full max-w-xl max-h-[85dvh] overflow-y-auto rounded-2xl bg-white p-4 space-y-3" data-testid="raccourci-fenetre">
            <h2 className="text-lg font-bold">{edition.id ? "Modifier le raccourci" : "Nouveau raccourci"}</h2>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-sm font-semibold">Nom<input value={edition.nom} onChange={(e) => setEdition({ ...edition, nom: e.target.value })} maxLength={40} placeholder="Statut d'un reçu" className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
              <label className="text-sm font-semibold">Zone par défaut<input value={edition.zone} onChange={(e) => setEdition({ ...edition, zone: e.target.value })} placeholder="docx=CMC" className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
            </div>
            <label className="block text-sm font-semibold">Commande (paramètres entre accolades)
              <textarea value={edition.sql} onChange={(e) => setEdition({ ...edition, sql: e.target.value })} rows={4} className="mt-1 w-full rounded-lg border border-slate-300 p-2 font-mono text-sm font-normal" placeholder="UPDATE VenteClinique SET Mag = {vStatut} WHERE Référence = {RefNum}" /></label>
            <p className="text-sm" data-testid="raccourci-parametres">{params.length ? <>Paramètres détectés, dans l'ordre demandé : <b>{params.join(" → ")}</b></> : "Aucun paramètre : la commande s'exécutera telle quelle."}</p>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edition.confirmer} onChange={(e) => setEdition({ ...edition, confirmer: e.target.checked })} /> Demander « OUI » avant d'exécuter une modification</label>
            <div className="flex flex-wrap justify-end gap-2">
              <button type="button" onClick={() => setEdition(null)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold"><X className="w-4 h-4" /> Fermer</button>
              <button type="button" onClick={enregistrer} disabled={enCours} data-testid="raccourci-enregistrer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Save className="w-4 h-4" /> Enregistrer</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function CommandeHfsqlLiluvineSection() {
  const [lignes, setLignes] = useState(null);
  const [journal, setJournal] = useState([]);
  const [initial, setInitial] = useState("");
  const [max, setMax] = useState(30);
  const modifie = lignes !== null && JSON.stringify(lignes) !== initial;

  const charger = useCallback(async () => {
    toast("Lecture des numéros et du journal en cours…");
    try {
      const r = await apiClient.get("/admin/liluvine-hfsql-acces");
      setLignes(r.data.acces); setInitial(JSON.stringify(r.data.acces)); setMax(r.data.maximum); setJournal(r.data.journal || []);
      toast.success(`${r.data.acces.length} numéro(s) autorisé(s), ${(r.data.journal || []).length} commande(s) au journal.`);
    } catch (e) { setLignes([]); toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const maj = (i, champ, v) => setLignes((l) => l.map((x, k) => (k === i ? { ...x, [champ]: v } : x)));
  const enregistrer = async () => {
    toast("Enregistrement en cours…");
    try { const r = await apiClient.put("/admin/liluvine-hfsql-acces", { acces: lignes }); setLignes(r.data.acces); setInitial(JSON.stringify(r.data.acces)); toast.success(`Enregistré : ${r.data.acces.length} numéro(s) autorisé(s).`); }
    catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  if (lignes === null) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3" data-testid="commande-hfsql-acces">
      <p className="text-xs text-slate-600">
        Numéros WhatsApp autorisés à envoyer une commande HFSQL à Liluvine : « <b>hfsql docx=CMC SELECT …</b> ». Une lecture s'exécute tout de suite ; une <b>modification</b> (INSERT, UPDATE, DELETE) est répétée par Liluvine et attend « OUI ».
        Mêmes contrôles « Prudent » que Loois (une seule instruction, UPDATE / DELETE avec WHERE, aucune modification de structure). Zones permises vides = toutes. 20 commandes par heure et par numéro.
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead><tr className="text-left text-slate-600"><th className="px-1">Numéro WhatsApp</th><th className="px-1">Nom</th><th className="px-1">Zones permises (codes clients)</th><th className="px-1">Actif</th><th /></tr></thead>
          <tbody>
            {lignes.map((l, i) => (
              <tr key={i} className="border-t">
                <td className="px-1 py-1"><input value={l.numero || ""} onChange={(e) => maj(i, "numero", e.target.value)} placeholder="+226 70 12 34 56" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1"><input value={l.nom || ""} onChange={(e) => maj(i, "nom", e.target.value)} placeholder="BADINI Awa" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1"><input value={l.zones || ""} onChange={(e) => maj(i, "zones", e.target.value)} placeholder="CMC, PHL (vide = toutes)" className="w-48 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1 text-center"><input type="checkbox" checked={l.actif !== false} onChange={(e) => maj(i, "actif", e.target.checked)} aria-label="Actif" /></td>
                <td className="px-1 py-1"><button type="button" onClick={() => setLignes((x) => x.filter((_, k) => k !== i))} aria-label="Retirer ce numéro" title="Retirer ce numéro" className="text-red-700"><Trash2 className="w-4 h-4" /></button></td>
              </tr>))}
            {lignes.length === 0 && <tr><td colSpan={5} className="px-1 py-2 text-slate-500">Aucun numéro autorisé : la fonction est fermée.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={lignes.length >= max} onClick={() => setLignes((l) => [...l, { numero: "", nom: "", zones: "", actif: true }])} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Plus className="w-4 h-4" /> Ajouter un numéro</button>
        <button type="button" onClick={enregistrer} disabled={!modifie} data-testid="commande-hfsql-enregistrer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Save className="w-4 h-4" /> Enregistrer</button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
        {modifie && <span className="text-xs text-amber-700">modifié, non enregistré</span>}
      </div>
      <RaccourcisHfsql />
      <h4 className="font-semibold pt-2">Journal des dernières commandes</h4>
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="min-w-full text-xs" data-testid="commande-hfsql-journal">
          <thead className="sticky top-0 bg-white"><tr className="text-left text-slate-600"><th className="px-1">Quand</th><th className="px-1">Qui</th><th className="px-1">Zone</th><th className="px-1">Nature</th><th className="px-1">Commande</th><th className="px-1">Issue</th></tr></thead>
          <tbody>
            {journal.map((e, i) => (
              <tr key={i} className="border-t align-top">
                <td className="px-1 py-1 whitespace-nowrap tabular-nums">{(e.quand || "").slice(0, 16).replace("T", " ")}</td>
                <td className="px-1 py-1">{e.nom || e.numero}</td><td className="px-1 py-1">{e.zone}</td>
                <td className="px-1 py-1">{e.nature === "MODIF" ? <span className="text-red-700 font-semibold">MODIF</span> : e.nature}</td>
                <td className="px-1 py-1 max-w-md break-words">{e.sql}</td><td className="px-1 py-1">{e.issue}</td>
              </tr>))}
            {journal.length === 0 && <tr><td colSpan={6} className="px-1 py-2 text-slate-500">Aucune commande pour le moment.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
