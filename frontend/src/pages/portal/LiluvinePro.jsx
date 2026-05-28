import React, { useEffect, useRef, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Bot, Send, Plus, Trash2, MessageCircle, Loader2, Sparkles, User, Edit2 } from "lucide-react";

/*
  Iter38r-fix6 — Liluvine PRO / Assistant SAWALI

  Chat page with:
   - Sidebar listing the user's previous sessions
   - Main chat area with message history + composer
   - Auto-injection of business context (contacts, tickets, payments, RDV, notes)
     via keyword detection on the server
   - Tokens tracked through the AI Quotas module
*/
export default function LiluvinePro() {
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const scrollRef = useRef(null);

  const loadSessions = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/liluvine-pro/sessions");
      setSessions(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement des conversations");
    }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  const loadSession = async (sid) => {
    if (!sid) { setMessages([]); setActiveId(null); return; }
    setLoadingSession(true);
    try {
      const r = await apiClient.get(`/me/liluvine-pro/sessions/${sid}`);
      setMessages(r.data?.messages || []);
      setActiveId(sid);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Conversation introuvable");
    } finally { setLoadingSession(false); }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    setMessages((m) => [...m, { id: `tmp-${Date.now()}`, role: "user", content: text, _pending: true }]);
    setInput("");
    try {
      const r = await apiClient.post("/me/liluvine-pro/chat", {
        text, session_id: activeId,
      });
      setActiveId(r.data.session_id);
      setMessages((m) => [
        ...m.filter((x) => !x._pending),
        { id: `u-${r.data.message_id}`, role: "user", content: text },
        { id: r.data.message_id, role: "assistant", content: r.data.reply,
          tokens: r.data.tokens, model: r.data.model,
          context_injected: r.data.context_injected },
      ]);
      if (r.data.warn) {
        toast.warning("⚠️ Vous approchez de votre quota IA mensuel (80% atteint).");
      }
      await loadSessions();
    } catch (err) {
      setMessages((m) => m.filter((x) => !x._pending));
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail || "Erreur";
      if (status === 429) {
        toast.error(`Quota IA atteint : ${detail}`);
      } else {
        toast.error(detail);
      }
    } finally { setSending(false); }
  };

  const startNew = () => { setActiveId(null); setMessages([]); setInput(""); };

  const delSession = async (sid) => {
    if (!window.confirm("Supprimer cette conversation ? (irréversible)")) return;
    try {
      await apiClient.delete(`/me/liluvine-pro/sessions/${sid}`);
      toast.success("Conversation supprimée");
      if (activeId === sid) startNew();
      await loadSessions();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const rename = async (sid, current) => {
    const next = window.prompt("Nouveau titre :", current);
    if (!next || next === current) return;
    try {
      await apiClient.patch(`/me/liluvine-pro/sessions/${sid}`, { title: next });
      await loadSessions();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  // Auto-scroll to bottom on new message
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="flex h-[calc(100vh-120px)] gap-3 px-4 py-4" data-testid="liluvine-pro-page">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 rounded-2xl ring-1 ring-slate-200 bg-white flex flex-col">
        <div className="p-3 border-b border-slate-100 flex items-center justify-between">
          <p className="text-xs uppercase tracking-wider font-semibold text-slate-500">Conversations</p>
          <button
            onClick={startNew}
            className="inline-flex items-center gap-1 rounded-lg bg-fuchsia-600 text-white px-2 py-1 text-xs hover:bg-fuchsia-700"
            data-testid="liluvine-new-session-btn"
          >
            <Plus className="h-3 w-3" /> Nouvelle
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1" data-testid="liluvine-sessions-list">
          {sessions.length === 0 ? (
            <p className="text-[11px] text-slate-400 italic px-2 py-4 text-center">Aucune conversation encore.</p>
          ) : sessions.map((s) => {
            const active = s.id === activeId;
            return (
              <div
                key={s.id}
                className={`group rounded-lg px-2.5 py-2 transition cursor-pointer ${
                  active ? "bg-fuchsia-50 ring-1 ring-fuchsia-400" : "hover:bg-slate-50"
                }`}
                onClick={() => loadSession(s.id)}
                data-testid={`liluvine-session-${s.id}`}
              >
                <p className={`text-xs font-semibold truncate ${active ? "text-fuchsia-700" : "text-slate-700"}`}>
                  {s.title || "Sans titre"}
                </p>
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-[10px] text-slate-400">{s.message_count} msg · {new Date(s.updated_at).toLocaleDateString("fr-FR")}</span>
                  <div className="opacity-0 group-hover:opacity-100 flex gap-0.5 transition">
                    <button
                      onClick={(e) => { e.stopPropagation(); rename(s.id, s.title); }}
                      className="text-slate-400 hover:text-sky-600 p-0.5"
                      title="Renommer"
                    >
                      <Edit2 className="h-3 w-3" />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); delSession(s.id); }}
                      className="text-slate-400 hover:text-rose-600 p-0.5"
                      title="Supprimer"
                      data-testid={`liluvine-del-${s.id}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Main chat */}
      <main className="flex-1 flex flex-col rounded-2xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <header className="px-5 py-3 border-b border-slate-100 flex items-center gap-2">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-fuchsia-500 to-violet-600 flex items-center justify-center">
            <Bot className="h-5 w-5 text-white" />
          </div>
          <div className="flex-1">
            <h1 className="font-display font-bold text-slate-900 text-sm inline-flex items-center gap-1">
              Liluvine PRO <Sparkles className="h-3 w-3 text-fuchsia-500" />
            </h1>
            <p className="text-[11px] text-slate-500">Assistant interne · Claude Sonnet 4.6 · Accès lecture seule à vos données</p>
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-4" data-testid="liluvine-messages-area">
          {loadingSession ? (
            <p className="text-center text-slate-400 italic py-12">Chargement…</p>
          ) : messages.length === 0 ? (
            <div className="text-center py-12 max-w-md mx-auto">
              <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-fuchsia-500 to-violet-600 flex items-center justify-center mx-auto mb-4">
                <Bot className="h-8 w-8 text-white" />
              </div>
              <h2 className="font-display font-bold text-lg text-slate-900 mb-2">Bonjour 👋</h2>
              <p className="text-sm text-slate-600 leading-relaxed">
                Je suis votre assistant interne. Posez-moi des questions sur vos contacts, tickets, paiements, rendez-vous ou notes — j'ai accès à vos données en lecture seule.
              </p>
              <div className="mt-4 grid grid-cols-1 gap-2">
                {[
                  "Combien j'ai de tickets ouverts cette semaine ?",
                  "Liste mes 5 derniers paiements PawaPay",
                  "Rédige-moi un SMS de rappel RDV poli",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => setInput(suggestion)}
                    className="text-left text-xs rounded-lg ring-1 ring-slate-200 hover:ring-fuchsia-400 px-3 py-2 bg-white hover:bg-fuchsia-50 transition"
                    data-testid={`liluvine-suggestion-${suggestion.slice(0, 10)}`}
                  >
                    💡 {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) => (
              <div
                key={m.id}
                className={`flex gap-2 ${m.role === "user" ? "justify-end" : "justify-start"}`}
                data-testid={`liluvine-msg-${m.role}`}
              >
                {m.role === "assistant" && (
                  <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-fuchsia-500 to-violet-600 flex items-center justify-center shrink-0">
                    <Bot className="h-4 w-4 text-white" />
                  </div>
                )}
                <div className={`max-w-[75%] rounded-2xl px-3.5 py-2 ${
                  m.role === "user"
                    ? "bg-sky-600 text-white"
                    : "bg-slate-50 ring-1 ring-slate-200 text-slate-800"
                }`}>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>
                  {m.role === "assistant" && (m.tokens || m.context_injected) && (
                    <p className="text-[9px] text-slate-400 mt-1">
                      {m.tokens && <>~{m.tokens} tokens · </>}
                      {m.context_injected && <>📚 Contexte DB injecté · </>}
                      {m.model || ""}
                    </p>
                  )}
                </div>
                {m.role === "user" && (
                  <div className="h-8 w-8 rounded-lg bg-sky-600 flex items-center justify-center shrink-0">
                    <User className="h-4 w-4 text-white" />
                  </div>
                )}
              </div>
            ))
          )}
          {sending && (
            <div className="flex gap-2" data-testid="liluvine-typing">
              <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-fuchsia-500 to-violet-600 flex items-center justify-center shrink-0">
                <Loader2 className="h-4 w-4 text-white animate-spin" />
              </div>
              <div className="rounded-2xl px-4 py-2 bg-slate-50 ring-1 ring-slate-200 text-slate-500 text-sm italic">
                Liluvine réfléchit…
              </div>
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="p-3 border-t border-slate-100" data-testid="liluvine-composer">
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
              }}
              placeholder="Posez votre question… (Entrée = envoyer, Shift+Entrée = nouvelle ligne)"
              disabled={sending}
              rows={2}
              maxLength={8000}
              className="flex-1 resize-none rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none disabled:opacity-50"
              data-testid="liluvine-input"
            />
            <button
              onClick={send}
              disabled={sending || !input.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-fuchsia-600 text-white px-3.5 py-2 text-sm hover:bg-fuchsia-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
              data-testid="liluvine-send-btn"
            >
              <Send className="h-4 w-4" />
              {sending ? "Envoi…" : "Envoyer"}
            </button>
          </div>
          <p className="text-[10px] text-slate-400 mt-1 tabular-nums">
            {input.length} / 8000 · Mots-clés détectés : contacts, tickets, paiements, RDV, notes
          </p>
        </div>
      </main>
    </div>
  );
}
