import React, { useEffect, useState } from "react";
import axios from "axios";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, Globe, Database, ShieldCheck, ArrowLeft, RefreshCw, AlertTriangle, AlertOctagon, Info, Clock, CheckCircle2, Mail, Bell } from "lucide-react";
import { LOGO_URL } from "@/lib/brand";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const PROBE_ICONS = {
  db_ping: Database,
  api_health: Activity,
  api_company_info: Globe,
  api_visits_count: Activity,
  auth_login_endpoint: ShieldCheck,
};

const SEVERITY_META = {
  info: { Icon: Info, ring: "ring-sky-400/40", text: "text-sky-300", bg: "bg-sky-500/10", label: "Info" },
  warning: { Icon: AlertTriangle, ring: "ring-amber-400/40", text: "text-amber-300", bg: "bg-amber-500/10", label: "Avertissement" },
  critical: { Icon: AlertOctagon, ring: "ring-rose-400/40", text: "text-rose-300", bg: "bg-rose-500/10", label: "Critique" },
};

const formatDuration = (mins) => {
  if (mins === null || mins === undefined) return "—";
  if (mins < 1) return "< 1 min";
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60), m = mins % 60;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
};

export default function StatusPage() {
  const [data, setData] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [windowH, setWindowH] = useState(168);
  const [params, setParams] = useSearchParams();
  const subStatus = params.get("subscribe");

  // Auto-clear the subscribe query param after showing the toast
  useEffect(() => {
    if (subStatus) {
      const t = setTimeout(() => {
        const next = new URLSearchParams(params);
        next.delete("subscribe");
        setParams(next, { replace: true });
      }, 6000);
      return () => clearTimeout(t);
    }
  }, [subStatus, params, setParams]);

  const load = async (w = windowH) => {
    setLoading(true);
    try {
      const [s, inc] = await Promise.all([
        axios.get(`${API}/public/status?window_hours=${w}`),
        axios.get(`${API}/public/incidents?limit=30`),
      ]);
      setData(s.data);
      setIncidents(inc.data || []);
    } catch { /* noop */ }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);
  // auto-refresh every 60s
  useEffect(() => {
    const t = setInterval(() => load(), 60000);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [windowH]);

  const overallTone = !data?.stats ? "slate" : data.stats.overall_uptime_pct >= 99 ? "emerald" : data.stats.overall_uptime_pct >= 95 ? "amber" : "rose";
  const palette = {
    emerald: { ring: "ring-emerald-400", bg: "bg-emerald-500/10", text: "text-emerald-300", label: "Tous les services opérationnels" },
    amber: { ring: "ring-amber-400", bg: "bg-amber-500/10", text: "text-amber-300", label: "Performance dégradée" },
    rose: { ring: "ring-rose-400", bg: "bg-rose-500/10", text: "text-rose-300", label: "Incident en cours" },
    slate: { ring: "ring-slate-400", bg: "bg-slate-500/10", text: "text-slate-300", label: "État inconnu" },
  }[overallTone];

  return (
    <div className="min-h-screen bg-[#0E1F3D] text-white" data-testid="public-status-page">
      <header className="border-b border-white/10 bg-black/20 backdrop-blur-sm">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3" data-testid="status-home-link">
            <img src={LOGO_URL} alt="SAWALI" className="h-9 w-9 rounded-md ring-1 ring-white/20" />
            <div>
              <p className="font-display font-bold text-sm">{data?.company || "SAWALI SMART SYSTEMS"}</p>
              <p className="text-[10px] uppercase tracking-[0.3em] text-sawali-blue-light">Page de statut</p>
            </div>
          </Link>
          <Link to="/" className="text-xs text-slate-300 hover:text-white inline-flex items-center gap-1.5">
            <ArrowLeft className="h-3.5 w-3.5" /> Retour au site
          </Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        {/* Subscription feedback banner */}
        {subStatus && (
          <SubscribeFeedback status={subStatus} />
        )}

        {/* Overall banner */}
        <div className={`rounded-2xl ${palette.bg} ring-2 ${palette.ring} p-8 mb-8`} data-testid="status-overall-banner">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-300 mb-1">État global</p>
              <h1 className={`text-3xl sm:text-4xl font-display font-bold ${palette.text}`} data-testid="status-overall-label">
                {palette.label}
              </h1>
              {data?.stats && (
                <p className="text-sm text-slate-300 mt-2">
                  Disponibilité moyenne sur {data.stats.window_hours} h :
                  <span className={`ml-2 text-xl font-display font-bold ${palette.text} tabular-nums`} data-testid="status-overall-pct">
                    {data.stats.overall_uptime_pct} %
                  </span>
                </p>
              )}
            </div>
            <div className="flex flex-col items-end gap-2">
              <select
                value={windowH}
                onChange={(e) => { const w = parseInt(e.target.value, 10); setWindowH(w); load(w); }}
                className="rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2 text-sm"
                data-testid="status-window-select"
              >
                <option value={24} className="text-slate-900">24 h</option>
                <option value={72} className="text-slate-900">3 jours</option>
                <option value={168} className="text-slate-900">7 jours</option>
                <option value={720} className="text-slate-900">30 jours</option>
              </select>
              <button
                onClick={() => load()}
                className="text-xs text-slate-300 hover:text-white inline-flex items-center gap-1.5"
                data-testid="status-refresh"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
              </button>
            </div>
          </div>
        </div>

        {/* Per-probe list */}
        <div className="rounded-2xl bg-white/5 ring-1 ring-white/10 p-6">
          <h2 className="text-xs uppercase tracking-[0.3em] text-slate-400 mb-4">Services surveillés</h2>
          {!data?.stats?.probes?.length ? (
            <div className="text-center py-12 text-slate-400">Aucune donnée disponible.</div>
          ) : (
            <ul className="divide-y divide-white/10">
              {data.stats.probes.map((p) => {
                const Icon = PROBE_ICONS[p.key] || Activity;
                const last = p.timeline.length ? p.timeline[p.timeline.length - 1] : null;
                const tone = !last ? "slate" : last.ok ? "emerald" : "rose";
                const dotClass = { emerald: "bg-emerald-500", rose: "bg-rose-500", slate: "bg-slate-500" }[tone];
                return (
                  <li key={p.key} className="py-4 flex items-center gap-4" data-testid={`status-probe-${p.key}`}>
                    <Icon className="h-5 w-5 text-slate-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <span className="text-sm font-medium">{p.label}</span>
                        <div className="flex items-center gap-2">
                          <span className={`h-2 w-2 rounded-full ${dotClass}`} />
                          <span className={`text-xs tabular-nums ${p.uptime_pct >= 99 ? "text-emerald-300" : p.uptime_pct >= 95 ? "text-amber-300" : "text-rose-300"}`}>
                            {p.uptime_pct} %
                          </span>
                        </div>
                      </div>
                      <Sparkline timeline={p.timeline} />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Incident history */}
        <div className="rounded-2xl bg-white/5 ring-1 ring-white/10 p-6 mt-6" data-testid="incident-history">
          <h2 className="text-xs uppercase tracking-[0.3em] text-slate-400 mb-4">Historique des incidents</h2>
          {!incidents?.length ? (
            <div className="text-center py-12 text-slate-400 text-sm">
              <CheckCircle2 className="h-6 w-6 mx-auto mb-2 text-emerald-400" />
              Aucun incident enregistré. Tous les services ont fonctionné normalement.
            </div>
          ) : (
            <ul className="space-y-4" data-testid="incident-history-list">
              {incidents.map((it) => <IncidentItem key={it.id} item={it} />)}
            </ul>
          )}
        </div>

        {/* Email subscription */}
        <SubscribeForm />

        <p className="text-center text-[11px] text-slate-500 mt-8">
          Sondes exécutées chaque heure · {data?.stats?.samples || 0} relevé(s) · dernière mise à jour {data?.stats?.generated_at ? new Date(data.stats.generated_at).toLocaleString("fr-FR") : "—"}
        </p>
      </main>
    </div>
  );
}

const Sparkline = ({ timeline }) => {
  if (!timeline?.length) {
    return <div className="text-[11px] text-slate-500 italic">Pas encore de relevé sur la fenêtre.</div>;
  }
  return (
    <div className="flex gap-[2px] h-6" data-testid="status-sparkline">
      {timeline.map((t, i) => (
        <span
          key={i}
          className={`flex-1 rounded-sm ${t.ok ? "bg-emerald-500/80" : "bg-rose-500/80"}`}
          title={`${new Date(t.ts).toLocaleString("fr-FR")} — ${t.ok ? "OK" : "Échec"} (${t.duration_ms} ms)`}
          style={{ minWidth: 3 }}
        />
      ))}
    </div>
  );
};

// Single incident card with severity tag, timeline, and updates
const IncidentItem = ({ item }) => {
  const meta = SEVERITY_META[item.severity] || SEVERITY_META.warning;
  const Icon = meta.Icon;
  const ongoing = item.status === "ongoing";
  return (
    <li
      className={`rounded-xl ring-1 ${meta.ring} ${meta.bg} p-5`}
      data-testid={`incident-item-${item.id}`}
      data-severity={item.severity}
      data-status={item.status}
    >
      <div className="flex items-start gap-3">
        <Icon className={`h-5 w-5 flex-shrink-0 ${meta.text}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className={`text-[10px] uppercase tracking-[0.2em] font-bold ${meta.text}`}>{meta.label}</span>
            {ongoing ? (
              <span className="text-[10px] uppercase tracking-[0.2em] font-bold bg-rose-500/20 text-rose-200 px-2 py-0.5 rounded-full animate-pulse">En cours</span>
            ) : (
              <span className="text-[10px] uppercase tracking-[0.2em] font-bold bg-emerald-500/20 text-emerald-200 px-2 py-0.5 rounded-full inline-flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" /> Résolu
              </span>
            )}
            <span className="text-[11px] text-slate-400 inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {new Date(item.started_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}
            </span>
            {!ongoing && (
              <span className="text-[11px] text-slate-400">
                · Durée : <strong className="text-slate-200">{formatDuration(item.duration_minutes)}</strong>
              </span>
            )}
          </div>
          <p className="text-sm text-slate-100 leading-relaxed">{item.message}</p>
          {item.link_url && (
            <a
              href={item.link_url}
              target={item.link_url.startsWith("http") ? "_blank" : undefined}
              rel="noreferrer"
              className="text-xs text-sawali-blue-light underline mt-1 inline-block"
            >
              {item.link_label || "En savoir plus"} →
            </a>
          )}
          {/* Timeline of updates */}
          {item.updates?.length > 0 && (
            <ol className="mt-3 border-l-2 border-white/10 pl-4 space-y-2" data-testid="incident-updates">
              {item.updates.map((u, idx) => (
                <li key={idx} className="relative">
                  <span className="absolute -left-[19px] top-1 h-2 w-2 rounded-full bg-sawali-blue ring-2 ring-[#0E1F3D]" />
                  <p className="text-[11px] text-slate-400">
                    {new Date(u.ts).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}
                    {u.severity && u.severity !== item.severity && (
                      <span className="ml-2 text-[10px] uppercase font-bold">→ {u.severity}</span>
                    )}
                  </p>
                  <p className="text-sm text-slate-200">{u.message}</p>
                </li>
              ))}
              {!ongoing && item.resolved_at && (
                <li className="relative">
                  <span className="absolute -left-[19px] top-1 h-2 w-2 rounded-full bg-emerald-400 ring-2 ring-[#0E1F3D]" />
                  <p className="text-[11px] text-emerald-300 font-semibold">
                    {new Date(item.resolved_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })} · Incident résolu
                  </p>
                </li>
              )}
            </ol>
          )}
        </div>
      </div>
    </li>
  );
};


// Inline banner shown when the user comes back from the email confirm/unsubscribe link
const SubscribeFeedback = ({ status }) => {
  const map = {
    confirmed: { tone: "emerald", title: "Abonnement confirmé !", text: "Vous serez notifié par email à chaque ouverture et résolution d'incident." },
    ok: { tone: "emerald", title: "Désabonnement effectué", text: "Vous ne recevrez plus de notifications d'incidents SAWALI." },
    invalid: { tone: "rose", title: "Lien invalide ou expiré", text: "Le lien ne correspond à aucun abonnement actif." },
  }[status];
  if (!map) return null;
  const tone = { emerald: { bg: "bg-emerald-500/15", ring: "ring-emerald-400/40", text: "text-emerald-200" }, rose: { bg: "bg-rose-500/15", ring: "ring-rose-400/40", text: "text-rose-200" } }[map.tone];
  return (
    <div className={`mb-6 rounded-xl ${tone.bg} ring-1 ${tone.ring} p-4`} data-testid="subscribe-feedback" data-status={status}>
      <p className={`text-sm font-semibold ${tone.text}`}>{map.title}</p>
      <p className="text-xs text-slate-200 mt-1">{map.text}</p>
    </div>
  );
};

// Email subscription form. Double opt-in — confirmation link sent by email.
const SubscribeForm = () => {
  const [email, setEmail] = useState("");
  const [state, setState] = useState("idle"); // idle | loading | success | error
  const [msg, setMsg] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!email.trim()) return;
    setState("loading");
    setMsg("");
    try {
      const r = await axios.post(`${API}/public/incidents/subscribe`, { email: email.trim().toLowerCase() });
      if (r.data?.already_subscribed) {
        setState("success");
        setMsg("Vous êtes déjà abonné à cet email. Aucune action supplémentaire requise.");
      } else if (r.data?.confirmation_resent) {
        setState("success");
        setMsg("Lien de confirmation renvoyé. Vérifiez votre boîte mail.");
      } else {
        setState("success");
        setMsg("Vérifiez votre boîte mail pour confirmer votre abonnement.");
      }
      setEmail("");
    } catch (err) {
      setState("error");
      setMsg(err?.response?.data?.detail || "Erreur — veuillez réessayer.");
    }
  };

  return (
    <div className="mt-6 rounded-2xl bg-gradient-to-br from-sawali-blue/15 to-white/5 ring-1 ring-sawali-blue/40 p-6" data-testid="subscribe-form-section">
      <div className="flex items-start gap-4 flex-wrap">
        <div className="h-11 w-11 rounded-xl bg-sawali-blue/30 flex items-center justify-center flex-shrink-0">
          <Bell className="h-5 w-5 text-sawali-blue-light" />
        </div>
        <div className="flex-1 min-w-[260px]">
          <h2 className="text-lg font-display font-bold mb-1">Soyez prévenu des incidents</h2>
          <p className="text-sm text-slate-300 mb-4">
            Recevez un email à chaque ouverture et résolution d'incident. Vous pouvez vous désabonner à tout moment.
          </p>
          <form onSubmit={submit} className="flex flex-wrap gap-2" data-testid="subscribe-form">
            <div className="relative flex-1 min-w-[220px]">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="vous@entreprise.com"
                disabled={state === "loading"}
                className="w-full rounded-lg bg-white/10 border border-white/20 text-white placeholder:text-slate-400 pl-9 pr-3 py-2.5 text-sm focus:outline-none focus:border-sawali-blue focus:ring-2 focus:ring-sawali-blue/30 disabled:opacity-50"
                data-testid="subscribe-email-input"
              />
            </div>
            <button
              type="submit"
              disabled={state === "loading"}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-sawali-blue text-white px-5 py-2.5 text-sm font-medium hover:bg-sawali-blue-light transition disabled:opacity-50"
              data-testid="subscribe-submit"
            >
              {state === "loading" ? "Envoi…" : "S'abonner"}
            </button>
          </form>
          {msg && (
            <p
              className={`text-xs mt-3 ${state === "error" ? "text-rose-300" : "text-emerald-300"}`}
              data-testid="subscribe-message"
            >
              {msg}
            </p>
          )}
          <p className="text-[10px] text-slate-400 mt-3">
            Double opt-in : un email de confirmation vous sera envoyé. Aucune autre communication ne vous sera adressée.
          </p>
        </div>
      </div>
    </div>
  );
};
