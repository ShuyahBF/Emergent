/*
 * Iter36l — Public "team online X/Y" badge (social proof).
 *
 * Polls /api/public/team-presence every 30s. Compact pill with a green
 * pulsing dot when at least one staff member is connected, otherwise a
 * neutral "Équipe joignable 24/7" fallback.
 *
 * Variants:
 *   - tone="light"  → dark text on light background (footer, contact page)
 *   - tone="dark"   → light text on dark background (hero overlay)
 *   - compact={true} → smaller for nav bars
 */
import React, { useEffect, useState } from "react";
import axios from "axios";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

export default function TeamPresenceBadge({ tone = "light", compact = false, className = "" }) {
  const [data, setData] = useState({ online: 0, total: 0 });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchPresence = async () => {
      try {
        const r = await axios.get(`${BACKEND}/api/public/team-presence`, { timeout: 8000 });
        if (!cancelled) {
          setData(r.data || { online: 0, total: 0 });
          setLoaded(true);
        }
      } catch {
        if (!cancelled) setLoaded(true);
      }
    };
    fetchPresence();
    const t = setInterval(fetchPresence, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!loaded || data.total === 0) return null;

  const isOnline = data.online > 0;
  const isDark = tone === "dark";

  const baseColor = isOnline
    ? (isDark
        ? "bg-emerald-500/15 text-emerald-100 ring-emerald-400/40"
        : "bg-emerald-50 text-emerald-700 ring-emerald-200")
    : (isDark
        ? "bg-white/5 text-slate-200 ring-white/10"
        : "bg-slate-50 text-slate-600 ring-slate-200");

  const dotColor = isOnline ? "bg-emerald-500" : "bg-slate-400";

  const sizing = compact
    ? "text-[10px] px-2 py-0.5"
    : "text-xs px-2.5 py-1";

  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-full ring-1 font-medium ${baseColor} ${sizing} ${className}`}
      data-testid="team-presence-badge"
      title={isOnline
        ? `${data.online} membre(s) de l'équipe SAWALI actuellement en ligne sur ${data.total}`
        : "L'équipe SAWALI est joignable — réponse sous 24h"}
    >
      <span className="relative inline-flex shrink-0">
        <span className={`inline-block ${compact ? "h-1.5 w-1.5" : "h-2 w-2"} rounded-full ${dotColor}`} />
        {isOnline && (
          <span className={`absolute inline-flex ${compact ? "h-1.5 w-1.5" : "h-2 w-2"} rounded-full ${dotColor} opacity-60 animate-ping`} />
        )}
      </span>
      <span className="whitespace-nowrap">
        {isOnline ? (
          <>
            Équipe en ligne <span className="font-bold tabular-nums" data-testid="team-presence-count">{data.online}</span>
            <span className="opacity-60">/{data.total}</span>
          </>
        ) : (
          "Équipe joignable 24/7"
        )}
      </span>
    </div>
  );
}
