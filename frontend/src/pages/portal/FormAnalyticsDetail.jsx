import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiClient, API } from "@/lib/api";
import {
  BarChart3, Globe, Lock, RefreshCw, MapPin, Users, UserX, Download, Eye, TrendingUp, UserCheck,
} from "lucide-react";
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

const todayIso = () => new Date().toISOString().slice(0, 10);
const daysAgoIso = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

const PIE_COLORS = ["#1E90FF", "#10b981", "#f59e0b", "#e11d48", "#8b5cf6"];

export default function FormAnalyticsDetail() {
  const { fid } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState(daysAgoIso(30));
  const [dateTo, setDateTo] = useState(todayIso());

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/me/forms/${fid}/analytics`, {
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
  }, [fid]);

  const pieData = useMemo(() => {
    if (!data) return [];
    return [
      { name: "Authentifiés", value: data.auth_count || 0 },
      { name: "Anonymes", value: data.anon_count || 0 },
    ];
  }, [data]);

  const maxCountry = Math.max(1, ...((data?.by_country || []).map((c) => c.count)));

  const exportCsv = async () => {
    try {
      const token = localStorage.getItem("sawali_token");
      const url = `${API}/me/forms/${fid}/analytics/export.csv?date_from=${dateFrom}&date_to=${dateTo}`;
      const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!resp.ok) {
        const msg = await resp.text();
        throw new Error(`HTTP ${resp.status} — ${msg.slice(0, 120)}`);
      }
      const ct = resp.headers.get("content-type") || "";
      if (!ct.includes("csv")) {
        throw new Error("Réponse inattendue du serveur");
      }
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${data?.form?.number || fid}-submissions.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast.success("Export CSV téléchargé");
    } catch (err) {
      toast.error(err?.message || "Erreur export CSV");
    }
  };

  return (
    <div className="max-w-6xl space-y-6" data-testid="form-analytics-detail-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Analytics formulaire</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <BarChart3 className="h-5 w-5 text-sawali-blue" />
            {data?.form?.title || "Chargement…"}
          </h1>
          {data?.form?.number && (
            <code className="text-[11px] font-mono bg-slate-100 px-1.5 py-0.5 rounded">{data.form.number}</code>
          )}
        </div>
        <div className="flex gap-2 flex-wrap">
          <Link
            to="/portal/forms/analytics"
            className="text-xs text-sawali-blue hover:underline inline-flex items-center gap-1 px-2 py-1.5"
            data-testid="analytics-detail-back-global"
          >
            ← Analytics global
          </Link>
          <Link
            to={`/portal/forms/${fid}/edit`}
            className="text-xs text-slate-700 hover:underline inline-flex items-center gap-1 px-2 py-1.5"
            data-testid="analytics-detail-edit"
          >
            Éditer le formulaire
          </Link>
          <button
            onClick={exportCsv}
            disabled={!data}
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 text-white px-3 py-1.5 text-xs hover:bg-emerald-700 disabled:opacity-50"
            data-testid="analytics-export-csv-btn"
          >
            <Download className="h-3.5 w-3.5" /> Export CSV
          </button>
        </div>
      </div>

      {/* Date filters */}
      <div className="flex items-end gap-3 flex-wrap rounded-xl border border-slate-200 bg-white p-4">
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Du</label>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
            data-testid="analytics-detail-from"
          />
        </div>
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Au</label>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm"
            data-testid="analytics-detail-to"
          />
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-1.5 text-sm hover:bg-sawali-blue-light"
          data-testid="analytics-detail-apply"
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
              data-testid={`analytics-detail-range-${label}`}
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
          {/* KPI */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KPI label="Vues" value={data.views} icon={Eye} />
            <KPI label="Soumissions" value={data.submissions} icon={Users} accent />
            <KPI label="Taux de complétion" value={`${data.completion_rate}%`} icon={TrendingUp} />
            <KPI
              label="Publication"
              value={data.form.is_public ? "Public" : "Privé"}
              icon={data.form.is_public ? Globe : Lock}
            />
          </div>

          {/* Time series */}
          <div className="rounded-xl border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-display font-bold mb-1">Soumissions dans le temps</h3>
            <p className="text-xs text-slate-500 mb-3">
              {data.series.length > 0
                ? `${data.submissions} soumissions sur ${data.series.length} jour(s) actifs.`
                : "Aucune soumission dans la période sélectionnée."}
            </p>
            <div className="h-56" data-testid="analytics-detail-timeseries">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data.series} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                  <defs>
                    <linearGradient id="subGrad2" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#1E90FF" stopOpacity={0.55} />
                      <stop offset="100%" stopColor="#1E90FF" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <RTooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Area type="monotone" dataKey="count" stroke="#1E90FF" strokeWidth={2} fill="url(#subGrad2)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            {/* Pie */}
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-sm font-display font-bold mb-1 flex items-center gap-2">
                <UserX className="h-4 w-4 text-sawali-blue" /> Authentifiés vs Anonymes
              </h3>
              <p className="text-xs text-slate-500 mb-3">
                {data.auth_count + data.anon_count} soumission(s) au total.
              </p>
              <div className="h-56" data-testid="analytics-detail-pie">
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

            {/* Countries */}
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-sm font-display font-bold mb-1 flex items-center gap-2">
                <MapPin className="h-4 w-4 text-sawali-blue" /> Géolocalisation
              </h3>
              <p className="text-xs text-slate-500 mb-3">Top pays des répondants.</p>
              {data.by_country.length === 0 ? (
                <p className="text-sm text-slate-400 italic">Aucune donnée géographique.</p>
              ) : (
                <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                  {data.by_country.slice(0, 15).map((c) => (
                    <div key={c.country} className="text-xs">
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

          {/* Top authors + Recent */}
          <div className="grid md:grid-cols-2 gap-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-sm font-display font-bold mb-3 flex items-center gap-2">
                <UserCheck className="h-4 w-4 text-sawali-blue" /> Top répondants
              </h3>
              {data.top_authors.length === 0 ? (
                <p className="text-sm text-slate-400 italic">Aucun répondant authentifié.</p>
              ) : (
                <ul className="space-y-1.5">
                  {data.top_authors.map((a) => (
                    <li
                      key={a.label}
                      className="flex items-center justify-between text-xs border-b border-slate-100 pb-1.5"
                    >
                      <span className="text-slate-700 truncate">{a.label}</span>
                      <span className="font-mono text-sawali-blue font-semibold">{a.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5">
              <h3 className="text-sm font-display font-bold mb-3">10 dernières soumissions</h3>
              {data.recent.length === 0 ? (
                <p className="text-sm text-slate-400 italic">Aucune soumission.</p>
              ) : (
                <ul className="space-y-1.5" data-testid="analytics-recent-list">
                  {data.recent.map((r) => (
                    <li key={r.id} className="text-xs border-b border-slate-100 pb-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-700 truncate">
                          {r.user_label}
                          {r.anonymous && (
                            <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
                              anonyme
                            </span>
                          )}
                        </span>
                        <span className="text-slate-500 text-[10px]">
                          {r.created_at ? new Date(r.created_at).toLocaleString("fr-FR") : "—"}
                        </span>
                      </div>
                      {(r.geo?.country || r.respondent_email) && (
                        <div className="text-[10px] text-slate-400 mt-0.5">
                          {r.respondent_email && <>✉ {r.respondent_email} · </>}
                          {r.geo?.country && <>🌍 {r.geo.country}</>}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Iter34v — Tableau brut des soumissions (visible + exportable) */}
          <SubmissionsTable fid={fid} dateFrom={dateFrom} dateTo={dateTo} />
        </>
      )}
    </div>
  );
}

// ============================================================
// Iter34v — Tableau brut des soumissions formulaire (avec données réelles)
// ============================================================
function SubmissionsTable({ fid, dateFrom, dateTo }) {
  const [data, setData] = React.useState({ columns: [], rows: [] });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiClient.get(`/me/forms/${fid}/submissions-table`, {
      params: { date_from: dateFrom, date_to: dateTo },
    })
      .then((r) => { if (!cancelled) setData(r.data || { columns: [], rows: [] }); })
      .catch(() => { /* noop */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [fid, dateFrom, dateTo]);

  // Iter38r-fix4 — Auto-scroll to the submissions table when the URL hash
  // is `#submissions` (entry point from FormsList "Données" button).
  React.useEffect(() => {
    if (loading) return;
    if (typeof window === "undefined") return;
    if ((window.location.hash || "").toLowerCase() !== "#submissions") return;
    const el = document.getElementById("submissions");
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [loading]);

  const { columns = [], rows = [] } = data;
  if (loading) return <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-slate-400 text-sm">Chargement du tableau des soumissions…</div>;

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden" id="submissions" data-testid="submissions-table-block">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <div>
          <h3 className="font-display font-semibold text-sm">Tableau des soumissions</h3>
          <p className="text-[10px] text-slate-500">Vue brute — chaque ligne = 1 soumission, chaque colonne = 1 champ du formulaire</p>
        </div>
        <span className="rounded-full bg-sky-100 text-sky-700 px-2 py-0.5 text-[10px] font-semibold tabular-nums" data-testid="submissions-table-count">{rows.length} ligne(s)</span>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-8 text-center text-slate-400 text-sm italic">Aucune soumission pour cette période.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-600 uppercase tracking-wider">
              <tr>
                <th className="text-left px-3 py-2 sticky left-0 bg-slate-50">Date</th>
                <th className="text-left px-3 py-2">Auteur</th>
                {columns.map((c) => (
                  <th key={c.id} className="text-left px-3 py-2 whitespace-nowrap">{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-sky-50/60" data-testid={`submission-row-${r.id}`}>
                  <td className="px-3 py-2 sticky left-0 bg-white text-slate-500 text-[10px]">
                    {r.created_at ? new Date(r.created_at).toLocaleString("fr-FR") : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {r.anonymous
                      ? <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 text-slate-600 px-1.5 py-0.5 text-[10px]">Anonyme</span>
                      : <span className="font-medium text-slate-700">{r.user_label}</span>}
                  </td>
                  {columns.map((c) => {
                    const v = r[c.id];
                    const text = v == null || v === "" ? "—" : (typeof v === "object" ? JSON.stringify(v) : String(v));
                    return (
                      <td key={c.id} className="px-3 py-2 max-w-[220px] truncate text-slate-800" title={text}>{text}</td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function KPI({ label, value, icon: Icon, accent = false }) {
  return (
    <div
      className={`rounded-xl border p-4 ${accent ? "bg-sawali-blue/5 border-sawali-blue/30" : "bg-white border-slate-200"}`}
      data-testid={`analytics-detail-kpi-${label}`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
        <Icon className={`h-3.5 w-3.5 ${accent ? "text-sawali-blue" : "text-slate-400"}`} />
      </div>
      <div className={`text-2xl font-display font-bold ${accent ? "text-sawali-blue" : "text-slate-900"}`}>{value}</div>
    </div>
  );
}
