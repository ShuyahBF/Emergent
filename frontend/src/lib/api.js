import axios from "axios";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const apiClient = axios.create({ baseURL: API });

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("sawali_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  config.metadata = { startTime: Date.now() };
  return config;
});

// =====================================================================
// API TRACE — fire-and-forget log on every mutating call (POST/PUT/PATCH/DELETE)
// + a furtive success toast on 2xx responses (excluding noisy endpoints).
// =====================================================================
const TRACE_SKIP_PATTERNS = [
  "/me/api-trace",
  "/me/access-log",
  "/track",
  "/visits/count",
  "/visits/trend",
  "/auth/captcha-config",
  "/me/formations/", // visit/close happens silently
];
const TOAST_SKIP_PATTERNS = [
  ...TRACE_SKIP_PATTERNS,
  "/auth/login",      // login page already toasts
  "/auth/verify-otp", // login page already toasts
  "/auth/resend-otp",
];

const isTraced = (config) => {
  const m = (config?.method || "").toUpperCase();
  if (!["POST", "PUT", "PATCH", "DELETE"].includes(m)) return false;
  const url = config?.url || "";
  return !TRACE_SKIP_PATTERNS.some((p) => url.includes(p));
};

const truncate = (v, n = 4000) => {
  if (v === undefined || v === null) return null;
  try {
    const s = typeof v === "string" ? v : JSON.stringify(v);
    return s.length > n ? `${s.slice(0, n)}... (truncated, ${s.length} chars)` : s;
  } catch { return String(v).slice(0, n); }
};

const recordTrace = (cfg, status, responseBody, errorMsg) => {
  if (!isTraced(cfg)) return;
  const start = cfg?.metadata?.startTime || Date.now();
  const duration = Date.now() - start;
  const body = {
    method: (cfg.method || "").toUpperCase(),
    url: cfg.url || "",
    status,
    duration_ms: duration,
    request_body: typeof cfg.data === "string" ? truncate(cfg.data) : truncate(cfg.data),
    response_body: truncate(responseBody),
    module: typeof window !== "undefined" ? window.location.pathname : null,
    error: errorMsg || null,
  };
  // Skip multipart/binary uploads — request body is FormData
  if (cfg?.headers?.["Content-Type"]?.toString().includes("multipart")) {
    body.request_body = "[multipart/form-data]";
  }
  // Fire and forget; never block the original request
  apiClient.post("/me/api-trace", body).catch(() => {});
};

const shouldFlashSuccess = (cfg) => {
  if (!isTraced(cfg)) return false;
  const url = cfg?.url || "";
  return !TOAST_SKIP_PATTERNS.some((p) => url.includes(p));
};

apiClient.interceptors.response.use(
  (r) => {
    try {
      recordTrace(r.config, r.status, r.data, null);
      if (shouldFlashSuccess(r.config) && r.status >= 200 && r.status < 300) {
        // Furtive non-blocking success toast — most pages already toast a custom message,
        // so we keep this short and silent (1.5s, low-priority).
        // Pages that already raise their own toast will simply stack a second one — accepted.
        try { toast.success("Opération effectuée avec succès", { duration: 1500 }); } catch { /* noop */ }
      }
    } catch { /* noop */ }
    return r;
  },
  (err) => {
    try {
      const status = err?.response?.status || 0;
      recordTrace(err?.config || {}, status, err?.response?.data, err?.message);
    } catch { /* noop */ }
    if (err?.response?.status === 401 && !err.config?.url?.includes("/auth/")) {
      localStorage.removeItem("sawali_token");
      localStorage.removeItem("sawali_user");
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);
