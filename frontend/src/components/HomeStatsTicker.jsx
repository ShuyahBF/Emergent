import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Eye, Clock } from "lucide-react";

const fmtDate = (d) => d.toLocaleDateString("fr-FR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
const fmtTime = (d) => d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/**
 * Floating glass ticker shown on the public homepage hero.
 * - Live date + time clock (updates every second).
 * - Total visit counter (refreshed every 30s, also when the page mounts).
 * Visibility is controlled by `visits_counter_enabled` setting (default true).
 */
export default function HomeStatsTicker() {
  const [now, setNow] = useState(new Date());
  const [count, setCount] = useState(null);
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
    // Slight delay so /track has time to record this visit first
    const t0 = setTimeout(fetchCount, 800);
    const t1 = setInterval(fetchCount, 30000);
    return () => { clearTimeout(t0); clearInterval(t1); };
  }, []);

  if (!enabled) {
    // Still render the live clock alone — keeps the modern feel even without the counter
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 backdrop-blur-md px-3.5 py-1.5 text-[11px] font-mono text-slate-200" data-testid="home-ticker">
        <Clock className="h-3.5 w-3.5 text-sawali-blue-light" />
        <span className="capitalize">{fmtDate(now)}</span>
        <span className="w-px h-3 bg-white/20" />
        <span className="tabular-nums tracking-wider text-white">{fmtTime(now)}</span>
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
      </span>
    </div>
  );
}
