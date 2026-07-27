/*
  Notification sound library for WhatsApp inbound alerts.
  - 5 programmatic presets generated via Web Audio API (no assets to ship).
  - 1 "custom" mode that plays an admin-uploaded MP3 via <Audio>.
  - Volume is normalised 0.0 → 1.0 and applied uniformly.

  Public API:
    listPresets()          → [{key, label, description}]
    playSound(key, url?, volume?) → void
    getEffectiveConfig(admin) → resolved {preset, url, volume} respecting
                                localStorage user overrides.
*/

const STORAGE_KEY_PRESET = "sawali_wa_sound_preset";
const STORAGE_KEY_VOLUME = "sawali_wa_sound_volume";

const PRESETS = [
  { key: "bip", label: "Bip (sinusoïde ascendante)", description: "Blip court 880Hz → 1320Hz, discret." },
  { key: "ding", label: "Ding (triangle descendant)", description: "Note claire descendante style desktop." },
  { key: "chime", label: "Chime (accord bell)", description: "Deux notes en accord, plus musical." },
  { key: "alert", label: "Alert (triple beep)", description: "Trois beeps rapides pour urgence." },
  { key: "subtle", label: "Subtle (basse fréquence)", description: "Tonalité feutrée basse fréquence." },
];

export function listPresets() {
  return PRESETS.slice();
}

/* -------------------------------- Presets -------------------------------- */

function bip(ctx, volume) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.type = "sine";
  osc.frequency.setValueAtTime(880, ctx.currentTime);
  osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.18);
  gain.gain.setValueAtTime(volume, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.4);
  osc.start();
  osc.stop(ctx.currentTime + 0.42);
  osc.onended = () => ctx.close();
}

function ding(ctx, volume) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.type = "triangle";
  osc.frequency.setValueAtTime(1400, ctx.currentTime);
  osc.frequency.exponentialRampToValueAtTime(700, ctx.currentTime + 0.45);
  gain.gain.setValueAtTime(volume, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.55);
  osc.start();
  osc.stop(ctx.currentTime + 0.6);
  osc.onended = () => ctx.close();
}

function chime(ctx, volume) {
  // Bell-like two-note chord (Eb + G, offset 40ms)
  const start = ctx.currentTime;
  const tones = [
    { freq: 622, offset: 0 },
    { freq: 784, offset: 0.04 },
  ];
  let closed = 0;
  tones.forEach(({ freq, offset }) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, start + offset);
    gain.gain.setValueAtTime(0.0001, start + offset);
    gain.gain.exponentialRampToValueAtTime(volume, start + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + offset + 0.7);
    osc.start(start + offset);
    osc.stop(start + offset + 0.75);
    osc.onended = () => {
      closed += 1;
      if (closed >= tones.length) ctx.close();
    };
  });
}

function alert(ctx, volume) {
  // Three quick square beeps (urgent feel)
  const start = ctx.currentTime;
  const spacing = 0.12;
  let closed = 0;
  for (let i = 0; i < 3; i += 1) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = "square";
    osc.frequency.setValueAtTime(1000, start + i * spacing);
    gain.gain.setValueAtTime(0.0001, start + i * spacing);
    gain.gain.exponentialRampToValueAtTime(volume * 0.7, start + i * spacing + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + i * spacing + 0.09);
    osc.start(start + i * spacing);
    osc.stop(start + i * spacing + 0.1);
    osc.onended = () => {
      closed += 1;
      if (closed >= 3) ctx.close();
    };
  }
}

function subtle(ctx, volume) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  const filter = ctx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(600, ctx.currentTime);
  osc.connect(filter);
  filter.connect(gain);
  gain.connect(ctx.destination);
  osc.type = "sine";
  osc.frequency.setValueAtTime(440, ctx.currentTime);
  osc.frequency.linearRampToValueAtTime(330, ctx.currentTime + 0.28);
  gain.gain.setValueAtTime(0.0001, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(volume * 0.6, ctx.currentTime + 0.03);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.32);
  osc.start();
  osc.stop(ctx.currentTime + 0.35);
  osc.onended = () => ctx.close();
}

const RENDERERS = { bip, ding, chime, alert, subtle };

/* -------------------------------- Player --------------------------------- */

function playCustomUrl(url, volume) {
  try {
    const audio = new Audio(url);
    audio.volume = Math.max(0, Math.min(1, volume));
    audio.play().catch(() => { /* autoplay blocked until first click — swallow */ });
  } catch { /* swallow */ }
}

export function playSound(presetKey, customUrl, volume = 0.4) {
  const vol = Math.max(0, Math.min(1, Number(volume) || 0.4));
  if (presetKey === "custom" && customUrl) {
    playCustomUrl(customUrl, vol);
    return;
  }
  const renderer = RENDERERS[presetKey] || RENDERERS.bip;
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    renderer(ctx, vol);
  } catch { /* swallow — sound is best effort */ }
}

/* -------------------- Effective config (admin + user override) ------------ */

export function getUserOverridePreset() {
  const v = localStorage.getItem(STORAGE_KEY_PRESET);
  return v && ["bip", "ding", "chime", "alert", "subtle", "custom"].includes(v) ? v : null;
}

export function getUserOverrideVolume() {
  const raw = localStorage.getItem(STORAGE_KEY_VOLUME);
  if (raw == null) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0 || n > 1) return null;
  return n;
}

export function setUserOverridePreset(preset) {
  if (!preset) {
    localStorage.removeItem(STORAGE_KEY_PRESET);
    return;
  }
  localStorage.setItem(STORAGE_KEY_PRESET, preset);
}

export function setUserOverrideVolume(volume) {
  if (volume == null || Number.isNaN(volume)) {
    localStorage.removeItem(STORAGE_KEY_VOLUME);
    return;
  }
  localStorage.setItem(STORAGE_KEY_VOLUME, String(volume));
}

/**
 * Resolve the effective playback config given the tenant admin defaults.
 * @param {Object} adminDefaults - {preset, url, volume} from /me/features
 * @returns {{preset: string, url: string|null, volume: number, adminPreset: string, adminUrl: string|null, adminVolume: number}}
 */
export function getEffectiveConfig(adminDefaults = {}) {
  const adminPreset = adminDefaults.preset || "bip";
  const adminUrl = adminDefaults.url || null;
  const adminVolume = typeof adminDefaults.volume === "number" ? adminDefaults.volume : 0.4;
  const userPreset = getUserOverridePreset();
  const userVolume = getUserOverrideVolume();
  const preset = userPreset || adminPreset;
  const volume = userVolume != null ? userVolume : adminVolume;
  // The URL only makes sense when preset === "custom"; it always comes from admin.
  const url = preset === "custom" ? adminUrl : null;
  return { preset, url, volume, adminPreset, adminUrl, adminVolume };
}
