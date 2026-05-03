import React, { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  ArrowLeft, Calendar, Wrench, MessageCircle, FileText, Folder, RefreshCw, Mail, Phone, MapPin, Building, Filter, Activity, StickyNote, ListTodo, Plus, Trash2, Bell, CheckSquare, Square,
} from "lucide-react";

/*
  Admin → Fiche client → Timeline CRM unifiée
  Agrège RDV, interventions, WhatsApp, formulaires, documents sur une seule frise.
*/
const TYPE_META = {
  appointment: { label: "RDV", icon: Calendar, color: "bg-indigo-500" },
  intervention: { label: "Intervention", icon: Wrench, color: "bg-orange-500" },
  whatsapp: { label: "WhatsApp", icon: MessageCircle, color: "bg-emerald-500" },
  form: { label: "Formulaire", icon: FileText, color: "bg-sky-500" },
  document: { label: "Document", icon: Folder, color: "bg-slate-500" },
  note: { label: "Note", icon: StickyNote, color: "bg-amber-500" },
  task: { label: "Tâche", icon: ListTodo, color: "bg-fuchsia-500" },
};

export default function AdminClientTimeline() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [notes, setNotes] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTypes, setActiveTypes] = useState(
    new Set(["appointment", "intervention", "whatsapp", "form", "document", "note", "task"])
  );

  const load = async () => {
    setLoading(true);
    try {
      const [tl, ns, ts] = await Promise.all([
        apiClient.get(`/admin/clients/${id}/timeline`, { params: { limit: 300 } }),
        apiClient.get(`/admin/clients/${id}/notes`),
        apiClient.get(`/admin/clients/${id}/tasks`),
      ]);
      setData(tl.data);
      setNotes(ns.data || []);
      setTasks(ts.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);

  const toggleType = (t) => {
    setActiveTypes((s) => {
      const next = new Set(s);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  const filtered = useMemo(
    () => (data?.events || []).filter((e) => activeTypes.has(e.type)),
    [data, activeTypes]
  );

  // Group by month for visual segmentation
  const grouped = useMemo(() => {
    const out = {};
    filtered.forEach((e) => {
      const d = e.ts ? new Date(e.ts) : null;
      const key = d && !isNaN(d) ? `${d.toLocaleString("fr-FR", { month: "long", year: "numeric" })}` : "Sans date";
      if (!out[key]) out[key] = [];
      out[key].push(e);
    });
    return out;
  }, [filtered]);

  if (loading || !data) {
    return (
      <div className="text-center text-slate-500 py-20" data-testid="client-timeline-loading">
        Chargement…
      </div>
    );
  }

  const c = data.client;

  return (
    <div className="max-w-6xl space-y-6" data-testid="client-timeline-page">
      <Link
        to="/admin/clients"
        className="inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline"
        data-testid="timeline-back"
      >
        <ArrowLeft className="h-3 w-3" /> Retour aux clients
      </Link>

      {/* Client header */}
      <div className="rounded-xl border border-slate-200 bg-gradient-to-r from-slate-50 to-white p-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Fiche client</p>
            <h1 className="text-2xl font-display font-bold flex items-center gap-2">
              <Activity className="h-5 w-5 text-sawali-blue" />
              {c.company || c.full_name || "—"}
            </h1>
            <p className="text-sm text-slate-500 mt-1">{c.full_name && c.company ? c.full_name : ""}</p>
          </div>
          <button
            onClick={load}
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="timeline-refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Rafraîchir
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-xs text-slate-700">
          <Info icon={Mail} value={c.email} />
          <Info icon={Phone} value={c.phone} />
          <Info icon={Building} value={c.client_code} />
          <Info icon={MapPin} value={[c.city, c.country].filter(Boolean).join(", ") || null} />
        </div>
      </div>

      {/* Type filters with counts */}
      <div className="flex items-center gap-2 flex-wrap">
        <Filter className="h-4 w-4 text-slate-400" />
        {Object.entries(TYPE_META).map(([t, meta]) => {
          const Icon = meta.icon;
          const count = data.counts?.[t] || 0;
          const active = activeTypes.has(t);
          return (
            <button
              key={t}
              onClick={() => toggleType(t)}
              className={`inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border transition ${
                active
                  ? `${meta.color} text-white border-transparent`
                  : "bg-white text-slate-600 border-slate-300 hover:bg-slate-50"
              }`}
              data-testid={`timeline-filter-${t}`}
            >
              <Icon className="h-3 w-3" /> {meta.label}
              <span className={`ml-1 text-[10px] ${active ? "bg-white/30 text-white" : "bg-slate-100 text-slate-500"} px-1.5 rounded`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Notes & Tasks panels */}
      <div className="grid lg:grid-cols-2 gap-4">
        <NotesPanel clientId={id} notes={notes} onChange={load} />
        <TasksPanel clientId={id} tasks={tasks} onChange={load} />
      </div>

      {/* Timeline */}
      {filtered.length === 0 ? (
        <div className="text-center text-slate-400 py-16 italic text-sm border border-dashed border-slate-200 rounded-xl">
          Aucun événement pour ce client {activeTypes.size < 5 ? "(filtres actifs)" : ""}.
        </div>
      ) : (
        <div className="space-y-6" data-testid="timeline-list">
          {Object.entries(grouped).map(([monthLabel, events]) => (
            <div key={monthLabel}>
              <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-3 sticky top-0 bg-white py-1">
                {monthLabel} <span className="text-slate-400">({events.length})</span>
              </h3>
              <div className="relative pl-8">
                {/* vertical line */}
                <div className="absolute left-3 top-1 bottom-1 w-px bg-slate-200" />
                <div className="space-y-3">
                  {events.map((e) => <TimelineCard key={`${e.type}-${e.id}`} event={e} />)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TimelineCard({ event }) {
  const meta = TYPE_META[event.type] || TYPE_META.document;
  const Icon = meta.icon;
  const ts = event.ts ? new Date(event.ts) : null;
  const tsLabel = ts && !isNaN(ts)
    ? ts.toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <div className="relative" data-testid={`timeline-event-${event.type}-${event.id}`}>
      <span
        className={`absolute -left-8 top-2.5 h-6 w-6 rounded-full ${meta.color} text-white flex items-center justify-center shadow-sm`}
      >
        <Icon className="h-3 w-3" />
      </span>
      <div className="rounded-lg border border-slate-200 bg-white p-3 hover:shadow-sm transition">
        <div className="flex items-center justify-between gap-3 mb-1">
          <h4 className="text-sm font-medium text-slate-900 truncate">{event.title}</h4>
          <span className="text-[11px] text-slate-400 shrink-0">{tsLabel}</span>
        </div>
        <p className="text-xs text-slate-500">{event.summary}</p>
        {event.status && (
          <span className={`inline-block mt-1.5 text-[10px] px-1.5 py-0.5 rounded ${
            event.status === "ko" || event.status === "rejected" || event.status === "cancelled"
              ? "bg-rose-100 text-rose-700"
              : event.status === "ok" || event.status === "completed" || event.status === "approved"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-slate-100 text-slate-600"
          }`}>
            {event.status}
          </span>
        )}
      </div>
    </div>
  );
}

function Info({ icon: Icon, value }) {
  return (
    <div className="flex items-center gap-1.5 text-slate-600">
      <Icon className="h-3 w-3 text-slate-400" />
      <span className="truncate">{value || "—"}</span>
    </div>
  );
}

function NotesPanel({ clientId, notes, onChange }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  const create = async () => {
    if (!text.trim()) return toast.error("Note vide");
    setSaving(true);
    try {
      await apiClient.post(`/admin/clients/${clientId}/notes`, { text });
      setText("");
      toast.success("Note ajoutée");
      await onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (nid) => {
    if (!window.confirm("Supprimer cette note ?")) return;
    try {
      await apiClient.delete(`/admin/clients/${clientId}/notes/${nid}`);
      toast.success("Supprimée");
      await onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/30 p-4" data-testid="notes-panel">
      <h3 className="text-sm font-display font-bold flex items-center gap-2 mb-3">
        <StickyNote className="h-4 w-4 text-amber-600" /> Notes ({notes.length})
      </h3>
      <div className="space-y-2 mb-3 max-h-56 overflow-y-auto pr-1">
        {notes.length === 0 ? (
          <p className="text-xs text-slate-400 italic">Aucune note. Ajoutez-en une ci-dessous.</p>
        ) : notes.map((n) => (
          <div key={n.id} className="rounded-lg bg-white border border-amber-100 p-2 group" data-testid={`note-${n.id}`}>
            <p className="text-xs text-slate-700 whitespace-pre-line">{n.text}</p>
            <div className="flex items-center justify-between mt-1.5">
              <span className="text-[10px] text-slate-400">
                {n.author_label} · {n.created_at ? new Date(n.created_at).toLocaleString("fr-FR") : "—"}
              </span>
              <button
                onClick={() => remove(n.id)}
                className="text-slate-400 hover:text-rose-600 transition opacity-60 group-hover:opacity-100"
                data-testid={`note-delete-${n.id}`}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          placeholder="Ex: Le client a appelé pour un suivi technique"
          className="flex-1 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs"
          data-testid="note-text-input"
        />
        <button
          onClick={create}
          disabled={saving}
          className="self-end inline-flex items-center gap-1 rounded-lg bg-amber-500 text-white px-3 py-2 text-xs hover:bg-amber-600 disabled:opacity-50"
          data-testid="note-add-btn"
        >
          <Plus className="h-3.5 w-3.5" /> Ajouter
        </button>
      </div>
    </div>
  );
}

function TasksPanel({ clientId, tasks, onChange }) {
  const [form, setForm] = useState({ title: "", due_date: "", due_time: "", remind: false });
  const [saving, setSaving] = useState(false);

  const create = async () => {
    if (!form.title.trim()) return toast.error("Titre requis");
    let due_at = null;
    if (form.due_date) {
      const local = new Date(`${form.due_date}T${form.due_time || "09:00"}`);
      if (isNaN(local.getTime())) return toast.error("Date invalide");
      due_at = local.toISOString();
    }
    setSaving(true);
    try {
      await apiClient.post(`/admin/clients/${clientId}/tasks`, {
        title: form.title,
        due_at,
        remind_via_whatsapp: form.remind,
      });
      setForm({ title: "", due_date: "", due_time: "", remind: false });
      toast.success("Tâche ajoutée");
      await onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (t) => {
    try {
      await apiClient.put(`/admin/clients/${clientId}/tasks/${t.id}`, {
        status: t.status === "done" ? "open" : "done",
      });
      await onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (tid) => {
    if (!window.confirm("Supprimer cette tâche ?")) return;
    try {
      await apiClient.delete(`/admin/clients/${clientId}/tasks/${tid}`);
      toast.success("Supprimée");
      await onChange();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const sortedTasks = [...tasks].sort((a, b) => {
    if (a.status !== b.status) return a.status === "done" ? 1 : -1;  // Open first
    return (a.due_at || "z") < (b.due_at || "z") ? -1 : 1;
  });

  return (
    <div className="rounded-xl border border-fuchsia-200 bg-fuchsia-50/30 p-4" data-testid="tasks-panel">
      <h3 className="text-sm font-display font-bold flex items-center gap-2 mb-3">
        <ListTodo className="h-4 w-4 text-fuchsia-600" /> Tâches ({tasks.filter((t) => t.status !== "done").length} ouverte(s))
      </h3>
      <div className="space-y-1.5 mb-3 max-h-56 overflow-y-auto pr-1">
        {sortedTasks.length === 0 ? (
          <p className="text-xs text-slate-400 italic">Aucune tâche.</p>
        ) : sortedTasks.map((t) => {
          const isDone = t.status === "done";
          const overdue = !isDone && t.due_at && new Date(t.due_at) < new Date();
          return (
            <div
              key={t.id}
              className={`rounded-lg bg-white border p-2 group ${
                overdue ? "border-rose-300 bg-rose-50/50" : "border-fuchsia-100"
              }`}
              data-testid={`task-${t.id}`}
            >
              <div className="flex items-start gap-2">
                <button
                  onClick={() => toggle(t)}
                  className={isDone ? "text-emerald-600" : "text-slate-400 hover:text-fuchsia-600"}
                  data-testid={`task-toggle-${t.id}`}
                  title={isDone ? "Marquer à faire" : "Marquer terminée"}
                >
                  {isDone ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                </button>
                <div className="flex-1 min-w-0">
                  <p className={`text-xs ${isDone ? "line-through text-slate-400" : "text-slate-800"}`}>{t.title}</p>
                  <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
                    {t.due_at && (
                      <span className={overdue ? "text-rose-600 font-semibold" : ""}>
                        ⏰ {new Date(t.due_at).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                      </span>
                    )}
                    {t.remind_via_whatsapp && (
                      <span className="text-emerald-600 inline-flex items-center gap-0.5">
                        <Bell className="h-2.5 w-2.5" /> WhatsApp
                      </span>
                    )}
                    {t.author_label && <span className="text-slate-400">par {t.author_label}</span>}
                  </div>
                </div>
                <button
                  onClick={() => remove(t.id)}
                  className="text-slate-400 hover:text-rose-600 transition opacity-60 group-hover:opacity-100"
                  data-testid={`task-delete-${t.id}`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <div className="space-y-2">
        <input
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Ex: Rappeler la semaine prochaine"
          className="w-full rounded-lg border border-fuchsia-300 bg-white px-3 py-2 text-xs"
          data-testid="task-title-input"
        />
        <div className="grid grid-cols-2 gap-2">
          <input
            type="date"
            value={form.due_date}
            onChange={(e) => setForm({ ...form, due_date: e.target.value })}
            className="rounded-lg border border-fuchsia-300 bg-white px-2 py-1.5 text-xs"
            data-testid="task-due-date"
          />
          <input
            type="time"
            value={form.due_time}
            onChange={(e) => setForm({ ...form, due_time: e.target.value })}
            className="rounded-lg border border-fuchsia-300 bg-white px-2 py-1.5 text-xs"
            data-testid="task-due-time"
          />
        </div>
        <div className="flex items-center justify-between">
          <label className="inline-flex items-center gap-1.5 text-xs text-slate-700" data-testid="task-remind-toggle">
            <input
              type="checkbox"
              checked={form.remind}
              onChange={(e) => setForm({ ...form, remind: e.target.checked })}
              className="accent-emerald-600"
            />
            <Bell className="h-3 w-3 text-emerald-600" /> Rappel WhatsApp 1h avant
          </label>
          <button
            onClick={create}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded-lg bg-fuchsia-600 text-white px-3 py-1.5 text-xs hover:bg-fuchsia-700 disabled:opacity-50"
            data-testid="task-add-btn"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter
          </button>
        </div>
      </div>
    </div>
  );
}
