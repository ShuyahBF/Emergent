import React, { useEffect, useState } from "react";
import axios from "axios";
import { Headphones } from "lucide-react";

/*
  Public Support Load Gauge — sticky top banner, centered, displays 7 bars
  styled like a cellular-signal indicator. Color goes green → orange → red as
  the support team load grows. Polls /api/public/support-load every 60 s so
  webhook updates appear within ~1 minute on every public page.
*/
const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

// 7 thresholds → 7 bars. Each "active" bar uses its own color so the gauge
// gradients smoothly from green to red even at low levels (level=1 is green,
// level=4 is orange, level=7 is red).
const BAR_COLORS = [
  "#16a34a", // 1 — green
  "#22c55e", // 2 — green-light
  "#84cc16", // 3 — lime
  "#eab308", // 4 — yellow
  "#f59e0b", // 5 — amber
  "#f97316", // 6 — orange
  "#ef4444", // 7 — red
];

const LEVEL_LABEL = {
  0: "Inactif",
  1: "Très disponible",
  2: "Disponible",
  3: "Charge légère",
  4: "Charge modérée",
  5: "Charge élevée",
  6: "Très occupé",
  7: "Saturé",
};

export default function SupportLoadGauge({ inline = false }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await axios.get(`${BACKEND}/api/public/support-load`, { timeout: 8000 });
        if (!cancelled) setData(r.data);
      } catch { /* silent — keep last known state */ }
    };
    load();
    const t = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!data || !data.enabled) return null;
  const level = Math.max(0, Math.min(7, Number(data.level) || 0));
  const dominantColor = level > 0 ? BAR_COLORS[level - 1] : "#64748b";
  const headline = data.label || LEVEL_LABEL[level] || "—";

  // Inline (navbar-embedded) variant — full-width thin strip, gauge centered.
  // Returns null when disabled so the strip vanishes (no empty space left in
  // the navbar). The gauge sits in a backdrop-blurred pill so it stays legible
  // against any hero background that bleeds through the sticky header.
  if (inline) {
    return (
      <div
        className="w-full flex items-center justify-center px-2 sm:px-4 py-1 border-b border-white/5"
        data-testid="support-load-gauge-strip"
      >
        <div
          className="inline-flex items-center gap-1.5 sm:gap-2 text-[10px] sm:text-[11px] text-slate-100 px-2 py-1 rounded-full ring-1 ring-white/10 bg-white/5 backdrop-blur-sm max-w-full"
          data-testid="support-load-gauge-inline"
          role="status"
          aria-label={`Niveau d'occupation du support : ${level} sur 7 — ${headline}`}
          title={`Support : ${headline} (${level}/7)`}
        >
          <Headphones className="h-3 w-3 opacity-70 shrink-0" />
          <span className="opacity-60 uppercase tracking-[0.18em] text-[9px] hidden md:inline">Support</span>
          <Bars level={level} />
          <span className="font-semibold truncate max-w-[150px] sm:max-w-none" style={{ color: dominantColor }}>
            {headline}
          </span>
          <span className="opacity-50 text-[9px] hidden sm:inline">{level}/7</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="w-full bg-gradient-to-b from-slate-900 to-slate-800 border-b border-slate-700 text-slate-100"
      data-testid="support-load-gauge"
      role="status"
      aria-label={`Niveau d'occupation du support : ${level} sur 7 — ${headline}`}
    >
      <div className="max-w-6xl mx-auto px-4 py-1.5 flex items-center justify-center gap-3 text-[11px]">
        <Headphones className="h-3.5 w-3.5 opacity-70 hidden sm:block" />
        <span className="hidden md:inline-block opacity-70 uppercase tracking-[0.18em] text-[9px]">
          Support technique
        </span>
        <Bars level={level} />
        <span className="font-semibold" style={{ color: dominantColor }}>
          {headline}
        </span>
        <span className="opacity-50 text-[9px] hidden md:inline-block">{level}/7</span>
      </div>
    </div>
  );
}

function Bars({ level }) {
  // 7 bars with growing height (signal-style). Active bars use their own color
  // up to `level`; inactive bars stay neutral grey.
  const heights = [4, 6, 8, 10, 12, 14, 16];
  return (
    <div className="flex items-end gap-[2px] h-4" data-testid="support-load-bars">
      {heights.map((h, i) => {
        const active = i < level;
        return (
          <div
            key={i}
            className="w-[3px] rounded-sm transition-colors"
            style={{
              height: `${h}px`,
              backgroundColor: active ? BAR_COLORS[i] : "rgba(148,163,184,0.25)",
              boxShadow: active ? `0 0 4px ${BAR_COLORS[i]}80` : "none",
            }}
            data-testid={`support-bar-${i + 1}`}
          />
        );
      })}
    </div>
  );
}
