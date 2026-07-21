// Iter43-fix10 (2026-03) — Story Studio (Phase 1 MVP)
// =====================================================================
// Génération de vidéos/images AI au format Story (9:16) + bibliothèque
// + bouton "Partager WhatsApp" (deep link mobile).
// Phase 2 ajoutera : OAuth Meta/TikTok + publication automatique IG/FB/TikTok.

import React from "react";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Video, Image as ImageIcon, Loader2, Download, Share2,
  Trash2, RefreshCw, Wand2, Settings as SettingsIcon, AlertTriangle,
  Smartphone, Copy, X, Clock, Send, Instagram, Facebook, CheckCircle2,
  Plug, PlugZap, Eye, History as HistoryIcon,
  Wallet, FileText as FileTextIcon, TrendingUp, Coins, Upload,
} from "lucide-react";
import { LocalMediaImporter } from "@/components/LocalMediaImporter";

// Helper formatter pour montants XOF
const fmtXOF = (n) => `${Number(n || 0).toLocaleString("fr-FR")} XOF`;

export default function StoryStudio() {
  const [tab, setTab] = React.useState("generate"); // generate | library | social | history | settings
  const [library, setLibrary] = React.useState([]);
  const [libraryLoading, setLibraryLoading] = React.useState(false);
  const [settings, setSettings] = React.useState(null);
  const [shareModal, setShareModal] = React.useState(null);
  const [publishModal, setPublishModal] = React.useState(null);
  const [searchParams, setSearchParams] = useSearchParams();

  const loadLibrary = React.useCallback(async () => {
    setLibraryLoading(true);
    try {
      const r = await apiClient.get("/admin/story-studio/library", { params: { limit: 100 } });
      setLibrary(r.data?.items || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur chargement bibliothèque"); }
    finally { setLibraryLoading(false); }
  }, []);

  const loadSettings = React.useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/story-studio/settings");
      setSettings(r.data);
    } catch { /* noop */ }
  }, []);

  React.useEffect(() => { loadLibrary(); loadSettings(); }, [loadLibrary, loadSettings]);

  // Iter43-fix11 — Handle OAuth callback return (redirect from Meta/TikTok)
  React.useEffect(() => {
    const oauth = searchParams.get("meta_oauth");
    const tiktok = searchParams.get("tiktok_oauth");
    if (oauth === "connected") {
      const pages = searchParams.get("pages") || "?";
      toast.success(`Meta connecté ! ${pages} Page(s) découverte(s).`);
      setTab("social");
      searchParams.delete("meta_oauth");
      searchParams.delete("social_account_id");
      searchParams.delete("pages");
      setSearchParams(searchParams, { replace: true });
    } else if (oauth === "error") {
      const reason = searchParams.get("reason") || "Erreur inconnue";
      toast.error(`Connexion Meta échouée : ${reason}`);
      setTab("social");
      searchParams.delete("meta_oauth");
      searchParams.delete("reason");
      setSearchParams(searchParams, { replace: true });
    }
    if (tiktok === "connected") {
      toast.success("TikTok connecté !");
      setTab("social");
      searchParams.delete("tiktok_oauth");
      searchParams.delete("social_account_id");
      setSearchParams(searchParams, { replace: true });
    } else if (tiktok === "error") {
      const reason = searchParams.get("reason") || "Erreur inconnue";
      toast.error(`Connexion TikTok échouée : ${reason}`);
      setTab("social");
      searchParams.delete("tiktok_oauth");
      searchParams.delete("reason");
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  return (
    <div className="space-y-5" data-testid="story-studio">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-violet-600" /> Story Studio
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Génération AI de vidéos + publication automatique IG/FB + partage WhatsApp.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1 flex-wrap">
          {[
            { v: "generate", label: "Créer", icon: Wand2 },
            { v: "library", label: "Bibliothèque", icon: Video },
            { v: "social", label: "Comptes Meta", icon: PlugZap },
            { v: "history", label: "Historique", icon: HistoryIcon },
            { v: "billing", label: "Facturation", icon: Wallet },
            { v: "settings", label: "Paramètres", icon: SettingsIcon },
          ].map((t) => (
            <button key={t.v} onClick={() => setTab(t.v)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium ${tab === t.v ? "bg-white shadow text-violet-700" : "text-slate-600 hover:text-slate-900"}`}
                    data-testid={`tab-${t.v}`}>
              <t.icon className="h-3.5 w-3.5" />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Banner Phase 2 — désormais activée */}
      <div className="rounded-lg bg-emerald-50 ring-1 ring-emerald-200 p-3 text-xs text-emerald-900 flex items-start gap-2" data-testid="phase2-banner">
        <CheckCircle2 className="h-4 w-4 flex-shrink-0 mt-0.5" />
        <div>
          <strong>Phase 2 active</strong> — Publication automatique Instagram Stories/Reels + Facebook Page Feed
          via OAuth Meta. TikTok arrive en Phase 4. Connectez votre compte Meta dans l'onglet « Comptes Meta »
          pour activer la publication.
        </div>
      </div>

      {tab === "generate" && (
        <>
          {/* Iter43-fix24az-l retest — Import local (alternative à la génération IA) */}
          <div className="rounded-xl bg-gradient-to-br from-slate-50 to-white ring-1 ring-slate-200 p-5" data-testid="story-local-import-panel">
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                  <Upload className="h-4 w-4" /> Importer un média local
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Alternative à la génération IA : téléversez votre propre image ou vidéo,
                  elle sera ajoutée à la bibliothèque et prête à être publiée sur les réseaux sociaux.
                </p>
              </div>
            </div>
            <LocalMediaImporter
              accept="both"
              maxSizeMb={200}
              label="Choisir un fichier local"
              testIdPrefix="story-local-import"
              endpoint="/admin/story-studio/library/upload"
              fileField="file"
              labelField="title"
              onImported={() => {
                toast.success("Asset ajouté dans la bibliothèque Story Studio");
                loadLibrary();
              }}
            />
          </div>
          <GenerateTab settings={settings} onCreated={loadLibrary} />
        </>
      )}
      {tab === "library" && (
        <LibraryTab
          items={library}
          loading={libraryLoading}
          onRefresh={loadLibrary}
          onShare={setShareModal}
          onPublish={setPublishModal}
          onDelete={async (id) => {
            if (!window.confirm("Supprimer définitivement cet asset ?")) return;
            try {
              await apiClient.delete(`/admin/story-studio/library/${id}`);
              toast.success("Supprimé");
              loadLibrary();
            } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
          }}
        />
      )}
      {tab === "social" && <SocialAccountsTab settings={settings} />}
      {tab === "history" && <PostsHistoryTab />}
      {tab === "billing" && <BillingTab />}
      {tab === "settings" && <SettingsTab settings={settings} onSaved={loadSettings} />}

      {shareModal && <ShareWhatsAppModal asset={shareModal} onClose={() => setShareModal(null)} />}
      {publishModal && (
        <PublishModal
          asset={publishModal}
          onClose={() => setPublishModal(null)}
          onPublished={() => { setPublishModal(null); loadLibrary(); }}
        />
      )}
    </div>
  );
}

// ============================================================
// TAB : Générer
// ============================================================
function GenerateTab({ settings, onCreated }) {
  const [mode, setMode] = React.useState("video"); // video | image
  const [engine, setEngine] = React.useState("sora-2");
  const [prompt, setPrompt] = React.useState("");
  const [duration, setDuration] = React.useState(8);
  const [size, setSize] = React.useState("720x1280");  // défaut sora-2 (720p)
  const [title, setTitle] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  // Iter43-fix10a — Auto-adjust size selon engine (Sora 2 standard limité à 720p)
  React.useEffect(() => {
    if (engine === "sora-2") setSize("720x1280");
    else if (engine === "sora-2-pro") setSize("1024x1792");
    else setSize("1024x1792");
  }, [engine]);

  const submit = async (e) => {
    e.preventDefault();
    if (prompt.trim().length < 5) { toast.error("Décrivez votre story (5 caractères min)"); return; }
    setBusy(true);
    try {
      if (mode === "video") {
        await apiClient.post("/admin/story-studio/generate/text-to-video", {
          engine,
          model: engine === "fal" ? (settings?.fal_default_model || "fal-ai/kling-video/v2.1/master/text-to-video") : undefined,
          prompt: prompt.trim(),
          duration_seconds: Number(duration),
          size,
          title: title || undefined,
        });
        toast.success("Vidéo générée et ajoutée à la bibliothèque");
      } else {
        await apiClient.post("/admin/story-studio/generate/text-to-image", {
          prompt: prompt.trim(),
          title: title || undefined,
        });
        toast.success("Image générée et ajoutée à la bibliothèque");
      }
      setPrompt("");
      setTitle("");
      onCreated();
    } catch (e) {
      toast.error(e?.response?.data?.detail || `Échec génération ${mode}`);
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5 space-y-4" data-testid="generate-form">
      <div className="flex gap-2">
        {[
          { v: "video", label: "Vidéo", icon: Video },
          { v: "image", label: "Image", icon: ImageIcon },
        ].map((m) => (
          <button key={m.v} type="button" onClick={() => setMode(m.v)}
                  className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium ${mode === m.v ? "bg-violet-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}
                  data-testid={`mode-${m.v}`}>
            <m.icon className="h-3.5 w-3.5" />
            {m.label}
          </button>
        ))}
      </div>

      <label className="block">
        <span className="block text-xs font-semibold text-slate-700 mb-1">Titre interne (optionnel)</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)}
               placeholder="Ex : Campagne rentrée 2026"
               className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
               data-testid="generate-title" />
      </label>

      <label className="block">
        <span className="block text-xs font-semibold text-slate-700 mb-1">Description (prompt) *</span>
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
                  required minLength={5}
                  placeholder="Ex : Une pharmacienne souriante accueille un client dans une pharmacie moderne et lumineuse, plan vertical 9:16, ambiance professionnelle, lumière naturelle."
                  rows={4}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  data-testid="generate-prompt" />
        <p className="text-[10px] text-slate-500 mt-1">
          💡 Astuce : décrivez le <em>sujet</em>, le <em>contexte</em>, l'<em>action</em>, le <em>style</em> et l'<em>ambiance</em>.
        </p>
      </label>

      {mode === "video" && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">Moteur</span>
            <select value={engine} onChange={(e) => setEngine(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="generate-engine">
              <option value="sora-2">Sora 2 (rapide, inclus)</option>
              <option value="sora-2-pro">Sora 2 Pro (HD, inclus)</option>
              <option value="fal" disabled={!settings?.fal_api_key_set}>
                Fal.ai (HD long){!settings?.fal_api_key_set ? " — clé non configurée" : ""}
              </option>
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">Durée</span>
            <select value={duration} onChange={(e) => setDuration(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="generate-duration">
              {engine.startsWith("sora") ? (
                <>
                  <option value={4}>4 secondes</option>
                  <option value={8}>8 secondes</option>
                  <option value={12}>12 secondes</option>
                </>
              ) : (
                <>
                  <option value={5}>5 secondes</option>
                  <option value={10}>10 secondes</option>
                  <option value={15}>15 secondes</option>
                </>
              )}
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-semibold text-slate-700 mb-1">Format</span>
            <select value={size} onChange={(e) => setSize(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="generate-size">
              {/* Sora 2 standard ne supporte que 720p. Sora 2 Pro et Fal supportent plus. */}
              {engine === "sora-2" ? (
                <>
                  <option value="720x1280">9:16 vertical 720p (Stories)</option>
                  <option value="1280x720">16:9 horizontal 720p</option>
                </>
              ) : engine === "sora-2-pro" ? (
                <>
                  <option value="1024x1792">9:16 vertical HD (Stories) — recommandé</option>
                  <option value="1792x1024">16:9 horizontal HD</option>
                  <option value="720x1280">9:16 vertical 720p</option>
                  <option value="1280x720">16:9 horizontal 720p</option>
                </>
              ) : (
                <>
                  <option value="1024x1792">9:16 vertical (Stories)</option>
                  <option value="1024x1024">1:1 carré (Feed)</option>
                  <option value="1792x1024">16:9 horizontal</option>
                  <option value="1280x720">16:9 HD</option>
                </>
              )}
            </select>
          </label>
        </div>
      )}

      <div className="rounded-lg bg-violet-50 ring-1 ring-violet-200 p-3 text-xs text-violet-900">
        <strong>⏱️ Temps estimé :</strong> {mode === "image" ? "10-30 s" : engine === "fal" ? "30 s – 2 min" : "1-3 min selon durée"} —
        la génération est synchrone, restez sur la page.
      </div>

      <button type="submit" disabled={busy}
              className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-violet-600 text-white hover:bg-violet-700 px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
              data-testid="generate-submit">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
        {busy ? "Génération en cours…" : `Générer la ${mode === "video" ? "vidéo" : "image"}`}
      </button>
    </form>
  );
}

// ============================================================
// TAB : Bibliothèque
// ============================================================
function LibraryTab({ items, loading, onRefresh, onShare, onPublish, onDelete }) {
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <button onClick={onRefresh} className="text-xs inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50" data-testid="library-refresh">
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      {loading && items.length === 0 ? (
        <div className="text-center py-12 text-slate-400">Chargement…</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-slate-400 italic" data-testid="library-empty">
          Aucun asset. Créez votre première story depuis l'onglet « Créer ».
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((it) => <AssetCard key={it.id} asset={it} onShare={onShare} onPublish={onPublish} onDelete={onDelete} />)}
        </div>
      )}
    </div>
  );
}

function AssetCard({ asset, onShare, onPublish, onDelete }) {
  const isVideo = asset.kind === "video";
  const isReady = asset.status === "ready";
  const isProcessing = asset.status === "processing";
  const isFailed = asset.status === "failed";
  // Iter43-fix24k — Statut "expired" : fichier local perdu (redéploiement K8s)
  // ET URL source CDN expirée. L'asset reste visible avec un badge clair pour
  // que l'admin puisse régénérer.
  const isExpired = asset.status === "expired";
  const [blobUrl, setBlobUrl] = React.useState(null);
  const [blobLoading, setBlobLoading] = React.useState(false);

  // Iter43-fix10a — Charge le média via apiClient (auth) puis blob URL.
  React.useEffect(() => {
    let cancel = false;
    let createdUrl = null;
    if (isReady && asset.url) {
      setBlobLoading(true);
      apiClient.get(asset.url, { responseType: "blob" })
        .then((r) => {
          if (cancel) return;
          createdUrl = URL.createObjectURL(r.data);
          setBlobUrl(createdUrl);
        })
        .catch(() => { /* silent — empty preview */ })
        .finally(() => { if (!cancel) setBlobLoading(false); });
    }
    return () => {
      cancel = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [asset.id, asset.url, isReady]);

  const downloadAsset = async () => {
    try {
      const r = await apiClient.get(asset.url, { responseType: "blob" });
      const blob = new Blob([r.data], { type: isVideo ? "video/mp4" : "image/png" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${asset.title || "story"}.${isVideo ? "mp4" : "png"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 8000);
    } catch (e) {
      toast.error("Échec téléchargement");
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 overflow-hidden" data-testid={`asset-card-${asset.id}`}>
      <div className="aspect-[9/16] bg-slate-100 flex items-center justify-center relative">
        {isReady && blobUrl ? (
          isVideo ? (
            <video src={blobUrl} controls className="w-full h-full object-cover" data-testid={`asset-video-${asset.id}`} />
          ) : (
            <img src={blobUrl} alt={asset.title} className="w-full h-full object-cover" data-testid={`asset-image-${asset.id}`} />
          )
        ) : isReady && blobLoading ? (
          <div className="text-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400 mx-auto" /><p className="text-xs text-slate-400 mt-2">Chargement…</p></div>
        ) : isProcessing ? (
          <div className="text-center"><Loader2 className="h-8 w-8 animate-spin text-violet-600 mx-auto" /><p className="text-xs text-slate-500 mt-2">Génération…</p></div>
        ) : isFailed ? (
          <div className="text-center px-3"><AlertTriangle className="h-6 w-6 text-rose-500 mx-auto" /><p className="text-xs text-rose-600 mt-2">Échec</p><p className="text-[10px] text-slate-500 mt-1 line-clamp-2">{asset.error}</p></div>
        ) : isExpired ? (
          <div className="text-center px-3" data-testid={`asset-expired-${asset.id}`}>
            <AlertTriangle className="h-6 w-6 text-amber-500 mx-auto" />
            <p className="text-xs text-amber-700 font-semibold mt-2">Vidéo expirée</p>
            <p className="text-[10px] text-slate-500 mt-1 line-clamp-3">
              {asset.expired_reason || "Fichier perdu lors d'un redéploiement serveur. Régénérez l'asset."}
            </p>
          </div>
        ) : null}
        <span className="absolute top-2 left-2 text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded bg-white/90 backdrop-blur ring-1 ring-slate-200">
          {isVideo ? "Vidéo" : "Image"} · {asset.engine}
        </span>
      </div>
      <div className="p-3 space-y-2">
        <p className="text-sm font-medium text-slate-900 line-clamp-1" title={asset.title}>{asset.title || "Sans titre"}</p>
        <p className="text-[11px] text-slate-500 line-clamp-2">{asset.prompt}</p>
        {/* Iter43-fix15 — Consommation tokens / coût estimé */}
        {asset.usage_estimate?.estimated && (
          <div className="text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded bg-violet-50 text-violet-700 ring-1 ring-violet-200"
               data-testid={`asset-usage-${asset.id}`}
               title={`${asset.usage_estimate.engine_label} · ${asset.usage_estimate.quantity} ${asset.usage_estimate.unit}(s) × ${asset.usage_estimate.unit_cost_usd}$`}>
            <Coins className="h-3 w-3" />
            <span className="font-semibold">
              {asset.usage_estimate.estimated_cost_xof} XOF
            </span>
            <span className="text-violet-500">
              (~${asset.usage_estimate.estimated_cost_usd?.toFixed(3)})
            </span>
          </div>
        )}
        <div className="flex items-center gap-1 flex-wrap pt-1">
          {isReady && (
            <>
              <button onClick={downloadAsset}
                 className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700"
                 data-testid={`asset-download-${asset.id}`}>
                <Download className="h-3 w-3" /> Télécharger
              </button>
              {isVideo && (
                <button onClick={() => onPublish(asset)}
                        className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-violet-600 text-white hover:bg-violet-700"
                        data-testid={`asset-publish-${asset.id}`}>
                  <Send className="h-3 w-3" /> Publier IG/FB
                </button>
              )}
              <button onClick={() => onShare(asset)}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                      data-testid={`asset-share-${asset.id}`}>
                <Share2 className="h-3 w-3" /> WhatsApp
              </button>
            </>
          )}
          <button onClick={() => onDelete(asset.id)}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded text-rose-600 hover:bg-rose-50 ml-auto"
                  data-testid={`asset-delete-${asset.id}`}>
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// MODAL : Partage WhatsApp (deep link mobile)
// ============================================================
function ShareWhatsAppModal({ asset, onClose }) {
  const [shareData, setShareData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get(`/admin/story-studio/library/${asset.id}/whatsapp-share`);
        setShareData(r.data);
      } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); onClose(); }
      finally { setLoading(false); }
    })();
  }, [asset.id, onClose]);

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text).then(() => toast.success("Copié"));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="share-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold inline-flex items-center gap-2">
            <Smartphone className="h-4 w-4 text-emerald-600" /> Partager sur WhatsApp Status
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          {loading ? (
            <div className="text-center py-6"><Loader2 className="h-6 w-6 animate-spin text-emerald-600 mx-auto" /></div>
          ) : shareData ? (
            <>
              <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
                <strong>📱 Ouvrez ce lien depuis votre mobile :</strong>
                <p className="mt-1">L'app WhatsApp s'ouvrira avec le texte pré-rempli. Appuyez ensuite sur l'icône <strong>« Status »</strong> pour publier.</p>
              </div>

              <a href={shareData.deep_link}
                 className="block text-center w-full px-4 py-3 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700"
                 data-testid="share-deep-link-btn">
                📲 Ouvrir WhatsApp (mobile)
              </a>

              <a href={shareData.web_fallback} target="_blank" rel="noopener noreferrer"
                 className="block text-center w-full px-4 py-2 rounded-lg bg-slate-100 text-slate-700 text-sm hover:bg-slate-200"
                 data-testid="share-web-link-btn">
                💻 Ouvrir WhatsApp Web (si pas sur mobile)
              </a>

              <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
                <p className="text-[11px] text-slate-500 mb-1">URL média publique :</p>
                <div className="flex items-center gap-1">
                  <code className="flex-1 text-[10px] bg-white rounded p-1.5 ring-1 ring-slate-200 truncate font-mono">{shareData.media_url}</code>
                  <button onClick={() => copyToClipboard(shareData.media_url)}
                          className="text-xs px-2 py-1.5 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-100"
                          title="Copier l'URL">
                    <Copy className="h-3 w-3" />
                  </button>
                </div>
              </div>

              <details className="text-xs text-slate-600">
                <summary className="cursor-pointer font-medium">Instructions détaillées</summary>
                <p className="mt-2 leading-relaxed">{shareData.instructions}</p>
                <ol className="mt-2 space-y-1 list-decimal list-inside">
                  <li>Téléchargez la vidéo sur votre mobile (lien « Télécharger » dans la bibliothèque)</li>
                  <li>Ouvrez WhatsApp → onglet <strong>Status</strong></li>
                  <li>Appuyez sur l'icône caméra → sélectionnez la vidéo téléchargée</li>
                  <li>Ajoutez votre légende et publiez ✅</li>
                </ol>
              </details>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ============================================================
// TAB : Comptes Meta — Iter43-fix11 Phase 2 (OAuth)
// ============================================================
function SocialAccountsTab({ settings }) {
  const [accounts, setAccounts] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [connecting, setConnecting] = React.useState(false);
  const [connectingTiktok, setConnectingTiktok] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/story-studio/social-accounts");
      setAccounts(r.data?.items || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur chargement"); }
    finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const connectMeta = async () => {
    if (!settings?.meta_app_id || !settings?.meta_app_secret_set) {
      toast.error("Configurez d'abord Meta App ID + Secret dans Paramètres.");
      return;
    }
    setConnecting(true);
    try {
      const r = await apiClient.get("/admin/story-studio/oauth/meta/start", {
        params: { return_to: "/admin/story-studio" },
      });
      window.location.href = r.data.auth_url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur démarrage OAuth");
      setConnecting(false);
    }
  };

  const connectTiktok = async () => {
    if (!settings?.tiktok_client_key || !settings?.tiktok_client_secret_set) {
      toast.error("Configurez d'abord TikTok Client Key + Secret dans Paramètres.");
      return;
    }
    setConnectingTiktok(true);
    try {
      const r = await apiClient.get("/admin/story-studio/oauth/tiktok/start", {
        params: { return_to: "/admin/story-studio" },
      });
      window.location.href = r.data.auth_url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur démarrage OAuth TikTok");
      setConnectingTiktok(false);
    }
  };

  const refreshAccount = async (accId) => {
    try {
      await apiClient.post(`/admin/story-studio/social-accounts/${accId}/refresh`);
      toast.success("Pages rafraîchies");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const disconnect = async (accId) => {
    if (!window.confirm("Déconnecter ce compte Meta ? Les tokens seront supprimés.")) return;
    try {
      await apiClient.delete(`/admin/story-studio/social-accounts/${accId}`);
      toast.success("Compte déconnecté");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const togglePage = async (accId, pageId, isActive) => {
    try {
      await apiClient.put(`/admin/story-studio/social-accounts/${accId}/pages/${pageId}`, { is_active: isActive });
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const credsConfigured = settings?.meta_app_id && settings?.meta_app_secret_set;
  const tiktokConfigured = settings?.tiktok_client_key && settings?.tiktok_client_secret_set;
  const metaAccounts = accounts.filter((a) => a.provider === "meta");
  const tiktokAccounts = accounts.filter((a) => a.provider === "tiktok");

  return (
    <div className="space-y-4" data-testid="social-accounts-tab">
      <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5 space-y-3">
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-base font-semibold inline-flex items-center gap-2">
              <PlugZap className="h-4 w-4 text-blue-600" /> Comptes Meta (Facebook + Instagram)
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              Connectez les comptes Meta Business de vos clients. Le SAWALI Meta App configuré dans
              Paramètres sert d'intermédiaire OAuth pour tous les tenants.
            </p>
          </div>
          <button
            onClick={connectMeta}
            disabled={connecting || !credsConfigured}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50"
            data-testid="connect-meta-btn"
            title={!credsConfigured ? "Configurez Meta App ID + Secret dans Paramètres" : ""}
          >
            {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Facebook className="h-4 w-4" />}
            Connecter un compte Meta
          </button>
        </div>
        {!credsConfigured && (
          <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900" data-testid="creds-missing-warning">
            <strong>⚠️ Meta App non configuré.</strong> Allez dans <em>Paramètres → Meta</em>, renseignez
            votre Meta App ID + App Secret obtenus sur <a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener noreferrer" className="underline">developers.facebook.com</a>,
            puis ajoutez l'URI de redirection dans la configuration OAuth de votre application Meta.
          </div>
        )}
      </div>

      {/* Iter43-fix14 — Phase 4 TikTok section */}
      <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5 space-y-3">
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-base font-semibold inline-flex items-center gap-2">
              <Video className="h-4 w-4 text-pink-600" /> Comptes TikTok
            </h2>
            <p className="text-xs text-slate-500 mt-1">
              Publication directe via TikTok Content Posting API (sandbox/production).
              En mode sandbox, les posts restent privés.
            </p>
          </div>
          <button
            onClick={connectTiktok}
            disabled={connectingTiktok || !tiktokConfigured}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-pink-600 text-white text-sm font-semibold hover:bg-pink-700 disabled:opacity-50"
            data-testid="connect-tiktok-btn"
            title={!tiktokConfigured ? "Configurez TikTok Client Key + Secret dans Paramètres" : ""}
          >
            {connectingTiktok ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
            Connecter un compte TikTok
          </button>
        </div>
        {!tiktokConfigured && (
          <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900" data-testid="tiktok-creds-missing">
            <strong>⚠️ TikTok App non configuré.</strong> Suivez les instructions dans <em>Paramètres → TikTok</em>.
          </div>
        )}
        {/* Iter43-fix24az-p — Badge visible du mode privé/public actif */}
        {tiktokConfigured && (
          <div className={`rounded-lg p-3 text-xs flex items-start gap-2 ${
            (settings?.tiktok_privacy_level || "SELF_ONLY") === "SELF_ONLY"
              ? "bg-emerald-50 ring-1 ring-emerald-200 text-emerald-900"
              : "bg-orange-50 ring-1 ring-orange-200 text-orange-900"
          }`} data-testid="tiktok-current-privacy-badge">
            <span className="text-base">
              {(settings?.tiktok_privacy_level || "SELF_ONLY") === "SELF_ONLY" ? "🔒" : "🌐"}
            </span>
            <div>
              <strong>Mode de publication actuel : {
                { SELF_ONLY: "Privé (visible uniquement par vous)",
                  MUTUAL_FOLLOW_FRIENDS: "Amis mutuels",
                  FOLLOWER_OF_CREATOR: "Abonnés",
                  PUBLIC_TO_EVERYONE: "Public (tout le monde)",
                }[settings?.tiktok_privacy_level || "SELF_ONLY"]
              }</strong>
              <p className="mt-0.5 text-[11px] opacity-80">
                Modifiez ce paramètre dans <em>Paramètres → TikTok → Visibilité par défaut</em>.
              </p>
            </div>
          </div>
        )}
        {tiktokAccounts.length > 0 && (
          <div className="space-y-2 mt-2">
            {tiktokAccounts.map((a) => (
              <div key={a.id} className="flex items-center gap-3 p-2 rounded ring-1 ring-slate-200" data-testid={`tiktok-account-${a.id}`}>
                {a.tiktok_avatar_url && <img src={a.tiktok_avatar_url} alt="" className="h-8 w-8 rounded-full" />}
                <div className="flex-1">
                  <p className="font-semibold text-sm">{a.tiktok_display_name || a.account_label}</p>
                  <p className="text-[10px] text-slate-500 font-mono">{a.tiktok_open_id}</p>
                </div>
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-700">{a.status}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-400">Chargement…</div>
      ) : metaAccounts.length === 0 ? (
        <div className="text-center py-12 text-slate-400 italic bg-white rounded-xl ring-1 ring-slate-200" data-testid="no-accounts">
          Aucun compte Meta connecté. Cliquez sur « Connecter un compte Meta » pour commencer.
        </div>
      ) : (
        <div className="space-y-3">
          {metaAccounts.map((a) => (
            <MetaAccountCard
              key={a.id}
              account={a}
              onRefresh={() => refreshAccount(a.id)}
              onDisconnect={() => disconnect(a.id)}
              onTogglePage={(pid, active) => togglePage(a.id, pid, active)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function MetaAccountCard({ account, onRefresh, onDisconnect, onTogglePage }) {
  const pages = account.pages || [];
  const expiresAt = account.long_lived_user_token_expires_at;
  const expDate = expiresAt ? new Date(expiresAt) : null;
  const daysLeft = expDate ? Math.round((expDate - new Date()) / (1000 * 60 * 60 * 24)) : null;
  const expSoon = daysLeft !== null && daysLeft < 7;

  return (
    <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-4" data-testid={`meta-account-${account.id}`}>
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div>
          <p className="font-semibold text-slate-900 inline-flex items-center gap-2">
            <Facebook className="h-4 w-4 text-blue-600" /> {account.meta_user_name || account.account_label}
          </p>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {account.meta_user_email && <>📧 {account.meta_user_email} · </>}
            {pages.length} Page(s)
            {daysLeft !== null && (
              <span className={`ml-2 px-1.5 py-0.5 rounded ${expSoon ? "bg-amber-100 text-amber-800" : "bg-emerald-50 text-emerald-700"}`}>
                Token : {daysLeft > 0 ? `${daysLeft}j restants` : "expiré"}
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-1">
          <button onClick={onRefresh} className="text-xs inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-100 hover:bg-slate-200" data-testid={`refresh-${account.id}`}>
            <RefreshCw className="h-3 w-3" /> Rafraîchir
          </button>
          <button onClick={onDisconnect} className="text-xs inline-flex items-center gap-1 px-2 py-1 rounded text-rose-600 hover:bg-rose-50" data-testid={`disconnect-${account.id}`}>
            <Trash2 className="h-3 w-3" /> Déconnecter
          </button>
        </div>
      </div>

      {pages.length === 0 ? (
        <p className="text-xs text-slate-400 italic mt-3">Aucune Page rattachée. L'utilisateur Meta n'administre aucune Page Facebook.</p>
      ) : (
        <div className="mt-3 space-y-1.5">
          {pages.map((p) => (
            <div key={p.page_id} className="flex items-center gap-2 text-sm p-2 rounded bg-slate-50" data-testid={`page-${p.page_id}`}>
              <input type="checkbox" checked={p.is_active !== false}
                     onChange={(e) => onTogglePage(p.page_id, e.target.checked)}
                     className="rounded"
                     data-testid={`page-toggle-${p.page_id}`} />
              <Facebook className="h-3.5 w-3.5 text-blue-500" />
              <span className="font-medium text-slate-800 flex-1">{p.page_name}</span>
              {p.ig_business_account_id ? (
                <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-pink-100 text-pink-700">
                  <Instagram className="h-2.5 w-2.5" /> @{p.ig_username || p.ig_business_account_id}
                </span>
              ) : (
                <span className="text-[10px] text-slate-400 italic">Pas d'IG lié</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// MODAL : Publier sur IG/FB — Iter43-fix11 Phase 2
// ============================================================
function PublishModal({ asset, onClose, onPublished }) {
  const [accounts, setAccounts] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [caption, setCaption] = React.useState(asset.caption || asset.title || "");
  const [mode, setMode] = React.useState("immediate"); // immediate | draft
  const [targets, setTargets] = React.useState([]); // [{social_account_id, page_id, target, label}]
  const [publishing, setPublishing] = React.useState(false);
  const [results, setResults] = React.useState(null);

  React.useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get("/admin/story-studio/social-accounts");
        setAccounts((r.data?.items || []).filter((a) => a.status === "connected"));
      } catch { /* noop */ }
      finally { setLoading(false); }
    })();
  }, []);

  const toggleTarget = (acc, page, kind) => {
    const id = `${acc.id}::${page?.page_id || "tiktok"}::${kind}`;
    setTargets((prev) => {
      const exists = prev.find((t) => t._key === id);
      if (exists) return prev.filter((t) => t._key !== id);
      return [
        ...prev,
        {
          _key: id,
          social_account_id: acc.id,
          page_id: page?.page_id || "tiktok",
          target: kind,
          _label: `${page?.page_name || acc.tiktok_display_name || acc.account_label} · ${
            kind === "fb_feed" ? "Facebook Feed"
            : kind === "ig_story" ? "Instagram Story"
            : kind === "ig_reel" ? "Instagram Reel"
            : "TikTok"
          }`,
        },
      ];
    });
  };

  const isSelected = (acc, page, kind) =>
    !!targets.find((t) => t._key === `${acc.id}::${page?.page_id || "tiktok"}::${kind}`);

  const submit = async () => {
    if (targets.length === 0) {
      toast.error("Sélectionnez au moins une cible");
      return;
    }
    setPublishing(true);
    setResults(null);
    try {
      const cleanTargets = targets.map((t) => ({
        social_account_id: t.social_account_id,
        page_id: t.page_id,
        target: t.target,
      }));
      const r = await apiClient.post(`/admin/story-studio/library/${asset.id}/publish`, {
        targets: cleanTargets,
        caption: caption.trim(),
        mode,
      });
      setResults(r.data);
      if (r.data.ok) {
        toast.success(mode === "draft" ? "Brouillon enregistré" : "Publication réussie");
        if (mode === "draft") onPublished();
      } else if (r.data.status === "partial") {
        toast.warning("Publication partielle — voir détails");
      } else {
        toast.error("Échec de la publication — voir détails");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lors de la publication");
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-4"
         onClick={(e) => e.target === e.currentTarget && !publishing && onClose()}
         data-testid="publish-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold inline-flex items-center gap-2">
            <Send className="h-4 w-4 text-violet-600" /> Publier sur Instagram + Facebook
          </h3>
          <button onClick={onClose} disabled={publishing} className="text-slate-500 hover:text-slate-900 disabled:opacity-30">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          {loading ? (
            <div className="text-center py-6"><Loader2 className="h-6 w-6 animate-spin text-violet-600 mx-auto" /></div>
          ) : accounts.length === 0 ? (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
              <strong>Aucun compte Meta connecté.</strong> Allez dans l'onglet « Comptes Meta » pour en connecter un.
            </div>
          ) : (
            <>
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Cibles</label>
                <div className="space-y-3 max-h-64 overflow-y-auto pr-1">
                  {accounts.map((acc) => {
                    if (acc.provider === "tiktok") {
                      return (
                        <div key={acc.id} className="rounded-lg border border-slate-200 p-3">
                          <p className="text-xs font-semibold text-slate-700 mb-2 inline-flex items-center gap-1">
                            <Video className="h-3 w-3 text-pink-600" />
                            TikTok — {acc.tiktok_display_name || acc.account_label}
                          </p>
                          <div className="flex flex-wrap gap-1.5 ml-2">
                            <button onClick={() => toggleTarget(acc, null, "tiktok")}
                                    className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded ${isSelected(acc, null, "tiktok") ? "bg-pink-600 text-white" : "bg-slate-100 hover:bg-slate-200"}`}
                                    data-testid={`target-tiktok-${acc.id}`}>
                              <Video className="h-3 w-3" /> TikTok (Direct Post)
                            </button>
                          </div>
                        </div>
                      );
                    }
                    // Meta
                    return (
                      <div key={acc.id} className="rounded-lg border border-slate-200 p-3">
                        <p className="text-xs font-semibold text-slate-700 mb-2">{acc.meta_user_name}</p>
                        {(acc.pages || []).filter((p) => p.is_active !== false).map((p) => (
                          <div key={p.page_id} className="ml-2 space-y-1 mb-2">
                            <p className="text-[11px] text-slate-600 font-medium">{p.page_name}</p>
                            <div className="flex flex-wrap gap-1.5 ml-2">
                              <button onClick={() => toggleTarget(acc, p, "fb_feed")}
                                      className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded ${isSelected(acc, p, "fb_feed") ? "bg-blue-600 text-white" : "bg-slate-100 hover:bg-slate-200"}`}
                                      data-testid={`target-fb-${p.page_id}`}>
                                <Facebook className="h-3 w-3" /> Facebook Feed
                              </button>
                              {p.ig_business_account_id && (
                                <>
                                  <button onClick={() => toggleTarget(acc, p, "ig_story")}
                                          className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded ${isSelected(acc, p, "ig_story") ? "bg-pink-600 text-white" : "bg-slate-100 hover:bg-slate-200"}`}
                                          data-testid={`target-ig-story-${p.page_id}`}>
                                    <Instagram className="h-3 w-3" /> IG Story
                                  </button>
                                  <button onClick={() => toggleTarget(acc, p, "ig_reel")}
                                          className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded ${isSelected(acc, p, "ig_reel") ? "bg-pink-600 text-white" : "bg-slate-100 hover:bg-slate-200"}`}
                                          data-testid={`target-ig-reel-${p.page_id}`}>
                                    <Instagram className="h-3 w-3" /> IG Reel
                                  </button>
                                </>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>

              <label className="block">
                <span className="block text-xs font-semibold text-slate-700 mb-1">Légende</span>
                <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3}
                          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                          data-testid="publish-caption" />
                <p className="text-[10px] text-slate-500 mt-1">
                  ℹ️ Les Instagram Stories n'affichent pas de légende. Les Reels et Facebook l'utilisent.
                </p>
              </label>

              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Mode</label>
                <div className="flex gap-2">
                  <button onClick={() => setMode("immediate")}
                          className={`flex-1 text-xs px-3 py-2 rounded ${mode === "immediate" ? "bg-violet-600 text-white" : "bg-slate-100"}`}
                          data-testid="mode-immediate">
                    🚀 Publier maintenant
                  </button>
                  <button onClick={() => setMode("draft")}
                          className={`flex-1 text-xs px-3 py-2 rounded ${mode === "draft" ? "bg-violet-600 text-white" : "bg-slate-100"}`}
                          data-testid="mode-draft">
                    📝 Enregistrer brouillon
                  </button>
                </div>
              </div>

              {results && (
                <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 space-y-1" data-testid="publish-results">
                  <p className="text-xs font-semibold text-slate-700 flex items-center justify-between">
                    <span>Résultats :</span>
                    {results.total_cost > 0 && (
                      <span className="text-violet-700 inline-flex items-center gap-1">
                        <Coins className="h-3 w-3" /> Coût total : {fmtXOF(results.total_cost)}
                      </span>
                    )}
                  </p>
                  {(results.results || []).map((r, i) => (
                    <p key={i} className="text-[11px]">
                      {r.ok ? "✅" : "❌"} {r.target} →{" "}
                      {r.ok ? <span className="text-emerald-700">
                        Publié (id: {r.channel_id})
                        {r.billing?.billed && (
                          <span className="ml-1 text-violet-700">
                            · {fmtXOF(r.billing.cost)}
                            {r.billing.mode === "credits" && " (crédits)"}
                            {r.billing.mode === "invoice" && " (facture)"}
                            {r.billing.mode === "mixed" && " (mixte)"}
                          </span>
                        )}
                      </span>
                            : <span className="text-rose-700">{r.error}</span>}
                    </p>
                  ))}
                  {results.ok && mode === "immediate" && (
                    <button onClick={onPublished} className="mt-2 text-xs px-3 py-1 rounded bg-emerald-600 text-white">Fermer</button>
                  )}
                </div>
              )}

              <button onClick={submit} disabled={publishing || targets.length === 0}
                      className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-violet-600 text-white hover:bg-violet-700 px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
                      data-testid="publish-submit">
                {publishing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {publishing ? "Publication…" : (mode === "draft" ? "Enregistrer le brouillon" : `Publier sur ${targets.length} cible(s)`)}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================
// TAB : Historique des publications — Iter43-fix11 Phase 2
// ============================================================
function PostsHistoryTab() {
  const [posts, setPosts] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/story-studio/posts", { params: { limit: 100 } });
      setPosts(r.data?.items || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const publishNow = async (postId) => {
    try {
      await apiClient.post(`/admin/story-studio/posts/${postId}/publish-now`);
      toast.success("Publication lancée");
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5" data-testid="posts-history">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-semibold inline-flex items-center gap-2">
          <HistoryIcon className="h-4 w-4 text-slate-600" /> Historique des publications
        </h2>
        <button onClick={load} className="text-xs inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-100">
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      {loading && posts.length === 0 ? (
        <div className="text-center py-8 text-slate-400">Chargement…</div>
      ) : posts.length === 0 ? (
        <div className="text-center py-8 text-slate-400 italic">Aucune publication.</div>
      ) : (
        <div className="space-y-2">
          {posts.map((p) => (
            <div key={p.id} className="text-xs p-3 rounded ring-1 ring-slate-200 bg-slate-50" data-testid={`post-${p.id}`}>
              <div className="flex justify-between items-start flex-wrap gap-2">
                <div className="flex-1">
                  <p className="font-medium text-slate-800 line-clamp-2">{p.caption || "(sans légende)"}</p>
                  <p className="text-[10px] text-slate-500 mt-1">
                    {p.created_at?.slice(0, 16).replace("T", " ")} · {(p.targets || []).length} cible(s)
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] px-2 py-0.5 rounded ${
                    p.status === "published" ? "bg-emerald-50 text-emerald-700" :
                    p.status === "draft" ? "bg-slate-200 text-slate-700" :
                    p.status === "partial" ? "bg-amber-50 text-amber-800" :
                    p.status === "failed" ? "bg-rose-50 text-rose-700" :
                    "bg-blue-50 text-blue-700"
                  }`}>{p.status}</span>
                  {(p.status === "draft" || p.status === "failed") && (
                    <button onClick={() => publishNow(p.id)} className="text-[10px] px-2 py-0.5 rounded bg-violet-600 text-white hover:bg-violet-700">
                      Publier maintenant
                    </button>
                  )}
                </div>
              </div>
              {p.results?.length > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-[10px] text-slate-600">Détails par cible</summary>
                  <div className="mt-1 space-y-0.5 ml-2">
                    {p.results.map((r, i) => (
                      <p key={i} className="text-[10px]">
                        {r.ok ? "✅" : "❌"} {r.target} →{" "}
                        {r.ok ? <span className="text-emerald-700">id={r.channel_id}</span>
                              : <span className="text-rose-700">{r.error}</span>}
                      </p>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// TAB : Paramètres
// ============================================================
function SettingsTab({ settings, onSaved }) {
  const [form, setForm] = React.useState({});
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (settings) {
      setForm({
        fal_api_key: "",  // toujours vide à l'ouverture (masqué côté serveur)
        fal_default_model: settings.fal_default_model || "fal-ai/kling-video/v2.1/master/text-to-video",
        sora_enabled: settings.sora_enabled,
        sora_default_duration: settings.sora_default_duration,
        sora_default_size: settings.sora_default_size,
        meta_app_id: settings.meta_app_id || "",
        meta_app_secret: "",
        meta_redirect_uri: settings.meta_redirect_uri || "",
        tiktok_client_key: settings.tiktok_client_key || "",
        tiktok_client_secret: "",
        tiktok_redirect_uri: settings.tiktok_redirect_uri || "",
        // Iter43-fix24az-p — Toggle "Publier en privé sur TikTok" mis en avant
        tiktok_privacy_level: settings.tiktok_privacy_level || "SELF_ONLY",
        default_caption_template: settings.default_caption_template || "",
      });
    }
  }, [settings]);

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      // N'envoyer que les champs non-vides pour les secrets
      const payload = { ...form };
      if (!payload.fal_api_key) delete payload.fal_api_key;
      if (!payload.meta_app_secret) delete payload.meta_app_secret;
      if (!payload.tiktok_client_secret) delete payload.tiktok_client_secret;
      await apiClient.put("/admin/story-studio/settings", payload);
      toast.success("Paramètres enregistrés");
      onSaved();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const update = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  if (!settings) return <div className="text-slate-400 py-8 text-center">Chargement…</div>;

  return (
    <form onSubmit={save} className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5 space-y-5" data-testid="settings-form">
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-violet-700">🎬 Fal.ai (vidéos HD payantes)</legend>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Clé API Fal.ai {settings.fal_api_key_set && <span className="text-[10px] text-emerald-600 ml-1">✓ configurée ({settings.fal_api_key})</span>}</span>
          <input type="password" value={form.fal_api_key || ""} onChange={update("fal_api_key")}
                 placeholder={settings.fal_api_key_set ? "Laisser vide pour conserver" : "fal_xxxxxxxx"}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                 data-testid="settings-fal-key" />
          <p className="text-[10px] text-slate-500 mt-1">Obtenez votre clé sur <a href="https://fal.ai/dashboard/keys" target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline">fal.ai/dashboard/keys</a></p>
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Modèle Fal.ai par défaut</span>
          <select value={form.fal_default_model || ""} onChange={update("fal_default_model")}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="settings-fal-model">
            <option value="fal-ai/kling-video/v2.1/master/text-to-video">Kling 2.1 Master (premium, cinema)</option>
            <option value="fal-ai/kling-video/v2.5-turbo/pro/text-to-video">Kling 2.5 Turbo Pro (rapide)</option>
            <option value="fal-ai/veo3/text-to-video">Veo 3 (Google, prompt control)</option>
          </select>
        </label>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-blue-700">📘 Meta (Instagram Stories + Facebook)</legend>
        <p className="text-[11px] text-slate-500">App SAWALI utilisée par tous les tenants. Vos clients connecteront leurs comptes via OAuth.</p>
        <div className="rounded-lg bg-blue-50 ring-1 ring-blue-200 p-3 text-[11px] text-blue-900" data-testid="meta-setup-help">
          <p className="font-semibold mb-1">📋 Configuration Meta Developer App</p>
          <ol className="list-decimal list-inside space-y-0.5">
            <li>Créez une App sur <a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener noreferrer" className="underline">developers.facebook.com/apps</a> (type « Business »).</li>
            <li>Ajoutez les produits <strong>Facebook Login for Business</strong> et <strong>Instagram</strong>.</li>
            <li>Dans <em>Facebook Login → Settings</em>, ajoutez cette URI dans « Valid OAuth Redirect URIs » :
              <code className="block mt-1 p-1 bg-white rounded font-mono text-[10px] break-all">
                {window.location.origin}/api/admin/story-studio/oauth/meta/callback
              </code>
            </li>
            <li>Demandez l'App Review pour les permissions : <code>instagram_content_publish</code>, <code>pages_manage_posts</code>, <code>business_management</code>.</li>
            <li>Renseignez l'App ID + Secret ci-dessous.</li>
          </ol>
        </div>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Meta App ID</span>
          <input value={form.meta_app_id || ""} onChange={update("meta_app_id")}
                 placeholder="123456789012345"
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="settings-meta-app-id" />
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Meta App Secret {settings.meta_app_secret_set && <span className="text-[10px] text-emerald-600 ml-1">✓ configurée</span>}</span>
          <input type="password" value={form.meta_app_secret || ""} onChange={update("meta_app_secret")}
                 placeholder={settings.meta_app_secret_set ? "Laisser vide pour conserver" : "App secret"}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="settings-meta-app-secret" />
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">Meta Redirect URI <span className="text-slate-400 font-normal">(laisser vide pour auto-détection)</span></span>
          <input value={form.meta_redirect_uri || ""} onChange={update("meta_redirect_uri")}
                 placeholder={`${window.location.origin}/api/admin/story-studio/oauth/meta/callback`}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="settings-meta-redirect" />
          <p className="text-[10px] text-slate-500 mt-1">Cette URI doit être strictement identique à celle déclarée dans votre app Meta.</p>
        </label>
      </fieldset>

      {/* Iter43-fix14 — Phase 4 TikTok Settings */}
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-pink-700">🎵 TikTok (Content Posting API)</legend>
        <div className="rounded-lg bg-pink-50 ring-1 ring-pink-200 p-3 text-[11px] text-pink-900" data-testid="tiktok-setup-help">
          <p className="font-semibold mb-1">📋 Configuration TikTok Developer App</p>
          <ol className="list-decimal list-inside space-y-0.5">
            <li>Créez un compte sur <a href="https://developers.tiktok.com/" target="_blank" rel="noopener noreferrer" className="underline">developers.tiktok.com</a></li>
            <li>Allez dans <em>Manage apps</em> → <strong>Connect an app</strong>. Choisissez "Business" et associez à une Organization.</li>
            <li>Dans <em>Add products</em>, ajoutez <strong>Login Kit</strong> et <strong>Content Posting API</strong>.</li>
            <li>Dans <em>Scopes</em>, activez : <code>video.upload</code>, <code>video.publish</code>, <code>user.info.basic</code>.</li>
            <li>Dans <em>App settings → Login Kit → Redirect URI</em>, ajoutez :
              <code className="block mt-1 p-1 bg-white rounded font-mono text-[10px] break-all">
                {window.location.origin}/api/admin/story-studio/oauth/tiktok/callback
              </code>
            </li>
            <li>Démarrez avec une <strong>Sandbox</strong> (Mode → Sandbox) pour tester. Les posts sandbox sont privés.</li>
            <li>Une fois validé, soumettez l'app à <em>Review</em> pour passer en production publique.</li>
            <li>Récupérez le <strong>Client Key</strong> et <strong>Client Secret</strong> et collez-les ci-dessous.</li>
          </ol>
          <p className="mt-2 text-[10px]"><strong>📌 Tokens</strong> : access_token = 24h (refresh auto), refresh_token = 365j.</p>
        </div>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">TikTok Client Key</span>
          <input value={form.tiktok_client_key || ""} onChange={update("tiktok_client_key")}
                 placeholder="aw_xxxxxxxxxxxxxx"
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="settings-tiktok-client-key" />
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">TikTok Client Secret {settings.tiktok_client_secret_set && <span className="text-[10px] text-emerald-600 ml-1">✓ configuré</span>}</span>
          <input type="password" value={form.tiktok_client_secret || ""} onChange={update("tiktok_client_secret")}
                 placeholder={settings.tiktok_client_secret_set ? "Laisser vide pour conserver" : "Client secret"}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="settings-tiktok-client-secret" />
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">TikTok Redirect URI <span className="text-slate-400 font-normal">(laisser vide pour auto-détection)</span></span>
          <input value={form.tiktok_redirect_uri || ""} onChange={update("tiktok_redirect_uri")}
                 placeholder={`${window.location.origin}/api/admin/story-studio/oauth/tiktok/callback`}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="settings-tiktok-redirect" />
        </label>

        {/* Iter43-fix24az-p — TikTok Privacy Level toggle mis en avant */}
        <div className="rounded-lg border-2 border-pink-300 bg-gradient-to-br from-pink-50 to-fuchsia-50 p-4 space-y-2" data-testid="tiktok-privacy-panel">
          <div className="flex items-start gap-2">
            <div className="mt-0.5">🔒</div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-pink-900">Visibilité par défaut des publications TikTok</p>
              <p className="text-[11px] text-pink-700 mt-0.5">
                Sélectionnez le mode de publication par défaut. En Sandbox ou tant que l&apos;app TikTok n&apos;est pas approuvée en review, seul <strong>Privé (SELF_ONLY)</strong> est autorisé.
              </p>
            </div>
            <span className={`text-[11px] font-semibold px-2 py-1 rounded ${
              (form.tiktok_privacy_level || "SELF_ONLY") === "SELF_ONLY" ? "bg-emerald-100 text-emerald-700" : "bg-orange-100 text-orange-700"
            }`} data-testid="tiktok-privacy-badge">
              {(form.tiktok_privacy_level || "SELF_ONLY") === "SELF_ONLY" ? "🔒 Privé" : "🌐 Public"}
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
            {[
              { v: "SELF_ONLY", label: "🔒 Privé — visible uniquement par vous", desc: "Aucune diffusion publique. Recommandé en sandbox / audit." },
              { v: "MUTUAL_FOLLOW_FRIENDS", label: "👥 Amis mutuels", desc: "Visible par les personnes qui vous suivent en réciproque." },
              { v: "FOLLOWER_OF_CREATOR", label: "🎯 Abonnés", desc: "Visible par vos abonnés." },
              { v: "PUBLIC_TO_EVERYONE", label: "🌐 Public", desc: "Visible par tous. Nécessite audit approuvé côté TikTok." },
            ].map((opt) => {
              const selected = (form.tiktok_privacy_level || "SELF_ONLY") === opt.v;
              return (
                <label
                  key={opt.v}
                  className={`flex items-start gap-2 p-2 rounded-lg cursor-pointer border-2 transition ${
                    selected ? "border-pink-500 bg-white shadow-sm" : "border-transparent hover:bg-white/60"
                  }`}
                  data-testid={`tiktok-privacy-option-${opt.v}`}
                >
                  <input
                    type="radio"
                    name="tiktok_privacy_level"
                    value={opt.v}
                    checked={selected}
                    onChange={() => setForm({ ...form, tiktok_privacy_level: opt.v })}
                    className="mt-1 accent-pink-600"
                  />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-800">{opt.label}</p>
                    <p className="text-[10px] text-slate-500 mt-0.5">{opt.desc}</p>
                  </div>
                </label>
              );
            })}
          </div>
          <p className="text-[10px] text-pink-700 italic pt-1">
            💡 Ce réglage s&apos;applique à toutes les publications TikTok créées depuis le studio. Le mode réel utilisé peut être ajusté par TikTok si votre app n&apos;a pas encore l&apos;autorisation demandée.
          </p>
        </div>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-slate-700">📝 Légende par défaut</legend>
        <textarea value={form.default_caption_template || ""} onChange={update("default_caption_template")}
                  rows={2}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  placeholder="✨ {title}&#10;&#10;#SAWALI #Liluvine"
                  data-testid="settings-caption-template" />
        <p className="text-[10px] text-slate-500">Variables disponibles : <code>{"{title}"}</code></p>
      </fieldset>

      <button type="submit" disabled={saving}
              className="w-full rounded-lg bg-slate-900 text-white hover:bg-slate-800 px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
              data-testid="settings-save">
        {saving ? "Enregistrement…" : "💾 Enregistrer les paramètres"}
      </button>
    </form>
  );
}

// ============================================================
// Iter43-fix13 — TAB : Facturation (multi-tenant)
// ============================================================
function BillingTab() {
  const [tab, setTab] = React.useState("summary"); // summary | tenants | tenant_detail
  const [selectedTenant, setSelectedTenant] = React.useState(null);

  return (
    <div className="space-y-4" data-testid="billing-tab">
      <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
        <button onClick={() => { setTab("summary"); setSelectedTenant(null); }}
                className={`text-xs inline-flex items-center gap-1.5 px-3 py-1.5 rounded ${tab === "summary" ? "bg-white shadow text-violet-700" : "text-slate-600 hover:text-slate-900"}`}
                data-testid="billing-tab-summary">
          <TrendingUp className="h-3 w-3" /> Vue d'ensemble
        </button>
        <button onClick={() => { setTab("tenants"); setSelectedTenant(null); }}
                className={`text-xs inline-flex items-center gap-1.5 px-3 py-1.5 rounded ${tab === "tenants" ? "bg-white shadow text-violet-700" : "text-slate-600 hover:text-slate-900"}`}
                data-testid="billing-tab-tenants">
          <Wallet className="h-3 w-3" /> Tenants
        </button>
      </div>

      {tab === "summary" && <BillingSummary />}
      {tab === "tenants" && !selectedTenant && (
        <TenantsList onSelect={(t) => { setSelectedTenant(t); setTab("tenant_detail"); }} />
      )}
      {tab === "tenant_detail" && selectedTenant && (
        <TenantBillingDetail
          tenantId={selectedTenant.tenant_id}
          tenantLabel={selectedTenant.tenant_label || selectedTenant.tenant_id}
          onBack={() => { setSelectedTenant(null); setTab("tenants"); }}
        />
      )}
    </div>
  );
}

function BillingSummary() {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/story-studio/billing/summary");
      setData(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  if (loading) return <div className="text-center py-8 text-slate-400">Chargement…</div>;
  if (!data) return null;

  return (
    <div className="space-y-4" data-testid="billing-summary">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          icon={Coins} color="emerald"
          label="Crédits en circulation"
          value={fmtXOF(data.total_credits_in_circulation)}
          testid="stat-credits-circulation"
        />
        <StatCard
          icon={FileTextIcon} color="amber"
          label={`Factures ${data.period} (à payer)`}
          value={fmtXOF(data.current_period_invoices_total)}
          sub={`${data.current_period_open_invoices} ouverte(s)`}
          testid="stat-invoices-current"
        />
        <StatCard
          icon={TrendingUp} color="violet"
          label="Top consommateurs"
          value={`${data.top_consumers.length}`}
          sub="ce mois-ci"
          testid="stat-top-consumers"
        />
      </div>
      {data.top_consumers.length > 0 && (
        <div className="bg-white rounded-xl ring-1 ring-slate-200 p-4">
          <h3 className="text-sm font-semibold mb-3">Top 10 consommateurs ({data.period})</h3>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="text-left px-2 py-1.5">Tenant</th>
                <th className="text-right px-2 py-1.5">Publications</th>
                <th className="text-right px-2 py-1.5">Total facturé</th>
              </tr>
            </thead>
            <tbody>
              {data.top_consumers.map((c) => (
                <tr key={c.tenant_id} className="border-t border-slate-100" data-testid={`top-consumer-${c.tenant_id}`}>
                  <td className="px-2 py-1.5 font-mono text-xs">{c.tenant_id.slice(0, 12)}…</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{c.publications}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums font-semibold text-violet-700">{fmtXOF(c.total_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatCard({ icon: Icon, color, label, value, sub, testid }) {
  const colors = {
    emerald: "from-emerald-50 to-white ring-emerald-200 text-emerald-700",
    amber: "from-amber-50 to-white ring-amber-200 text-amber-700",
    violet: "from-violet-50 to-white ring-violet-200 text-violet-700",
  }[color] || "from-slate-50 to-white ring-slate-200 text-slate-700";
  return (
    <div className={`rounded-xl bg-gradient-to-br ${colors} ring-1 p-4`} data-testid={testid}>
      <div className="flex items-start justify-between">
        <p className="text-[11px] uppercase tracking-wider opacity-80">{label}</p>
        <Icon className="h-4 w-4 opacity-70" />
      </div>
      <p className="text-2xl font-bold tabular-nums mt-2">{value}</p>
      {sub && <p className="text-[11px] opacity-70 mt-1">{sub}</p>}
    </div>
  );
}

function TenantsList({ onSelect }) {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/story-studio/billing/tenants");
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  if (loading) return <div className="text-center py-8 text-slate-400">Chargement…</div>;
  if (items.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400 italic bg-white rounded-xl ring-1 ring-slate-200" data-testid="no-tenants">
        Aucun tenant facturable. Les tenants apparaissent ici dès qu'ils connectent un compte Meta ou reçoivent un crédit.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl ring-1 ring-slate-200 overflow-hidden" data-testid="tenants-list">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-slate-600 text-xs">
          <tr>
            <th className="text-left px-3 py-2">Tenant</th>
            <th className="text-left px-3 py-2">Mode</th>
            <th className="text-right px-3 py-2">Crédits</th>
            <th className="text-right px-3 py-2">Pub. ce mois</th>
            <th className="text-right px-3 py-2">Total ce mois</th>
            <th className="text-right px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr key={t.tenant_id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`tenant-row-${t.tenant_id}`}>
              <td className="px-3 py-2">
                <p className="font-medium text-slate-900">{t.tenant_label || <span className="font-mono text-xs">{t.tenant_id.slice(0, 16)}</span>}</p>
                {t.tenant_email && <p className="text-[10px] text-slate-500">{t.tenant_email}</p>}
              </td>
              <td className="px-3 py-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-700">
                  {t.billing_mode === "credits_first" ? "Crédits puis facture"
                    : t.billing_mode === "credits_only" ? "Crédits uniquement"
                    : "Facture uniquement"}
                </span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums font-semibold">
                <span className={t.credits_balance > 0 ? "text-emerald-700" : "text-slate-400"}>
                  {fmtXOF(t.credits_balance)}
                </span>
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{t.current_period_publications || 0}</td>
              <td className="px-3 py-2 text-right tabular-nums font-semibold text-violet-700">{fmtXOF(t.current_period_total)}</td>
              <td className="px-3 py-2 text-right">
                <button onClick={() => onSelect(t)}
                        className="text-[11px] px-2 py-1 rounded bg-violet-50 text-violet-700 hover:bg-violet-100"
                        data-testid={`view-tenant-${t.tenant_id}`}>
                  Détails →
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TenantBillingDetail({ tenantId, tenantLabel, onBack }) {
  const [cfg, setCfg] = React.useState(null);
  const [ledger, setLedger] = React.useState([]);
  const [invoices, setInvoices] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(false);
  const [topupOpen, setTopupOpen] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [r1, r2, r3] = await Promise.all([
        apiClient.get(`/admin/story-studio/billing/tenants/${tenantId}/config`),
        apiClient.get(`/admin/story-studio/billing/tenants/${tenantId}/ledger`, { params: { limit: 50 } }),
        apiClient.get(`/admin/story-studio/billing/tenants/${tenantId}/invoices`),
      ]);
      setCfg(r1.data);
      setLedger(r2.data?.items || []);
      setInvoices(r3.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally { setLoading(false); }
  }, [tenantId]);
  React.useEffect(() => { load(); }, [load]);

  const markPaid = async (invId) => {
    if (!window.confirm("Marquer cette facture comme payée ?")) return;
    try {
      await apiClient.put(`/admin/story-studio/billing/invoices/${invId}/status`, { status: "paid" });
      toast.success("Facture marquée payée");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  if (loading || !cfg) return <div className="text-center py-8 text-slate-400">Chargement…</div>;

  return (
    <div className="space-y-4" data-testid="tenant-billing-detail">
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="text-xs text-slate-600 hover:text-slate-900" data-testid="back-to-tenants">
          ← Retour à la liste
        </button>
        <button onClick={() => setTopupOpen(true)}
                className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                data-testid="topup-credits-btn">
          <Coins className="h-3 w-3" /> Créditer
        </button>
      </div>

      <div className="bg-white rounded-xl ring-1 ring-slate-200 p-4">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-semibold">{tenantLabel}</h3>
            <p className="text-[10px] font-mono text-slate-400">{tenantId}</p>
          </div>
          <button onClick={() => setEditing(true)}
                  className="text-xs px-2 py-1 rounded bg-sky-50 text-sky-700 hover:bg-sky-100"
                  data-testid="edit-config-btn">
            Modifier les tarifs
          </button>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <KV label="Mode" value={cfg.billing_mode} />
          <KV label="Solde crédits" value={<span className="font-bold text-emerald-700">{fmtXOF(cfg.credits_balance)}</span>} />
          <KV label="Devise" value={cfg.currency} />
          <KV label="Jour facture" value={cfg.monthly_invoice_day} />
        </div>
        <div className="mt-3 pt-3 border-t border-slate-100">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Tarifs unitaires</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <PricingChip icon={Facebook} label="FB Feed" value={fmtXOF(cfg.pricing.fb_feed)} />
            <PricingChip icon={Instagram} label="IG Story" value={fmtXOF(cfg.pricing.ig_story)} />
            <PricingChip icon={Instagram} label="IG Reel" value={fmtXOF(cfg.pricing.ig_reel)} />
            <PricingChip icon={Video} label="TikTok" value={fmtXOF(cfg.pricing.tiktok)} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white rounded-xl ring-1 ring-slate-200 p-4">
          <h3 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
            <FileTextIcon className="h-4 w-4 text-amber-600" /> Factures mensuelles
          </h3>
          {invoices.length === 0 ? (
            <p className="text-xs text-slate-400 italic">Aucune facture.</p>
          ) : (
            <div className="space-y-1.5">
              {invoices.map((i) => (
                <div key={i.id} className="flex items-center gap-2 p-2 rounded bg-slate-50 text-xs" data-testid={`invoice-${i.id}`}>
                  <span className="font-mono text-[10px]">{i.period}</span>
                  <span className="flex-1 tabular-nums font-semibold">{fmtXOF(i.amount_due)}</span>
                  <span className="text-slate-500">{i.publications_count} pub.</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    i.status === "paid" ? "bg-emerald-50 text-emerald-700" :
                    i.status === "cancelled" ? "bg-slate-200 text-slate-600" :
                    "bg-amber-100 text-amber-800"
                  }`}>{i.status}</span>
                  {i.status === "open" && (
                    <button onClick={() => markPaid(i.id)} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-600 text-white hover:bg-emerald-700"
                            data-testid={`mark-paid-${i.id}`}>
                      Marquer payée
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl ring-1 ring-slate-200 p-4">
          <h3 className="text-sm font-semibold mb-2 inline-flex items-center gap-1.5">
            <HistoryIcon className="h-4 w-4 text-slate-600" /> Journal (50 dernières lignes)
          </h3>
          {ledger.length === 0 ? (
            <p className="text-xs text-slate-400 italic">Aucune entrée.</p>
          ) : (
            <div className="space-y-1 max-h-80 overflow-y-auto">
              {ledger.map((l) => (
                <div key={l.id} className="flex items-center gap-2 text-[11px] p-1.5 rounded hover:bg-slate-50" data-testid={`ledger-${l.id}`}>
                  <span className="text-[9px] text-slate-400 font-mono">{l.created_at?.slice(11, 16)}</span>
                  <span className={`text-[9px] px-1 py-0.5 rounded ${l.type === "topup" ? "bg-emerald-100 text-emerald-700" : "bg-violet-100 text-violet-700"}`}>
                    {l.type === "topup" ? "+CR" : "PUB"}
                  </span>
                  <span className="flex-1 truncate">
                    {l.type === "topup"
                      ? `Crédit (${l.reason || "manuel"})`
                      : `${l.target} → ${l.settlement}`}
                  </span>
                  <span className={`tabular-nums font-semibold ${l.type === "topup" ? "text-emerald-700" : "text-rose-700"}`}>
                    {l.type === "topup" ? "+" : "−"}{fmtXOF(l.type === "topup" ? l.amount : l.cost)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {editing && <ConfigEditModal cfg={cfg} tenantId={tenantId} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load(); }} />}
      {topupOpen && <TopupModal tenantId={tenantId} currency={cfg.currency} onClose={() => setTopupOpen(false)} onDone={() => { setTopupOpen(false); load(); }} />}
    </div>
  );
}

function KV({ label, value }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-sm font-medium text-slate-900">{value}</p>
    </div>
  );
}

function PricingChip({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-1.5 p-2 rounded bg-slate-50 ring-1 ring-slate-100">
      <Icon className="h-3 w-3 text-slate-500" />
      <span className="text-[10px] text-slate-600">{label}</span>
      <span className="ml-auto font-semibold tabular-nums text-xs">{value}</span>
    </div>
  );
}

function ConfigEditModal({ cfg, tenantId, onClose, onSaved }) {
  const [form, setForm] = React.useState({
    pricing: { ...cfg.pricing },
    currency: cfg.currency || "XOF",
    billing_mode: cfg.billing_mode || "credits_first",
    monthly_invoice_day: cfg.monthly_invoice_day || 1,
    notes: cfg.notes || "",
  });
  const [saving, setSaving] = React.useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await apiClient.put(`/admin/story-studio/billing/tenants/${tenantId}/config`, form);
      toast.success("Configuration sauvegardée");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-4" data-testid="config-edit-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-md">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold inline-flex items-center gap-1.5">
            <SettingsIcon className="h-4 w-4 text-sky-600" /> Tarifs et facturation
          </h3>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          <label className="block text-sm">
            <span className="block text-xs font-semibold mb-1">Mode de facturation</span>
            <select value={form.billing_mode}
                    onChange={(e) => setForm({ ...form, billing_mode: e.target.value })}
                    className="w-full px-3 py-2 border rounded text-sm" data-testid="billing-mode-select">
              <option value="credits_first">Crédits puis facture (recommandé)</option>
              <option value="credits_only">Crédits uniquement (bloque si vide)</option>
              <option value="invoice_only">Facture mensuelle uniquement</option>
            </select>
          </label>
          <div>
            <p className="text-xs font-semibold mb-2">Tarifs unitaires (XOF)</p>
            <div className="grid grid-cols-2 gap-2">
              {[["fb_feed", "FB Feed"], ["ig_story", "IG Story"], ["ig_reel", "IG Reel"], ["tiktok", "TikTok"]].map(([k, lbl]) => (
                <label key={k} className="block text-xs">
                  <span className="text-slate-600">{lbl}</span>
                  <input type="number" min={0}
                         value={form.pricing[k] ?? 0}
                         onChange={(e) => setForm({ ...form, pricing: { ...form.pricing, [k]: Number(e.target.value) || 0 } })}
                         className="w-full px-2 py-1 border rounded mt-0.5 text-sm"
                         data-testid={`pricing-${k}`} />
                </label>
              ))}
            </div>
          </div>
          <label className="block text-sm">
            <span className="block text-xs font-semibold mb-1">Jour de clôture facture (1-28)</span>
            <input type="number" min={1} max={28}
                   value={form.monthly_invoice_day}
                   onChange={(e) => setForm({ ...form, monthly_invoice_day: Number(e.target.value) || 1 })}
                   className="w-full px-3 py-2 border rounded text-sm" data-testid="invoice-day-input" />
          </label>
          <label className="block text-sm">
            <span className="block text-xs font-semibold mb-1">Notes</span>
            <textarea rows={2} value={form.notes}
                      onChange={(e) => setForm({ ...form, notes: e.target.value })}
                      className="w-full px-3 py-2 border rounded text-sm" />
          </label>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300">Annuler</button>
          <button type="submit" disabled={saving}
                  className="px-3 py-2 rounded text-sm bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
                  data-testid="config-save-btn">
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
    </div>
  );
}

function TopupModal({ tenantId, currency, onClose, onDone }) {
  const [amount, setAmount] = React.useState(5000);
  const [reason, setReason] = React.useState("admin_topup");
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await apiClient.post(`/admin/story-studio/billing/tenants/${tenantId}/credits/topup`,
        { amount_xof: Number(amount), reason, note });
      toast.success(`Crédité — nouveau solde : ${fmtXOF(r.data.balance)}`);
      onDone();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" data-testid="topup-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-sm">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h3 className="font-display font-semibold inline-flex items-center gap-1.5">
            <Coins className="h-4 w-4 text-emerald-600" /> Créditer le tenant
          </h3>
          <button type="button" onClick={onClose} className="text-slate-500"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3">
          <label className="block text-sm">
            <span className="block text-xs font-semibold mb-1">Montant ({currency})</span>
            <input type="number" min={100} step={100}
                   value={amount}
                   onChange={(e) => setAmount(e.target.value)}
                   className="w-full px-3 py-2 border rounded text-sm font-mono"
                   data-testid="topup-amount" required />
          </label>
          <label className="block text-sm">
            <span className="block text-xs font-semibold mb-1">Motif</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)}
                   className="w-full px-3 py-2 border rounded text-sm" data-testid="topup-reason" />
          </label>
          <label className="block text-sm">
            <span className="block text-xs font-semibold mb-1">Note (optionnelle)</span>
            <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)}
                      className="w-full px-3 py-2 border rounded text-sm" />
          </label>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200">Annuler</button>
          <button type="submit" disabled={busy}
                  className="px-3 py-2 rounded text-sm bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                  data-testid="topup-submit">
            {busy ? "Crédit en cours…" : "Créditer"}
          </button>
        </div>
      </form>
    </div>
  );
}

