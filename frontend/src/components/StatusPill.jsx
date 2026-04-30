import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Discrete trust seal — bottom-left corner of every public page.
// Polls the public status endpoint every 60 s.
export default function StatusPill() {
  const [data, setData] = useState(null);
  const [hidden, setHidden] = useState(() => {
    try { return sessionStorage.getItem("sawali_status_pill_hidden") === "1"; }
    catch { return false; }
  });

  const load = async () => {
    try {
      const r = await axios.get(`${API}/public/status?window_hours=24`);
      setData(r.data?.stats || null);
    } catch { /* silent */ }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  if (hidden || !data) return null;

  const pct = data.overall_uptime_pct ?? 100;
  const tone = pct >= 99 ? "emerald" : pct >= 95 ? "amber" : "rose";
  const label = tone === "emerald" ? "Tous les services" : tone === "amber" ? "Performance dégradée" : "Incident en cours";
  const dotClass = { emerald: "bg-emerald-500", amber: "bg-amber-500", rose: "bg-rose-500" }[tone];
  const ringClass = { emerald: "ring-emerald-400/40", amber: "ring-amber-400/40", rose: "ring-rose-400/40" }[tone];

  return (
    <div
      className="fixed bottom-4 left-4 sm:bottom-6 sm:left-6 z-[55] print:hidden"
      data-testid="status-pill"
    >
      <Link
        to="/uptime"
        className={`group inline-flex items-center gap-2 rounded-full bg-[#0E1F3D]/85 backdrop-blur-md ring-1 ${ringClass} pl-2 pr-3 py-1.5 text-white shadow-lg hover:shadow-xl hover:bg-[#0E1F3D]/95 transition-all`}
        title={`Disponibilité 24h : ${pct}%. Cliquez pour voir le détail.`}
        data-testid="status-pill-link"
      >
        <span className="relative flex h-2.5 w-2.5">
          {tone === "emerald" && (
            <span className={`animate-ping absolute inline-flex h-full w-full rounded-full ${dotClass} opacity-60`} />
          )}
          <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${dotClass}`} />
        </span>
        <span className="text-[11px] font-medium tracking-wide hidden sm:inline">{label}</span>
        <span className="text-[11px] font-mono tabular-nums text-sawali-blue-light">{pct}%</span>
      </Link>
      <button
        onClick={() => {
          setHidden(true);
          try { sessionStorage.setItem("sawali_status_pill_hidden", "1"); } catch { /* noop */ }
        }}
        className="absolute -top-1 -right-1 inline-flex items-center justify-center h-4 w-4 rounded-full bg-slate-700 hover:bg-slate-900 text-white opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-[9px]"
        aria-label="Masquer pour cette session"
        data-testid="status-pill-dismiss"
      >
        ×
      </button>
    </div>
  );
}
