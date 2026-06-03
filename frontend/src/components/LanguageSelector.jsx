// S046 — Language selector dropdown.
// Compact button + popover with the supported languages from the backend.
import React, { useEffect, useRef, useState } from "react";
import { Globe, Check } from "lucide-react";
import { toast } from "sonner";
import { useI18n } from "@/contexts/I18nContext";

export default function LanguageSelector({ compact = false }) {
  const { lang, setLang, languages, t } = useI18n();
  const [open, setOpen] = useState(false);
  const popRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e) => {
      if (popRef.current && !popRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  const current = (languages || []).find((l) => l.code === lang);

  const handlePick = (langDef) => {
    if (langDef.code === lang) { setOpen(false); return; }
    setLang(langDef.code);
    setOpen(false);
    // Visual feedback : confirms the click registered even when most of
    // the visible page has no translation yet (fallback FR applies).
    const label = langDef.native || langDef.label || langDef.code.toUpperCase();
    const msg = t("lang.changed", "Langue changée");
    toast.success(`${msg} : ${label}`, { duration: 2500, id: "lang-change" });
  };

  return (
    <div className="relative" ref={popRef} data-testid="language-selector">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 bg-white hover:bg-slate-50 px-2 py-1 text-xs"
        title="Choisir la langue"
        data-testid="language-selector-toggle"
      >
        <Globe className="h-3.5 w-3.5 text-slate-500" />
        <span className="font-semibold uppercase">{lang}</span>
        {!compact && current?.native && (
          <span className="text-slate-500 hidden sm:inline">· {current.native}</span>
        )}
      </button>
      {open && (
        <div
          className="absolute right-0 mt-1 z-50 min-w-[180px] rounded-lg ring-1 ring-slate-200 bg-white shadow-lg py-1"
          data-testid="language-selector-popover"
        >
          {(languages || []).map((l) => {
            const isActive = l.code === lang;
            return (
              <button
                key={l.code}
                type="button"
                onClick={() => handlePick(l)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-slate-50 ${isActive ? "bg-sky-50 text-sky-800 font-semibold" : "text-slate-700"}`}
                data-testid={`language-option-${l.code}`}
              >
                <span className="uppercase font-mono text-[10px] bg-slate-100 rounded px-1 py-0.5">{l.code}</span>
                <span className="flex-1 text-left">{l.native || l.label}</span>
                {isActive && <Check className="h-3.5 w-3.5 text-sky-600" />}
              </button>
            );
          })}
          <div className="border-t border-slate-100 mt-1 pt-1 px-3 pb-1 text-[10px] text-slate-400 italic">
            Source : FR · fallback automatique
          </div>
        </div>
      )}
    </div>
  );
}
