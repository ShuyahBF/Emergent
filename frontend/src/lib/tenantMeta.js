/*
 * Iter38b — Helper to get the tenant-configured phone placeholder.
 *
 * Reads from localStorage (where AuthContext caches /api/me/tenant-meta).
 * Works inside ANY component (no hook required), so it can be used in
 * deeply nested JSX placeholder props without prop drilling.
 *
 * The tenant meta is refreshed at login and on AuthContext mount.
 */

const FALLBACK = {
  phone_example: "+22670000000",
  dial_prefix: "+226",
  country_code: "BF",
  country_name: "Burkina Faso",
};

export function getTenantMeta() {
  try {
    const raw = localStorage.getItem("sawali_tenant_meta");
    if (!raw) return FALLBACK;
    const m = JSON.parse(raw);
    return {
      phone_example: m.phone_example || FALLBACK.phone_example,
      dial_prefix: m.dial_prefix || FALLBACK.dial_prefix,
      country_code: m.country_code || FALLBACK.country_code,
      country_name: m.country_name || FALLBACK.country_name,
    };
  } catch {
    return FALLBACK;
  }
}

export function phonePlaceholder() {
  return getTenantMeta().phone_example;
}

export function dialPrefix() {
  return getTenantMeta().dial_prefix;
}
