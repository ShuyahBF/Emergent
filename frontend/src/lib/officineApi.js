// Iter42 — Officine portal: dedicated API client + JWT in localStorage.
// Separate key (`sawali_officine_token`) to avoid clashing with CRM auth.
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const OFFICINE_API = `${BACKEND_URL}/api`;
export const OFFICINE_TOKEN_KEY = "sawali_officine_token";
export const OFFICINE_DATA_KEY = "sawali_officine_data";

export const officineApi = axios.create({ baseURL: OFFICINE_API });

officineApi.interceptors.request.use((config) => {
  const token = localStorage.getItem(OFFICINE_TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

officineApi.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      // Token invalid/expired — clear and redirect to officine login
      const url = err.config?.url || "";
      if (!url.includes("/officines-portal/auth/")) {
        localStorage.removeItem(OFFICINE_TOKEN_KEY);
        localStorage.removeItem(OFFICINE_DATA_KEY);
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/officines/login")) {
          window.location.href = "/officines/login";
        }
      }
    }
    return Promise.reject(err);
  }
);

export function saveOfficineSession(token, officine) {
  localStorage.setItem(OFFICINE_TOKEN_KEY, token);
  localStorage.setItem(OFFICINE_DATA_KEY, JSON.stringify(officine || {}));
}

export function loadOfficineSession() {
  const token = localStorage.getItem(OFFICINE_TOKEN_KEY) || "";
  let officine = null;
  try { officine = JSON.parse(localStorage.getItem(OFFICINE_DATA_KEY) || "null"); } catch { /* noop */ }
  return { token, officine };
}

export function clearOfficineSession() {
  localStorage.removeItem(OFFICINE_TOKEN_KEY);
  localStorage.removeItem(OFFICINE_DATA_KEY);
}
