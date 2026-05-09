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
  "/auth/", // Skip ALL auth endpoints — they fire before localStorage has the token
            // (would cause /me/api-trace to be called without auth → 401 → forced logout race)
  "/me/formations/", // visit/close happens silently
];

// Paths that should NEVER trigger a forced logout on 401, even if the user is logged in.
// These are telemetry/non-critical and a 401 here must not wipe the session.
const NO_LOGOUT_ON_401 = ["/me/api-trace", "/me/access-log", "/track"];
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

// =====================================================================
// Redact sensitive keys before sending to the trace endpoint.
// Matches password, token, secret, api_key (and common variants).
// =====================================================================
const SENSITIVE_RE = /(password|passwd|secret|token|api[_-]?key|recaptcha|otp|code|session_token|smtp_password|smtp_user|api_basic_pass|webhook_token|webhook_basic_pass|notes_webhook_token|notes_webhook_basic_pass)/i;

const redact = (value) => {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map(redact);
  if (typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = SENSITIVE_RE.test(k) ? "[REDACTED]" : redact(v);
    }
    return out;
  }
  return value;
};

const recordTrace = (cfg, status, responseBody, errorMsg) => {
  if (!isTraced(cfg)) return;
  const start = cfg?.metadata?.startTime || Date.now();
  const duration = Date.now() - start;
  // Parse string bodies before redacting (axios may send already-stringified data)
  let reqRaw = cfg.data;
  if (typeof reqRaw === "string") {
    try { reqRaw = JSON.parse(reqRaw); } catch { /* keep as string */ }
  }
  const safeReq = typeof reqRaw === "string" ? reqRaw : redact(reqRaw);
  const safeResp = typeof responseBody === "string" ? responseBody : redact(responseBody);
  const body = {
    method: (cfg.method || "").toUpperCase(),
    url: cfg.url || "",
    status,
    duration_ms: duration,
    request_body: truncate(safeReq),
    response_body: truncate(safeResp),
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
      // Surface the upstream webhook result (if any) as a centered modal.
      // Only show when the webhook is enabled — silent otherwise.
      const wr = r?.data?.webhook_result;
      if (wr && wr.enabled) {
        // Dynamic import to avoid a circular dep between api.js ↔ WebhookResultModal.jsx
        import("@/components/WebhookResultModal").then((mod) => {
          mod.showWebhookResult(wr);
        }).catch(() => { /* noop */ });
      }
    } catch { /* noop */ }
    return r;
  },
  (err) => {
    try {
      const status = err?.response?.status || 0;
      recordTrace(err?.config || {}, status, err?.response?.data, err?.message);
    } catch { /* noop */ }
    if (err?.response?.status === 401) {
      const url = err.config?.url || "";
      const isAuthEndpoint = url.includes("/auth/");
      const isTelemetry = NO_LOGOUT_ON_401.some((p) => url.includes(p));
      // Only force a logout-redirect when the user WAS logged in. Anonymous
      // visitors of public marketing pages whose components opportunistically
      // call /me/* endpoints get a 401 — that's expected, do NOT bounce them
      // to /login (it would break the entire public site for first-time visitors).
      const hadToken = typeof localStorage !== "undefined" && !!localStorage.getItem("sawali_token");
      if (!isAuthEndpoint && !isTelemetry && hadToken) {
        localStorage.removeItem("sawali_token");
        localStorage.removeItem("sawali_user");
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(err);
  }
);
