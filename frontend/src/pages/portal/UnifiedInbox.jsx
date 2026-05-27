/*
 * Iter38i — Unified omnichannel inbox.
 * Aggregates WhatsApp + Messenger threads. Two-pane layout: thread list (left)
 * and message view (right). Channel-colored badges and unread counts.
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { MessageCircle, Facebook, Loader2, RefreshCw, Inbox as InboxIcon, ArrowDown } from "lucide-react";
import { toast } from "sonner";

const channelMeta = {
  whatsapp: { label: "WA", color: "bg-emerald-100 text-emerald-700 ring-emerald-200", Icon: MessageCircle },
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

  useEffect(() => { load(); }, [load]);

  const openThread = async (t) => {
    setSelected(t);
    setLoadingMsgs(true);
    setMessages([]);
    try {
      const q = t.channel === "messenger" && t.page_id ? `?page_id=${encodeURIComponent(t.page_id)}` : "";
      const r = await apiClient.get(`/me/inbox/unified/${t.channel}/${encodeURIComponent(t.peer_id)}${q}`);
      setMessages(r.data?.messages || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoadingMsgs(false); }
  };

  const filtered = threads.filter((t) => filterCh === "all" || t.channel === filterCh);

  return (
    <div className="p-6 space-y-4" data-testid="unified-inbox">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <InboxIcon className="h-7 w-7 text-indigo-600" />
          <div>
            <h1 className="text-2xl font-display font-bold">Inbox unifiée</h1>
            <p className="text-sm text-slate-500">
              Tous vos canaux (WhatsApp{channelsEnabled.messenger ? " + Messenger" : ""}) en un seul écran.
              {totals.unread > 0 && <span className="ml-2 inline-flex items-center gap-1 bg-rose-50 text-rose-700 px-2 py-0.5 rounded-full text-xs font-medium">{totals.unread} non-lu(s)</span>}
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
                  return (
                    <div key={i} className={`flex ${isOut ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[70%] rounded-2xl px-3 py-2 text-sm ${isOut ? "bg-indigo-600 text-white" : "bg-white border border-slate-200 text-slate-800"}`}>
                        <p className="whitespace-pre-wrap break-words">{m.text || <em>(média)</em>}</p>
                        {m.media_url && <a href={m.media_url} target="_blank" rel="noreferrer" className={`text-xs underline mt-1 block ${isOut ? "text-indigo-100" : "text-indigo-600"}`}>📎 Pièce jointe</a>}
                        <p className={`text-[10px] mt-1 ${isOut ? "text-indigo-200" : "text-slate-400"}`}>{m.at ? new Date(m.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : ""}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="p-3 border-t border-slate-200 text-xs text-slate-500 italic flex items-center gap-2">
                💬 Envoi de messages depuis l'inbox unifiée — disponible dans la prochaine itération. Utilisez en attendant <strong>Centre de Messagerie</strong> (WhatsApp) ou <strong>Meta → Messenger</strong>.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
