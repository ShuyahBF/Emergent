// Iter38r-fix9z10 — Suggestion S009 — Auto-logout integration.
// Mounts the idle timer ONLY when a user is authenticated. Fetches the
// admin-configured `auto_logout_minutes` from /api/me/idle-config on login,
// then schedules timers + shows a 30-second warning modal before logging out.
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Clock, LogOut } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { useIdleTimer } from "@/lib/useIdleTimer";

export default function AutoLogoutGate() {
  const { user, logout } = useAuth() || {};
  const navigate = useNavigate();
  const [config, setConfig] = useState({ auto_logout_minutes: 0, warning_seconds: 30 });

  // Pull config when the user becomes authenticated
  useEffect(() => {
    if (!user) {
      setConfig({ auto_logout_minutes: 0, warning_seconds: 30 });
      return;
    }
    let cancelled = false;
    apiClient.get("/me/idle-config")
      .then((r) => { if (!cancelled) setConfig(r.data); })
      .catch(() => { /* silent — falls back to disabled */ });
    return () => { cancelled = true; };
  }, [user]);

  const handleLogout = () => {
    try { logout && logout(); } catch { /* swallow */ }
    toast.warning("Session expirée par inactivité — merci de vous reconnecter.", {
      duration: 6000,
      id: "idle-logout-toast",
    });
    // S-iter39d (fix #3) — Hard navigation guarantees every lingering modal
    // (Welcome briefing, dialogs, sticky toasts) is unmounted. The previous
    // react-router navigate() could leave the Welcome briefing visible
    // because PortalLayout state survived the auth context update.
    try {
      window.location.assign("/login");
    } catch {
      navigate("/login", { replace: true });
    }
  };

  const { warningCountdown, stayConnected } = useIdleTimer({
    idleMinutes: Number(config.auto_logout_minutes) || 0,
    warningSeconds: Number(config.warning_seconds) || 30,
    onLogout: handleLogout,
    enabled: !!user,
  });

  // 2026-02 (#5) — When admin enables `force_logout_on_idle` for a user,
  // we don't show the warning modal — we logout immediately as soon as the
  // idle timer would have surfaced the warning. The hook still measures
  // inactivity correctly; we simply bypass the modal.
  useEffect(() => {
    if (!user) return;
    if (warningCountdown === null) return;
    if (user.force_logout_on_idle) {
      // Skip warning, force immediate logout
      handleLogout();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [warningCountdown, user]);

  if (warningCountdown === null) return null;
  // When `force_logout_on_idle` is on, also hide the modal to avoid flicker.
  if (user?.force_logout_on_idle) return null;

  return (
    <div
      className="fixed inset-0 z-[9999] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="idle-warning-title"
      data-testid="idle-warning-modal"
    >
      <div className="bg-white rounded-2xl ring-1 ring-rose-200 shadow-2xl max-w-md w-full p-6 sm:p-7">
        <div className="flex items-center gap-3 mb-3">
          <div className="h-12 w-12 rounded-full bg-rose-50 flex items-center justify-center">
            <Clock className="h-6 w-6 text-rose-600 animate-pulse" />
          </div>
          <div>
            <h2 id="idle-warning-title" className="font-display font-bold text-lg text-slate-900">
              Session bientôt fermée
            </h2>
            <p className="text-xs text-slate-500">Inactivité détectée</p>
          </div>
        </div>
        <p className="text-sm text-slate-700">
          Vous allez être déconnecté(e) dans{" "}
          <strong className="text-rose-700 tabular-nums" data-testid="idle-warning-countdown">
            {warningCountdown}
          </strong>{" "}
          seconde{warningCountdown > 1 ? "s" : ""} faute d'activité.
        </p>
        <p className="text-xs text-slate-500 mt-2">
          Cliquez sur « Rester connecté(e) » pour prolonger votre session.
        </p>
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 mt-5">
          <button
            onClick={handleLogout}
            className="text-xs inline-flex items-center justify-center gap-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-2"
            data-testid="idle-warning-logout-now"
          >
            <LogOut className="h-3.5 w-3.5" /> Se déconnecter maintenant
          </button>
          <button
            onClick={stayConnected}
            className="text-sm inline-flex items-center justify-center gap-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 font-semibold shadow-sm"
            data-testid="idle-warning-stay"
          >
            Rester connecté(e)
          </button>
        </div>
      </div>
    </div>
  );
}
