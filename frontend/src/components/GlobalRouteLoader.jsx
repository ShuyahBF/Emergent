// S-iter39d (fix #7) — Animated circular loader shown briefly between
// page navigations. Improves perceived performance on slow connections
// by reassuring the user that the server has acknowledged the request.
// Mounts at the App root; subscribes to React Router location changes
// and the global axios interceptor (via apiClient.interceptors) so any
// in-flight backend call extends the visible window.
//
// Iter40-route-loader (S051) — Admin-toggleable via /api/public/ui-flags.
// When `global_route_loader_enabled === false`, the component disables itself
// completely (no fetches, no interceptors, no DOM). The flag is fetched once
// at mount AND refreshed when AdminSettings dispatches a 'ui-flags-updated'
// CustomEvent so the toggle takes effect immediately without a reload.
import React, { useEffect, useState, useRef } from "react";
import { useLocation } from "react-router-dom";
import { apiClient } from "@/lib/api";

const MIN_VISIBLE_MS = 350;     // Don't flicker for sub-100ms transitions
const NAV_GRACE_MS = 220;       // How long to show after a route change
const REQUEST_THROTTLE_MS = 80;  // Coalesce bursts of requests
const FLAG_CACHE_KEY = "ui_flag_global_route_loader_enabled";

export default function GlobalRouteLoader() {
  const location = useLocation();
  const [visible, setVisible] = useState(false);
  const [progress, setProgress] = useState(0);
  // Iter40-route-loader — gate. Default true (cached) so the loader appears
  // for first-paint UX while we fetch the real flag.
  const [enabled, setEnabled] = useState(() => {
    try {
      const v = localStorage.getItem(FLAG_CACHE_KEY);
      return v === null ? true : v === "1";
    } catch { return true; }
  });
  const pendingCount = useRef(0);
  const showTsRef = useRef(0);
  const hideTimerRef = useRef(null);
  const progressTimerRef = useRef(null);

  // Iter40-route-loader — Fetch the public toggle once at mount and listen to
  // 'ui-flags-updated' so AdminSettings changes apply immediately.
  useEffect(() => {
    const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
    const fetchFlag = () => {
      fetch(`${apiBase}/api/public/ui-flags`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data) return;
          const v = data.global_route_loader_enabled !== false;
          setEnabled(v);
          try { localStorage.setItem(FLAG_CACHE_KEY, v ? "1" : "0"); } catch { /* ignore */ }
        })
        .catch(() => {});
    };
    fetchFlag();
    const onChange = () => fetchFlag();
    window.addEventListener("ui-flags-updated", onChange);
    return () => window.removeEventListener("ui-flags-updated", onChange);
  }, []);

  const clearHide = () => { if (hideTimerRef.current) { clearTimeout(hideTimerRef.current); hideTimerRef.current = null; } };

  const hide = () => {
    const elapsed = Date.now() - showTsRef.current;
    const wait = Math.max(0, MIN_VISIBLE_MS - elapsed);
    clearHide();
    hideTimerRef.current = setTimeout(() => {
      setVisible(false);
      setProgress(0);
      if (progressTimerRef.current) { clearInterval(progressTimerRef.current); progressTimerRef.current = null; }
    }, wait);
  };

  const show = () => {
    clearHide();
    if (!visible) {
      showTsRef.current = Date.now();
      setVisible(true);
      setProgress(15);
      if (progressTimerRef.current) clearInterval(progressTimerRef.current);
      // Asymptotic progress curve toward 90% (never completes until done)
      progressTimerRef.current = setInterval(() => {
        setProgress((p) => (p < 90 ? p + Math.max(1, Math.round((90 - p) * 0.05)) : p));
      }, 120);
    }
  };

  // Route change → flash the loader
  useEffect(() => {
    if (!enabled) return;
    show();
    const t = setTimeout(() => {
      if (pendingCount.current <= 0) hide();
    }, NAV_GRACE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, enabled]);

  // Wire axios interceptors so in-flight API calls extend the loader.
  useEffect(() => {
    if (!enabled) return undefined;
    let bumpTimer = null;
    const onStart = () => {
      pendingCount.current += 1;
      if (bumpTimer) clearTimeout(bumpTimer);
      bumpTimer = setTimeout(() => show(), REQUEST_THROTTLE_MS);
    };
    const onEnd = () => {
      pendingCount.current = Math.max(0, pendingCount.current - 1);
      if (pendingCount.current === 0) {
        setProgress(100);
        hide();
      }
    };

    const reqId = apiClient.interceptors.request.use(
      (cfg) => { onStart(); return cfg; },
      (err) => { onEnd(); return Promise.reject(err); },
    );
    const resId = apiClient.interceptors.response.use(
      (res) => { onEnd(); return res; },
      (err) => { onEnd(); return Promise.reject(err); },
    );
    return () => {
      apiClient.interceptors.request.eject(reqId);
      apiClient.interceptors.response.eject(resId);
      if (bumpTimer) clearTimeout(bumpTimer);
      clearHide();
      if (progressTimerRef.current) clearInterval(progressTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // Iter40-route-loader — When disabled or nothing is showing, render nothing.
  if (!enabled || !visible) return null;

  const R = 18;
  const CIRC = 2 * Math.PI * R;
  const offset = CIRC * (1 - progress / 100);

  return (
    <div
      className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[9998] pointer-events-none"
      aria-live="polite"
      aria-busy="true"
      data-testid="global-route-loader"
    >
      <div className="bg-white/95 backdrop-blur rounded-full shadow-2xl ring-1 ring-slate-200 p-3 flex items-center justify-center" style={{ width: 64, height: 64 }}>
        <svg width="44" height="44" viewBox="0 0 44 44">
          <circle cx="22" cy="22" r={R} stroke="#E2E8F0" strokeWidth="4" fill="none" />
          <circle
            cx="22" cy="22" r={R}
            stroke="url(#g-route-loader)"
            strokeWidth="4"
            strokeLinecap="round"
            fill="none"
            strokeDasharray={CIRC}
            strokeDashoffset={offset}
            style={{ transform: "rotate(-90deg)", transformOrigin: "22px 22px", transition: "stroke-dashoffset 200ms ease-out" }}
          />
          <defs>
            <linearGradient id="g-route-loader" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#1E90FF" />
              <stop offset="100%" stopColor="#c026d3" />
            </linearGradient>
          </defs>
        </svg>
      </div>
      <p className="text-[10px] text-center text-slate-600 mt-2 font-medium tabular-nums">{Math.min(100, Math.round(progress))}%</p>
    </div>
  );
}
