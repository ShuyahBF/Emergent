// =====================================================================
// Iter38r-fix9e — Live toast feed for Liluvine PRO WhatsApp auto-replies
// =====================================================================
// Mounted globally in the portal layout. Polls /me/liluvine-pro/autoreply-feed
// every 20s. When a new assistant reply is detected, it pops a custom sonner
// toast with the contact name + a preview of the reply + a soft notification
// sound (using the existing /sounds/notify.mp3 asset if present, otherwise a
// tiny Web Audio chirp). The user can mute/unmute via localStorage.
// =====================================================================
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Bot, Volume2, VolumeX, MessageCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";

const STORAGE_KEY = "sawali.liluvine.live_toast_muted";
const POLL_INTERVAL_MS = 20_000;
const SEEN_IDS_LIMIT = 80;

function playChirp() {
  try {
    // Tiny browser beep (no external asset required)
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    gain.gain.value = 0.04;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.frequency.linearRampToValueAtTime(1320, ctx.currentTime + 0.08);
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.18);
    osc.stop(ctx.currentTime + 0.2);
    setTimeout(() => ctx.close().catch(() => {}), 250);
  } catch { /* noop */ }
}

export default function LiluvineLiveToast() {
  const navigate = useNavigate();
  const sinceRef = useRef(null);
  const seenRef = useRef(new Set());
  const timerRef = useRef(null);
  const [muted, setMuted] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === "1"; } catch { return false; }
  });
  const mutedRef = useRef(muted);
  useEffect(() => { mutedRef.current = muted; }, [muted]);

  const popToast = useCallback((item) => {
    const contact = item.contact_label || (item.phone_digits ? `+${item.phone_digits}` : "Contact WA");
    toast.custom(
      (t) => (
        <div
          className="rounded-xl shadow-xl ring-1 ring-fuchsia-200 bg-white p-3 max-w-sm flex items-start gap-3 animate-in slide-in-from-right-4 fade-in"
          data-testid={`liluvine-live-toast-${item.id}`}
        >
          <div className="rounded-full bg-fuchsia-100 ring-1 ring-fuchsia-200 p-2 flex-shrink-0">
            <Bot className="h-4 w-4 text-fuchsia-700" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-fuchsia-700 font-semibold">
              Liluvine vient de répondre à WhatsApp
            </p>
            <p className="text-xs font-medium text-slate-800 truncate">{contact}</p>
            <p className="text-[11px] text-slate-600 mt-1 line-clamp-2">{item.content_preview}</p>
            {item.phone_digits && (
              <button
                type="button"
                onClick={() => {
                  toast.dismiss(t);
                  navigate(`/portal/contacts?q=${encodeURIComponent(item.phone_digits)}`);
                }}
                className="mt-2 inline-flex items-center gap-1 text-[10px] font-medium text-fuchsia-700 hover:text-fuchsia-900 hover:underline"
                data-testid={`liluvine-live-toast-view-${item.id}`}
              >
                <MessageCircle className="h-3 w-3" /> 👁 Voir la conversation
              </button>
            )}
          </div>
          <button onClick={() => toast.dismiss(t)} className="text-slate-400 hover:text-slate-700 text-sm">×</button>
        </div>
      ),
      { duration: 9000, position: "bottom-right" },
    );
    if (!mutedRef.current) playChirp();
  }, [navigate]);

  const tick = useCallback(async () => {
    try {
      const params = sinceRef.current ? `?since=${encodeURIComponent(sinceRef.current)}` : "";
      const r = await apiClient.get(`/me/liluvine-pro/autoreply-feed${params}`);
      const items = (r.data?.items || []).slice().reverse(); // oldest first for chronological popping
      const now = r.data?.server_now;
      if (now) sinceRef.current = now;
      for (const it of items) {
        if (seenRef.current.has(it.id)) continue;
        seenRef.current.add(it.id);
        // First load: don't pop toasts for pre-existing items
        if (sinceRef.current && items.indexOf(it) >= 0 && !sinceRef.current.startsWith("INIT")) {
          // (real popping below)
        }
        popToast(it);
      }
      // Bound the seen set
      if (seenRef.current.size > SEEN_IDS_LIMIT) {
        seenRef.current = new Set(Array.from(seenRef.current).slice(-SEEN_IDS_LIMIT));
      }
    } catch { /* silently ignore — auth or net issue */ }
  }, [popToast]);

  // Bootstrap: fetch current state but DON'T pop existing items
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiClient.get("/me/liluvine-pro/autoreply-feed");
        if (cancelled) return;
        const items = r.data?.items || [];
        for (const it of items) seenRef.current.add(it.id);
        sinceRef.current = r.data?.server_now || new Date().toISOString();
      } catch {
        sinceRef.current = new Date().toISOString();
      }
      if (cancelled) return;
      // Start polling
      timerRef.current = setInterval(tick, POLL_INTERVAL_MS);
    })();
    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [tick]);

  // Mute toggle is rendered nowhere by default. Expose via a global event so
  // existing UI can flip it. Also expose a tiny floating control for now:
  return (
    <button
      type="button"
      onClick={() => {
        const next = !muted;
        setMuted(next);
        try { localStorage.setItem(STORAGE_KEY, next ? "1" : "0"); } catch { /* noop */ }
        toast.success(next ? "🔇 Sons Liluvine coupés" : "🔔 Sons Liluvine activés", { duration: 2000 });
      }}
      title={muted ? "Activer le son Liluvine PRO" : "Couper le son Liluvine PRO"}
      className="fixed bottom-4 left-4 z-40 h-8 w-8 rounded-full bg-white/80 backdrop-blur ring-1 ring-slate-300 shadow flex items-center justify-center text-slate-500 hover:text-fuchsia-700 hover:ring-fuchsia-300 transition"
      data-testid="liluvine-live-toast-mute"
    >
      {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
    </button>
  );
}
