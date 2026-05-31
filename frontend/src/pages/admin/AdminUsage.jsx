import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { RefreshCw, BarChart3, MessageCircle, Sparkles, CreditCard, Download, Activity, AlertTriangle, Send, Zap, ArrowRightLeft, Coins, Users, Eye, Building2, Trash2 } from "lucide-react";
import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import SmsProvidersBlock from "@/components/SmsProvidersBlock";
import VelocityChart from "@/components/VelocityChart";

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
  // Campaign Efficiency dashboard — quantifies WA-first strategy vs SMS
  const [campaign, setCampaign] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const [r, cR] = await Promise.all([
        apiClient.get("/admin/usage/summary", { params: { days } }),
        apiClient.get("/admin/campaign-efficiency", { params: { days } }).catch(() => ({ data: null })),
      ]);
      setData(r.data);
      setCampaign(cR.data);
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
      "Coût unitaire WA", "Devise", "Coût WA",
      "SMS envoyés OK", "SMS envoyés KO", "Coût unitaire SMS", "Coût SMS",
      "Synthèses IA",
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
        r.sms_sent_ok || 0,
        r.sms_sent_ko || 0,
        r.sms_unit_cost || 0,
        r.sms_cost || 0,
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
          <ResetUsageButton onDone={load} />
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard icon={MessageCircle} color="emerald" label="WA envoyés" value={totals.wa_sent_ok || 0} subtitle={`${totals.wa_sent_ko || 0} échec(s)`} testid="kpi-wa-sent" />
        <KpiCard icon={Activity} color="sky" label="WA reçus" value={totals.wa_inbound || 0} subtitle={`${totals.wa_total || 0} trafic total`} testid="kpi-wa-inbound" />
        <KpiCard icon={Send} color="indigo" label="SMS envoyés" value={totals.sms_sent_ok || 0} subtitle={`${totals.sms_sent_ko || 0} échec(s) • ${totals.sms_total || 0} tot.`} testid="kpi-sms-sent" />
        <KpiCard icon={CreditCard} color="amber" label="Coût total estimé" value={((totals.wa_cost || 0) + (totals.sms_cost || 0)).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} subtitle={`WA ${(totals.wa_cost || 0).toLocaleString("fr-FR")} • SMS ${(totals.sms_cost || 0).toLocaleString("fr-FR")} XOF`} testid="kpi-total-cost" />
      </div>

      {/* Iter34f — User activity card (last logins + top pages, filterable) */}
      <UserActivityCard />

      {/* Campaign Efficiency dashboard — quantifies WA-first strategy vs SMS */}
      {campaign && (
        <div className="rounded-xl ring-1 ring-emerald-200 bg-gradient-to-br from-emerald-50/60 via-white to-indigo-50/40 p-4" data-testid="campaign-efficiency-block">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-700 inline-flex items-center gap-2">
              <Zap className="h-4 w-4 text-emerald-600" /> Efficacité de campagne — stratégie WhatsApp-first
            </h2>
            <span className="text-[10px] text-slate-400">{campaign.period_days} jours</span>
          </div>
          <p className="text-[11px] text-slate-500 mb-3 max-w-3xl">
            Mesure du taux de délivrance WA vs SMS, du repli automatique en cas d'échec WA, et de l'économie générée
            par chaque message WhatsApp réussi (qui n'a pas eu besoin d'être envoyé en SMS payant).
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiCard
              icon={MessageCircle} color="emerald"
              label="Délivrance WA"
              value={`${campaign.wa.delivery_rate}%`}
              subtitle={`${campaign.wa.sent_ok}/${campaign.wa.total} envoyés`}
              testid="kpi-wa-delivery"
            />
            <KpiCard
              icon={Send} color="indigo"
              label="Délivrance SMS"
              value={`${campaign.sms.delivery_rate}%`}
              subtitle={`${campaign.sms.sent_ok}/${campaign.sms.total} envoyés`}
              testid="kpi-sms-delivery"
            />
            <KpiCard
              icon={ArrowRightLeft} color="amber"
              label="Repli SMS"
              value={`${campaign.fallback.success_rate}%`}
              subtitle={`${campaign.fallback.succeeded}/${campaign.fallback.triggered} repli OK • ${campaign.fallback.trigger_rate_on_wa_failures}% des échecs WA`}
              testid="kpi-fallback-rate"
            />
            <KpiCard
              icon={Coins} color="emerald"
              label="Économie estimée"
              value={`${(campaign.cost_savings.estimated_savings_xof || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} XOF`}
              subtitle={`${campaign.cost_savings.wa_success_count} WA × ${(campaign.cost_savings.sms_unit_cost_avg || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} XOF/SMS moy.`}
              testid="kpi-cost-savings"
            />
          </div>
          {campaign.daily?.length > 0 && (
            <div className="w-full h-56 mt-4" data-testid="campaign-daily-chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={campaign.daily.slice(-Math.min(30, campaign.daily.length))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="day" tick={{ fontSize: 9 }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip
                    formatter={(v, n) => [v, ({
                      wa_ok: "WA livrés", wa_ko: "WA échoués",
                      sms_ok: "SMS livrés", sms_ko: "SMS échoués",
                      fallback_ok: "Repli SMS livré",
                    })[n] || n]}
                    labelFormatter={(l) => `Jour ${l}`}
                  />
                  <Legend formatter={(v) => ({
                    wa_ok: "WA livrés", wa_ko: "WA échoués",
                    sms_ok: "SMS livrés", sms_ko: "SMS échoués",
                    fallback_ok: "Repli SMS livré",
                  })[v] || v} />
                  <Bar dataKey="wa_ok" stackId="a" fill="#10b981" />
                  <Bar dataKey="wa_ko" stackId="a" fill="#fb923c" />
                  <Bar dataKey="sms_ok" stackId="b" fill="#6366f1" />
                  <Bar dataKey="sms_ko" stackId="b" fill="#f43f5e" />
                  <Bar dataKey="fallback_ok" stackId="c" fill="#a78bfa" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* Per-provider breakdown (Iter38r-fix9p — enriched with latency, cost, last fail) */}
      <SmsProvidersBlock days={data.period_days || days} />

      {/* Iter38r-fix9p — Velocity chart (sawali-portal owner only) */}
      <VelocityChart />

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
                formatter={(v, n) => [v, n === "wa" ? "WhatsApp envoyés" : (n === "sms" ? "SMS envoyés" : "Synthèses IA")]}
                labelFormatter={(l) => `Jour ${l}`}
              />
              <Legend formatter={(v) => (v === "wa" ? "WhatsApp" : (v === "sms" ? "SMS" : "Synthèses IA"))} />
              <Bar dataKey="wa" stackId="a" fill="#10b981" />
              <Bar dataKey="sms" stackId="a" fill="#6366f1" />
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
                <Th k="sms_sent_ok" sortKey={sortKey} dir={dir} onSort={toggleSort} right>SMS ✓</Th>
                <Th k="sms_cost" sortKey={sortKey} dir={dir} onSort={toggleSort} right>Coût SMS</Th>
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
                  <td className="px-3 py-2 text-right text-indigo-700 font-mono">{c.sms_sent_ok || 0}</td>
                  <td className="px-3 py-2 text-right font-mono">
                    {(c.sms_cost || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} <span className="text-[10px] text-slate-400">XOF</span>
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

// ============================================================
// Iter34f — User activity (last logins + top pages, filterable)
// ============================================================
const PERIOD_LABELS = [
  { value: "today", label: "Aujourd'hui" },
  { value: "week", label: "7 jours" },
  { value: "month", label: "30 jours" },
  { value: "quarter", label: "90 jours" },
  { value: "year", label: "1 an" },
];

const _fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
};

// ============================================================
// Iter34i — Reset usage counters (compteur visites + access_logs)
// ============================================================
const ResetUsageButton = ({ onDone }) => {
  const [open, setOpen] = useState(false);
  const [purge, setPurge] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (purge && !window.confirm("⚠️ Vous allez SUPPRIMER définitivement toutes les visites enregistrées et toutes les traces d'accès (access_logs). Cette action est IRRÉVERSIBLE. Continuer ?")) return;
    setBusy(true);
    try {
      const r = await apiClient.post("/admin/visits/reset", { purge_access_logs: purge });
      if (purge) {
        toast.success(`Réinitialisation complète : ${r.data?.purged_visits || 0} visites + ${r.data?.purged_access_logs || 0} logs supprimés`);
      } else {
        toast.success(`Compteur remis à 0 — ${r.data?.real_count || 0} visites masquées (conservées en base)`);
      }
      setOpen(false);
      setPurge(false);
      onDone && onDone();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-lg ring-1 ring-rose-300 bg-white text-rose-700 hover:bg-rose-50 px-3 py-1.5 text-sm"
        data-testid="usage-reset-btn"
      >
        <Trash2 className="h-4 w-4" /> Réinitialiser
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-lg ring-1 ring-slate-200 bg-white shadow-xl p-3 z-50 space-y-2" data-testid="usage-reset-panel">
          <p className="text-xs font-semibold text-slate-700">Réinitialiser le compteur d'usage</p>
          <p className="text-[11px] text-slate-500 leading-snug">
            Idéal après des phases de simulation pour partir d'une base propre des usages réels.
          </p>
          <label className="flex items-start gap-2 text-[11px] text-slate-700 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={purge}
              onChange={(e) => setPurge(e.target.checked)}
              className="mt-0.5"
              data-testid="usage-reset-purge"
            />
            <span>
              <span className="font-semibold">Purge complète</span> — supprimer définitivement les visites + traces d'accès. Sinon, simple offset (les données restent en base et sont masquées).
            </span>
          </label>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              onClick={() => { setOpen(false); setPurge(false); }}
              className="text-[11px] text-slate-500 hover:text-slate-900 px-2 py-1"
            >
              Annuler
            </button>
            <button
              onClick={run}
              disabled={busy}
              className={`text-[11px] font-semibold px-3 py-1 rounded ${purge ? "bg-rose-600 hover:bg-rose-700" : "bg-amber-600 hover:bg-amber-700"} text-white disabled:opacity-50`}
              data-testid="usage-reset-confirm"
            >
              {busy ? "…" : purge ? "Purger TOUT" : "Mettre à 0"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const UserActivityCard = () => {
  const [period, setPeriod] = useState("week");
  const [company, setCompany] = useState("");
  const [data, setData] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = { period, limit: 10 };
      if (company) params.company = company;
      const [r, hm] = await Promise.all([
        apiClient.get("/admin/user-activity", { params }),
        // The heatmap always shows "month" granularity for stability,
        // but is filtered by the same company. Period filter applies via param.
        apiClient.get("/admin/user-activity/heatmap", { params: { ...params, period: period === "today" ? "week" : period } }),
      ]);
      setData(r.data);
      setHeatmap(hm.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [period, company]);

  const totals = data?.totals || { hits: 0, unique_users: 0, unique_companies: 0 };

  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4 space-y-4" data-testid="user-activity-card">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-sm font-semibold text-slate-700 inline-flex items-center gap-2">
          <Users className="h-4 w-4 text-sawali-blue" /> Connexions & pages visitées
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="inline-flex rounded ring-1 ring-slate-200 p-0.5 bg-slate-50">
            {PERIOD_LABELS.map((p) => (
              <button
                key={p.value}
                onClick={() => setPeriod(p.value)}
                className={`px-2.5 py-1 text-[11px] rounded ${period === p.value ? "bg-sawali-blue text-white" : "text-slate-600 hover:bg-white"}`}
                data-testid={`user-activity-period-${p.value}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="relative inline-flex items-center">
            <Building2 className="h-3.5 w-3.5 text-slate-400 absolute left-2 pointer-events-none" />
            <select
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="appearance-none rounded ring-1 ring-slate-200 bg-white pl-7 pr-8 py-1 text-[11px] min-w-[160px]"
              data-testid="user-activity-company-filter"
            >
              <option value="">Toutes les sociétés</option>
              {(data?.company_options || []).map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded ring-1 ring-slate-200 bg-white hover:bg-slate-50 px-2 py-1 text-[11px] text-slate-600"
            data-testid="user-activity-refresh"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Mini KPIs */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50 p-3" data-testid="user-activity-kpi-hits">
          <p className="text-[10px] uppercase tracking-wider text-sky-700 font-semibold">Visites de pages</p>
          <p className="text-2xl font-display font-bold text-slate-900">{totals.hits.toLocaleString("fr-FR")}</p>
        </div>
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3" data-testid="user-activity-kpi-users">
          <p className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold">Utilisateurs actifs</p>
          <p className="text-2xl font-display font-bold text-slate-900">{totals.unique_users}</p>
        </div>
        <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3" data-testid="user-activity-kpi-companies">
          <p className="text-[10px] uppercase tracking-wider text-amber-700 font-semibold">Sociétés actives</p>
          <p className="text-2xl font-display font-bold text-slate-900">{totals.unique_companies}</p>
        </div>
      </div>

      {/* Tables */}
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-lg ring-1 ring-slate-200 overflow-hidden" data-testid="user-activity-logins">
          <div className="px-3 py-2 bg-slate-50 text-[10px] uppercase tracking-wider font-semibold text-slate-600 flex items-center gap-1.5">
            <Users className="h-3 w-3" /> Derniers utilisateurs connectés
          </div>
          {data?.last_logins?.length ? (
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="text-left px-3 py-1.5">Utilisateur</th>
                  <th className="text-left px-3 py-1.5">Société</th>
                  <th className="text-left px-3 py-1.5">Dernière activité</th>
                  <th className="text-right px-3 py-1.5">Visites</th>
                </tr>
              </thead>
              <tbody>
                {data.last_logins.map((u) => (
                  <tr key={u.user_email} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60">
                    <td className="px-3 py-1.5">
                      <div className="font-medium text-slate-700 truncate max-w-[160px]" title={u.user_email}>{u.user_name || u.user_email}</div>
                      <div className="text-[10px] text-slate-400 truncate max-w-[160px]" title={u.user_email}>{u.user_email}</div>
                    </td>
                    <td className="px-3 py-1.5 text-slate-600 truncate max-w-[120px]">{u.company || "—"}</td>
                    <td className="px-3 py-1.5 text-slate-500">{_fmtDate(u.last_seen_at)}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-semibold text-slate-700">{u.hits}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="px-3 py-6 text-center text-[11px] text-slate-400 italic">Aucune activité sur la période sélectionnée.</p>
          )}
        </div>

        <div className="rounded-lg ring-1 ring-slate-200 overflow-hidden" data-testid="user-activity-pages">
          <div className="px-3 py-2 bg-slate-50 text-[10px] uppercase tracking-wider font-semibold text-slate-600 flex items-center gap-1.5">
            <Eye className="h-3 w-3" /> Top pages visitées
          </div>
          {data?.top_pages?.length ? (
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                <tr className="border-b border-slate-100">
                  <th className="text-left px-3 py-1.5">Module</th>
                  <th className="text-left px-3 py-1.5">Page</th>
                  <th className="text-right px-3 py-1.5">Visites</th>
                  <th className="text-right px-3 py-1.5">Util.</th>
                </tr>
              </thead>
              <tbody>
                {data.top_pages.map((p, i) => (
                  <tr key={`${p.module}-${p.page}-${i}`} className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60">
                    <td className="px-3 py-1.5 text-slate-700 capitalize truncate max-w-[80px]">{p.module || "—"}</td>
                    <td className="px-3 py-1.5 text-slate-500 font-mono text-[11px] truncate max-w-[180px]" title={p.page}>{p.page || "—"}</td>
                    <td className="px-3 py-1.5 text-right font-mono font-semibold text-slate-700">{p.hits}</td>
                    <td className="px-3 py-1.5 text-right text-slate-500">{p.unique_users}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="px-3 py-6 text-center text-[11px] text-slate-400 italic">Aucune visite enregistrée.</p>
          )}
        </div>
      </div>

      {/* Heatmap — Mon→Sun × 0h→23h */}
      <ActivityHeatmap heatmap={heatmap} />
    </div>
  );
};

const ActivityHeatmap = ({ heatmap }) => {
  if (!heatmap || !heatmap.matrix) return null;
  const matrix = heatmap.matrix;
  const peakCount = Math.max(1, heatmap.peak?.count || 0);
  const weekdays = heatmap.weekdays || ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

  // Color scale: white → sky → indigo. Intensity is sqrt-scaled so low values
  // remain visible while peak bursts dominate.
  const cellColor = (n) => {
    if (n === 0) return { bg: "rgba(241, 245, 249, 1)", fg: "rgba(148, 163, 184, 0.6)" };
    const ratio = Math.sqrt(n / peakCount);
    const alpha = 0.15 + ratio * 0.85;
    return { bg: `rgba(30, 144, 255, ${alpha.toFixed(2)})`, fg: ratio > 0.5 ? "white" : "rgba(15, 23, 42, 0.85)" };
  };

  return (
    <div className="rounded-lg ring-1 ring-slate-200 overflow-hidden" data-testid="user-activity-heatmap">
      <div className="px-3 py-2 bg-slate-50 text-[10px] uppercase tracking-wider font-semibold text-slate-600 flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5">
          <Activity className="h-3 w-3" /> Carte de chaleur — heures d'activité (UTC)
        </span>
        <span className="text-slate-500 font-normal normal-case">
          Total {heatmap.total.toLocaleString("fr-FR")} · pic {heatmap.peak?.count || 0}
          {heatmap.peak?.day !== null && heatmap.peak?.hour !== null && (
            <> · {weekdays[heatmap.peak.day]} {String(heatmap.peak.hour).padStart(2, "0")}h</>
          )}
        </span>
      </div>
      <div className="overflow-x-auto p-3">
        <table className="text-[9px] min-w-[640px]" data-testid="heatmap-grid">
          <thead>
            <tr>
              <th className="w-10"></th>
              {Array.from({ length: 24 }).map((_, h) => (
                <th key={h} className={`text-center text-slate-400 font-mono px-0.5 py-1 ${h % 3 === 0 ? "" : "opacity-50"}`}>
                  {h % 3 === 0 ? `${String(h).padStart(2, "0")}h` : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, wd) => (
              <tr key={wd}>
                <td className="text-right pr-2 text-slate-500 font-semibold">{weekdays[wd]}</td>
                {row.map((n, h) => {
                  const { bg, fg } = cellColor(n);
                  return (
                    <td key={h} className="p-0">
                      <div
                        className="aspect-square w-full min-w-[18px] flex items-center justify-center font-mono"
                        style={{ backgroundColor: bg, color: fg }}
                        title={`${weekdays[wd]} ${String(h).padStart(2, "0")}h — ${n} visite(s)`}
                        data-testid={`heatmap-cell-${wd}-${h}`}
                      >
                        {n > 0 ? n : ""}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-3 pb-3 flex items-center gap-1.5 text-[9px] text-slate-500">
        <span>Faible</span>
        {[0.15, 0.3, 0.5, 0.7, 1.0].map((a, i) => (
          <span key={i} className="inline-block h-2.5 w-5 rounded-sm" style={{ backgroundColor: `rgba(30, 144, 255, ${a})` }} />
        ))}
        <span>Élevée</span>
      </div>
    </div>
  );
};
