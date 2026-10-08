/*
  SurveyResults — lot 27 : mesure des retours d'un sondage WhatsApp.

  - Chiffres : invités, envoyés, ouverts, réponses, taux d'ouverture et de réponse ;
  - filtre par période (du … au …) et par envoi : base des bilans livrés au client ;
  - graphiques par question : barres (choix, oui/non), note moyenne et
    répartition, score NPS (promoteurs / passifs / détracteurs), réponses libres ;
  - taux de réponse par entreprise (échantillonnage) et réponses par jour ;
  - destinataires et leur état (envoyé, ouvert, répondu, échec) ;
  - Relancer les non-répondants, Envoyer à d'autres contacts, export Excel (CSV) ;
  - progression des envois en cours (actualisée toutes les 4 s).
*/
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell, CartesianGrid, PieChart, Pie, Legend,
} from "recharts";
import { ArrowLeft, Send, RefreshCw, Download, Edit, Users, Eye, CheckCircle2, AlertTriangle, BellRing, Star } from "lucide-react";
import SurveySendModal from "@/components/SurveySendModal";
import { SURVEY_STATUS } from "@/pages/portal/Surveys";
import { marquerVu } from "@/lib/nouveautesFormulaires";   // lot 41
import SuiviEnvois from "@/components/SuiviEnvois";            // lot 42
import { siVisible } from "@/lib/visibilite";   // lot 79.6 : relectures en pause onglet masqué

const PALETTE = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#64748b"];
const INVITE_STATUS = {
  queued: ["En attente", "bg-slate-100 text-slate-600"],
  sent: ["Envoyé", "bg-sky-100 text-sky-700"],
  failed: ["Échec", "bg-rose-100 text-rose-700"],
  skipped: ["Non envoyé", "bg-amber-100 text-amber-700"],
};
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

// Graphique d'une question selon son type
function QuestionChart({ q, index }) {
  if (q.type === "text") {
    return (
      <div className="max-h-64 overflow-auto space-y-1.5">
        {(q.answers || []).map((a, i) => (
          <div key={i} className="rounded-lg bg-slate-50 px-3 py-2 text-sm">
            <p className="text-slate-800 whitespace-pre-line">{a.text}</p>
            <p className="text-[10px] text-slate-400 mt-0.5">{a.name ? `${a.name} · ` : ""}{fmt(a.at)}</p>
          </div>
        ))}
        {!(q.answers || []).length && <p className="text-sm text-slate-400">Aucune réponse libre.</p>}
      </div>
    );
  }
  if (q.type === "nps") {
    const pie = [
      { name: "Promoteurs (9-10)", value: q.promoters || 0, color: "#10b981" },
      { name: "Passifs (7-8)", value: q.passives || 0, color: "#f59e0b" },
      { name: "Détracteurs (0-6)", value: q.detractors || 0, color: "#ef4444" },
    ];
    return (
      <div className="grid sm:grid-cols-[160px_1fr] gap-3 items-center">
        <div className="text-center">
          <p className="text-[11px] uppercase tracking-wider text-slate-500">Score NPS</p>
          <p className={`text-4xl font-black tabular-nums ${q.nps == null ? "text-slate-300" : q.nps >= 30 ? "text-emerald-600" : q.nps >= 0 ? "text-amber-500" : "text-rose-600"}`}>
            {q.nps == null ? "—" : q.nps > 0 ? `+${q.nps}` : q.nps}
          </p>
          <p className="text-[11px] text-slate-500">moyenne {q.average ?? "—"} / 10</p>
        </div>
        <div className="h-48">
          <ResponsiveContainer>
            <PieChart>
              <Pie data={pie} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70} paddingAngle={2} isAnimationActive>
                {pie.map((p) => <Cell key={p.name} fill={p.color} />)}
              </Pie>
              <Tooltip /><Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }
  const data = q.type === "rating" ? q.distribution.map((d) => ({ label: `${d.label} ★`, count: d.count }))
    : (q.options || []).map((o) => ({ label: o.label, count: o.count, pct: o.pct }));
  return (
    <div>
      {q.type === "rating" && (
        <p className="mb-2 flex items-center gap-1 text-sm text-slate-700">
          Note moyenne <b className="text-lg text-amber-500 tabular-nums">{q.average ?? "—"}</b> / 5
          <Star className="h-4 w-4 text-amber-400 fill-amber-400" />
        </p>
      )}
      <div style={{ height: Math.max(140, data.length * 34) }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 10, right: 30 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="label" width={130} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v, n, p) => [`${v} réponse(s)${p?.payload?.pct != null ? ` · ${p.payload.pct} %` : ""}`, ""]} />
            <Bar dataKey="count" radius={[0, 6, 6, 0]} isAnimationActive>
              {data.map((_, i) => <Cell key={i} fill={q.type === "rating" ? "#f59e0b" : PALETTE[(i + index) % PALETTE.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export default function SurveyResults() {
  const { sid } = useParams();
  const { pathname } = useLocation();
  const base = pathname.startsWith("/admin") ? "/admin" : "/portal";
  const [survey, setSurvey] = useState(null);
  // Lot 41 — résultats consultés : la puce verte et la bulle bleue s'éteignent
  useEffect(() => { marquerVu("sondage", sid); }, [sid]);
  const [res, setRes] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [invites, setInvites] = useState([]);
  const [inviteFilter, setInviteFilter] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sendOpen, setSendOpen] = useState(null);   // null | "send" | "reminder"

  // Paramètres communs (envoi et période choisis)
  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (campaignId) p.set("campaign_id", campaignId);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    return p.toString();
  }, [campaignId, dateFrom, dateTo]);

  const load = useCallback(async () => {
    try {
      const [s, r, c, i] = await Promise.all([
        apiClient.get(`/me/wa-surveys/${sid}`),
        apiClient.get(`/me/wa-surveys/${sid}/results${params ? `?${params}` : ""}`),
        apiClient.get(`/me/wa-surveys/${sid}/campaigns`),
        apiClient.get(`/me/wa-surveys/${sid}/invites${inviteFilter ? `?status=${inviteFilter}` : ""}`),
      ]);
      setSurvey(s.data); setRes(r.data); setCampaigns(c.data?.items || []); setInvites(i.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger les résultats");
    }
  }, [sid, params, inviteFilter]);
  useEffect(() => { load(); }, [load]);

  // Envoi en cours : actualisation automatique
  const running = campaigns.some((c) => c.status === "running");
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(siVisible(load), 4000);   // lot 79.6 : relecture en pause onglet masqué
    return () => clearInterval(t);
  }, [running, load]);

  // Lot 42 — annulation d'un envoi programmé ou en attente de la plage horaire
  const annulerEnvoi = async (cid) => {
    try { await apiClient.delete(`/me/wa-surveys/${sid}/campaigns/${cid}`); toast.success("Envoi annulé"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Annulation impossible"); }
  };

  const exportCsv = async () => {
    try {
      const r = await apiClient.get(`/me/wa-surveys/${sid}/export.csv${dateFrom || dateTo ? `?${params}` : ""}`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = `${(survey?.title || "sondage").replace(/[^\w-]+/g, "_")}.csv`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch { toast.error("Export impossible"); }
  };

  if (!res || !survey) return <p className="text-sm text-slate-500">Chargement…</p>;
  const t = res.totals;
  const [stLabel, stCls] = SURVEY_STATUS[survey.status] || SURVEY_STATUS.draft;
  const waiting = Math.max(0, t.sent - t.answered);
  const kpis = [
    [Users, "Envoyés", t.sent, `${t.invited} invité(s)`, "text-sky-600"],
    [Eye, "Ouverts", t.opened, t.open_rate == null ? "—" : `${t.open_rate} % des envoyés`, "text-indigo-600"],
    [CheckCircle2, "Réponses", t.answered, t.response_rate == null ? "—" : `taux ${t.response_rate} %`, "text-emerald-600"],
    [AlertTriangle, "Non envoyés", t.failed + t.skipped, `${t.failed} échec(s) · ${t.skipped} hors 24 h`, "text-rose-600"],
  ];

  return (
    <div className="max-w-6xl space-y-5" data-testid="survey-results">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link to={`${base}/surveys`} className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
            <ArrowLeft className="h-4 w-4" /> Sondages
          </Link>
          <h1 className="text-2xl font-display font-bold text-slate-900 flex flex-wrap items-center gap-2">
            {survey.title} <span className={`text-xs font-medium rounded-full px-2 py-0.5 ${stCls}`}>{stLabel}</span>
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setSendOpen("send")} disabled={survey.status === "closed"} data-testid="results-send"
            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 text-white px-3 py-2 text-sm hover:bg-emerald-700 disabled:opacity-40">
            <Send className="h-4 w-4" /> Envoyer
          </button>
          <button onClick={() => setSendOpen("reminder")} disabled={!waiting || survey.status === "closed"} data-testid="results-remind"
            title="Renvoyer le lien aux invités qui n'ont pas répondu"
            className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500 text-white px-3 py-2 text-sm hover:bg-amber-600 disabled:opacity-40">
            <BellRing className="h-4 w-4" /> Relancer ({waiting})
          </button>
          {/* Lot 41 — nouvel essai pour les invitations en échec ou non envoyées */}
          <button onClick={() => setSendOpen("renvoi")} disabled={!(t.failed + t.skipped) || survey.status === "closed"}
            data-testid="results-resend-failed" title="Renvoyer aux destinataires dont l'envoi a échoué ou n'est pas parti"
            className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 text-white px-3 py-2 text-sm hover:bg-rose-700 disabled:opacity-40">
            <RefreshCw className="h-4 w-4" /> Renvoyer les échecs ({t.failed + t.skipped})
          </button>
          <button onClick={exportCsv} data-testid="results-export"
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50">
            <Download className="h-4 w-4" /> Excel
          </button>
          <Link to={`${base}/surveys/${sid}/edit`} className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50">
            <Edit className="h-4 w-4" /> Éditer
          </Link>
          <button onClick={load} title="Actualiser" className="rounded-lg ring-1 ring-slate-300 bg-white px-2.5 py-2 hover:bg-slate-50">
            <RefreshCw className={`h-4 w-4 ${running ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Filtres : envoi + période */}
      <div className="flex flex-wrap items-end gap-3 rounded-xl bg-white ring-1 ring-slate-200 p-3 text-sm">
        <label className="text-xs text-slate-600">Envoi
          <select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
            <option value="">Tous les envois</option>
            {campaigns.map((c) => <option key={c.id} value={c.id}>{fmt(c.created_at)} · {c.kind === "reminder" ? "relance" : "envoi"} · {c.total} dest.{c.status === "scheduled" ? " · programmé" : c.status === "waiting" ? " · en attente" : c.status === "cancelled" ? " · annulé" : ""}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-600">Du
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="results-from" />
        </label>
        <label className="text-xs text-slate-600">Au
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-1 block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="results-to" />
        </label>
        {(campaignId || dateFrom || dateTo) && (
          <button onClick={() => { setCampaignId(""); setDateFrom(""); setDateTo(""); }} className="text-xs text-sawali-blue hover:underline pb-2">Effacer les filtres</button>
        )}
      </div>

      {/* Lot 42 — envois programmés ou en attente de la plage horaire (annulables) */}
      <SuiviEnvois items={campaigns} onAnnuler={annulerEnvoi} />

      {/* Envois en cours */}
      {campaigns.filter((c) => c.status === "running").map((c) => (
        <div key={c.id} className="rounded-xl bg-sky-50 ring-1 ring-sky-200 p-3" data-testid="campaign-progress">
          <p className="text-sm text-sky-800">
            Envoi en cours : <b>{c.done}</b> / {c.total} ({c.sent_ok} envoyé(s), {c.sent_ko} échec(s), {c.skipped} non envoyé(s))
          </p>
          <div className="mt-2 h-2 rounded-full bg-sky-100 overflow-hidden">
            <div className="h-full bg-sky-500 transition-all" style={{ width: `${c.total ? (100 * c.done) / c.total : 0}%` }} />
          </div>
        </div>
      ))}

      {/* Chiffres clés */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {kpis.map(([Icon, label, value, sub, color]) => (
          <div key={label} className="rounded-xl bg-white ring-1 ring-slate-200 p-4">
            <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-slate-500"><Icon className="h-3.5 w-3.5" /> {label}</p>
            <p className={`text-3xl font-black tabular-nums ${color}`}>{value}</p>
            <p className="text-xs text-slate-500">{sub}</p>
          </div>
        ))}
      </div>
      {t.sent > 0 && (
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4">
          <p className="text-xs text-slate-500 mb-1">Entonnoir : envoyés → ouverts → réponses</p>
          {[["Envoyés", t.sent, "bg-sky-500"], ["Ouverts", t.opened, "bg-indigo-500"], ["Réponses", t.answered, "bg-emerald-500"]].map(([l, v, c]) => (
            <div key={l} className="flex items-center gap-2 text-xs my-1">
              <span className="w-20 text-slate-600">{l}</span>
              <div className="flex-1 h-4 rounded bg-slate-100 overflow-hidden">
                <div className={`h-full ${c} transition-all duration-700`} style={{ width: `${(100 * v) / t.sent}%` }} />
              </div>
              <span className="w-10 text-right tabular-nums font-semibold">{v}</span>
            </div>
          ))}
        </div>
      )}

      {/* Questions */}
      <div className="grid lg:grid-cols-2 gap-4">
        {res.questions.map((q, i) => (
          <div key={q.id} className={`rounded-xl bg-white ring-1 ring-slate-200 p-4 ${q.type === "text" ? "lg:col-span-2" : ""}`} data-testid={`result-q-${i}`}>
            <p className="font-semibold text-slate-900">{i + 1}. {q.label}</p>
            <p className="text-[11px] text-slate-500 mb-2">{q.answered} réponse(s)</p>
            <QuestionChart q={q} index={i} />
          </div>
        ))}
      </div>

      {/* Par entreprise + par jour */}
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4">
          <p className="font-semibold text-slate-900 mb-2">Taux de réponse par entreprise</p>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] uppercase text-slate-500"><th>Entreprise</th><th className="text-right">Envoyés</th><th className="text-right">Réponses</th><th className="text-right">Taux</th></tr></thead>
            <tbody>
              {res.by_company.map((b) => (
                <tr key={b.company} className="border-t border-slate-100">
                  <td className="py-1 truncate max-w-[12rem]">{b.company}</td>
                  <td className="text-right tabular-nums">{b.sent}</td>
                  <td className="text-right tabular-nums">{b.answered}</td>
                  <td className="text-right tabular-nums font-semibold">{b.rate == null ? "—" : `${b.rate} %`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!res.by_company.length && <p className="text-sm text-slate-400">Aucun envoi.</p>}
        </div>
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4">
          <p className="font-semibold text-slate-900 mb-2">Réponses par jour</p>
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={res.timeline}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(d) => d.slice(5)} />
                <YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="count" name="Réponses" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Destinataires */}
      <div className="rounded-xl bg-white ring-1 ring-slate-200 p-4" data-testid="results-invites">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <p className="font-semibold text-slate-900 mr-2">Destinataires</p>
          {[["", "Tous"], ["answered", "Ont répondu"], ["waiting", "En attente de réponse"], ["failed", "Échecs"], ["skipped", "Non envoyés"]].map(([k, l]) => (
            <button key={k} onClick={() => setInviteFilter(k)}
              className={`text-xs px-2.5 py-1 rounded-full ring-1 ${inviteFilter === k ? "bg-sawali-blue text-white ring-sawali-blue" : "bg-white ring-slate-200"}`}>{l}</button>
          ))}
        </div>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white"><tr className="text-left text-[11px] uppercase text-slate-500">
              <th className="py-1">Contact</th><th>Envoi</th><th>Ouvert</th><th>Réponse</th></tr></thead>
            <tbody>
              {invites.map((i) => {
                const [l, c] = INVITE_STATUS[i.status] || INVITE_STATUS.queued;
                return (
                  <tr key={i.id} className="border-t border-slate-100 align-top">
                    <td className="py-1.5"><p className="font-medium text-slate-800">{i.name}</p><p className="text-[11px] text-slate-400">{i.company} · {i.phone}</p></td>
                    <td><span className={`text-[11px] rounded px-1.5 py-0.5 ${c}`} title={i.error || ""}>{l}</span>
                      {i.sent_count > 1 && <span className="ml-1 text-[10px] text-slate-400">×{i.sent_count}</span>}
                      {i.error && <p className="text-[10px] text-rose-500 max-w-[16rem]">{i.error}</p>}</td>
                    <td className="text-xs text-slate-600">{fmt(i.opened_at)}</td>
                    <td className="text-xs">{i.answered_at ? <span className="text-emerald-700 font-medium">{fmt(i.answered_at)}</span> : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!invites.length && <p className="text-sm text-slate-400 py-2">Personne dans cette liste.</p>}
        </div>
      </div>

      {sendOpen && (
        <SurveySendModal survey={survey} reminder={sendOpen === "reminder" || sendOpen === "renvoi"}
          renvoiEchecs={sendOpen === "renvoi"} waitingCount={sendOpen === "renvoi" ? t.failed + t.skipped : waiting}
          onClose={() => setSendOpen(null)} onSent={() => { setSendOpen(null); load(); }} />
      )}
    </div>
  );
}
