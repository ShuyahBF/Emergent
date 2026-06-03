// =====================================================================
// Iter38r-fix9i — Pack Liluvine PRO (b) : Page admin dédiée /admin/liluvine-history
// =====================================================================
// Full historique des conversations Liluvine PRO (web + WhatsApp + SMS +
// Facebook) avec filtres canal / période / recherche, et action "Reprendre
// la conversation" (human takeover) accessible aux rôles administrateur /
// superviseur / modération.

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Sparkles, Search, MessageCircle, Hand, Eye, AlertTriangle, Phone, Globe, ArrowRightCircle, RefreshCw, Camera } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import LiluvineScreenshotsInsights from "@/components/LiluvineScreenshotsInsights";

const CHANNELS = [
  { id: "all", label: "Tous canaux", icon: null, badge: null },
  { id: "web", label: "Web", icon: Globe, badge: "🌐 Web" },
  { id: "whatsapp", label: "WhatsApp", icon: Phone, badge: "📱 WA" },
  { id: "facebook", label: "Facebook", icon: null, badge: "📘 FB" },
  { id: "sms", label: "SMS", icon: null, badge: "📩 SMS" },
];

const DATE_RANGES = [
  ["today", "Aujourd'hui"],
  ["7d", "7 jours"],
  ["30d", "30 jours"],
  ["90d", "90 jours"],
  ["all", "Toujours"],
];

// S-iter39d (fix #2) — Include the stored values used in the DB:
// tracked_role can be "Moderation" or "Administrateur" (lowercase becomes
// "moderation" / "administrateur"), not "moderateur".
const TAKEOVER_ROLES = new Set(["admin", "superviseur", "moderateur", "moderation", "administrateur"]);

export default function AdminLiluvineHistory() {
  const { user } = useAuth() || {};
  const navigate = useNavigate();
  const role = (user?.role || "").toLowerCase();
  const trackedRole = (user?.tracked_role || "").toLowerCase();
  const canTakeover = TAKEOVER_ROLES.has(role) || TAKEOVER_ROLES.has(trackedRole);

  const [channel, setChannel] = useState("all");
  const [dateRange, setDateRange] = useState("30d");
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [openSession, setOpenSession] = useState(null);
  const [openMessages, setOpenMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  // #1 (2026-02 — suite S044) — Top-level tabs (conversations vs screenshots)
  const [topTab, setTopTab] = useState("conversations");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (channel !== "all") params.set("channel", channel);
      if (dateRange !== "all") params.set("date_range", dateRange);
      if (q.trim()) params.set("q", q.trim());
      params.set("limit", "200");
      const r = await apiClient.get(`/admin/liluvine-pro/sessions-history?${params.toString()}`);
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, [channel, dateRange, q]);

  useEffect(() => { load(); }, [load]);

  const openConversation = async (session) => {
    setOpenSession(session);
    setOpenMessages([]);
    setLoadingMessages(true);
    try {
      const r = await apiClient.get(`/me/liluvine-pro/sessions/${session.id}`);
      setOpenMessages(r.data?.messages || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Conversation introuvable");
    } finally {
      setLoadingMessages(false);
    }
  };

  const takeover = async (session) => {
    if (!canTakeover) return;
    if (!window.confirm(`Reprendre la conversation avec ${session.user_label || session.title} ?\n\nLiluvine PRO arrêtera de répondre automatiquement à ce contact pendant 2 heures (vous pouvez prolonger ou libérer manuellement ensuite).`)) return;
    try {
      const r = await apiClient.post(`/admin/liluvine-pro/sessions/${session.id}/takeover`, { duration_minutes: 120 });
      toast.success("Conversation reprise — Liluvine se tait, à vous de répondre 👋");
      const phone = r.data?.phone_digits;
      if (session.channel === "whatsapp" && phone) {
        // Redirect to the contact view with WhatsApp tab pre-opened for manual reply
        navigate(`/portal/contacts?q=${encodeURIComponent(phone)}`);
        return;
      }
      // Otherwise just refresh
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur — impossible de reprendre");
    }
  };

  const releaseTakeover = async (session) => {
    if (!canTakeover) return;
    if (!window.confirm("Libérer la conversation ? Liluvine PRO reprendra ses réponses automatiques.")) return;
    try {
      await apiClient.post(`/admin/liluvine-pro/sessions/${session.id}/release`);
      toast.success("Conversation libérée — Liluvine PRO reprend la main");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const counts = useMemo(() => {
    const acc = { all: items.length, web: 0, whatsapp: 0, facebook: 0, sms: 0, takeover: 0 };
    for (const it of items) {
      const ch = it.channel || "web";
      if (acc[ch] !== undefined) acc[ch] += 1;
      if (it.human_takeover) acc.takeover += 1;
    }
    return acc;
  }, [items]);

  const fmtAge = (iso) => {
    if (!iso) return "—";
    try {
      const diff = Date.now() - new Date(iso).getTime();
      const min = Math.floor(diff / 60000);
      if (min < 1) return "à l'instant";
      if (min < 60) return `il y a ${min} min`;
      if (min < 1440) return `il y a ${Math.floor(min / 60)} h`;
      return new Date(iso).toLocaleDateString("fr-FR");
    } catch { return iso; }
  };

  return (
    <div className="space-y-4 p-4" data-testid="admin-liluvine-history">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-fuchsia-500 to-violet-600 flex items-center justify-center">
            <Bot className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="font-display font-bold text-slate-900 text-xl inline-flex items-center gap-1">
              Liluvine PRO — Historique <Sparkles className="h-4 w-4 text-fuchsia-500" />
            </h1>
            <p className="text-xs text-slate-500">Toutes les conversations (Web + WhatsApp + SMS + Facebook) avec action « Reprendre ».</p>
          </div>
        </div>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs inline-flex items-center gap-1 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 px-2.5 py-1.5"
          data-testid="liluvine-history-refresh"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>

      {/* #1 (2026-02) — Top-level tabs: Conversations vs Screenshots/Top Screens */}
      <div className="inline-flex gap-1 rounded-lg ring-1 ring-slate-200 bg-white p-1" data-testid="liluvine-top-tabs">
        <button
          onClick={() => setTopTab("conversations")}
          data-testid="liluvine-top-tab-conversations"
          className={`px-3 py-1.5 text-xs rounded-md inline-flex items-center gap-1.5 ${topTab === "conversations" ? "bg-fuchsia-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
        >
          <MessageCircle size={14} /> Conversations
        </button>
        <button
          onClick={() => setTopTab("screenshots")}
          data-testid="liluvine-top-tab-screenshots"
          className={`px-3 py-1.5 text-xs rounded-md inline-flex items-center gap-1.5 ${topTab === "screenshots" ? "bg-fuchsia-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
        >
          <Camera size={14} /> Captures & Analytics
        </button>
      </div>

      {topTab === "screenshots" ? (
        <LiluvineScreenshotsInsights />
      ) : (
      <>
      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {CHANNELS.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setChannel(c.id)}
            className={`rounded-lg p-3 ring-1 transition text-left ${channel === c.id ? "ring-fuchsia-400 bg-fuchsia-50" : "ring-slate-200 bg-white hover:ring-fuchsia-300"}`}
            data-testid={`liluvine-history-channel-${c.id}`}
          >
            <div className="text-[10px] uppercase tracking-wider text-slate-500">{c.label}</div>
            <div className="text-xl font-display font-bold text-slate-900">{counts[c.id] ?? 0}</div>
            {c.id === "all" && counts.takeover > 0 && (
              <div className="text-[10px] text-amber-700 mt-0.5 inline-flex items-center gap-1">
                <Hand className="h-3 w-3" /> {counts.takeover} reprise(s)
              </div>
            )}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="inline-flex rounded-lg ring-1 ring-emerald-200 bg-white p-0.5" data-testid="liluvine-history-date-range">
          {DATE_RANGES.map(([v, l]) => (
            <button
              key={v}
              type="button"
              onClick={() => setDateRange(v)}
              className={`px-3 py-1 text-[11px] rounded ${dateRange === v ? "bg-emerald-600 text-white" : "text-slate-600 hover:bg-emerald-50"}`}
              data-testid={`liluvine-history-date-${v}`}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") load(); }}
            placeholder="Rechercher (titre, contact)…"
            className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-200 focus:ring-fuchsia-400 outline-none"
            data-testid="liluvine-history-search"
          />
        </div>
        {!canTakeover && (
          <span className="inline-flex items-center gap-1 text-[11px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded px-2 py-1">
            <AlertTriangle className="h-3 w-3" /> Lecture seule (rôle restreint)
          </span>
        )}
      </div>

      {/* Table */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]" data-testid="liluvine-history-table">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="px-3 py-2 text-left">Contact / Titre</th>
              <th className="px-2 py-2 text-left">Canal</th>
              <th className="px-2 py-2 text-left">Dernier message</th>
              <th className="px-2 py-2 text-center">Messages</th>
              <th className="px-2 py-2 text-left">Mise à jour</th>
              <th className="px-2 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-400 italic">Chargement…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-slate-400 italic">Aucune conversation pour ces filtres.</td></tr>
            ) : items.map((it) => {
              const ch = CHANNELS.find((c) => c.id === it.channel) || CHANNELS[0];
              const isTakenOver = !!it.human_takeover;
              return (
                <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50/60" data-testid={`liluvine-history-row-${it.id}`}>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-slate-800 truncate max-w-[280px]">{it.user_label || it.title || "Sans titre"}</div>
                    {it.title && it.title !== it.user_label && (
                      <div className="text-[11px] text-slate-500 truncate max-w-[280px]">{it.title}</div>
                    )}
                    {isTakenOver && (
                      <span className="mt-1 inline-flex items-center gap-1 text-[10px] rounded-full bg-amber-50 text-amber-800 ring-1 ring-amber-200 px-1.5 py-0.5">
                        <Hand className="h-2.5 w-2.5" /> Reprise par {it.human_takeover_by || "humain"}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <span className="text-[10px] rounded-full ring-1 ring-slate-200 bg-slate-50 px-1.5 py-0.5 text-slate-700">{ch.badge || ch.label}</span>
                  </td>
                  <td className="px-2 py-2 max-w-[300px]">
                    <div className="text-xs text-slate-600 truncate">{it.last_message_preview || "—"}</div>
                    {it.last_message_role && (
                      <div className="text-[10px] text-slate-400">{it.last_message_role === "assistant" ? "🤖 Liluvine" : "👤 Contact"}</div>
                    )}
                  </td>
                  <td className="px-2 py-2 text-center text-slate-700">{it.message_count || 0}</td>
                  <td className="px-2 py-2 text-[11px] text-slate-500 whitespace-nowrap">{fmtAge(it.updated_at)}</td>
                  <td className="px-2 py-2 text-right">
                    <div className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => openConversation(it)}
                        className="text-[11px] inline-flex items-center gap-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 px-2 py-1 text-slate-700"
                        title="Voir la conversation"
                        data-testid={`liluvine-history-view-${it.id}`}
                      >
                        <Eye className="h-3 w-3" /> Voir
                      </button>
                      {canTakeover && !isTakenOver && (
                        <button
                          type="button"
                          onClick={() => takeover(it)}
                          className="text-[11px] inline-flex items-center gap-1 rounded bg-amber-500 hover:bg-amber-600 text-white px-2 py-1 font-medium"
                          title="Reprendre la conversation (suspend Liluvine pendant 2 h)"
                          data-testid={`liluvine-history-takeover-${it.id}`}
                        >
                          <Hand className="h-3 w-3" /> Reprendre
                        </button>
                      )}
                      {canTakeover && isTakenOver && (
                        <button
                          type="button"
                          onClick={() => releaseTakeover(it)}
                          className="text-[11px] inline-flex items-center gap-1 rounded bg-emerald-500 hover:bg-emerald-600 text-white px-2 py-1 font-medium"
                          title="Libérer — Liluvine reprend la main"
                          data-testid={`liluvine-history-release-${it.id}`}
                        >
                          <ArrowRightCircle className="h-3 w-3" /> Libérer
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Read-only conversation modal */}
      {openSession && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" onClick={() => setOpenSession(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[85vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <MessageCircle className="h-4 w-4 text-fuchsia-600 shrink-0" />
                <h3 className="font-display font-semibold text-slate-800 truncate">
                  {openSession.user_label || openSession.title || "Conversation"}
                </h3>
                <span className="text-[10px] rounded-full ring-1 ring-slate-200 bg-slate-50 px-1.5 py-0.5 text-slate-600 shrink-0">
                  {openSession.channel}
                </span>
              </div>
              <button onClick={() => setOpenSession(null)} className="text-slate-400 hover:text-slate-700 text-xl leading-none">×</button>
            </header>
            <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50/30">
              {loadingMessages ? (
                <p className="text-center text-slate-400 italic py-8">Chargement…</p>
              ) : openMessages.length === 0 ? (
                <p className="text-center text-slate-400 italic py-8">Conversation vide.</p>
              ) : openMessages.map((m) => (
                <div key={m.id} className={`flex ${m.role === "user" ? "justify-start" : "justify-end"}`}>
                  <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === "user"
                      ? "bg-white ring-1 ring-slate-200 text-slate-800"
                      : "bg-fuchsia-600 text-white"
                  }`}>
                    <div className="text-[9px] uppercase tracking-wider opacity-70 mb-0.5">
                      {m.role === "user" ? "👤 Contact" : "🤖 Liluvine"} · {new Date(m.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                    </div>
                    {m.content}
                  </div>
                </div>
              ))}
            </div>
            <footer className="px-5 py-3 border-t border-slate-200 flex items-center justify-end gap-2">
              {canTakeover && !openSession.human_takeover && (
                <button
                  type="button"
                  onClick={() => { takeover(openSession); setOpenSession(null); }}
                  className="inline-flex items-center gap-1 rounded-lg bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 text-sm font-medium"
                  data-testid="liluvine-history-modal-takeover"
                >
                  <Hand className="h-3.5 w-3.5" /> Reprendre la conversation
                </button>
              )}
              <button
                type="button"
                onClick={() => setOpenSession(null)}
                className="rounded-lg ring-1 ring-slate-300 text-slate-600 hover:bg-slate-50 px-3 py-1.5 text-sm"
              >
                Fermer
              </button>
            </footer>
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}
