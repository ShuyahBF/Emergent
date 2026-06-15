import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Calendar, Wrench, FileText, ArrowRight, CheckCircle2, Clock, ClipboardList, Sparkles, X, Copy, Loader2, RefreshCw, FileDown, MessageCircle as MessageCircleIcon, Ticket, Eye, UserPlus, MessageSquare, CreditCard, AlertTriangle } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import BrochuresWidget from "@/components/BrochuresWidget";
import WeatherWidget from "@/components/WeatherWidget";

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
  const [notes, setNotes] = useState({
    reports: { count: 0, last_updated: null },
    suivis: { count: 0, last_updated: null },
    notes: { count: 0, last_updated: null },
    tasks: { count: 0, last_updated: null },
  });
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
          <p className="text-xs uppercase tracking-[0.2em] text-sawali-blue">Espace Loois</p>
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

      {/* Iter43-fix20 — Widget météo détaillé dans le dashboard portail */}
      <WeatherWidget variant="detailed" placement="portal" />

      {/* Iter38r-fix8b — Notes & Tâches s'affichent toujours, Rapports/Suivis selon feature flag */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4" data-testid="dashboard-notes-section">
        {features.show_reports_button && (
          <NoteCard to="/portal/notes/reports" label="rapports" accent="#1E90FF" count={notes.reports.count} lastUpdated={notes.reports.last_updated} icon={FileText} testid="dashboard-reports-btn" />
        )}
        {features.show_suivis_button && (
          <NoteCard to="/portal/notes/suivis" label="suivis" accent="#10B981" count={notes.suivis.count} lastUpdated={notes.suivis.last_updated} icon={ClipboardList} testid="dashboard-suivis-btn" />
        )}
        {/* Iter35g — Notes & Tâches personnelles (transcription vocale Whisper incluse) */}
        <NoteCard to="/portal/notes/notes" label="notes" accent="#A855F7" count={notes.notes.count} lastUpdated={notes.notes.last_updated} icon={FileText} testid="dashboard-notes-btn" />
        <NoteCard to="/portal/notes/tasks" label="tâches" accent="#F59E0B" count={notes.tasks.count} lastUpdated={notes.tasks.last_updated} icon={ClipboardList} testid="dashboard-tasks-btn" />
      </div>

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
      {/* Iter35o — Tickets en attente */}
      <TicketsPendingCard />
      {/* Iter38c — Carte dépenses non justifiées (utilisateurs suivis avec accès Caisse) */}
      <UnjustifiedExpensesCard />
      {/* Iter35m — Synthèse des médias WhatsApp reçus */}
      {smartFeatures.whatsapp && <WaMediaSummaryCard />}
      {/* Iter38r-fix9p — Brochures PDF (admin/superviseur uniquement) */}
      <BrochuresWidget />
      {showAi && <AiSummaryModal onClose={() => setShowAi(false)} />}
    </div>
  );
}

// ====================================================================
// Iter38c — Unjustified expenses card (tracked users with cashier access)
// Shows the sum of THIS user's expenses still unjustified (incl. those past
// the deadline → which will be deducted from next payslip).
// ====================================================================
function UnjustifiedExpensesCard() {
  const { user } = useAuth() || {};
  const [data, setData] = useState(null);
  // Iter38m — Show whenever the user has any pending expense (either created by
  // them or attributed to them as employee). The backend returns count=0 if none.
  useEffect(() => {
    if (!user) return;
    apiClient.get("/cashier/expenses/me/dashboard-card")
      .then((r) => setData(r.data))
      .catch(() => setData(null));
  }, [user]);
  if (!data || (data.count || 0) === 0) return null;
  const hasLate = (data.late_unjustified || 0) > 0;
  return (
    <Link to="/portal/cash" className="block rounded-xl border-2 border-rose-200 bg-gradient-to-br from-rose-50 to-amber-50 p-5 hover:shadow-md transition-shadow"
      data-testid="dashboard-unjustified-expenses-card">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2 mb-2">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center ${hasLate ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700"}`}>
            {hasLate ? <AlertTriangle size={20} /> : <Clock size={20} />}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Mes dépenses caisse à justifier</h3>
            <p className="text-xs text-slate-500">
              {data.deadline_hours === 0 ? "Pas de délai limite" : `Délai : ${data.deadline_hours}h`}
            </p>
          </div>
        </div>
        <ArrowRight size={18} className="text-slate-400" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div data-testid="dashboard-unjust-total">
          <p className="text-xs text-slate-500">Total non justifiées</p>
          <p className="text-xl font-bold text-amber-900">
            {Number(data.total_unjustified || 0).toLocaleString("fr-FR")} {data.currency}
          </p>
          <p className="text-xs text-slate-400 mt-0.5">{data.count} opération(s)</p>
        </div>
        <div data-testid="dashboard-unjust-late">
          <p className="text-xs text-rose-600">Dont hors délai</p>
          <p className={`text-xl font-bold ${hasLate ? "text-rose-700" : "text-slate-400"}`}>
            {Number(data.late_unjustified || 0).toLocaleString("fr-FR")} {data.currency}
          </p>
          {hasLate && <p className="text-xs text-rose-500 mt-0.5">Sera déduit du salaire</p>}
        </div>
      </div>
    </Link>
  );
}

// ====================================================================
// Iter35o — Tickets pending card (dashboard).
// Shows total non-closed tickets + breakdown by status (open / in_progress
// / suspended). Links to /portal/tickets.
// ====================================================================
function TicketsPendingCard() {
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  useEffect(() => {
    apiClient.get("/me/tickets/pending-count").then((r) => setData(r.data)).catch(() => setData(null));
    apiClient.get("/me/dashboard/ticket-stats?days=30").then((r) => setStats(r.data)).catch(() => setStats(null));
  }, []);
  if (!data) return null;
  const { count, by_status = {} } = data;
  return (
    <section
      className={`rounded-xl border p-5 space-y-3 ${count > 0 ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}
      data-testid="dashboard-tickets-pending"
    >
      <div className="flex items-center gap-4">
        <div className={`h-12 w-12 rounded-lg flex items-center justify-center ${count > 0 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
          <Ticket className="h-6 w-6" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className="text-3xl font-display font-bold tabular-nums" data-testid="dashboard-tickets-count">{count}</span>
            <span className="text-sm text-slate-600">ticket(s) d'intervention en cours</span>
          </div>
          {count > 0 && (
            <div className="flex flex-wrap gap-2 mt-2 text-[11px]">
              {by_status.open > 0 && <span className="rounded-full bg-amber-100 ring-1 ring-amber-300 text-amber-800 px-2 py-0.5">🟡 En attente : <strong>{by_status.open}</strong></span>}
              {by_status.in_progress > 0 && <span className="rounded-full bg-sky-100 ring-1 ring-sky-300 text-sky-800 px-2 py-0.5">🔵 En cours : <strong>{by_status.in_progress}</strong></span>}
              {by_status.suspended > 0 && <span className="rounded-full bg-slate-200 ring-1 ring-slate-300 text-slate-800 px-2 py-0.5">⏸️ Suspendus : <strong>{by_status.suspended}</strong></span>}
            </div>
          )}
        </div>
        <a
          href="/portal/tickets"
          className={`shrink-0 inline-flex items-center gap-1 text-sm font-medium rounded-lg px-3 py-2 ring-1 transition ${count > 0 ? "bg-amber-600 text-white ring-amber-700 hover:bg-amber-700" : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"}`}
          data-testid="dashboard-tickets-cta"
        >
          Ouvrir <ArrowRight className="h-4 w-4" />
        </a>
      </div>
      {/* Iter35p — Score de résolution (30 derniers jours) */}
      {stats && stats.me && stats.me.closed_count > 0 && (
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/60 p-3 grid sm:grid-cols-4 gap-2" data-testid="dashboard-ticket-stats">
          <div className="sm:col-span-4 text-[11px] uppercase tracking-widest font-semibold text-emerald-800 mb-1">
            🏁 Mon score résolution tickets (30 j)
          </div>
          <ResolutionTile label="Délai moyen" value={fmtDuration(stats.me.avg_seconds)} primary testid="ticket-stat-avg" />
          <ResolutionTile label="Médiane" value={fmtDuration(stats.me.median_seconds)} testid="ticket-stat-median" />
          <ResolutionTile label="Plus rapide" value={fmtDuration(stats.me.fastest_seconds)} testid="ticket-stat-fastest" />
          <ResolutionTile label="Tickets clôturés" value={`${stats.me.closed_count}`} testid="ticket-stat-count" />
          {stats.team && stats.team.length > 1 && (
            <details className="sm:col-span-4">
              <summary className="text-[11px] text-emerald-800 font-semibold cursor-pointer hover:underline" data-testid="ticket-stats-team-toggle">
                🏆 Classement équipe ({stats.team.length})
              </summary>
              <ol className="mt-2 space-y-1.5 text-xs">
                {stats.team.map((m, i) => (
                  <li key={m.user_id} className="flex items-center justify-between rounded bg-white ring-1 ring-emerald-200 px-2 py-1.5">
                    <span className="flex items-center gap-2 min-w-0">
                      <span className={`text-[10px] font-mono w-5 text-center ${i === 0 ? "text-amber-600 font-bold" : "text-slate-500"}`}>#{i + 1}</span>
                      <span className="truncate">{m.label}</span>
                    </span>
                    <span className="flex items-center gap-3 text-[11px] tabular-nums shrink-0">
                      <span className="text-emerald-700 font-semibold">{fmtDuration(m.avg_seconds)}</span>
                      <span className="text-slate-500">{m.closed_count} clôturé(s)</span>
                    </span>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

const ResolutionTile = ({ label, value, primary, testid }) => (
  <div className={`rounded ring-1 px-2 py-1.5 ${primary ? "bg-emerald-600 text-white ring-emerald-700 shadow-sm" : "bg-white ring-emerald-200 text-emerald-900"}`} data-testid={testid}>
    <p className={`text-[9px] uppercase tracking-wider ${primary ? "text-white/80" : "text-emerald-700/80"}`}>{label}</p>
    <p className="text-base font-display font-bold tabular-nums leading-tight">{value}</p>
  </div>
);

// ====================================================================
// Iter35m — WhatsApp media summary card (dashboard).
// Shows counts by kind + top contacts + last 5 thumbnails over a chosen
// trailing window (7/30/90 days).
// ====================================================================
// Iter36a — Top senders list with Import / Eye preview / Open conversation actions
function TopSendersList({ items, onChanged }) {
  const [openPreview, setOpenPreview] = useState(null); // {phone_digits}
  const [importing, setImporting] = useState(null);
  const [imported, setImported] = useState({});

  const doImport = async (c) => {
    setImporting(c.phone_digits);
    try {
      const r = await apiClient.post("/me/wa-import-by-phone", {
        phone_digits: c.phone_digits,
        name: c.contact_name,
      });
      setImported((p) => ({ ...p, [c.phone_digits]: r.data?.contact?.id || true }));
      toast.success(r.data?.already_present
        ? `${c.contact_name || c.phone_digits} : déjà présent`
        : `${c.contact_name || c.phone_digits} ajouté au répertoire ✓`);
      if (onChanged) onChanged();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'import");
    } finally {
      setImporting(null);
    }
  };

  return (
    <ul className="space-y-1.5" data-testid="top-senders-list">
      {items.map((c, i) => {
        const isExpanded = openPreview === c.phone_digits;
        const isImporting = importing === c.phone_digits;
        const wasImported = imported[c.phone_digits];
        const directoryId = wasImported && wasImported !== true ? wasImported : c.contact_id;
        const inDirectory = !!c.in_directory || !!wasImported;
        return (
          <li key={c.phone_digits || i} className="rounded ring-1 ring-slate-200 bg-white p-2" data-testid={`top-sender-${c.phone_digits || i}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className="text-emerald-700 font-semibold tabular-nums text-xs bg-emerald-50 px-1.5 py-0.5 rounded ring-1 ring-emerald-200" data-testid={`top-sender-count-${c.phone_digits}`}>×{c.count}</span>
                <span className="text-slate-700 truncate text-sm" title={`+${c.phone_digits}`}>
                  {c.contact_name || `+${c.phone_digits}`}
                </span>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                {!inDirectory && (
                  <button
                    onClick={() => doImport(c)}
                    disabled={isImporting}
                    className="inline-flex items-center gap-1 rounded text-[10px] font-medium px-2 py-1 bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
                    title="Importer dans le répertoire"
                    data-testid={`top-sender-import-${c.phone_digits}`}
                  >
                    {isImporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <UserPlus className="h-3 w-3" />}
                    Importer
                  </button>
                )}
                {inDirectory && (
                  <span className="text-[9px] font-semibold uppercase tracking-wider text-emerald-700 bg-emerald-50 ring-1 ring-emerald-200 px-1.5 py-0.5 rounded" data-testid={`top-sender-in-directory-${c.phone_digits}`}>
                    ✓ Répertoire
                  </span>
                )}
                <button
                  onClick={() => setOpenPreview(isExpanded ? null : c.phone_digits)}
                  className="inline-flex items-center justify-center rounded p-1 text-slate-500 hover:text-slate-900 hover:bg-slate-100 transition"
                  title="Voir le dernier message"
                  data-testid={`top-sender-eye-${c.phone_digits}`}
                >
                  <Eye className="h-3.5 w-3.5" />
                </button>
                <Link
                  to={`/portal/contacts?open=${directoryId || ""}&phone=${c.phone_digits || ""}`}
                  className="inline-flex items-center justify-center rounded p-1 text-emerald-600 hover:text-emerald-800 hover:bg-emerald-50 transition"
                  title="Ouvrir la conversation"
                  data-testid={`top-sender-open-${c.phone_digits}`}
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                </Link>
              </div>
            </div>
            {isExpanded && (
              <div className="mt-1.5 pt-1.5 border-t border-slate-100 text-[11px] text-slate-600" data-testid={`top-sender-preview-${c.phone_digits}`}>
                {c.last_message_preview ? (
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[9px] font-bold uppercase px-1 py-0.5 rounded ${c.last_message_direction === "inbound" ? "bg-emerald-100 text-emerald-700" : "bg-sky-100 text-sky-700"}`}>
                        {c.last_message_direction === "inbound" ? "← Reçu" : "→ Envoyé"}
                      </span>
                      <span className="text-[10px] text-slate-400">
                        {c.last_message_at ? new Date(c.last_message_at).toLocaleString("fr-FR") : ""}
                      </span>
                    </div>
                    <p className="italic text-slate-700">{c.last_message_preview}</p>
                  </div>
                ) : (
                  <p className="italic text-slate-400">Aucun message récent.</p>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function WaMediaSummaryCard() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  // Iter35n — Reply-time stats (avg/median/replies) for the same window
  const [reply, setReply] = useState(null);

  const reload = React.useCallback(() => {
    setLoading(true);
    Promise.all([
      apiClient.get(`/me/dashboard/wa-media-summary?days=${days}`).then((r) => r.data).catch(() => null),
      apiClient.get(`/me/dashboard/wa-reply-stats?days=${days}`).then((r) => r.data).catch(() => null),
    ]).then(([m, rs]) => {
      setData(m);
      setReply(rs);
      setLoading(false);
    });
  }, [days]);

  useEffect(() => { reload(); }, [reload]);

  const counts = data?.counts || { image: 0, audio: 0, video: 0, document: 0, total: 0 };
  const top = data?.top_contacts || [];
  const last = data?.last_items || [];

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-6 space-y-4" data-testid="dashboard-wa-media-summary">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-lg bg-emerald-50 flex items-center justify-center">
            <MessageCircleIcon className="h-4 w-4 text-emerald-600" />
          </div>
          <div>
            <h2 className="font-display font-semibold text-slate-900">Médias WhatsApp reçus</h2>
            <p className="text-[11px] text-slate-500">Synthèse des images, audios, vidéos et PDF reçus</p>
          </div>
        </div>
        <div className="inline-flex rounded-lg ring-1 ring-slate-200 bg-slate-50 p-0.5" data-testid="wa-media-days-toggle">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`text-xs px-2.5 py-1 rounded-md transition ${days === d ? "bg-emerald-600 text-white shadow-sm" : "text-slate-600 hover:bg-white"}`}
              data-testid={`wa-media-days-${d}`}
            >
              {d} j
            </button>
          ))}
        </div>
      </header>

      {loading ? (
        <p className="text-sm text-slate-500 italic">Chargement…</p>
      ) : (
        <>
          {/* Iter35n — Reply-time score (per-user + optional team leaderboard) */}
          {reply && <ReplyTimeBlock reply={reply} />}

          {/* Counts row */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            <CountTile label="Total" value={counts.total} color="slate" testid="wa-media-count-total" />
            <CountTile label="Images" value={counts.image} color="sky" testid="wa-media-count-image" />
            <CountTile label="Audios" value={counts.audio} color="fuchsia" testid="wa-media-count-audio" />
            <CountTile label="Vidéos" value={counts.video} color="amber" testid="wa-media-count-video" />
            <CountTile label="PDF / Doc." value={counts.document} color="emerald" testid="wa-media-count-document" />
          </div>

          <div className="grid lg:grid-cols-2 gap-4">
            {/* Top contacts — Iter36a: import button + last-message preview + open chat */}
            <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3" data-testid="wa-media-top-contacts">
              <p className="text-[11px] uppercase tracking-widest text-slate-500 font-semibold mb-2">Top expéditeurs</p>
              {top.length === 0 ? (
                <p className="text-xs italic text-slate-400">Aucun média reçu sur la période.</p>
              ) : (
                <TopSendersList items={top} onChanged={() => reload && reload()} />
              )}
            </div>

            {/* Last items thumbnails */}
            <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3" data-testid="wa-media-last-items">
              <p className="text-[11px] uppercase tracking-widest text-slate-500 font-semibold mb-2">Derniers reçus</p>
              {last.length === 0 ? (
                <p className="text-xs italic text-slate-400">Aucun média sur la période.</p>
              ) : (
                <ul className="grid grid-cols-5 gap-2">
                  {last.map((it) => (
                    <li key={it.id}>
                      <a
                        href={`/portal/contacts${it.contact_id ? `?open=${it.contact_id}` : ""}`}
                        title={`${it.contact_name || it.from || "?"} — ${new Date(it.received_at || it.created_at).toLocaleString("fr-FR")}`}
                        className="block aspect-square rounded ring-1 ring-slate-200 bg-white overflow-hidden hover:ring-emerald-400 transition"
                        data-testid={`wa-media-last-${it.id}`}
                      >
                        {it.media_kind === "image" ? (
                          <img src={absoluteFileUrl(it.media_url)} alt="" className="h-full w-full object-cover" loading="lazy" />
                        ) : (
                          <div className="h-full w-full flex flex-col items-center justify-center text-[10px] text-slate-500 p-1">
                            <span className="uppercase font-semibold text-[8px]">{it.media_kind || "doc"}</span>
                            <span className="truncate w-full text-center">{(it.media_filename || "").slice(0, 14)}</span>
                          </div>
                        )}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}

const CountTile = ({ label, value, color, testid }) => {
  const ring = {
    slate: "ring-slate-300 text-slate-800",
    sky: "ring-sky-300 text-sky-700",
    fuchsia: "ring-fuchsia-300 text-fuchsia-700",
    amber: "ring-amber-300 text-amber-700",
    emerald: "ring-emerald-300 text-emerald-700",
  }[color] || "ring-slate-300 text-slate-800";
  return (
    <div className={`rounded-lg ring-1 bg-white p-2.5 text-center ${ring}`} data-testid={testid}>
      <p className="text-2xl font-display font-bold tabular-nums">{value}</p>
      <p className="text-[10px] uppercase tracking-wider mt-0.5 opacity-80">{label}</p>
    </div>
  );
};

// Iter35n — Format a duration in seconds to a compact FR string
const fmtDuration = (s) => {
  if (s == null) return "—";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 24 * 3600) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return m ? `${h} h ${m} min` : `${h} h`;
  }
  return `${Math.floor(s / 86400)} j`;
};

// Iter35n — Reply-time card body. Shows the user's avg/median/replies +
// (when elevated) a leaderboard of the fastest teammates.
const ReplyTimeBlock = ({ reply }) => {
  const me = reply?.me || {};
  const team = reply?.team || [];
  const days = reply?.days || 7;
  const noData = !me.replies;
  return (
    <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/60 p-3 space-y-2" data-testid="wa-reply-stats">
      <div className="flex items-center gap-2 mb-1">
        <p className="text-[11px] uppercase tracking-widest text-emerald-800 font-semibold">
          ⚡ Mon score réactivité WhatsApp
        </p>
        <span className="text-[10px] text-emerald-700/70 ml-auto">{days} j</span>
      </div>
      {noData ? (
        <p className="text-xs text-emerald-800/70 italic">
          Aucun message répondu sur la période. Réponds rapidement à un message reçu pour voir ton score apparaître ici.
        </p>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <ReplyTile label="Temps moyen" value={fmtDuration(me.avg_seconds)} primary testid="wa-reply-avg" />
          <ReplyTile label="Médiane" value={fmtDuration(me.median_seconds)} testid="wa-reply-median" />
          <ReplyTile label="Plus rapide" value={fmtDuration(me.fastest_seconds)} testid="wa-reply-fastest" />
          <ReplyTile label="Réponses" value={`${me.replies}`} testid="wa-reply-count" />
        </div>
      )}
      {team.length > 1 && (
        <details className="mt-2">
          <summary className="text-[11px] text-emerald-800 font-semibold cursor-pointer hover:underline" data-testid="wa-reply-team-toggle">
            🏆 Classement de l'équipe ({team.length})
          </summary>
          <ol className="mt-2 space-y-1.5 text-xs">
            {team.map((t, i) => (
              <li key={t.user_id} className="flex items-center justify-between rounded bg-white ring-1 ring-emerald-200 px-2 py-1.5" data-testid={`wa-reply-team-${i}`}>
                <span className="flex items-center gap-2 min-w-0">
                  <span className={`text-[10px] font-mono w-5 text-center ${i === 0 ? "text-amber-600 font-bold" : "text-slate-500"}`}>#{i + 1}</span>
                  <span className="truncate">{t.label}</span>
                </span>
                <span className="flex items-center gap-3 text-[11px] tabular-nums shrink-0">
                  <span className="text-emerald-700 font-semibold">{fmtDuration(t.avg_seconds)}</span>
                  <span className="text-slate-500">{t.replies} rép.</span>
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
};

const ReplyTile = ({ label, value, primary, testid }) => (
  <div className={`rounded ring-1 px-2 py-1.5 ${primary ? "bg-emerald-600 text-white ring-emerald-700 shadow-sm" : "bg-white ring-emerald-200 text-emerald-900"}`} data-testid={testid}>
    <p className={`text-[9px] uppercase tracking-wider ${primary ? "text-white/80" : "text-emerald-700/80"}`}>{label}</p>
    <p className="text-base font-display font-bold tabular-nums leading-tight">{value}</p>
  </div>
);

const absoluteFileUrl = (u) => {
  if (!u) return "";
  if (u.startsWith("http")) return u;
  const base = process.env.REACT_APP_BACKEND_URL || "";
  return `${base}${u.startsWith("/") ? "" : "/"}${u}`;
};

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

