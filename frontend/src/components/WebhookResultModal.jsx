import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, XCircle, Copy, X, AlertCircle, Clock } from "lucide-react";
import { apiClient } from "@/lib/api";

// Global bus — any POST/PUT/DELETE response that contains a `webhook_result`
// dispatches a CustomEvent on window. The modal listens and surfaces the
// upstream webhook outcome (status, url, body, error) in a centered popup.
export const SHOW_WEBHOOK_RESULT_EVENT = "sawali:webhook-result";

export const showWebhookResult = (result) => {
  if (!result) return;
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(SHOW_WEBHOOK_RESULT_EVENT, { detail: result }));
};

export default function WebhookResultModal() {
  const [result, setResult] = useState(null);
  // Per-user feature flag: only show webhook return modals when explicitly
  // enabled by the admin on the parent client. Admins/superviseurs are also
  // governed by this flag (they can view the same audit info via api_traces).
  const allowedRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const fetchAllowed = async () => {
      try {
        const r = await apiClient.get("/me/features");
        if (!cancelled) {
          allowedRef.current = !!(r?.data?.features?.webhook_returns);
        }
      } catch {
        if (!cancelled) allowedRef.current = false;
      }
    };
    fetchAllowed();
    // Refresh occasionally to pick up admin toggles without a page reload
    const t = setInterval(fetchAllowed, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  useEffect(() => {
    const handler = (e) => {
      // Hard gate: drop any incoming event when the user isn't allowed to see
      // webhook returns. allowedRef may still be `null` during initial load —
      // in that case we DROP to avoid leaking returns until the flag is known.
      if (allowedRef.current !== true) return;
      setResult(e.detail || null);
    };
    window.addEventListener(SHOW_WEBHOOK_RESULT_EVENT, handler);
    return () => window.removeEventListener(SHOW_WEBHOOK_RESULT_EVENT, handler);
  }, []);

  if (!result) return null;
  if (!result.enabled) {
    // Webhook disabled — nothing to show
    setTimeout(() => setResult(null), 0);
    return null;
  }

  const ok = !!result.ok;
  const tone = ok ? "emerald" : "rose";
  const palette = {
    emerald: { ring: "ring-emerald-400", bg: "bg-emerald-50", text: "text-emerald-900", iconBg: "bg-emerald-500", icon: CheckCircle2, label: "Webhook exécuté avec succès" },
    rose: { ring: "ring-rose-400", bg: "bg-rose-50", text: "text-rose-900", iconBg: "bg-rose-500", icon: XCircle, label: result.error ? "Webhook en erreur" : `Webhook — HTTP ${result.status}` },
  }[tone];
  const Icon = palette.icon;

  const bodyPreview = formatBody(result.body);

  const copyAll = async () => {
    const text = JSON.stringify(result, null, 2);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* noop */
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      data-testid="webhook-result-modal"
      role="dialog"
      aria-modal="true"
      onClick={(e) => { if (e.target === e.currentTarget) setResult(null); }}
    >
      <div className={`w-full max-w-xl rounded-2xl ${palette.bg} ring-2 ${palette.ring} shadow-2xl overflow-hidden`}>
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-slate-200/60">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`h-9 w-9 rounded-lg ${palette.iconBg} flex items-center justify-center flex-shrink-0`}>
              <Icon className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Résultat du webhook</p>
              <h2 className={`text-sm font-display font-bold ${palette.text} truncate`} data-testid="webhook-result-label">
                {palette.label}
              </h2>
            </div>
          </div>
          <button
            onClick={() => setResult(null)}
            className="h-8 w-8 rounded-full hover:bg-slate-200 inline-flex items-center justify-center text-slate-500"
            aria-label="Fermer"
            data-testid="webhook-result-close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5 space-y-4 text-sm">
          {result.url && (
            <Row label="URL appelée">
              <code className="text-[12px] bg-white px-2 py-1 rounded border border-slate-200 break-all">{result.url}</code>
            </Row>
          )}
          {result.status !== null && result.status !== undefined && (
            <Row label="Code HTTP">
              <span className={`inline-flex items-center gap-1.5 text-[12px] font-mono font-semibold px-2 py-1 rounded ${ok ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`} data-testid="webhook-result-status">
                {result.status}
              </span>
            </Row>
          )}
          {result.error && (
            <Row label="Erreur">
              <div className="flex items-start gap-2 bg-white rounded border border-rose-200 px-3 py-2 text-rose-800 text-[12px]">
                <AlertCircle className="h-4 w-4 flex-shrink-0 mt-[1px]" />
                <span>{result.error}</span>
              </div>
            </Row>
          )}
          {bodyPreview !== null && (
            <Row label="Message / réponse du serveur">
              <pre className="bg-white rounded border border-slate-200 px-3 py-2 text-[12px] max-h-48 overflow-auto whitespace-pre-wrap break-words" data-testid="webhook-result-body">
                {bodyPreview}
              </pre>
            </Row>
          )}
          {!result.fired && !result.error && (
            <div className="flex items-center gap-2 text-slate-500 text-[12px]">
              <Clock className="h-3.5 w-3.5" /> Le webhook n'a pas été déclenché (désactivé ou client introuvable).
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 px-5 py-3 bg-slate-50 border-t border-slate-200/60">
          <button
            onClick={copyAll}
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-600 hover:text-slate-900"
            data-testid="webhook-result-copy"
          >
            <Copy className="h-3.5 w-3.5" /> Copier le résultat
          </button>
          <button
            onClick={() => setResult(null)}
            className="inline-flex items-center rounded-lg bg-slate-900 text-white px-4 py-2 text-[12px] font-medium hover:bg-slate-800"
            data-testid="webhook-result-ok"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

const Row = ({ label, children }) => (
  <div>
    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-1">{label}</p>
    {children}
  </div>
);

const formatBody = (body) => {
  if (body === null || body === undefined) return null;
  if (typeof body === "string") return body || "(réponse vide)";
  try { return JSON.stringify(body, null, 2); } catch { return String(body); }
};
