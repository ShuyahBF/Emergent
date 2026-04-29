import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { Eye, Clock, TrendingUp } from "lucide-react";

const fmtDate = (d) => d.toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
const fmtTime = (d) => d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/**
 * Floating glass ticker shown on the public homepage hero.
 * - Live date + time clock (updates every second).
 * - Total visit counter (refreshed every 30s).
 * - Inline 7-day sparkline showing visit trend (refreshed every 60s).
 * Visibility is controlled by `visits_counter_enabled` setting (default true).
 */
export default function HomeStatsTicker() {
  const [now, setNow] = useState(new Date());
  const [count, setCount] = useState(null);
  const [trend, setTrend] = useState([]);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    const fetchCount = () =>
      apiClient.get("/visits/count")
        .then((r) => {
          setEnabled(r.data?.enabled !== false);
          setCount(typeof r.data?.count === "number" ? r.data.count : 0);
        })
        .catch(() => {});
    const fetchTrend = () =>
      apiClient.get("/visits/trend?days=7")
        .then((r) => setTrend(Array.isArray(r.data?.days) ? r.data.days : []))
        .catch(() => {});
    const t0 = setTimeout(() => { fetchCount(); fetchTrend(); }, 800);
    const tCount = setInterval(fetchCount, 30000);
    const tTrend = setInterval(fetchTrend, 60000);
    return () => { clearTimeout(t0); clearInterval(tCount); clearInterval(tTrend); };
  }, []);

  const peak = useMemo(() => trend.reduce((m, d) => Math.max(m, d.count), 0), [trend]);
  const last = trend[trend.length - 1]?.count ?? 0;

  if (!enabled) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-sawali-blue/30 bg-[#0E1F3D]/70 backdrop-blur-md px-3.5 py-1.5 text-[11px] font-mono text-slate-100" data-testid="home-ticker">
        <Clock className="h-3.5 w-3.5 text-sawali-blue-light animate-pulse" />
        <span className="capitalize">{fmtDate(now)}</span>
        <span className="w-px h-3 bg-white/20" />
        <span className="tabular-nums tracking-wider text-white" data-testid="home-clock">{fmtTime(now)}</span>
      </div>
    );
  }

  return (
    <div className="inline-flex flex-wrap items-center gap-2 rounded-full border border-sawali-blue/30 bg-[#0E1F3D]/70 backdrop-blur-md px-1.5 py-1 text-[11px] font-mono shadow-lg shadow-sawali-blue/10" data-testid="home-ticker">
      <span className="inline-flex items-center gap-2 rounded-full bg-white/[0.06] px-3 py-1 text-slate-100">
        <Clock className="h-3.5 w-3.5 text-sawali-blue-light animate-pulse" />
        <span className="capitalize hidden sm:inline">{fmtDate(now)}</span>
        <span className="capitalize sm:hidden">
          {now.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })}
        </span>
        <span className="w-px h-3 bg-white/20" />
        <span className="tabular-nums tracking-wider text-white" data-testid="home-clock">{fmtTime(now)}</span>
      </span>
      <span
        className="inline-flex items-center gap-2 rounded-full bg-sawali-blue/25 ring-1 ring-sawali-blue/60 px-3 py-1 text-sawali-blue-light"
        title="Nombre total de visites"
        data-testid="home-visits-counter"
      >
        <Eye className="h-3.5 w-3.5" />
        <span className="uppercase tracking-[0.2em] text-[10px] hidden sm:inline">visites</span>
        <span className="tabular-nums font-semibold text-white" data-testid="home-visits-value">
          {count === null ? "…" : count.toLocaleString("fr-FR")}
        </span>
        {trend.length >= 2 && (
          <span
            className="hidden sm:inline-flex items-center gap-1 pl-1 ml-1 border-l border-sawali-blue/40"
            title={`Tendance 7 jours · pic ${peak} · aujourd'hui ${last}`}
            data-testid="home-visits-spark"
          >
            <TrendingUp className="h-3 w-3 opacity-70" />
            <Sparkline data={trend} />
          </span>
        )}
      </span>
    </div>
  );
}

// ====================================================================
// Sparkline — minimal inline SVG, no extra dependency
// ====================================================================
function Sparkline({ data, width = 64, height = 18 }) {
  if (!data || data.length < 2) return null;
  const counts = data.map((d) => d.count);
  const max = Math.max(...counts, 1);
  const min = Math.min(...counts);
  const span = Math.max(max - min, 1);
  const stepX = width / (data.length - 1);
  const points = counts.map((c, i) => [
    +(i * stepX).toFixed(2),
    +(height - ((c - min) / span) * (height - 4) - 2).toFixed(2),
  ]);
  const pathLine = points.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`)).join(" ");
  const pathArea = `${pathLine} L${width},${height} L0,${height} Z`;
  const last = points[points.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs>
        <linearGradient id="sawSpark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1E90FF" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#1E90FF" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={pathArea} fill="url(#sawSpark)" />
      <path d={pathLine} fill="none" stroke="#7DC4FF" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="2" fill="#fff" stroke="#1E90FF" strokeWidth="1" />
    </svg>
  );
}
