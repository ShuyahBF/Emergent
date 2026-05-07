import React, { useEffect, useState } from "react";
import axios from "axios";
import { apiClient } from "@/lib/api";
import { MessageCircle, X, AlertTriangle } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

/**
 * Floating Virtual Assistant button.
 * - Opens an external popup chatbot (e.g. JotForm AI agent) on click.
 * - Polls /api/public/support-load every 60s — when the support load is
 *   above the configured threshold, the button switches to "alert" style
 *   (color, label) and shows a tooltip suggesting the chat as the
 *   preferred channel during high-load periods.
 */
export default function VirtualAssistant() {
  const [config, setConfig] = useState(null);
  const [dismissed, setDismissed] = useState(false);
  const [alert, setAlert] = useState(null); // {label, message, level}
  const [tooltipOpen, setTooltipOpen] = useState(false);

  useEffect(() => {
    apiClient.get("/company-info").then((r) => {
      const a = r.data?.assistant;
      if (a && a.enabled && a.url) setConfig(a);
    }).catch(() => {});
    if (sessionStorage.getItem("sawali_assistant_dismissed") === "1") {
      setDismissed(true);
    }
    // Poll the gauge to know when to switch into "alert" mode
    let cancelled = false;
    const fetchLoad = async () => {
      try {
        const r = await axios.get(`${BACKEND}/api/public/support-load`, { timeout: 8000 });
        if (cancelled) return;
        const lil = r.data?.liluvine || {};
        if (lil.alert_active) {
          setAlert({
            label: lil.label || "🔴 Forte affluence — chat plutôt",
            message: lil.message || "Notre équipe est très sollicitée. Privilégiez ce chat ou notre formulaire de contact pour une réponse plus rapide qu'au téléphone.",
            level: r.data?.level || 0,
          });
          // Auto-show tooltip once per session
          if (!sessionStorage.getItem("sawali_liluvine_alert_seen")) {
            setTooltipOpen(true);
            sessionStorage.setItem("sawali_liluvine_alert_seen", "1");
            setTimeout(() => setTooltipOpen(false), 12000);
          }
        } else {
          setAlert(null);
          setTooltipOpen(false);
        }
      } catch { /* silent */ }
    };
    fetchLoad();
    const t = setInterval(fetchLoad, 60000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!config || dismissed) return null;

  const openPopup = () => {
    setTooltipOpen(false);
    const vw = window.innerWidth || 1024;
    const vh = window.innerHeight || 768;
    const w = Math.min(720, Math.max(320, Math.floor(vw * 0.9)));
    const h = Math.min(640, Math.max(420, Math.floor(vh * 0.85)));
    const top = Math.max(0, Math.floor((window.outerHeight - h) / 2 + (window.screenY || 0)));
    const left = Math.max(0, Math.floor((window.outerWidth - w) / 2 + (window.screenX || 0)));
    const url = config.url.includes("parentURL=")
      ? config.url
      : `${config.url}${config.url.includes("?") ? "&" : "?"}parentURL=${encodeURIComponent(window.location.href)}`;
    window.open(url, "sawali_assistant", `scrollbars=yes,toolbar=no,resizable=yes,width=${w},height=${h},top=${top},left=${left}`);
  };

  const handleDismiss = (e) => {
    e.stopPropagation();
    setDismissed(true);
    sessionStorage.setItem("sawali_assistant_dismissed", "1");
  };

  const inAlert = !!alert;
  const buttonColor = inAlert ? "#dc2626" : (config.color || "#0075E3");
  const buttonLabel = inAlert ? alert.label : (config.label || "Assistant Support");

  return (
    <div className="fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-[60] print:hidden" data-testid="virtual-assistant">
      {/* Alert tooltip — auto-shown once per session, dismissible */}
      {inAlert && tooltipOpen && (
        <div
          className="absolute bottom-full mb-2 right-0 max-w-[280px] sm:max-w-xs rounded-2xl bg-white ring-1 ring-rose-200 shadow-2xl p-3 text-xs animate-in fade-in slide-in-from-bottom-2"
          role="alert"
          data-testid="virtual-assistant-alert"
        >
          <button
            onClick={() => setTooltipOpen(false)}
            className="absolute top-1 right-1 text-slate-400 hover:text-slate-700"
            aria-label="Fermer"
            data-testid="virtual-assistant-alert-close"
          >
            <X className="h-3 w-3" />
          </button>
          <div className="inline-flex items-center gap-1.5 text-rose-700 font-bold mb-1 text-[10px] uppercase tracking-wider">
            <AlertTriangle className="h-3 w-3" /> Forte affluence
          </div>
          <p className="text-slate-700 leading-snug">{alert.message}</p>
          <button
            onClick={openPopup}
            className="mt-2 w-full rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-3 py-1.5 text-xs font-semibold"
            data-testid="virtual-assistant-alert-cta"
          >
            Démarrer le chat
          </button>
          {/* Speech-bubble tail */}
          <span className="absolute -bottom-1.5 right-6 w-3 h-3 bg-white ring-1 ring-rose-200 rotate-45" />
        </div>
      )}

      <div className="relative group">
        <button
          type="button"
          onClick={openPopup}
          onMouseEnter={() => inAlert && setTooltipOpen(true)}
          aria-label={buttonLabel}
          className={`inline-flex items-center justify-center gap-2 rounded-full font-medium text-white shadow-2xl transition-transform hover:scale-105 active:scale-95
                     h-12 w-12 sm:w-auto sm:h-auto sm:px-4 sm:py-2.5 lg:px-5 lg:py-3
                     text-sm lg:text-base 2xl:text-lg ring-2 ring-white/20 ${inAlert ? "animate-bounce-slow" : ""}`}
          style={{
            backgroundColor: buttonColor,
            boxShadow: `0 12px 32px -10px ${buttonColor}aa`,
          }}
          data-testid="virtual-assistant-button"
        >
          {inAlert ? <AlertTriangle className="h-5 w-5 flex-shrink-0" /> : <MessageCircle className="h-5 w-5 flex-shrink-0" />}
          <span className="hidden sm:inline whitespace-nowrap">{buttonLabel}</span>
          <span aria-hidden className="absolute inset-0 rounded-full animate-ping opacity-25 pointer-events-none" style={{ backgroundColor: buttonColor }} />
        </button>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Masquer l'assistant"
          title="Masquer (jusqu'à la prochaine session)"
          className="absolute -top-1.5 -right-1.5 inline-flex items-center justify-center h-5 w-5 rounded-full bg-slate-900 text-white opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
          data-testid="virtual-assistant-dismiss"
        >
          <X className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}
