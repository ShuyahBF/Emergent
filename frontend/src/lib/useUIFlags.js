// Iter40-ui-flags — Shared hook + applier for public UI flags.
//
// What is this for?
//   The backend exposes a tiny anonymous endpoint /api/public/ui-flags
//   that returns display toggles AND public branding fields (brand name,
//   primary color, logo URL, hero tagline). Components that mount BEFORE
//   authentication (App root, GlobalRouteLoader, MarketingLayout, …) read
//   this hook to apply customization without touching the codebase per
//   reseller / white-label deployment.
//
// Side effects performed on the document:
//   - Sets `document.title` from public_brand_name (when present)
//   - Writes a CSS custom property `--brand-primary` from public_brand_color
//     so any stylesheet can reference `var(--brand-primary, #1E90FF)`
//
// Reactivity:
//   - Fetches once at mount
//   - Listens to the global CustomEvent `ui-flags-updated` so Admin
//     Settings changes propagate without a full reload
//   - Caches the JSON payload in localStorage to avoid a flash at next boot
import { useEffect, useState } from "react";

const CACHE_KEY = "ui_flags_cache_v1";

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function writeCache(data) {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(data)); } catch { /* ignore */ }
}

function applyBranding(flags) {
  if (!flags) return;
  // Document title
  if (flags.public_brand_name && typeof document !== "undefined") {
    document.title = flags.public_brand_name;
  }
  // Primary brand color → CSS variable on :root
  if (flags.public_brand_color && typeof document !== "undefined") {
    document.documentElement.style.setProperty("--brand-primary", flags.public_brand_color);
  }
}

export function useUIFlags() {
  const [flags, setFlags] = useState(() => readCache());
  const apiBase = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

  useEffect(() => {
    let cancelled = false;
    const fetchFlags = () => {
      fetch(`${apiBase}/api/public/ui-flags`)
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (cancelled || !data) return;
          setFlags(data);
          writeCache(data);
          applyBranding(data);
        })
        .catch(() => {});
    };
    fetchFlags();
    const onChange = () => fetchFlags();
    window.addEventListener("ui-flags-updated", onChange);
    return () => {
      cancelled = true;
      window.removeEventListener("ui-flags-updated", onChange);
    };
  }, [apiBase]);

  // Always re-apply branding on mount (in case the cache was used)
  useEffect(() => { applyBranding(flags); }, [flags]);

  return flags || {};
}
