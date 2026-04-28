import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, Edit, X } from "lucide-react";
import { toast } from "sonner";

const empty = { client_id: "", title: "", description: "", status: "completed", intervention_date: "", technician: "", duration_hours: "" };

export default function AdminInterventions() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);

  const load = () => apiClient.get("/admin/interventions").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/clients").then((r) => setClients(r.data));
  }, []);

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it } : empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const submit = async (e) => {
    e.preventDefault();
    try {
      const payload = { ...form, duration_hours: form.duration_hours ? parseFloat(form.duration_hours) : null };
      if (editing?.id) await apiClient.put(`/admin/interventions/${editing.id}`, payload);
      else await apiClient.post("/admin/interventions", payload);
      toast.success("Intervention enregistrée"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ?")) return;
    await apiClient.delete(`/admin/interventions/${id}`);
    await load();
  };

  const clientName = (id) => clients.find((c) => c.id === id)?.full_name || id;

  return (
    <div className="space-y-6" data-testid="admin-interventions-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div><h1 className="text-2xl font-display font-bold">Interventions</h1></div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm" data-testid="new-intervention-btn">
          <Plus className="h-4 w-4" /> Nouvelle intervention
        </button>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">N°</th>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Titre</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-left px-4 py-3">Mis à jour</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">Aucune intervention.</td></tr>}
            {items.map((i) => (
              <tr key={i.id} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono text-xs text-slate-700">{i.intervention_number || "-"}</td>
                <td className="px-4 py-3">{clientName(i.client_id)}</td>
                <td className="px-4 py-3">{i.title}</td>
                <td className="px-4 py-3">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</td>
                <td className="px-4 py-3">{i.status}</td>
                <td className="px-4 py-3 text-slate-500 text-xs">{(i.updated_at || i.created_at) ? new Date(i.updated_at || i.created_at).toLocaleString("fr-FR") : "-"}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => open(i)} className="text-slate-500 mr-3"><Edit className="h-4 w-4 inline" /></button>
                  <button onClick={() => del(i.id)} className="text-rose-600"><Trash2 className="h-4 w-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-md max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{editing?.id ? `Modifier${editing?.intervention_number ? ` — ${editing.intervention_number}` : ""}` : "Nouvelle intervention"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3" data-testid="intervention-form">
              <div>
                <label className="block text-xs font-semibold mb-1">Client *</label>
                <select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="">— Sélectionner —</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.full_name} ({c.email})</option>)}
                </select>
              </div>
              <Input label="Titre *" value={form.title} onChange={(v) => setForm({ ...form, title: v })} required />
              <div>
                <label className="block text-xs font-semibold mb-1">Description</label>
                <textarea rows={3} value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
              </div>
              <Input label="Date *" type="date" value={form.intervention_date?.slice(0, 10) || ""} onChange={(v) => setForm({ ...form, intervention_date: v })} required />
              <Input label="Technicien" value={form.technician || ""} onChange={(v) => setForm({ ...form, technician: v })} />
              <Input label="Durée (h)" value={form.duration_hours || ""} onChange={(v) => setForm({ ...form, duration_hours: v })} />
              <div>
                <label className="block text-xs font-semibold mb-1">Statut</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  {["planned", "in_progress", "completed", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <button type="submit" className="w-full rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm">Enregistrer</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const Input = ({ label, type = "text", value, onChange, required }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input type={type} required={required} value={value} onChange={(e) => onChange(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
  </div>
);
