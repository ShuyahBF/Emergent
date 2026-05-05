import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Pencil, Trash2, X, Save, RefreshCw } from "lucide-react";

const STATUS = [
  { v: "pending", l: "En attente" },
  { v: "confirmed", l: "Confirmé" },
  { v: "completed", l: "Terminé" },
  { v: "cancelled", l: "Annulé" },
];

export default function AdminAppointments() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/appointments");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const updateStatus = async (id, status) => {
    try {
      await apiClient.put(`/admin/appointments/${id}`, { status });
      toast.success("Statut mis à jour");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };
  const del = async (id) => {
    if (!window.confirm("Supprimer ce RDV ?")) return;
    try {
      await apiClient.delete(`/admin/appointments/${id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="space-y-6" data-testid="admin-appointments-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">Rendez-vous</h1>
          <p className="text-sm text-slate-500">Toutes les demandes de RDV (publiques et clients).</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
          data-testid="appt-refresh"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Client</th>
              <th className="text-left px-4 py-3">Sujet</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Durée</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Chargement…</td></tr>}
            {!loading && items.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucun RDV.</td></tr>}
            {items.map((a) => (
              <tr key={a.id} className="border-t border-slate-100" data-testid={`admin-appt-${a.id}`}>
                <td className="px-4 py-3">
                  <p className="font-medium">{a.name}</p>
                  <p className="text-xs text-slate-500">{a.email}</p>
                  {a.company && <p className="text-[11px] text-slate-400">{a.company}</p>}
                </td>
                <td className="px-4 py-3 text-slate-600">
                  {a.subject}
                  {a.message && <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-1">{a.message}</p>}
                </td>
                <td className="px-4 py-3 text-slate-600">
                  {new Date(a.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}
                </td>
                <td className="px-4 py-3 text-slate-600 text-xs">{a.duration_min || 30} min</td>
                <td className="px-4 py-3">
                  <select value={a.status} onChange={(e) => updateStatus(a.id, e.target.value)} className="text-xs rounded border border-slate-300 px-2 py-1" data-testid={`appt-status-${a.id}`}>
                    {STATUS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
                  </select>
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <button
                    onClick={() => setEditing(a)}
                    className="inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue text-xs mr-3"
                    data-testid={`edit-appt-${a.id}`}
                  >
                    <Pencil className="h-3.5 w-3.5" /> Modifier
                  </button>
                  <button
                    onClick={() => del(a.id)}
                    className="inline-flex items-center gap-1 text-rose-600 text-xs hover:underline"
                    data-testid={`del-appt-${a.id}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Supprimer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <EditAppointmentModal
          appt={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
          updateUrl={`/admin/appointments/${editing.id}`}
        />
      )}
    </div>
  );
}

export const EditAppointmentModal = ({ appt, onClose, onSaved, updateUrl }) => {
  const [form, setForm] = useState({
    subject: appt.subject || "",
    message: appt.message || "",
    scheduled_at_local: toLocalInput(appt.scheduled_at),
    duration_min: appt.duration_min || 30,
    status: appt.status || "pending",
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!form.subject.trim()) { toast.error("Sujet requis"); return; }
    if (!form.scheduled_at_local) { toast.error("Date requise"); return; }
    setSaving(true);
    try {
      const payload = {
        subject: form.subject,
        message: form.message || null,
        scheduled_at: new Date(form.scheduled_at_local).toISOString(),
        duration_min: Number(form.duration_min) || 30,
        status: form.status,
      };
      await apiClient.put(updateUrl, payload);
      toast.success("Rendez-vous mis à jour");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="appt-edit-modal"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">Modifier le rendez-vous</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Sujet *</label>
          <input
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="appt-edit-subject"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Message</label>
          <textarea
            value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })}
            rows={3}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="appt-edit-message"
          />
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Date et heure *</label>
            <input
              type="datetime-local"
              value={form.scheduled_at_local}
              onChange={(e) => setForm({ ...form, scheduled_at_local: e.target.value })}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="appt-edit-datetime"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Durée (min)</label>
            <input
              type="number"
              min="15"
              step="15"
              value={form.duration_min}
              onChange={(e) => setForm({ ...form, duration_min: e.target.value })}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="appt-edit-duration"
            />
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Statut</label>
          <select
            value={form.status}
            onChange={(e) => setForm({ ...form, status: e.target.value })}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="appt-edit-status"
          >
            {STATUS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
          </select>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
            data-testid="appt-edit-save"
          >
            <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// Convert ISO to value of <input type="datetime-local"> (local browser TZ)
function toLocalInput(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const off = d.getTimezoneOffset();
    const local = new Date(d.getTime() - off * 60000);
    return local.toISOString().slice(0, 16);
  } catch { return ""; }
}
