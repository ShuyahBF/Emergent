// S025 — Download approval gate.
// Wraps a download flow with a server-side approval workflow:
//   1. Calls POST /me/download-requests to create a pending approval.
//   2. Shows a fullscreen circular progress gauge with the admin-configurable
//      pending message ("En attente d'approbation pour le téléchargement...").
//   3. Polls /me/download-requests/{token} every 2 s.
//   4. On status=approved → triggers the actual download (open in new tab).
//   5. On status=denied|expired|cancelled → shows the "Désolé, l'opération
//      n'a pas été confirmée" toast and closes the gauge.
//
// Admin/Superviseur bypass the gate (backend returns direct=true).
import React, { useState, useEffect, useRef, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { ShieldCheck, X, Loader2 } from "lucide-react";

const POLL_INTERVAL_MS = 2000;

export function useDownloadGate() {
  const [state, setState] = useState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" });
  const pollTimer = useRef(null);
  const cancelledRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
  }, []);

  const close = useCallback(async () => {
    stopPolling();
    if (state.token && state.status === "pending") {
      cancelledRef.current = true;
      try { await apiClient.post(`/me/download-requests/${state.token}/cancel`); } catch { /* noop */ }
    }
    setState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" });
  }, [state.token, state.status, stopPolling]);

  const triggerActualDownload = (url, label) => {
    // Open in a new tab. The user has consented + the server has approved.
    try {
      const a = document.createElement("a");
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.download = label || "";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  };

  const requestDownload = useCallback(async ({ url, label }) => {
    cancelledRef.current = false;
    try {
      const r = await apiClient.post("/me/download-requests", { resource_url: url, resource_label: label });
      const data = r.data || {};
      if (data.direct) {
        triggerActualDownload(data.approved_url || url, label);
        return;
      }
      if (!data.token) {
        toast.error("Configuration d'approbation incomplète.");
        return;
      }
      // P3 (2026-02) — Admin can disable the central waiting gauge. When
      // off, we just show a discreet toast and silently poll in the
      // background. The download triggers automatically once approved.
      const gaugeEnabled = data.gauge_enabled !== false; // default ON for back-compat
      if (!gaugeEnabled) {
        toast.info(
          (data.pending_message || "En attente d'approbation pour le téléchargement…") +
          " (Vous serez notifié dès l'approbation)",
          { duration: 6000 }
        );
        setState({ open: false, token: data.token, status: "pending", label, url, pendingMessage: "", gaugeEnabled: false });
      } else {
        setState({ open: true, token: data.token, status: "pending", label, url, pendingMessage: data.pending_message || "En attente d'approbation pour le téléchargement...", gaugeEnabled: true });
      }
      pollTimer.current = setInterval(async () => {
        if (cancelledRef.current) return;
        try {
          const p = await apiClient.get(`/me/download-requests/${data.token}`);
          const status = p.data?.status;
          if (status && status !== "pending") {
            stopPolling();
            if (status === "approved") {
              triggerActualDownload(url, label);
              if (!gaugeEnabled) {
                toast.success(`✅ Téléchargement de « ${label} » approuvé et démarré.`);
                setState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" });
              } else {
                setState((s) => ({ ...s, status: "approved" }));
                setTimeout(() => setState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" }), 1500);
              }
            } else {
              const msg = status === "denied" ? "Désolé, l'opération n'a pas été confirmée." :
                          status === "expired" ? "La demande a expiré (24 h sans réponse)." :
                          "Demande annulée.";
              if (!gaugeEnabled) {
                toast.warning(`« ${label} » — ${msg}`);
                setState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" });
              } else {
                setState((s) => ({ ...s, status }));
                toast.warning(msg);
                setTimeout(() => setState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" }), 3000);
              }
            }
          }
        } catch (e) {
          if (e?.response?.status === 404) {
            stopPolling();
            setState({ open: false, token: null, status: null, label: "", url: "", pendingMessage: "" });
          }
        }
      }, POLL_INTERVAL_MS);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lors de la demande d'approbation");
    }
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  return { requestDownload, close, state };
}

export default function DownloadGate({ state, onClose }) {
  if (!state.open) return null;
  // Indeterminate visual progress — spins continuously while pending
  return (
    <div
      className="fixed inset-0 z-[9997] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      data-testid="download-approval-modal"
    >
      <div className="bg-white rounded-2xl shadow-2xl ring-1 ring-slate-200 max-w-md w-full p-6 text-center">
        <div className="relative mx-auto" style={{ width: 96, height: 96 }}>
          <svg width="96" height="96" viewBox="0 0 96 96" data-testid="download-gauge-svg">
            <circle cx="48" cy="48" r="40" stroke="#E2E8F0" strokeWidth="6" fill="none" />
            <circle
              cx="48" cy="48" r="40"
              stroke="url(#g-dl-loader)"
              strokeWidth="6"
              strokeLinecap="round"
              fill="none"
              strokeDasharray="60 200"
              style={{
                transform: "rotate(-90deg)",
                transformOrigin: "48px 48px",
                animation: state.status === "pending" ? "spin 1.4s linear infinite" : "none",
              }}
            />
            <defs>
              <linearGradient id="g-dl-loader" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#1E90FF" />
                <stop offset="100%" stopColor="#c026d3" />
              </linearGradient>
            </defs>
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <ShieldCheck className="h-8 w-8 text-sawali-blue" />
          </div>
        </div>
        <h3 className="text-lg font-display font-bold text-slate-900 mt-4" data-testid="download-gauge-title">
          {state.status === "approved" ? "✅ Approuvé !"
            : state.status === "denied" ? "❌ Refusé"
            : state.status === "expired" ? "⏳ Expiré"
            : "Demande en cours"}
        </h3>
        <p className="text-sm text-slate-600 mt-2" data-testid="download-gauge-message">
          {state.status === "pending" ? state.pendingMessage : ""}
          {state.status === "approved" ? "Téléchargement démarré…" : ""}
          {state.status === "denied" ? "Désolé, l'opération n'a pas été confirmée." : ""}
          {state.status === "expired" ? "La demande n'a pas reçu de réponse dans le délai imparti." : ""}
        </p>
        <p className="text-[11px] text-slate-400 mt-2 italic">Document demandé : « {state.label} »</p>
        {state.status === "pending" && (
          <button
            onClick={onClose}
            className="mt-4 inline-flex items-center gap-1 px-4 py-2 text-xs rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700"
            data-testid="download-gauge-cancel"
          >
            <X className="h-3.5 w-3.5" /> Annuler la demande
          </button>
        )}
      </div>
      <style>{`@keyframes spin { from { transform: rotate(-90deg); } to { transform: rotate(270deg); } }`}</style>
    </div>
  );
}
