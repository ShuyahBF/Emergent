/*
 * Iter38k — Portal → Générateur d'Images.
 * Real implementation using Gemini Nano Banana (via /api/me/ai/generate-image
 * and /api/me/ai/edit-image). Includes history gallery and download.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { Sparkles, Image as ImageIcon, Video, Wand2, Loader2, Download, RefreshCw, Upload, X, History, Clapperboard, Lock } from "lucide-react";
import { toast } from "sonner";
import { LocalMediaImporter } from "@/components/LocalMediaImporter";

const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

// Iter38r-fix8b — Friendly byte formatter for the "X protégés" badge.
function fmtBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} Ko`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} Go`;
}

export default function MediaGenerator() {
  const [tab, setTab] = useState("image"); // 'image' | 'video'
  const [prompt, setPrompt] = useState("");
  const [aspect, setAspect] = useState("square");
  const [iconMode, setIconMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [current, setCurrent] = useState(null); // {url, kind}
  const [history, setHistory] = useState([]);
  const [storageStats, setStorageStats] = useState({ files: 0, bytes: 0 });
  const [refFile, setRefFile] = useState(null);
  const refInputRef = useRef(null);
  // Video state
  // Iter38r-fix9m — Image model selector (Nano Banana, GPT Image 1, Imagen 4)
  const [imageModel, setImageModel] = useState("nano-banana");
  const [videoDuration, setVideoDuration] = useState(4);
  const [videoSize, setVideoSize] = useState("1280x720");
  const [videoModel, setVideoModel] = useState("sora-2");
  // Iter38o — Feature flags from /me/features
  const [features, setFeatures] = useState(null);
  useEffect(() => {
    apiClient.get("/me/features")
      .then((r) => setFeatures(r.data?.features || {}))
      .catch(() => setFeatures({}));
  }, []);
  const aiImageEnabled = features === null ? true : !!features.ai_image_gen;
  const aiVideoEnabled = features === null ? true : !!features.ai_video_gen;
  // Auto-switch to a visible tab if current one is disabled
  useEffect(() => {
    if (features === null) return;
    if (tab === "image" && !aiImageEnabled && aiVideoEnabled) setTab("video");
    else if (tab === "video" && !aiVideoEnabled && aiImageEnabled) setTab("image");
  }, [features, aiImageEnabled, aiVideoEnabled, tab]);

  const loadHistory = useCallback(async () => {
    try {
      const r = await apiClient.get("/me/ai/history?limit=24");
      setHistory(r.data?.items || []);
      setStorageStats(r.data?.storage_stats || { files: 0, bytes: 0 });
    } catch { /* noop */ }
  }, []);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  const generate = async () => {
    if (!prompt.trim()) { toast.warning("Saisissez une description (prompt)"); return; }
    setBusy(true); setCurrent(null);
    try {
      let r;
      if (tab === "video") {
        if (videoModel === "veo-3.1") {
          r = await apiClient.post("/me/ai/generate-video-veo", {
            prompt: prompt.trim(), resolution: videoSize.split("x")[1] === "1080" ? "1080p" : "720p",
          });
          const jobId = r.data?.job_id;
          toast.info("Veo 3.1 — vidéo en cours de génération (peut prendre 2-5 min)…");
          // Poll every 10s up to 6 minutes
          const start = Date.now();
          let final = null;
          while (Date.now() - start < 360000) {
            await new Promise((res) => setTimeout(res, 10000));
            const p = await apiClient.get(`/me/ai/generate-video-veo/${jobId}`);
            if (p.data?.status === "completed" && p.data?.video_uri) {
              final = p.data.video_uri;
              break;
            }
            if (p.data?.status === "failed") {
              throw new Error(p.data?.error || "Veo: échec");
            }
          }
          if (!final) throw new Error("Timeout Veo (6 min)");
          setCurrent({ url: final, kind: "video" });
          toast.success("Vidéo Veo 3.1 générée !");
        } else {
          r = await apiClient.post("/me/ai/generate-video", {
            prompt: prompt.trim(), duration: videoDuration, size: videoSize, model: videoModel,
          }, { timeout: 900000 });
          setCurrent({ url: r.data?.url, kind: "video" });
          toast.success("Vidéo générée !");
        }
      } else if (refFile) {
        const form = new FormData();
        form.append("prompt", prompt.trim());
        form.append("file", refFile);
        r = await apiClient.post("/me/ai/edit-image", form, { headers: { "Content-Type": "multipart/form-data" } });
        setCurrent({ url: r.data?.url, kind: "image" });
        toast.success("Image générée !");
      } else {
        // Iter38r-fix9m — Image model branch: Imagen 4 vs Nano Banana
        if (imageModel === "imagen-4") {
          r = await apiClient.post("/me/ai/generate-image-imagen", {
            prompt: prompt.trim(),
            aspect_ratio: aspect === "1:1" ? "1:1" : aspect === "16:9" ? "16:9" : aspect === "9:16" ? "9:16" : "1:1",
          });
          const url = r.data?.images?.[0];
          setCurrent({ url, kind: "image" });
          toast.success("Image Imagen 4 générée !");
        } else {
          r = await apiClient.post("/me/ai/generate-image", {
            prompt: prompt.trim(), aspect, icon_mode: iconMode,
          });
          setCurrent({ url: r.data?.url, kind: "image" });
          toast.success("Image générée !");
        }
      }
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
          Décrivez ce que vous voulez ; <strong>Gemini Nano Banana</strong> crée l'image ou <strong>Sora 2</strong> crée la vidéo en quelques secondes.
        </p>
      </div>

      {/* Tabs image / video */}
      {features !== null && !aiImageEnabled && !aiVideoEnabled ? (
        <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-6 text-center" data-testid="mediagen-feature-disabled">
          <Wand2 className="h-10 w-10 text-amber-600 mx-auto mb-2" />
          <p className="text-sm text-amber-900 font-semibold">Génération IA désactivée pour ce client.</p>
          <p className="text-xs text-amber-700 mt-1">
            Contactez votre administrateur pour activer "Génération d'Image IA" ou "Génération de Vidéo IA"
            dans <em>SMART Communications</em>.
          </p>
        </div>
      ) : (
      <div className="flex gap-2 border-b border-slate-200">
        {aiImageEnabled && (
          <button onClick={() => setTab("image")}
            className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition ${tab === "image" ? "border-sawali-blue text-sawali-blue" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            data-testid="mediagen-tab-image">
            <ImageIcon className="h-4 w-4" /> Image (Nano Banana)
          </button>
        )}
        {aiVideoEnabled && (
          <button onClick={() => setTab("video")}
            className={`inline-flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition ${tab === "video" ? "border-violet-600 text-violet-600" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            data-testid="mediagen-tab-video">
            <Clapperboard className="h-4 w-4" /> Vidéo (Sora 2)
          </button>
        )}
      </div>
      )}

      {/* Composer */}
      {(aiImageEnabled || aiVideoEnabled) && (
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
            {tab === "image" ? (
              <>
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
              </>
            ) : (
              <>
                <label className="text-xs text-slate-500">Durée :</label>
                <div className="flex rounded-lg border border-slate-300 overflow-hidden text-xs">
                  {[4, 8, 12].map((d) => (
                    <button key={d} onClick={() => setVideoDuration(d)}
                      className={`px-3 py-1.5 ${videoDuration === d ? "bg-violet-600 text-white" : "bg-white hover:bg-slate-50 text-slate-700"}`}
                      data-testid={`mediagen-duration-${d}`}>{d}s</button>
                  ))}
                </div>
                <select value={videoSize} onChange={(e) => setVideoSize(e.target.value)}
                  className="text-xs px-2 py-1.5 border border-slate-300 rounded-lg" data-testid="mediagen-video-size">
                  <option value="1280x720">720p paysage (1280x720)</option>
                  <option value="1024x1024">Carré (1024x1024)</option>
                  <option value="1024x1792">Portrait (1024x1792)</option>
                  <option value="1792x1024">Large (1792x1024)</option>
                </select>
                <select value={videoModel} onChange={(e) => setVideoModel(e.target.value)}
                  className="text-xs px-2 py-1.5 border border-slate-300 rounded-lg" data-testid="mediagen-video-model">
                  <option value="sora-2">Sora 2 (rapide)</option>
                  <option value="sora-2-pro">Sora 2 Pro (qualité)</option>
                  <option value="veo-3.1">Veo 3.1 (Google · son natif)</option>
                </select>
              </>
            )}
            {tab === "image" && (
              <select value={imageModel} onChange={(e) => setImageModel(e.target.value)}
                className="text-xs px-2 py-1.5 border border-slate-300 rounded-lg" data-testid="mediagen-image-model">
                <option value="nano-banana">Nano Banana (Gemini)</option>
                <option value="imagen-4">Imagen 4 (Google HD)</option>
              </select>
            )}
          </div>

          {/* Reference image (image mode only) */}
          {tab === "image" && (
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
          )}

          {tab === "video" && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              ⏱️ La génération vidéo prend généralement <strong>2 à 5 minutes</strong>. Restez sur la page.
            </p>
          )}

          <button onClick={generate} disabled={busy || !prompt.trim()}
            className={`w-full inline-flex items-center justify-center gap-2 ${tab === "video" ? "bg-gradient-to-r from-violet-700 to-fuchsia-700" : "bg-gradient-to-r from-violet-600 to-pink-600"} hover:opacity-90 disabled:opacity-50 text-white px-4 py-3 rounded-lg font-medium`}
            data-testid="mediagen-generate-btn">
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
            {busy ? (tab === "video" ? "Génération vidéo… (2-5 min)" : "Génération… (5-10 s)") : (tab === "video" ? "Générer la vidéo" : "Générer l'image")}
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
              {current.kind === "video" ? (
                <video src={fullUrl(current.url)} controls autoPlay className="w-full h-full object-contain" data-testid="mediagen-current-video" />
              ) : (
                <img src={fullUrl(current.url)} alt="Generated" className="w-full h-full object-contain" data-testid="mediagen-current-img" />
              )}
              <a href={fullUrl(current.url)} download className="absolute bottom-3 right-3 inline-flex items-center gap-1 bg-white/90 hover:bg-white text-slate-700 px-3 py-1.5 rounded-lg text-xs shadow">
                <Download className="h-3.5 w-3.5" /> Télécharger
              </a>
            </div>
          ) : (
            <div className="text-center text-slate-400 px-4">
              {tab === "video" ? <Video className="h-12 w-12 mx-auto mb-2" /> : <ImageIcon className="h-12 w-12 mx-auto mb-2" />}
              <p className="text-sm">{tab === "video" ? "La vidéo générée apparaîtra ici" : "L'image générée apparaîtra ici"}</p>
            </div>
          )}
        </div>
      </div>
      )}

      {/* Iter43-fix24az-l retest — Import local (image ou vidéo) */}
      <div className="bg-gradient-to-br from-slate-50 to-white border border-slate-200 rounded-2xl p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
              <Upload className="h-4 w-4" /> Importer un média local
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Téléversez une image ou une vidéo depuis votre ordinateur. Elle sera stockée dans votre bibliothèque
              et pourra ensuite être publiée sur Meta, LinkedIn, X, TikTok, etc.
            </p>
          </div>
        </div>
        <LocalMediaImporter
          accept="both"
          maxSizeMb={100}
          label="Choisir une image ou une vidéo"
          testIdPrefix="mediagen-local-import"
          onImported={(m) => {
            setCurrent({ url: m.public_url, kind: m.kind });
            loadHistory();
          }}
        />
      </div>

      {/* History */}
      <div>
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-sm font-semibold text-slate-700 flex items-center gap-1">
            <History className="h-4 w-4" /> Historique récent ({history.length})
          </h2>
          <div className="flex items-center gap-2">
            {storageStats.files > 0 && (
              <span
                className="inline-flex items-center gap-1.5 text-[11px] font-medium rounded-full bg-emerald-50 ring-1 ring-emerald-200 text-emerald-800 px-2.5 py-1"
                title="Vos fichiers IA sont sauvegardés sur Emergent Object Storage — ils survivent à chaque redéploiement."
                data-testid="mediagen-storage-stats"
              >
                <Lock className="h-3 w-3" />
                {storageStats.files} fichier{storageStats.files > 1 ? "s" : ""} protégé{storageStats.files > 1 ? "s" : ""}
                {storageStats.bytes > 0 && (
                  <span className="text-emerald-700/80">· {fmtBytes(storageStats.bytes)}</span>
                )}
              </span>
            )}
            <button onClick={loadHistory} className="text-xs text-violet-600 hover:underline inline-flex items-center gap-1">
              <RefreshCw className="h-3 w-3" /> Actualiser
            </button>
          </div>
        </div>
        {history.length === 0 ? (
          <p className="text-xs text-slate-400 italic">Aucune image générée pour le moment.</p>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
            {history.map((h) => (
              <button key={h.id} onClick={() => setCurrent({ url: h.url, kind: h.kind || "image" })}
                title={`${h.prompt}${h.persistent ? "\n🔒 Stocké de façon persistante" : ""}`}
                className="aspect-square overflow-hidden rounded-lg ring-1 ring-slate-200 bg-slate-100 hover:ring-2 hover:ring-violet-500 transition relative"
                data-testid={`mediagen-hist-${h.id}`}>
                {h.kind === "video" ? (
                  <>
                    <video src={fullUrl(h.url)} muted className="w-full h-full object-cover" />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/30">
                      <Clapperboard className="h-6 w-6 text-white" />
                    </span>
                  </>
                ) : (
                  <img src={fullUrl(h.url)} alt={h.prompt} className="w-full h-full object-cover" loading="lazy" />
                )}
                {h.persistent && (
                  <span
                    className="absolute top-1 right-1 inline-flex items-center gap-0.5 rounded-full bg-emerald-600/90 text-white text-[9px] font-semibold px-1.5 py-0.5 shadow ring-1 ring-emerald-700/50"
                    data-testid={`mediagen-hist-persistent-${h.id}`}
                  >
                    <Lock className="h-2.5 w-2.5" />
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
