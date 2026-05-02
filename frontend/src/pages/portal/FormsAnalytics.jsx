import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { BarChart3, Globe, Lock, ArrowRight, RefreshCw, MapPin, Users, UserX, FileText } from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RTooltip,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import { toast } from "sonner";

// Default range = last 30 days
const todayIso = () => new Date().toISOString().slice(0, 10);
const daysAgoIso = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

const PIE_COLORS = ["#1E90FF", "#10b981", "#f59e0b", "#e11d48", "#8b5cf6", "#64748b"];

export default function FormsAnalytics() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState(daysAgoIso(30));
  const [dateTo, setDateTo] = useState(todayIso());

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/forms-analytics", {
        params: { date_from: dateFrom, date_to: dateTo },
      });
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pieData = useMemo(() => {
    if (!data) return [];
    const s = data.submissions || {};
    return [
      { name: "Authentifiés", value: s.auth_count || 0 },
      { name: "Anonymes", value: s.anon_count || 0 },
    ];
  }, [data]);

  const maxCountry = Math.max(1, ...((data?.submissions?.by_country || []).map((c) => c.count)));

  return (
    <div className="max-w-6xl space-y-6" data-testid="forms-analytics-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Formulaires</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-sawali-blue" /> Analytics global
          </h1>
        </div>
        <Link
          to="/portal/forms"
          className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1"
          data-testid="analytics-back-list"
        >
          ← Retour à la bibliothèque
        </Link>
      </div>

      {/* Filters */}
      <div className="flex items-end gap-3 flex-wrap rounded-xl border border-slate-200 bg-white p-4">
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Du</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
            data-testid="analytics-date-from"
          />
        </div>
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Au</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
            data-testid="analytics-date-to"
          />
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-1.5 text-sm hover:bg-sawali-blue-light"
          data-testid="analytics-apply-btn"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Appliquer
        </button>
        <div className="flex gap-1 ml-auto">
          {[
            ["7j", 7],
            ["30j", 30],
            ["90j", 90],
            ["1an", 365],
          ].map(([label, n]) => (
            <button
              key={label}
              onClick={() => {
                setDateFrom(daysAgoIso(n));
                setDateTo(todayIso());
                setTimeout(load, 0);
              }}
              className="text-[11px] rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-100"
              data-testid={`analytics-range-${label}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading || !data ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPI label="Formulaires" value={data.total_forms} icon={FileText} />
            <KPI label="Vues totales" value={data.total_views} icon={Globe} />
            <KPI label="Soumissions" value={data.submissions.total_submissions} icon={Users} accent />
            <KPI label="Publics / Privés" value={`${data.public_count} / ${data.private_count}`} icon={Lock} />
          </div>

          {/* Time series */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-display font-bold mb-1">Soumissions dans le temps</h3>
            <p className="text-xs text-slate-500 mb-3">
              {data.submissions.series.length > 0
                ? `${data.submissions.total_submissions} soumissions sur ${data.submissions.series.length} jour(s) actifs.`
                : "Aucune soumission dans la période sélectionnée."}
            </p>
            <div className="h-56" data-testid="analytics-timeseries">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.submissions.series} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                  <defs>
                    <linearGradient id="subGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#1E90FF" stopOpacity={0.55} />
                      <stop offset="100%" stopColor="#1E90FF" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <RTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Area type="monotone" dataKey="count" stroke="#1E90FF" strokeWidth={2} fill="url(#subGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Pie auth/anon + countries */}
          <div className="grid md:grid-cols-2 gap-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-sm font-display font-bold mb-1 flex items-center gap-2">
                <UserX className="h-4 w-4 text-sawali-blue" /> Authentifiés vs Anonymes
              </h3>
              <p className="text-xs text-slate-500 mb-3">Répartition des soumissions.</p>
              <div className="h-56" data-testid="analytics-pie">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" outerRadius={70} innerRadius={40} dataKey="value" label>
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Legend verticalAlign="bottom" height={24} iconSize={10} wrapperStyle={{ fontSize: 12 }} />
                    <RTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-sm font-display font-bold mb-1 flex items-center gap-2">
                <MapPin className="h-4 w-4 text-sawali-blue" /> Géolocalisation
              </h3>
              <p className="text-xs text-slate-500 mb-3">Top pays (si géo transmise par le répondant).</p>
              {data.submissions.by_country.length === 0 ? (
                <p className="text-sm text-slate-400 italic">Aucune donnée géographique.</p>
              ) : (
                <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                  {data.submissions.by_country.slice(0, 15).map((c) => (
                    <div key={c.country} className="text-xs" data-testid={`analytics-country-${c.country}`}>
                      <div className="flex justify-between mb-1">
                        <span className="text-slate-700 truncate">{c.country}</span>
                        <span className="font-mono text-slate-500">{c.count}</span>
                      </div>
                      <div className="h-1.5 rounded bg-slate-100 overflow-hidden">
                        <div
                          className="h-full bg-sawali-blue"
                          style={{ width: `${(c.count / maxCountry) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Top forms */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-display font-bold mb-3">Top formulaires</h3>
            {data.top_forms.length === 0 ? (
              <p className="text-sm text-slate-400 italic">Aucun formulaire pour cette période.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm" data-testid="analytics-top-forms">
                  <thead className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
                    <tr>
                      <th className="text-left py-2 pr-4">Formulaire</th>
                      <th className="text-left py-2 pr-4">N°</th>
                      <th className="text-right py-2 pr-4">Vues</th>
                      <th className="text-right py-2 pr-4">Soumissions</th>
                      <th className="py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_forms.map((f) => (
                      <tr key={f.id} className="border-b border-slate-100 hover:bg-slate-50" data-testid={`analytics-form-row-${f.id}`}>
                        <td className="py-2 pr-4">
                          <span className="inline-flex items-center gap-1">
                            {f.is_public ? <Globe className="h-3 w-3 text-emerald-600" /> : <Lock className="h-3 w-3 text-slate-500" />}
                            <span className="line-clamp-1">{f.title}</span>
                          </span>
                        </td>
                        <td className="py-2 pr-4 text-[11px] font-mono text-slate-500">{f.number}</td>
                        <td className="py-2 pr-4 text-right font-mono">{f.views}</td>
                        <td className="py-2 pr-4 text-right font-mono font-semibold text-sawali-blue">{f.submissions}</td>
                        <td className="py-2 text-right">
                          <Link
                            to={`/portal/forms/${f.id}/analytics`}
                            className="inline-flex items-center gap-1 text-[11px] text-sawali-blue hover:underline"
                            data-testid={`analytics-open-${f.id}`}
                          >
                            Détails <ArrowRight className="h-3 w-3" />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function KPI({ label, value, icon: Icon, accent = false }) {
  return (
    <div
      className={`rounded-xl border p-4 ${accent ? "bg-sawali-blue/5 border-sawali-blue/30" : "bg-white border-slate-200"}`}
      data-testid={`analytics-kpi-${label}`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
        <Icon className={`h-3.5 w-3.5 ${accent ? "text-sawali-blue" : "text-slate-400"}`} />
      </div>
      <div className={`text-2xl font-display font-bold ${accent ? "text-sawali-blue" : "text-slate-900"}`}>{value}</div>
    </div>
  );
}
