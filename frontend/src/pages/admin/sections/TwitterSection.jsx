// =====================================================================
// Iter43-fix24ax (2026-02-26) — Twitter (X) admin section.
// Compact UI: config (Client ID/Secret/Redirect), OAuth connect, compose tweet, list recent tweets.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Loader2, ExternalLink, Send, RefreshCw, Trash2, Copy, Check, AlertCircle, Twitter as XIcon } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TwitterSection = () => {
  const [cfg, setCfg] = useState(null);
  const [redirect, setRedirect] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [tweetText, setTweetText] = useState("");
  const [tweetImage, setTweetImage] = useState("");
  const [posting, setPosting] = useState(false);
  const [tweets, setTweets] = useState([]);
  const [reveal, setReveal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, p] = await Promise.all([
        apiClient.get("/admin/twitter/config"),
        apiClient.get("/admin/twitter/oauth/preview-redirect-uri").catch(() => null),
      ]);
      setCfg(c.data);
      if (p?.data?.redirect_uri) setRedirect(p.data.redirect_uri);
    } catch { setCfg(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const onMsg = (e) => {
      if (e?.data?.type !== "twitter-oauth-result") return;
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
        client_id: cfg.client_id,
        ...(cfg.client_secret && cfg.client_secret !== "********" ? { client_secret: cfg.client_secret } : {}),
        redirect_uri: cfg.redirect_uri,
      };
      await apiClient.put("/admin/twitter/config", body);
      toast.success("Config Twitter enregistrée"); await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setSaving(false); }
  };

  const connect = async () => {
    setConnecting(true);
    try {
      const r = await apiClient.get("/admin/twitter/oauth/authorize");
      const w = 600, h = 720;
      const left = window.screenX + (window.outerWidth - w) / 2;
      const top = window.screenY + (window.outerHeight - h) / 2;
      const p = window.open(r.data.authorization_url, "twitter-oauth", `width=${w},height=${h},left=${left},top=${top}`);
      if (!p) { window.location.href = r.data.authorization_url; }
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); setConnecting(false); }
  };

  const disconnect = async () => {
    if (!window.confirm("Déconnecter Twitter ?")) return;
    try { await apiClient.delete("/admin/twitter/connection"); toast.success("Déconnecté"); setTweets([]); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  const postTweet = async () => {
    if (!tweetText.trim()) return toast.warning("Texte requis");
    if (tweetText.length > 280) return toast.error(`Trop long (${tweetText.length}/280)`);
    setPosting(true);
    try {
      const r = await apiClient.post("/twitter/tweets", { text: tweetText, ...(tweetImage ? { image_url: tweetImage } : {}) });
      toast.success(`Tweet publié : ${r.data?.tweet_id || "OK"}`);
      setTweetText(""); setTweetImage(""); loadTweets();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setPosting(false); }
  };

  const loadTweets = useCallback(async () => {
    if (!cfg?.connected) return;
    try {
      const r = await apiClient.get("/twitter/tweets?limit=10");
      setTweets(r.data?.items || []);
    } catch { setTweets([]); }
  }, [cfg?.connected]);

  useEffect(() => { loadTweets(); }, [loadTweets]);

  if (loading) return <div className="p-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin inline mr-2" />Chargement Twitter…</div>;

  return (
    <section className="rounded-xl ring-1 ring-slate-200 bg-white p-5 space-y-4" data-testid="admin-twitter-section">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-bold inline-flex items-center gap-2">
          <XIcon className="h-5 w-5 text-slate-800" /> X / Twitter — Posts
        </h2>
        <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${cfg?.connected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`} data-testid="twitter-status-badge">
          {cfg?.connected ? `✓ @${cfg.username}` : "○ Non connecté"}
        </span>
      </header>

      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
        <h3 className="text-xs uppercase text-slate-600 font-semibold">1. App X (developer.twitter.com)</h3>
        <p className="text-[11px] text-slate-500">
          Créez une App OAuth 2.0 sur{" "}
          <a href="https://developer.twitter.com/en/portal/dashboard" target="_blank" rel="noreferrer" className="text-cyan-600 underline">
            developer.twitter.com <ExternalLink className="inline h-3 w-3" />
          </a>{" "} avec User authentication settings → Type of App = Web App + Confidential Client.
        </p>
        <div className="grid sm:grid-cols-2 gap-2">
          <label className="block"><span className="block text-xs text-slate-700 mb-1">Client ID</span>
            <input type="text" value={cfg?.client_id || ""} onChange={(e) => setCfg({...cfg, client_id: e.target.value})} className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="twitter-client-id" /></label>
          <label className="block"><span className="block text-xs text-slate-700 mb-1">Client Secret</span>
            <div className="flex gap-1">
              <input type={reveal ? "text" : "password"} value={cfg?.client_secret || ""} onChange={(e) => setCfg({...cfg, client_secret: e.target.value})} className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="twitter-client-secret" />
              <button onClick={() => setReveal(!reveal)} className="text-xs px-2 rounded ring-1 ring-slate-300">{reveal ? "🙈" : "👁"}</button>
            </div></label>
        </div>
        {redirect && (
          <div className="rounded ring-2 ring-amber-300 bg-amber-50 p-2 text-xs space-y-1" data-testid="twitter-redirect-warning">
            <p className="font-semibold text-amber-900 inline-flex items-center gap-1"><AlertCircle className="h-3 w-3" /> ÉTAPE OBLIGATOIRE — Redirect URI effectif</p>
            <p className="text-amber-800 text-[11px]">Ajoutez cette URL EXACTE dans App → User authentication settings → Callback URI/Redirect URL :</p>
            <div className="flex gap-1">
              <code className="flex-1 bg-white px-2 py-1 rounded ring-1 ring-amber-300 text-[10px] font-mono break-all" data-testid="twitter-redirect-uri-computed">{redirect}</code>
              <button onClick={() => { navigator.clipboard.writeText(redirect); toast.success("Copié"); }} className="text-[10px] px-2 py-1 rounded bg-amber-600 hover:bg-amber-700 text-white inline-flex items-center gap-1" data-testid="twitter-copy-redirect"><Copy className="h-3 w-3" />Copier</button>
            </div>
          </div>
        )}
        {/* Iter43-fix24az-b — Editable Redirect URI override (PROD vs PREVIEW) */}
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
              placeholder={`${window.location.origin}/api/twitter/oauth/callback`}
              data-testid="twitter-redirect-uri-input"
            />
            <button
              type="button"
              onClick={() => setCfg({...cfg, redirect_uri: ""})}
              className="text-xs px-2 py-1.5 rounded bg-slate-100 ring-1 ring-slate-300 hover:bg-slate-200"
              data-testid="twitter-clear-redirect"
              title="Effacer l'override pour utiliser l'URL automatique"
            >
              Auto
            </button>
            <button
              type="button"
              onClick={() => setCfg({...cfg, redirect_uri: `${window.location.origin}/api/twitter/oauth/callback`})}
              className="text-xs px-2 py-1.5 rounded bg-slate-100 ring-1 ring-slate-300 hover:bg-slate-200"
              data-testid="twitter-use-current-redirect"
              title="Pré-remplir avec l'URL de l'environnement actuel"
            >
              Cet env
            </button>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">
            ⚠️ Si l&apos;URL effective ci-dessus est figée sur l&apos;environnement preview, cliquez <strong>Auto</strong> puis <strong>Enregistrer</strong> — le backend recalculera depuis votre domaine actuel.
          </p>
        </label>
        <button onClick={save} disabled={saving} className="text-xs px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-900 text-white inline-flex items-center gap-1 disabled:opacity-50" data-testid="twitter-save-config">
          {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />} Enregistrer
        </button>
      </div>

      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-2">
        <h3 className="text-xs uppercase text-slate-600 font-semibold">2. Connexion OAuth</h3>
        {!cfg?.connected ? (
          <button onClick={connect} disabled={connecting || !cfg?.client_id} className="text-sm px-3 py-1.5 rounded bg-slate-900 hover:bg-black text-white inline-flex items-center gap-2 disabled:opacity-50" data-testid="twitter-connect-btn">
            {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <XIcon className="h-4 w-4" />} Connecter X / Twitter
          </button>
        ) : (
          <div className="text-xs space-y-2">
            <p>Connecté en tant que <strong>@{cfg.username}</strong> (id={cfg.user_id})</p>
            <p className="text-[10px] text-slate-500">Token expire : {cfg.token_expires_at ? new Date(cfg.token_expires_at).toLocaleString("fr-FR") : "—"}</p>
            <div className="flex gap-2">
              <button onClick={connect} className="text-xs px-2 py-1 rounded bg-slate-100 ring-1 ring-slate-300 inline-flex items-center gap-1"><RefreshCw className="h-3 w-3" />Reconnecter</button>
              <button onClick={disconnect} className="text-xs px-2 py-1 rounded bg-rose-100 ring-1 ring-rose-200 text-rose-700 inline-flex items-center gap-1" data-testid="twitter-disconnect-btn"><Trash2 className="h-3 w-3" />Déconnecter</button>
            </div>
          </div>
        )}
      </div>

      {cfg?.connected && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-blue-50/30 p-3 space-y-2">
          <h3 className="text-xs uppercase text-slate-600 font-semibold">3. Publier un tweet</h3>
          <textarea rows={3} value={tweetText} onChange={(e) => setTweetText(e.target.value)} maxLength={280} placeholder="Quoi de neuf ?" className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="twitter-tweet-text" />
          <input type="text" value={tweetImage} onChange={(e) => setTweetImage(e.target.value)} placeholder="URL image (facultatif)" className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="twitter-tweet-image" />
          <div className="flex items-center justify-between">
            <span className={`text-[10px] ${tweetText.length > 280 ? "text-rose-600 font-bold" : "text-slate-500"}`}>{tweetText.length}/280</span>
            <button onClick={postTweet} disabled={posting || !tweetText.trim()} className="text-sm px-3 py-1.5 rounded bg-slate-900 text-white inline-flex items-center gap-2 disabled:opacity-50" data-testid="twitter-tweet-submit">
              {posting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}Tweeter
            </button>
          </div>
        </div>
      )}

      {cfg?.connected && tweets.length > 0 && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-3 space-y-1">
          <h3 className="text-xs uppercase text-slate-600 font-semibold">4. Tweets récents</h3>
          <ul className="space-y-1" data-testid="twitter-tweets-list">
            {tweets.map((t, i) => (
              <li key={t.tweet_id || i} className="text-xs bg-white p-2 rounded ring-1 ring-slate-200">
                <p className="whitespace-pre-wrap">{t.text}</p>
                <p className="text-[10px] text-slate-400 mt-1">{t.created_at ? new Date(t.created_at).toLocaleString("fr-FR") : ""} • <a href={`https://x.com/${cfg.username}/status/${t.tweet_id}`} target="_blank" rel="noreferrer" className="underline">Voir sur X</a></p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};

export default TwitterSection;
