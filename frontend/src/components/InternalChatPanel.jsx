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
import { MessageSquareText, Send, X, Hash, Users as UsersIcon, Circle, RefreshCw, Mic, Square, Camera, Image as ImageIcon, Loader2 } from "lucide-react";

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

  // Iter36l — Voice note recording & Whisper transcription state
  const [recState, setRecState] = useState("idle"); // idle | recording | transcribing
  const [recElapsed, setRecElapsed] = useState(0);  // seconds since recording started
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const recTimerRef = useRef(null);

  // Iter36n — Photo upload state
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0); // 0..100
  const [lightbox, setLightbox] = useState(null); // {url, filename} when zoomed
  const cameraInputRef = useRef(null);
  const galleryInputRef = useRef(null);

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

  // ---- Iter36l: Voice note recording → Whisper transcription ----
  const startRecording = async () => {
    if (recState !== "idle") return;
    if (!navigator.mediaDevices || typeof MediaRecorder === "undefined") {
      toast.error("Votre navigateur ne supporte pas l'enregistrement audio");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : (MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "");
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        // Stop the mic
        stream.getTracks().forEach((t) => t.stop());
        if (recTimerRef.current) { clearInterval(recTimerRef.current); recTimerRef.current = null; }
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        audioChunksRef.current = [];
        if (blob.size < 800) {
          // Too short / silent
          setRecState("idle");
          setRecElapsed(0);
          toast.warning("Enregistrement trop court");
          return;
        }
        setRecState("transcribing");
        try {
          const form = new FormData();
          form.append("audio", blob, "voice-note.webm");
          form.append("language", "fr");
          const r = await apiClient.post("/me/chat/transcribe", form, {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 60000,
          });
          const transcribed = (r.data?.text || "").trim();
          if (!transcribed) {
            toast.warning("Aucun texte transcrit — réessayez plus distinctement");
          } else {
            // Insert at end of current text (preserve any existing draft)
            setText((prev) => (prev ? `${prev.trim()} ${transcribed}` : transcribed));
            toast.success("Transcription prête — éditez puis envoyez");
          }
        } catch (err) {
          toast.error(err?.response?.data?.detail || "Erreur de transcription");
        } finally {
          setRecState("idle");
          setRecElapsed(0);
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecState("recording");
      setRecElapsed(0);
      recTimerRef.current = setInterval(() => {
        setRecElapsed((s) => {
          // Auto-stop at 60s
          if (s >= 59) {
            try { recorder.stop(); } catch { /* noop */ }
            return s;
          }
          return s + 1;
        });
      }, 1000);
    } catch (err) {
      toast.error("Microphone refusé ou indisponible");
      setRecState("idle");
    }
  };

  const stopRecording = () => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state === "recording") {
      try { rec.stop(); } catch { /* noop */ }
    }
  };

  // Cleanup on unmount
  useEffect(() => () => {
    if (recTimerRef.current) clearInterval(recTimerRef.current);
    const rec = mediaRecorderRef.current;
    if (rec && rec.state === "recording") {
      try { rec.stop(); } catch { /* noop */ }
    }
  }, []);

  // ---- Iter36n: Client-side photo compression + upload ----
  // Resize to max 1920px on the long edge, JPEG quality 82.
  // Bypass if the source is already small (<400 KB).
  const compressImage = (file) => new Promise((resolve, reject) => {
    if (file.size < 400 * 1024) {
      // Already small enough, send as-is
      resolve(file);
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Lecture du fichier impossible"));
    reader.onload = (e) => {
      const img = new Image();
      img.onerror = () => reject(new Error("Image illisible"));
      img.onload = () => {
        const MAX_EDGE = 1920;
        let { width, height } = img;
        if (width > MAX_EDGE || height > MAX_EDGE) {
          const ratio = Math.min(MAX_EDGE / width, MAX_EDGE / height);
          width = Math.round(width * ratio);
          height = Math.round(height * ratio);
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);
        canvas.toBlob(
          (blob) => {
            if (!blob) return reject(new Error("Compression échouée"));
            // Re-wrap as a File so the backend sees a sensible filename
            const ts = Date.now();
            const out = new File([blob], `photo-${ts}.jpg`, { type: "image/jpeg" });
            resolve(out);
          },
          "image/jpeg",
          0.82,
        );
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });

  const handlePhotoFile = async (file) => {
    if (!file || !activeClientId || !activeThreadKey) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Seules les photos sont supportées pour le moment");
      return;
    }
    setUploadingPhoto(true);
    setUploadProgress(0);
    try {
      // Compress before upload (saves mobile data drastically)
      let toUpload = file;
      try { toUpload = await compressImage(file); } catch { /* fallback to original */ }
      const form = new FormData();
      form.append("photo", toUpload, toUpload.name || "photo.jpg");
      if (activeThreadKey !== "general") {
        form.append("recipient_id", activeThreadKey);
      }
      // Optional caption from the textarea (cleared after send)
      if (text.trim()) form.append("caption", text.trim());
      await apiClient.post(
        `/me/chat/${activeClientId}/messages/photo`,
        form,
        {
          headers: { "Content-Type": "multipart/form-data" },
          timeout: 90000,
          onUploadProgress: (e) => {
            if (e.total) setUploadProgress(Math.round((e.loaded * 100) / e.total));
          },
        },
      );
      setText("");
      loadMessages(activeClientId, activeThreadKey);
      toast.success("Photo envoyée");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec d'envoi de la photo");
    } finally {
      setUploadingPhoto(false);
      setUploadProgress(0);
      if (cameraInputRef.current) cameraInputRef.current.value = "";
      if (galleryInputRef.current) galleryInputRef.current.value = "";
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
                  const hasMedia = m.media_kind === "image" && m.media_url;
                  return (
                    <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                      <div className={`max-w-[75%] rounded-2xl px-3 py-2 text-sm shadow-sm ${mine ? "bg-sawali-blue text-white" : "bg-white ring-1 ring-slate-200 text-slate-800"}`}>
                        {!mine && (
                          <p className="text-[10px] font-semibold text-slate-500 mb-0.5">{m.sender_name}</p>
                        )}
                        {hasMedia && (
                          <button
                            type="button"
                            onClick={() => setLightbox({ url: `${process.env.REACT_APP_BACKEND_URL}${m.media_url}`, msgId: m.id })}
                            className="block mb-1 rounded-lg overflow-hidden ring-1 ring-black/10 max-w-[260px]"
                            data-testid={`chat-media-${m.id}`}
                            title="Cliquer pour agrandir"
                          >
                            <ChatMediaThumb src={`${process.env.REACT_APP_BACKEND_URL}${m.media_url}`} />
                          </button>
                        )}
                        {m.text && (
                          <p className="whitespace-pre-wrap break-words">{m.text}</p>
                        )}
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
                {recState === "recording" && (
                  <div className="mb-2 flex items-center gap-2 rounded-lg bg-rose-50 ring-1 ring-rose-200 px-3 py-2 text-xs text-rose-800" data-testid="internal-chat-recording-indicator">
                    <span className="relative inline-flex">
                      <span className="h-2 w-2 rounded-full bg-rose-500" />
                      <span className="absolute inline-flex h-2 w-2 rounded-full bg-rose-500 opacity-60 animate-ping" />
                    </span>
                    Enregistrement en cours — {String(Math.floor(recElapsed / 60)).padStart(2, "0")}:{String(recElapsed % 60).padStart(2, "0")} / 01:00
                    <span className="ml-auto text-[10px] text-rose-600">Cliquez le carré pour arrêter</span>
                  </div>
                )}
                {recState === "transcribing" && (
                  <div className="mb-2 flex items-center gap-2 rounded-lg bg-sky-50 ring-1 ring-sky-200 px-3 py-2 text-xs text-sky-800" data-testid="internal-chat-transcribing-indicator">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    Transcription par Whisper en cours…
                  </div>
                )}
                {uploadingPhoto && (
                  <div className="mb-2 flex items-center gap-2 rounded-lg bg-emerald-50 ring-1 ring-emerald-200 px-3 py-2 text-xs text-emerald-800" data-testid="internal-chat-uploading-indicator">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Envoi de la photo… {uploadProgress > 0 && `${uploadProgress}%`}
                    <span className="ml-auto inline-block h-1 w-24 rounded-full bg-emerald-200 overflow-hidden">
                      <span
                        className="block h-full bg-emerald-500 transition-all"
                        style={{ width: `${Math.max(5, uploadProgress)}%` }}
                      />
                    </span>
                  </div>
                )}
                <div className="flex items-end gap-2">
                  {/* Iter36n — Camera capture (mobile-native via capture="environment") */}
                  <input
                    ref={cameraInputRef}
                    type="file"
                    accept="image/*"
                    capture="environment"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handlePhotoFile(f); }}
                    className="hidden"
                    data-testid="internal-chat-camera-input"
                  />
                  <input
                    ref={galleryInputRef}
                    type="file"
                    accept="image/*"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handlePhotoFile(f); }}
                    className="hidden"
                    data-testid="internal-chat-gallery-input"
                  />
                  <div className="flex gap-1 shrink-0">
                    <button
                      onClick={() => cameraInputRef.current?.click()}
                      disabled={sending || uploadingPhoto || recState !== "idle"}
                      className="lg:hidden inline-flex items-center justify-center h-10 w-10 rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:opacity-40 disabled:cursor-not-allowed"
                      data-testid="internal-chat-camera"
                      title="Prendre une photo"
                    >
                      <Camera className="h-4 w-4" />
                    </button>
                    <button
                      onClick={() => galleryInputRef.current?.click()}
                      disabled={sending || uploadingPhoto || recState !== "idle"}
                      className="inline-flex items-center justify-center h-10 w-10 rounded-lg bg-slate-100 text-slate-600 hover:bg-slate-200 disabled:opacity-40 disabled:cursor-not-allowed"
                      data-testid="internal-chat-gallery"
                      title="Choisir une photo (galerie / disque)"
                    >
                      {uploadingPhoto ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImageIcon className="h-4 w-4" />}
                    </button>
                  </div>
                  <button
                    onClick={recState === "recording" ? stopRecording : startRecording}
                    disabled={sending || uploadingPhoto || recState === "transcribing"}
                    className={`inline-flex items-center justify-center h-10 w-10 rounded-lg shrink-0 transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                      recState === "recording"
                        ? "bg-rose-500 text-white hover:bg-rose-600 animate-pulse"
                        : recState === "transcribing"
                          ? "bg-sky-100 text-sky-600"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                    data-testid="internal-chat-mic"
                    title={
                      recState === "recording"
                        ? "Arrêter et transcrire"
                        : recState === "transcribing"
                          ? "Transcription en cours…"
                          : "Note vocale (transcription automatique)"
                    }
                  >
                    {recState === "recording"
                      ? <Square className="h-4 w-4 fill-white" />
                      : recState === "transcribing"
                        ? <RefreshCw className="h-4 w-4 animate-spin" />
                        : <Mic className="h-4 w-4" />}
                  </button>
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                    placeholder={
                      recState === "recording"
                        ? "Parlez maintenant…"
                        : recState === "transcribing"
                          ? "Transcription en cours…"
                          : "Écrire un message… (Entrée pour envoyer, Maj+Entrée pour saut de ligne)"
                    }
                    rows={1}
                    maxLength={2000}
                    className="flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue/30 max-h-[120px]"
                    data-testid="internal-chat-input"
                    disabled={sending || recState !== "idle"}
                  />
                  <button
                    onClick={sendMessage}
                    disabled={sending || !text.trim() || recState !== "idle"}
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

      {/* Iter36n — Lightbox */}
      {lightbox && (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/85 cursor-zoom-out"
          onClick={() => setLightbox(null)}
          data-testid="chat-media-lightbox"
        >
          <button
            onClick={() => setLightbox(null)}
            className="absolute top-4 right-4 text-white/80 hover:text-white"
            aria-label="Fermer"
          >
            <X className="h-6 w-6" />
          </button>
          <ChatMediaThumb
            src={lightbox.url}
            className="max-h-[90vh] max-w-[95vw] rounded-lg shadow-2xl object-contain"
            full
          />
        </div>
      )}
    </>
  );
}

// =====================================================================
// Iter36n — Authenticated <img> renderer.
// Chat media URLs require a Bearer token. We fetch the bytes via axios
// (apiClient injects auth), then surface them as an object URL.
// =====================================================================
function ChatMediaThumb({ src, className, full }) {
  const [blobUrl, setBlobUrl] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    let createdUrl = null;
    setError(false);
    setBlobUrl(null);
    (async () => {
      try {
        // src is "<BACKEND>/api/me/chat/media/..." — extract path for apiClient
        const url = new URL(src);
        const path = url.pathname.replace(/^\/api/, "");
        const r = await apiClient.get(path, { responseType: "blob" });
        if (!active) return;
        createdUrl = URL.createObjectURL(r.data);
        setBlobUrl(createdUrl);
      } catch {
        if (active) setError(true);
      }
    })();
    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [src]);

  if (error) {
    return (
      <div className={`flex items-center justify-center bg-slate-100 text-slate-400 text-xs ${full ? "h-40 w-40" : "h-32 w-32"}`}>
        <ImageIcon className="h-5 w-5 mr-1" /> Indisponible
      </div>
    );
  }
  if (!blobUrl) {
    return (
      <div className={`flex items-center justify-center bg-slate-100 ${full ? "h-40 w-full" : "h-32 w-full"}`}>
        <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
      </div>
    );
  }
  return (
    <img
      src={blobUrl}
      alt=""
      className={className || "block w-full h-auto max-h-[280px] object-cover"}
      loading="lazy"
    />
  );
}
