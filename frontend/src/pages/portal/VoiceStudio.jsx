// =====================================================================
// Iter38r-fix9m — ElevenLabs Voice Cloning + TTS page
// =====================================================================

import React, { useCallback, useEffect, useState, useRef } from "react";
import { Mic, Upload, Trash2, Play, Sparkles, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function VoiceStudio() {
  const [voices, setVoices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [cloneForm, setCloneForm] = useState({ name: "", description: "" });
  const [cloning, setCloning] = useState(false);
  const fileRef = useRef(null);
  const [selectedVoice, setSelectedVoice] = useState("");
  const [ttsText, setTtsText] = useState("");
  const [audioUrl, setAudioUrl] = useState(null);
  const [generating, setGenerating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/ai/voices");
      setVoices(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const submitClone = async (e) => {
    e.preventDefault();
    const f = fileRef.current?.files?.[0];
    if (!cloneForm.name.trim() || !f) {
      toast.error("Nom et fichier audio requis");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      toast.error("Fichier > 10 Mo");
      return;
    }
    setCloning(true);
    try {
      const fd = new FormData();
      fd.append("name", cloneForm.name.trim());
      fd.append("description", cloneForm.description || "");
      fd.append("audio_file", f);
      const r = await apiClient.post("/me/ai/voices/clone", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`Voix « ${r.data.name} » créée`);
      setCloneForm({ name: "", description: "" });
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur clonage");
    } finally { setCloning(false); }
  };

  const removeVoice = async (voiceId) => {
    if (!window.confirm("Supprimer cette voix ? L'action est irréversible côté ElevenLabs.")) return;
    try {
      await apiClient.delete(`/me/ai/voices/${voiceId}`);
      toast.success("Voix supprimée");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const generateTts = async (e) => {
    e.preventDefault();
    if (!selectedVoice || !ttsText.trim()) {
      toast.error("Voix et texte requis");
      return;
    }
    setGenerating(true);
    setAudioUrl(null);
    try {
      const r = await apiClient.post("/me/ai/tts-elevenlabs", {
        voice_id: selectedVoice,
        text: ttsText.trim(),
      });
      setAudioUrl(r.data?.audio_data_url);
      toast.success(`Audio généré (${Math.round((r.data?.size_bytes || 0) / 1024)} Ko)`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur TTS");
    } finally { setGenerating(false); }
  };

  return (
    <div className="space-y-4 p-4" data-testid="voice-studio-page">
      <div className="flex items-center gap-2">
        <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-rose-500 to-orange-500 flex items-center justify-center">
          <Mic className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="font-display font-bold text-slate-900 text-xl inline-flex items-center gap-1">
            Voice Studio <Sparkles className="h-4 w-4 text-rose-500" />
          </h1>
          <p className="text-xs text-slate-500">Clonez votre voix (ElevenLabs Instant Voice Cloning) et générez n'importe quel texte en audio.</p>
        </div>
      </div>

      {/* Voice cloning form */}
      <form onSubmit={submitClone} className="rounded-xl ring-1 ring-rose-200 bg-gradient-to-br from-rose-50/40 to-white p-4 space-y-3" data-testid="voice-clone-form">
        <h2 className="font-display font-semibold text-sm text-slate-800 inline-flex items-center gap-1">
          <Upload className="h-4 w-4 text-rose-600" /> Cloner une nouvelle voix
        </h2>
        <p className="text-xs text-slate-500">Un échantillon de 30 sec à 2 min suffit. Fichier MP3 ou WAV, max 10 Mo. Voix claire, sans bruit de fond.</p>
        <div className="grid sm:grid-cols-2 gap-3">
          <input
            type="text"
            value={cloneForm.name}
            onChange={(e) => setCloneForm({ ...cloneForm, name: e.target.value })}
            placeholder="Nom de la voix (ex: Voix Jean-François)"
            className="text-sm rounded-lg border border-slate-300 px-3 py-2"
            data-testid="voice-clone-name"
            required
          />
          <input
            type="text"
            value={cloneForm.description}
            onChange={(e) => setCloneForm({ ...cloneForm, description: e.target.value })}
            placeholder="Description (optionnel)"
            className="text-sm rounded-lg border border-slate-300 px-3 py-2"
            data-testid="voice-clone-description"
          />
        </div>
        <input
          type="file"
          ref={fileRef}
          accept="audio/*"
          className="block w-full text-sm text-slate-600 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-rose-100 file:text-rose-700 hover:file:bg-rose-200 cursor-pointer"
          data-testid="voice-clone-file"
          required
        />
        <button
          type="submit"
          disabled={cloning}
          className="rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50 inline-flex items-center gap-2"
          data-testid="voice-clone-submit"
        >
          <Upload className="h-4 w-4" /> {cloning ? "Clonage en cours…" : "Cloner la voix"}
        </button>
      </form>

      {/* Voices list */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4" data-testid="voice-list">
        <h2 className="font-display font-semibold text-sm text-slate-800 mb-3 inline-flex items-center gap-1">
          <Volume2 className="h-4 w-4" /> Mes voix ({voices.length})
        </h2>
        {loading ? (
          <p className="text-center text-slate-400 italic py-4">Chargement…</p>
        ) : voices.length === 0 ? (
          <p className="text-center text-slate-400 italic py-4">Aucune voix clonée pour le moment.</p>
        ) : (
          <ul className="space-y-2">
            {voices.map((v) => (
              <li key={v.id} className="flex items-center justify-between gap-2 rounded-lg ring-1 ring-slate-100 px-3 py-2 hover:bg-slate-50" data-testid={`voice-row-${v.voice_id}`}>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-sm text-slate-800 truncate">{v.name}</div>
                  <div className="text-[11px] text-slate-500 truncate">{v.description || v.voice_id}</div>
                </div>
                <div className="inline-flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setSelectedVoice(v.voice_id)}
                    className="text-[11px] inline-flex items-center gap-1 rounded ring-1 ring-slate-300 hover:bg-slate-100 px-2 py-1 text-slate-700"
                    data-testid={`voice-select-${v.voice_id}`}
                  >
                    Utiliser
                  </button>
                  <button
                    type="button"
                    onClick={() => removeVoice(v.voice_id)}
                    className="text-rose-500 hover:text-rose-700 p-1"
                    title="Supprimer"
                    data-testid={`voice-delete-${v.voice_id}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* TTS form */}
      <form onSubmit={generateTts} className="rounded-xl ring-1 ring-orange-200 bg-gradient-to-br from-orange-50/40 to-white p-4 space-y-3" data-testid="voice-tts-form">
        <h2 className="font-display font-semibold text-sm text-slate-800 inline-flex items-center gap-1">
          <Play className="h-4 w-4 text-orange-600" /> Générer un audio
        </h2>
        <select
          value={selectedVoice}
          onChange={(e) => setSelectedVoice(e.target.value)}
          className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2 bg-white"
          data-testid="voice-tts-select"
          required
        >
          <option value="">-- Choisir une voix --</option>
          {voices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.name}</option>)}
        </select>
        <textarea
          value={ttsText}
          onChange={(e) => setTtsText(e.target.value)}
          placeholder="Texte à lire (max 5000 caractères)…"
          rows={4}
          maxLength={5000}
          className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2 resize-y"
          data-testid="voice-tts-text"
          required
        />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={generating || !selectedVoice}
            className="rounded-lg bg-orange-600 hover:bg-orange-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50 inline-flex items-center gap-2"
            data-testid="voice-tts-submit"
          >
            <Play className="h-4 w-4" /> {generating ? "Génération…" : "Générer"}
          </button>
          {audioUrl && (
            <audio controls src={audioUrl} className="flex-1" data-testid="voice-tts-audio" />
          )}
        </div>
      </form>
    </div>
  );
}
