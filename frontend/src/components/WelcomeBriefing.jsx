import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { X, Ticket, MessageCircle, MessageSquare, MessageSquareText, FileText, Lock, CheckCircle2, TrendingUp, Send, Sparkles, Clock, Banknote, Bot } from "lucide-react";

/*
  Iter35r → Iter36g — Welcome briefing modal.

  Shown right after the first successful login of a session for any user
  (admin/superviseur/tracked). Lists:
    • Pending tickets (open + suspended) in the user's scope
    • Unread WhatsApp + SMS counts
    • The user's own personal notes created within the last N days (admin-tunable)
    • Iter36g: NEW since last visit (tickets + WA inbound + notes) using a
      localStorage "last_seen_at" stamp so a user coming back after the weekend
      sees instantly what piled up while they were away.

  The user must click "J'ai lu" to dismiss. We persist a sessionStorage key so
  the modal only appears once per session.
*/

const SS_KEY = "sawali_welcome_briefing_seen";
const LS_LAST_SEEN = "sawali_portal_last_seen_at";

export default function WelcomeBriefing({ onClose, isComptaStrict = false }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  // Iter43-fix — Le bouton "J'ai lu" n'est actif qu'une fois le contenu lu
  // jusqu'en bas (ou si le contenu tient sans scroll).
  const [canAcknowledge, setCanAcknowledge] = useState(false);
  const scrollRef = useRef(null);

  const checkScrolledBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    // Si le contenu n'est pas plus grand que le conteneur → pas besoin de scroller
    if (el.scrollHeight <= el.clientHeight + 4) {
      setCanAcknowledge(true);
      return;
    }
    // Tolérance de 8px pour absorber les arrondis subpixel / barres de défilement
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
    if (atBottom) setCanAcknowledge(true);
  };

  // Quand le contenu vient d'être rendu (après le chargement), on revérifie
  // si une barre de défilement est nécessaire. Si non, le bouton est libéré.
  useEffect(() => {
    if (!loading) {
      // attendre la prochaine frame pour que le DOM soit mesurable
      const id = window.requestAnimationFrame(checkScrolledBottom);
      return () => window.cancelAnimationFrame(id);
    }
  }, [loading, data]);

  useEffect(() => {
    // Iter36g — pull the saved last_seen stamp BEFORE the request so the
    // backend can compute the "new since last visit" diff. We refresh the
    // stamp ONLY after the user explicitly clicks "J'ai lu" (in dismiss())
    // to guarantee they actually saw the briefing.
    let qs = "";
    try {
      const lastSeen = localStorage.getItem(LS_LAST_SEEN);
      if (lastSeen) qs = `?last_seen_at=${encodeURIComponent(lastSeen)}`;
    } catch { /* noop */ }
    apiClient
      .get(`/me/welcome-briefing${qs}`)
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  const dismiss = () => {
    try {
      sessionStorage.setItem(SS_KEY, "1");
      // Iter36g — refresh the last-seen stamp ONLY on explicit dismissal
      const stamp = data?.server_now || new Date().toISOString();
      localStorage.setItem(LS_LAST_SEEN, stamp);
    } catch { /* noop */ }
    onClose?.();
  };

  // Don't show the modal if everything is empty
  const tickets = data?.tickets || [];
  const unread = data?.unread_messages || { whatsapp: 0, sms: 0, total: 0 };
  const notes = data?.recent_notes || [];
  const health = data?.daily_health || null;
  const sinceLast = data?.since_last_visit || null;
  // Iter38r-fix8d — Expense reminder for tracked users
  const expenseReminder = data?.expense_reminder || null;
  // Iter38r-fix9d — Liluvine PRO auto-reply ROI counter
  const liluAuto = data?.liluvine_autoreply_today || null;
  const hasLiluAuto = !!liluAuto && (liluAuto.today > 0 || liluAuto.last_7d > 0);
  // Iter38r-fix9o (Item 8) — WhatsApp OTP demo signups widget (admins only)
  const waDemo = data?.wa_demo_recent || null;
  const hasWaDemo = !!waDemo && (waDemo.total || 0) > 0;
  // Iter38r-fix8b — Quick KPIs (Rapports/Suivis/Notes/Tâches) so the briefing
  // is never empty for active users.
  const kpis = data?.notes_kpis || null;
  const sharedRecent = kpis?.shared_recent || null;
  const hasSharedRecent = !!sharedRecent && sharedRecent.total > 0;
  const totalKpis = kpis
    ? (kpis.reports?.count || 0) + (kpis.suivis?.count || 0) + (kpis.notes?.count || 0) + (kpis.tasks?.count || 0)
    : 0;
  const hasKpis = totalKpis > 0;
  const hasHealth = !!health && (
    (health.tickets_resolved_yesterday || 0) > 0
    || (health.messages_sent_today || 0) > 0
    || (health.tickets_opened_today || 0) > 0
    || (health.wa_response_rate_24h !== null && health.wa_response_rate_24h !== undefined)
  );
  const hasSinceLast = !!sinceLast && (sinceLast.total_count || 0) > 0;
  const hasExpenseReminder = !!expenseReminder && expenseReminder.count > 0;
  const isEmpty = !loading && tickets.length === 0 && unread.total === 0 && notes.length === 0 && !hasHealth && !hasSinceLast && !hasExpenseReminder && !hasKpis && !hasLiluAuto && !hasSharedRecent && !hasWaDemo;

  if (!loading && isEmpty) {
    // Mark as seen and close silently
    try { sessionStorage.setItem(SS_KEY, "1"); } catch { /* noop */ }
    setTimeout(onClose, 0);
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center p-4 sm:p-8 bg-black/50 overflow-y-auto"
      data-testid="welcome-briefing"
      onClick={(e) => {
        // 2026-02 fork iter108 fix — Allow click-outside to dismiss so the
        // overlay never traps the user on other pages (rapport testing_agent).
        if (e.target === e.currentTarget) dismiss();
      }}
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl my-auto">
        <header className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.3em] text-slate-500">Briefing</p>
            <h2 className="text-xl font-display font-bold text-slate-900">Bienvenue 👋</h2>
            <p className="text-xs text-slate-500 mt-0.5">Voici ce qui vous attend aujourd'hui</p>
          </div>
          <button onClick={dismiss} className="text-slate-400 hover:text-slate-700" data-testid="welcome-briefing-close-x">
            <X className="h-5 w-5" />
          </button>
        </header>

        {loading ? (
          <div className="p-8 text-center text-slate-500">Chargement…</div>
        ) : (
          <div
            ref={scrollRef}
            onScroll={checkScrolledBottom}
            className="p-6 space-y-4 max-h-[60vh] overflow-y-auto"
            data-testid="welcome-briefing-scroll"
          >
            {/* Iter38r-fix8b — Synthèse Rapports / Suivis / Notes / Tâches */}
            {hasKpis && (
              <section className="rounded-lg ring-1 ring-indigo-200 bg-gradient-to-br from-indigo-50/60 via-white to-violet-50/40 p-3" data-testid="welcome-notes-kpis">
                <div className="flex items-center gap-2 mb-2">
                  <FileText className="h-4 w-4 text-indigo-700" />
                  <h3 className="text-sm font-semibold text-indigo-900">Synthèse de votre activité</h3>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {(kpis.reports?.count || 0) > 0 && !isComptaStrict && (
                    <Link to="/portal/notes/reports" onClick={dismiss}
                      className="rounded-lg ring-1 ring-sky-200 bg-sky-50/60 p-2 hover:bg-sky-100 transition"
                      data-testid="welcome-kpi-reports">
                      <div className="flex items-center justify-between">
                        <FileText className="h-4 w-4 text-sky-600" />
                        <span className="text-lg font-display font-bold text-sky-900 leading-none">{kpis.reports.count}</span>
                      </div>
                      <p className="text-[10px] uppercase tracking-wider mt-1 text-sky-800/80">Rapports</p>
                    </Link>
                  )}
                  {(kpis.suivis?.count || 0) > 0 && !isComptaStrict && (
                    <Link to="/portal/notes/suivis" onClick={dismiss}
                      className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/60 p-2 hover:bg-emerald-100 transition"
                      data-testid="welcome-kpi-suivis">
                      <div className="flex items-center justify-between">
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                        <span className="text-lg font-display font-bold text-emerald-900 leading-none">{kpis.suivis.count}</span>
                      </div>
                      <p className="text-[10px] uppercase tracking-wider mt-1 text-emerald-800/80">Suivis</p>
                    </Link>
                  )}
                  {(kpis.notes?.count || 0) > 0 && (
                    <Link to="/portal/notes/notes" onClick={dismiss}
                      className="rounded-lg ring-1 ring-violet-200 bg-violet-50/60 p-2 hover:bg-violet-100 transition"
                      data-testid="welcome-kpi-notes">
                      <div className="flex items-center justify-between">
                        <FileText className="h-4 w-4 text-violet-600" />
                        <span className="text-lg font-display font-bold text-violet-900 leading-none">{kpis.notes.count}</span>
                      </div>
                      <p className="text-[10px] uppercase tracking-wider mt-1 text-violet-800/80">Notes</p>
                    </Link>
                  )}
                  {(kpis.tasks?.count || 0) > 0 && (
                    <Link to="/portal/notes/tasks" onClick={dismiss}
                      className={`rounded-lg ring-1 p-2 transition ${(kpis.tasks?.overdue || 0) > 0 ? "ring-rose-300 bg-rose-50/70 hover:bg-rose-100" : "ring-amber-200 bg-amber-50/60 hover:bg-amber-100"}`}
                      data-testid="welcome-kpi-tasks">
                      <div className="flex items-center justify-between">
                        <Clock className={`h-4 w-4 ${(kpis.tasks?.overdue || 0) > 0 ? "text-rose-600" : "text-amber-600"}`} />
                        <span className={`text-lg font-display font-bold leading-none ${(kpis.tasks?.overdue || 0) > 0 ? "text-rose-900" : "text-amber-900"}`}>{kpis.tasks.count}</span>
                      </div>
                      <p className={`text-[10px] uppercase tracking-wider mt-1 ${(kpis.tasks?.overdue || 0) > 0 ? "text-rose-800/80" : "text-amber-800/80"}`}>
                        Tâches{(kpis.tasks?.overdue || 0) > 0 ? ` · ${kpis.tasks.overdue} en retard` : ""}
                      </p>
                    </Link>
                  )}
                </div>
              </section>
            )}

            {/* Iter38r-fix9h — Shared with me this week */}
            {hasSharedRecent && (
              <section className="rounded-lg ring-1 ring-emerald-200 bg-gradient-to-br from-emerald-50/70 via-white to-teal-50/40 p-3" data-testid="welcome-shared-recent">
                <div className="flex items-start gap-3">
                  <div className="rounded-full bg-emerald-100 ring-1 ring-emerald-200 p-2 flex-shrink-0">
                    <Send className="h-5 w-5 text-emerald-700" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-2xl font-display font-bold text-emerald-900 leading-none">{sharedRecent.total}</span>
                      <p className="text-sm text-emerald-900 font-medium">
                        nouveau{sharedRecent.total > 1 ? "x" : ""} partage{sharedRecent.total > 1 ? "s" : ""} cette semaine 📥
                      </p>
                    </div>
                    <div className="mt-2 flex items-center gap-2 flex-wrap">
                      {sharedRecent.by_kind.reports > 0 && (
                        <Link to="/portal/notes/reports?scope=shared" onClick={dismiss} className="text-[10px] rounded-full bg-sky-50 ring-1 ring-sky-200 text-sky-800 px-2 py-0.5 hover:bg-sky-100">
                          {sharedRecent.by_kind.reports} rapport{sharedRecent.by_kind.reports > 1 ? "s" : ""}
                        </Link>
                      )}
                      {sharedRecent.by_kind.suivis > 0 && (
                        <Link to="/portal/notes/suivis?scope=shared" onClick={dismiss} className="text-[10px] rounded-full bg-emerald-50 ring-1 ring-emerald-200 text-emerald-800 px-2 py-0.5 hover:bg-emerald-100">
                          {sharedRecent.by_kind.suivis} suivi{sharedRecent.by_kind.suivis > 1 ? "s" : ""}
                        </Link>
                      )}
                      {sharedRecent.by_kind.notes > 0 && (
                        <Link to="/portal/notes/notes?scope=shared" onClick={dismiss} className="text-[10px] rounded-full bg-violet-50 ring-1 ring-violet-200 text-violet-800 px-2 py-0.5 hover:bg-violet-100">
                          {sharedRecent.by_kind.notes} note{sharedRecent.by_kind.notes > 1 ? "s" : ""}
                        </Link>
                      )}
                      {sharedRecent.by_kind.tasks > 0 && (
                        <Link to="/portal/notes/tasks?scope=shared" onClick={dismiss} className="text-[10px] rounded-full bg-amber-50 ring-1 ring-amber-200 text-amber-800 px-2 py-0.5 hover:bg-amber-100">
                          {sharedRecent.by_kind.tasks} tâche{sharedRecent.by_kind.tasks > 1 ? "s" : ""}
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Iter38r-fix9o (Item 8) — WhatsApp OTP demo signups */}
            {hasWaDemo && (
              <section className="rounded-lg ring-1 ring-green-300 bg-gradient-to-br from-green-50/70 via-white to-emerald-50/40 p-3" data-testid="welcome-wa-demo">
                <div className="flex items-start gap-3">
                  <div className="rounded-full bg-green-100 ring-1 ring-green-200 p-2 flex-shrink-0">
                    <MessageCircle className="h-5 w-5 text-green-700" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-2xl font-display font-bold text-green-900 leading-none">{waDemo.total}</span>
                      <p className="text-sm text-green-900 font-medium">
                        connexion{waDemo.total > 1 ? "s" : ""} WhatsApp démo
                      </p>
                      {waDemo.unseen > 0 && (
                        <span className="ml-1 text-[10px] rounded-full bg-rose-100 text-rose-800 ring-1 ring-rose-200 px-2 py-0.5 font-semibold" data-testid="welcome-wa-demo-unseen">
                          {waDemo.unseen} non vu{waDemo.unseen > 1 ? "s" : ""}
                        </span>
                      )}
                    </div>
                    {(waDemo.items || []).length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {(waDemo.items || []).slice(0, 5).map((it) => (
                          <li key={it.id} className="text-xs text-green-900/90 flex items-center gap-2" data-testid="welcome-wa-demo-row">
                            <span className="font-mono text-[10px] bg-white ring-1 ring-green-200 rounded px-1.5 py-0.5 text-green-700">{it.user_no || "DEM"}</span>
                            <span className="font-medium truncate">{it.full_name}</span>
                            <span className="font-mono text-[10px] text-green-700">{it.whatsapp || it.phone}</span>
                            {!it.wa_onboarding_seen_by && <span className="ml-auto text-[9px] rounded-full bg-rose-50 text-rose-700 ring-1 ring-rose-200 px-1.5 py-0.5">nouveau</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                    <Link to="/admin/tracked-users?source=wa_otp_login" onClick={dismiss} className="inline-block mt-2 text-[10px] rounded-full bg-green-50 ring-1 ring-green-300 text-green-800 px-2 py-0.5 hover:bg-green-100" data-testid="welcome-wa-demo-link">
                      Voir tous les utilisateurs WA →
                    </Link>
                  </div>
                </div>
              </section>
            )}



            {/* Iter38r-fix9d — Liluvine PRO auto-reply ROI counter */}
            {hasLiluAuto && (
              <section className="rounded-lg ring-1 ring-fuchsia-200 bg-gradient-to-br from-fuchsia-50/70 via-white to-pink-50/40 p-3 relative overflow-hidden" data-testid="welcome-liluvine-autoreply">
                <div className="absolute -right-4 -top-4 opacity-10">
                  <Sparkles className="h-20 w-20 text-fuchsia-600" />
                </div>
                <div className="flex items-start gap-3 relative">
                  <div className="rounded-full bg-fuchsia-100 ring-1 ring-fuchsia-200 p-2 flex-shrink-0">
                    <Bot className="h-5 w-5 text-fuchsia-700" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-2xl font-display font-bold text-fuchsia-900 leading-none">
                        {liluAuto.today}
                      </span>
                      <p className="text-sm text-fuchsia-900 font-medium">
                        {liluAuto.today === 0
                          ? "WhatsApp pris en charge aujourd'hui"
                          : liluAuto.today === 1
                          ? "WhatsApp pris en charge par Liluvine aujourd'hui 🎉"
                          : "WhatsApp pris en charge par Liluvine aujourd'hui 🎉"}
                      </p>
                    </div>
                    <div className="mt-1.5 flex items-center gap-3 flex-wrap text-[11px] text-fuchsia-800/80">
                      {liluAuto.minutes_saved_today > 0 && (
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />~{liluAuto.minutes_saved_today} min économisée{liluAuto.minutes_saved_today > 1 ? "s" : ""}
                        </span>
                      )}
                      {liluAuto.yesterday > 0 && <span>Hier : {liluAuto.yesterday}</span>}
                      {liluAuto.last_7d > 0 && <span>7 derniers jours : <strong>{liluAuto.last_7d}</strong></span>}
                      {!liluAuto.enabled && (
                        <span className="rounded-full bg-amber-100 ring-1 ring-amber-300 text-amber-800 px-1.5 py-0.5">⏸ Désactivé</span>
                      )}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* Iter38d — Expense reminder for tracked users with cashier access */}
            {hasExpenseReminder && (
              <section
                className={`rounded-lg ring-1 p-3 ${expenseReminder.late_unjustified > 0 ? "ring-rose-300 bg-gradient-to-br from-rose-50 to-amber-50" : "ring-amber-200 bg-amber-50"}`}
                data-testid="welcome-expense-reminder"
              >
                <div className="flex items-center gap-2 mb-2">
                  <Banknote className={`h-4 w-4 ${expenseReminder.late_unjustified > 0 ? "text-rose-700" : "text-amber-700"}`} />
                  <h3 className={`text-sm font-semibold ${expenseReminder.late_unjustified > 0 ? "text-rose-900" : "text-amber-900"}`}>
                    Rappel — Mes dépenses caisse à justifier
                  </h3>
                </div>
                <p className="text-sm text-slate-700">
                  Vous avez <strong>{expenseReminder.count}</strong> dépense(s) en attente de justification ce mois pour un total de{" "}
                  <strong className="text-amber-900">{Number(expenseReminder.total_unjustified || 0).toLocaleString("fr-FR")} {expenseReminder.currency}</strong>.
                </p>
                {expenseReminder.late_unjustified > 0 && (
                  <p className="text-sm text-rose-800 mt-1.5" data-testid="welcome-expense-late">
                    ⚠️ Dont <strong>{Number(expenseReminder.late_unjustified).toLocaleString("fr-FR")} {expenseReminder.currency}</strong> sont déjà <strong>hors délai ({expenseReminder.deadline_hours}h)</strong> et seront <strong>déduites de votre prochaine paie</strong> si non justifiées.
                  </p>
                )}
                <Link
                  to="/portal/cash"
                  onClick={dismiss}
                  data-testid="welcome-expense-link"
                  className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-rose-700 hover:underline"
                >
                  Aller à la Caisse pour régulariser →
                </Link>
              </section>
            )}

            {/* Iter35t — Santé quotidienne (mini-dashboard motivant) */}
            {hasHealth && (
              <section className="rounded-lg ring-1 ring-sky-200 bg-gradient-to-br from-sky-50 via-white to-emerald-50/40 p-3" data-testid="welcome-daily-health">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="h-4 w-4 text-sky-700" />
                  <h3 className="text-sm font-semibold text-sky-900">Santé quotidienne</h3>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <HealthStat
                    testid="health-tickets-resolved"
                    icon={CheckCircle2}
                    value={health.tickets_resolved_yesterday ?? 0}
                    label="Tickets clos hier"
                    tone="emerald"
                  />
                  <HealthStat
                    testid="health-tickets-opened"
                    icon={Ticket}
                    value={health.tickets_opened_today ?? 0}
                    label="Ouverts aujourd'hui"
                    tone="amber"
                  />
                  <HealthStat
                    testid="health-wa-response-rate"
                    icon={TrendingUp}
                    value={health.wa_response_rate_24h === null || health.wa_response_rate_24h === undefined ? "—" : `${health.wa_response_rate_24h}%`}
                    label={`Réponse WA 24h${health.wa_inbound_24h ? ` (${health.wa_outbound_24h}/${health.wa_inbound_24h})` : ""}`}
                    tone={
                      health.wa_response_rate_24h === null || health.wa_response_rate_24h === undefined
                        ? "slate"
                        : health.wa_response_rate_24h >= 80
                          ? "emerald"
                          : health.wa_response_rate_24h >= 50
                            ? "amber"
                            : "rose"
                    }
                  />
                  <HealthStat
                    testid="health-messages-sent"
                    icon={Send}
                    value={health.messages_sent_today ?? 0}
                    label="Messages envoyés"
                    tone="sky"
                  />
                </div>
              </section>
            )}

            {/* Iter36g — "Depuis votre dernière visite" (only if there's something new) */}
            {hasSinceLast && (
              <section className="rounded-lg ring-1 ring-amber-300 bg-gradient-to-br from-amber-50 via-white to-amber-50/40 p-3" data-testid="welcome-since-last">
                <div className="flex items-center gap-2 mb-2">
                  <Clock className="h-4 w-4 text-amber-700" />
                  <h3 className="text-sm font-semibold text-amber-900">
                    Depuis votre dernière visite
                  </h3>
                  <span className="text-[10px] text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded-full" title={sinceLast.last_seen_at}>
                    {new Date(sinceLast.last_seen_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                  </span>
                </div>
                {/* Summary badges */}
                <div className="flex flex-wrap gap-2 text-[11px] mb-2">
                  {sinceLast.new_tickets_count > 0 && (
                    <Link to="/portal/tickets" className="inline-flex items-center gap-1 rounded-full bg-rose-100 text-rose-800 ring-1 ring-rose-200 px-2 py-0.5 hover:bg-rose-200 transition" data-testid="welcome-since-last-tickets-badge">
                      <Ticket className="h-3 w-3" />
                      {sinceLast.new_tickets_count} ticket{sinceLast.new_tickets_count > 1 ? "s" : ""}
                    </Link>
                  )}
                  {sinceLast.new_whatsapp_count > 0 && !isComptaStrict && (
                    <Link to="/portal/contacts" className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200 px-2 py-0.5 hover:bg-emerald-200 transition" data-testid="welcome-since-last-wa-badge">
                      <MessageCircle className="h-3 w-3" />
                      {sinceLast.new_whatsapp_count} WhatsApp
                    </Link>
                  )}
                  {sinceLast.new_notes_count > 0 && (
                    <Link to="/portal/notes" className="inline-flex items-center gap-1 rounded-full bg-sky-100 text-sky-800 ring-1 ring-sky-200 px-2 py-0.5 hover:bg-sky-200 transition" data-testid="welcome-since-last-notes-badge">
                      <FileText className="h-3 w-3" />
                      {sinceLast.new_notes_count} note{sinceLast.new_notes_count > 1 ? "s" : ""}
                    </Link>
                  )}
                  {sinceLast.new_chat_messages_count > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        // Trigger the InternalChatPanel FAB so the user can read them
                        const fab = document.querySelector('[data-testid="internal-chat-fab"]');
                        if (fab) fab.click();
                      }}
                      className="inline-flex items-center gap-1 rounded-full bg-violet-100 text-violet-800 ring-1 ring-violet-200 px-2 py-0.5 hover:bg-violet-200 transition"
                      data-testid="welcome-since-last-chat-badge"
                      title="Ouvrir le chat interne pour répondre"
                    >
                      <MessageSquareText className="h-3 w-3" />
                      {sinceLast.new_chat_messages_count} message{sinceLast.new_chat_messages_count > 1 ? "s" : ""} de chat non lu{sinceLast.new_chat_messages_count > 1 ? "s" : ""}
                    </button>
                  )}
                </div>
                {/* New tickets detail (max 5) */}
                {sinceLast.new_tickets?.length > 0 && (
                  <div className="space-y-1" data-testid="welcome-since-last-tickets-list">
                    {sinceLast.new_tickets.slice(0, 5).map((t) => (
                      <Link key={t.id} to="/portal/tickets" className="flex items-center gap-2 text-[11px] py-0.5 hover:bg-amber-50 rounded px-1 transition">
                        <span className="font-mono text-[10px] bg-white px-1 py-0.5 rounded ring-1 ring-amber-200 text-rose-700">{t.number || t.id.slice(0, 8)}</span>
                        <span className="text-slate-700 truncate flex-1">{t.motif || "(sans motif)"}</span>
                        {t.contact_name && <span className="text-slate-500 truncate max-w-[120px]">{t.contact_name}</span>}
                      </Link>
                    ))}
                    {sinceLast.new_tickets.length > 5 && (
                      <div className="text-[10px] text-amber-700 italic pt-0.5">+ {sinceLast.new_tickets.length - 5} autre(s)</div>
                    )}
                  </div>
                )}
              </section>
            )}

            {/* Tickets en attente / suspendus */}
            {tickets.length > 0 && (
              <section className="rounded-lg ring-1 ring-amber-200 bg-amber-50/50 p-3" data-testid="welcome-tickets">
                <div className="flex items-center gap-2 mb-2">
                  <Ticket className="h-4 w-4 text-amber-700" />
                  <h3 className="text-sm font-semibold text-amber-900">
                    {tickets.length} ticket(s) d'intervention à traiter
                  </h3>
                </div>
                <ul className="space-y-1.5">
                  {tickets.slice(0, 8).map((t) => (
                    <li key={t.id} className="flex items-center gap-2 text-xs bg-white ring-1 ring-amber-200 rounded px-2 py-1.5">
                      <code className="font-mono bg-amber-100 text-amber-900 px-1.5 py-0.5 rounded text-[10px]">{t.number}</code>
                      <span className={`text-[10px] uppercase tracking-wider font-semibold rounded-full px-1.5 py-0.5 ${
                        t.status === "open" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700"
                      }`}>
                        {t.status === "open" ? "Attente" : "Suspendu"}
                      </span>
                      <span className="flex-1 truncate text-slate-700" title={t.motif}>{t.motif}</span>
                      <span className="text-[10px] text-slate-500 truncate max-w-[120px]">{t.contact_name || "—"}</span>
                    </li>
                  ))}
                  {tickets.length > 8 && (
                    <li className="text-[11px] text-amber-700 italic">… et {tickets.length - 8} autre(s)</li>
                  )}
                </ul>
                <Link to="/portal/tickets" onClick={dismiss} className="inline-block mt-2 text-xs text-amber-700 hover:underline" data-testid="welcome-tickets-link">
                  Voir tous les tickets →
                </Link>
              </section>
            )}

            {/* Messages non lus */}
            {unread.total > 0 && (
              <section className="rounded-lg ring-1 ring-sky-200 bg-sky-50/50 p-3" data-testid="welcome-unread">
                <div className="flex items-center gap-2 mb-2">
                  <MessageCircle className="h-4 w-4 text-sky-700" />
                  <h3 className="text-sm font-semibold text-sky-900">
                    {unread.total} message(s) non lu(s)
                  </h3>
                </div>
                <div className="flex gap-2 flex-wrap text-xs">
                  {unread.whatsapp > 0 && (
                    <span className="inline-flex items-center gap-1 bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200 rounded-full px-2 py-0.5">
                      <MessageCircle className="h-3 w-3" /> WhatsApp : <strong>{unread.whatsapp}</strong>
                    </span>
                  )}
                  {unread.sms > 0 && (
                    <span className="inline-flex items-center gap-1 bg-violet-100 text-violet-800 ring-1 ring-violet-200 rounded-full px-2 py-0.5">
                      <MessageSquare className="h-3 w-3" /> SMS : <strong>{unread.sms}</strong>
                    </span>
                  )}
                </div>
                {/* Iter38r-fix7 — Comptable strict has no access to messaging center */}
                {!isComptaStrict && (
                  <Link to="/portal/contacts" onClick={dismiss} className="inline-block mt-2 text-xs text-sky-700 hover:underline" data-testid="welcome-messages-link">
                    Ouvrir le centre de messagerie →
                  </Link>
                )}
              </section>
            )}

            {/* Notes récentes de l'utilisateur */}
            {notes.length > 0 && (
              <section className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40 p-3" data-testid="welcome-notes">
                <div className="flex items-center gap-2 mb-2">
                  <FileText className="h-4 w-4 text-emerald-700" />
                  <h3 className="text-sm font-semibold text-emerald-900">
                    Vos notes des {data?.recent_notes_window_days || 3} derniers jours ({notes.length})
                  </h3>
                </div>
                <ul className="space-y-1.5">
                  {notes.slice(0, 8).map((n) => (
                    <li key={n.id} className="flex items-center gap-2 text-xs bg-white ring-1 ring-emerald-200 rounded px-2 py-1.5">
                      {n.is_private ? <Lock className="h-3 w-3 text-emerald-700" /> : <span className="text-[10px] uppercase tracking-wider font-semibold text-emerald-700 bg-emerald-100 rounded px-1 py-0.5">Public</span>}
                      <span className="flex-1 truncate text-slate-700">{n.title || "(Sans titre)"}</span>
                      {n.target_user_ids?.length > 0 && (
                        <span className="text-[10px] text-fuchsia-700">→ {n.target_user_ids.length} cible(s)</span>
                      )}
                    </li>
                  ))}
                  {notes.length > 8 && <li className="text-[11px] text-emerald-700 italic">… et {notes.length - 8} autre(s)</li>}
                </ul>
                <Link to="/portal/notes" onClick={dismiss} className="inline-block mt-2 text-xs text-emerald-700 hover:underline" data-testid="welcome-notes-link">
                  Voir mes notes →
                </Link>
              </section>
            )}
          </div>
        )}

        <footer className="px-6 py-3 border-t border-slate-200 flex items-center justify-end gap-3">
          {/* 2026-02 fork iter108 fix — Bouton "J'ai lu" toujours cliquable
              (le blocage jusqu'au scroll bas piégeait l'utilisateur en cas
              de contenu long ; rapport testing_agent iter97). */}
          <button
            onClick={dismiss}
            className="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition bg-sawali-blue text-white hover:opacity-90 cursor-pointer"
            data-testid="welcome-briefing-ack"
            title="Marquer comme lu"
          >
            <CheckCircle2 className="h-4 w-4" /> J&apos;ai lu
          </button>
        </footer>
      </div>
    </div>
  );
}

export function shouldShowWelcomeBriefing() {
  try { return sessionStorage.getItem(SS_KEY) !== "1"; } catch { return true; }
}

// Iter35t — mini-stat card used inside the daily-health section
const TONE_CLASSES = {
  emerald: "bg-emerald-50 ring-emerald-200 text-emerald-900 [&_svg]:text-emerald-600",
  amber: "bg-amber-50 ring-amber-200 text-amber-900 [&_svg]:text-amber-600",
  sky: "bg-sky-50 ring-sky-200 text-sky-900 [&_svg]:text-sky-600",
  rose: "bg-rose-50 ring-rose-200 text-rose-900 [&_svg]:text-rose-600",
  slate: "bg-slate-50 ring-slate-200 text-slate-700 [&_svg]:text-slate-500",
};

function HealthStat({ icon: Icon, value, label, tone = "sky", testid }) {
  const cls = TONE_CLASSES[tone] || TONE_CLASSES.sky;
  return (
    <div className={`rounded-lg ring-1 p-2 ${cls}`} data-testid={testid}>
      <div className="flex items-center justify-between">
        <Icon className="h-4 w-4" />
        <span className="text-lg font-display font-bold leading-none">{value}</span>
      </div>
      <p className="text-[10px] uppercase tracking-wider mt-1 opacity-80 truncate" title={label}>{label}</p>
    </div>
  );
}
