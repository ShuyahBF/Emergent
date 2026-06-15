// Iter43-fix20 (2026-06) — Météo widget piloté par Open-Meteo.
// Deux variantes : `compact` (nav top, sidebar) et `detailed` (hero, dashboard).
//
// Stratégie :
//  1. Charge /api/public/weather/settings → décide s'il faut s'afficher.
//  2. Demande la ville via /api/public/weather/ip-locate (Cloudflare + ipwho.is).
//  3. Récupère /api/public/weather/current?lat=&lon=&units=.
//  4. Bouton "📍 Améliorer" → browser geolocation (précis ~10m).
//  5. Auto-refresh toutes les 10 min.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Sun, Moon, Cloud, CloudSun, CloudFog, CloudDrizzle, CloudRain,
         CloudRainWind, CloudSnow, CloudLightning, MapPin, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

// Map de l'icône retournée par le backend vers le composant Lucide.
const ICON_MAP = {
  sun: Sun, moon: Moon, cloud: Cloud, "cloud-sun": CloudSun, "cloud-fog": CloudFog,
  "cloud-drizzle": CloudDrizzle, "cloud-rain": CloudRain,
  "cloud-rain-wind": CloudRainWind, "cloud-snow": CloudSnow,
  "cloud-lightning": CloudLightning,
};

// Couleur d'accent par condition pour ajouter du « peps » visuel.
const ICON_TONE = {
  sun: "text-amber-400 weather-icon-sun",
  moon: "text-slate-200 weather-icon-moon",
  "cloud-sun": "text-amber-300",
  "cloud-rain": "text-sky-300 weather-icon-rain",
  "cloud-rain-wind": "text-sky-200 weather-icon-rain",
  "cloud-drizzle": "text-sky-300 weather-icon-rain",
  "cloud-snow": "text-white",
  "cloud-lightning": "text-yellow-300 weather-icon-storm",
  "cloud-fog": "text-slate-300",
  cloud: "text-slate-300",
};

function detectUnits() {
  // Choisit °F si la langue dominante du navigateur est en-US ; sinon °C.
  if (typeof navigator === "undefined") return "celsius";
  const lang = (navigator.language || "").toLowerCase();
  // En-US/en-LR/en-MM/my (Liberia, Birmanie, USA = Fahrenheit)
  if (lang === "en-us" || lang === "en-lr" || lang === "en-mm" || lang === "my") {
    return "fahrenheit";
  }
  return "celsius";
}

export default function WeatherWidget({
  variant = "compact",     // "compact" | "detailed"
  placement = "public",    // "public" | "portal"
  className = "",
}) {
  const [settings, setSettings] = useState(null);
  const [loc, setLoc] = useState(null);     // {lat, lon, city, country, source}
  const [data, setData] = useState(null);   // weather payload from backend
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [improving, setImproving] = useState(false);
  const [precise, setPrecise] = useState(false);

  const units = useMemo(() => detectUnits(), []);

  // ---- 1. Settings ----
  useEffect(() => {
    let alive = true;
    apiClient.get("/public/weather/settings")
      .then((r) => { if (alive) setSettings(r.data); })
      .catch(() => { if (alive) setSettings({ enabled: false }); });
    return () => { alive = false; };
  }, []);

  // ---- 2. Localisation IP ----
  const loadLocationByIp = useCallback(async () => {
    try {
      const r = await apiClient.get("/public/weather/ip-locate");
      setLoc(r.data);
      setPrecise(false);
      return r.data;
    } catch {
      setError("Impossible de détecter la localisation.");
      return null;
    }
  }, []);

  // ---- 3. Météo ----
  const fetchWeather = useCallback(async (lat, lon) => {
    try {
      const r = await apiClient.get(`/public/weather/current?lat=${lat}&lon=${lon}&units=${units}`);
      setData(r.data);
      setError(null);
    } catch (e) {
      setError(e?.response?.data?.detail || "Erreur météo");
    }
  }, [units]);

  // Initial load: settings → location → weather
  useEffect(() => {
    if (!settings) return;
    if (!settings.enabled) { setLoading(false); return; }
    const placementOk = placement === "public" ? settings.show_public : settings.show_portal;
    if (!placementOk) { setLoading(false); return; }
    let alive = true;
    (async () => {
      const l = await loadLocationByIp();
      if (alive && l && l.lat && l.lon) {
        await fetchWeather(l.lat, l.lon);
      }
      if (alive) setLoading(false);
    })();
    return () => { alive = false; };
  }, [settings, placement, loadLocationByIp, fetchWeather]);

  // Auto-refresh toutes les 10 min.
  useEffect(() => {
    if (!loc?.lat || !loc?.lon) return undefined;
    const id = setInterval(() => fetchWeather(loc.lat, loc.lon), 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [loc, fetchWeather]);

  // ---- 4. Améliorer via GPS browser ----
  const improvePrecision = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return;
    setImproving(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        setLoc((prev) => ({ ...(prev || {}), lat, lon, source: "browser_gps" }));
        setPrecise(true);
        await fetchWeather(lat, lon);
        setImproving(false);
      },
      () => { setImproving(false); },
      { enableHighAccuracy: true, timeout: 6000, maximumAge: 60000 },
    );
  }, [fetchWeather]);

  // ---- Garde-fous d'affichage ----
  if (!settings || !settings.enabled) return null;
  const placementOk = placement === "public" ? settings.show_public : settings.show_portal;
  if (!placementOk) return null;
  if (loading) {
    return (
      <div className={`inline-flex items-center gap-1.5 text-xs text-slate-400 ${className}`} data-testid="weather-loading">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span>Météo…</span>
      </div>
    );
  }
  if (error || !data) {
    return null; // Échec silencieux pour ne pas polluer l'UI publique.
  }

  const IconComp = ICON_MAP[data.icon] || Cloud;
  const tone = ICON_TONE[data.icon] || "text-sky-200";
  const cityLabel = loc?.city || settings.default_city || "—";
  const tempUnit = data.units?.temp || "°C";
  const lang = (typeof navigator !== "undefined" ? navigator.language : "fr").toLowerCase();
  const conditionLabel = lang.startsWith("en") ? data.label_en : data.label_fr;

  if (variant === "compact") {
    return (
      <div
        className={`inline-flex items-center gap-2 rounded-full bg-white/5 ring-1 ring-white/10 px-3 py-1 text-xs text-slate-200 hover:bg-white/10 transition ${className}`}
        title={`${conditionLabel} · ${cityLabel} · Ressenti ${Math.round(data.feels_like)}${tempUnit} · Vent ${Math.round(data.wind_kmh)} km/h · Humidité ${data.humidity_pct}%`}
        data-testid="weather-widget-compact"
      >
        <IconComp className={`h-4 w-4 ${tone}`} />
        <strong className="text-white" data-testid="weather-temp">
          {Math.round(data.temperature)}{tempUnit}
        </strong>
        <span className="hidden sm:inline text-slate-400">·</span>
        <span className="hidden sm:inline text-slate-300 truncate max-w-[120px]" data-testid="weather-city">
          {cityLabel}
        </span>
      </div>
    );
  }

  // === Detailed ===
  return (
    <div
      className={`relative overflow-hidden rounded-2xl ring-1 ring-white/10 bg-gradient-to-br from-sawali-blue/30 via-[#0e1d36]/40 to-[#081226]/60 p-5 sm:p-6 backdrop-blur-md ${className}`}
      data-testid="weather-widget-detailed"
    >
      <div className="absolute -top-6 -right-6 opacity-25 pointer-events-none">
        <IconComp className={`h-32 w-32 ${tone}`} />
      </div>
      <div className="relative flex items-start gap-4">
        <div className={`p-2 rounded-xl bg-white/10 ring-1 ring-white/20`}>
          <IconComp className={`h-10 w-10 ${tone}`} data-testid="weather-icon-detailed" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-display font-bold text-white tabular-nums">
              {Math.round(data.temperature)}<span className="text-2xl">{tempUnit}</span>
            </span>
            <span className="text-sm text-slate-300">
              ressenti <span className="text-white tabular-nums">{Math.round(data.feels_like)}{tempUnit}</span>
            </span>
          </div>
          <p className="text-sm text-slate-200 mt-0.5" data-testid="weather-condition">{conditionLabel}</p>
          <div className="flex items-center gap-1.5 mt-2 text-xs text-slate-400">
            <MapPin className="h-3.5 w-3.5" />
            <span data-testid="weather-detailed-city">
              {cityLabel}
              {loc?.country ? <span className="ml-1 text-slate-500">({loc.country})</span> : null}
            </span>
            {precise && (
              <span className="ml-2 inline-flex items-center rounded-full bg-emerald-500/15 text-emerald-300 px-2 py-0.5 text-[10px]" title="Position GPS précise">
                ✓ GPS
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 mt-3 text-xs">
            <div className="text-slate-400">Vent · <span className="text-slate-200 tabular-nums">{Math.round(data.wind_kmh)} km/h</span></div>
            <div className="text-slate-400">Humidité · <span className="text-slate-200 tabular-nums">{data.humidity_pct}%</span></div>
          </div>
          {!precise && typeof navigator !== "undefined" && navigator.geolocation && (
            <button
              type="button"
              onClick={improvePrecision}
              disabled={improving}
              className="mt-3 inline-flex items-center gap-1.5 text-[11px] text-sawali-blue-light hover:text-white transition disabled:opacity-60"
              data-testid="weather-improve-button"
            >
              {improving ? <Loader2 className="h-3 w-3 animate-spin" /> : <MapPin className="h-3 w-3" />}
              {improving ? "Localisation…" : "📍 Améliorer la précision"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
