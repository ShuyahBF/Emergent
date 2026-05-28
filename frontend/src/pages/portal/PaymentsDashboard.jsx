import React, { useEffect, useState, useMemo } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Wallet, Link2, MessageCircle, Send, ArrowDownToLine, TrendingUp,
  CheckCircle2, Clock, AlertCircle, Power, Layers,
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, Legend,
} from "recharts";

/*
  Portal → Encaissements 360° dashboard.
  Cross-source view : payment links + transactions + channel attribution.
*/
const COLORS_STATUS = { completed: "#10b981", pending: "#f59e0b", failed: "#e11d48" };
const COLORS_MNO = { ORANGE: "#FF7900", MOOV: "#0076BB", TELECEL: "#E2241A", MTN: "#FFCC00", AIRTEL: "#E60012", OTHER: "#94a3b8" };
const MNO_FULL_NAME = { ORANGE: "Orange Money", MOOV: "Moov Money", TELECEL: "Telecel Cash", MTN: "MTN Mobile Money", AIRTEL: "Airtel Money", OTHER: "Autres" };
const COLORS_CHANNEL = { whatsapp: "#25D366", sms: "#f59e0b", direct: "#6366f1" };

function fmtAmount(n, ccy = "XOF") {
  if (n == null) return "—";
  return `${Number(n).toLocaleString("fr-FR")} ${ccy}`;
}
function shortDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
}

export default function PaymentsDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/me/payments-dashboard?days=${days}`);
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [days]);

  const statusPie = useMemo(() => {
    if (!data) return [];
    return [
      { name: "Complétés", value: data.totals?.payments_completed || 0, key: "completed" },
      { name: "En attente", value: data.totals?.payments_pending || 0, key: "pending" },
      { name: "Échoués", value: data.totals?.payments_failed || 0, key: "failed" },
    ].filter((x) => x.value > 0);
  }, [data]);

  const mnoBars = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.by_mno || {})
      .filter(([, v]) => v > 0)
      .map(([k, v]) => ({ name: k, value: v }));
  }, [data]);

  // Iter38r-fix3 — Operator share donut (% breakdown) for visual negotiation.
  const mnoTotal = useMemo(() => mnoBars.reduce((acc, b) => acc + b.value, 0), [mnoBars]);
  const mnoShare = useMemo(() => mnoBars.map((b) => ({
    ...b,
    pct: mnoTotal > 0 ? Math.round((b.value / mnoTotal) * 100) : 0,
  })), [mnoBars, mnoTotal]);

  const channelData = useMemo(() => {
    if (!data) return [];
    const sent = data.channels?.sent || {};
    const att = data.channels?.payments_attributed || {};
    return [
      { name: "WhatsApp", sent: sent.whatsapp || 0, paid: att.whatsapp || 0, key: "whatsapp" },
      { name: "SMS", sent: sent.sms || 0, paid: att.sms || 0, key: "sms" },
      { name: "Direct", sent: 0, paid: att.direct || 0, key: "direct" },
    ];
  }, [data]);

  return (
    <div className="space-y-6 max-w-7xl" data-testid="payments-dashboard">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-display font-bold inline-flex items-center gap-2">
            <Wallet className="h-7 w-7 text-amber-600" /> Encaissements 360°
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Vue produit : liens + transactions + canaux + conversion. Dernière période sélectionnée : {days} jours.
          </p>
        </div>
        <div className="flex gap-2">
          <select value={days} onChange={(e) => setDays(parseInt(e.target.value, 10))}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm bg-white" data-testid="dashboard-period">
            <option value={7}>7 derniers jours</option>
            <option value={30}>30 derniers jours</option>
            <option value={90}>90 derniers jours</option>
            <option value={180}>6 derniers mois</option>
            <option value={365}>1 an</option>
          </select>
        </div>
      </div>

      {loading && !data && <p className="text-sm text-slate-500 italic">Chargement…</p>}
      {data && (
        <>
          {/* KPI grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="dashboard-kpis">
            <Kpi label="Encaissements" value={fmtAmount(data.totals.amount_completed)} sub={`${data.totals.payments_completed} transactions complétées`} tone="emerald" Icon={ArrowDownToLine} testid="kpi-cash" />
            <Kpi label="Liens actifs" value={data.totals.links_active} sub={`${data.totals.links} au total`} tone="amber" Icon={Link2} testid="kpi-links" />
            <Kpi label="En attente" value={data.totals.payments_pending} sub="Paiements à confirmer" tone="sky" Icon={Clock} testid="kpi-pending" />
            <Kpi label="Conversion" value={data.channels.conversion_rate_pct != null ? `${data.channels.conversion_rate_pct} %` : "—"} sub={`${(data.channels.sent.whatsapp + data.channels.sent.sms)} envois liés`} tone="violet" Icon={TrendingUp} testid="kpi-conversion" />
          </div>

          {/* Daily area chart */}
          <Section title="Évolution des encaissements" icon={TrendingUp} testid="dashboard-chart-daily">
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={data.daily || []}>
                <defs>
                  <linearGradient id="amountFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tickFormatter={shortDate} fontSize={11} stroke="#64748b" />
                <YAxis fontSize={11} stroke="#64748b" tickFormatter={(v) => v.toLocaleString("fr-FR")} />
                <Tooltip
                  formatter={(v, name) => name === "amount" ? [fmtAmount(v), "Montant"] : [v, "Transactions"]}
                  labelFormatter={shortDate}
                />
                <Area type="monotone" dataKey="amount" stroke="#10b981" fill="url(#amountFill)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </Section>

          {/* Status + MNO + Channels grid */}
          <div className="grid lg:grid-cols-3 gap-4">
            <Section title="Répartition par statut" icon={CheckCircle2} testid="chart-status" compact>
              {statusPie.length === 0 ? <Empty text="Aucune transaction sur la période." /> : (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={statusPie} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={45} outerRadius={75} paddingAngle={2}>
                      {statusPie.map((s) => <Cell key={s.key} fill={COLORS_STATUS[s.key]} />)}
                    </Pie>
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </Section>

            <Section title="Répartition par opérateur Mobile Money" icon={Layers} testid="chart-mno" compact>
              {mnoShare.length === 0 ? <Empty text="Aucun paiement encore." /> : (
                <div className="flex flex-col">
                  <ResponsiveContainer width="100%" height={180}>
                    <PieChart>
                      <Pie
                        data={mnoShare}
                        dataKey="value"
                        nameKey="name"
                        cx="50%" cy="50%"
                        innerRadius={42}
                        outerRadius={72}
                        paddingAngle={3}
                        label={({ pct }) => pct >= 8 ? `${pct}%` : ""}
                        labelLine={false}
                      >
                        {mnoShare.map((b) => (
                          <Cell key={b.name} fill={COLORS_MNO[b.name] || COLORS_MNO.OTHER} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v, _n, p) => [`${v} transactions (${p.payload.pct}%)`, p.payload.name]} />
                    </PieChart>
                  </ResponsiveContainer>
                  <ul className="space-y-1 px-2 mt-1" data-testid="mno-breakdown-legend">
                    {mnoShare.map((b) => (
                      <li key={b.name} className="flex items-center justify-between text-xs">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: COLORS_MNO[b.name] || COLORS_MNO.OTHER }} />
                          <span className="font-semibold text-slate-700">{MNO_FULL_NAME[b.name] || b.name}</span>
                        </span>
                        <span className="font-mono text-slate-500">{b.value} · <span className="text-slate-900 font-semibold">{b.pct}%</span></span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>

            <Section title="Canal de diffusion" icon={Send} testid="chart-channels" compact>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={channelData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="name" fontSize={11} stroke="#64748b" />
                  <YAxis fontSize={11} stroke="#64748b" />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="sent" name="Envoyés" fill="#94a3b8" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="paid" name="Payés" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Section>
          </div>

          {/* Top links */}
          <Section title="Top 5 des liens les plus utilisés" icon={Link2} testid="dashboard-top-links">
            {(data.top_links || []).length === 0 ? <Empty text="Aucun lien créé. Créez-en un dans l'onglet « Liens de paiement »." /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
                    <tr>
                      <th className="text-left px-3 py-2">Libellé</th>
                      <th className="text-left px-3 py-2">Slug</th>
                      <th className="text-right px-3 py-2">Montant</th>
                      <th className="text-center px-3 py-2">Utilisations</th>
                      <th className="text-left px-3 py-2">Statut</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_links.map((l) => (
                      <tr key={l.slug} className="border-t border-slate-100" data-testid={`top-link-${l.slug}`}>
                        <td className="px-3 py-2 font-semibold text-slate-800">{l.label}</td>
                        <td className="px-3 py-2 font-mono text-[11px] text-slate-500">/pay/{l.slug}</td>
                        <td className="px-3 py-2 text-right font-mono">{l.amount != null ? fmtAmount(l.amount) : <span className="italic text-amber-700">libre</span>}</td>
                        <td className="px-3 py-2 text-center font-mono">{l.uses_count}{l.max_uses ? <span className="text-slate-400">/{l.max_uses}</span> : ""}</td>
                        <td className="px-3 py-2">
                          <StatusBadge status={l.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

const TONES = {
  emerald: "bg-emerald-50 ring-emerald-200 text-emerald-900",
  amber: "bg-amber-50 ring-amber-200 text-amber-900",
  sky: "bg-sky-50 ring-sky-200 text-sky-900",
  violet: "bg-violet-50 ring-violet-200 text-violet-900",
  slate: "bg-slate-50 ring-slate-200 text-slate-900",
};

function Kpi({ label, value, sub, tone = "slate", Icon, testid }) {
  return (
    <div className={`rounded-xl ring-1 p-3 ${TONES[tone]}`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider opacity-70">{label}</span>
        {Icon && <Icon className="h-4 w-4 opacity-60" />}
      </div>
      <div className="text-2xl font-display font-bold leading-tight">{value}</div>
      <div className="text-[11px] opacity-70 truncate">{sub}</div>
    </div>
  );
}

function Section({ title, icon: Icon, children, testid, compact = false }) {
  return (
    <div className={`rounded-xl ring-1 ring-slate-200 bg-white ${compact ? "p-3" : "p-4"}`} data-testid={testid}>
      <h3 className="font-display font-semibold text-slate-700 inline-flex items-center gap-2 mb-3 text-sm">
        {Icon && <Icon className="h-4 w-4" />} {title}
      </h3>
      {children}
    </div>
  );
}

function Empty({ text }) {
  return <p className="text-xs text-slate-400 italic text-center py-8">{text}</p>;
}

function StatusBadge({ status }) {
  const map = {
    active: { cls: "bg-emerald-100 text-emerald-800", label: "Actif", Icon: CheckCircle2 },
    disabled: { cls: "bg-slate-100 text-slate-700", label: "Désactivé", Icon: Power },
    expired: { cls: "bg-amber-100 text-amber-800", label: "Expiré", Icon: Clock },
    exhausted: { cls: "bg-rose-100 text-rose-800", label: "Épuisé", Icon: AlertCircle },
  };
  const m = map[status] || map.active;
  const I = m.Icon;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${m.cls}`}>
      <I className="h-3 w-3" /> {m.label}
    </span>
  );
}
