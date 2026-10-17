/*
  Lot 227 — Paramètres : « Formules des plateformes » — abonnements vendus aux utilisateurs des plateformes (Paiement Mobile…).
    - Vitrine : plateforme (liste), nom, description, prix en FCFA, durée en jours (30 par défaut), fonction débloquée (liste), active.
    - Chaque paiement (page PawaPay hébergée) active la formule pour sa durée ; un nouveau paiement avant l'échéance S'AJOUTE au temps restant.
    - Parrainage : jours offerts à CHACUN (parrain et filleul) quand le filleul paie sa première formule (0 = désactivé).
    - Suivi : abonnés actifs, ventes et chiffre d'affaires par formule ; une formule déjà vendue n'est jamais supprimée, elle est désactivée.
  API : GET/POST/PUT/DELETE /admin/formules-plateformes, PUT /admin/formules-plateformes-reglages (backend/routes/formules_plateformes.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const fcfa = (n) => `${Number(n || 0).toLocaleString("fr-FR")} FCFA`;
const VIDE = { plateforme: "", nom: "", description: "", prix: "", duree_jours: 30, fonctions: ["ocr_ordonnances"], actif: true, ordre: 0 };

export default function FormulesPlateformesSection() {
  const [d, setD] = useState(null);
  const [edition, setEdition] = useState(null);       // formule en cours de saisie (id absent = nouvelle)
  const [jours, setJours] = useState(7);
  const [envoi, setEnvoi] = useState(false);

  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/formules-plateformes");
      setD(r.data);
      setJours(r.data.parrainage_jours);
    } catch (e) { toast.error(e?.response?.data?.detail || "Formules indisponibles (réservé à l'administrateur principal)"); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const enregistrer = async (e) => {
    e.preventDefault();
    setEnvoi(true);
    const corps = { plateforme: edition.plateforme, nom: edition.nom, description: edition.description, prix: Number(edition.prix),
      duree_jours: Number(edition.duree_jours), fonctions: edition.fonctions, actif: edition.actif, ordre: Number(edition.ordre || 0) };
    try {
      if (edition.id) await apiClient.put(`/admin/formules-plateformes/${edition.id}`, corps);
      else await apiClient.post("/admin/formules-plateformes", corps);
      toast.success("Formule enregistrée");
      setEdition(null);
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); } finally { setEnvoi(false); }
  };
  const supprimer = async (f) => {
    if (!window.confirm(`Supprimer la formule « ${f.nom} » ? (désactivée seulement si elle a déjà été vendue)`)) return;
    try {
      const r = await apiClient.delete(`/admin/formules-plateformes/${f.id}`);
      toast.success(r.data.desactivee ? "Formule déjà vendue : désactivée" : "Formule supprimée");
      charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Suppression impossible"); }
  };
  const enregistrerParrainage = async () => {
    try { await apiClient.put("/admin/formules-plateformes-reglages", { parrainage_jours: Number(jours) }); toast.success("Parrainage enregistré"); charger(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); }
  };

  if (!d) return <p className="text-xs text-slate-500">Chargement des formules…</p>;
  const champ = (cle) => (e) => setEdition({ ...edition, [cle]: e.target.value });
  return (
    <div className="space-y-4" data-testid="formules-plateformes">
      <p className="text-xs text-slate-600">
        Formules vendues aux utilisateurs des plateformes (ex. « OCR Ordonnances » dans Paiement Mobile). Le paiement passe par la page PawaPay
        hébergée et active la formule tout seul ; payer avant l'échéance <b>ajoute</b> la durée au temps restant.
      </p>
      {!d.pawapay_actif && <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900 ring-1 ring-amber-200">PawaPay n'est pas activé : les achats sont refusés tant qu'il ne l'est pas (rubrique PawaPay).</p>}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 text-center text-xs">
        <div className="rounded-lg ring-1 ring-slate-200 p-2"><p className="text-slate-500">Utilisateurs suivis</p><p className="text-lg font-bold">{d.membres}</p></div>
        <div className="rounded-lg ring-1 ring-slate-200 p-2"><p className="text-slate-500">Abonnés actifs</p><p className="text-lg font-bold">{d.formules.reduce((n, f) => n + f.abonnes_actifs, 0)}</p></div>
        <div className="rounded-lg ring-1 ring-slate-200 p-2 col-span-2 md:col-span-1"><p className="text-slate-500">Chiffre d'affaires</p><p className="text-lg font-bold">{fcfa(d.formules.reduce((n, f) => n + f.chiffre, 0))}</p></div>
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-lg ring-1 ring-slate-200 p-3 text-xs">
        <label className="flex flex-col gap-1">Parrainage : jours offerts à chacun (parrain et filleul)
          <input type="number" min={0} max={90} value={jours} onChange={(e) => setJours(e.target.value)} className="w-28 rounded border border-slate-300 px-2 py-1" data-testid="parrainage-jours" />
        </label>
        <button type="button" onClick={enregistrerParrainage} className="rounded bg-slate-800 px-3 py-1.5 text-white">Enregistrer</button>
        <span className="text-slate-500">0 = pas de récompense. Donnés à la première formule payée du filleul.</span>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Formules ({d.formules.length})</p>
        <button type="button" onClick={() => setEdition({ ...VIDE, plateforme: d.plateformes[0]?.code || "" })} className="rounded bg-emerald-600 px-3 py-1.5 text-xs text-white" data-testid="formule-ajouter">+ Nouvelle formule</button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="p-1">Plateforme</th><th>Formule</th><th>Prix</th><th>Durée</th><th>Abonnés</th><th>Ventes</th><th>CA</th><th>État</th><th /></tr></thead>
          <tbody>
            {d.formules.length === 0 && <tr><td colSpan={9} className="p-3 text-slate-500">Aucune formule. Créez « OCR Ordonnances » pour Paiement Mobile.</td></tr>}
            {d.formules.map((f) => (
              <tr key={f.id} className="border-t border-slate-100">
                <td className="p-1">{f.plateforme}</td>
                <td><b>{f.nom}</b><br /><span className="text-slate-500">{(f.fonctions || []).map((x) => d.fonctions[x] || x).join(", ")}</span></td>
                <td>{fcfa(f.prix)}</td><td>{f.duree_jours} j</td><td>{f.abonnes_actifs}</td><td>{f.ventes}</td><td>{fcfa(f.chiffre)}</td>
                <td>{f.actif ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800">Active</span> : <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">Inactive</span>}</td>
                <td className="whitespace-nowrap text-right">
                  <button type="button" onClick={() => setEdition({ ...f, prix: String(f.prix), description: f.description || "" })} className="px-1" aria-label={`Modifier ${f.nom}`}>✏️</button>
                  <button type="button" onClick={() => supprimer(f)} className="px-1" aria-label={`Supprimer ${f.nom}`}>🗑</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {edition && (
        <form onSubmit={enregistrer} className="space-y-2 rounded-lg ring-1 ring-slate-300 bg-slate-50 p-3 text-xs" data-testid="formule-form">
          <p className="text-sm font-semibold">{edition.id ? "Modifier la formule" : "Nouvelle formule"}</p>
          <div className="grid gap-2 md:grid-cols-2">
            <label className="flex flex-col gap-1">Plateforme
              <select required value={edition.plateforme} onChange={champ("plateforme")} className="rounded border border-slate-300 px-2 py-1.5">
                <option value="" disabled>Choisir…</option>
                {d.plateformes.map((p) => <option key={p.code} value={p.code}>{p.nom} ({p.code})</option>)}
              </select></label>
            <label className="flex flex-col gap-1">Nom affiché
              <input required minLength={2} maxLength={60} value={edition.nom} onChange={champ("nom")} placeholder="OCR Ordonnances" className="rounded border border-slate-300 px-2 py-1.5" /></label>
            <label className="flex flex-col gap-1">Prix (FCFA)
              <input required type="number" min={100} value={edition.prix} onChange={champ("prix")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
            <label className="flex flex-col gap-1">Durée (jours)
              <input required type="number" min={1} max={366} value={edition.duree_jours} onChange={champ("duree_jours")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
            <label className="flex flex-col gap-1">Fonction débloquée
              <select value={edition.fonctions[0] || ""} onChange={(e) => setEdition({ ...edition, fonctions: e.target.value ? [e.target.value] : [] })} className="rounded border border-slate-300 px-2 py-1.5">
                {Object.entries(d.fonctions).map(([k, n]) => <option key={k} value={k}>{n}</option>)}
              </select></label>
            <label className="flex flex-col gap-1">Ordre d'affichage
              <input type="number" min={0} max={999} value={edition.ordre} onChange={champ("ordre")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
          </div>
          <label className="flex flex-col gap-1">Description (affichée à l'utilisateur)
            <input maxLength={300} value={edition.description} onChange={champ("description")} className="rounded border border-slate-300 px-2 py-1.5" /></label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={edition.actif} onChange={(e) => setEdition({ ...edition, actif: e.target.checked })} />Formule active (proposée à l'achat)</label>
          <div className="flex gap-2">
            <button type="submit" disabled={envoi} className="rounded bg-emerald-600 px-3 py-1.5 text-white">{envoi ? "Patientez…" : "Enregistrer"}</button>
            <button type="button" onClick={() => setEdition(null)} className="rounded border border-slate-300 px-3 py-1.5">Annuler</button>
          </div>
        </form>
      )}
    </div>
  );
}
