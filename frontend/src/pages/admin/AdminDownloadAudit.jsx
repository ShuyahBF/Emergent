// S029 — Audit journal for download-approval requests.
// Admin/superviseur only. Lists all download-request records with filters
// (status, free-text on requester/resource) and KPI counters.
import React, { useEffect, useState, useMemo } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  History, Search, RefreshCw, Loader2, ShieldCheck, X as XIcon, Clock, Ban, AlertCircle, CheckCircle2,
} from "lucide-react";

const STATUS_META = {
  pending:   { label: "En attente", icon: Clock,        cls: "bg-amber-100 text-amber-800 ring-amber-300" },
  approved:  { label: "Autorisé",   icon: CheckCircle2, cls: "bg-emerald-100 text-emerald-800 ring-emerald-300" },
  denied:    { label: "Refusé",     icon: Ban,          cls: "bg-rose-100 text-rose-800 ring-rose-300" },
  expired:   { label: "Expiré",     icon: AlertCircle,  cls: "bg-slate-100 text-slate-700 ring-slate-300" },
  cancelled: { label: "Annulé",     icon: XIcon,        cls: "bg-slate-100 text-slate-700 ring-slate-300" },
};

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  } catch { return iso; }
}

export default function AdminDownloadAudit() {
  const [data, setData] = useState({ items: [], counters: {} });
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/download-requests/admin/audit", {
        params: { status, q: q || undefined, limit: 500 },
      });
      setData(r.data || { items: [], counters: {} });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [status]);

  const counters = data.counters || {};
  const total = useMemo(
    () => Object.values(counters).reduce((a, b) => a + (b || 0), 0),
    [counters]
  );

  return (
    <div className="space-y-5" data-testid="admin-download-audit-page">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
            <History className="h-6 w-6 text-violet-600" />
            Journal d'audit — Téléchargements
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Suivi de toutes les demandes d'approbation de téléchargement (S025).
            Total des demandes : <strong>{total}</strong>
          </p>
        </div>
        <button onClick={load} disabled={loading} className="text-xs inline-flex items-center gap-1 px-3 py-2 rounded-lg ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-50" data-testid="audit-refresh">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Rafraîchir
        </button>
      </header>

      {/* KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2" data-testid="audit-kpi-cards">
        {Object.entries(STATUS_META).map(([k, m]) => {
          const Icon = m.icon;
          const v = counters[k] || 0;
          return (
            <button
              key={k}
              onClick={() => setStatus(k)}
              className={`rounded-xl p-3 text-left ring-1 transition ${status === k ? "ring-violet-500 shadow" : "ring-slate-200"} ${m.cls.replace(/ring-[a-z-]+/g, "")} hover:scale-[1.01]`}
              data-testid={`audit-kpi-${k}`}
            >
              <p className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest font-semibold">
                <Icon className="h-3 w-3" /> {m.label}
              </p>
              <p className="text-2xl font-display font-bold mt-1 tabular-nums">{v}</p>
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-2 flex-wrap" data-testid="audit-filters">
        <button
          onClick={() => setStatus("all")}
          className={`text-xs px-3 py-1.5 rounded-lg ring-1 ${status === "all" ? "bg-violet-600 text-white ring-violet-700" : "bg-white ring-slate-200 hover:bg-slate-50"}`}
          data-testid="audit-filter-all"
        >
          Tout ({total})
        </button>
        <div className="relative flex-1 max-w-xs">
          <Search className="h-3.5 w-3.5 absolute left-2.5 top-2 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") load(); }}
            placeholder="Rechercher (demandeur, document)…"
            className="w-full pl-8 pr-2 py-1.5 rounded-lg ring-1 ring-slate-300 text-xs bg-white"
            data-testid="audit-search-input"
          />
        </div>
        <button onClick={load} disabled={loading} className="text-xs px-3 py-1.5 rounded-lg bg-sawali-blue text-white" data-testid="audit-search-button">
          Filtrer
        </button>
      </div>

      <div className="rounded-2xl ring-1 ring-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm" data-testid="audit-table">
          <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">Date</th>
              <th className="text-left px-3 py-2">Demandeur</th>
              <th className="text-left px-3 py-2">Document</th>
              <th className="text-left px-3 py-2">Statut</th>
              <th className="text-left px-3 py-2">Décidé</th>
              <th className="text-left px-3 py-2">Via</th>
              <th className="text-left px-3 py-2">N° approbateur</th>
              <th className="text-left px-3 py-2">Envoi WA</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-500 text-xs">Chargement…</td></tr>
            )}
            {!loading && data.items.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400 italic text-xs" data-testid="audit-empty">
                Aucune demande pour ce filtre.
              </td></tr>
            )}
            {!loading && data.items.map((it) => {
              const m = STATUS_META[it.status] || { label: it.status, cls: "" };
              const Icon = m.icon || ShieldCheck;
              return (
                <tr key={it.token} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`audit-row-${it.token}`}>
                  <td className="px-3 py-2 text-xs text-slate-600 tabular-nums whitespace-nowrap">{fmtDate(it.created_at)}</td>
                  <td className="px-3 py-2 text-xs">
                    <p className="font-medium text-slate-800">{it.requester_name || "—"}</p>
                    <p className="text-[10px] text-slate-400">{it.requester_email || ""}</p>
                  </td>
                  <td className="px-3 py-2 text-xs max-w-xs truncate" title={it.resource_label}>{it.resource_label || "—"}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ring-1 ${m.cls}`}>
                      <Icon className="h-2.5 w-2.5" /> {m.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-600 tabular-nums whitespace-nowrap">{fmtDate(it.decided_at)}</td>
                  <td className="px-3 py-2 text-[10px] text-slate-500">
                    {it.decided_via === "template_button" ? "🔘 Bouton" :
                     it.decided_via === "magic_link" ? "🔗 Lien magique" :
                     it.decided_via === "admin_override" ? "⚡ Admin" : "—"}
                  </td>
                  <td className="px-3 py-2 text-[10px] text-slate-500 font-mono">{it.decided_by_phone || "—"}</td>
                  <td className="px-3 py-2 text-[10px]">
                    {it.wa_send_status === "template_sent" || it.wa_send_status === "text_sent" ? (
                      <span className="text-emerald-700">✓ {it.wa_send_status === "template_sent" ? "Template" : "Texte"}</span>
                    ) : it.wa_send_status ? (
                      <span className="text-rose-600" title={it.wa_send_error || ""}>✗ {it.wa_send_status}</span>
                    ) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-slate-400 text-center">
        {data.items.length} ligne{data.items.length > 1 ? "s" : ""} · Maximum 500 affichées · Demandes expirées automatiquement après 24 h
      </p>
    </div>
  );
}
