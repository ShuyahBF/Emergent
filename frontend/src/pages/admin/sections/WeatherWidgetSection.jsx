// =====================================================================
// Iter43-fix20 (2026-06) — Weather widget admin section.
// Toggle global + visibilité (public/portail) + ville par défaut.
// Données via Open-Meteo (gratuit, sans clé API).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Save, CloudSun, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TITLE = "🌤️ Widget Météo (Open-Meteo)";

const WeatherWidgetSection = () => {
  const [form, setForm] = useState({
    weather_widget_enabled: false,
    weather_widget_show_public: true,
    weather_widget_show_portal: true,
    weather_widget_default_city: "",
    weather_widget_default_country: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/settings");
      const s = r.data || {};
      setForm({
        weather_widget_enabled: Boolean(s.weather_widget_enabled),
        weather_widget_show_public: s.weather_widget_show_public !== false,
        weather_widget_show_portal: s.weather_widget_show_portal !== false,
        weather_widget_default_city: s.weather_widget_default_city || "",
        weather_widget_default_country: s.weather_widget_default_country || "",
      });
    } catch {
      toast.error("Erreur chargement paramètres météo");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/settings", {
        weather_widget_enabled: !!form.weather_widget_enabled,
        weather_widget_show_public: !!form.weather_widget_show_public,
        weather_widget_show_portal: !!form.weather_widget_show_portal,
        weather_widget_default_city: (form.weather_widget_default_city || "").trim(),
        weather_widget_default_country: (form.weather_widget_default_country || "").trim().toUpperCase(),
      });
      toast.success("Paramètres météo enregistrés");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const testPreview = async () => {
    setPreviewing(true);
    setPreview(null);
    try {
      const city = (form.weather_widget_default_city || "Ouagadougou").trim();
      const geo = await apiClient.get(`/public/weather/geocode?q=${encodeURIComponent(city)}`);
      const { lat, lon } = geo.data || {};
      if (lat == null || lon == null) throw new Error("Ville introuvable");
      const w = await apiClient.get(`/public/weather/current?lat=${lat}&lon=${lon}&units=celsius`);
      setPreview({ city: geo.data.name, country: geo.data.country, ...w.data });
      toast.success("Données météo récupérées");
    } catch (e) {
      toast.error(e?.response?.data?.detail || e?.message || "Erreur preview");
    } finally {
      setPreviewing(false);
    }
  };

  if (loading) return null;

  return (
    <div id="s-weather-widget" className="scroll-mt-32" data-settings-anchor="s-weather-widget">
      <div className="rounded-xl border-2 border-sky-300 bg-sky-50/40 p-6 space-y-4" data-testid="admin-weather-widget">
        <div className="flex items-center gap-2">
          <CloudSun className="h-5 w-5 text-sky-700" />
          <h2 className="font-display font-semibold">{TITLE}</h2>
        </div>
        <p className="text-sm text-slate-600">
          Affiche un widget météo en temps réel (température, ressenti, humidité, vent, condition)
          basé sur la <strong>ville détectée du visiteur</strong> via son adresse IP (Cloudflare puis
          ipwho.is). Source des données : <a href="https://open-meteo.com" target="_blank" rel="noreferrer" className="text-sky-700 underline">Open-Meteo</a>{" "}
          — <strong>100% gratuit, sans clé API</strong>, données conformes RGPD.
        </p>

        {/* Toggles */}
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 cursor-pointer hover:border-sky-400" data-testid="weather-toggle-enabled">
            <input
              type="checkbox"
              checked={form.weather_widget_enabled}
              onChange={(e) => setForm((f) => ({ ...f, weather_widget_enabled: e.target.checked }))}
              className="mt-0.5 h-4 w-4 accent-sky-600"
            />
            <span>
              <span className="block font-semibold text-slate-800">Activer le widget météo</span>
              <span className="block text-xs text-slate-500">Master toggle — désactive tout en un clic.</span>
            </span>
          </label>
          <label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 cursor-pointer hover:border-sky-400" data-testid="weather-toggle-public">
            <input
              type="checkbox"
              checked={form.weather_widget_show_public}
              disabled={!form.weather_widget_enabled}
              onChange={(e) => setForm((f) => ({ ...f, weather_widget_show_public: e.target.checked }))}
              className="mt-0.5 h-4 w-4 accent-sky-600 disabled:opacity-40"
            />
            <span>
              <span className="block font-semibold text-slate-800">Afficher sur le site public</span>
              <span className="block text-xs text-slate-500">Compact en nav top + détaillé en hero de la home.</span>
            </span>
          </label>
          <label className="flex items-start gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 cursor-pointer hover:border-sky-400" data-testid="weather-toggle-portal">
            <input
              type="checkbox"
              checked={form.weather_widget_show_portal}
              disabled={!form.weather_widget_enabled}
              onChange={(e) => setForm((f) => ({ ...f, weather_widget_show_portal: e.target.checked }))}
              className="mt-0.5 h-4 w-4 accent-sky-600 disabled:opacity-40"
            />
            <span>
              <span className="block font-semibold text-slate-800">Afficher dans le portail client</span>
              <span className="block text-xs text-slate-500">Compact dans la sidebar + détaillé sur le dashboard.</span>
            </span>
          </label>
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3">
            <label className="block text-xs font-semibold text-slate-700 mb-1">Unités</label>
            <p className="text-xs text-slate-600">
              Auto-détecté selon la langue du navigateur visiteur : <strong>°C</strong> par défaut,{" "}
              <strong>°F</strong> si la langue préférée est <code>en-US</code>.
            </p>
          </div>
        </div>

        {/* Ville fallback */}
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Ville par défaut (fallback)</label>
            <input
              type="text"
              value={form.weather_widget_default_city}
              onChange={(e) => setForm((f) => ({ ...f, weather_widget_default_city: e.target.value }))}
              placeholder="Ouagadougou"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              data-testid="weather-default-city"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Utilisée si la détection IP échoue (ex. visiteurs avec VPN ou IP privée).
            </p>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Code pays (ISO 2)</label>
            <input
              type="text"
              maxLength={2}
              value={form.weather_widget_default_country}
              onChange={(e) => setForm((f) => ({ ...f, weather_widget_default_country: e.target.value.toUpperCase() }))}
              placeholder="BF"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm uppercase focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              data-testid="weather-default-country"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Ex. <code>BF</code> = Burkina Faso, <code>FR</code> = France, <code>CI</code> = Côte d'Ivoire.
            </p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2 pt-2">
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-sky-600 hover:bg-sky-700 text-white px-4 py-2 text-sm font-semibold disabled:opacity-50"
            data-testid="weather-save-btn"
          >
            <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
          <button
            onClick={testPreview}
            disabled={previewing}
            type="button"
            className="inline-flex items-center gap-2 rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-50 text-slate-700 px-4 py-2 text-sm disabled:opacity-50"
            data-testid="weather-preview-btn"
          >
            <RefreshCw className={`h-4 w-4 ${previewing ? "animate-spin" : ""}`} />
            Tester avec la ville par défaut
          </button>
        </div>

        {preview && (
          <div className="rounded-lg ring-1 ring-emerald-300 bg-emerald-50/60 p-3 text-sm space-y-1" data-testid="weather-preview-result">
            <p className="font-semibold text-emerald-800">
              ✓ {preview.city}{preview.country ? ` (${preview.country})` : ""} — {preview.label_fr}
            </p>
            <p className="text-emerald-900">
              <strong>{Math.round(preview.temperature)}°C</strong>{" "}
              · ressenti {Math.round(preview.feels_like)}°C
              · humidité {preview.humidity_pct}%
              · vent {Math.round(preview.wind_kmh)} km/h
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default WeatherWidgetSection;
