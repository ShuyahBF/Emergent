import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { MessageSquare, AlertTriangle, CheckCircle2, RefreshCw, TrendingUp, DollarSign } from "lucide-react";

const PROVIDER_LABELS = {
  orange: "Orange",
  moov: "Moov",
  telecel: "Telecel",
  ovh: "OVH",
  unknown: "Inconnu / Test",
};

const PROVIDER_COLORS = {
  orange: "bg-orange-100 text-orange-800 ring-orange-300",
  moov: "bg-sky-100 text-sky-800 ring-sky-300",
  telecel: "bg-rose-100 text-rose-800 ring-rose-300",
  ovh: "bg-indigo-100 text-indigo-800 ring-indigo-300",
  unknown: "bg-slate-100 text-slate-700 ring-slate-300",
};

function StatCard({ icon: Icon, label, value, sub, tone = "slate" }) {
  const tones = {
    emerald: "bg-emerald-50 ring-emerald-200 text-emerald-900 [&_svg]:text-emerald-600",
    rose: "bg-rose-50 ring-rose-200 text-rose-900 [&_svg]:text-rose-600",
    amber: "bg-amber-50 ring-amber-200 text-amber-900 [&_svg]:text-amber-600",
    sky: "bg-sky-50 ring-sky-200 text-sky-900 [&_svg]:text-sky-600",
    slate: "bg-white ring-slate-200 text-slate-900 [&_svg]:text-slate-500",
  };
  return (
    <div className={`rounded-xl ring-1 p-4 ${tones[tone] || tones.slate}`}>
      <div className="flex items-center justify-between mb-1">
        <Icon className="h-4 w-4" />
        <span className="text-[10px] uppercase tracking-wider opacity-70">{label}</span>
      </div>
      <div className="text-2xl font-display font-bold leading-tight">{value}</div>
      {sub && <div className="text-[11px] opacity-70 mt-0.5">{sub}</div>}
    </div>
  );
}

function BudgetGauge({ budget }) {
  if (!budget || budget.status === "no_budget") {
    return (
      <div className="rounded-xl ring-1 ring-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
        Aucun budget mensuel défini. Configurez <code className="bg-white px-1 rounded">sms_monthly_budget_xof</code> dans les Paramètres pour activer la jauge.
      </div>
    );
  }
  const pct = Math.min(budget.used_pct ?? 0, 200); // clamp display to 200%
  const barPct = Math.min(pct, 100);
  const overPct = pct > 100 ? pct - 100 : 0;
  const tone = budget.status === "over" ? "rose" : budget.status === "warning" ? "amber" : "emerald";
  const toneBar = {
    emerald: "bg-emerald-500",
    amber: "bg-amber-500",
    rose: "bg-rose-500",
  }[tone];
  const toneRing = {
    emerald: "ring-emerald-200 bg-emerald-50",
    amber: "ring-amber-200 bg-amber-50",
    rose: "ring-rose-200 bg-rose-50",
  }[tone];
  return (
    <div className={`rounded-xl ring-1 p-4 ${toneRing}`} data-testid="sms-budget-gauge">
      <div className="flex items-center justify-between text-sm mb-2">
        <div className="flex items-center gap-2">
          <DollarSign className="h-4 w-4" />
          <span className="font-semibold">Budget mensuel SMS</span>
        </div>
        <span className="font-mono text-xs">{Math.round(budget.spent_this_month_xof).toLocaleString("fr-FR")} / {Math.round(budget.monthly_xof).toLocaleString("fr-FR")} XOF</span>
      </div>
      <div className="relative h-3 bg-white rounded-full overflow-hidden ring-1 ring-slate-200">
        <div className={`absolute left-0 top-0 h-full ${toneBar} transition-all`} style={{ width: `${barPct}%` }} />
        {overPct > 0 && (
          <div className="absolute left-0 top-0 h-full bg-rose-700/80" style={{ width: "100%" }} />
        )}
      </div>
      <div className="flex justify-between text-[11px] mt-1 opacity-70">
        <span>{pct.toFixed(1)}% utilisé</span>
        {budget.status === "over" && <span className="font-semibold text-rose-700">DÉPASSEMENT</span>}
        {budget.status === "warning" && <span className="font-semibold text-amber-700">⚠ Bientôt épuisé</span>}
        {budget.status === "ok" && <span className="text-emerald-700">Sous contrôle</span>}
      </div>
    </div>
  );
}

function DailyChart({ daily }) {
  if (!daily || daily.length === 0) return null;
  const maxOk = Math.max(...daily.map((d) => d.sent_ok), 1);
  const maxKo = Math.max(...daily.map((d) => d.sent_ko), 1);
  const max = Math.max(maxOk, maxKo, 1);
  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="sms-daily-chart">
      <div className="flex items-center gap-2 mb-3">
        <TrendingUp className="h-4 w-4 text-sky-600" />
        <span className="text-sm font-semibold">Envois quotidiens ({daily.length} j)</span>
      </div>
      <div className="flex items-end gap-1 h-32">
        {daily.map((d) => {
          const okH = (d.sent_ok / max) * 100;
          const koH = (d.sent_ko / max) * 100;
          return (
            <div key={d.day} className="flex-1 flex flex-col-reverse gap-px relative group min-w-0" title={`${d.day} · OK ${d.sent_ok} / KO ${d.sent_ko}`}>
              {d.sent_ok > 0 && <div className="bg-emerald-500 rounded-t" style={{ height: `${okH}%` }} />}
              {d.sent_ko > 0 && <div className="bg-rose-500 rounded-t" style={{ height: `${koH}%` }} />}
              {d.sent_ok === 0 && d.sent_ko === 0 && <div className="bg-slate-100 rounded-t" style={{ height: "2px" }} />}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mt-2 text-[10px] text-slate-500">
        <span>{daily[0]?.day}</span>
        <span className="flex items-center gap-2">
          <span className="flex items-center gap-1"><span className="w-2 h-2 bg-emerald-500 rounded-sm" /> OK</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 bg-rose-500 rounded-sm" /> Échec</span>
        </span>
        <span>{daily[daily.length - 1]?.day}</span>
      </div>
    </div>
  );
}

export default function AdminSmsDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  const load = useCallback(async (n = days) => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/sms/dashboard?days=${n}`);
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec du chargement");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { load(days); }, [load, days]);

  if (loading && !data) {
    return <div className="p-8 text-center text-slate-500">Chargement…</div>;
  }
  if (!data) {
    return <div className="p-8 text-center text-rose-600">Aucune donnée.</div>;
  }

  const t = data.totals || {};
  const providers = Object.entries(data.by_provider || {});

  return (
    <div className="space-y-6 p-4" data-testid="sms-dashboard">
      {/* Header */}
      <header className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900">Tableau de bord SMS</h1>
          <p className="text-sm text-slate-500">Consommation, coût et échecs par opérateur · {data.period_days} derniers jours.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm bg-white"
            data-testid="sms-period-select"
          >
            <option value={7}>7 j</option>
            <option value={30}>30 j</option>
            <option value={90}>90 j</option>
            <option value={365}>365 j</option>
          </select>
          <button
            onClick={() => load(days)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 text-white hover:bg-slate-800 px-3 py-1.5 text-sm"
            data-testid="sms-refresh-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Actualiser
          </button>
        </div>
      </header>

      {/* Top-level stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard icon={MessageSquare} label="Envoyés OK" value={t.sent_ok ?? 0} sub={`sur ${t.total ?? 0}`} tone="emerald" />
        <StatCard icon={AlertTriangle} label="Échecs" value={t.sent_ko ?? 0} sub={`${100 - (t.success_rate_pct ?? 0)}% d'échec`} tone={(t.sent_ko ?? 0) > 0 ? "rose" : "slate"} />
        <StatCard icon={CheckCircle2} label="Taux succès" value={`${t.success_rate_pct ?? 0}%`} sub="période sélectionnée" tone={(t.success_rate_pct ?? 100) >= 90 ? "emerald" : (t.success_rate_pct ?? 0) >= 70 ? "amber" : "rose"} />
        <StatCard icon={DollarSign} label="Coût estimé" value={`${Math.round(t.cost_xof ?? 0).toLocaleString("fr-FR")} XOF`} sub="cumul période" tone="sky" />
      </div>

      {/* Budget gauge */}
      <BudgetGauge budget={data.budget} />

      {/* Per-provider */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="sms-by-provider">
        <h2 className="text-sm font-semibold text-slate-800 mb-3">Détail par opérateur</h2>
        {providers.length === 0 && <p className="text-sm italic text-slate-400">Aucun envoi sur la période.</p>}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {providers.map(([prov, p]) => (
            <div key={prov} className="rounded-lg ring-1 ring-slate-200 p-3" data-testid={`sms-provider-${prov}`}>
              <div className="flex items-center justify-between mb-2">
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ring-1 ${PROVIDER_COLORS[prov] || PROVIDER_COLORS.unknown}`}>
                  {PROVIDER_LABELS[prov] || prov}
                </span>
                <span className="text-xs font-mono text-slate-500">{p.unit_cost_xof} XOF/SMS</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-lg font-bold text-emerald-600">{p.sent_ok}</div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-500">OK</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-rose-600">{p.sent_ko}</div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-500">KO</div>
                </div>
                <div>
                  <div className="text-lg font-bold text-slate-800">{p.success_rate_pct}%</div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-500">Réussite</div>
                </div>
              </div>
              <div className="text-center mt-2 pt-2 border-t border-slate-100">
                <span className="text-xs text-slate-500">Coût : </span>
                <span className="text-sm font-semibold text-slate-800">{Math.round(p.cost_xof).toLocaleString("fr-FR")} XOF</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Daily chart */}
      <DailyChart daily={data.daily_series} />

      {/* Top errors */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="sms-top-errors">
        <h2 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-rose-500" />
          Top des erreurs ({data.top_errors?.length || 0})
        </h2>
        {(!data.top_errors || data.top_errors.length === 0) && <p className="text-sm italic text-slate-400">Aucune erreur sur la période — bravo !</p>}
        <div className="space-y-2">
          {(data.top_errors || []).map((e, idx) => (
            <div key={idx} className="flex items-start gap-2 text-xs p-2 rounded ring-1 ring-rose-100 bg-rose-50/50" data-testid={`sms-error-${idx}`}>
              <span className="font-bold text-rose-700 min-w-[2.5rem]">×{e.count}</span>
              <div className="flex-1">
                <div className="text-slate-800">{e.message}</div>
                <div className="text-[10px] text-slate-500 mt-0.5">
                  {(e.providers || []).map((p) => PROVIDER_LABELS[p] || p).join(", ") || "—"}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
