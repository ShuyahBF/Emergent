// ============================================================================
// Lot 458 — Paramètres → « 📡 Commande HFSQL distante via Liluvine ».
// L'administrateur (SEUL : une commande SQL touche des données réelles) règle QUI peut envoyer une commande HFSQL à Liluvine par WhatsApp :
//   « hfsql docx=CMC SELECT … » ou « hfsql docx=CMC UPDATE … » (une modification demande « OUI »). Une machine du client l'exécute ; la réponse (zone, base, commande, résultat du moteur) revient sur WhatsApp.
// Un numéro peut être limité à certaines zones (codes de clients, ex. CMC, PHL). Journal des dernières commandes ci-dessous. Enregistrement explicite (règle 15).
// Backend : GET/PUT /api/admin/liluvine-hfsql-acces (administrateur seul).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

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
