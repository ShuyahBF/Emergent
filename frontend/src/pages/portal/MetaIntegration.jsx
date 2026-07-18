/*
 * Iter38h — Portail Meta (Pages + Messenger + Ads).
 * 3 tabs gated by tenant features. Connect/disconnect Facebook account,
 * publish posts/photos, view Messenger conversations, manage Ads campaigns.
 */
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import {
  Facebook, MessageCircle, Megaphone, Loader2, RefreshCw, Send, Image as ImageIcon,
  LogOut, CheckCircle2, AlertTriangle, Plus, BarChart3,
} from "lucide-react";
import { toast } from "sonner";
import { LocalMediaImporter } from "@/components/LocalMediaImporter";

export default function MetaIntegration() {
  const [params, setParams] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("pages");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/meta/status");
      setStatus(r.data);
      // Pick first enabled tab
      const f = r.data.features || {};
      if (f.meta_pages) setTab("pages");
      else if (f.meta_messenger) setTab("messenger");
      else if (f.meta_ads) setTab("ads");
    } catch {
      toast.error("Erreur de chargement");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Handle OAuth callback redirect
  useEffect(() => {
    if (params.get("cb")) {
      const s = params.get("status");
      if (s === "success") toast.success(`Connexion Meta réussie ! ${params.get("pages") || 0} Page(s), ${params.get("ads") || 0} compte(s) Ads.`);
      else if (s === "error") toast.error(`Connexion Meta échouée : ${params.get("reason") || "inconnue"} ${params.get("detail") || ""}`);
      // Clean URL
      params.delete("cb"); params.delete("status"); params.delete("pages"); params.delete("ads"); params.delete("reason"); params.delete("detail");
      setParams(params, { replace: true });
      load();
    }
  }, [params, setParams, load]);

  const connect = async () => {
    try {
      const r = await apiClient.get("/me/meta/oauth/url");
      window.location.href = r.data.auth_url;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible de générer le lien OAuth");
    }
  };

  const disconnect = async () => {
    if (!window.confirm("Déconnecter votre compte Meta ? Tous les tokens stockés seront supprimés.")) return;
    try {
      await apiClient.post("/me/meta/disconnect");
      toast.success("Compte Meta déconnecté");
      load();
    } catch {
      toast.error("Erreur");
    }
  };

  if (loading || !status) {
    return <div className="p-8 flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-blue-500" /></div>;
  }

  const f = status.features || {};
  const anyEnabled = f.meta_pages || f.meta_messenger || f.meta_ads;
  if (!anyEnabled) {
    return (
      <div className="p-8" data-testid="meta-disabled">
        <div className="rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <Facebook className="h-12 w-12 mx-auto text-slate-300 mb-3" />
          <h2 className="text-lg font-display font-semibold text-slate-700">Module Meta non activé</h2>
          <p className="mt-2 text-sm text-slate-500 max-w-md mx-auto">
            Aucune fonctionnalité Meta (Pages, Messenger, Ads) n'est activée pour votre compte.
            Contactez votre administrateur pour activer l'intégration.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6" data-testid="meta-page">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Facebook className="h-7 w-7 text-blue-600" />
          <div>
            <h1 className="text-2xl font-display font-bold">Intégration Meta</h1>
            <p className="text-sm text-slate-500">
              {status.connected ? (
                <span className="inline-flex items-center gap-1 text-emerald-700">
                  <CheckCircle2 className="h-4 w-4" /> Connecté en tant que <strong>{status.user_name}</strong>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-amber-700">
                  <AlertTriangle className="h-4 w-4" /> Compte Meta non connecté
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="inline-flex items-center gap-1 px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded-lg text-sm" data-testid="meta-refresh-btn">
            <RefreshCw className="h-4 w-4" /> Actualiser
          </button>
          {status.connected ? (
            <button onClick={disconnect} className="inline-flex items-center gap-1 px-3 py-1.5 bg-rose-100 hover:bg-rose-200 text-rose-700 rounded-lg text-sm" data-testid="meta-disconnect-btn">
              <LogOut className="h-4 w-4" /> Déconnecter
            </button>
          ) : (
            <button onClick={connect} className="inline-flex items-center gap-2 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium" data-testid="meta-connect-btn">
              <Facebook className="h-4 w-4" /> Connecter Facebook
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-slate-200">
        {f.meta_pages && (
          <TabBtn icon={Facebook} label="Pages" active={tab === "pages"} onClick={() => setTab("pages")} testId="meta-tab-pages" />
        )}
        {f.meta_messenger && (
          <TabBtn icon={MessageCircle} label="Messenger" active={tab === "messenger"} onClick={() => setTab("messenger")} testId="meta-tab-messenger" />
        )}
        {f.meta_ads && (
          <TabBtn icon={Megaphone} label="Ads" active={tab === "ads"} onClick={() => setTab("ads")} testId="meta-tab-ads" />
        )}
      </div>

      {/* Tab content */}
      {!status.connected ? (
        <div className="rounded-xl bg-blue-50 border border-blue-200 p-8 text-center">
          <p className="text-sm text-slate-600">Connectez votre compte Facebook pour commencer.</p>
        </div>
      ) : (
        <>
          {tab === "pages" && f.meta_pages && <PagesTab status={status} reload={load} />}
          {tab === "messenger" && f.meta_messenger && <MessengerTab status={status} />}
          {tab === "ads" && f.meta_ads && <AdsTab status={status} />}
        </>
      )}
    </div>
  );
}

function TabBtn({ icon: Icon, label, active, onClick, testId }) {
  return (
    <button onClick={onClick} className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition ${active ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-700"}`} data-testid={testId}>
      <Icon className="h-4 w-4" /> {label}
    </button>
  );
}

// -------- Pages tab ----------
function PagesTab({ status, reload }) {
  const [selPage, setSelPage] = useState(status.pages?.[0]?.page_id || "");
  const [posts, setPosts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [composer, setComposer] = useState({ message: "", link: "", published: true });
  const [photo, setPhoto] = useState({ image_url: "", caption: "", published: true });

  const loadPosts = useCallback(async () => {
    if (!selPage) return;
    setBusy(true);
    try {
      const r = await apiClient.get(`/me/meta/pages/${selPage}/posts?limit=10`);
      setPosts(r.data?.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur chargement posts");
    } finally { setBusy(false); }
  }, [selPage]);
  useEffect(() => { loadPosts(); }, [loadPosts]);

  const publish = async () => {
    if (!composer.message.trim()) return toast.warning("Saisissez un message");
    setBusy(true);
    try {
      await apiClient.post(`/me/meta/pages/${selPage}/posts`, composer);
      toast.success("Post publié");
      setComposer({ message: "", link: "", published: true });
      loadPosts();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur publication"); }
    finally { setBusy(false); }
  };

  const uploadPhoto = async () => {
    if (!photo.image_url.trim()) return toast.warning("URL d'image requise");
    setBusy(true);
    try {
      await apiClient.post(`/me/meta/pages/${selPage}/photos`, photo);
      toast.success("Photo publiée");
      setPhoto({ image_url: "", caption: "", published: true });
      loadPosts();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur photo"); }
    finally { setBusy(false); }
  };

  if (!status.pages?.length) {
    return <div className="p-6 text-sm text-slate-500 text-center bg-slate-50 rounded-lg">Aucune Page Facebook trouvée sur ce compte.</div>;
  }

  return (
    <div className="space-y-4" data-testid="meta-pages-tab">
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600">Page :</label>
        <select value={selPage} onChange={(e) => setSelPage(e.target.value)} className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm" data-testid="meta-page-select">
          {status.pages.map((p) => <option key={p.page_id} value={p.page_id}>{p.name}</option>)}
        </select>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        {/* Composer */}
        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold flex items-center gap-2"><Plus className="h-4 w-4" /> Nouveau post</h3>
          <textarea
            value={composer.message} onChange={(e) => setComposer({ ...composer, message: e.target.value })}
            placeholder="Quoi de neuf ?" rows={4}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
            data-testid="meta-post-message"
          />
          <input
            type="url" value={composer.link} onChange={(e) => setComposer({ ...composer, link: e.target.value })}
            placeholder="Lien (optionnel)"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
          />
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={composer.published} onChange={(e) => setComposer({ ...composer, published: e.target.checked })} />
            Publier immédiatement (sinon brouillon)
          </label>
          <button onClick={publish} disabled={busy} className="w-full inline-flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium" data-testid="meta-publish-btn">
            <Send className="h-4 w-4" /> Publier
          </button>
        </div>

        {/* Photo uploader */}
        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold flex items-center gap-2"><ImageIcon className="h-4 w-4" /> Publier une photo</h3>
          {/* Iter43-fix24az-l retest — Local media import (image only for FB photo endpoint) */}
          <LocalMediaImporter
            accept="image"
            maxSizeMb={20}
            label="Importer une image locale"
            testIdPrefix="meta-photo-local-import"
            onImported={(m) => setPhoto((p) => ({ ...p, image_url: m.public_url }))}
          />
          <input
            type="url" value={photo.image_url} onChange={(e) => setPhoto({ ...photo, image_url: e.target.value })}
            placeholder="… ou coller une URL publique d'image (https://…)"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
            data-testid="meta-photo-image-url"
          />
          <input
            type="text" value={photo.caption} onChange={(e) => setPhoto({ ...photo, caption: e.target.value })}
            placeholder="Légende (optionnel)"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
          />
          <button onClick={uploadPhoto} disabled={busy} className="w-full inline-flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium">
            <Send className="h-4 w-4" /> Téléverser
          </button>
        </div>
      </div>

      {/* Recent posts */}
      <div>
        <h3 className="text-sm font-semibold mb-2 flex items-center justify-between">
          <span>Derniers posts</span>
          <button onClick={loadPosts} className="text-xs text-blue-600 hover:underline">Actualiser</button>
        </h3>
        {busy ? <Loader2 className="h-5 w-5 animate-spin text-blue-500" /> : posts.length === 0 ? (
          <p className="text-xs text-slate-400 italic">Aucun post.</p>
        ) : (
          <div className="space-y-2">
            {posts.map((p) => (
              <div key={p.id} className="bg-white border border-slate-200 rounded-lg p-3 text-sm" data-testid={`meta-post-${p.id}`}>
                <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
                  <span>{new Date(p.created_time).toLocaleString("fr-FR")}</span>
                  {!p.is_published && <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded">Brouillon</span>}
                </div>
                <p className="whitespace-pre-wrap">{p.message || <em className="text-slate-400">(sans texte)</em>}</p>
                <div className="mt-2 flex items-center gap-3 text-xs text-slate-500">
                  {p.reactions?.summary && <span>👍 {p.reactions.summary.total_count}</span>}
                  {p.comments?.summary && <span>💬 {p.comments.summary.total_count}</span>}
                  {p.permalink_url && <a href={p.permalink_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">Voir sur Facebook</a>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// -------- Messenger tab ----------
function MessengerTab({ status }) {
  const [selPage, setSelPage] = useState(status.pages?.[0]?.page_id || "");
  const [convos, setConvos] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!selPage) return;
    setBusy(true);
    try {
      const r = await apiClient.get(`/me/meta/messenger/conversations?page_id=${selPage}&limit=20`);
      setConvos(r.data?.data || []);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur conversations"); }
    finally { setBusy(false); }
  }, [selPage]);
  useEffect(() => { load(); }, [load]);

  if (!status.pages?.length) {
    return <div className="p-6 text-sm text-slate-500 text-center bg-slate-50 rounded-lg">Aucune Page connectée — pas d'inbox Messenger disponible.</div>;
  }

  return (
    <div className="space-y-4" data-testid="meta-messenger-tab">
      <div className="flex items-center gap-2">
        <label className="text-sm text-slate-600">Page :</label>
        <select value={selPage} onChange={(e) => setSelPage(e.target.value)} className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm">
          {status.pages.map((p) => <option key={p.page_id} value={p.page_id}>{p.name}</option>)}
        </select>
        <button onClick={load} className="ml-auto text-xs text-blue-600 hover:underline">Actualiser</button>
      </div>
      {busy ? <Loader2 className="h-5 w-5 animate-spin text-blue-500" /> : convos.length === 0 ? (
        <p className="text-sm text-slate-400 italic">Aucune conversation récente.</p>
      ) : (
        <div className="space-y-2">
          {convos.map((c) => {
            const lastMsg = c.messages?.data?.[0];
            const participant = c.participants?.data?.[0];
            return (
              <div key={c.id} className="bg-white border border-slate-200 rounded-lg p-3" data-testid={`meta-convo-${c.id}`}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-slate-800">{participant?.name || "Inconnu"}</span>
                  <span className="text-slate-500">{c.updated_time ? new Date(c.updated_time).toLocaleString("fr-FR") : ""}</span>
                </div>
                {lastMsg && <p className="mt-1 text-sm text-slate-600 truncate">{lastMsg.message || <em>(média)</em>}</p>}
                <p className="text-[10px] text-slate-400 mt-1">{c.message_count || 0} message(s)</p>
              </div>
            );
          })}
        </div>
      )}
      <p className="text-xs text-slate-400 italic">
        💬 L'envoi de messages depuis cette inbox sera activé dans la prochaine itération. Pour l'instant, utilisez Meta Business Suite pour répondre.
      </p>
    </div>
  );
}

// -------- Ads tab ----------
function AdsTab({ status }) {
  const [selAcc, setSelAcc] = useState(status.ads_accounts?.[0]?.id || "");
  const [insights, setInsights] = useState(null);
  const [busy, setBusy] = useState(false);
  const [datePreset, setDatePreset] = useState("last_7d");

  const load = useCallback(async () => {
    if (!selAcc) return;
    setBusy(true);
    try {
      const r = await apiClient.get(`/me/meta/ads/accounts/${selAcc}/insights?date_preset=${datePreset}`);
      setInsights(r.data?.data?.[0] || {});
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur insights"); setInsights({}); }
    finally { setBusy(false); }
  }, [selAcc, datePreset]);
  useEffect(() => { load(); }, [load]);

  if (!status.ads_accounts?.length) {
    return <div className="p-6 text-sm text-slate-500 text-center bg-slate-50 rounded-lg">Aucun compte publicitaire trouvé.</div>;
  }

  return (
    <div className="space-y-4" data-testid="meta-ads-tab">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-sm text-slate-600">Compte Ads :</label>
        <select value={selAcc} onChange={(e) => setSelAcc(e.target.value)} className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm" data-testid="meta-ads-account-select">
          {status.ads_accounts.map((a) => <option key={a.id} value={a.id}>{a.name || a.id} ({a.currency})</option>)}
        </select>
        <select value={datePreset} onChange={(e) => setDatePreset(e.target.value)} className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm">
          <option value="today">Aujourd'hui</option>
          <option value="yesterday">Hier</option>
          <option value="last_7d">7 derniers jours</option>
          <option value="last_30d">30 derniers jours</option>
          <option value="this_month">Ce mois</option>
        </select>
      </div>
      {busy ? <Loader2 className="h-5 w-5 animate-spin text-blue-500" /> : insights ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Impressions" value={insights.impressions} />
          <Stat label="Clics" value={insights.clicks} />
          <Stat label="Dépenses" value={insights.spend ? `${insights.spend} ${status.ads_accounts.find((a) => a.id === selAcc)?.currency || ""}` : "-"} />
          <Stat label="Portée" value={insights.reach} />
          <Stat label="CTR" value={insights.ctr ? `${parseFloat(insights.ctr).toFixed(2)}%` : "-"} />
          <Stat label="CPC" value={insights.cpc ? `${parseFloat(insights.cpc).toFixed(2)}` : "-"} />
        </div>
      ) : null}
      <p className="text-xs text-slate-400 italic">
        📊 Création de campagnes et ad sets disponibles via API. UI de création complète à venir dans Iter38i.
      </p>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4">
      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
      <p className="text-2xl font-display font-bold text-slate-800 mt-1 flex items-center gap-1">
        <BarChart3 className="h-5 w-5 text-blue-600" /> {value ?? "-"}
      </p>
    </div>
  );
}
