import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { AlertTriangle, Clock, X } from "lucide-react";

/**
 * Iter35h — DemoBanner.
 * Persistent strip at the very top of /portal that shows the demo account's
 * expiration countdown and a compact gauge of every quota's usage. Hides
 * itself for non-demo users (the API returns is_demo=false). Refresh
 * every 60s so the user sees the live counters tick as they consume.
 */
const QUOTA_LABELS = {
  whatsapp_sends: "WhatsApp",
  sms_sends: "SMS",
  ai_generations: "IA",
  transcriptions: "Transcription",
  directory_contacts: "Contacts",
  payments: "Paiements",
  attachments_bytes: "Stockage",
};

const formatBytes = (n) => {
  if (n == null) return "";
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} Ko`;
  return `${(n / 1024 / 1024).toFixed(1)} Mo`;
};

export default function DemoBanner() {
  const [data, setData] = useState(null);
  const [collapsed, setCollapsed] = useState(false);

  const load = async () => {
    try {
      const r = await apiClient.get("/me/demo/status");
      setData(r.data || null);
    } catch (e) {
      setData(null);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000); // 1 min
    return () => clearInterval(id);
  }, []);

  if (!data || !data.is_demo) return null;

  const daysLeft = data.days_left;
  const expiringSoon = typeof daysLeft === "number" && daysLeft <= 3;
  const quotas = data.quotas || {};
  const accent = expiringSoon ? "bg-rose-100 border-rose-400 text-rose-900" : "bg-amber-100 border-amber-400 text-amber-900";

  return (
    <div className={`border-b-2 ${accent}`} data-testid="demo-banner">
      <div className="px-4 py-2 flex items-center gap-3 flex-wrap">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span className="font-semibold text-sm">Compte de démonstration</span>
        {typeof daysLeft === "number" && (
          <span className="inline-flex items-center gap-1 text-xs font-semibold" data-testid="demo-days-left">
            <Clock className="h-3 w-3" />
            {daysLeft === 0 ? "Expire aujourd'hui" : daysLeft === 1 ? "Expire demain" : `Expire dans ${daysLeft} jours`}
          </span>
        )}
        <div className="flex-1 min-w-[200px] flex items-center gap-3 flex-wrap text-xs">
          {Object.entries(quotas).map(([k, v]) => {
            if (!v || v.limit == null) return null;
            const isStorage = k === "attachments_bytes";
            const usedLabel = isStorage ? formatBytes(v.used) : `${v.used}`;
            const limitLabel = isStorage ? formatBytes(v.limit) : `${v.limit}`;
            const percent = v.limit ? Math.min(100, Math.round((v.used / v.limit) * 100)) : 0;
            const reached = v.limit > 0 && v.used >= v.limit;
            return (
              <span
                key={k}
                className={`inline-flex items-center gap-1 ${reached ? "text-rose-700 font-bold" : "text-slate-700"}`}
                data-testid={`demo-quota-${k}`}
                title={`${QUOTA_LABELS[k] || k} : ${usedLabel}/${limitLabel} (${percent}%)`}
              >
                <span className="font-semibold">{QUOTA_LABELS[k] || k}</span>
                <span className="opacity-80">{usedLabel}/{limitLabel}</span>
              </span>
            );
          })}
        </div>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-xs underline opacity-70 hover:opacity-100"
          data-testid="demo-banner-toggle"
        >
          {collapsed ? "Afficher les détails" : "Masquer"}
        </button>
      </div>
      {!collapsed && (
        <div className="px-4 pb-2 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2" data-testid="demo-banner-gauges">
          {Object.entries(quotas).map(([k, v]) => {
            if (!v || v.limit == null) return null;
            const isStorage = k === "attachments_bytes";
            const percent = v.limit ? Math.min(100, Math.round((v.used / v.limit) * 100)) : 0;
            const bar = percent >= 100 ? "bg-rose-600" : percent >= 75 ? "bg-amber-500" : "bg-emerald-500";
            return (
              <div key={k} className="bg-white/70 rounded px-2 py-1" data-testid={`demo-gauge-${k}`}>
                <div className="text-[10px] font-semibold text-slate-700">{QUOTA_LABELS[k] || k}</div>
                <div className="h-1.5 rounded bg-slate-200 overflow-hidden">
                  <div className={`h-full ${bar}`} style={{ width: `${percent}%` }} />
                </div>
                <div className="text-[10px] text-slate-600 mt-0.5">
                  {isStorage ? `${formatBytes(v.used)} / ${formatBytes(v.limit)}` : `${v.used} / ${v.limit}`}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
