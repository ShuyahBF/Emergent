/*
 * Iter38k — Portal → Générateur d'Images.
 * Real implementation using Gemini Nano Banana (via /api/me/ai/generate-image
 * and /api/me/ai/edit-image). Includes history gallery and download.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { Sparkles, Image as ImageIcon, Video, Wand2, Loader2, Download, RefreshCw, Upload, X, History } from "lucide-react";
import { toast } from "sonner";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

export default function MediaGenerator() {
  const [prompt, setPrompt] = useState("");
  const [aspect, setAspect] = useState("square");
  const [iconMode, setIconMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState(null); // {url}
  const [history, setHistory] = useState([]);
  const [refFile, setRefFile] = useState(null);
  const refInputRef = useRef(null);

  const loadHistory = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/ai/history?limit=24");
      setHistory(r.data?.items || []);
    } catch { /* noop */ }
  }, []);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const generate = async () => {
    if (!prompt.trim()) { toast.warning("Saisissez une description (prompt)"); return; }
    setBusy(true); setCurrent(null);
    try {
      let r;
      if (refFile) {
        const form = new FormData();
        form.append("prompt", prompt.trim());
        form.append("file", refFile);
        r = await apiClient.post("/me/ai/edit-image", form, { headers: { "Content-Type": "multipart/form-data" } });
      } else {
        r = await apiClient.post("/me/ai/generate-image", {
          prompt: prompt.trim(), aspect, icon_mode: iconMode,
        });
      }
      setCurrent({ url: r.data?.url });
      toast.success("Image générée !");
      loadHistory();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Génération échouée");
    } finally { setBusy(false); }
  };

  const fullUrl = (u) => (u?.startsWith("http") ? u : `${BACKEND}${u || ""}`);

  const pickRef = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) { toast.error("Max 8 Mo"); return; }
    setRefFile(f);
  };

  return (
    <div className="space-y-6" data-testid="media-generator-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Création de contenu</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <Wand2 className="h-5 w-5 text-sawali-blue" /> Générateur d'Images IA
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Décrivez ce que vous voulez ; <strong>Gemini Nano Banana</strong> crée l'image pour vous en quelques secondes.
          Téléversez une image de référence pour la <em>retravailler</em>.
        </p>
      </div>

      {/* Composer */}
      <div className="grid lg:grid-cols-[1fr_400px] gap-6">
        <div className="bg-white rounded-2xl border border-slate-200 p-5 space-y-3">
          <label className="text-xs text-slate-500">Description (prompt)</label>
          <textarea
            value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder="Ex: Une boutique élégante de vêtements africains avec mannequins, style photographie professionnelle, lumière chaude…"
            rows={5}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-sawali-blue focus:outline-none"
            data-testid="mediagen-prompt"
          />

          <div className="flex flex-wrap gap-3 items-center">
            <label className="text-xs text-slate-500">Format :</label>
            <div className="flex rounded-lg border border-slate-300 overflow-hidden text-xs">
              {[["square", "Carré"], ["portrait", "Portrait"], ["landscape", "Paysage"]].map(([v, l]) => (
                <button key={v} onClick={() => setAspect(v)}
                  className={`px-3 py-1.5 ${aspect === v ? "bg-sawali-blue text-white" : "bg-white hover:bg-slate-50 text-slate-700"}`}
                  data-testid={`mediagen-aspect-${v}`}>{l}</button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" checked={iconMode} onChange={(e) => setIconMode(e.target.checked)} data-testid="mediagen-iconmode" />
              Mode icône / pictogramme
            </label>
          </div>

          {/* Reference image */}
          <div className="pt-2 border-t border-slate-100">
            <label className="text-xs text-slate-500">Image de référence (optionnel — pour image-to-image)</label>
            <div className="flex items-center gap-3 mt-1">
              <input type="file" accept="image/*" onChange={pickRef} ref={refInputRef} className="hidden" data-testid="mediagen-ref-input" />
              <button onClick={() => refInputRef.current?.click()} className="inline-flex items-center gap-1 text-xs px-2.5 py-1 bg-slate-100 hover:bg-slate-200 rounded">
                <Upload className="h-3 w-3" /> {refFile ? "Remplacer" : "Téléverser PNG/JPG"}
              </button>
              {refFile && (
                <span className="inline-flex items-center gap-1 text-xs bg-violet-50 text-violet-700 px-2 py-1 rounded">
                  {refFile.name.slice(0, 30)}
                  <button onClick={() => { setRefFile(null); if (refInputRef.current) refInputRef.current.value = ""; }}>
                    <X className="h-3 w-3" />
                  </button>
                </span>
              )}
            </div>
          </div>

          <button onClick={generate} disabled={busy || !prompt.trim()}
            className="w-full inline-flex items-center justify-center gap-2 bg-gradient-to-r from-violet-600 to-pink-600 hover:opacity-90 disabled:opacity-50 text-white px-4 py-3 rounded-lg font-medium"
            data-testid="mediagen-generate-btn">
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
            {busy ? "Génération… (5-10 s)" : "Générer l'image"}
          </button>
        </div>

        {/* Preview */}
        <div className="bg-slate-100 rounded-2xl flex items-center justify-center min-h-[300px] overflow-hidden ring-1 ring-slate-200" data-testid="mediagen-preview">
          {busy ? (
            <div className="text-center text-slate-500">
              <Loader2 className="h-10 w-10 animate-spin mx-auto mb-2 text-violet-500" />
              <p className="text-xs">Nano Banana au travail…</p>
            </div>
          ) : current ? (
            <div className="relative w-full h-full">
              <img src={fullUrl(current.url)} alt="Generated" className="w-full h-full object-contain" data-testid="mediagen-current-img" />
              <a href={fullUrl(current.url)} download className="absolute bottom-3 right-3 inline-flex items-center gap-1 bg-white/90 hover:bg-white text-slate-700 px-3 py-1.5 rounded-lg text-xs shadow">
                <Download className="h-3.5 w-3.5" /> Télécharger
              </a>
            </div>
          ) : (
            <div className="text-center text-slate-400 px-4">
              <ImageIcon className="h-12 w-12 mx-auto mb-2" />
              <p className="text-sm">L'image générée apparaîtra ici</p>
            </div>
          )}
        </div>
      </div>

      {/* Video placeholder — Sora 2 plus tard */}
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-xs text-slate-500">
        <Video className="h-4 w-4 inline mr-1 text-slate-400" />
        Génération <strong>vidéo</strong> (Sora 2) à venir dans une prochaine itération.
      </div>

      {/* History */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-1">
            <History className="h-4 w-4" /> Historique récent ({history.length})
          </h2>
          <button onClick={loadHistory} className="text-xs text-violet-600 hover:underline inline-flex items-center gap-1">
            <RefreshCw className="h-3 w-3" /> Actualiser
          </button>
        </div>
        {history.length === 0 ? (
          <p className="text-xs text-slate-400 italic">Aucune image générée pour le moment.</p>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
            {history.map((h) => (
              <button key={h.id} onClick={() => setCurrent({ url: h.url })}
                title={h.prompt} className="aspect-square overflow-hidden rounded-lg ring-1 ring-slate-200 bg-slate-100 hover:ring-2 hover:ring-violet-500 transition"
                data-testid={`mediagen-hist-${h.id}`}>
                <img src={fullUrl(h.url)} alt={h.prompt} className="w-full h-full object-cover" loading="lazy" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
