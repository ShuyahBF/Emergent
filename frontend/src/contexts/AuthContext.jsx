import React, { createContext, useContext, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const u = localStorage.getItem("sawali_user");
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("sawali_token");
    if (!token) { setLoading(false); return; }
    apiClient
      .get("/auth/me")
      .then((r) => {
        setUser(r.data);
        localStorage.setItem("sawali_user", JSON.stringify(r.data));
      })
      .catch(() => {
        localStorage.removeItem("sawali_token");
        localStorage.removeItem("sawali_user");
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = (token, userObj) => {
    localStorage.setItem("sawali_token", token);
    localStorage.setItem("sawali_user", JSON.stringify(userObj));
    setUser(userObj);
  };

  const logout = () => {
    localStorage.removeItem("sawali_token");
    localStorage.removeItem("sawali_user");
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
