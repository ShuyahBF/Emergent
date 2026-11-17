// OffreConversation.jsx — Lot 431 : onglet « Produits & services » d'une conversation du Centre de messagerie.
// Montre les logiciels, produits et services du CLIENT relié au contact, SANS AUCUN TARIF. Lecture pour toute l'équipe ; modification réservée au
// superviseur (le serveur refuse les autres). Les tarifs, échéances et rappels ne se voient ni ne se modifient ici : ils restent dans la fiche du client.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Boxes, Package, Pencil, Plus, Save, Trash2, Wrench, X, Laptop } from "lucide-react";
import { apiClient } from "@/lib/api";

const TYPES = [["logiciel", "Logiciel", Laptop], ["produit", "Produit", Package], ["service", "Service", Wrench]];   // liste finie → liste déroulante (règle 10)
const LIBELLE = Object.fromEntries(TYPES.map(([k, l]) => [k, l]));

export default function OffreConversation({ contact, onCount }) {
  const [etat, setEtat] = useState(null);           // { client, lignes, modifiable }
  const [edition, setEdition] = useState(null);     // lignes en cours de modification (null = lecture)
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(async () => {
    try {
      const { data } = await apiClient.post("/me/contact-offre", { contact_id: contact.id });
      setEtat(data); onCount?.(data.lignes.length);
    } catch { setEtat({ client: null, lignes: [], modifiable: false, erreur: true }); }
  }, [contact.id, onCount]);
  useEffect(() => { setEtat(null); setEdition(null); charger(); }, [charger]);

  if (!etat) return <p className="px-5 py-4 text-sm text-slate-500" data-testid="offre-chargement">Patientez…</p>;
  if (etat.erreur) return <p className="px-5 py-4 text-sm text-rose-700">Impossible de lire les produits et services.</p>;
  if (!etat.client) return (
    <p className="px-5 py-4 text-sm text-slate-500" data-testid="offre-sans-client">Ce contact n'est relié à aucun client : aucun produit ni service à afficher.</p>
  );

  const majLigne = (i, champ, valeur) => setEdition(edition.map((l, k) => (k === i ? { ...l, [champ]: valeur } : l)));
  const enregistrer = async () => {
    setOccupe(true);
    try {
      const { data } = await apiClient.put("/me/contact-offre", { contact_id: contact.id, lignes: edition });
      setEtat({ ...etat, lignes: data.lignes }); onCount?.(data.lignes.length); setEdition(null);
      toast.success("Produits et services enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3" data-testid="wa-tab-offre-content">
      <div className="flex flex-wrap items-center gap-2">
        <Boxes className="h-4 w-4 text-sawali-blue" aria-hidden="true" />
        <h3 className="text-sm font-semibold">Produits et services de {etat.client.nom || "ce client"}</h3>
        <span className="text-xs text-slate-500">(sans les tarifs)</span>
        {etat.modifiable && !edition && (
          <button type="button" onClick={() => setEdition(etat.lignes.map((l) => ({ ...l })))} data-testid="offre-modifier"
            className="ml-auto inline-flex items-center gap-1 rounded border border-sawali-blue px-2.5 py-1 text-xs font-semibold text-sawali-blue hover:bg-slate-50">
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" /> Modifier</button>
        )}
      </div>

      {!edition ? (
        etat.lignes.length === 0 ? <p className="text-sm italic text-slate-400" data-testid="offre-vide">Aucun produit ni service enregistré pour ce client.</p> : (
          <ul className="space-y-2" data-testid="offre-liste">
            {etat.lignes.map((l) => {
              const Pic = (TYPES.find(([k]) => k === l.type) || TYPES[0])[2];
              return (
                <li key={l.id} className={`rounded-lg border p-3 ${l.actif ? "border-slate-200 bg-white" : "border-slate-200 bg-slate-50 opacity-70"}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Pic className="h-4 w-4 text-slate-500" aria-hidden="true" />
                    <span className="font-semibold text-slate-900">{l.nom}</span>
                    {l.version && <span className="rounded bg-slate-100 px-1.5 text-xs tabular-nums text-slate-700">v{l.version}</span>}
                    <span className="text-xs text-slate-500">{LIBELLE[l.type]}</span>
                    {!l.actif && <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900">Inactif</span>}
                  </div>
                  {l.description && <p className="mt-1 text-sm text-slate-600">{l.description}</p>}
                </li>
              );
            })}
          </ul>
        )
      ) : (
        <div className="space-y-2" data-testid="offre-edition">
          {edition.map((l, i) => (
            <div key={l.id || `n${i}`} className="grid gap-2 rounded-lg border border-slate-200 bg-white p-2 sm:grid-cols-[130px_1fr_80px_auto]">
              <select value={l.type} onChange={(e) => majLigne(i, "type", e.target.value)} aria-label="Type" className="rounded border border-slate-300 px-2 py-1 text-sm">
                {TYPES.map(([k, lib]) => <option key={k} value={k}>{lib}</option>)}
              </select>
              <input value={l.nom || ""} onChange={(e) => majLigne(i, "nom", e.target.value)} maxLength={120} placeholder="Nom" aria-label="Nom" className="rounded border border-slate-300 px-2 py-1 text-sm" />
              <input value={l.version || ""} onChange={(e) => majLigne(i, "version", e.target.value)} maxLength={40} placeholder="Version" aria-label="Version" className="rounded border border-slate-300 px-2 py-1 text-sm" />
              <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={l.actif !== false} onChange={(e) => majLigne(i, "actif", e.target.checked)} /> Actif</label>
              <input value={l.description || ""} onChange={(e) => majLigne(i, "description", e.target.value)} maxLength={300} placeholder="Description" aria-label="Description" className="rounded border border-slate-300 px-2 py-1 text-sm sm:col-span-3" />
              <button type="button" onClick={() => setEdition(edition.filter((_, k) => k !== i))} aria-label={`Retirer ${l.nom || "cette ligne"}`} className="inline-flex items-center gap-1 text-xs text-rose-700">
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Retirer</button>
            </div>
          ))}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => setEdition([...edition, { type: "produit", nom: "", description: "", version: "", actif: true }])}
              className="inline-flex items-center gap-1 rounded border border-slate-300 px-2.5 py-1.5 text-sm"><Plus className="h-4 w-4" aria-hidden="true" /> Ajouter une ligne</button>
            <button type="button" onClick={enregistrer} disabled={occupe} data-testid="offre-enregistrer"
              className="inline-flex items-center gap-1 rounded bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white"><Save className="h-4 w-4" aria-hidden="true" /> {occupe ? "Patientez…" : "Enregistrer"}</button>
            <button type="button" onClick={() => setEdition(null)} className="inline-flex items-center gap-1 rounded border border-slate-300 px-3 py-1.5 text-sm"><X className="h-4 w-4" aria-hidden="true" /> Annuler</button>
          </div>
          <p className="text-xs text-slate-500">Les tarifs, échéances et rappels ne sont jamais modifiés ici : ils restent dans la fiche du client.</p>
        </div>
      )}
    </div>
  );
}
