// DemandesPlateformesSection.jsx — Lot 384 : rubrique « 📮 Demandes des plateformes » des Paramètres.
// Les plateformes clientes (ALBARKA…) remontent leurs corrections et nouvelles fonctionnalités ; SAWALI leur attribue un numéro
// (DEM-…) et le leur retourne avec un commentaire et la date de réalisation (ou la date prévue). Ici l'administrateur traite
// chaque demande : en attente (date prévue), réalisée (date + commentaire) ou refusée (raison). Recherche libre en haut.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

import { Save as Ico15Save, X as Ico15X } from "lucide-react";
const jour = (d) => (d ? String(d).slice(0, 10).split("-").reverse().join("/") : "—");
const COULEUR = { remontee: "text-amber-700", realisee: "text-emerald-700", refusee: "text-rose-700" };
const LIBELLE = { remontee: "En attente", realisee: "Réalisée", refusee: "Refusée" };

export default function DemandesPlateformesSection() {
  const [q, setQ] = useState("");
  const [demandes, setDemandes] = useState(null);
  const [edition, setEdition] = useState(null);   // { plateforme, numero, statut, commentaire, realisee_le, prevue_le }

  const charger = useCallback(() => apiClient.get("/admin/plateformes/demandes", { params: { q } })
    .then((r) => setDemandes(r.data.demandes)).catch(() => setDemandes([])), [q]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);   // recherche en direct

  // Enregistre le traitement de la demande ouverte
  const enregistrer = async () => {
    try {
      await apiClient.put(`/admin/plateformes/${edition.plateforme}/demandes/${edition.numero}`, {
        statut: edition.statut, commentaire: edition.commentaire, realisee_le: edition.realisee_le || null, prevue_le: edition.prevue_le || null });
      toast.success("Demande mise à jour : la plateforme la relira à son prochain échange");
      setEdition(null);
      charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  if (!demandes) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-demandes-plateformes">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher une demande (texte, numéro DEM-…, commentaire, « refusée »…)"
        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="demandes-plateformes-recherche" />
      <p className="text-xs text-slate-600">
        Les plateformes (ALBARKA…) remontent leurs demandes de corrections et de nouvelles fonctionnalités ; chacune reçoit ici un numéro
        <b> DEM-…</b> retourné à la plateforme avec votre commentaire et la date de réalisation (ou la date prévue).
      </p>
      <table className="w-full text-xs">
        <thead className="text-left text-slate-500"><tr><th className="py-1">N°</th><th>Plateforme</th><th>Type</th><th>Demande</th><th>Statut</th><th>Suivi</th><th /></tr></thead>
        <tbody>
          {demandes.map((d) => (
            <tr key={d.numero} className="border-t border-slate-100 align-top">
              <td className="py-1 font-mono">{d.numero}</td><td>{d.plateforme_nom}</td>
              <td>{d.type === "correction" ? "Correction" : "Nouveauté"}</td><td className="max-w-xs">{d.texte}</td>
              <td className={`font-semibold ${COULEUR[d.statut] || ""}`}>{LIBELLE[d.statut] || d.statut}</td>
              <td>{d.statut === "realisee" ? `Réalisée le ${jour(d.realisee_le)}` : d.statut === "remontee" && d.prevue_le ? `Prévue le ${jour(d.prevue_le)}` : ""}
                {d.commentaire && <div className="text-slate-500">{d.commentaire}</div>}</td>
              <td><button type="button" className="rounded bg-sky-700 px-2 py-1 text-white"
                onClick={() => setEdition({ plateforme: d.plateforme, numero: d.numero, statut: d.statut, commentaire: d.commentaire || "", realisee_le: d.realisee_le || "", prevue_le: d.prevue_le || "" })}>Traiter</button></td>
            </tr>
          ))}
          {demandes.length === 0 && <tr><td colSpan={7} className="py-3 text-center text-slate-500">Aucune demande{q ? " pour cette recherche" : ""}.</td></tr>}
        </tbody>
      </table>
      {edition && (
        <div className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 p-3" data-testid="demandes-plateformes-edition">
          <div className="text-sm font-semibold">Traiter {edition.numero}</div>
          <select value={edition.statut} onChange={(e) => setEdition({ ...edition, statut: e.target.value })} className="rounded border border-slate-300 px-2 py-1 text-sm">
            <option value="remontee">En attente (avec date prévue)</option>
            <option value="realisee">Réalisée</option>
            <option value="refusee">Refusée</option>
          </select>
          {edition.statut === "remontee" && <label className="block text-xs">Prévue le <input type="date" value={edition.prevue_le} onChange={(e) => setEdition({ ...edition, prevue_le: e.target.value })} className="ml-1 rounded border border-slate-300 px-2 py-1" /></label>}
          {edition.statut === "realisee" && <label className="block text-xs">Réalisée le <input type="date" value={edition.realisee_le} onChange={(e) => setEdition({ ...edition, realisee_le: e.target.value })} className="ml-1 rounded border border-slate-300 px-2 py-1" /> (vide = aujourd'hui)</label>}
          <textarea value={edition.commentaire} onChange={(e) => setEdition({ ...edition, commentaire: e.target.value })} rows={2} placeholder={edition.statut === "refusee" ? "Raison du refus (obligatoire)" : "Commentaire pour la plateforme"} className="w-full rounded border border-slate-300 px-2 py-1 text-sm" />
          <div className="flex gap-2">
            <button type="button" onClick={enregistrer} className="rounded bg-emerald-700 px-3 py-1.5 text-sm font-semibold text-white"><Ico15Save className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Enregistrer</button>
            <button type="button" onClick={() => setEdition(null)} className="rounded border border-slate-300 px-3 py-1.5 text-sm"><Ico15X className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Annuler</button>
          </div>
        </div>
      )}
    </div>
  );
}
