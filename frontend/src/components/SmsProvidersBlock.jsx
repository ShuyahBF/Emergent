// Iter38r-fix9p (P1) — Detailed SMS-by-provider block used by AdminUsage.
// Reads from GET /api/admin/usage/sms-providers and renders per-provider
// cards with: count OK/KO, success rate, avg send latency, estimated cost,
// last failure (timestamp + reason).
import React, { useCallback, useEffect, useState } from "react";
import { Send, AlertTriangle, Clock, Coins, RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";

const PROVIDER_COLORS = {
  ORANGE: "bg-orange-50 ring-orange-200 text-orange-900",
  MOOV: "bg-sky-50 ring-sky-200 text-sky-900",
  TELECEL: "bg-rose-50 ring-rose-200 text-rose-900",
  OVH: "bg-violet-50 ring-violet-200 text-violet-900",
};

export default function SmsProvidersBlock({ days = 30 }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/admin/usage/sms-providers?days=${days}`);
      setItems(r.data?.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="sms-providers-loading">
        <p className="text-xs text-slate-500">Chargement répartition SMS…</p>
      </div>
    );
  }
  if (items.length === 0) {
    return null; // Hide if no SMS data over the period
  }

  return (
    <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="sms-by-provider">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-700 inline-flex items-center gap-1.5">
          <Send className="h-4 w-4 text-indigo-500" /> Répartition SMS par fournisseur ({days} j)
        </h2>
        <button onClick={load} className="text-[11px] text-slate-500 hover:text-slate-900 inline-flex items-center gap-1" data-testid="sms-providers-refresh">
          <RefreshCw className="h-3 w-3" /> Recharger
        </button>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {items.map((p) => {
          const ratio = p.total > 0 ? Math.round((p.sent_ok / p.total) * 100) : 0;
          const tone = PROVIDER_COLORS[p.provider] || "bg-slate-50 ring-slate-200 text-slate-900";
          return (
            <div key={p.provider} className={`rounded-lg ring-1 p-3 ${tone}`} data-testid={`sms-prov-${p.provider}`}>
              <div className="flex items-baseline justify-between">
                <p className="text-[10px] uppercase tracking-wider font-bold">{p.provider}</p>
                <span className={`text-[10px] font-semibold ${ratio >= 90 ? "text-emerald-700" : ratio >= 70 ? "text-amber-700" : "text-rose-700"}`}>
                  {ratio}%
                </span>
              </div>
              <p className="text-2xl font-display font-bold tabular-nums mt-0.5">{p.sent_ok}</p>
              <p className="text-[11px] opacity-75 -mt-0.5">/ {p.total} envoyés</p>
              <div className="mt-2 space-y-1 border-t border-current/10 pt-2">
                {p.avg_latency_human && (
                  <p className="text-[10px] inline-flex items-center gap-1 opacity-80">
                    <Clock className="h-2.5 w-2.5" /> Délai moy. <strong className="font-mono">{p.avg_latency_human}</strong>
                  </p>
                )}
                {p.unit_cost > 0 && (
                  <p className="text-[10px] inline-flex items-center gap-1 opacity-80">
                    <Coins className="h-2.5 w-2.5" /> ~{p.estimated_cost.toLocaleString("fr-FR")} XOF ({p.unit_cost}/SMS)
                  </p>
                )}
                {p.sent_ko > 0 && (
                  <p className="text-[10px] text-rose-700 font-semibold">{p.sent_ko} échec(s)</p>
                )}
                {p.last_failure && (
                  <details className="text-[10px] mt-1">
                    <summary className="cursor-pointer inline-flex items-center gap-1 text-rose-700">
                      <AlertTriangle className="h-2.5 w-2.5" /> Dernier échec
                    </summary>
                    <div className="mt-1 pl-3 space-y-0.5 text-rose-800/90">
                      <p>📅 {p.last_failure.created_at ? new Date(p.last_failure.created_at).toLocaleString("fr-FR") : "—"}</p>
                      {p.last_failure.to && <p>📞 {p.last_failure.to}</p>}
                      {p.last_failure.error_message && (
                        <p className="font-mono break-words bg-white/60 rounded px-1 py-0.5">{p.last_failure.error_message.slice(0, 200)}</p>
                      )}
                    </div>
                  </details>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {items.some((p) => p.unit_cost === 0) && (
        <p className="text-[10px] text-slate-500 mt-3">
          💡 Configurez <code className="bg-slate-100 px-1 rounded">sms_unit_cost_orange</code>, <code className="bg-slate-100 px-1 rounded">sms_unit_cost_moov</code>, etc. dans <code className="bg-slate-100 px-1 rounded">settings.global</code> pour estimer les coûts.
        </p>
      )}
    </div>
  );
}
