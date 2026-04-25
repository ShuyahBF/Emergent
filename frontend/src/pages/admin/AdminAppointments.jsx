import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

const STATUS = [
  { v: "pending", l: "En attente" },
  { v: "confirmed", l: "Confirmé" },
  { v: "completed", l: "Terminé" },
  { v: "cancelled", l: "Annulé" },
];

export default function AdminAppointments() {
  const [items, setItems] = useState([]);
  const load = () => apiClient.get("/admin/appointments").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const updateStatus = async (id, status) => {
    await apiClient.put(`/admin/appointments/${id}`, { status });
    toast.success("Statut mis à jour");
    await load();
  };
  const del = async (id) => {
    if (!window.confirm("Supprimer ce RDV ?")) return;
    await apiClient.delete(`/admin/appointments/${id}`);
    toast.success("Supprimé"); await load();
  };

  return (
    <div className="space-y-6" data-testid="admin-appointments-page">
      <div>
        <h1 className="text-2xl font-display font-bold">Rendez-vous</h1>
        <p className="text-sm text-slate-500">Toutes les demandes de RDV (publiques et clients).</p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Sujet</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-500">Aucun RDV.</td></tr>}
            {items.map((a) => (
              <tr key={a.id} className="border-t border-slate-100" data-testid={`admin-appt-${a.id}`}>
                <td className="px-4 py-3">
                  <p className="font-medium">{a.name}</p>
                  <p className="text-xs text-slate-500">{a.email}</p>
                </td>
                <td className="px-4 py-3 text-slate-600">{a.subject}</td>
                <td className="px-4 py-3 text-slate-600">{new Date(a.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</td>
                <td className="px-4 py-3">
                  <select value={a.status} onChange={(e) => updateStatus(a.id, e.target.value)} className="text-xs rounded border border-slate-300 px-2 py-1" data-testid={`appt-status-${a.id}`}>
                    {STATUS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
                  </select>
                </td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => del(a.id)} className="text-rose-600 text-xs hover:underline" data-testid={`del-appt-${a.id}`}>Supprimer</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
