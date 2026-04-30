import React, { useEffect, useState } from "react";
import axios from "axios";
import { Info, AlertTriangle, AlertOctagon, X, ArrowRight } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const PALETTE = {
  info: { bg: "bg-sky-500", icon: Info, text: "text-white", ring: "ring-sky-300/50" },
  warning: { bg: "bg-amber-500", icon: AlertTriangle, text: "text-slate-900", ring: "ring-amber-300/50" },
  critical: { bg: "bg-rose-600", icon: AlertOctagon, text: "text-white", ring: "ring-rose-300/50" },
};

// Sticky banner displayed above the marketing nav. Auto-hides if disabled
// or empty. Dismissible per session-key (key is timestamp-based so a NEW
// announcement re-appears even if the previous one was dismissed).
export default function IncidentBanner() {
  const [data, setData] = useState(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await axios.get(`${API}/company-info`);
        if (cancelled) return;
        const b = r.data?.incident_banner;
        if (!b?.enabled || !b?.message) {
          setData(null);
          return;
        }
        setData(b);
        // Per-announcement dismissal — reset whenever the message changes
        const key = `sawali_incident_dismissed:${b.updated_at || b.message}`;
        try {
          if (sessionStorage.getItem(key) === "1") setHidden(true);
          else setHidden(false);
        } catch { /* noop */ }
      } catch { /* noop */ }
    };
    load();
    const t = setInterval(load, 120000); // re-check every 2 min
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!data || hidden) return null;

  const sev = (data.severity || "warning").toLowerCase();
  const palette = PALETTE[sev] || PALETTE.warning;
  const Icon = palette.icon;

  const dismiss = () => {
    setHidden(true);
    try {
      const key = `sawali_incident_dismissed:${data.updated_at || data.message}`;
      sessionStorage.setItem(key, "1");
    } catch { /* noop */ }
  };

  return (
    <div
      className={`relative ${palette.bg} ${palette.text} ring-1 ${palette.ring} print:hidden`}
      data-testid="incident-banner"
      data-severity={sev}
      role="alert"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-2.5 flex items-center gap-3">
        <Icon className="h-4 w-4 flex-shrink-0" />
        <p className="flex-1 text-sm font-medium leading-snug" data-testid="incident-banner-message">
          {data.message}
          {data.link_url && (
            <a
              href={data.link_url}
              target={data.link_url.startsWith("http") ? "_blank" : undefined}
              rel={data.link_url.startsWith("http") ? "noreferrer" : undefined}
              className="ml-2 inline-flex items-center gap-1 underline decoration-2 underline-offset-2 hover:opacity-80 font-semibold"
              data-testid="incident-banner-link"
            >
              {data.link_label || "En savoir plus"} <ArrowRight className="h-3 w-3" />
            </a>
          )}
        </p>
        <button
          onClick={dismiss}
          className="flex-shrink-0 inline-flex items-center justify-center h-6 w-6 rounded-full hover:bg-black/10 transition-colors"
          aria-label="Fermer"
          data-testid="incident-banner-dismiss"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
