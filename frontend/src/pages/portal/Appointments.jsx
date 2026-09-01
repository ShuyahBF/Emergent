import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Calendar, Plus, ArrowRight, Pencil, Trash2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { EditAppointmentModal } from "@/pages/admin/AdminAppointments";

const formatDate = (d) => d.toISOString().slice(0, 10);

// 2026-02 fork iter108 fix — FastAPI 422 renvoie `detail` sous forme d'ARRAY
// d'objets Pydantic ; rendre cet array directement dans <toast> fait planter
// React ('Objects are not valid as a React child'). Ce helper normalise
// n'importe quel format en string affichable.
function formatApiError(err, fallback = "Erreur") {
  const d = err?.response?.data?.detail;
  if (!d) return err?.message || fallback;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d.map((e) => {
      if (typeof e === "string") return e;
      const loc = Array.isArray(e?.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
      return loc ? `${loc}: ${e?.msg || "invalide"}` : (e?.msg || "invalide");
    }).join(" • ");
  }
  return JSON.stringify(d);
}

export default function ClientAppointments() {
  const [items, setItems] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [days, setDays] = useState([]);
  const [date, setDate] = useState(null);
  const [slots, setSlots] = useState([]);
  const [slot, setSlot] = useState(null);
  const [form, setForm] = useState({ subject: "", message: "", participants: "", reminder_minutes: 60 });
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = () => apiClient.get("/me/appointments").then((r) => setItems(r.data));
  useEffect(() => { load().catch(() => {}); }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer ce rendez-vous ?")) return;
    try {
      await apiClient.delete(`/me/appointments/${id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(formatApiError(err));
    }
  };

  useEffect(() => {
    if (!showForm) return;
    const list = [];
    const today = new Date();
    for (let i = 0; i < 14; i++) list.push(new Date(today.getTime() + i * 86400000));
    setDays(list);
    setDate(formatDate(today));
  }, [showForm]);

  useEffect(() => {
    if (!date) return;
    apiClient.get(`/availability?date=${date}`).then((r) => setSlots(r.data.slots || [])).catch(() => setSlots([]));
  }, [date]);

  const submit = async (e) => {
    e.preventDefault();
    if (!slot) return toast.error("Choisissez un créneau");
    setLoading(true);
    try {
      // 2026-02 fork iter107 — Participants (téléphones séparés par virgule) + rappel_minutes
      const participants = (form.participants || "")
        .split(/[,;\n]/)
        .map((s) => s.trim())
        .filter(Boolean);
      const reminder = Number(form.reminder_minutes);
      const payload = {
        subject: form.subject,
        message: form.message,
        scheduled_at: slot.start,
        duration_min: 30,
      };
      if (participants.length > 0) payload.participants = participants;
      if (!Number.isNaN(reminder) && reminder > 0) payload.reminder_minutes = reminder;
      await apiClient.post("/me/appointments", payload);
      toast.success("Rendez-vous demandé");
      setShowForm(false);
      setForm({ subject: "", message: "", participants: "", reminder_minutes: 60 });
      setSlot(null);
      await load();
    } catch (err) {
      toast.error(formatApiError(err));
    } finally { setLoading(false); }
  };

  return (
    <div className="space-y-6" data-testid="client-appointments-page">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Mes rendez-vous</h1>
          <p className="text-sm text-slate-500">Suivez et planifiez vos rendez-vous avec notre équipe.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => load()} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm" data-testid="rdv-refresh">
            <RefreshCw className="h-4 w-4" /> Actualiser
          </button>
          {/* 2026-02 fork iter107 — Bouton Synchroniser Google Calendar */}
          <button
            onClick={async () => {
              try {
                const r = await apiClient.post("/me/appointments/gcal-sync");
                const d = r.data || {};
                toast.success(`Synchronisation réussie : ${d.inserted || 0} ajout(s), ${d.updated || 0} mise(s) à jour, ${d.deleted || 0} suppr.`);
                await load();
              } catch (err) {
                toast.error(formatApiError(err, "Google Calendar non configuré"));
              }
            }}
            className="inline-flex items-center gap-2 rounded-lg border border-teal-300 bg-teal-50 text-teal-700 hover:bg-teal-100 px-3 py-2 text-sm"
            data-testid="rdv-gcal-sync"
            title="Forcer la synchronisation manuelle avec Google Calendar"
          >
            <RefreshCw className="h-4 w-4" /> Synchroniser
          </button>
          <button onClick={() => setShowForm((v) => !v)} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="new-rdv-toggle">
            <Plus className="h-4 w-4" /> {showForm ? "Annuler" : "Nouveau rendez-vous"}
          </button>
        </div>
      </div>

      {showForm && (
        <form onSubmit={submit} className="rounded-xl border border-slate-200 bg-white p-6 space-y-4" data-testid="client-rdv-form">
          <div className="flex gap-2 overflow-x-auto pb-2">
            {days.map((d) => {
              const k = formatDate(d);
              const active = k === date;
              return (
                <button type="button" key={k} onClick={() => { setDate(k); setSlot(null); }}
                        className={`min-w-[80px] rounded-lg border px-3 py-2 text-center text-sm ${active ? "bg-sawali-blue text-white border-sawali-blue" : "border-slate-200 hover:bg-slate-50"}`}
                        data-testid={`portal-day-${k}`}>
                  {d.toLocaleDateString("fr-FR", { weekday: "short", day: "2-digit", month: "short" })}
                </button>
              );
            })}
          </div>
          <div>
            <p className="text-xs font-semibold text-slate-700 mb-2">Créneaux disponibles</p>
            {slots.length === 0 ? <p className="text-sm text-slate-500">Aucun créneau ce jour.</p> :
              <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
                {slots.map((s) => (
                  <button key={s.start} type="button" disabled={!s.available}
                          onClick={() => setSlot(s)}
                          className={`rounded-md border px-2 py-1.5 text-xs ${!s.available ? "text-slate-400 line-through" : slot?.start === s.start ? "bg-sawali-blue text-white border-sawali-blue" : "border-slate-200 hover:bg-slate-50"}`}
                          data-testid={`portal-slot-${s.start}`}>
                    {new Date(s.start).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                  </button>
                ))}
              </div>}
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Sujet *</label>
            <input required value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })}
                   className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="rdv-subject" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Message</label>
            <textarea rows={3} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="rdv-message" />
          </div>
          {/* 2026-02 fork iter107 — Participants (téléphones) + rappel personnalisable */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Participants — n° WhatsApp <span className="text-slate-400 font-normal">(séparés par virgule)</span>
              </label>
              <input
                value={form.participants}
                onChange={(e) => setForm({ ...form, participants: e.target.value })}
                placeholder="+22670000001, +22670000002"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="rdv-participants"
              />
              <p className="text-[10px] text-slate-500 mt-1">
                Chaque numéro reçoit une invitation WhatsApp à la création du RDV et un rappel automatique.
              </p>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Rappel avant le RDV
              </label>
              <select
                value={form.reminder_minutes}
                onChange={(e) => setForm({ ...form, reminder_minutes: Number(e.target.value) })}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm bg-white"
                data-testid="rdv-reminder-minutes"
              >
                <option value={0}>Aucun rappel</option>
                <option value={15}>15 minutes avant</option>
                <option value={30}>30 minutes avant</option>
                <option value={60}>1 heure avant</option>
                <option value={120}>2 heures avant</option>
                <option value={1440}>24 heures avant</option>
              </select>
            </div>
          </div>
          <button type="submit" disabled={loading} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50" data-testid="submit-rdv">
            {loading ? "Envoi..." : "Confirmer"} <ArrowRight className="h-4 w-4" />
          </button>
        </form>
      )}

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wider">
            <tr>
              <th className="text-left px-4 py-3">Sujet</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Statut</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-500">Aucun rendez-vous.</td></tr>}
            {items.map((a) => (
              <tr key={a.id} className="border-t border-slate-100" data-testid={`appt-row-${a.id}`}>
                <td className="px-4 py-3 font-medium text-slate-800">
                  {a.subject}
                  {a.message && <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-1">{a.message}</p>}
                </td>
                <td className="px-4 py-3 text-slate-600">{new Date(a.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</td>
                <td className="px-4 py-3"><StatusBadge s={a.status} /></td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {a.status !== "completed" && (
                    <>
                      <button
                        onClick={() => setEditing(a)}
                        className="inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue text-xs mr-3"
                        data-testid={`portal-appt-edit-${a.id}`}
                      >
                        <Pencil className="h-3.5 w-3.5" /> Modifier
                      </button>
                      <button
                        onClick={() => del(a.id)}
                        className="inline-flex items-center gap-1 text-rose-600 text-xs hover:underline"
                        data-testid={`portal-appt-delete-${a.id}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Supprimer
                      </button>
                    </>
                  )}
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
          updateUrl={`/me/appointments/${editing.id}`}
        />
      )}
    </div>
  );
}

const StatusBadge = ({ s }) => {
  const m = { pending: ["Attente", "bg-amber-100 text-amber-700"], confirmed: ["Confirmé", "bg-sky-100 text-sky-700"], cancelled: ["Annulé", "bg-rose-100 text-rose-700"], completed: ["Terminé", "bg-emerald-100 text-emerald-700"] };
  const [l, c] = m[s] || [s, "bg-slate-100 text-slate-700"];
  return <span className={`text-xs px-2 py-1 rounded ${c}`}>{l}</span>;
};
