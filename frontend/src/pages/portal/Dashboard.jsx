import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Calendar, Wrench, FileText, ArrowRight, CheckCircle2, Clock, ClipboardList, Sparkles, X, Copy, Loader2, RefreshCw, FileDown } from "lucide-react";

const StatCard = ({ icon: Icon, label, value, hint, testid }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-5" data-testid={testid}>
    <div className="flex items-center gap-3">
      <div className="h-10 w-10 rounded-lg bg-sawali-blue/10 flex items-center justify-center">
        <Icon className="h-5 w-5 text-sawali-blue" />
      </div>
      <div>
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</p>
        <p className="text-2xl font-display font-bold text-slate-900">{value}</p>
        {hint && <p className="text-[11px] text-slate-500 mt-1">{hint}</p>}
      </div>
    </div>
  </div>
);

const NoteCard = ({ to, label, accent, count, lastUpdated, icon: Icon, testid }) => (
  <Link
    to={to}
    className="group rounded-xl border border-slate-200 bg-white p-5 hover:border-current transition flex items-start gap-4"
    style={{ "--brand": accent }}
    data-testid={testid}
  >
    <div className="h-12 w-12 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: accent + "18" }}>
      <Icon className="h-6 w-6" style={{ color: accent }} />
    </div>
    <div className="flex-1 min-w-0">
      <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Mes {label}</p>
      <p className="text-3xl font-display font-bold text-slate-900 leading-tight">{count}</p>
      <p className="text-[11px] text-slate-500 mt-1 truncate">
        {lastUpdated ? `Dernière mise à jour : ${new Date(lastUpdated).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })}` : "Aucun enregistrement"}
      </p>
    </div>
    <ArrowRight className="h-4 w-4 text-slate-400 group-hover:translate-x-1 transition-transform" style={{ color: accent }} />
  </Link>
);

export default function ClientDashboard() {
  const [data, setData] = useState(null);
  const [notes, setNotes] = useState({ reports: { count: 0, last_updated: null }, suivis: { count: 0, last_updated: null } });
  const [features, setFeatures] = useState({ show_reports_button: true, show_suivis_button: true });
  const [smartFeatures, setSmartFeatures] = useState({ whatsapp: true, sms: true, ai: true, payments: true });
  const [showAi, setShowAi] = useState(false);

  useEffect(() => {
    apiClient.get("/me/account").then((r) => setData(r.data)).catch(() => {});
    apiClient.get("/me/notes-summary").then((r) => setNotes(r.data)).catch(() => {});
    apiClient.get("/company-info").then((r) => {
      if (r.data?.portal_features) setFeatures(r.data.portal_features);
    }).catch(() => {});
    apiClient.get("/me/features").then((r) => setSmartFeatures(r.data?.features || {})).catch(() => {});
  }, []);
  if (!data) return <p className="text-slate-500">Chargement...</p>;

  const s = data.stats;
  return (
    <div className="space-y-8" data-testid="client-dashboard">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-sawali-blue">Espace Client</p>
          <h1 className="text-3xl font-display font-bold">Bonjour, {data.user.full_name.split(" ")[0]}</h1>
          <p className="text-sm text-slate-500 mt-1">Voici l'état de votre compte aujourd'hui.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => smartFeatures.ai && setShowAi(true)}
            disabled={!smartFeatures.ai}
            title={smartFeatures.ai ? "Ouvrir la synthèse IA" : "Fonctionnalité Génération IA non activée — contactez votre administrateur"}
            className={`inline-flex items-center gap-2 rounded-lg text-white px-4 py-2 text-sm shadow-sm transition ${
              smartFeatures.ai
                ? "bg-gradient-to-r from-fuchsia-600 to-violet-600 hover:from-fuchsia-700 hover:to-violet-700"
                : "bg-slate-300 cursor-not-allowed"
            }`}
            data-testid="dashboard-ai-summary-btn"
          >
            <Sparkles className="h-4 w-4" /> Synthèse IA
          </button>
          <Link to="/portal/appointments" className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="dashboard-cta-rdv">
            Demander un rendez-vous <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Calendar} label="Rendez-vous" value={s.appointments} hint={`${s.appointments_pending} en attente`} testid="stat-appointments" />
        <StatCard icon={Wrench} label="Interventions" value={s.interventions} testid="stat-interventions" />
        <StatCard icon={FileText} label="Documents" value={s.documents} testid="stat-documents" />
        <StatCard icon={CheckCircle2} label="Statut" value={data.user.account_status === "active" ? "Actif" : "Inactif"} testid="stat-status" />
      </div>

      {(features.show_reports_button || features.show_suivis_button) && (
        <div className="grid sm:grid-cols-2 gap-4" data-testid="dashboard-notes-section">
          {features.show_reports_button && (
            <NoteCard to="/portal/notes/reports" label="rapports" accent="#1E90FF" count={notes.reports.count} lastUpdated={notes.reports.last_updated} icon={FileText} testid="dashboard-reports-btn" />
          )}
          {features.show_suivis_button && (
            <NoteCard to="/portal/notes/suivis" label="suivis" accent="#10B981" count={notes.suivis.count} lastUpdated={notes.suivis.last_updated} icon={ClipboardList} testid="dashboard-suivis-btn" />
          )}
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-6">
        <div className="rounded-xl border border-slate-200 bg-white p-6" data-testid="recent-appointments">
          <h2 className="font-display font-semibold flex items-center gap-2"><Clock className="h-4 w-4 text-sawali-blue" /> Rendez-vous récents</h2>
          <ul className="mt-4 divide-y divide-slate-100">
            {data.recent_appointments.length === 0 && <p className="text-sm text-slate-500">Aucun rendez-vous.</p>}
            {data.recent_appointments.map((a) => (
              <li key={a.id} className="py-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{a.subject}</p>
                  <p className="text-xs text-slate-500">{new Date(a.scheduled_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</p>
                </div>
                <Badge status={a.status} />
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-6" data-testid="recent-interventions">
          <h2 className="font-display font-semibold flex items-center gap-2"><Wrench className="h-4 w-4 text-sawali-blue" /> Interventions récentes</h2>
          <ul className="mt-4 divide-y divide-slate-100">
            {data.recent_interventions.length === 0 && <p className="text-sm text-slate-500">Aucune intervention enregistrée.</p>}
            {data.recent_interventions.map((i) => (
              <li key={i.id} className="py-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{i.title}</p>
                  <p className="text-xs text-slate-500">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</p>
                </div>
                <Badge status={i.status} />
              </li>
            ))}
          </ul>
        </div>
      </div>
      {showAi && <AiSummaryModal onClose={() => setShowAi(false)} />}
    </div>
  );
}

const Badge = ({ status }) => {
  const map = {
    pending: ["Attente", "bg-amber-100 text-amber-700"],
    confirmed: ["Confirmé", "bg-sky-100 text-sky-700"],
    cancelled: ["Annulé", "bg-rose-100 text-rose-700"],
    completed: ["Terminé", "bg-emerald-100 text-emerald-700"],
    in_progress: ["En cours", "bg-violet-100 text-violet-700"],
    planned: ["Planifié", "bg-slate-100 text-slate-700"],
  };
  const [label, cls] = map[status] || [status, "bg-slate-100 text-slate-700"];
  return <span className={`text-xs px-2 py-1 rounded ${cls}`}>{label}</span>;
};

// ====================================================================
// AI Summary modal — fetches recent WhatsApp messages, lets the user
// filter by date range / client / direction, sends them to the
// /me/ai/summarize endpoint and displays the rendered summary.
// ====================================================================
function AiSummaryModal({ onClose }) {
  const [tab, setTab] = useState("generate"); // generate | history
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(7);
  const [clientFilter, setClientFilter] = useState("");
  const [direction, setDirection] = useState("all");
  const [target, setTarget] = useState("");
  const [context, setContext] = useState("");
  const [summary, setSummary] = useState("");
  const [provider, setProvider] = useState("");
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/whatsapp/history", { params: { limit: 300 } });
      setMessages(Array.isArray(r.data) ? r.data : []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    setHistoryLoading(true);
    try {
      const r = await apiClient.get("/me/ai/summaries", { params: { limit: 100 } });
      setHistory(Array.isArray(r.data) ? r.data : []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => { if (tab === "history") loadHistory(); }, [tab]);

  const deleteSummary = async (id) => {
    if (!window.confirm("Supprimer cette synthèse ?")) return;
    try {
      await apiClient.delete(`/me/ai/summaries/${id}`);
      toast.success("Synthèse supprimée");
      await loadHistory();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const [convertingId, setConvertingId] = useState(null);
  const convertToReport = async (h) => {
    const defaultTitle = h.target ? `Synthèse IA — ${h.target}` : `Synthèse IA — ${(h.created_at || "").slice(0, 10)}`;
    const title = window.prompt("Titre du rapport :", defaultTitle);
    if (!title) return;
    const isPrivate = window.confirm(
      "Voulez-vous rendre ce rapport PRIVÉ ?\n\n" +
      "OK = Privé (visible uniquement par vous et les administrateurs)\n" +
      "Annuler = Public (partagé avec les autres utilisateurs du même client)",
    );
    setConvertingId(h.id);
    try {
      const r = await apiClient.post(`/me/ai/summaries/${h.id}/to-report`, {
        title,
        is_private: isPrivate,
      });
      const numero = r.data?.report?.numero || "";
      toast.success(`Rapport ${numero} créé. Retrouvez-le dans "Rapports".`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de conversion");
    } finally {
      setConvertingId(null);
    }
  };

  const clientOptions = useMemo(() => {
    const seen = new Set();
    const out = [];
    messages.forEach((m) => {
      const key = m.client_id || "";
      if (!key || seen.has(key)) return;
      seen.add(key);
      out.push({ id: key, label: m.recipient_label || key });
    });
    return out;
  }, [messages]);

  const filtered = useMemo(() => {
    const cutoff = Date.now() - days * 24 * 3600 * 1000;
    return messages.filter((m) => {
      const ts = m.created_at ? new Date(m.created_at).getTime() : 0;
      if (ts && ts < cutoff) return false;
      if (clientFilter && m.client_id !== clientFilter) return false;
      if (direction !== "all" && m.direction !== direction) return false;
      return true;
    });
  }, [messages, days, clientFilter, direction]);

  const run = async () => {
    if (filtered.length === 0) { toast.error("Aucun message dans la fenêtre sélectionnée"); return; }
    setRunning(true); setSummary(""); setProvider("");
    try {
      const r = await apiClient.post("/me/ai/summarize", {
        messages: filtered,
        target: target || undefined,
        context: context || undefined,
      });
      setSummary(r.data?.summary || "");
      setProvider(r.data?.provider || "");
      if (!r.data?.summary) toast.message("Synthèse vide.");
      else toast.success(`Synthèse générée via ${r.data?.provider || "IA"}`);
      // Mark history as stale so a switch to the "Historique" tab re-fetches.
      setHistory([]);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de synthèse");
    } finally {
      setRunning(false);
    }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(summary); toast.success("Synthèse copiée"); }
    catch { toast.error("Copie impossible"); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="ai-summary-modal"
    >
      <div className="w-full max-w-3xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-gradient-to-r from-fuchsia-50 to-violet-50">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-fuchsia-600" /> Synthèse IA des conversations WhatsApp
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        {/* Tabs */}
        <div className="flex gap-0.5 px-5 pt-3 border-b border-slate-100" data-testid="ai-summary-tabs">
          <button
            onClick={() => setTab("generate")}
            className={`px-3 py-2 text-xs font-semibold rounded-t-md transition ${
              tab === "generate"
                ? "bg-white text-fuchsia-700 ring-1 ring-fuchsia-200 ring-b-0"
                : "text-slate-500 hover:text-slate-800"
            }`}
            data-testid="ai-summary-tab-generate"
          >
            Générer
          </button>
          <button
            onClick={() => setTab("history")}
            className={`px-3 py-2 text-xs font-semibold rounded-t-md transition ${
              tab === "history"
                ? "bg-white text-fuchsia-700 ring-1 ring-fuchsia-200 ring-b-0"
                : "text-slate-500 hover:text-slate-800"
            }`}
            data-testid="ai-summary-tab-history"
          >
            Mes synthèses ({history.length || "—"})
          </button>
        </div>
        {tab === "generate" ? (
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <div className="grid sm:grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-semibold block mb-1">Période</label>
              <select
                value={days}
                onChange={(e) => setDays(parseInt(e.target.value, 10))}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="ai-summary-days"
              >
                <option value="1">Dernières 24 h</option>
                <option value="3">3 derniers jours</option>
                <option value="7">7 derniers jours</option>
                <option value="14">14 derniers jours</option>
                <option value="30">30 derniers jours</option>
                <option value="90">90 derniers jours</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Client</label>
              <select
                value={clientFilter}
                onChange={(e) => setClientFilter(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="ai-summary-client"
              >
                <option value="">Tous les clients</option>
                {clientOptions.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Sens</label>
              <select
                value={direction}
                onChange={(e) => setDirection(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="ai-summary-direction"
              >
                <option value="all">Tous</option>
                <option value="outbound">Envoyés</option>
                <option value="inbound">Reçus</option>
              </select>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold block mb-1">Cible (facultatif)</label>
              <input
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="Nom du client, ex: ACME"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="ai-summary-target"
              />
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Contexte (facultatif)</label>
              <input
                value={context}
                onChange={(e) => setContext(e.target.value)}
                placeholder="Ex: préparer le compte-rendu pour la réunion"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                data-testid="ai-summary-context"
              />
            </div>
          </div>
          <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 text-xs text-slate-600 flex items-center justify-between">
            <span>
              <strong className="text-slate-800">{filtered.length}</strong> message(s) sélectionné(s)
              {loading ? " · chargement…" : ""}
            </span>
            <button
              onClick={load}
              className="inline-flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-900"
              data-testid="ai-summary-refresh"
            >
              <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
            </button>
          </div>

          {summary && (
            <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-4 space-y-2" data-testid="ai-summary-result">
              <div className="flex items-center justify-between">
                <p className="text-[11px] uppercase tracking-wider text-emerald-700 font-semibold">
                  Synthèse {provider ? `· ${provider}` : ""}
                </p>
                <button onClick={copy} className="text-[11px] inline-flex items-center gap-1 text-emerald-700 hover:text-emerald-900" data-testid="ai-summary-copy">
                  <Copy className="h-3 w-3" /> Copier
                </button>
              </div>
              <p className="whitespace-pre-line text-sm text-slate-800 leading-relaxed">{summary}</p>
            </div>
          )}
        </div>
        ) : (
        <div className="flex-1 overflow-y-auto px-5 py-4" data-testid="ai-summary-history">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-slate-500">
              {historyLoading ? "Chargement…" : `${history.length} synthèse(s) enregistrée(s)`}
            </p>
            <button
              onClick={loadHistory}
              className="inline-flex items-center gap-1 text-[11px] text-slate-600 hover:text-slate-900"
              data-testid="ai-summary-history-refresh"
            >
              <RefreshCw className={`h-3 w-3 ${historyLoading ? "animate-spin" : ""}`} /> Actualiser
            </button>
          </div>
          {!historyLoading && history.length === 0 ? (
            <p className="text-sm text-slate-400 italic text-center py-8">
              Aucune synthèse enregistrée. Générez-en une depuis l'onglet « Générer ».
            </p>
          ) : (
            <ul className="space-y-3">
              {history.map((h) => (
                <li key={h.id} className="rounded-lg ring-1 ring-slate-200 bg-white p-3" data-testid={`ai-summary-history-row-${h.id}`}>
                  <div className="flex items-center justify-between text-[11px] text-slate-500 mb-1">
                    <span className="inline-flex items-center gap-2">
                      <span className={`px-1.5 py-0.5 rounded ${h.provider === "openai" ? "bg-emerald-100 text-emerald-800" : "bg-violet-100 text-violet-800"}`}>
                        {h.provider}{h.model ? ` · ${h.model}` : ""}
                      </span>
                      <span>{h.created_at ? new Date(h.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}</span>
                      {h.target && <span className="text-slate-700">· {h.target}</span>}
                      {h.messages_count != null && <span className="text-slate-400">({h.messages_count} msg)</span>}
                    </span>
                    <span className="flex items-center gap-2">
                      <button
                        onClick={() => convertToReport(h)}
                        disabled={convertingId === h.id}
                        className="inline-flex items-center gap-1 text-[11px] rounded bg-sawali-blue text-white px-2 py-0.5 hover:bg-sawali-blue-light disabled:opacity-50"
                        title="Créer un rapport à partir de cette synthèse"
                        data-testid={`ai-summary-history-to-report-${h.id}`}
                      >
                        {convertingId === h.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileDown className="h-3 w-3" />}
                        Rapport
                      </button>
                      <button
                        onClick={async () => {
                          try { await navigator.clipboard.writeText(h.summary || ""); toast.success("Copiée"); }
                          catch { toast.error("Copie impossible"); }
                        }}
                        className="text-slate-500 hover:text-slate-900"
                        title="Copier"
                        data-testid={`ai-summary-history-copy-${h.id}`}
                      >
                        <Copy className="h-3 w-3" />
                      </button>
                      <button
                        onClick={() => deleteSummary(h.id)}
                        className="text-rose-500 hover:text-rose-700"
                        title="Supprimer"
                        data-testid={`ai-summary-history-delete-${h.id}`}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </span>
                  </div>
                  {h.context && <p className="text-[11px] text-slate-500 italic mb-1">Contexte : {h.context}</p>}
                  <p className="whitespace-pre-line text-sm text-slate-800 leading-relaxed">{h.summary}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
        )}
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200 bg-slate-50">
          <button onClick={onClose} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2">Fermer</button>
          {tab === "generate" && (
            <button
              onClick={run}
              disabled={running || filtered.length === 0}
              className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-gradient-to-r from-fuchsia-600 to-violet-600 hover:from-fuchsia-700 hover:to-violet-700 text-white px-4 py-2 disabled:opacity-50"
              data-testid="ai-summary-run"
            >
              {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {running ? "Génération…" : "Générer la synthèse"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

