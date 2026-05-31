// Iter38r-fix9p — RGPD cookie consent banner for the public site.
// Persists choices in localStorage under `sawali_cookie_consent_v1` :
//   { necessary: true, analytics: bool, marketing: bool, preferences: bool,
//     accepted_at: ISO, version: 1 }
// Necessary cookies (session, auth, CSRF) are always on.
// Banner re-appears only if no decision was stored OR version is bumped.
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Cookie, X, Check, Settings2 } from "lucide-react";

const STORAGE_KEY = "sawali_cookie_consent_v1";
const VERSION = 1;

export const getConsent = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed.version !== VERSION) return null;
    return parsed;
  } catch { return null; }
};

export default function CookieBanner() {
  const [open, setOpen] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [choices, setChoices] = useState({
    analytics: true,
    marketing: false,
    preferences: true,
  });

  useEffect(() => {
    if (!getConsent()) {
      // Small delay to avoid layout shift on first paint
      const t = setTimeout(() => setOpen(true), 800);
      return () => clearTimeout(t);
    }
  }, []);

  const save = (overrides) => {
    const final = {
      necessary: true,
      analytics: overrides?.analytics ?? choices.analytics,
      marketing: overrides?.marketing ?? choices.marketing,
      preferences: overrides?.preferences ?? choices.preferences,
      accepted_at: new Date().toISOString(),
      version: VERSION,
    };
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(final)); } catch {}
    setOpen(false);
  };

  const acceptAll = () => save({ analytics: true, marketing: true, preferences: true });
  const rejectOptional = () => save({ analytics: false, marketing: false, preferences: false });

  if (!open) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-[90] p-3 sm:p-4 print:hidden" data-testid="cookie-banner">
      <div className="max-w-5xl mx-auto rounded-2xl ring-1 ring-slate-200 bg-white shadow-2xl shadow-slate-900/30 overflow-hidden">
        <div className="p-4 sm:p-5">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-amber-100 ring-1 ring-amber-200 p-2 flex-shrink-0">
              <Cookie className="h-5 w-5 text-amber-700" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-display font-bold text-slate-900 text-sm">Cookies & vie privée</h3>
              <p className="text-xs text-slate-600 mt-1 leading-relaxed">
                Nous utilisons des cookies pour le bon fonctionnement du site (obligatoires), mesurer l'audience et améliorer votre expérience. Vous gardez le contrôle.
                {" "}<Link to="/politique-confidentialite" className="text-sawali-blue underline">En savoir plus</Link>.
              </p>

              {showDetails && (
                <div className="mt-3 space-y-2 rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3">
                  <CookieRow label="Nécessaires" desc="Session, authentification, sécurité. Indispensables." enabled disabled />
                  <CookieRow
                    label="Préférences"
                    desc="Thème, langue, dernières recherches."
                    enabled={choices.preferences}
                    onToggle={() => setChoices((c) => ({ ...c, preferences: !c.preferences }))}
                    testid="cookie-toggle-preferences"
                  />
                  <CookieRow
                    label="Mesure d'audience (analytics)"
                    desc="Statistiques d'utilisation anonymes (Plausible, etc.) — aucune donnée personnelle vendue."
                    enabled={choices.analytics}
                    onToggle={() => setChoices((c) => ({ ...c, analytics: !c.analytics }))}
                    testid="cookie-toggle-analytics"
                  />
                  <CookieRow
                    label="Marketing"
                    desc="Personnalisation des contenus, retargeting publicitaire."
                    enabled={choices.marketing}
                    onToggle={() => setChoices((c) => ({ ...c, marketing: !c.marketing }))}
                    testid="cookie-toggle-marketing"
                  />
                </div>
              )}

              <div className="flex flex-wrap gap-2 mt-3">
                <button
                  type="button"
                  onClick={acceptAll}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium px-3 py-1.5"
                  data-testid="cookie-accept-all"
                >
                  <Check className="h-3.5 w-3.5" /> Tout accepter
                </button>
                <button
                  type="button"
                  onClick={rejectOptional}
                  className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-medium px-3 py-1.5"
                  data-testid="cookie-reject-optional"
                >
                  <X className="h-3.5 w-3.5" /> Refuser les optionnels
                </button>
                {showDetails ? (
                  <button
                    type="button"
                    onClick={() => save()}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-medium px-3 py-1.5"
                    data-testid="cookie-save-choices"
                  >
                    <Check className="h-3.5 w-3.5" /> Enregistrer mes choix
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowDetails(true)}
                    className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-medium px-3 py-1.5"
                    data-testid="cookie-customize"
                  >
                    <Settings2 className="h-3.5 w-3.5" /> Personnaliser
                  </button>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={rejectOptional}
              aria-label="Fermer le bandeau cookies"
              className="ml-1 text-slate-400 hover:text-slate-700 transition-colors flex-shrink-0"
              data-testid="cookie-banner-close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function CookieRow({ label, desc, enabled, onToggle, disabled, testid }) {
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        onClick={!disabled ? onToggle : undefined}
        disabled={disabled}
        className={`mt-0.5 inline-flex h-5 w-9 items-center rounded-full transition-colors flex-shrink-0 ${
          enabled ? "bg-emerald-600" : "bg-slate-300"
        } ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
        data-testid={testid}
      >
        <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${enabled ? "translate-x-5" : "translate-x-1"}`} />
      </button>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-slate-800">{label}{disabled && <span className="ml-1 text-[10px] text-slate-500 font-normal">(toujours actifs)</span>}</p>
        <p className="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{desc}</p>
      </div>
    </div>
  );
}
