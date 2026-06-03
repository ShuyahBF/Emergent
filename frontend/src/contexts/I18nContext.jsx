// S046 (2026-02) — i18n provider for the SAWALI frontend.
//
// Strategy : we ship our own thin wrapper around i18next so the admin's
// MongoDB-backed translations are the source of truth. The provider
// fetches `/api/i18n/translations?lang=…` on mount and on language
// change, then exposes a `t(key, fallback?)` helper via context.
//
// The selected language is persisted in localStorage (`sawali_lang`)
// so the user keeps their choice across sessions. Default = FR.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";

const STORAGE_KEY = "sawali_lang";
const DEFAULT_LANG = "fr";

const I18nContext = createContext({
  lang: DEFAULT_LANG,
  setLang: () => {},
  t: (key, fallback) => fallback || key,
  translations: {},
  languages: [],
  loading: false,
});

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG; }
    catch { return DEFAULT_LANG; }
  });
  const [translations, setTranslations] = useState({});
  const [languages, setLanguages] = useState([]);
  const [loading, setLoading] = useState(false);

  // Fetch supported languages once
  useEffect(() => {
    apiClient.get("/i18n/languages").then((r) => {
      setLanguages(r.data?.items || []);
    }).catch(() => {});
  }, []);

  // Fetch translations whenever the language changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    apiClient.get("/i18n/translations", { params: { lang } })
      .then((r) => {
        if (cancelled) return;
        setTranslations(r.data?.translations || {});
      })
      .catch(() => { if (!cancelled) setTranslations({}); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [lang]);

  // Apply RTL on <html> for Arabic
  useEffect(() => {
    const langDef = languages.find((l) => l.code === lang);
    if (langDef) {
      document.documentElement.setAttribute("dir", langDef.rtl ? "rtl" : "ltr");
      document.documentElement.setAttribute("lang", lang);
    }
  }, [lang, languages]);

  const setLang = useCallback((nextLang) => {
    if (!nextLang) return;
    setLangState(nextLang);
    try { localStorage.setItem(STORAGE_KEY, nextLang); } catch { /* noop */ }
  }, []);

  // The lookup helper. `fallback` is used when the key isn't present in
  // the dictionary (typically a hardcoded French label, so the UI keeps
  // its meaning even before the admin has translated the new string).
  const t = useCallback((key, fallback) => {
    if (translations[key]) return translations[key];
    return fallback != null ? fallback : key;
  }, [translations]);

  const value = useMemo(() => ({
    lang, setLang, t, translations, languages, loading,
  }), [lang, setLang, t, translations, languages, loading]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

// Convenience hook returning just the `t` function (mirrors react-i18next)
export function useT() {
  const { t } = useContext(I18nContext);
  return t;
}
