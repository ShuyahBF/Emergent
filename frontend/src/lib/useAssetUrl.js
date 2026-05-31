// Iter38r-fix9z5-P3 — Single source of truth for resolving asset URLs.
// Centralizes the relative-vs-absolute decision so `/api/files/{id}` and
// other backend-served assets work in BOTH preview and production without
// each component re-implementing the same prefix logic.
//
// Usage:
//   const resolve = useAssetUrl();
//   <img src={resolve(banner.image_url)} />
//
// Or for one-off resolution outside React:
//   import { resolveAssetUrl } from "@/lib/useAssetUrl";
//   const full = resolveAssetUrl("/api/files/abc");
import { useCallback } from "react";

const BACKEND = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

export function resolveAssetUrl(u) {
  if (!u) return "";
  if (typeof u !== "string") return "";
  if (u.startsWith("http://") || u.startsWith("https://")) return u;
  if (u.startsWith("data:") || u.startsWith("blob:")) return u;
  if (u.startsWith("/")) return `${BACKEND}${u}`;
  return `${BACKEND}/${u}`;
}

export function useAssetUrl() {
  return useCallback(resolveAssetUrl, []);
}
