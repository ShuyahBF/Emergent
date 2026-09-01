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
    // 2026-02 fork iter107 — Participants + reminder_minutes
    participants: appt.participants || [],
    reminder_minutes: appt.reminder_minutes ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [contacts, setContacts] = useState([]);
  const [contactQuery, setContactQuery] = useState("");

  useEffect(() => {
    apiClient.get("/me/contacts")
      .then((r) => setContacts(Array.isArray(r.data) ? r.data : (r.data?.items || [])))
      .catch(() => setContacts([]));
  }, []);

  const clientScopeContacts = React.useMemo(() => {
    // Only contacts of the same client as the appointment.
    if (!appt.client_id) return contacts;
    return contacts.filter((c) => c.client_id === appt.client_id || !c.client_id);
  }, [contacts, appt.client_id]);

  const filteredContacts = React.useMemo(() => {
    const q = contactQuery.trim().toLowerCase();
    const selectedIds = new Set(form.participants.map((p) => p.contact_id).filter(Boolean));
    return clientScopeContacts
      .filter((c) => !selectedIds.has(c.id))
      .filter((c) => !q || (c.name || "").toLowerCase().includes(q) || (c.phone || "").includes(q))
      .slice(0, 6);
  }, [clientScopeContacts, contactQuery, form.participants]);

  const addParticipant = (c) => {
    setForm((f) => ({
      ...f,
      participants: [...(f.participants || []), {
        contact_id: c.id,
        name: c.name || "",
        phone: c.phone || c.whatsapp || "",
      }],
    }));
    setContactQuery("");
  };

  const removeParticipant = (idx) => {
    setForm((f) => ({ ...f, participants: f.participants.filter((_, i) => i !== idx) }));
  };

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
        // 2026-02 fork iter107
        participants: form.participants || [],
        reminder_minutes: form.reminder_minutes === "" ? null : Math.max(1, Number(form.reminder_minutes) || 0),
      };
      await apiClient.put(updateUrl, payload);
      toast.success(payload.participants.length > 0
        ? `Rendez-vous mis à jour — WhatsApp envoyé aux ${payload.participants.length} participant(s).`
        : "Rendez-vous mis à jour");
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

        {/* 2026-02 fork iter107 — Reminder minutes */}
        <div>
          <label className="block text-xs font-semibold mb-1">
            Rappel WhatsApp (mn ou h avant le RDV) — laisser vide pour utiliser la valeur globale
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min="1"
              value={form.reminder_minutes ?? ""}
              onChange={(e) => setForm({ ...form, reminder_minutes: e.target.value })}
              placeholder="ex : 30 (mn) ou 60 (1h)"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="appt-edit-reminder-minutes"
            />
            <span className="text-xs text-slate-500 whitespace-nowrap">minutes</span>
          </div>
        </div>

        {/* 2026-02 fork iter107 — Participants picker */}
        <div className="rounded-lg border-2 border-teal-200 bg-teal-50/40 p-3 space-y-2" data-testid="appt-edit-participants">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-teal-900">👥 Participants</span>
            <span className="text-[10px] text-teal-700">
              — parmi les contacts du client lié{form.participants.length > 0 ? ` · ${form.participants.length} sélectionné(s)` : ""}
            </span>
          </div>
          {form.participants.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {form.participants.map((p, idx) => (
                <span
                  key={p.contact_id || `${p.name}-${idx}`}
                  className="inline-flex items-center gap-1 bg-white border border-teal-300 rounded-full px-2 py-0.5 text-xs"
                  data-testid={`appt-participant-${idx}`}
                >
                  <span className="font-medium text-teal-800">{p.name}</span>
                  {p.phone && <span className="text-[10px] text-slate-500 font-mono">({p.phone})</span>}
                  <button
                    onClick={() => removeParticipant(idx)}
                    className="text-slate-400 hover:text-rose-600 ml-0.5"
                    title="Retirer"
                    data-testid={`appt-participant-remove-${idx}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="relative">
            <input
              type="text"
              value={contactQuery}
              onChange={(e) => setContactQuery(e.target.value)}
              placeholder="Rechercher un contact (nom ou téléphone)…"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="appt-participant-search"
            />
            {contactQuery && filteredContacts.length > 0 && (
              <div className="absolute z-10 top-full mt-1 left-0 right-0 bg-white border border-slate-200 rounded-lg shadow-lg max-h-48 overflow-y-auto" data-testid="appt-participant-suggestions">
                {filteredContacts.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => addParticipant(c)}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-teal-50 flex items-center justify-between"
                    data-testid={`appt-participant-suggest-${c.id}`}
                  >
                    <span className="font-medium">{c.name}</span>
                    <span className="text-xs text-slate-500 font-mono">{c.phone || c.whatsapp || "—"}</span>
                  </button>
                ))}
              </div>
            )}
            {contactQuery && filteredContacts.length === 0 && (
              <p className="text-[11px] text-slate-500 mt-1" data-testid="appt-participant-empty">
                Aucun contact ne correspond dans le registre du client lié.
              </p>
            )}
          </div>
          <p className="text-[10px] text-teal-800 italic">
            Un modèle WhatsApp est envoyé à chaque participant sélectionné à la création / modification du RDV. Si la liste est vide, aucun WA n'est envoyé.
          </p>
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
