import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { RefreshCw, BarChart3, MessageCircle, Sparkles, CreditCard, Download, Activity, AlertTriangle } from "lucide-react";
import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";

/*
  Admin → Usage Dashboard
  Consolidates consumption (WhatsApp + AI summaries) per client over N days
  for billing & heavy-user detection. Backed by /admin/usage/summary.
*/
const PERIOD_OPTIONS = [
  { days: 7, label: "7 j" },
  { days: 30, label: "30 j" },
  { days: 90, label: "90 j" },
  { days: 180, label: "6 mois" },
];

export default function AdminUsage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState("wa_cost");
  const [dir, setDir] = useState("desc");

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/usage/summary", { params: { days } });
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [days]);

  const sorted = useMemo(() => {
    if (!data) return [];
    const out = [...(data.per_client || [])];
    out.sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      if (typeof va === "number") return dir === "asc" ? va - vb : vb - va;
      return dir === "asc"
        ? String(va || "").localeCompare(String(vb || ""))
        : String(vb || "").localeCompare(String(va || ""));
    });
    return out;
  }, [data, sortKey, dir]);

  const toggleSort = (k) => {
    if (sortKey === k) setDir(dir === "asc" ? "desc" : "asc");
    else { setSortKey(k); setDir("desc"); }
  };

  const exportCsv = () => {
    if (!data?.per_client) return;
    const rows = [[
      "Client", "Société", "WA envoyés OK", "WA envoyés KO", "WA reçus",
      "Coût unitaire", "Devise", "Coût WA", "Synthèses IA",
      "WA activé", "SMS activé", "IA activé", "Paiements activé",
    ]];
    data.per_client.forEach((r) => {
      rows.push([
        r.full_name || "",
        r.company || "",
        r.wa_sent_ok,
        r.wa_sent_ko,
        r.wa_inbound,
        r.wa_unit_cost,
        r.wa_currency,
        r.wa_cost,
        r.ai_summaries,
        r.features?.whatsapp ? "oui" : "non",
        r.features?.sms ? "oui" : "non",
        r.features?.ai ? "oui" : "non",
        r.features?.payments ? "oui" : "non",
      ]);
    });
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(";")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `sawali-usage-${days}d-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading && !data) return <p className="p-6 text-slate-500">Chargement…</p>;
  if (!data) return null;
  const { totals = {}, daily_series = [] } = data;

  return (
    <div className="space-y-6 p-6" data-testid="admin-usage-page">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
            <BarChart3 className="h-6 w-6 text-sawali-blue" /> Tableau de bord — Usage & Facturation
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Consommation des services facturables (WhatsApp, IA, paiements) sur les {data.period_days} derniers jours.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="inline-flex rounded-lg ring-1 ring-slate-200 p-0.5 bg-white">
            {PERIOD_OPTIONS.map((p) => (
              <button
                key={p.days}
                onClick={() => setDays(p.days)}
                className={`px-3 py-1.5 text-xs rounded ${days === p.days ? "bg-sawali-blue text-white" : "text-slate-600 hover:bg-slate-100"}`}
                data-testid={`usage-period-${p.days}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            onClick={load}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50"
            data-testid="usage-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button
            onClick={exportCsv}
            className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 text-white px-3 py-1.5 text-sm hover:bg-emerald-700"
            data-testid="usage-export"
          >
            <Download className="h-4 w-4" /> CSV
          </button>
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard icon={MessageCircle} color="emerald" label="WA envoyés" value={totals.wa_sent_ok || 0} subtitle={`${totals.wa_sent_ko || 0} échec(s)`} testid="kpi-wa-sent" />
        <KpiCard icon={Activity} color="sky" label="WA reçus" value={totals.wa_inbound || 0} subtitle={`${totals.wa_total || 0} trafic total`} testid="kpi-wa-inbound" />
        <KpiCard icon={Sparkles} color="fuchsia" label="Synthèses IA" value={totals.ai_count || 0} subtitle="Période entière" testid="kpi-ai-count" />
        <KpiCard icon={CreditCard} color="amber" label="Coût WA estimé" value={(totals.wa_cost || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} subtitle={data.per_client?.[0]?.wa_currency || "XOF"} testid="kpi-wa-cost" />
      </div>

      {/* Chart */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-700 inline-flex items-center gap-1.5">
            <BarChart3 className="h-4 w-4 text-sawali-blue" /> Activité quotidienne
          </h2>
          <span className="text-[10px] text-slate-400">{daily_series.length} jours</span>
        </div>
        <div className="w-full h-64" data-testid="usage-daily-chart">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={daily_series}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip
                formatter={(v, n) => [v, n === "wa" ? "WhatsApp envoyés" : "Synthèses IA"]}
                labelFormatter={(l) => `Jour ${l}`}
              />
              <Legend formatter={(v) => (v === "wa" ? "WhatsApp envoyés" : "Synthèses IA")} />
              <Bar dataKey="wa" stackId="a" fill="#10b981" />
              <Bar dataKey="ai" stackId="a" fill="#c026d3" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Per-client table */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-700">Détails par client ({sorted.length})</h2>
          {sorted.length === 0 && <span className="text-[11px] text-amber-700 inline-flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> Aucun client</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
              <tr>
                <Th k="full_name" sortKey={sortKey} dir={dir} onSort={toggleSort}>Client</Th>
                <Th k="company" sortKey={sortKey} dir={dir} onSort={toggleSort}>Société</Th>
                <Th k="wa_sent_ok" sortKey={sortKey} dir={dir} onSort={toggleSort} right>WA ✓</Th>
                <Th k="wa_sent_ko" sortKey={sortKey} dir={dir} onSort={toggleSort} right>WA ✗</Th>
                <Th k="wa_inbound" sortKey={sortKey} dir={dir} onSort={toggleSort} right>WA ↓</Th>
                <Th k="wa_cost" sortKey={sortKey} dir={dir} onSort={toggleSort} right>Coût WA</Th>
                <Th k="ai_summaries" sortKey={sortKey} dir={dir} onSort={toggleSort} right>IA</Th>
                <th className="text-center px-3 py-2 w-32">Actives</th>
                <th className="text-right px-3 py-2 w-16"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.client_id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`usage-row-${c.client_id}`}>
                  <td className="px-3 py-2 font-medium text-slate-800">{c.full_name || "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{c.company || "—"}</td>
                  <td className="px-3 py-2 text-right text-emerald-700 font-mono">{c.wa_sent_ok}</td>
                  <td className="px-3 py-2 text-right text-rose-600 font-mono">{c.wa_sent_ko}</td>
                  <td className="px-3 py-2 text-right text-slate-700 font-mono">{c.wa_inbound}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {(c.wa_cost || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} <span className="text-[10px] text-slate-400">{c.wa_currency}</span>
                  </td>
                  <td className="px-3 py-2 text-right text-fuchsia-700 font-mono">{c.ai_summaries}</td>
                  <td className="px-3 py-2 text-center">
                    <div className="inline-flex gap-1" title="Fonctionnalités actives">
                      <Dot on={c.features?.whatsapp} color="emerald" label="W" />
                      <Dot on={c.features?.sms} color="sky" label="S" />
                      <Dot on={c.features?.ai} color="fuchsia" label="I" />
                      <Dot on={c.features?.payments} color="amber" label="P" />
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link to={`/admin/clients/${c.client_id}/timeline`} className="text-xs text-sawali-blue hover:underline">Voir</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const KpiCard = ({ icon: Icon, color, label, value, subtitle, testid }) => (
  <div className={`rounded-xl ring-1 ring-${color}-200 bg-${color}-50 p-4`} data-testid={testid}>
    <div className="flex items-center justify-between mb-2">
      <span className={`text-[10px] uppercase tracking-wider font-semibold text-${color}-700`}>{label}</span>
      <Icon className={`h-4 w-4 text-${color}-600`} />
    </div>
    <p className="text-2xl font-display font-bold text-slate-900">{value}</p>
    <p className="text-[11px] text-slate-500 mt-0.5">{subtitle}</p>
  </div>
);

const Th = ({ k, sortKey, dir, onSort, children, right }) => (
  <th
    onClick={() => onSort(k)}
    className={`${right ? "text-right" : "text-left"} px-3 py-2 cursor-pointer select-none hover:text-slate-800`}
  >
    {children}
    {sortKey === k ? <span className="ml-0.5 text-slate-400">{dir === "asc" ? "▲" : "▼"}</span> : null}
  </th>
);

const Dot = ({ on, color, label }) => (
  <span
    className={`h-5 w-5 rounded-full flex items-center justify-center text-[9px] font-bold ${
      on ? `bg-${color}-500 text-white` : "bg-slate-200 text-slate-400"
    }`}
    title={on ? "Activé" : "Désactivé"}
  >
    {label}
  </span>
);
