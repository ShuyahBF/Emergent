import React, { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  ArrowLeft, Calendar, Wrench, MessageCircle, FileText, Folder, RefreshCw, Mail, Phone, MapPin, Building, Filter, Activity,
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
};

export default function AdminClientTimeline() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTypes, setActiveTypes] = useState(
    new Set(["appointment", "intervention", "whatsapp", "form", "document"])
  );

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/clients/${id}/timeline`, { params: { limit: 300 } });
      setData(r.data);
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
