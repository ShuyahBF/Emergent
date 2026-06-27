// =====================================================================
// Iter43-fix24ax (2026-02-26) — Facebook Page admin section.
// Compact UI: App config, OAuth connect, list Pages, pick active Page, compose post, list feed.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Loader2, ExternalLink, Send, RefreshCw, Trash2, Copy, Check, AlertCircle, Facebook, Building2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const FacebookSection = () => {
  const [cfg, setCfg] = useState(null);
  const [redirect, setRedirect] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [pages, setPages] = useState([]);
  const [loadingPages, setLoadingPages] = useState(false);
  const [postText, setPostText] = useState("");
  const [postImage, setPostImage] = useState("");
  const [posting, setPosting] = useState(false);
  const [feed, setFeed] = useState([]);
  const [reveal, setReveal] = useState(false);
  // Iter43-fix24az-c — Test config (validates App ID/Secret without OAuth)
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, p] = await Promise.all([
        apiClient.get("/admin/facebook/config"),
        apiClient.get("/admin/facebook/oauth/preview-redirect-uri").catch(() => null),
      ]);
      setCfg(c.data);
      if (p?.data?.redirect_uri) setRedirect(p.data.redirect_uri);
    } catch { setCfg(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const onMsg = (e) => {
      if (e?.data?.type !== "facebook-oauth-result") return;
      if (e.data.success) { toast.success(e.data.message); load(); }
      else toast.error(e.data.message);
      setConnecting(false);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        app_id: cfg.app_id,
        ...(cfg.app_secret && cfg.app_secret !== "********" ? { app_secret: cfg.app_secret } : {}),
        redirect_uri: cfg.redirect_uri,
      };
      await apiClient.put("/admin/facebook/config", body);
      toast.success("Config Facebook enregistrée"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setSaving(false); }
  };

  const testConfig = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await apiClient.post("/admin/facebook/test-config");
      setTestResult(r.data);
      if (r.data?.ok) toast.success("✓ App ID + Secret valides");
      else toast.error(`✗ Échec : ${r.data?.fb_error_message || "secret invalide"}`);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Erreur";
      setTestResult({ ok: false, fb_error_message: detail, status_code: e?.response?.status || 0 });
      toast.error(detail);
    } finally { setTesting(false); }
  };

  const connect = async () => {
    setConnecting(true);
    try {
      const r = await apiClient.get("/admin/facebook/oauth/authorize");
      const w = 600, h = 720;
      const left = window.screenX + (window.outerWidth - w) / 2;
      const top = window.screenY + (window.outerHeight - h) / 2;
      const p = window.open(r.data.authorization_url, "facebook-oauth", `width=${w},height=${h},left=${left},top=${top}`);
      if (!p) window.location.href = r.data.authorization_url;
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); setConnecting(false); }
  };

  const disconnect = async () => {
    if (!window.confirm("Déconnecter Facebook ?")) return;
    try { await apiClient.delete("/admin/facebook/connection"); toast.success("Déconnecté"); setPages([]); setFeed([]); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const loadPages = async () => {
    setLoadingPages(true);
    try {
      const r = await apiClient.get("/admin/facebook/pages");
      setPages(r.data?.pages || []);
      if ((r.data?.pages || []).length === 0) {
        toast.info("Aucune Page Facebook administrée détectée. Vérifiez les scopes pages_show_list + pages_manage_posts.");
      }
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setLoadingPages(false); }
  };

  const pickPage = async (p) => {
    if (!window.confirm(`Définir « ${p.name} » comme Page active pour les publications ?`)) return;
    try {
      await apiClient.put("/admin/facebook/active-page", { page_id: p.id, page_access_token: p.access_token, page_name: p.name });
      toast.success(`Page active : ${p.name}`);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const post = async () => {
    if (!postText.trim()) return toast.warning("Texte requis");
    setPosting(true);
    try {
      const r = await apiClient.post("/facebook/posts", { text: postText, ...(postImage ? { image_url: postImage } : {}) });
      toast.success(`Post publié : ${r.data?.post_id || "OK"}`);
      setPostText(""); setPostImage(""); loadFeed();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setPosting(false); }
  };

  const loadFeed = useCallback(async () => {
    if (!cfg?.active_page_id) return;
    try {
      const r = await apiClient.get("/facebook/posts?limit=10");
      setFeed(r.data?.items || []);
    } catch { setFeed([]); }
  }, [cfg?.active_page_id]);

  useEffect(() => { loadFeed(); }, [loadFeed]);

  if (loading) return <div className="p-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin inline mr-2" />Chargement Facebook…</div>;

  return (
    <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5 space-y-4" data-testid="admin-facebook-section">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-bold inline-flex items-center gap-2">
          <Facebook className="h-5 w-5 text-[#1877f2]" /> Facebook Page — Posts
        </h2>
        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${cfg?.active_page_id ? "bg-emerald-100 text-emerald-700" : cfg?.connected ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"}`} data-testid="facebook-status-badge">
          {cfg?.active_page_id ? `✓ ${cfg.active_page_name}` : cfg?.connected ? "⚠ Pas de Page" : "○ Non connecté"}
        </span>
      </header>

      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
        <h3 className="text-xs uppercase text-slate-600 font-semibold">1. App Facebook</h3>
        <p className="text-[11px] text-slate-500">
          Créez une App sur{" "}
          <a href="https://developers.facebook.com/apps/" target="_blank" rel="noreferrer" className="text-[#1877f2] underline">
            developers.facebook.com <ExternalLink className="inline h-3 w-3" />
          </a>{" "} avec Facebook Login pour le Business + Page produit.
        </p>
        <div className="grid sm:grid-cols-2 gap-2">
          <label className="block"><span className="block text-xs text-slate-700 mb-1">App ID</span>
            <input type="text" value={cfg?.app_id || ""} onChange={(e) => setCfg({...cfg, app_id: e.target.value})} className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="facebook-app-id" /></label>
          <label className="block"><span className="block text-xs text-slate-700 mb-1">App Secret</span>
            <div className="flex gap-1">
              <input type={reveal ? "text" : "password"} value={cfg?.app_secret || ""} onChange={(e) => setCfg({...cfg, app_secret: e.target.value})} className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="facebook-app-secret" />
              <button onClick={() => setReveal(!reveal)} className="text-xs px-2 rounded ring-1 ring-slate-300">{reveal ? "🙈" : "👁"}</button>
            </div></label>
        </div>
        {/* Iter43-fix24az — Editable Redirect URI override (PROD vs PREVIEW) */}
        <label className="block">
          <span className="block text-xs text-slate-700 mb-1">
            Redirect URI <span className="text-slate-400">(facultatif — auto-calculé depuis l&apos;URL courante si vide)</span>
          </span>
          <div className="flex gap-1">
            <input
              type="text"
              value={cfg?.redirect_uri || ""}
              onChange={(e) => setCfg({...cfg, redirect_uri: e.target.value})}
              className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
              placeholder={`${window.location.origin}/api/facebook/oauth/callback`}
              data-testid="facebook-redirect-uri-input"
            />
            <button
              type="button"
              onClick={() => setCfg({...cfg, redirect_uri: ""})}
              className="text-xs px-2 py-1.5 rounded bg-slate-100 ring-1 ring-slate-300 hover:bg-slate-200"
              data-testid="facebook-clear-redirect"
              title="Effacer pour utiliser l'URL automatique de l'environnement courant"
            >
              Auto
            </button>
            <button
              type="button"
              onClick={() => setCfg({...cfg, redirect_uri: `${window.location.origin}/api/facebook/oauth/callback`})}
              className="text-xs px-2 py-1.5 rounded bg-slate-100 ring-1 ring-slate-300 hover:bg-slate-200"
              data-testid="facebook-use-current-redirect"
              title="Pré-remplir avec l'URL de l'environnement actuel"
            >
              Cet env
            </button>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">
            ⚠️ Si vous testez sur PROD <strong>et</strong> PREVIEW, laissez ce champ vide et ajoutez les deux URL ci-dessous dans Facebook Login → Settings.
          </p>
        </label>
        {redirect && (
          <div className="rounded ring-2 ring-amber-300 bg-amber-50 p-2 text-xs space-y-1" data-testid="facebook-redirect-warning">
            <p className="font-semibold text-amber-900 inline-flex items-center gap-1"><AlertCircle className="h-3 w-3" /> Redirect URI effectif (à enregistrer dans Facebook Login → Settings)</p>
            <div className="flex gap-1">
              <code className="flex-1 bg-white px-2 py-1 rounded ring-1 ring-amber-300 text-[10px] font-mono break-all" data-testid="facebook-redirect-uri-computed">{redirect}</code>
              <button onClick={() => { navigator.clipboard.writeText(redirect); toast.success("Copié"); }} className="text-[10px] px-2 py-1 rounded bg-amber-600 hover:bg-amber-700 text-white inline-flex items-center gap-1" data-testid="facebook-copy-redirect"><Copy className="h-3 w-3" />Copier</button>
            </div>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <button onClick={save} disabled={saving} className="text-xs px-3 py-1.5 rounded bg-slate-800 text-white inline-flex items-center gap-1 disabled:opacity-50" data-testid="facebook-save-config">
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />} Enregistrer
          </button>
          <button onClick={testConfig} disabled={testing || !cfg?.app_id} className="text-xs px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white inline-flex items-center gap-1 disabled:opacity-50" data-testid="facebook-test-config">
            {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : "🧪"} Tester App ID/Secret
          </button>
        </div>
        {testResult && (
          <div
            className={`rounded ring-1 p-2 text-[11px] space-y-1 ${testResult.ok ? "bg-emerald-50 ring-emerald-300 text-emerald-900" : "bg-rose-50 ring-rose-300 text-rose-900"}`}
            data-testid="facebook-test-result"
          >
            <p className="font-semibold">{testResult.ok ? "✅ Credentials valides" : "❌ Credentials rejetés par Facebook"}</p>
            <p>HTTP <code className="font-mono">{testResult.status_code}</code> · App ID utilisée : <code className="font-mono">{testResult.app_id_masked || "—"}</code></p>
            {testResult.message && <p>{testResult.message}</p>}
            {testResult.fb_error_message && (
              <p className="break-words">
                <strong>Erreur FB :</strong> <code className="font-mono">{testResult.fb_error_message}</code>
                {testResult.fb_error_code != null && <span className="ml-2 text-[10px]">(code {testResult.fb_error_code})</span>}
              </p>
            )}
            {testResult.fb_trace_id && <p className="text-[10px] opacity-70">trace_id : <code>{testResult.fb_trace_id}</code></p>}
            {!testResult.ok && (
              <p className="text-[10px] italic mt-1">
                💡 Action : LinkedIn-style → régénérez le secret sur{" "}
                <a href="https://developers.facebook.com/apps/" target="_blank" rel="noreferrer" className="underline">developers.facebook.com</a>
                {" "}→ App Settings → Basic → App Secret → <strong>Show</strong> → copiez-collez ici → Enregistrer → Re-tester.
              </p>
            )}
          </div>
        )}
      </div>

      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
        <h3 className="text-xs uppercase text-slate-600 font-semibold">2. Connexion OAuth</h3>
        {!cfg?.connected ? (
          <button onClick={connect} disabled={connecting || !cfg?.app_id} className="text-sm px-3 py-1.5 rounded bg-[#1877f2] hover:bg-[#0f5fb5] text-white inline-flex items-center gap-2 disabled:opacity-50" data-testid="facebook-connect-btn">
            {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Facebook className="h-4 w-4" />}Connecter Facebook
          </button>
        ) : (
          <div className="text-xs space-y-2">
            <p>Connecté en tant que <strong>{cfg.user_name}</strong> ({cfg.user_email})</p>
            <p className="text-[10px] text-slate-500">User token expire : {cfg.user_token_expires_at ? new Date(cfg.user_token_expires_at).toLocaleString("fr-FR") : "—"}</p>
            <div className="flex gap-2">
              <button onClick={loadPages} disabled={loadingPages} className="text-xs px-2 py-1 rounded bg-amber-100 ring-1 ring-amber-300 text-amber-700 inline-flex items-center gap-1" data-testid="facebook-load-pages">
                {loadingPages ? <Loader2 className="h-3 w-3 animate-spin" /> : <Building2 className="h-3 w-3" />}Lister mes Pages
              </button>
              <button onClick={connect} className="text-xs px-2 py-1 rounded bg-slate-100 ring-1 ring-slate-300 inline-flex items-center gap-1"><RefreshCw className="h-3 w-3" />Reconnecter</button>
              <button onClick={disconnect} className="text-xs px-2 py-1 rounded bg-rose-100 ring-1 ring-rose-200 text-rose-700 inline-flex items-center gap-1" data-testid="facebook-disconnect-btn"><Trash2 className="h-3 w-3" />Déconnecter</button>
            </div>
            {pages.length > 0 && (
              <ul className="mt-2 space-y-1" data-testid="facebook-pages-list">
                {pages.map((p) => (
                  <li key={p.id} className={`flex items-center justify-between p-2 rounded text-xs ${cfg.active_page_id === p.id ? "bg-emerald-100 ring-1 ring-emerald-300" : "bg-white ring-1 ring-slate-200"}`}>
                    <div>
                      <p className="font-semibold">{p.name}</p>
                      <p className="font-mono text-[10px] text-slate-500">{p.id} — {p.category}</p>
                    </div>
                    {cfg.active_page_id === p.id ? <span className="text-[10px] text-emerald-700 font-bold">✓ Active</span> :
                      <button onClick={() => pickPage(p)} className="text-[10px] px-2 py-1 rounded bg-[#1877f2] text-white" data-testid={`facebook-pick-page-${p.id}`}>Choisir</button>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {cfg?.active_page_id && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-blue-50/30 p-3 space-y-2">
          <h3 className="text-xs uppercase text-slate-600 font-semibold">3. Publier sur « {cfg.active_page_name} »</h3>
          <textarea rows={4} value={postText} onChange={(e) => setPostText(e.target.value)} placeholder="Que voulez-vous partager ?" className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="facebook-post-text" />
          <input type="text" value={postImage} onChange={(e) => setPostImage(e.target.value)} placeholder="URL image (facultatif)" className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="facebook-post-image" />
          <button onClick={post} disabled={posting || !postText.trim()} className="text-sm px-3 py-1.5 rounded bg-[#1877f2] text-white inline-flex items-center gap-2 disabled:opacity-50" data-testid="facebook-post-submit">
            {posting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}Publier
          </button>
        </div>
      )}

      {cfg?.active_page_id && feed.length > 0 && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-1">
          <h3 className="text-xs uppercase text-slate-600 font-semibold">4. Feed récent</h3>
          <ul className="space-y-1" data-testid="facebook-feed-list">
            {feed.map((f, i) => (
              <li key={f.post_id || i} className="text-xs bg-white p-2 rounded ring-1 ring-slate-200">
                <p className="whitespace-pre-wrap">{f.text || <em className="text-slate-400">(sans texte)</em>}</p>
                <p className="text-[10px] text-slate-400 mt-1">{f.created_at ? new Date(f.created_at).toLocaleString("fr-FR") : ""} {f.permalink && (<>• <a href={f.permalink} target="_blank" rel="noreferrer" className="underline">Voir le post</a></>)}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};

export default FacebookSection;
