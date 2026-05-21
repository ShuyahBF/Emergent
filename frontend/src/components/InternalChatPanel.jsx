/*
 * Iter36k — Internal chat panel (floating drawer).
 *
 * Displays:
 *   - A floating chat bubble FAB at bottom-right (badge with unread count).
 *   - When opened, a 3-pane drawer:
 *       LEFT  — list of clients where chat is enabled (only if >1)
 *       MIDDLE — threads list (#general + 1-to-1 DMs) with unread badges
 *       RIGHT  — current thread messages + composer
 *
 * Realtime via useInternalChat (WebSocket). Falls back to polling threads
 * every 30s as defensive backup.
 */
import React, { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { useInternalChat } from "@/hooks/useInternalChat";
import { toast } from "sonner";
import { MessageSquareText, Send, X, Hash, Users as UsersIcon, Circle, RefreshCw } from "lucide-react";

function playMessageBlip() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.1);
    gain.gain.setValueAtTime(0.25, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
    osc.start();
    osc.stop(ctx.currentTime + 0.27);
    osc.onended = () => ctx.close();
  } catch { /* best effort */ }
}

function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) {
      return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch { return ""; }
}

export default function InternalChatPanel() {
  const { user } = useAuth();
  const token = typeof window !== "undefined" ? localStorage.getItem("sawali_token") : null;
  const [open, setOpen] = useState(false);
  const [clients, setClients] = useState([]);
  const [activeClientId, setActiveClientId] = useState(null);
  const [threads, setThreads] = useState([]);
  const [members, setMembers] = useState([]);
  const [activeThreadKey, setActiveThreadKey] = useState(null);  // "general" or user_id
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [unreadTotal, setUnreadTotal] = useState(0);
  const [unreadPerClient, setUnreadPerClient] = useState({});
  const scrollRef = useRef(null);

  // ---- WebSocket connection ----
  const { connected, lastEvent } = useInternalChat({ token, enabled: !!user && clients.length > 0 });

  // ---- API helpers ----
  const loadClients = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/chat/clients");
      const list = r.data || [];
      setClients(list);
      if (list.length > 0 && !activeClientId) {
        setActiveClientId(list[0].id);
      }
    } catch { /* noop */ }
  }, [activeClientId]);

  const loadUnreadCount = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/chat/unread-count");
      setUnreadTotal(r.data?.total || 0);
      setUnreadPerClient(r.data?.per_client || {});
    } catch { /* noop */ }
  }, []);

  const loadThreads = useCallback(async (cid) => {
    if (!cid) return;
    try {
      const r = await apiClient.get(`/me/chat/${cid}/threads`);
      setThreads(r.data || []);
    } catch { /* noop */ }
  }, []);

  const loadMembers = useCallback(async (cid) => {
    if (!cid) return;
    try {
      const r = await apiClient.get(`/me/chat/${cid}/members`);
      setMembers((r.data || []).filter((m) => !m.is_self));
    } catch { /* noop */ }
  }, []);

  const loadMessages = useCallback(async (cid, key) => {
    if (!cid || !key) return;
    setLoadingMessages(true);
    try {
      const r = await apiClient.get(`/me/chat/${cid}/messages`, { params: { with_user: key, limit: 100 } });
      setMessages(r.data || []);
    } catch { /* noop */ } finally { setLoadingMessages(false); }
  }, []);

  const markThreadRead = useCallback(async (cid, key) => {
    if (!cid || !key) return;
    try {
      await apiClient.post(`/me/chat/${cid}/threads/${key}/mark-all-read`);
      loadUnreadCount();
      loadThreads(cid);
    } catch { /* noop */ }
  }, [loadUnreadCount, loadThreads]);

  // ---- Initial load ----
  useEffect(() => { if (user) { loadClients(); loadUnreadCount(); } }, [user, loadClients, loadUnreadCount]);

  // Polling fallback for unread count (so badge updates even if WS is down)
  useEffect(() => {
    if (!user) return undefined;
    const t = setInterval(loadUnreadCount, 30000);
    return () => clearInterval(t);
  }, [user, loadUnreadCount]);

  // When clientId changes, load threads + members
  useEffect(() => {
    if (activeClientId) {
      loadThreads(activeClientId);
      loadMembers(activeClientId);
      setActiveThreadKey(null);
      setMessages([]);
    }
  }, [activeClientId, loadThreads, loadMembers]);

  // When threadKey changes, load history + mark read
  useEffect(() => {
    if (activeClientId && activeThreadKey) {
      loadMessages(activeClientId, activeThreadKey);
      if (open) markThreadRead(activeClientId, activeThreadKey);
    }
  }, [activeClientId, activeThreadKey, open, loadMessages, markThreadRead]);

  // Scroll-to-bottom on messages change
  useEffect(() => {
    if (scrollRef.current) {
      requestAnimationFrame(() => {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      });
    }
  }, [messages.length]);

  // ---- WebSocket event handler ----
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type === "message") {
      const { client_id, message } = lastEvent;
      const isMine = message?.sender_id === user?.id;
      // Refresh threads (counters) + global unread
      loadUnreadCount();
      loadThreads(client_id);
      // If currently viewing this thread, append + auto-mark-read
      if (open && activeClientId === client_id && (
        (activeThreadKey === "general" && !message.recipient_id) ||
        (activeThreadKey === message.sender_id && message.recipient_id === user?.id) ||
        (activeThreadKey === message.recipient_id && message.sender_id === user?.id)
      )) {
        setMessages((prev) => {
          if (prev.some((m) => m.id === message.id)) return prev;
          return [...prev, message];
        });
        if (!isMine) {
          apiClient.post(`/me/chat/messages/${message.id}/read`).catch(() => {});
        }
      } else if (!isMine) {
        // Toast + sound for messages received in a thread the user isn't viewing
        playMessageBlip();
        toast.info(`💬 ${message.sender_name}: ${(message.text || "").slice(0, 80)}`, {
          duration: 4000,
        });
      }
    }
  }, [lastEvent, user?.id, open, activeClientId, activeThreadKey, loadUnreadCount, loadThreads]);

  // ---- Send message ----
  const sendMessage = async () => {
    const t = text.trim();
    if (!t || !activeClientId || !activeThreadKey) return;
    setSending(true);
    try {
      const recipient = activeThreadKey === "general" ? null : activeThreadKey;
      await apiClient.post(`/me/chat/${activeClientId}/messages`, {
        text: t,
        recipient_id: recipient,
      });
      setText("");
      // WS will push the message back via the broadcast; locally also reload as safety
      loadMessages(activeClientId, activeThreadKey);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally {
      setSending(false);
    }
  };

  // useMemo MUST be called before any conditional return (React Hooks rule)
  const dmThreadIds = useMemo(
    () => new Set(threads.filter((t) => t.kind === "dm").map((t) => t.key)),
    [threads],
  );

  // Hide entire feature if user has no chat-enabled clients
  if (!user || clients.length === 0) return null;

  const activeClient = clients.find((c) => c.id === activeClientId);
  const activeThread = threads.find((t) => t.key === activeThreadKey);
  const activeMember = activeThreadKey && activeThreadKey !== "general"
    ? members.find((m) => m.id === activeThreadKey)
    : null;

  // Build a list of "potential threads" = members not yet having a DM thread
  const newableMembers = members.filter((m) => !dmThreadIds.has(m.id));

  return (
    <>
      {/* Floating FAB */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-40 inline-flex items-center justify-center h-12 w-12 rounded-full bg-sawali-blue text-white shadow-2xl hover:bg-sawali-blue-light hover:scale-105 transition-all ring-2 ring-white"
          data-testid="internal-chat-fab"
          title="Chat interne"
        >
          <MessageSquareText className="h-5 w-5" />
          {unreadTotal > 0 && (
            <span
              className="absolute -top-1 -right-1 inline-flex items-center justify-center min-w-[20px] h-5 px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold tabular-nums ring-2 ring-white"
              data-testid="internal-chat-badge"
            >
              {unreadTotal > 99 ? "99+" : unreadTotal}
            </span>
          )}
        </button>
      )}

      {/* Drawer */}
      {open && (
        <div
          className="fixed bottom-4 right-4 z-40 w-[95vw] max-w-2xl h-[600px] max-h-[85vh] rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 flex overflow-hidden"
          data-testid="internal-chat-drawer"
        >
          {/* Left pane — clients + threads */}
          <div className="w-64 shrink-0 border-r border-slate-200 bg-slate-50 flex flex-col">
            <div className="px-3 py-3 border-b border-slate-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MessageSquareText className="h-4 w-4 text-sawali-blue" />
                <span className="font-display font-bold text-sm">Chat interne</span>
              </div>
              <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
                <Circle className={`h-2 w-2 ${connected ? "fill-emerald-500 text-emerald-500" : "fill-slate-300 text-slate-300"}`} />
                {connected ? "En ligne" : "Hors ligne"}
              </span>
            </div>

            {/* Client selector (only if >1) */}
            {clients.length > 1 && (
              <select
                value={activeClientId || ""}
                onChange={(e) => setActiveClientId(e.target.value)}
                className="m-2 px-2 py-1.5 text-xs bg-white border border-slate-300 rounded-md"
                data-testid="internal-chat-client-select"
              >
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.full_name || c.company || c.id}
                    {unreadPerClient[c.id] > 0 ? ` (${unreadPerClient[c.id]})` : ""}
                  </option>
                ))}
              </select>
            )}

            {/* Thread list */}
            <div className="flex-1 overflow-y-auto py-1">
              {threads.map((t) => {
                const isActive = t.key === activeThreadKey;
                return (
                  <button
                    key={t.key}
                    onClick={() => setActiveThreadKey(t.key)}
                    className={`w-full text-left px-3 py-2 flex items-start gap-2 transition-colors ${isActive ? "bg-sky-100 ring-1 ring-sky-200" : "hover:bg-white"}`}
                    data-testid={`internal-chat-thread-${t.key}`}
                  >
                    <div className="shrink-0 mt-0.5">
                      {t.kind === "general"
                        ? <Hash className="h-4 w-4 text-slate-500" />
                        : <UsersIcon className="h-4 w-4 text-slate-500" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-medium truncate text-slate-800">{t.label}</span>
                        {t.unread > 0 && (
                          <span className="ml-auto inline-flex items-center justify-center min-w-[18px] h-4 px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold">
                            {t.unread}
                          </span>
                        )}
                      </div>
                      {t.last_message && (
                        <p className="text-[10px] text-slate-500 truncate mt-0.5">
                          {(t.last_message.text || "").slice(0, 40)}
                        </p>
                      )}
                    </div>
                  </button>
                );
              })}

              {/* "Start new chat with…" */}
              {newableMembers.length > 0 && (
                <div className="px-3 pt-3 pb-1">
                  <p className="text-[9px] uppercase tracking-wider text-slate-400 mb-1">Nouveau chat</p>
                  {newableMembers.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => setActiveThreadKey(m.id)}
                      className="w-full text-left px-2 py-1.5 text-xs rounded hover:bg-white text-slate-600 flex items-center gap-2"
                      data-testid={`internal-chat-new-${m.id}`}
                    >
                      <Circle className={`h-2 w-2 ${m.online ? "fill-emerald-500 text-emerald-500" : "fill-slate-300 text-slate-300"}`} />
                      <span className="truncate">{m.name}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right pane — messages */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between bg-white">
              <div className="min-w-0">
                <p className="text-sm font-bold text-slate-800 truncate">
                  {activeThreadKey === "general"
                    ? `#général — ${activeClient?.full_name || activeClient?.company || ""}`
                    : activeMember?.name || activeThread?.label || "Sélectionnez un fil"}
                </p>
                {activeThreadKey && activeThreadKey !== "general" && (
                  <p className="text-[10px] text-slate-500 inline-flex items-center gap-1">
                    <Circle className={`h-1.5 w-1.5 ${activeMember?.online ? "fill-emerald-500 text-emerald-500" : "fill-slate-400 text-slate-400"}`} />
                    {activeMember?.online ? "En ligne" : "Hors ligne"}
                  </p>
                )}
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-slate-400 hover:text-slate-700"
                data-testid="internal-chat-close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-2 bg-slate-50">
              {!activeThreadKey ? (
                <p className="text-center text-slate-400 italic text-sm py-8">
                  Sélectionnez un fil à gauche ou démarrez une nouvelle conversation.
                </p>
              ) : loadingMessages ? (
                <p className="text-center text-slate-500 text-sm py-8">
                  <RefreshCw className="h-4 w-4 inline animate-spin" /> Chargement…
                </p>
              ) : messages.length === 0 ? (
                <p className="text-center text-slate-400 italic text-sm py-8">
                  Aucun message. Soyez le premier à écrire.
                </p>
              ) : (
                messages.map((m) => {
                  const mine = m.sender_id === user?.id;
                  return (
                    <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-2xl px-3 py-2 text-sm shadow-sm ${mine ? "bg-sawali-blue text-white" : "bg-white ring-1 ring-slate-200 text-slate-800"}`}>
                        {!mine && (
                          <p className="text-[10px] font-semibold text-slate-500 mb-0.5">{m.sender_name}</p>
                        )}
                        <p className="whitespace-pre-wrap break-words">{m.text}</p>
                        <p className={`text-[9px] mt-1 text-right ${mine ? "text-white/70" : "text-slate-400"}`}>
                          {fmtTime(m.created_at)}
                        </p>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Composer */}
            {activeThreadKey && (
              <div className="border-t border-slate-200 bg-white p-3">
                <div className="flex items-end gap-2">
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                    placeholder="Écrire un message… (Entrée pour envoyer, Maj+Entrée pour saut de ligne)"
                    rows={1}
                    maxLength={2000}
                    className="flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue/30 max-h-[120px]"
                    data-testid="internal-chat-input"
                    disabled={sending}
                  />
                  <button
                    onClick={sendMessage}
                    disabled={sending || !text.trim()}
                    className="inline-flex items-center justify-center h-10 w-10 rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue-light disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                    data-testid="internal-chat-send"
                  >
                    {sending ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
