/*
 * Admin section — Configurable WhatsApp inbound notification sound.
 * Lets admins choose a preset, upload a custom MP3, adjust the volume,
 * and test the resulting sound live.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Bell, Loader2, Play, Upload, Save, Volume2 } from "lucide-react";
import { listPresets, playSound } from "@/lib/notificationSounds";

const PRESETS = listPresets();

export default function WaNotificationSoundSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [config, setConfig] = useState({ preset: "bip", url: null, volume: 0.4 });
  const [dirty, setDirty] = useState(false);
  const fileInputRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/notification-sounds/config");
      setConfig({
        preset: r.data?.preset || "bip",
        url: r.data?.url || null,
        volume: typeof r.data?.volume === "number" ? r.data.volume : 0.4,
      });
      setDirty(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger la config du son");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const chooseFile = () => fileInputRef.current?.click();

  const onFileSelected = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 500 * 1024) {
      toast.error(`Fichier trop volumineux (max 500 KB, actuel : ${Math.round(file.size / 1024)} KB)`);
      return;
    }
    if (!file.type.startsWith("audio/")) {
      toast.error("Le fichier doit être un audio (MP3, WAV, OGG…)");
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const r = await apiClient.post(
        "/admin/notification-sounds/upload",
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      setConfig((c) => ({ ...c, preset: "custom", url: r.data?.url || null }));
      setDirty(false);  // upload already persisted preset + url server-side
      toast.success(`Son personnalisé enregistré (${Math.round((r.data?.size || 0) / 1024)} KB)`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de l'envoi du fichier");
    } finally {
      setUploading(false);
    }
  };

  const onPresetChange = (key) => {
    setConfig((c) => ({ ...c, preset: key }));
    setDirty(true);
  };

  const onVolumeChange = (v) => {
    setConfig((c) => ({ ...c, volume: v }));
    setDirty(true);
  };

  const testCurrent = () => {
    playSound(config.preset, config.url, config.volume);
  };

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/notification-sounds/config", {
        preset: config.preset,
        volume: config.volume,
      });
      setDirty(false);
      toast.success("Son de notification sauvegardé");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section
      className="bg-white rounded-2xl border border-slate-200 p-6 space-y-4"
      data-testid="wa-notification-sound-section"
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-amber-100 flex items-center justify-center shrink-0">
          <Bell className="h-5 w-5 text-amber-700" />
        </div>
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-800">
            Son de notification WhatsApp (nouveau message entrant)
          </h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Choisissez la tonalité jouée lorsqu&apos;un nouveau message WhatsApp arrive. Cette valeur est
            un défaut pour tout le tenant ; chaque utilisateur peut ensuite l&apos;ajuster depuis son
            profil (préférence stockée localement).
          </p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm py-3">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
        </div>
      ) : (
        <>
          {/* Preset chooser */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-2 uppercase tracking-wider">
              Tonalité par défaut
            </label>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => onPresetChange(p.key)}
                  className={`text-left px-3 py-2 rounded-lg ring-1 transition ${
                    config.preset === p.key
                      ? "bg-amber-600 text-white ring-amber-700"
                      : "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"
                  }`}
                  data-testid={`wa-sound-preset-${p.key}`}
                >
                  <div className="text-sm font-medium">{p.label}</div>
                  <div className={`text-[11px] ${config.preset === p.key ? "text-amber-100" : "text-slate-500"}`}>
                    {p.description}
                  </div>
                </button>
              ))}
              {/* Custom card (only enabled when a URL has been uploaded) */}
              <button
                type="button"
                onClick={() => config.url && onPresetChange("custom")}
                disabled={!config.url}
                className={`text-left px-3 py-2 rounded-lg ring-1 transition ${
                  config.preset === "custom"
                    ? "bg-purple-600 text-white ring-purple-700"
                    : config.url
                      ? "bg-white text-slate-700 ring-slate-300 hover:bg-slate-50"
                      : "bg-slate-50 text-slate-400 ring-slate-200 cursor-not-allowed"
                }`}
                data-testid="wa-sound-preset-custom"
              >
                <div className="text-sm font-medium">Personnalisé (MP3 chargé)</div>
                <div className={`text-[11px] truncate ${config.preset === "custom" ? "text-purple-100" : "text-slate-500"}`}>
                  {config.url ? config.url : "Aucun fichier chargé — utilisez le bouton ci-dessous."}
                </div>
              </button>
            </div>
          </div>

          {/* Upload custom */}
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-3 space-y-2">
            <div className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
              Fichier personnalisé (MP3, WAV, OGG…) — max 500 KB
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*"
                onChange={onFileSelected}
                className="hidden"
                data-testid="wa-sound-upload-input"
              />
              <button
                type="button"
                onClick={chooseFile}
                disabled={uploading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-sm disabled:opacity-50"
                data-testid="wa-sound-upload-btn"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {uploading ? "Envoi…" : "Choisir un fichier"}
              </button>
              {config.url && (
                <a
                  href={config.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-purple-700 hover:underline"
                  data-testid="wa-sound-custom-open"
                >
                  Écouter le fichier chargé ↗
                </a>
              )}
            </div>
          </div>

          {/* Volume slider */}
          <div>
            <label
              htmlFor="wa-sound-volume"
              className="flex items-center gap-2 text-xs font-semibold text-slate-700 mb-2 uppercase tracking-wider"
            >
              <Volume2 className="h-4 w-4" /> Volume par défaut : {Math.round(config.volume * 100)}%
            </label>
            <input
              id="wa-sound-volume"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={config.volume}
              onChange={(e) => onVolumeChange(Number(e.target.value))}
              className="w-full accent-amber-600"
              data-testid="wa-sound-volume-slider"
            />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-2 border-t border-slate-200">
            <button
              type="button"
              onClick={testCurrent}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-900 text-white text-sm"
              data-testid="wa-sound-test-btn"
            >
              <Play className="h-4 w-4" /> Tester le son
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving || !dirty}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50"
              data-testid="wa-sound-save-btn"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Enregistrer
            </button>
            {dirty && !saving && (
              <span className="text-xs text-amber-600 font-medium">Modifications non enregistrées</span>
            )}
          </div>
        </>
      )}
    </section>
  );
}
