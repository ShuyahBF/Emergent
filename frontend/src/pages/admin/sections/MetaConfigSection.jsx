// =====================================================================
// Iter38h — Meta Graph API admin configuration section.
// Stores App ID + secret + verify token + redirect URI + graph version.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Facebook, Save, Copy } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const TITLE = "Intégration Meta (Facebook / Messenger / Ads)";

const MetaConfigSection = () => {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/meta/config");
      setCfg(r.data);
      setForm({
        meta_app_id: r.data.meta_app_id || "",
        meta_graph_version: r.data.meta_graph_version || "v20.0",
        meta_redirect_uri: r.data.meta_redirect_uri || r.data.default_redirect_uri || "",
        meta_app_secret: "",
        meta_webhook_verify_token: "",
      });
    } catch {
      toast.error("Erreur chargement config Meta");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      // Only send fields the admin actually filled (avoid wiping secrets with blanks)
      const payload = {};
      if (form.meta_app_id !== undefined) payload.meta_app_id = form.meta_app_id;
      if (form.meta_graph_version) payload.meta_graph_version = form.meta_graph_version;
      if (form.meta_redirect_uri !== undefined) payload.meta_redirect_uri = form.meta_redirect_uri;
      if (form.meta_app_secret && form.meta_app_secret.trim()) payload.meta_app_secret = form.meta_app_secret.trim();
      if (form.meta_webhook_verify_token && form.meta_webhook_verify_token.trim()) payload.meta_webhook_verify_token = form.meta_webhook_verify_token.trim();
      await apiClient.put("/admin/meta/config", payload);
      toast.success("Configuration Meta enregistrée");
      setForm((f) => ({ ...f, meta_app_secret: "", meta_webhook_verify_token: "" }));
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur enregistrement");
    } finally { setSaving(false); }
  };

  const copyToClipboard = (text, label) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => toast.success(`${label} copié`));
    }
  };

  if (!cfg) return null;

  return (
    <div id="s-meta-integration" className="scroll-mt-32" data-settings-anchor="s-meta-integration">
      <div className="rounded-xl border-2 border-blue-300 bg-blue-50/40 p-6 space-y-4" data-testid="admin-meta-config">
        <div className="flex items-center gap-2">
          <Facebook className="h-4 w-4 text-blue-700" />
          <h2 className="font-display font-semibold">{TITLE}</h2>
        </div>
        <p className="text-sm text-slate-600">
          Configurez votre application Meta (compatible Facebook Pages, Messenger Platform et
          Marketing API). Une seule App peut servir aux 3 modules. <strong>Activez ensuite</strong> les
          modules souhaités par client dans <em>Clients liés → SMART COMMUNICATIONS → Features</em>.
          Documentation : <a href="https://developers.facebook.com/apps" target="_blank" rel="noreferrer" className="text-blue-700 underline">developers.facebook.com/apps</a>.
        </p>

        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-800">Identifiants App Meta</h3>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-500 mb-1 block">App ID</label>
              <input
                type="text" value={form.meta_app_id || ""}
                onChange={(e) => setForm({ ...form, meta_app_id: e.target.value })}
                placeholder="123456789012345"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
                data-testid="meta-app-id"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">App Secret (laisser vide pour conserver)</label>
              <input
                type="password" value={form.meta_app_secret || ""}
                onChange={(e) => setForm({ ...form, meta_app_secret: e.target.value })}
                placeholder={cfg.meta_app_secret_preview || "App Secret"}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
                data-testid="meta-app-secret"
              />
              <p className="text-[10px] text-slate-400 mt-0.5">Actuellement : <code>{cfg.meta_app_secret_preview || "non défini"}</code></p>
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Verify Token Webhook (laisser vide pour conserver)</label>
              <input
                type="password" value={form.meta_webhook_verify_token || ""}
                onChange={(e) => setForm({ ...form, meta_webhook_verify_token: e.target.value })}
                placeholder={cfg.meta_webhook_verify_token_preview || "Verify Token"}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
                data-testid="meta-webhook-token"
              />
              <p className="text-[10px] text-slate-400 mt-0.5">Actuellement : <code>{cfg.meta_webhook_verify_token_preview || "non défini"}</code></p>
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Graph API version</label>
              <input
                type="text" value={form.meta_graph_version || ""}
                onChange={(e) => setForm({ ...form, meta_graph_version: e.target.value })}
                placeholder="v20.0"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono"
                data-testid="meta-graph-version"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="text-xs text-slate-500 mb-1 block">Redirect URI (à copier dans la config Meta App → Facebook Login)</label>
              <div className="flex gap-2">
                <input
                  type="text" value={form.meta_redirect_uri || ""}
                  onChange={(e) => setForm({ ...form, meta_redirect_uri: e.target.value })}
                  className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-xs font-mono"
                  data-testid="meta-redirect-uri"
                />
                <button onClick={() => copyToClipboard(form.meta_redirect_uri, "Redirect URI")} className="px-3 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-xs">
                  <Copy className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
          <div className="flex justify-end">
            <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-2 text-sm font-medium" data-testid="meta-save-btn">
              <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer"}
            </button>
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-2">
          <h3 className="text-sm font-semibold text-slate-800">Webhook Messenger / Pages</h3>
          <p className="text-xs text-slate-600">
            Dans <em>Meta App Dashboard → Webhooks</em>, ajoutez l'URL ci-dessous comme callback,
            collez votre <em>Verify Token</em> dans le champ correspondant et abonnez-vous aux
            champs <code>messages</code>, <code>messaging_postbacks</code>, <code>feed</code>.
          </p>
          <div className="flex gap-2 items-center">
            <input readOnly value={cfg.webhook_callback_url} className="flex-1 px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono" data-testid="meta-webhook-url" />
            <button onClick={() => copyToClipboard(cfg.webhook_callback_url, "URL webhook")} className="px-3 py-2 bg-slate-100 hover:bg-slate-200 rounded-lg text-xs">
              <Copy className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-900">
          <strong>Étapes à suivre côté Meta :</strong>
          <ol className="list-decimal list-inside mt-1 space-y-0.5">
            <li>Créer/réutiliser votre App Meta sur <a href="https://developers.facebook.com/apps" target="_blank" rel="noreferrer" className="underline">developers.facebook.com/apps</a></li>
            <li>Produits à activer : <em>Facebook Login</em>, <em>Pages API</em>, <em>Messenger</em>, <em>Marketing API</em></li>
            <li>Dans <em>Facebook Login → Valid OAuth Redirect URIs</em> : coller l'URI ci-dessus</li>
            <li>Dans <em>Webhooks</em> : coller l'URL callback + le Verify Token</li>
            <li>Permissions à demander en App Review : <code>pages_show_list, pages_manage_posts, pages_messaging, ads_management, ads_read</code></li>
          </ol>
        </div>
      </div>
    </div>
  );
};

export default MetaConfigSection;
