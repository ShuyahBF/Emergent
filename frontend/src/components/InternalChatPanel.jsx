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
import { MessageSquareText, Send, X, Hash, Users as UsersIcon, Circle, RefreshCw, Mic, Square, Camera, Image as ImageIcon, Loader2, Sparkles, Search, Reply, PanelLeftClose, PanelLeft } from "lucide-react";
import { useResizablePanel, DragHandle } from "@/hooks/useResizablePanel";

/*
 * Iter36r — Distinct sound for incoming internal chat messages.
 *
 * To stand out from the WhatsApp notifier (880Hz → 1320Hz, single tone),
 * we play a warmer two-note motif (E5 → G5, triangle wave) reminiscent
 * of a friendly conversation chime. ~280 ms total, soft attack.
 */
function playChatBlip() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const masterGain = ctx.createGain();
    masterGain.connect(ctx.destination);
    masterGain.gain.value = 0.25;

    const tones = [
      { freq: 659.25, start: 0,    dur: 0.16 }, // E5
      { freq: 783.99, start: 0.10, dur: 0.20 }, // G5 (slight overlap for legato)
    ];
    tones.forEach(({ freq, start, dur }) => {
      const osc = ctx.createOscillator();
      const env = ctx.createGain();
      osc.connect(env);
      env.connect(masterGain);
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
      env.gain.setValueAtTime(0.0001, ctx.currentTime + start);
      env.gain.exponentialRampToValueAtTime(0.7, ctx.currentTime + start + 0.02);
      env.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
      osc.start(ctx.currentTime + start);
      osc.stop(ctx.currentTime + start + dur + 0.02);
    });
    setTimeout(() => { try { ctx.close(); } catch { /* noop */ } }, 600);
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

// Iter36s — Render a snippet with the search term highlighted in <mark>
function highlightTerm(text, term) {
  if (!text || !term) return text;
  try {
    const safe = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const rx = new RegExp(`(${safe})`, "ig");
    const parts = text.split(rx);
    return parts.map((p, i) =>
      rx.test(p)
        ? <mark key={i} className="bg-amber-200 text-amber-900 rounded px-0.5">{p}</mark>
        : <span key={i}>{p}</span>
    );
  } catch {
    return text;
  }
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

  // Iter36q — One-time tutorial popover next to the microphone button.
  // Persists in localStorage so it never reappears once dismissed.
  const MIC_INTRO_KEY = "sawali_chat_mic_intro_seen";
  const [showMicIntro, setShowMicIntro] = useState(false);
  useEffect(() => {
    if (!open || !activeThreadKey) return;
    let seen = false;
    try { seen = localStorage.getItem(MIC_INTRO_KEY) === "1"; } catch { /* noop */ }
    if (!seen) {
      const t = setTimeout(() => setShowMicIntro(true), 600);
      return () => clearTimeout(t);
    }
  }, [open, activeThreadKey]);
  const dismissMicIntro = () => {
    setShowMicIntro(false);
    try { localStorage.setItem(MIC_INTRO_KEY, "1"); } catch { /* noop */ }
  };

  // Iter36s — Full-text search across history
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [highlightMsgId, setHighlightMsgId] = useState(null);
  const searchInputRef = useRef(null);

  // Iter38d — Resizable left panel (mouse + touch) + mobile collapse
  const { leftWidth, dragHandlers, isCollapsed, toggleCollapsed } = useResizablePanel({
    storageKey: "sawali_internal_chat_split",
    initial: 256,
    min: 180,
    max: 480,
  });

  // Iter38d — Expense reminder banner (shown to tracked users with cashier access)
  const [expenseReminder, setExpenseReminder] = useState(null);
  useEffect(() => {
    if (!open) return;
    apiClient
      .get("/cashier/expenses/me/dashboard-card")
      .then((r) => {
        const d = r.data;
        if (d && d.count > 0) setExpenseReminder(d); else setExpenseReminder(null);
      })
      .catch(() => setExpenseReminder(null));
  }, [open]);

  // Iter36t — Cmd/Ctrl+K global shortcut to open search from anywhere
  // in the portal. Also Esc closes the search bar.
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        // Only act if chat feature is available (clients > 0)
        if (clients.length === 0) return;
        e.preventDefault();
        setOpen(true);
        setSearchOpen(true);
        setTimeout(() => {
          searchInputRef.current?.focus();
          searchInputRef.current?.select();
        }, 150);
      } else if (e.key === "Escape" && searchOpen) {
        // Close search but keep drawer open
        setSearchOpen(false);
        setSearchTerm("");
        setSearchResults([]);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [clients.length, searchOpen]);

  const runSearch = useCallback(async (term) => {
    const t = (term || "").trim();
    if (!t) { setSearchResults([]); return; }
    setSearching(true);
    try {
      const r = await apiClient.get("/me/chat/search", {
        params: { q: t, client_id: activeClientId, limit: 30 },
      });
      setSearchResults(r.data?.results || []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [activeClientId]);

  // Debounce: trigger after 250 ms of inactivity
  useEffect(() => {
    if (!searchOpen) return;
    const t = setTimeout(() => runSearch(searchTerm), 250);
    return () => clearTimeout(t);
  }, [searchTerm, searchOpen, runSearch]);

  // Jump to a specific message (from search results)
  const jumpToMessage = useCallback(async (result) => {
    setSearchOpen(false);
    setSearchTerm("");
    setSearchResults([]);
    // Switch client + thread, then load and highlight
    if (result.client_id !== activeClientId) {
      setActiveClientId(result.client_id);
    }
    setActiveThreadKey(result.thread_key);
    // Wait a tick for loadMessages effect, then locate and scroll
    setTimeout(() => {
      const el = document.querySelector(`[data-msg-id="${result.id}"]`);
      if (el && scrollRef.current) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        setHighlightMsgId(result.id);
        setTimeout(() => setHighlightMsgId(null), 2500);
      }
    }, 600);
  }, [activeClientId]);

  // Iter36s — Reply-to state (WhatsApp-style quoted reply)
  const [replyTo, setReplyTo] = useState(null); // {id, text, sender_name, media_kind, is_mine}
  const cancelReply = () => setReplyTo(null);

  // Iter36s — Swipe-right detection on message bubbles → quick reply (mobile)
  const touchStateRef = useRef({});
  const startSwipe = (e, msg) => {
    const t = e.touches?.[0];
    if (!t) return;
    touchStateRef.current = {
      msg, startX: t.clientX, startY: t.clientY, lastDx: 0,
    };
  };
  const moveSwipe = (e) => {
    const s = touchStateRef.current;
    if (!s.msg) return;
    const t = e.touches?.[0];
    if (!t) return;
    const dx = t.clientX - s.startX;
    const dy = Math.abs(t.clientY - s.startY);
    // Lock to horizontal swipe (avoid hijacking page scroll)
    if (dx > 0 && dx > dy * 1.5) {
      s.lastDx = Math.min(dx, 100);
    }
  };
  const endSwipe = () => {
    const s = touchStateRef.current;
    touchStateRef.current = {};
    if (s.msg && s.lastDx >= 40) {
      replyToMessage(s.msg);
    }
  };

  const replyToMessage = (m) => {
    setReplyTo({
      id: m.id,
      text: (m.text || "").slice(0, 140) + ((m.text || "").length > 140 ? "…" : ""),
      sender_name: m.sender_name,
      media_kind: m.media_kind || null,
      is_mine: m.sender_id === user?.id,
    });
    // Focus the composer
    setTimeout(() => {
      const ta = document.querySelector('[data-testid="internal-chat-input"]');
      if (ta) ta.focus();
    }, 50);
  };

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

  // Iter36r — Robust auto-scroll: tracks BOTH length AND the id of the
  // last message, so that a full reload that ends with a new message at
  // the bottom (same length, different last id) still scrolls. Also runs
  // an extra delayed scroll to cope with images loading in.
  const lastMsgId = messages.length > 0 ? messages[messages.length - 1].id : null;
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const stick = () => { el.scrollTop = el.scrollHeight; };
    requestAnimationFrame(stick);
    const t = setTimeout(stick, 250);
    return () => clearTimeout(t);
  }, [messages.length, lastMsgId, activeThreadKey]);

  // ---- WebSocket event handler ----
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type === "message") {
      const { client_id, message } = lastEvent;
      const isMine = message?.sender_id === user?.id;
      // Refresh threads (counters) + global unread
      loadUnreadCount();
      loadThreads(client_id);
      // Iter36r — Always play the chat sound on RECEPTION (i.e. message
      // from somebody else), regardless of whether the user is on the
      // active thread or not. The visual toast only fires when the user
      // is on a DIFFERENT thread, since they'd otherwise see the message
      // directly in the conversation.
      if (!isMine) {
        playChatBlip();
      }
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
        // Toast for messages received in a thread the user isn't viewing
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
        reply_to_id: replyTo?.id || null,
      });
      setText("");
      setReplyTo(null);
      // WS will push the message back via the broadcast; locally also reload as safety
      await loadMessages(activeClientId, activeThreadKey);
      // Iter36r — Force scroll to the latest message after the history refresh
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally {
      setSending(false);
    }
  };

  // ---- Iter36l: Voice note recording → Whisper transcription ----
  const startRecording = async () => {
    if (recState !== "idle") return;
    // Iter36q — auto-dismiss the first-use tutorial once the feature is used
    if (showMicIntro) dismissMicIntro();
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
      if (replyTo?.id) form.append("reply_to_id", replyTo.id);
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
      setReplyTo(null);
      await loadMessages(activeClientId, activeThreadKey);
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
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
      {/* Floating FAB — Iter36p: stacked ABOVE the Liluvine virtual
          assistant FAB (which sits at bottom-4 right-4 and expands wide
          on desktop with a "Liluvine — Support Technique" label).
          Stacking vertically guarantees no overlap on any breakpoint. */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-20 right-4 sm:bottom-24 sm:right-6 z-40 inline-flex items-center justify-center h-12 w-12 rounded-full bg-sawali-blue text-white shadow-2xl hover:bg-sawali-blue-light hover:scale-105 transition-all ring-2 ring-white"
          data-testid="internal-chat-fab"
          title="Chat interne (Ctrl+K / ⌘K pour rechercher)"
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
          className="fixed bottom-4 right-4 z-[70] w-[95vw] max-w-2xl h-[600px] max-h-[85vh] rounded-2xl bg-white shadow-2xl ring-1 ring-slate-200 flex overflow-hidden"
          data-testid="internal-chat-drawer"
        >
          {/* Left pane — clients + threads (Iter38d resizable + mobile collapse) */}
          <div
            className={`shrink-0 border-r border-slate-200 bg-slate-50 flex-col ${isCollapsed ? "hidden" : "flex"}`}
            style={{ width: `${leftWidth}px` }}
            data-testid="internal-chat-left-panel"
          >
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
          {/* Iter38d — Resizable drag handle between panels */}
          {!isCollapsed && <DragHandle dragHandlers={dragHandlers} data-testid="internal-chat-resize" />}

          <div className="flex-1 flex flex-col min-w-0">
            <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between bg-white">
              <div className="flex items-center gap-2 min-w-0">
                {/* Iter38d — Mobile-friendly toggle of left panel */}
                <button
                  onClick={toggleCollapsed}
                  data-testid="internal-chat-toggle-left"
                  title={isCollapsed ? "Afficher la liste des conversations" : "Masquer la liste"}
                  className="md:hidden inline-flex items-center justify-center h-8 w-8 rounded-md text-slate-500 hover:text-slate-900 hover:bg-slate-100"
                >
                  {isCollapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
                </button>
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
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => {
                    setSearchOpen((v) => !v);
                    setTimeout(() => searchInputRef.current?.focus(), 100);
                  }}
                  className={`inline-flex items-center justify-center h-8 w-8 rounded-md transition-colors ${searchOpen ? "bg-sawali-blue text-white" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"}`}
                  data-testid="internal-chat-search-toggle"
                  title="Rechercher dans l'historique (Ctrl+K / ⌘K)"
                >
                  <Search className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setOpen(false)}
                  className="text-slate-400 hover:text-slate-700"
                  data-testid="internal-chat-close"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Iter36s — Search bar + results */}
            {searchOpen && (
              <div className="border-b border-slate-200 bg-white px-3 py-2" data-testid="internal-chat-search-panel">
                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
                  <input
                    ref={searchInputRef}
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="Rechercher dans l'historique…"
                    className="w-full rounded-md border border-slate-300 bg-white pl-8 pr-16 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue/30"
                    data-testid="internal-chat-search-input"
                  />
                  {searchTerm ? (
                    <button
                      onClick={() => { setSearchTerm(""); setSearchResults([]); }}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                      data-testid="internal-chat-search-clear"
                      title="Effacer (Échap)"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : (
                    <kbd className="absolute right-2 top-1/2 -translate-y-1/2 hidden sm:inline-flex items-center gap-0.5 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-mono text-slate-500" data-testid="internal-chat-search-kbd-hint">
                      ⌘K
                    </kbd>
                  )}
                </div>
                {searchTerm && (
                  <div className="mt-2 max-h-48 overflow-y-auto -mx-1" data-testid="internal-chat-search-results">
                    {searching ? (
                      <p className="text-center text-xs text-slate-400 py-3">
                        <RefreshCw className="h-3 w-3 inline animate-spin mr-1" /> Recherche…
                      </p>
                    ) : searchResults.length === 0 ? (
                      <p className="text-center text-xs text-slate-400 py-3 italic">
                        Aucun résultat
                      </p>
                    ) : (
                      <ul className="space-y-1 px-1">
                        {searchResults.map((m) => (
                          <li key={m.id}>
                            <button
                              onClick={() => jumpToMessage(m)}
                              className="w-full text-left rounded-md px-2 py-1.5 hover:bg-slate-100 transition-colors"
                              data-testid={`internal-chat-search-result-${m.id}`}
                            >
                              <div className="flex items-center gap-1.5">
                                <span className="text-[10px] font-semibold text-slate-700 truncate">{m.sender_name}</span>
                                <span className="text-[9px] text-slate-400">
                                  {m.thread_key === "general" ? "#général" : "DM"}
                                </span>
                                <span className="ml-auto text-[9px] text-slate-400">{fmtTime(m.created_at)}</span>
                              </div>
                              <p className="text-[11px] text-slate-600 truncate mt-0.5">
                                {m.media_kind === "image" && "📷 "}
                                {highlightTerm(m.text || (m.media_kind === "image" ? "Photo" : ""), searchTerm)}
                              </p>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Iter38d — Expense reminder banner shown above messages */}
            {expenseReminder && expenseReminder.count > 0 && (
              <div
                className={`mx-4 mt-3 mb-1 rounded-lg ring-1 px-3 py-2 text-xs flex items-center justify-between gap-2 ${expenseReminder.late_unjustified > 0 ? "ring-rose-300 bg-rose-50 text-rose-900" : "ring-amber-300 bg-amber-50 text-amber-900"}`}
                data-testid="internal-chat-expense-reminder"
              >
                <div className="min-w-0">
                  <strong>Rappel :</strong> {expenseReminder.count} dépense(s) à justifier (
                  {Number(expenseReminder.total_unjustified || 0).toLocaleString("fr-FR")}{" "}{expenseReminder.currency})
                  {expenseReminder.late_unjustified > 0 && (
                    <span> — <strong>{Number(expenseReminder.late_unjustified).toLocaleString("fr-FR")}</strong> hors délai !</span>
                  )}
                </div>
                <button
                  onClick={() => setExpenseReminder(null)}
                  data-testid="internal-chat-expense-dismiss"
                  className="text-slate-400 hover:text-slate-700 flex-shrink-0"
                  title="Masquer"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            )}

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
                  const isHighlighted = highlightMsgId === m.id;
                  return (
                    <div
                      key={m.id}
                      data-msg-id={m.id}
                      className={`group flex ${mine ? "justify-end" : "justify-start"}`}
                      onTouchStart={(e) => startSwipe(e, m)}
                      onTouchMove={moveSwipe}
                      onTouchEnd={endSwipe}
                    >
                      <div
                        className={`relative max-w-[75%] rounded-2xl px-3 py-2 text-sm shadow-sm transition-all ${
                          mine ? "bg-sawali-blue text-white" : "bg-white ring-1 ring-slate-200 text-slate-800"
                        } ${isHighlighted ? "ring-2 ring-amber-400 ring-offset-2" : ""}`}
                      >
                        {/* Iter36s — Quoted reply preview */}
                        {m.reply_to && (
                          <button
                            type="button"
                            onClick={() => {
                              const el = document.querySelector(`[data-msg-id="${m.reply_to.id}"]`);
                              if (el) {
                                el.scrollIntoView({ behavior: "smooth", block: "center" });
                                setHighlightMsgId(m.reply_to.id);
                                setTimeout(() => setHighlightMsgId(null), 2000);
                              }
                            }}
                            className={`block w-full text-left rounded-md border-l-2 pl-2 pr-1 py-1 mb-1 text-[11px] ${
                              mine
                                ? "border-white/80 bg-white/10 hover:bg-white/15"
                                : "border-sawali-blue bg-sky-50 hover:bg-sky-100 text-slate-700"
                            }`}
                            data-testid={`chat-reply-quote-${m.id}`}
                            title="Aller au message original"
                          >
                            <p className={`text-[10px] font-semibold truncate ${mine ? "text-white/90" : "text-sawali-blue"}`}>
                              {m.reply_to.sender_name || "—"}
                            </p>
                            <p className="truncate opacity-90">
                              {m.reply_to.media_kind === "image" && "📷 "}
                              {m.reply_to.text || (m.reply_to.media_kind === "image" ? "Photo" : "Message")}
                            </p>
                          </button>
                        )}
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
                        {/* Iter36s — Reply button (visible on hover desktop, always-on mobile via swipe) */}
                        <button
                          type="button"
                          onClick={() => replyToMessage(m)}
                          className={`absolute top-1 ${mine ? "-left-7" : "-right-7"} inline-flex items-center justify-center h-6 w-6 rounded-full bg-white shadow ring-1 ring-slate-200 text-slate-500 hover:text-sawali-blue hover:ring-sawali-blue/30 opacity-0 group-hover:opacity-100 transition-opacity`}
                          data-testid={`chat-reply-btn-${m.id}`}
                          title="Répondre à ce message"
                        >
                          <Reply className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Composer */}
            {activeThreadKey && (
              <div className="border-t border-slate-200 bg-white p-3">
                {/* Iter36s — Reply quote preview */}
                {replyTo && (
                  <div className="mb-2 flex items-start gap-2 rounded-lg bg-sky-50 ring-1 ring-sawali-blue/30 border-l-4 border-sawali-blue px-3 py-2 text-xs" data-testid="internal-chat-reply-preview">
                    <Reply className="h-3.5 w-3.5 text-sawali-blue mt-0.5 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[10px] font-semibold text-sawali-blue truncate">
                        Réponse à {replyTo.is_mine ? "vous-même" : replyTo.sender_name}
                      </p>
                      <p className="text-slate-700 truncate">
                        {replyTo.media_kind === "image" && "📷 "}
                        {replyTo.text || (replyTo.media_kind === "image" ? "Photo" : "Message")}
                      </p>
                    </div>
                    <button
                      onClick={cancelReply}
                      className="shrink-0 text-slate-400 hover:text-slate-700"
                      data-testid="internal-chat-reply-cancel"
                      title="Annuler la réponse"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
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
                  <div className="relative shrink-0">
                    <button
                      onClick={recState === "recording" ? stopRecording : startRecording}
                      disabled={sending || uploadingPhoto || recState === "transcribing"}
                      className={`inline-flex items-center justify-center h-10 w-10 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                        recState === "recording"
                          ? "bg-rose-500 text-white hover:bg-rose-600 animate-pulse"
                          : recState === "transcribing"
                            ? "bg-sky-100 text-sky-600"
                            : showMicIntro
                              ? "bg-sawali-blue text-white ring-2 ring-sawali-blue/40 ring-offset-2 animate-pulse"
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
                    {/* Iter36q — One-time onboarding popover */}
                    {showMicIntro && recState === "idle" && (
                      <div
                        className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-[230px] rounded-xl bg-slate-900 text-white p-3 shadow-2xl ring-1 ring-slate-700 animate-in fade-in slide-in-from-bottom-2"
                        data-testid="internal-chat-mic-intro"
                        role="dialog"
                      >
                        <button
                          onClick={dismissMicIntro}
                          className="absolute top-1 right-1 text-slate-400 hover:text-white"
                          aria-label="Fermer"
                          data-testid="internal-chat-mic-intro-close"
                        >
                          <X className="h-3 w-3" />
                        </button>
                        <div className="flex items-center gap-1.5 text-sky-300 text-[10px] font-bold uppercase tracking-wider mb-1">
                          <Sparkles className="h-3 w-3" /> Astuce
                        </div>
                        <p className="text-[11px] leading-snug pr-3">
                          Cliquez sur 🎙️ pour enregistrer une note vocale.
                          La transcription se fait automatiquement par IA :
                          vous pourrez relire et corriger avant l'envoi.
                        </p>
                        <button
                          onClick={dismissMicIntro}
                          className="mt-2 w-full rounded-md bg-sawali-blue hover:bg-sawali-blue-light text-white px-2 py-1 text-[11px] font-semibold"
                          data-testid="internal-chat-mic-intro-ack"
                        >
                          OK, compris
                        </button>
                        {/* Speech-bubble tail */}
                        <span className="absolute -bottom-1.5 left-1/2 -translate-x-1/2 w-3 h-3 bg-slate-900 ring-1 ring-slate-700 rotate-45" />
                      </div>
                    )}
                  </div>
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
                    /* Iter36p — Resizable vertically by user (min = 1 line, max = 3 lines).
                       Crucial on mobile where a long message would otherwise be cramped
                       to a single visible line. resize-y enables the native drag handle. */
                    className="flex-1 resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue/30 min-h-[40px] max-h-[120px]"
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
          className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/85 cursor-zoom-out"
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
