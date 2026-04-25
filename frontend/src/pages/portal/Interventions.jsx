import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export default function ClientInterventions() {
  const [items, setItems] = useState([]);
  useEffect(() => { apiClient.get("/me/interventions").then((r) => setItems(r.data)).catch(() => {}); }, []);
  return (
    <div className="space-y-6" data-testid="client-interventions-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Historique de nos interventions</h1>
        <p className="text-sm text-slate-500">Détail de toutes les interventions réalisées sur votre compte.</p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Titre</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Technicien</th>
              <th className="text-left px-4 py-3">Statut</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-500">Aucune intervention enregistrée.</td></tr>}
            {items.map((i) => (
              <tr key={i.id} className="border-t border-slate-100" data-testid={`intervention-row-${i.id}`}>
                <td className="px-4 py-3 font-medium text-slate-800">
                  {i.title}
                  {i.description && <p className="text-xs text-slate-500 font-normal mt-0.5 line-clamp-1">{i.description}</p>}
                </td>
                <td className="px-4 py-3 text-slate-600">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</td>
                <td className="px-4 py-3 text-slate-600">{i.technician || "-"}</td>
                <td className="px-4 py-3">
                  <span className="text-xs px-2 py-1 rounded bg-slate-100 text-slate-700">{i.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
