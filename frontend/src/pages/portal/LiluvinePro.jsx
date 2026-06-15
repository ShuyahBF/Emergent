import React, { useEffect, useRef, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Bot, Send, Plus, Trash2, MessageCircle, Loader2, Sparkles, User, Edit2, Globe, Phone, Search, Hand, ArrowRightCircle, HelpCircle, Image as ImageIcon, X } from "lucide-react";
import LiluvineMessageContent from "@/components/LiluvineMessageContent";
import { useResizablePanel, DragHandle } from "@/hooks/useResizablePanel";
import { useAuth } from "@/contexts/AuthContext";

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
  const { user: authUser } = useAuth() || {};
  const userRole = (authUser?.role || "").toLowerCase();
  const trackedRole = (authUser?.tracked_role || "").toLowerCase();
  // S-iter39b — Fix: tracked_role value stored as "Moderation" (not "moderateur").
  // Includes both legacy and current spelling so moderators get the Reprendre button.
  const canTakeover = ["admin", "superviseur", "moderateur"].includes(userRole)
    || ["admin", "superviseur", "moderateur", "moderation", "administrateur"].includes(trackedRole);
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  // Iter38r-fix7 — Branding (per-tenant theming from AdminSettings)
  const [branding, setBranding] = useState({ name: "Liluvine PRO", avatar_url: "", color: "fuchsia" });
  // Feature gate (ai_liluvine_pro must be enabled on parent admin)
  const [featureEnabled, setFeatureEnabled] = useState(true);
  const scrollRef = useRef(null);

  // Iter38r-fix9h — Channel filter (Pack Liluvine a+d)
  const [channelFilter, setChannelFilter] = useState("all"); // all | web | whatsapp | facebook | sms | sms_bird
  const [searchQ, setSearchQ] = useState("");
  // S-iter39b — "3 dernières conversations" quick toggle, always visible.
  // Sorts by updated_at desc and caps the list to the top 3.
  const [recentOnly, setRecentOnly] = useState(false);

  // S037 — "Demander de l'aide" modal state
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpNote, setHelpNote] = useState("");
  const [helpSending, setHelpSending] = useState(false);

  // S044 — Image attachment for "Compare ma capture d'écran avec SAWALI"
  const [attachedImage, setAttachedImage] = useState(null); // File object
  const [attachedPreview, setAttachedPreview] = useState(null); // data: URL for preview
  const fileInputRef = useRef(null);
  const pickAttachedImage = (file) => {
    if (!file) return;
    if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) {
      toast.error("Format non supporté (JPEG, PNG, WebP, GIF uniquement)");
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      toast.error("Image > 15 Mo");
      return;
    }
    setAttachedImage(file);
    const reader = new FileReader();
    reader.onload = (ev) => setAttachedPreview(ev.target?.result || null);
    reader.readAsDataURL(file);
  };
  const clearAttachedImage = () => {
    setAttachedImage(null);
    setAttachedPreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const requestHelp = async () => {
    const note = helpNote.trim();
    if (!note) { toast.error("Veuillez préciser brièvement votre demande."); return; }
    setHelpSending(true);
    try {
      const r = await apiClient.post("/me/liluvine-pro/request-help", {
        note,
        session_id: activeId || null,
      });
      if (r.data?.sent) {
        toast.success("Demande envoyée à l'administrateur via WhatsApp.");
      } else if (r.data?.skipped_reason === "throttled") {
        toast.info("Une demande vient d'être envoyée — patientez quelques minutes avant d'en envoyer une autre.");
      } else if (r.data?.skipped_reason === "disabled") {
        toast.warning("L'escalade est désactivée. Contactez l'administrateur directement.");
      } else if (r.data?.skipped_reason === "no_admin_phone") {
        toast.warning("Aucun numéro admin configuré pour les escalades.");
      } else {
        toast.error("Envoi échoué — réessayez plus tard.");
      }
      setHelpOpen(false);
      setHelpNote("");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lors de l'envoi de la demande.");
    } finally {
      setHelpSending(false);
    }
  };

  // Iter38r-fix9f — Resizable sidebar (matches Direct Chat & WhatsApp panes)
  const { leftWidth, dragHandlers, isCollapsed, toggleCollapsed } = useResizablePanel({
    storageKey: "liluvine_pro_split",
    initial: 280,
    min: 220,
    max: 480,
  });

  const loadSessions = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/liluvine-pro/sessions");
      setSessions(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement des conversations");
    }
  }, []);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  // Iter38r-fix7 — Load tenant-customized branding (name + avatar + color)
  useEffect(() => {
    apiClient.get("/me/liluvine-pro/branding")
      .then((r) => { if (r.data) setBranding({
        name: r.data.name || "Liluvine PRO",
        avatar_url: r.data.avatar_url || "",
        color: r.data.color || "fuchsia",
      }); })
      .catch(() => {/* silent — defaults stay */});
  }, []);

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

  // S044 — Send text + image via chat-with-image endpoint (non-streaming)
  const sendWithImage = async (text) => {
    if (!attachedImage) return;
    setSending(true);
    const tmpUserId = `u-${Date.now()}`;
    const tmpAsstId = `a-${Date.now()}`;
    const localPreview = attachedPreview;
    setMessages((m) => [
      ...m,
      {
        id: tmpUserId,
        role: "user",
        content: text || "📸 Capture d'écran envoyée",
        user_image_url: localPreview,
      },
      { id: tmpAsstId, role: "assistant", content: "", _streaming: true },
    ]);
    const file = attachedImage;
    setInput("");
    clearAttachedImage();
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (text) fd.append("text", text);
      if (activeId) fd.append("session_id", activeId);
      const r = await apiClient.post("/me/liluvine-pro/chat-with-image", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const d = r.data || {};
      if (d.session_id) setActiveId(d.session_id);
      setMessages((m) => m.map((x) => x.id === tmpAsstId ? {
        id: d.message_id || tmpAsstId,
        role: "assistant",
        content: d.reply || "",
        tokens: d.tokens,
        model: d.model,
        matched_images: d.matched_images || [],
      } : x));
      if (d.warn) toast.warning("⚠️ Vous approchez de votre quota IA mensuel (80% atteint).");
      await loadSessions();
    } catch (err) {
      setMessages((m) => m.filter((x) => x.id !== tmpAsstId));
      const detail = err?.response?.data?.detail || err?.message || "Erreur réseau";
      if (err?.response?.status === 429) toast.error(`Quota IA atteint : ${detail}`);
      else if (err?.response?.status === 403) { setFeatureEnabled(false); toast.error(detail); }
      else toast.error(detail);
    } finally { setSending(false); }
  };

  const send = async () => {
    const text = input.trim();
    if (sending) return;
    // S044 — When an image is attached, use the chat-with-image endpoint
    if (attachedImage) {
      await sendWithImage(text);
      return;
    }
    if (!text) return;
    setSending(true);
    const tmpUserId = `u-${Date.now()}`;
    const tmpAsstId = `a-${Date.now()}`;
    // Optimistic UI: user bubble + empty assistant bubble (will fill via stream)
    setMessages((m) => [
      ...m,
      { id: tmpUserId, role: "user", content: text },
      { id: tmpAsstId, role: "assistant", content: "", _streaming: true },
    ]);
    setInput("");
    try {
      // Iter38r-fix9t — SSE pseudo-streaming (Haiku 4.5 + chunked typewriter)
      const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
      const token = localStorage.getItem("sawali_token") || "";
      const resp = await fetch(`${apiBase}/api/me/liluvine-pro/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ text, session_id: activeId }),
      });
      if (!resp.ok) {
        let detail = "Erreur";
        try { const j = await resp.json(); detail = j.detail || detail; } catch { /* ignore */ }
        // Remove the placeholder assistant bubble
        setMessages((m) => m.filter((x) => x.id !== tmpAsstId));
        if (resp.status === 429) toast.error(`Quota IA atteint : ${detail}`);
        else if (resp.status === 403) { setFeatureEnabled(false); toast.error(detail); }
        else toast.error(detail);
        return;
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let assistantText = "";
      let finalMeta = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE events are separated by blank lines (\n\n)
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const lines = block.split("\n");
          let event = "message";
          let data = "";
          for (const line of lines) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          let payload;
          try { payload = JSON.parse(data); } catch { continue; }
          if (event === "session") {
            if (payload.session_id) setActiveId(payload.session_id);
          } else if (event === "token") {
            assistantText += payload.text || "";
            setMessages((m) => m.map((x) => x.id === tmpAsstId ? { ...x, content: assistantText } : x));
          } else if (event === "done") {
            finalMeta = payload;
          } else if (event === "error") {
            setMessages((m) => m.filter((x) => x.id !== tmpAsstId));
            toast.error(payload.detail || "Erreur");
            return;
          }
        }
      }
      if (finalMeta) {
        setMessages((m) => m.map((x) => x.id === tmpAsstId ? {
          id: finalMeta.message_id,
          role: "assistant",
          content: assistantText,
          tokens: finalMeta.tokens,
          model: finalMeta.model,
          context_injected: finalMeta.context_injected,
        } : x));
        if (finalMeta.warn) toast.warning("⚠️ Vous approchez de votre quota IA mensuel (80% atteint).");
      }
      await loadSessions();
    } catch (err) {
      setMessages((m) => m.filter((x) => x.id !== tmpAsstId));
      toast.error(err?.message || "Erreur réseau");
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

  // Iter38r-fix9i — Reprendre / libérer la conversation (admin/superviseur/modération)
  const takeover = async (s) => {
    if (!canTakeover) return;
    if (!window.confirm(`Reprendre la conversation avec ${s.user_label || s.title} ?\n\nLiluvine PRO arrêtera de répondre automatiquement pendant 2 heures.`)) return;
    try {
      const r = await apiClient.post(`/admin/liluvine-pro/sessions/${s.id}/takeover`, { duration_minutes: 120 });
      toast.success("Conversation reprise — Liluvine se tait 👋");
      await loadSessions();
      // Redirect to contacts (WA) for manual reply
      const phone = r.data?.phone_digits;
      const sid = s.id || "";
      if ((sid.startsWith("wa:") || s.external_source === "whatsapp_native" || s.external_source === "whatsapp") && phone) {
        window.location.href = `/portal/contacts?q=${encodeURIComponent(phone)}`;
      }
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const releaseTakeover = async (s) => {
    if (!canTakeover) return;
    if (!window.confirm("Libérer la conversation ? Liluvine PRO reprendra ses réponses automatiques.")) return;
    try {
      await apiClient.post(`/admin/liluvine-pro/sessions/${s.id}/release`);
      toast.success("Conversation libérée — Liluvine reprend la main");
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
    <div className="flex h-[calc(100vh-120px)] gap-0 px-4 py-4" data-testid="liluvine-pro-page">
      {/* Sidebar */}
      {!isCollapsed && (
        <aside
          style={{ width: leftWidth }}
          className="shrink-0 rounded-l-2xl ring-1 ring-slate-200 bg-white flex flex-col"
        >
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
        {/* Iter38r-fix9h — Channel filter tabs */}
        <div className="px-2 pt-2 flex items-center gap-1 overflow-x-auto" data-testid="liluvine-channel-tabs">
          {[
            { id: "all", label: "💬 Toutes", icon: null },
            { id: "web", label: "🌐 Web", icon: Globe },
            { id: "whatsapp", label: "📱 WA", icon: Phone },
            { id: "facebook", label: "📘 FB", icon: null },
            { id: "sms", label: "📩 SMS", icon: null },
            { id: "sms_bird", label: "📡 Bird", icon: null },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setChannelFilter(t.id)}
              className={`shrink-0 text-[10px] px-1.5 py-1 rounded-md transition ${channelFilter === t.id ? "bg-fuchsia-600 text-white font-medium" : "text-slate-600 hover:bg-slate-100"}`}
              data-testid={`liluvine-channel-${t.id}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="px-2 pt-2 pb-1">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-slate-400" />
            <input
              type="text"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              placeholder="Rechercher…"
              className="w-full pl-7 pr-2 py-1 text-xs rounded-md ring-1 ring-slate-200 focus:ring-fuchsia-400 outline-none"
              data-testid="liluvine-search-input"
            />
          </div>
          {/* S-iter39b — "3 dernières conversations" toggle, always visible */}
          <button
            type="button"
            onClick={() => setRecentOnly((v) => !v)}
            className={`mt-2 w-full text-[10px] inline-flex items-center justify-center gap-1 px-2 py-1 rounded-md ring-1 transition ${
              recentOnly
                ? "bg-fuchsia-600 text-white ring-fuchsia-700 font-semibold"
                : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"
            }`}
            title="Afficher uniquement les 3 dernières conversations"
            data-testid="liluvine-recent-only-toggle"
          >
            🕒 3 dernières conversations {recentOnly ? "(actif)" : ""}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1" data-testid="liluvine-sessions-list">
          {(() => {
            let filtered = sessions.filter((s) => {
              // Channel filter — sessions starting with wa:/fb:/sms: vs internal
              const sid = s.id || "";
              const src = s.external_source || "";
              let channel = "web";
              if (sid.startsWith("wa:") || src === "whatsapp_native" || src === "whatsapp") channel = "whatsapp";
              else if (sid.startsWith("fb:") || src === "facebook") channel = "facebook";
              else if (sid.startsWith("sms:bird:") || src === "bird_sms" || src === "sms_bird") channel = "sms_bird";
              else if (sid.startsWith("sms:") || src === "sms") channel = "sms";
              if (channelFilter !== "all" && channel !== channelFilter) return false;
              if (searchQ) {
                const q = searchQ.toLowerCase();
                return (s.title || "").toLowerCase().includes(q) || (s.user_label || "").toLowerCase().includes(q);
              }
              return true;
            });
            // S-iter39b — Cap to 3 most recent when the user enabled "3 dernières"
            if (recentOnly) {
              filtered = [...filtered]
                .sort((a, b) => new Date(b.updated_at || 0) - new Date(a.updated_at || 0))
                .slice(0, 3);
            }
            if (filtered.length === 0) {
              return <p className="text-[11px] text-slate-400 italic px-2 py-4 text-center">Aucune conversation {channelFilter !== "all" ? "sur ce canal" : "encore"}.</p>;
            }
            return filtered.map((s) => {
              const active = s.id === activeId;
              const sid = s.id || "";
              const src = s.external_source || "";
              const isWa = sid.startsWith("wa:") || src === "whatsapp_native" || src === "whatsapp";
              const isFb = sid.startsWith("fb:") || src === "facebook";
              const isBird = sid.startsWith("sms:bird:") || src === "bird_sms" || src === "sms_bird";
              const isSms = !isBird && (sid.startsWith("sms:") || src === "sms");
              const badge = isWa ? "📱 WA" : isFb ? "📘 FB" : isBird ? "📡 Bird" : isSms ? "📩 SMS" : "🌐 Web";
              const badgeColor = isWa ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                : isFb ? "bg-blue-50 text-blue-700 ring-blue-200"
                : isBird ? "bg-orange-50 text-orange-700 ring-orange-200"
                : isSms ? "bg-amber-50 text-amber-700 ring-amber-200"
                : "bg-slate-50 text-slate-600 ring-slate-200";
              const ageMin = s.updated_at ? Math.floor((Date.now() - new Date(s.updated_at).getTime()) / 60000) : null;
              const ageLabel = ageMin === null ? "" :
                ageMin < 1 ? "à l'instant" :
                ageMin < 60 ? `il y a ${ageMin} min` :
                ageMin < 1440 ? `il y a ${Math.floor(ageMin / 60)} h` :
                new Date(s.updated_at).toLocaleDateString("fr-FR");
              return (
                <div
                  key={s.id}
                  className={`group rounded-lg px-2.5 py-2 transition cursor-pointer ${
                    active ? "bg-fuchsia-50 ring-1 ring-fuchsia-400" : "hover:bg-slate-50"
                  }`}
                  onClick={() => loadSession(s.id)}
                  data-testid={`liluvine-session-${s.id}`}
                >
                  <div className="flex items-start justify-between gap-1">
                    <p className={`text-xs font-semibold truncate flex-1 ${active ? "text-fuchsia-700" : "text-slate-700"}`}>
                      {s.title || s.user_label || "Sans titre"}
                    </p>
                    <span className={`text-[8px] uppercase tracking-wider rounded ring-1 px-1 py-0.5 ${badgeColor}`} data-testid={`liluvine-session-badge-${s.id}`}>{badge}</span>
                  </div>
                  {s.user_label && s.user_label !== s.title && (
                    <p className="text-[10px] text-slate-500 truncate">{s.user_label}</p>
                  )}
                  <div className="flex items-center justify-between mt-0.5">
                    <span className="text-[10px] text-slate-400">{s.message_count} msg · {ageLabel}</span>
                    <div className="opacity-0 group-hover:opacity-100 flex gap-0.5 transition">
                      {canTakeover && isWa && !s.human_takeover && (
                        <button
                          onClick={(e) => { e.stopPropagation(); takeover(s); }}
                          className="text-amber-500 hover:text-amber-700 p-0.5"
                          title="Reprendre la conversation (suspend Liluvine 2 h)"
                          data-testid={`liluvine-takeover-${s.id}`}
                        >
                          <Hand className="h-3 w-3" />
                        </button>
                      )}
                      {canTakeover && isWa && s.human_takeover && (
                        <button
                          onClick={(e) => { e.stopPropagation(); releaseTakeover(s); }}
                          className="text-emerald-500 hover:text-emerald-700 p-0.5"
                          title="Libérer — Liluvine reprend"
                          data-testid={`liluvine-release-${s.id}`}
                        >
                          <ArrowRightCircle className="h-3 w-3" />
                        </button>
                      )}
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
                  {s.human_takeover && (
                    <div className="mt-1 inline-flex items-center gap-1 text-[9px] rounded-full bg-amber-50 text-amber-800 ring-1 ring-amber-200 px-1.5 py-0.5">
                      <Hand className="h-2.5 w-2.5" /> Reprise par humain
                    </div>
                  )}
                </div>
              );
            });
          })()}
        </div>
      </aside>
      )}

      {/* Resize handle */}
      {!isCollapsed && <DragHandle dragHandlers={dragHandlers} data-testid="liluvine-resize-handle" />}

      {/* Mobile/Toggle button */}
      <button
        type="button"
        onClick={toggleCollapsed}
        className="hidden sm:inline-flex absolute top-6 left-2 z-10 h-7 w-7 items-center justify-center rounded-full bg-white ring-1 ring-slate-300 shadow text-slate-500 hover:text-fuchsia-600 hover:ring-fuchsia-300 transition"
        title={isCollapsed ? "Afficher les conversations" : "Réduire le panneau"}
        data-testid="liluvine-toggle-sidebar"
      >
        {isCollapsed ? "›" : "‹"}
      </button>

      {/* Main chat */}
      <main className="flex-1 flex flex-col rounded-r-2xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <header className="px-5 py-3 border-b border-slate-100 flex items-center gap-2">
          <div className={`h-9 w-9 rounded-xl bg-gradient-to-br from-${branding.color}-500 to-violet-600 flex items-center justify-center overflow-hidden`}>
            {branding.avatar_url ? (
              <img src={branding.avatar_url} alt={branding.name} className="h-full w-full object-cover" />
            ) : (
              <Bot className="h-5 w-5 text-white" />
            )}
          </div>
          <div className="flex-1">
            <h1 className="font-display font-bold text-slate-900 text-sm inline-flex items-center gap-1">
              {branding.name} <Sparkles className={`h-3 w-3 text-${branding.color}-500`} />
            </h1>
            <p className="text-[11px] text-slate-500">Assistant interne · Claude Sonnet 4.6 · Accès lecture seule à vos données</p>
          </div>
        </header>

        {!featureEnabled && (
          <div className="m-4 rounded-xl ring-1 ring-amber-300 bg-amber-50 p-4 text-sm text-amber-900" data-testid="liluvine-disabled-banner">
            <p className="font-semibold mb-1">⚠️ Fonctionnalité non activée</p>
            <p className="text-xs">
              {branding.name} n'est pas activé pour votre compte. Contactez votre administrateur SAWALI pour demander son activation
              dans <strong>Admin → Clients → Fonctionnalités → {branding.name} (Assistant IA interne)</strong>.
            </p>
          </div>
        )}

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
                  {/* S044 — Display user-attached screenshot */}
                  {m.role === "user" && m.user_image_url && (
                    <img
                      src={m.user_image_url}
                      alt="Capture d'écran envoyée"
                      className="rounded-lg mb-1.5 max-h-48 object-contain ring-1 ring-sky-300/50"
                      data-testid="liluvine-msg-user-image"
                    />
                  )}
                  <LiluvineMessageContent content={m.content} />
                  {/* S044 — Matched SAWALI images carousel */}
                  {m.role === "assistant" && (m.matched_images || []).length > 0 && (
                    <div className="mt-2 grid grid-cols-3 gap-1.5" data-testid="liluvine-msg-matched-images">
                      {m.matched_images.map((mi, idx) => (
                        <a
                          key={mi.image_url + idx}
                          href={mi.image_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="relative group rounded ring-1 ring-slate-300 overflow-hidden bg-white"
                          title={`${mi.title || `Match #${idx + 1}`} (score ${mi.score?.toFixed(2)})`}
                        >
                          <img
                            src={mi.image_url}
                            alt={mi.title || `Match #${idx + 1}`}
                            className="h-20 w-full object-cover"
                          />
                          <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] px-1 py-0.5 truncate">
                            #{idx + 1} · {Math.round((mi.score || 0) * 100)}%
                          </div>
                        </a>
                      ))}
                    </div>
                  )}
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
          {/* S044 — Attached image preview */}
          {attachedPreview && (
            <div className="mb-2 flex items-start gap-2 rounded-lg ring-1 ring-fuchsia-200 bg-fuchsia-50 p-2" data-testid="liluvine-attached-image-preview">
              <img src={attachedPreview} alt="Aperçu de la capture" className="h-16 w-16 object-cover rounded ring-1 ring-fuchsia-200" />
              <div className="flex-1 min-w-0 text-xs">
                <p className="font-semibold text-fuchsia-800">📸 Capture d'écran prête à envoyer</p>
                <p className="text-fuchsia-700/80 truncate">{attachedImage?.name} · {Math.round((attachedImage?.size || 0) / 1024)} Ko</p>
                <p className="text-[10px] text-fuchsia-700/70 mt-0.5">
                  Liluvine va analyser cette image (OCR + Vision) et chercher l'écran SAWALI correspondant.
                </p>
              </div>
              <button
                onClick={clearAttachedImage}
                className="text-fuchsia-700 hover:text-fuchsia-900 p-1"
                title="Retirer l'image"
                data-testid="liluvine-attached-image-remove"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )}
          <div className="flex gap-2 items-end">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
              }}
              placeholder={attachedImage
                ? "Décrivez votre problème en quelques mots (optionnel)…"
                : "Posez votre question… (Entrée = envoyer, Shift+Entrée = nouvelle ligne)"}
              disabled={sending}
              rows={2}
              maxLength={8000}
              className="flex-1 resize-none rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none disabled:opacity-50"
              data-testid="liluvine-input"
            />
            {/* S044 — Attach image */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              onChange={(e) => pickAttachedImage(e.target.files?.[0])}
              className="hidden"
              data-testid="liluvine-attach-image-input"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={sending || helpSending}
              className="inline-flex items-center gap-1 rounded-lg bg-slate-100 text-slate-700 ring-1 ring-slate-200 px-2.5 py-2 text-sm hover:bg-slate-200 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="liluvine-attach-image-btn"
              title="Envoyer une capture d'écran — Liluvine identifiera l'écran SAWALI et la procédure"
            >
              <ImageIcon className="h-4 w-4" />
              <span className="hidden sm:inline">Capture</span>
            </button>
            <button
              onClick={() => setHelpOpen(true)}
              disabled={sending || helpSending}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-50 text-rose-700 ring-1 ring-rose-200 px-3.5 py-2 text-sm hover:bg-rose-100 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="liluvine-request-help-btn"
              title="Envoyer une demande d'aide à l'administrateur via WhatsApp"
            >
              <HelpCircle className="h-4 w-4" />
              Demander de l'aide
            </button>
            <button
              onClick={send}
              disabled={sending || (!input.trim() && !attachedImage) || !featureEnabled}
              className={`inline-flex items-center gap-1.5 rounded-lg bg-${branding.color}-600 text-white px-3.5 py-2 text-sm hover:bg-${branding.color}-700 disabled:opacity-40 disabled:cursor-not-allowed shadow-sm`}
              data-testid="liluvine-send-btn"
            >
              <Send className="h-4 w-4" />
              {sending ? "Envoi…" : (attachedImage ? "Analyser" : "Envoyer")}
            </button>
          </div>
          <p className="text-[10px] text-slate-400 mt-1 tabular-nums">
            {input.length} / 8000 · Mots-clés détectés : contacts, tickets, paiements, RDV, notes
          </p>
        </div>
      </main>

      {/* S037 — Modal "Demander de l'aide" */}
      {helpOpen && (
        <div
          className="fixed inset-0 z-[100] bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => !helpSending && setHelpOpen(false)}
          data-testid="liluvine-help-modal"
        >
          <div
            className="bg-white rounded-xl shadow-2xl max-w-md w-full p-5 space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-gradient-to-br from-rose-500 to-fuchsia-600 text-white grid place-items-center">
                <HelpCircle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-800">Demander de l'aide à l'admin</h3>
                <p className="text-xs text-slate-500">Un message WhatsApp avec le contexte de votre conversation lui sera envoyé.</p>
              </div>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Expliquez brièvement pourquoi vous avez besoin d'aide
              </label>
              <textarea
                value={helpNote}
                onChange={(e) => setHelpNote(e.target.value)}
                placeholder="Ex : Je n'arrive pas à expliquer la procédure de remboursement à ce client…"
                rows={4}
                maxLength={500}
                disabled={helpSending}
                className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm focus:ring-fuchsia-500 focus:ring-2 outline-none disabled:opacity-50"
                data-testid="liluvine-help-note-input"
                autoFocus
              />
              <p className="text-[10px] text-slate-400 mt-1 tabular-nums">{helpNote.length} / 500</p>
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setHelpOpen(false); setHelpNote(""); }}
                disabled={helpSending}
                className="text-sm px-3 py-2 rounded-lg ring-1 ring-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                data-testid="liluvine-help-cancel-btn"
              >
                Annuler
              </button>
              <button
                onClick={requestHelp}
                disabled={helpSending || !helpNote.trim()}
                className="text-sm px-4 py-2 rounded-lg bg-gradient-to-r from-rose-500 to-fuchsia-600 text-white shadow-md hover:from-rose-600 hover:to-fuchsia-700 disabled:opacity-50 inline-flex items-center gap-1.5"
                data-testid="liluvine-help-submit-btn"
              >
                {helpSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {helpSending ? "Envoi…" : "Envoyer la demande"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
