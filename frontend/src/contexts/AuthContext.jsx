import React, { createContext, useContext, useEffect, useState } from "react";
import { apiClient, sessionImpActive, quitterSessionImp, jetonCourant, CLE_IMP_USER } from "@/lib/api";

const AuthCtx = createContext(null);

const DEFAULT_TENANT_META = {
  country_code: "BF",
  country_name: "Burkina Faso",
  dial_prefix: "+226",
  phone_example: "+22670000000",
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      // Lot 44 — onglet en « Voir en tant que » : profil de la cible (sessionStorage)
      if (sessionImpActive()) {
        const ui = sessionStorage.getItem(CLE_IMP_USER);
        if (ui) return JSON.parse(ui);
      }
      const u = localStorage.getItem("sawali_user");
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);
  const [tenantMeta, setTenantMeta] = useState(() => {
    try {
      const m = localStorage.getItem("sawali_tenant_meta");
      return m ? JSON.parse(m) : DEFAULT_TENANT_META;
    } catch {
      return DEFAULT_TENANT_META;
    }
  });

  const refreshTenantMeta = React.useCallback(async () => {
    try {
      const r = await apiClient.get("/me/tenant-meta");
      const m = r.data || DEFAULT_TENANT_META;
      setTenantMeta(m);
      localStorage.setItem("sawali_tenant_meta", JSON.stringify(m));
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    const token = jetonCourant();
    if (!token) { setLoading(false); return; }
    apiClient
      .get("/auth/me")
      .then((r) => {
        setUser(r.data);
        // Lot 44 — en « Voir en tant que », le profil de l'Admin (localStorage) n'est pas écrasé
        if (sessionImpActive()) sessionStorage.setItem(CLE_IMP_USER, JSON.stringify(r.data));
        else localStorage.setItem("sawali_user", JSON.stringify(r.data));
        refreshTenantMeta();
      })
      .catch(() => {
        // Lot 44 — jeton « en tant que » refusé (expiré, session close) : retour au compte Admin
        if (sessionImpActive()) { quitterSessionImp(); return; }
        localStorage.removeItem("sawali_token");
        localStorage.removeItem("sawali_user");
        localStorage.removeItem("sawali_tenant_meta");
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, [refreshTenantMeta]);

  const login = (token, userObj) => {
    // Lot 44 — une vraie connexion met fin à toute session « en tant que » de l'onglet
    quitterSessionImp({ rediriger: false });
    localStorage.setItem("sawali_token", token);
    localStorage.setItem("sawali_user", JSON.stringify(userObj));
    try {
      sessionStorage.removeItem("sawali_welcome_briefing_seen");
    } catch { /* noop */ }
    setUser(userObj);
    refreshTenantMeta();
  };

  const logout = () => {
    // Lot 44 — « Déconnexion » pendant un « Voir en tant que » : on clôt la session
    // et on revient au compte de l'Admin (qui, lui, reste connecté).
    if (sessionImpActive()) {
      apiClient.post("/voir-en-tant-que/fin").catch(() => {}).finally(() => quitterSessionImp());
      return;
    }
    localStorage.removeItem("sawali_token");
    localStorage.removeItem("sawali_user");
    try {
      sessionStorage.removeItem("sawali_welcome_briefing_seen");
    } catch { /* noop */ }
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout, tenantMeta, refreshTenantMeta }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);

export const usePhonePlaceholder = () => {
  const { tenantMeta } = useAuth() || {};
  return (tenantMeta && tenantMeta.phone_example) || DEFAULT_TENANT_META.phone_example;
};
