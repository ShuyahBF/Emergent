// =====================================================================
// Iter43-fix24au (2026-02-26) — LinkedIn integration admin section.
// Lets admin :
//  1. Paste Client ID + Client Secret obtained from linkedin.com/developers
//  2. Connect (OAuth) and see status (member name, organizations, expiry)
//  3. Compose a quick post (text + optional image URL) as profile OR org
//  4. List latest posts (where the read scopes were granted)
//  5. Disconnect
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import {
  Linkedin, Loader2, ExternalLink, Send, RefreshCw, Trash2, Copy, Check,
  AlertCircle, Building2, User, Calendar
} from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const LinkedInSection = () => {
  const [config, setConfig] = useState({
    client_id: "",
    client_secret: "",
    redirect_uri: "",
    enable_member: true,
    enable_organization: true,
    connected: false,
    member_urn: "",
    member_name: "",
    scopes: [],
    organizations: [],
    token_expires_at: null,
    refresh_expires_at: null,
    connected_at: null,
    connected_by: null,
  });
  const [loading, setLoading] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [revealSecret, setRevealSecret] = useState(false);

  // Composer
  const [postText, setPostText] = useState("");
  const [postImageUrl, setPostImageUrl] = useState("");
  const [postAuthorType, setPostAuthorType] = useState("member");
  const [postOrgUrn, setPostOrgUrn] = useState("");
  const [posting, setPosting] = useState(false);
  const [lastPostResult, setLastPostResult] = useState(null);

  // Posts list
  const [posts, setPosts] = useState([]);
  const [postsLoading, setPostsLoading] = useState(false);
  const [postsError, setPostsError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/linkedin/config");
      setConfig((prev) => ({ ...prev, ...r.data }));
      // Default org URN in composer
      const orgs = r.data?.organizations || [];
      if (orgs.length > 0 && !postOrgUrn) {
        setPostOrgUrn(orgs[0].urn);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Listen for the LinkedIn OAuth popup result (postMessage from callback)
  useEffect(() => {
    const onMsg = (event) => {
      const d = event.data;
      if (!d || d.type !== "linkedin-oauth-result") return;
      if (d.success) {
        toast.success(d.message || "LinkedIn connecté !");
        load();
      } else {
        toast.error(d.message || "Échec OAuth LinkedIn");
      }
      setConnecting(false);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [load]);

  const saveConfig = async () => {
    setSavingConfig(true);
    try {
      const payload = {
        client_id: config.client_id,
        // Only send secret if user changed it (not the masked placeholder)
        ...(config.client_secret && config.client_secret !== "********" ? { client_secret: config.client_secret } : {}),
        redirect_uri: config.redirect_uri,
        enable_member: config.enable_member,
        enable_organization: config.enable_organization,
      };
      await apiClient.put("/admin/linkedin/config", payload);
      toast.success("Configuration LinkedIn enregistrée");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'enregistrement");
    } finally {
      setSavingConfig(false);
    }
  };

  const connect = async () => {
    setConnecting(true);
    try {
      const r = await apiClient.get("/admin/linkedin/oauth/authorize");
      const url = r.data?.authorization_url;
      if (!url) throw new Error("Authorization URL manquante");
      // Open in a popup so the callback can postMessage back
      const w = 600, h = 720;
      const left = window.screenX + (window.outerWidth - w) / 2;
      const top = window.screenY + (window.outerHeight - h) / 2;
      const popup = window.open(url, "linkedin-oauth", `width=${w},height=${h},left=${left},top=${top}`);
      if (!popup) {
        toast.warning("Pop-up bloqué — redirection en plein écran");
        window.location.href = url;
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || "Erreur OAuth");
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Déconnecter LinkedIn ? Les tokens seront supprimés.")) return;
    try {
      await apiClient.delete("/admin/linkedin/connection");
      toast.success("LinkedIn déconnecté");
      setPosts([]);
      setPostsError(null);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur déconnexion");
    }
  };

  const publishPost = async () => {
    if (!postText.trim()) {
      toast.warning("Texte du post requis");
      return;
    }
    setPosting(true);
    setLastPostResult(null);
    try {
      const body = {
        text: postText,
        ...(postImageUrl ? { image_url: postImageUrl } : {}),
        author_type: postAuthorType,
        ...(postAuthorType === "organization" ? { organization_urn: postOrgUrn } : {}),
      };
      const r = await apiClient.post("/linkedin/posts", body);
      setLastPostResult(r.data);
      toast.success(`Post publié : ${r.data?.post_urn || "OK"}`);
      setPostText("");
      setPostImageUrl("");
      // Refresh list
      loadPosts();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur publication");
    } finally {
      setPosting(false);
    }
  };

  const loadPosts = useCallback(async () => {
    if (!config.connected) return;
    setPostsLoading(true);
    setPostsError(null);
    try {
      const params = new URLSearchParams({ author_type: postAuthorType, limit: "10" });
      if (postAuthorType === "organization" && postOrgUrn) {
        params.set("organization_urn", postOrgUrn);
      }
      const r = await apiClient.get(`/linkedin/posts?${params.toString()}`);
      const items = r.data?.items || [];
      const errItem = items.find((it) => it._error);
      if (errItem) {
        setPostsError(`${errItem._error} — ${errItem._detail || ""}`);
        setPosts([]);
      } else {
        setPosts(items);
      }
    } catch (err) {
      setPostsError(err?.response?.data?.detail || "Erreur");
      setPosts([]);
    } finally {
      setPostsLoading(false);
    }
  }, [config.connected, postAuthorType, postOrgUrn]);

  useEffect(() => { loadPosts(); }, [loadPosts]);

  const copyText = (txt) => {
    try { navigator.clipboard.writeText(txt || ""); toast.success("Copié"); } catch { toast.error("Copie impossible"); }
  };

  if (loading) {
    return (
      <div className="p-6 text-sm text-slate-500 inline-flex items-center gap-2" data-testid="linkedin-section-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement LinkedIn…
      </div>
    );
  }

  const expiresAtDate = config.token_expires_at ? new Date(config.token_expires_at) : null;
  const refreshExpiresAtDate = config.refresh_expires_at ? new Date(config.refresh_expires_at) : null;

  return (
    <section
      id="s-linkedin"
      className="rounded-xl ring-1 ring-slate-200 bg-white p-5 space-y-5"
      data-testid="admin-linkedin-section"
    >
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Linkedin className="h-5 w-5 text-[#0a66c2]" />
          <h2 className="text-lg font-bold text-slate-800">LinkedIn — Publications & lecture</h2>
        </div>
        <span
          className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${config.connected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}
          data-testid="linkedin-status-badge"
        >
          {config.connected ? "✓ Connecté" : "○ Non connecté"}
        </span>
      </header>

      {/* === CONFIG === */}
      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-4 space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-slate-600 font-semibold">1. Application LinkedIn</h3>
        <p className="text-[11px] text-slate-500">
          Créez une App sur{" "}
          <a href="https://www.linkedin.com/developers/apps" target="_blank" rel="noopener noreferrer" className="text-[#0a66c2] underline">
            linkedin.com/developers/apps <ExternalLink className="inline h-3 w-3" />
          </a>{" "}
          puis collez le Client ID et le Client Secret ici.
        </p>

        <div className="grid md:grid-cols-2 gap-3">
          <label className="block">
            <span className="block text-xs text-slate-700 mb-1">Client ID</span>
            <input
              type="text"
              value={config.client_id}
              onChange={(e) => setConfig((p) => ({ ...p, client_id: e.target.value }))}
              className="w-full text-sm px-3 py-2 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-[#0a66c2] outline-none font-mono"
              data-testid="linkedin-client-id-input"
              placeholder="ex: 77rg7lu8v2hd3w"
            />
          </label>
          <label className="block">
            <span className="block text-xs text-slate-700 mb-1">Client Secret</span>
            <div className="flex gap-1">
              <input
                type={revealSecret ? "text" : "password"}
                value={config.client_secret}
                onChange={(e) => setConfig((p) => ({ ...p, client_secret: e.target.value }))}
                className="flex-1 text-sm px-3 py-2 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-[#0a66c2] outline-none font-mono"
                data-testid="linkedin-client-secret-input"
                placeholder="********"
              />
              <button
                type="button"
                onClick={() => setRevealSecret((v) => !v)}
                className="text-xs px-2 py-2 rounded ring-1 ring-slate-300 hover:bg-slate-100"
                data-testid="linkedin-reveal-secret"
              >
                {revealSecret ? "🙈" : "👁"}
              </button>
            </div>
          </label>
        </div>

        <label className="block">
          <span className="block text-xs text-slate-700 mb-1">
            Redirect URI <span className="text-slate-400">(facultatif — auto-calculé sinon)</span>
          </span>
          <div className="flex gap-1">
            <input
              type="text"
              value={config.redirect_uri}
              onChange={(e) => setConfig((p) => ({ ...p, redirect_uri: e.target.value }))}
              className="flex-1 text-xs px-3 py-2 rounded ring-1 ring-slate-300 font-mono"
              data-testid="linkedin-redirect-uri-input"
              placeholder={`${window.location.origin}/api/linkedin/oauth/callback`}
            />
            <button
              type="button"
              onClick={() => copyText(`${window.location.origin}/api/linkedin/oauth/callback`)}
              className="text-xs px-2 py-2 rounded ring-1 ring-slate-300 hover:bg-slate-100 inline-flex items-center gap-1"
              data-testid="linkedin-copy-redirect"
              title="Copier l'URL à autoriser dans LinkedIn → App → Auth"
            >
              <Copy className="h-3 w-3" />
            </button>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">
            ⚠️ Cette URL doit être <strong>ajoutée à la liste « Authorized redirect URLs »</strong> dans votre App LinkedIn → Auth.
          </p>
        </label>

        <div className="flex flex-wrap gap-4 text-xs">
          <label className="inline-flex items-center gap-2" data-testid="linkedin-toggle-member">
            <input
              type="checkbox"
              checked={config.enable_member}
              onChange={(e) => setConfig((p) => ({ ...p, enable_member: e.target.checked }))}
            />
            <User className="h-3 w-3" /> Profil personnel (w_member_social)
          </label>
          <label className="inline-flex items-center gap-2" data-testid="linkedin-toggle-org">
            <input
              type="checkbox"
              checked={config.enable_organization}
              onChange={(e) => setConfig((p) => ({ ...p, enable_organization: e.target.checked }))}
            />
            <Building2 className="h-3 w-3" /> Page entreprise (w_organization_social — requiert approbation Community Mgmt)
          </label>
        </div>

        <button
          type="button"
          onClick={saveConfig}
          disabled={savingConfig}
          className="text-sm px-4 py-2 rounded bg-slate-800 hover:bg-slate-900 text-white inline-flex items-center gap-2 disabled:opacity-50"
          data-testid="linkedin-save-config"
        >
          {savingConfig ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Enregistrer la config
        </button>
      </div>

      {/* === CONNECTION === */}
      <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-4 space-y-3">
        <h3 className="text-xs uppercase tracking-wider text-slate-600 font-semibold">2. Connexion OAuth</h3>

        {!config.connected ? (
          <div className="space-y-2">
            <p className="text-xs text-slate-600">Cliquez pour ouvrir l&apos;autorisation LinkedIn dans une pop-up.</p>
            <button
              type="button"
              onClick={connect}
              disabled={connecting || !config.client_id}
              className="text-sm px-4 py-2 rounded bg-[#0a66c2] hover:bg-[#084d92] text-white inline-flex items-center gap-2 disabled:opacity-50"
              data-testid="linkedin-connect-btn"
            >
              {connecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Linkedin className="h-4 w-4" />}
              Connecter LinkedIn
            </button>
            {!config.client_id && (
              <p className="text-[11px] text-amber-600 inline-flex items-center gap-1">
                <AlertCircle className="h-3 w-3" /> Configurez d&apos;abord Client ID + Secret.
              </p>
            )}
          </div>
        ) : (
          <>
            <div className="grid sm:grid-cols-2 gap-3 text-xs">
              <div>
                <span className="block text-slate-500 mb-0.5">Connecté en tant que</span>
                <p className="font-semibold text-slate-800" data-testid="linkedin-member-name">{config.member_name || "(inconnu)"}</p>
                <p className="font-mono text-[10px] text-slate-500" data-testid="linkedin-member-urn">{config.member_urn}</p>
              </div>
              <div>
                <span className="block text-slate-500 mb-0.5">Connecté par</span>
                <p className="text-slate-800">{config.connected_by || "—"}</p>
                <p className="text-[10px] text-slate-500">
                  Depuis : {config.connected_at ? new Date(config.connected_at).toLocaleString("fr-FR") : "—"}
                </p>
              </div>
              <div>
                <span className="block text-slate-500 mb-0.5">Access token expire</span>
                <p className="text-slate-800 inline-flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {expiresAtDate ? expiresAtDate.toLocaleString("fr-FR") : "—"}
                </p>
              </div>
              <div>
                <span className="block text-slate-500 mb-0.5">Refresh token expire</span>
                <p className="text-slate-800 inline-flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {refreshExpiresAtDate ? refreshExpiresAtDate.toLocaleString("fr-FR") : "—"}
                </p>
              </div>
            </div>

            <div>
              <span className="block text-xs text-slate-500 mb-1">Scopes obtenus :</span>
              <div className="flex flex-wrap gap-1" data-testid="linkedin-scopes">
                {(config.scopes || []).map((s) => (
                  <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-mono">{s}</span>
                ))}
                {(config.scopes || []).length === 0 && <span className="text-[11px] text-slate-400 italic">aucun</span>}
              </div>
            </div>

            {(config.organizations || []).length > 0 ? (
              <div>
                <span className="block text-xs text-slate-500 mb-1">Pages entreprise administrées :</span>
                <ul className="text-xs space-y-1" data-testid="linkedin-organizations">
                  {config.organizations.map((o) => (
                    <li key={o.urn} className="flex items-center gap-2">
                      <Building2 className="h-3 w-3 text-slate-400" />
                      <span className="font-semibold">{o.name || o.urn}</span>
                      <span className="font-mono text-[10px] text-slate-400">({o.urn})</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-[11px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded p-2">
                ℹ️ Aucune page entreprise détectée. C&apos;est normal si votre App LinkedIn n&apos;a pas encore l&apos;approbation
                <strong> Community Management API</strong>. Le post en tant que profil personnel reste disponible.
              </p>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                onClick={connect}
                disabled={connecting}
                className="text-xs px-3 py-1.5 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300 inline-flex items-center gap-1"
                data-testid="linkedin-reconnect-btn"
              >
                <RefreshCw className="h-3 w-3" /> Reconnecter
              </button>
              <button
                type="button"
                onClick={disconnect}
                className="text-xs px-3 py-1.5 rounded bg-rose-100 hover:bg-rose-200 text-rose-700 ring-1 ring-rose-200 inline-flex items-center gap-1"
                data-testid="linkedin-disconnect-btn"
              >
                <Trash2 className="h-3 w-3" /> Déconnecter
              </button>
            </div>
          </>
        )}
      </div>

      {/* === COMPOSER === */}
      {config.connected && (
        <div className="rounded-lg ring-1 ring-[#0a66c2]/30 bg-blue-50/30 p-4 space-y-3">
          <h3 className="text-xs uppercase tracking-wider text-slate-600 font-semibold">3. Publier un post</h3>
          <div className="flex flex-wrap gap-3 items-center">
            <label className="inline-flex items-center gap-1 text-xs">
              <input
                type="radio"
                checked={postAuthorType === "member"}
                onChange={() => setPostAuthorType("member")}
                data-testid="linkedin-post-author-member"
              /> <User className="h-3 w-3" /> Profil personnel
            </label>
            <label className={`inline-flex items-center gap-1 text-xs ${(config.organizations || []).length === 0 ? "opacity-50" : ""}`}>
              <input
                type="radio"
                checked={postAuthorType === "organization"}
                onChange={() => setPostAuthorType("organization")}
                disabled={(config.organizations || []).length === 0}
                data-testid="linkedin-post-author-org"
              /> <Building2 className="h-3 w-3" /> Page entreprise
            </label>
            {postAuthorType === "organization" && (
              <select
                value={postOrgUrn}
                onChange={(e) => setPostOrgUrn(e.target.value)}
                className="text-xs px-2 py-1 rounded ring-1 ring-slate-300"
                data-testid="linkedin-post-org-select"
              >
                {(config.organizations || []).map((o) => (
                  <option key={o.urn} value={o.urn}>{o.name || o.urn}</option>
                ))}
              </select>
            )}
          </div>
          <textarea
            value={postText}
            onChange={(e) => setPostText(e.target.value)}
            rows={4}
            placeholder="Que voulez-vous partager ? Vous pouvez utiliser #hashtags et @mentions."
            className="w-full text-sm px-3 py-2 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-[#0a66c2] outline-none"
            data-testid="linkedin-post-text"
          />
          <input
            type="text"
            value={postImageUrl}
            onChange={(e) => setPostImageUrl(e.target.value)}
            placeholder="URL d'une image (facultatif — JPEG/PNG/GIF)"
            className="w-full text-xs px-3 py-2 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-[#0a66c2] outline-none font-mono"
            data-testid="linkedin-post-image-url"
          />
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <p className="text-[10px] text-slate-500">
              {postText.length} caractère{postText.length > 1 ? "s" : ""} — Maximum LinkedIn : 3000
            </p>
            <button
              type="button"
              onClick={publishPost}
              disabled={posting || !postText.trim()}
              className="text-sm px-4 py-2 rounded bg-[#0a66c2] hover:bg-[#084d92] text-white inline-flex items-center gap-2 disabled:opacity-50"
              data-testid="linkedin-post-submit"
            >
              {posting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Publier
            </button>
          </div>
          {lastPostResult && (
            <div className="text-[11px] bg-emerald-50 ring-1 ring-emerald-200 rounded p-2" data-testid="linkedin-post-result">
              ✅ Publié : <code className="font-mono">{lastPostResult.post_urn}</code>
              <button
                type="button"
                onClick={() => copyText(lastPostResult.post_urn)}
                className="ml-2 text-emerald-700 underline"
              >
                Copier URN
              </button>
            </div>
          )}
        </div>
      )}

      {/* === POSTS LIST === */}
      {config.connected && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-slate-50 p-4 space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-xs uppercase tracking-wider text-slate-600 font-semibold">4. Posts récents</h3>
            <button
              type="button"
              onClick={loadPosts}
              disabled={postsLoading}
              className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300 inline-flex items-center gap-1"
              data-testid="linkedin-posts-refresh"
            >
              {postsLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />} Rafraîchir
            </button>
          </div>
          {postsError ? (
            <p className="text-[11px] text-amber-700 bg-amber-50 ring-1 ring-amber-200 rounded p-2" data-testid="linkedin-posts-error">
              ⚠️ Lecture impossible : {postsError}
              <br />
              <span className="text-[10px] italic">
                Note : la lecture des posts demande des scopes restreints (<code>r_member_social</code> est fermé, <code>r_organization_social</code> requiert Community Management).
                Vous pouvez toujours publier sans problème.
              </span>
            </p>
          ) : posts.length === 0 ? (
            <p className="text-[11px] text-slate-500 italic" data-testid="linkedin-posts-empty">Aucun post récent.</p>
          ) : (
            <ul className="space-y-2" data-testid="linkedin-posts-list">
              {posts.map((p, i) => (
                <li key={p.urn || i} className="text-xs bg-white ring-1 ring-slate-200 rounded p-2">
                  <p className="font-mono text-[9px] text-slate-400 break-all">{p.urn}</p>
                  <p className="mt-1 whitespace-pre-wrap">{p.text || <em className="text-slate-400">(sans texte)</em>}</p>
                  {p.created_at && (
                    <p className="text-[10px] text-slate-400 mt-1">
                      Créé : {typeof p.created_at === "number" ? new Date(p.created_at).toLocaleString("fr-FR") : p.created_at}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
};

export default LinkedInSection;
