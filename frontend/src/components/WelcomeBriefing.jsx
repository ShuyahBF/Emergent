import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { X, Ticket, MessageCircle, MessageSquare, FileText, Lock, CheckCircle2 } from "lucide-react";

/*
  Iter35r — Welcome briefing modal.

  Shown right after the first successful login of a session for any user
  (admin/superviseur/tracked). Lists:
    • Pending tickets (open + suspended) in the user's scope
    • Unread WhatsApp + SMS counts
    • The user's own personal notes created within the last N days (admin-tunable)

  The user must click "J'ai lu" to dismiss. We persist a sessionStorage key so
  the modal only appears once per session.
*/

const SS_KEY = "sawali_welcome_briefing_seen";

export default function WelcomeBriefing({ onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient
      .get("/me/welcome-briefing")
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  const dismiss = () => {
    try { sessionStorage.setItem(SS_KEY, "1"); } catch { /* noop */ }
    onClose?.();
  };

  // Don't show the modal if everything is empty
  const tickets = data?.tickets || [];
  const unread = data?.unread_messages || { whatsapp: 0, sms: 0, total: 0 };
  const notes = data?.recent_notes || [];
  const isEmpty = !loading && tickets.length === 0 && unread.total === 0 && notes.length === 0;

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
