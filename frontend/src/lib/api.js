import axios from "axios";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const apiClient = axios.create({ baseURL: API });

// =====================================================================
// Lot 44 — « Voir en tant que » (super-admin).
// Le jeton « en tant que » est rangé dans le sessionStorage de l'ONGLET : il
// remplace le jeton de l'Admin pour cet onglet seulement. Le jeton de l'Admin
// reste en place dans le localStorage (les autres onglets gardent le compte
// Admin) et redevient actif dès que les clés ci-dessous sont effacées.
// =====================================================================
export const CLE_IMP_JETON = "sawali_imp_token";   // jeton de la cible (30 min)
export const CLE_IMP_USER = "sawali_imp_user";     // profil de la cible
export const CLE_IMP_INFO = "sawali_imp_info";     // {session_id, cible_nom, cible_role, admin_nom, ro, expire_le, retour}

const lireSession = (cle) => {
  try { return typeof sessionStorage !== "undefined" ? sessionStorage.getItem(cle) : null; } catch { return null; }
};

/** Vrai si cet onglet navigue « en tant que » un autre compte. */
export function sessionImpActive() {
  return !!lireSession(CLE_IMP_JETON);
}

/** Informations de la session « en tant que » de cet onglet (ou null). */
export function infoImp() {
  try { return JSON.parse(lireSession(CLE_IMP_INFO) || "null"); } catch { return null; }
}

/** Jeton à envoyer : celui de la session « en tant que » s'il y en a une, sinon celui du compte. */
export function jetonCourant() {
  return lireSession(CLE_IMP_JETON) || (typeof localStorage !== "undefined" ? localStorage.getItem("sawali_token") : null);
}

/**
 * Quitte la session « en tant que » de cet onglet : efface le jeton de la cible
 * (le jeton de l'Admin, resté dans le localStorage, reprend la main) puis, si
 * demandé, recharge la page d'origine (fiche admin d'où la session a été ouverte).
 */
export function quitterSessionImp({ rediriger = true } = {}) {
  // Déjà quittée (ex. appel en double après un 401) : on ne relance pas de redirection.
  if (!sessionImpActive()) return false;
  const info = infoImp();
  try {
    sessionStorage.removeItem(CLE_IMP_JETON);
    sessionStorage.removeItem(CLE_IMP_USER);
    sessionStorage.removeItem(CLE_IMP_INFO);
  } catch { /* noop */ }
  if (rediriger && typeof window !== "undefined") {
    window.location.href = (info && info.retour) || "/admin";
  }
  return true;
}

// =====================================================================
// Lot 50 — refus avec un code lisible ({detail, code}) renvoyés par le serveur :
//   - 503 « maintenance_plateforme » : déconnexion forcée, retour à la connexion ;
//   - 401 « session_* » : session fermée (limite d'appareils, fermée à distance,
//     inactivité, maintenance) — le motif est affiché sur la page de connexion ;
//   - 402 « abonnement_expire » : l'écran « Abonnement expiré » s'affiche.
// =====================================================================
export const CLE_MOTIF_DECONNEXION = "sawali_motif_deconnexion";
export const EVENEMENT_ABONNEMENT = "sawali:abonnement";

export function noterMotifDeconnexion(message) {
  try { if (message) sessionStorage.setItem(CLE_MOTIF_DECONNEXION, message); } catch { /* noop */ }
}

/** Motif de la dernière déconnexion forcée (lu une seule fois par la page de connexion). */
export function lireMotifDeconnexion() {
  try {
    const m = sessionStorage.getItem(CLE_MOTIF_DECONNEXION);
    if (m) sessionStorage.removeItem(CLE_MOTIF_DECONNEXION);
    return m || "";
  } catch { return ""; }
}

/** Fermeture de la session du compte côté serveur (déconnexion) : sans attendre la réponse. */
export function fermerSessionServeur() {
  const jeton = typeof localStorage !== "undefined" ? localStorage.getItem("sawali_token") : null;
  if (!jeton) return;
  apiClient.post("/auth/logout", null, { headers: { Authorization: `Bearer ${jeton}` } }).catch(() => {});
}

apiClient.interceptors.request.use((config) => {
  // Lot 44 — jeton de la session « en tant que » de l'onglet en priorité
  const token = jetonCourant();
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
  "/me/activite",    // lot 50 — signal d'activité (contrôle serveur de l'inactivité), silencieux
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
    // Lot 50 — maintenance, session fermée, abonnement expiré
    const codeRefus = err?.response?.data?.code || "";
    if (err?.response?.status === 402 && codeRefus === "abonnement_expire" && typeof window !== "undefined") {
      try { window.dispatchEvent(new CustomEvent(EVENEMENT_ABONNEMENT, { detail: err.response.data })); } catch { /* noop */ }
    }
    if (err?.response?.status === 503 && codeRefus === "maintenance_plateforme" && !sessionImpActive()) {
      const avaitJeton = typeof localStorage !== "undefined" && !!localStorage.getItem("sawali_token");
      if (avaitJeton) {
        noterMotifDeconnexion(err.response.data.detail);
        localStorage.removeItem("sawali_token");
        localStorage.removeItem("sawali_user");
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          window.location.href = "/login";
        }
      }
    }
    if (err?.response?.status === 401 && codeRefus.startsWith("session_") && !sessionImpActive()) {
      noterMotifDeconnexion(err.response.data.detail);
    }
    if (err?.response?.status === 401) {
      const url = err.config?.url || "";
      const isAuthEndpoint = url.includes("/auth/");
      const isTelemetry = NO_LOGOUT_ON_401.some((p) => url.includes(p));
      // Lot 44 — session « en tant que » expirée ou close : retour au compte de
      // l'Admin (son jeton est intact), sans le déconnecter.
      if (sessionImpActive() && !isTelemetry) {
        quitterSessionImp();
        return Promise.reject(err);
      }
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
