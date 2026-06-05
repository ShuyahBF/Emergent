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

// Iter40-ui-flags — Lighten/darken a #RRGGBB color by an amount in [-1, 1].
// Used to derive primary-light and primary-dark from a single admin-chosen
// color so the Tailwind palette stays consistent.
function shiftColor(hex, amount) {
  if (!hex || !/^#[0-9A-Fa-f]{6}$/.test(hex)) return null;
  const num = parseInt(hex.slice(1), 16);
  let r = (num >> 16) & 0xff;
  let g = (num >> 8) & 0xff;
  let b = num & 0xff;
  const adj = (c) => {
    if (amount >= 0) return Math.round(c + (255 - c) * amount);
    return Math.round(c * (1 + amount));
  };
  r = Math.max(0, Math.min(255, adj(r)));
  g = Math.max(0, Math.min(255, adj(g)));
  b = Math.max(0, Math.min(255, adj(b)));
  return "#" + ((r << 16) | (g << 8) | b).toString(16).padStart(6, "0");
}

function applyBranding(flags) {
  if (!flags) return;
  // Document title
  if (flags.public_brand_name && typeof document !== "undefined") {
    document.title = flags.public_brand_name;
  }
  // Primary brand color → CSS variable on :root (+ light/dark derivatives so
  // every Tailwind class like bg-sawali-blue, bg-brand, bg-sawali-blue-light
  // automatically picks up the new color).
  if (flags.public_brand_color && typeof document !== "undefined") {
    const root = document.documentElement;
    const primary = flags.public_brand_color;
    root.style.setProperty("--brand-primary", primary);
    const light = shiftColor(primary, 0.12);
    const dark = shiftColor(primary, -0.18);
    if (light) root.style.setProperty("--brand-primary-light", light);
    if (dark) root.style.setProperty("--brand-primary-dark", dark);
  }
}

// Iter40-ui-flags-tailwind — Exported so AdminSettings can preview changes
// locally and instantly (without waiting for a database round-trip).
export const applyBrandingLocal = applyBranding;

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
