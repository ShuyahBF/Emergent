// S046 (2026-02) — i18n provider for the SAWALI frontend.
//
// Initial language resolution order :
//   1. `localStorage.sawali_lang` if the user has previously chosen one
//   2. `navigator.language` (browser/system) mapped to a supported code
//   3. Backend `/api/i18n/detect` (IP region → suggested language)
//   4. Fallback to FR
//
// Strategy : we keep our own tiny wrapper (no react-i18next runtime) so
// the admin's MongoDB-backed translations remain the source of truth.
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";

const STORAGE_KEY = "sawali_lang";
const DEFAULT_LANG = "fr";
const SUPPORTED_FALLBACK = ["fr", "en", "ar", "lg1", "lg2"];

function _normalizeBrowserLang(navLang) {
  if (!navLang) return "";
  const base = String(navLang).toLowerCase().split("-")[0];
  // Treat anything that starts with "ar" (incl. ar-MA, ar-EG…) as Arabic
  if (base === "ar") return "ar";
  if (base === "fr") return "fr";
  if (base === "en") return "en";
  return "";
}

const I18nContext = createContext({
  lang: DEFAULT_LANG,
  setLang: () => {},
  t: (key, fallback) => fallback || key,
  translations: {},
  languages: [],
  loading: false,
  isDetecting: false,
});

export function I18nProvider({ children }) {
  // Step 1: if user has an explicit choice in localStorage, honour it.
  // Step 2: otherwise try navigator.language synchronously so the first
  //         paint is in the right language whenever possible.
  // Step 3: kick off an async /i18n/detect call for region-based override
  //         when no explicit choice and no browser hint matched.
  const initialLang = (() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && SUPPORTED_FALLBACK.includes(stored)) return stored;
    } catch { /* noop */ }
    const fromBrowser = _normalizeBrowserLang(
      (typeof navigator !== "undefined" && (navigator.language || (navigator.languages && navigator.languages[0]))) || ""
    );
    return fromBrowser || DEFAULT_LANG;
  })();

  const [lang, setLangState] = useState(initialLang);
  const [translations, setTranslations] = useState({});
  const [languages, setLanguages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [userPickedExplicit, setUserPickedExplicit] = useState(() => {
    try { return !!localStorage.getItem(STORAGE_KEY); } catch { return false; }
  });

  // Fetch supported languages once
  useEffect(() => {
    apiClient.get("/i18n/languages").then((r) => {
      setLanguages(r.data?.items || []);
    }).catch(() => {});
  }, []);

  // Region-based detect — only if user hasn't picked explicitly AND we couldn't
  // infer from navigator. This is the BF → FR / MA → AR rule.
  useEffect(() => {
    if (userPickedExplicit) return;
    let stored = "";
    try { stored = localStorage.getItem(STORAGE_KEY) || ""; } catch { /* noop */ }
    if (stored) return;
    const fromBrowser = _normalizeBrowserLang(
      (typeof navigator !== "undefined" && (navigator.language || (navigator.languages && navigator.languages[0]))) || ""
    );
    if (fromBrowser) return; // we already used it as initialLang
    setIsDetecting(true);
    apiClient.get("/i18n/detect").then((r) => {
      const suggested = r.data?.suggested_lang;
      if (suggested && SUPPORTED_FALLBACK.includes(suggested) && suggested !== lang) {
        setLangState(suggested);
      }
    }).catch(() => {}).finally(() => setIsDetecting(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    setUserPickedExplicit(true);
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
    lang, setLang, t, translations, languages, loading, isDetecting,
  }), [lang, setLang, t, translations, languages, loading, isDetecting]);

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
