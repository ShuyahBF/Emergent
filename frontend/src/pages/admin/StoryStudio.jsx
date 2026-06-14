// Iter43-fix10 (2026-03) — Story Studio (Phase 1 MVP)
// =====================================================================
// Génération de vidéos/images AI au format Story (9:16) + bibliothèque
// + bouton "Partager WhatsApp" (deep link mobile).
// Phase 2 ajoutera : OAuth Meta/TikTok + publication automatique IG/FB/TikTok.

import React from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Video, Image as ImageIcon, Loader2, Download, Share2,
  Trash2, RefreshCw, Wand2, Settings as SettingsIcon, AlertTriangle,
  Smartphone, Copy, X, Clock,
} from "lucide-react";

export default function StoryStudio() {
  const [tab, setTab] = React.useState("generate"); // generate | library | settings | social
  const [library, setLibrary] = React.useState([]);
  const [libraryLoading, setLibraryLoading] = React.useState(false);
  const [settings, setSettings] = React.useState(null);
  const [shareModal, setShareModal] = React.useState(null);

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

  return (
    <div className="space-y-5" data-testid="story-studio">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-violet-600" /> Story Studio
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Génération AI de vidéos & images au format Story (9:16) + partage WhatsApp manuel-assisté.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
          {[
            { v: "generate", label: "Créer", icon: Wand2 },
            { v: "library", label: "Bibliothèque", icon: Video },
            { v: "social", label: "Comptes sociaux", icon: Share2 },
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

      {/* Banner Phase 2 */}
      <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900 flex items-start gap-2" data-testid="phase2-banner">
        <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
        <div>
          <strong>Phase 1 MVP active</strong> — La génération IA et le partage WhatsApp manuel-assisté fonctionnent.
          La publication automatique IG/FB/TikTok arrive en Phase 2 (OAuth Meta + TikTok Content Posting API).
          En attendant, partagez via le bouton WhatsApp ou téléchargez le média pour publier vous-même.
        </div>
      </div>

      {tab === "generate" && <GenerateTab settings={settings} onCreated={loadLibrary} />}
      {tab === "library" && (
        <LibraryTab
          items={library}
          loading={libraryLoading}
          onRefresh={loadLibrary}
          onShare={setShareModal}
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
      {tab === "social" && <SocialAccountsTab />}
      {tab === "settings" && <SettingsTab settings={settings} onSaved={loadSettings} />}

      {shareModal && <ShareWhatsAppModal asset={shareModal} onClose={() => setShareModal(null)} />}
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
function LibraryTab({ items, loading, onRefresh, onShare, onDelete }) {
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
          {items.map((it) => <AssetCard key={it.id} asset={it} onShare={onShare} onDelete={onDelete} />)}
        </div>
      )}
    </div>
  );
}

function AssetCard({ asset, onShare, onDelete }) {
  const isVideo = asset.kind === "video";
  const isReady = asset.status === "ready";
  const isProcessing = asset.status === "processing";
  const isFailed = asset.status === "failed";
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
        ) : null}
        <span className="absolute top-2 left-2 text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded bg-white/90 backdrop-blur ring-1 ring-slate-200">
          {isVideo ? "Vidéo" : "Image"} · {asset.engine}
        </span>
      </div>
      <div className="p-3 space-y-2">
        <p className="text-sm font-medium text-slate-900 line-clamp-1" title={asset.title}>{asset.title || "Sans titre"}</p>
        <p className="text-[11px] text-slate-500 line-clamp-2">{asset.prompt}</p>
        <div className="flex items-center gap-1 flex-wrap pt-1">
          {isReady && (
            <>
              <button onClick={downloadAsset}
                 className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700"
                 data-testid={`asset-download-${asset.id}`}>
                <Download className="h-3 w-3" /> Télécharger
              </button>
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
// TAB : Comptes sociaux (scaffolding Phase 2)
// ============================================================
function SocialAccountsTab() {
  const [accounts, setAccounts] = React.useState([]);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/story-studio/social-accounts");
      setAccounts(r.data?.items || []);
    } catch { /* noop */ }
    finally { setLoading(false); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  return (
    <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 p-5 space-y-4" data-testid="social-accounts-tab">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold inline-flex items-center gap-2">
            <Share2 className="h-4 w-4 text-sky-600" /> Comptes sociaux connectés
          </h2>
          <p className="text-xs text-slate-500 mt-1">Phase 2 — OAuth en cours d'implémentation</p>
        </div>
      </div>

      <div className="rounded-lg bg-sky-50 ring-1 ring-sky-200 p-3 text-xs text-sky-900">
        <strong>🚧 Phase 2 — OAuth automatique en développement.</strong>
        <p className="mt-1">En attendant, vous pouvez ajouter un token manuellement (mode dev) pour tester. Les tokens long-lived peuvent être obtenus via Graph API Explorer (Meta) ou TikTok Developer Portal.</p>
      </div>

      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-slate-600">
          <tr>
            <th className="text-left px-3 py-2">Tenant</th>
            <th className="text-left px-3 py-2">Réseau</th>
            <th className="text-left px-3 py-2">Compte</th>
            <th className="text-left px-3 py-2">Statut</th>
            <th className="text-left px-3 py-2">Ajouté</th>
          </tr>
        </thead>
        <tbody>
          {loading && <tr><td colSpan={5} className="px-3 py-4 text-center text-slate-400">Chargement…</td></tr>}
          {!loading && accounts.length === 0 && (
            <tr><td colSpan={5} className="px-3 py-4 text-center text-slate-400 italic">Aucun compte connecté.</td></tr>
          )}
          {accounts.map((a) => (
            <tr key={a.id} className="border-t border-slate-100">
              <td className="px-3 py-2 text-xs">{a.tenant_id?.slice(0, 8)}</td>
              <td className="px-3 py-2 text-xs capitalize">{a.provider}</td>
              <td className="px-3 py-2 text-xs">{a.account_label}</td>
              <td className="px-3 py-2"><span className="text-[10px] px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">{a.status}</span></td>
              <td className="px-3 py-2 text-[11px] text-slate-500">{a.created_at?.slice(0, 16).replace("T", " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
          <span className="block text-xs font-semibold text-slate-700 mb-1">Meta Redirect URI</span>
          <input value={form.meta_redirect_uri || ""} onChange={update("meta_redirect_uri")}
                 placeholder="https://sawalismartsystems.com/admin/story-studio/oauth/meta/callback"
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="settings-meta-redirect" />
        </label>
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-pink-700">🎵 TikTok</legend>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">TikTok Client Key</span>
          <input value={form.tiktok_client_key || ""} onChange={update("tiktok_client_key")}
                 placeholder="awxxxxxxxxxxxxxx"
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="settings-tiktok-key" />
          <p className="text-[10px] text-slate-500 mt-1">À créer sur <a href="https://developers.tiktok.com" target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline">developers.tiktok.com</a></p>
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">TikTok Client Secret {settings.tiktok_client_secret_set && <span className="text-[10px] text-emerald-600 ml-1">✓ configurée</span>}</span>
          <input type="password" value={form.tiktok_client_secret || ""} onChange={update("tiktok_client_secret")}
                 placeholder={settings.tiktok_client_secret_set ? "Laisser vide pour conserver" : "Client secret"}
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="settings-tiktok-secret" />
        </label>
        <label className="block">
          <span className="block text-xs font-semibold text-slate-700 mb-1">TikTok Redirect URI</span>
          <input value={form.tiktok_redirect_uri || ""} onChange={update("tiktok_redirect_uri")}
                 placeholder="https://sawalismartsystems.com/admin/story-studio/oauth/tiktok/callback"
                 className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="settings-tiktok-redirect" />
        </label>
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
