import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { MessageCircle, X } from "lucide-react";

/**
 * Floating Virtual Assistant button.
 * Opens an external popup chatbot (e.g. JotForm AI agent) on click.
 * Configuration is loaded from /api/company-info → settings.assistant.
 */
export default function VirtualAssistant() {
  const [config, setConfig] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    apiClient.get("/company-info").then((r) => {
      const a = r.data?.assistant;
      if (a && a.enabled && a.url) setConfig(a);
    }).catch(() => {});
    // Hide if user dismissed it earlier in this session
    if (sessionStorage.getItem("sawali_assistant_dismissed") === "1") {
      setDismissed(true);
    }
  }, []);

  if (!config || dismissed) return null;

  const openPopup = () => {
    // Compute popup size based on viewport: 90% of viewport, capped to 720x600.
    // On very small screens, use almost full width.
    const vw = window.innerWidth || 1024;
    const vh = window.innerHeight || 768;
    const w = Math.min(720, Math.max(320, Math.floor(vw * 0.9)));
    const h = Math.min(640, Math.max(420, Math.floor(vh * 0.85)));
    const top = Math.max(0, Math.floor((window.outerHeight - h) / 2 + (window.screenY || 0)));
    const left = Math.max(0, Math.floor((window.outerWidth - w) / 2 + (window.screenX || 0)));
    const url = config.url.includes("parentURL=")
      ? config.url
      : `${config.url}${config.url.includes("?") ? "&" : "?"}parentURL=${encodeURIComponent(window.location.href)}`;
    window.open(
      url,
      "sawali_assistant",
      `scrollbars=yes,toolbar=no,resizable=yes,width=${w},height=${h},top=${top},left=${left}`,
    );
  };

  const handleDismiss = (e) => {
    e.stopPropagation();
    setDismissed(true);
    sessionStorage.setItem("sawali_assistant_dismissed", "1");
  };

  return (
    <div className="fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-[60] print:hidden" data-testid="virtual-assistant">
      <div className="relative group">
        <button
          type="button"
          onClick={openPopup}
          aria-label={config.label || "Assistant Support"}
          className="inline-flex items-center justify-center gap-2 rounded-full font-medium text-white shadow-2xl transition-transform hover:scale-105 active:scale-95
                     h-12 w-12 sm:w-auto sm:h-auto sm:px-4 sm:py-2.5 lg:px-5 lg:py-3
                     text-sm lg:text-base 2xl:text-lg
                     ring-2 ring-white/20"
          style={{
            backgroundColor: config.color || "#0075E3",
            boxShadow: `0 12px 32px -10px ${config.color || "#0075E3"}aa`,
          }}
          data-testid="virtual-assistant-button"
        >
          <MessageCircle className="h-5 w-5 lg:h-5 lg:w-5 2xl:h-6 2xl:w-6 flex-shrink-0" />
          <span className="hidden sm:inline whitespace-nowrap">{config.label || "Assistant Support"}</span>
          {/* Pulsing ring */}
          <span
            aria-hidden
            className="absolute inset-0 rounded-full animate-ping opacity-25 pointer-events-none"
            style={{ backgroundColor: config.color || "#0075E3" }}
          />
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
