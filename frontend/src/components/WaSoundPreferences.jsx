/*
 * User-level override for the WhatsApp inbound notification sound.
 * The admin picks a tenant default (see WaNotificationSoundSection.jsx); each
 * user can pick a different preset and volume for their own browser (values
 * live in localStorage — no backend state).
 *
 * Rendered as a compact "Settings" chip below the desktop/sound toggles in
 * PortalLayout. Opens an inline panel with the preset list, a volume slider,
 * a Test button and a Reset link.
 */
import React, { useEffect, useRef, useState } from "react";
import { Settings2, Play, RotateCcw } from "lucide-react";
import {
  listPresets,
  playSound,
  getEffectiveConfig,
  setUserOverridePreset,
  setUserOverrideVolume,
  getUserOverridePreset,
  getUserOverrideVolume,
} from "@/lib/notificationSounds";

const PRESETS = listPresets();

export default function WaSoundPreferences({ adminDefaults, disabled, onChange }) {
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("bip");
  const [volume, setVolume] = useState(0.4);
  const [userOverridePreset, setUOP] = useState(null);
  const [userOverrideVolume, setUOV] = useState(null);
  const rootRef = useRef(null);

  useEffect(() => {
    const eff = getEffectiveConfig(adminDefaults || {});
    setPreset(eff.preset);
    setVolume(eff.volume);
    setUOP(getUserOverridePreset());
    setUOV(getUserOverrideVolume());
  }, [adminDefaults, open]);

  // Close on outside click
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const applyPreset = (key) => {
    setPreset(key);
    setUserOverridePreset(key);
    setUOP(key);
    if (onChange) onChange();
  };

  const applyVolume = (v) => {
    setVolume(v);
    setUserOverrideVolume(v);
    setUOV(v);
    if (onChange) onChange();
  };

  const reset = () => {
    setUserOverridePreset(null);
    setUserOverrideVolume(null);
    const eff = getEffectiveConfig(adminDefaults || {});
    setPreset(eff.preset);
    setVolume(eff.volume);
    setUOP(null);
    setUOV(null);
    if (onChange) onChange();
  };

  const test = () => {
    playSound(preset, adminDefaults?.url || null, volume);
  };

  if (disabled) return null;

  const hasOverride = userOverridePreset != null || userOverrideVolume != null;

  return (
    <div ref={rootRef} className="relative" data-testid="wa-sound-prefs-root">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`w-full inline-flex items-center justify-center gap-1 text-[10px] rounded px-1.5 py-1 ring-1 transition-colors ${
          hasOverride
            ? "bg-purple-500/20 text-purple-200 ring-purple-400/40"
            : "bg-white/5 text-slate-400 ring-white/10 hover:bg-white/10"
        }`}
        data-testid="wa-sound-prefs-toggle"
        title="Personnaliser mon son WhatsApp"
      >
        <Settings2 className="h-3 w-3" />
        {hasOverride ? "Perso" : "Préférences son"}
      </button>

      {open && (
        <div
          className="absolute z-30 bottom-full mb-2 left-0 right-0 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl p-3 space-y-2"
          data-testid="wa-sound-prefs-panel"
        >
          <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
            Mon son de notification
          </p>
          <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => applyPreset(p.key)}
                className={`w-full text-left text-[11px] px-2 py-1.5 rounded ring-1 transition-colors ${
                  preset === p.key
                    ? "bg-amber-500/30 text-amber-100 ring-amber-400/50"
                    : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"
                }`}
                data-testid={`wa-sound-prefs-preset-${p.key}`}
              >
                {p.label}
              </button>
            ))}
            {adminDefaults?.url && (
              <button
                type="button"
                onClick={() => applyPreset("custom")}
                className={`w-full text-left text-[11px] px-2 py-1.5 rounded ring-1 transition-colors ${
                  preset === "custom"
                    ? "bg-purple-500/30 text-purple-100 ring-purple-400/50"
                    : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"
                }`}
                data-testid="wa-sound-prefs-preset-custom"
              >
                Personnalisé (choix admin)
              </button>
            )}
          </div>
          <div className="pt-2 border-t border-slate-700">
            <label
              htmlFor="wa-sound-prefs-volume"
              className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold flex justify-between items-center"
            >
              <span>Volume</span>
              <span className="tabular-nums text-slate-300">{Math.round(volume * 100)}%</span>
            </label>
            <input
              id="wa-sound-prefs-volume"
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={volume}
              onChange={(e) => applyVolume(Number(e.target.value))}
              className="w-full accent-amber-500"
              data-testid="wa-sound-prefs-volume"
            />
          </div>
          <div className="flex gap-1 pt-2 border-t border-slate-700">
            <button
              type="button"
              onClick={test}
              className="flex-1 inline-flex items-center justify-center gap-1 text-[10px] rounded px-2 py-1.5 bg-slate-700 hover:bg-slate-600 text-white"
              data-testid="wa-sound-prefs-test"
            >
              <Play className="h-3 w-3" /> Tester
            </button>
            <button
              type="button"
              onClick={reset}
              disabled={!hasOverride}
              className="flex-1 inline-flex items-center justify-center gap-1 text-[10px] rounded px-2 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="wa-sound-prefs-reset"
              title="Utiliser le son défini par l'administrateur"
            >
              <RotateCcw className="h-3 w-3" /> Défaut admin
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
