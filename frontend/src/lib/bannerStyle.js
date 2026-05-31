// Iter38r-fix9z5 — Compute the CSS that controls how an ad banner is sized
// on the page. Supports four display modes set by the admin in
// `AdminAdBanners.jsx > BannerSizingBlock`:
//
//   • "auto"        — current default. Banner spans 100% width with a
//                     responsive 64px / 80px height (mobile / desktop).
//   • "ratio"       — width_pct of the viewport × aspect ratio (e.g. 16:9).
//                     Height auto-computed from CSS aspect-ratio.
//   • "percentage"  — width_pct of the viewport with a fixed height_px.
//   • "fixed"       — exact width_px × height_px (centered in the page).
//
// Returns:
//   { outer, inner }
// where `outer` styles the wrapping container (relative banner shell) and
// `inner` styles the actual <img>/<video> element so the media respects
// the chosen object-fit.

const VALID_RATIO = /^(\d{1,4}):(\d{1,4})$/;

function parseRatio(ratio) {
  if (!ratio || typeof ratio !== "string") return null;
  const m = ratio.trim().match(VALID_RATIO);
  if (!m) return null;
  const w = parseInt(m[1], 10);
  const h = parseInt(m[2], 10);
  if (!w || !h) return null;
  return `${w} / ${h}`;
}

export function computeBannerStyles(banner) {
  const mode = banner?.display_mode || "auto";
  const widthPct = clamp(banner?.width_pct ?? 100, 10, 100);
  const heightPx = clamp(banner?.height_px ?? 80, 20, 1200);
  const widthPx = clamp(banner?.width_px ?? 728, 50, 2400);
  const objectFit = ["cover", "contain", "fill"].includes(banner?.object_fit)
    ? banner.object_fit
    : "cover";

  // Inner media style — common across modes
  const inner = {
    width: "100%",
    height: "100%",
    objectFit,
    display: "block",
  };

  if (mode === "ratio") {
    const ratioCss = parseRatio(banner?.aspect_ratio) || "16 / 9";
    return {
      outer: {
        width: `${widthPct}%`,
        aspectRatio: ratioCss,
        marginLeft: "auto",
        marginRight: "auto",
      },
      inner,
      mode,
    };
  }

  if (mode === "percentage") {
    return {
      outer: {
        width: `${widthPct}%`,
        height: `${heightPx}px`,
        marginLeft: "auto",
        marginRight: "auto",
      },
      inner,
      mode,
    };
  }

  if (mode === "fixed") {
    return {
      outer: {
        width: `${widthPx}px`,
        maxWidth: "100%",
        height: `${heightPx}px`,
        marginLeft: "auto",
        marginRight: "auto",
      },
      inner,
      mode,
    };
  }

  // "auto" — fall back to responsive default handled by Tailwind classes
  return {
    outer: {},
    inner: { ...inner, height: undefined, width: undefined },
    mode: "auto",
  };
}

function clamp(n, lo, hi) {
  const x = Number(n);
  if (Number.isNaN(x)) return lo;
  return Math.min(Math.max(x, lo), hi);
}
