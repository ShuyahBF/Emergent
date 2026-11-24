// ============================================================================
// Lot 454 — Paramètres → « 💬 Consignes à Liluvine — numéros WhatsApp autorisés ».
// L'administrateur règle QUI peut donner des consignes à Liluvine par WhatsApp (utilisé par le lot « consignes par WhatsApp »), client / tenant par client.
// Une ligne = un numéro WhatsApp (reconnu par ses 8 derniers chiffres), un nom, le client concerné (vide = SAWALI) et « actif ».
// Le partage de l'écran « Consignes » aux superviseurs se règle dans « Liluvine — partage avec les superviseurs » (élément « Consignes à Liluvine »).
// Backend : GET/PUT /api/admin/liluvine-consignes-acces (administrateur seul). Enregistrement explicite (règle 15).
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Copy, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";


// Lot 456.1 — modèle Meta des envois en masse HORS fenêtre de 24 h : le texte à soumettre à Meta (avec le bouton « Bien reçu ») et le nom du modèle une fois approuvé.
function ModeleMasse() {
  const [info, setInfo] = useState(null);
  const [nom, setNom] = useState("");
  const [langue, setLangue] = useState("fr");
  const [initial, setInitial] = useState("");
  const modifie = info !== null && `${nom}|${langue}` !== initial;
  const charger = useCallback(async () => {
    toast("Lecture du modèle Meta en cours…");
    try { const r = await apiClient.get("/admin/liluvine-consignes/masse/modele"); setInfo(r.data.a_soumettre); setNom(r.data.modele.nom || ""); setLangue(r.data.modele.langue || "fr"); setInitial(`${r.data.modele.nom || ""}|${r.data.modele.langue || "fr"}`); toast.success("Modèle relu."); }
    catch (e) { toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);
  const enregistrer = async () => {
    toast("Enregistrement du modèle en cours…");
    try { const r = await apiClient.put("/admin/liluvine-consignes/masse/modele", { nom, langue }); setNom(r.data.modele.nom); setInitial(`${r.data.modele.nom}|${r.data.modele.langue}`); toast.success(r.data.modele.nom ? "Modèle enregistré : les envois en masse l'utiliseront hors fenêtre de 24 h." : "Modèle retiré : les contacts hors fenêtre resteront « non envoyé »."); }
    catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };
  const copier = (t) => { navigator.clipboard?.writeText(t); toast.success("Copié."); };
  if (!info) return null;
  return (
    <div className="mt-4 space-y-2 rounded-xl border border-slate-200 p-3" data-testid="modele-masse">
      <h4 className="font-semibold">📣 Modèle Meta des envois en masse (personnes qui n'ont pas écrit depuis 24 h)</h4>
      <p className="text-xs text-slate-600">À soumettre à Meta (Gestionnaire WhatsApp → Modèles de message) : catégorie « {info.categorie} », langue « {info.langue} », nom « {info.nom} », corps ci-dessous, bouton de réponse rapide « {info.bouton} ». Exemples demandés par Meta : {info.exemples.map((e) => `« ${e} »`).join(" et ")}.</p>
      <p className="rounded-lg bg-slate-50 p-2 text-sm">{info.corps}</p>
      <button type="button" onClick={() => copier(info.corps)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Copy className="w-4 h-4" /> Copier le corps</button>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-sm font-semibold">Nom du modèle APPROUVÉ par Meta<input value={nom} onChange={(e) => setNom(e.target.value)} placeholder={info.nom} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
        <label className="text-sm font-semibold">Langue<input value={langue} onChange={(e) => setLangue(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm font-normal" /></label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={enregistrer} disabled={!modifie} data-testid="modele-masse-enregistrer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Save className="w-4 h-4" /> Enregistrer le modèle</button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
        {modifie && <span className="text-xs text-amber-700">modifié, non enregistré</span>}
      </div>
    </div>
  );
}

export default function ConsignesLiluvineAccesSection() {
  const [lignes, setLignes] = useState(null);
  const [initial, setInitial] = useState("");
  const [max, setMax] = useState(100);
  const modifie = lignes !== null && JSON.stringify(lignes) !== initial;

  const charger = useCallback(async () => {
    toast("Lecture des numéros autorisés en cours…");
    try { const r = await apiClient.get("/admin/liluvine-consignes-acces"); setLignes(r.data.acces); setInitial(JSON.stringify(r.data.acces)); setMax(r.data.maximum); toast.success(`${r.data.acces.length} numéro(s) autorisé(s).`); }
    catch (e) { setLignes([]); toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const maj = (i, champ, v) => setLignes((l) => l.map((x, k) => (k === i ? { ...x, [champ]: v } : x)));
  const enregistrer = async () => {
    toast("Enregistrement en cours…");
    try { const r = await apiClient.put("/admin/liluvine-consignes-acces", { acces: lignes }); setLignes(r.data.acces); setInitial(JSON.stringify(r.data.acces)); toast.success(`Enregistré : ${r.data.acces.length} numéro(s) autorisé(s).`); }
    catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  if (lignes === null) return <p className="text-sm text-slate-500">Chargement…</p>;
  return (
    <div className="space-y-3" data-testid="consignes-acces">
      <p className="text-xs text-slate-600">Numéros WhatsApp autorisés à donner des consignes à Liluvine, par client / tenant (client vide = SAWALI). Un numéro inconnu ou désactivé est ignoré. Le superviseur ouvre l'écran « Consignes » (menu Liluvine) si l'élément lui est partagé dans « Liluvine — partage avec les superviseurs ».</p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead><tr className="text-left text-slate-600"><th className="px-1">Numéro WhatsApp</th><th className="px-1">Nom</th><th className="px-1">Client / tenant</th><th className="px-1">Actif</th><th /></tr></thead>
          <tbody>
            {lignes.map((l, i) => (
              <tr key={i} className="border-t">
                <td className="px-1 py-1"><input value={l.numero || ""} onChange={(e) => maj(i, "numero", e.target.value)} placeholder="+226 70 12 34 56" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1"><input value={l.nom || ""} onChange={(e) => maj(i, "nom", e.target.value)} placeholder="BADINI Awa" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1"><input value={l.tenant_nom || ""} onChange={(e) => maj(i, "tenant_nom", e.target.value)} placeholder="SAWALI (vide)" className="w-40 rounded border border-slate-300 p-1" /></td>
                <td className="px-1 py-1 text-center"><input type="checkbox" checked={l.actif !== false} onChange={(e) => maj(i, "actif", e.target.checked)} aria-label="Actif" /></td>
                <td className="px-1 py-1"><button type="button" onClick={() => setLignes((x) => x.filter((_, k) => k !== i))} aria-label="Retirer ce numéro" title="Retirer ce numéro" className="text-red-700"><Trash2 className="w-4 h-4" /></button></td>
              </tr>))}
            {lignes.length === 0 && <tr><td colSpan={5} className="px-1 py-2 text-slate-500">Aucun numéro autorisé.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={lignes.length >= max} onClick={() => setLignes((l) => [...l, { numero: "", nom: "", tenant: "", tenant_nom: "", actif: true }])} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><Plus className="w-4 h-4" /> Ajouter un numéro</button>
        <button type="button" onClick={enregistrer} disabled={!modifie} data-testid="consignes-acces-enregistrer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-3 py-1 text-sm font-semibold text-white disabled:opacity-50"><Save className="w-4 h-4" /> Enregistrer</button>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1 text-sm"><RefreshCw className="w-4 h-4" /> Actualiser</button>
        {modifie && <span className="text-xs text-amber-700">modifié, non enregistré</span>}
      </div>
      <ModeleMasse />
    </div>
  );
}
