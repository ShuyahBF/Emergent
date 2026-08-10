/*
 * Iter38i — Unified omnichannel inbox.
 * Aggregates WhatsApp + Messenger threads. Two-pane layout: thread list (left)
 * and message view (right). Channel-colored badges and unread counts.
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { MessageCircle, Facebook, Loader2, RefreshCw, Inbox as InboxIcon, Send, Smartphone, ArrowDown, CircleDollarSign, Trash2 } from "lucide-react";
import { toast } from "sonner";

const channelMeta = {
  whatsapp: { label: "WA", color: "bg-emerald-100 text-emerald-700 ring-emerald-200", Icon: MessageCircle },
  sms: { label: "SMS", color: "bg-amber-100 text-amber-700 ring-amber-200", Icon: Smartphone },
  sms_bird: { label: "SMS Bird", color: "bg-sky-100 text-sky-700 ring-sky-200", Icon: Smartphone }, // Iter43-fix24b
  messenger: { label: "MSG", color: "bg-blue-100 text-blue-700 ring-blue-200", Icon: Facebook },
};

export default function UnifiedInbox() {
  const [threads, setThreads] = useState([]);
  const [totals, setTotals] = useState({});
  const [channelsEnabled, setChannelsEnabled] = useState({});
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null); // {channel, peer_id, page_id?, peer_name}
  const [messages, setMessages] = useState([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [filterCh, setFilterCh] = useState("all");
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  // Iter43-fix24d — Badge coût Bird du jour
  const [birdCost, setBirdCost] = useState(null);
  const messagesEndRef = React.useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/inbox/unified?limit=60");
      setThreads(r.data?.items || []);
      setTotals(r.data?.totals || {});
      setChannelsEnabled(r.data?.channels_enabled || {});
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  }, []);

  // Iter43-fix24d — Coût Bird quotidien (rafraîchi à chaque load)
  const loadBirdCost = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/inbox/bird-cost-today");
      setBirdCost(r.data?.enabled ? r.data : null);
    } catch { setBirdCost(null); }
  }, []);

  useEffect(() => { load(); loadBirdCost(); }, [load, loadBirdCost]);

  // Iter38j — Poll every 20s to refresh threads (cheap call, ~60 threads max)
  useEffect(() => {
    const id = setInterval(() => { load(); loadBirdCost(); }, 20000);
    return () => clearInterval(id);
  }, [load, loadBirdCost]);

  // Iter38j — Update browser tab title with unread count
  useEffect(() => {
    const n = totals.unread || 0;
    document.title = n > 0 ? `(${n}) Inbox — SAWALI` : "Inbox — SAWALI";
    return () => { document.title = "SAWALI SMART SYSTEMS"; };
  }, [totals.unread]);

  // Auto-scroll bottom on new messages
  useEffect(() => {
    if (messagesEndRef.current) messagesEndRef.current.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const openThread = async (t) => {
    setSelected(t);
    setLoadingMsgs(true);
    setMessages([]);
    setComposer("");
    try {
      const q = t.channel === "messenger" && t.page_id ? `?page_id=${encodeURIComponent(t.page_id)}` : "";
      const r = await apiClient.get(`/me/inbox/unified/${t.channel}/${encodeURIComponent(t.peer_id)}${q}`);
      setMessages(r.data?.messages || []);
      // Iter38j — Mark thread as read silently
      if (t.unread_count > 0) {
        try {
          await apiClient.post(`/me/inbox/mark-read/${t.channel}/${encodeURIComponent(t.peer_id)}${q}`);
          load();
        } catch { /* noop */ }
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoadingMsgs(false); }
  };

  const sendMessage = async () => {
    if (!selected || !composer.trim() || sending) return;
    setSending(true);
    try {
      await apiClient.post("/me/inbox/send", {
        channel: selected.channel,
        thread_id: selected.peer_id,
        text: composer.trim(),
        page_id: selected.page_id,
      });
      // Optimistically add to messages
      setMessages((m) => [...m, {
        id: `local-${Date.now()}`, direction: "outbound", text: composer.trim(),
        at: new Date().toISOString(),
      }]);
      setComposer("");
      toast.success("Message envoyé");
      // Refresh threads list to update last_at
      setTimeout(() => load(), 500);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally { setSending(false); }
  };

  const filtered = threads.filter((t) => filterCh === "all" || t.channel === filterCh);

  // 2026-02 fork (Delete WA) — Recall an outbound message from within its 15min window.
  const recallMessage = async (m) => {
    if (!m?.id) return;
    const confirmMsg = m.status === "read"
      ? "Ce message a été lu. Rappel impossible (limitation Meta)."
      : `Rappeler ce message ?\n\nNote : WhatsApp n'efface PAS le message chez le destinataire (limitation Meta), il sera juste retiré de votre vue CRM.`;
    if (m.status === "read") { toast.error(confirmMsg); return; }
    if (!window.confirm(confirmMsg)) return;
    try {
      const r = await apiClient.patch(`/me/whatsapp/messages/${m.id}/recall`);
      // Optimistically mark the message recalled in place
      setMessages((list) => list.map((x) => (
        x.id === m.id ? { ...x, is_recalled: true, recalled_at: r.data?.recalled_at } : x
      )));
      if (r.data?.warning) toast.warning(r.data.warning, { duration: 6000 });
      else toast.success("Message rappelé");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de rappeler ce message");
    }
  };

  const canRecall = (m) => {
    if (m.direction !== "outbound") return false;
    if (m.is_recalled) return false;
    // status may be null (Meta hasn't ack'd yet), "sent", "delivered", "read", "failed"
    if (m.status === "read") return false;
    // Age check : reject if older than 15 min (same as backend)
    const ref = m.sent_at || m.at;
    if (ref) {
      const ageMin = (Date.now() - new Date(ref).getTime()) / 60000;
      // For "failed" status age doesn't matter
      if (m.status !== "failed" && ageMin > 15) return false;
    }
    return true;
  };

  return (
    <div className="p-6 space-y-4" data-testid="unified-inbox">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <InboxIcon className="h-7 w-7 text-indigo-600" />
          <div>
            <h1 className="text-2xl font-display font-bold">Inbox unifiée</h1>
            <p className="text-sm text-slate-500">
              Tous vos canaux (WhatsApp{channelsEnabled.sms_bird ? " + SMS Bird" : ""}{channelsEnabled.messenger ? " + Messenger" : ""}) en un seul écran.
              {totals.unread > 0 && <span className="ml-2 inline-flex items-center gap-1 bg-rose-50 text-rose-700 px-2 py-0.5 rounded-full text-xs font-medium">{totals.unread} non-lu(s)</span>}
              {birdCost && birdCost.enabled && (
                <span
                  className="ml-2 inline-flex items-center gap-1 bg-sky-50 text-sky-700 ring-1 ring-sky-200 px-2 py-0.5 rounded-full text-xs font-medium"
                  title={`Aujourd'hui : ${birdCost.count} SMS Bird envoyés à ${birdCost.unit_cost} ${birdCost.currency}/SMS`}
                  data-testid="bird-cost-badge"
                >
                  <CircleDollarSign className="h-3 w-3" />
                  Aujourd&apos;hui : {birdCost.cost.toLocaleString("fr-FR")} {birdCost.currency} ({birdCost.count} SMS Bird)
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={filterCh} onChange={(e) => setFilterCh(e.target.value)}
            className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm"
            data-testid="inbox-channel-filter"
          >
            <option value="all">Tous canaux ({threads.length})</option>
            <option value="whatsapp">WhatsApp ({totals.whatsapp || 0})</option>
            <option value="sms">SMS ({totals.sms || 0})</option>
            {channelsEnabled.sms_bird && <option value="sms_bird">SMS Bird ({totals.sms_bird || 0})</option>}
            {channelsEnabled.messenger && <option value="messenger">Messenger ({totals.messenger || 0})</option>}
          </select>
          <button onClick={load} className="inline-flex items-center gap-1 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm" data-testid="inbox-refresh-btn">
            <RefreshCw className="h-4 w-4" /> Actualiser
          </button>
        </div>
      </div>

      {/* Two-pane layout */}
      <div className="grid lg:grid-cols-[360px_1fr] gap-4 h-[70vh]">
        {/* Thread list */}
        <div className="bg-white border border-slate-200 rounded-lg overflow-y-auto" data-testid="inbox-threads">
          {loading ? (
            <div className="p-8 flex items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-indigo-500" /></div>
          ) : filtered.length === 0 ? (
            <p className="p-6 text-sm text-slate-400 italic text-center">Aucune conversation.</p>
          ) : (
            <div className="divide-y divide-slate-100">
              {filtered.map((t) => {
                const meta = channelMeta[t.channel] || channelMeta.whatsapp;
                const Icon = meta.Icon;
                const isActive = selected?.channel === t.channel && selected?.peer_id === t.peer_id;
                return (
                  <button
                    key={`${t.channel}-${t.peer_id}-${t.page_id || ""}`}
                    onClick={() => openThread(t)}
                    className={`w-full text-left p-3 hover:bg-slate-50 transition ${isActive ? "bg-indigo-50" : ""}`}
                    data-testid={`thread-${t.channel}-${t.peer_id}`}
                  >
                    <div className="flex items-start gap-2">
                      <span className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold ring-1 ${meta.color}`}>
                        <Icon className="h-2.5 w-2.5" /> {meta.label}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-medium text-slate-800 truncate">{t.peer_name || t.peer_id}</p>
                          {t.unread_count > 0 && (
                            <span className="inline-flex items-center justify-center bg-rose-500 text-white text-[10px] rounded-full min-w-[18px] h-[18px] px-1 font-medium">
                              {t.unread_count}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-500 truncate mt-0.5">{t.preview || <em>(sans texte)</em>}</p>
                        {t.page_name && <p className="text-[10px] text-slate-400 mt-0.5">via {t.page_name}</p>}
                        <p className="text-[10px] text-slate-400 mt-0.5">{t.last_at ? new Date(t.last_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "-"}</p>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Messages */}
        <div className="bg-white border border-slate-200 rounded-lg flex flex-col" data-testid="inbox-messages">
          {!selected ? (
            <div className="flex-1 flex items-center justify-center text-sm text-slate-400">
              Sélectionnez une conversation pour afficher les messages.
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {(() => {
                    const meta = channelMeta[selected.channel] || channelMeta.whatsapp;
                    const Icon = meta.Icon;
                    return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${meta.color}`}>
                      <Icon className="h-3 w-3" /> {selected.channel === "whatsapp" ? "WhatsApp" : "Messenger"}
                    </span>;
                  })()}
                  <h3 className="font-display font-semibold">{selected.peer_name || selected.peer_id}</h3>
                </div>
                <ArrowDown className="h-4 w-4 text-slate-400" />
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-2 bg-slate-50">
                {loadingMsgs ? (
                  <Loader2 className="h-5 w-5 animate-spin text-indigo-500 mx-auto" />
                ) : messages.length === 0 ? (
                  <p className="text-xs text-slate-400 italic text-center">Aucun message.</p>
                ) : messages.map((m, i) => {
                  const isOut = m.direction === "outbound";
                  const showRecallBtn = isOut && canRecall(m);
                  if (m.is_recalled) {
                    return (
                      <div key={i} className={`flex ${isOut ? "justify-end" : "justify-start"}`}>
                        <div
                          className="max-w-[70%] rounded-2xl px-3 py-2 text-xs italic bg-slate-100 border border-slate-200 text-slate-500 flex items-center gap-1.5"
                          data-testid={`inbox-message-recalled-${m.id}`}
                        >
                          <Trash2 className="h-3 w-3 shrink-0" />
                          <span>Message rappelé{m.recalled_at ? ` · ${new Date(m.recalled_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}` : ""}</span>
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div key={i} className={`flex group ${isOut ? "justify-end" : "justify-start"}`}>
                      {showRecallBtn && (
                        <button
                          type="button"
                          onClick={() => recallMessage(m)}
                          className="opacity-0 group-hover:opacity-100 self-center mr-1 p-1 rounded-md bg-white text-red-600 hover:bg-red-50 border border-red-200 shadow-sm transition-opacity"
                          title="Rappeler ce message (dans les 15 min après envoi)"
                          data-testid={`inbox-recall-btn-${m.id}`}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                      <div className={`max-w-[70%] rounded-2xl px-3 py-2 text-sm ${isOut ? "bg-indigo-600 text-white" : "bg-white border border-slate-200 text-slate-800"}`}>
                        <p className="whitespace-pre-wrap break-words">{m.text || <em>(média)</em>}</p>
                        {m.media_url && <a href={m.media_url} target="_blank" rel="noreferrer" className={`text-xs underline mt-1 block ${isOut ? "text-indigo-100" : "text-indigo-600"}`}>📎 Pièce jointe</a>}
                        <p className={`text-[10px] mt-1 ${isOut ? "text-indigo-200" : "text-slate-400"}`}>{m.at ? new Date(m.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</p>
                      </div>
                    </div>
                  );
                })}
                <div ref={messagesEndRef} />
              </div>
              <div className="p-3 border-t border-slate-200">
                <div className="flex items-end gap-2">
                  <textarea
                    value={composer} onChange={(e) => setComposer(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                    placeholder={`Répondre via ${selected.channel === "whatsapp" ? "WhatsApp" : "Messenger"}…`}
                    rows={1}
                    className="flex-1 resize-none px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    data-testid="inbox-composer"
                  />
                  <button
                    onClick={sendMessage} disabled={sending || !composer.trim()}
                    className="inline-flex items-center gap-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
                    data-testid="inbox-send-btn"
                  >
                    {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                    Envoyer
                  </button>
                </div>
                <p className="text-[10px] text-slate-400 mt-1">
                  Entrée pour envoyer · Maj+Entrée pour saut de ligne
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
