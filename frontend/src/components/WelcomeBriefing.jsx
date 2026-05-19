import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { X, Ticket, MessageCircle, MessageSquare, FileText, Lock, CheckCircle2, TrendingUp, Send, Sparkles, Clock } from "lucide-react";

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

export default function WelcomeBriefing({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

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
  const hasHealth = !!health && (
    (health.tickets_resolved_yesterday || 0) > 0
    || (health.messages_sent_today || 0) > 0
    || (health.tickets_opened_today || 0) > 0
    || (health.wa_response_rate_24h !== null && health.wa_response_rate_24h !== undefined)
  );
  const hasSinceLast = !!sinceLast && (sinceLast.total_count || 0) > 0;
  const isEmpty = !loading && tickets.length === 0 && unread.total === 0 && notes.length === 0 && !hasHealth && !hasSinceLast;

  if (!loading && isEmpty) {
    // Mark as seen and close silently
    try { sessionStorage.setItem(SS_KEY, "1"); } catch { /* noop */ }
    setTimeout(onClose, 0);
    return null;
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center p-4 sm:p-8 bg-black/50 overflow-y-auto" data-testid="welcome-briefing">
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
          <div className="p-6 space-y-4 max-h-[60vh] overflow-y-auto">
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
                  {sinceLast.new_whatsapp_count > 0 && (
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
                <Link to="/portal/contacts" onClick={dismiss} className="inline-block mt-2 text-xs text-sky-700 hover:underline" data-testid="welcome-messages-link">
                  Ouvrir le centre de messagerie →
                </Link>
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

        <footer className="px-6 py-3 border-t border-slate-200 flex justify-end">
          <button
            onClick={dismiss}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white hover:opacity-90 px-4 py-2 text-sm font-medium"
            data-testid="welcome-briefing-ack"
          >
            <CheckCircle2 className="h-4 w-4" /> J'ai lu
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
