import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Plus, Trash2, Edit, X } from "lucide-react";
import { toast } from "sonner";

const empty = { client_id: "", name: "", email: "", role: "", department: "", status: "active" };

export default function AdminTrackedUsers() {
  const [items, setItems] = useState([]);
  const [clients, setClients] = useState([]);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);

  const load = () => apiClient.get("/admin/tracked-users").then((r) => setItems(r.data));
  useEffect(() => {
    load().catch(() => {});
    apiClient.get("/admin/clients").then((r) => setClients(r.data));
  }, []);
  const open = (it = null) => { setEditing(it); setForm(it ? { ...empty, ...it } : empty); };
  const close = () => { setEditing(null); setForm(empty); };
  const submit = async (e) => {
    e.preventDefault();
    try {
      if (editing?.id) await apiClient.put(`/admin/tracked-users/${editing.id}`, form);
      else await apiClient.post("/admin/tracked-users", form);
      toast.success("Enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  const del = async (id) => { if (!window.confirm("Supprimer ?")) return; await apiClient.delete(`/admin/tracked-users/${id}`); await load(); };
  const cName = (id) => clients.find((c) => c.id === id)?.full_name || id;

  return (
    <div className="space-y-6" data-testid="admin-tracked-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div><h1 className="text-2xl font-display font-bold">Utilisateurs suivis (par client)</h1></div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm" data-testid="new-tracked-btn">
          <Plus className="h-4 w-4" /> Nouvel utilisateur
        </button>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr><th className="text-left px-4 py-3">Client</th><th className="text-left px-4 py-3">Nom</th><th className="text-left px-4 py-3">Email</th><th className="text-left px-4 py-3">Rôle</th><th className="text-left px-4 py-3">Statut</th><th className="text-right px-4 py-3">Actions</th></tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucun utilisateur.</td></tr>}
            {items.map((u) => (
              <tr key={u.id} className="border-t border-slate-100">
                <td className="px-4 py-3">{cName(u.client_id)}</td>
                <td className="px-4 py-3">{u.name}</td>
                <td className="px-4 py-3 text-slate-600">{u.email || "-"}</td>
                <td className="px-4 py-3 text-slate-600">{u.role || "-"}</td>
                <td className="px-4 py-3">{u.status}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => open(u)} className="text-slate-500 mr-3"><Edit className="h-4 w-4 inline" /></button>
                  <button onClick={() => del(u.id)} className="text-rose-600"><Trash2 className="h-4 w-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier" : "Nouvel utilisateur suivi"}</h3>
              <button onClick={close}><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3">
              <div>
                <label className="block text-xs font-semibold mb-1">Client *</label>
                <select required value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="">— Sélectionner —</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
                </select>
              </div>
              {[["name", "Nom *", true], ["email", "Email"], ["role", "Rôle"], ["department", "Service"]].map(([k, l, req]) => (
                <div key={k}>
                  <label className="block text-xs font-semibold mb-1">{l}</label>
                  <input required={req} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
                </div>
              ))}
              <div>
                <label className="block text-xs font-semibold mb-1">Statut</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm">
                  <option value="active">Actif</option><option value="inactive">Inactif</option>
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
