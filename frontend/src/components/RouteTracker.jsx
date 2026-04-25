import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { apiClient } from "@/lib/api";

/** Generates a stable session id stored in localStorage. */
const sessionId = (() => {
  if (typeof window === "undefined") return "";
  let id = localStorage.getItem("sawali_sid");
  if (!id) {
    id = (crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
    localStorage.setItem("sawali_sid", id);
  }
  return id;
})();

/**
 * Tracks every route change by POSTing to /api/track.
 * The backend resolves IP + country/city and (if configured) forwards
 * the event to the external REST endpoint defined in admin settings.
 */
export default function RouteTracker() {
  const location = useLocation();
  useEffect(() => {
    const path = location.pathname + (location.search || "");
    apiClient.post("/track", {
      page: path,
      referrer: document.referrer || "",
      session_id: sessionId,
    }).catch(() => {}); // never block the UI
  }, [location.pathname, location.search]);
  return null;
}
