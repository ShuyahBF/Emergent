// Iter41 Phase 3 (2026-02) — Section AdminSettings : Synthèse Liluvine + API Officines
// + Image de fond de sidebar (upload OU couleur dans S057).
import React, { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Loader2, Save, Eye, EyeOff, Sparkles, Upload, Image as ImageIcon, X, Plug
} from "lucide-react";

function TextField({ label, value, onChange, type = "text", testid, placeholder, hint }) {
  return (
    <label className="block text-xs">
      <span className="block text-slate-600 mb-1">{label}</span>
      <input type={type} value={value ?? ""}
             onChange={(e) => onChange(type === "number" ? (parseFloat(e.target.value) || 0) : e.target.value)}
             placeholder={placeholder}
             className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 focus:ring-fuchsia-500"
             data-testid={testid} />
      {hint && <p className="text-[10px] text-slate-400 mt-1">{hint}</p>}
    </label>
  );
}

function SecretField({ label, value, onChange, testid, placeholder }) {
  const [show, setShow] = useState(false);
  return (
    <label className="block text-xs">
      <span className="block text-slate-600 mb-1">{label}</span>
      <div className="flex items-stretch gap-1">
        <input type={show ? "text" : "password"} value={value ?? ""} onChange={(e) => onChange(e.target.value)}
               placeholder={placeholder}
               className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
               data-testid={testid} />
        <button type="button" onClick={() => setShow(!show)} className="px-2 ring-1 ring-slate-300 rounded text-slate-500 hover:bg-slate-50">
          {show ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
        </button>
      </div>
      {value === "********" && <p className="text-[10px] text-amber-600 mt-1">Token masqué — écrire pour remplacer.</p>}
    </label>
  );
}

export default function S059SyntheseOfficinesSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  // Iter42b — Test "à la demande" de la synthèse Liluvine
  const [synthTesting, setSynthTesting] = useState(false);
  const [synthResult, setSynthResult] = useState(null);
  const [form, setForm] = useState({});
  const fileRef = useRef(null);

  const load = async () => {
    let next;
    try {
      const r = await apiClient.get("/admin/settings");
      next = r.data || {};
    } catch (e) {
      toast.error("Erreur chargement");
    }
    setTimeout(() => {
      if (next) setForm(next);
      setLoading(false);
    }, 0);
  };

  useEffect(() => { load(); }, []);

  const upd = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const out = {
        synthese_enabled: !!form.synthese_enabled,
        synthese_email_to: form.synthese_email_to || "",
        synthese_wa_to: form.synthese_wa_to || "",
        synthese_hour: form.synthese_hour || "08:00",
        synthese_prompt: form.synthese_prompt || "",
        synthese_channels: form.synthese_channels || "both",
        officines_api_url: form.officines_api_url || "",
        officines_api_timeout: parseInt(form.officines_api_timeout) || 12,
        officines_public_quota_per_day: parseInt(form.officines_public_quota_per_day) || 10,
        sidebar_bg_image_url: form.sidebar_bg_image_url || "",
        sidebar_bg_image_opacity: typeof form.sidebar_bg_image_opacity === "number" ? form.sidebar_bg_image_opacity : 1,
      };
      if (form.officines_api_token && form.officines_api_token !== "********") {
        out.officines_api_token = form.officines_api_token;
      }
      await apiClient.put("/admin/settings", out);
      toast.success("Paramètres enregistrés");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setSaving(false), 0);
  };

  const handleUpload = async (file) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      toast.error("Fichier trop volumineux (max 2 MB)");
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiClient.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const url = r.data?.url || `/api/files/${r.data?.id}`;
      upd("sidebar_bg_image_url", url);
      toast.success("Image uploadée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur upload");
    }
    setTimeout(() => setUploading(false), 0);
  };

  const testOfficines = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await apiClient.post("/admin/officines/test-connection");
      setTestResult(r.data);
      if (r.data?.ok) toast.success("API Officines OK");
      else toast.error(`Échec : ${r.data?.error || "inconnu"}`);
    } catch (e) {
      const detail = e?.response?.data?.detail || "Erreur réseau";
      setTestResult({ ok: false, error: detail, debug: null });
      toast.error(detail);
    }
    setTimeout(() => setTesting(false), 0);
  };

  // Iter42b — Tester la synthèse Liluvine à la demande
  const testSynthese = async () => {
    setSynthTesting(true); setSynthResult(null);
    try {
      const r = await apiClient.post("/admin/synthese/test");
      setSynthResult(r.data);
      if (r.data?.ok) toast.success(`Synthèse envoyée (email=${r.data.sent_email}, wa=${r.data.sent_wa})`);
      else toast.warning("Synthèse générée mais aucun canal n'a pu envoyer — voir détail");
    } catch (e) {
      const detail = e?.response?.data?.detail || "Erreur réseau";
      setSynthResult({ ok: false, errors: [detail] });
      toast.error(detail);
    } finally { setSynthTesting(false); }
  };

  if (loading) return (
    <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
      <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
    </div>
  );

  return (
    <div className="space-y-6" data-testid="s059-section">
      {/* === Synthèse Liluvine === */}
      <div className="ring-1 ring-slate-200 rounded-lg p-4 bg-white space-y-3" data-testid="s059-synthese-block">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-fuchsia-100 flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-fuchsia-600" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">Synthèse programmée Liluvine</h3>
            <p className="text-xs text-slate-500 mt-1">
              Chaque jour à l&apos;heure choisie, Liluvine génère une synthèse de l&apos;activité (KPIs + prompt personnalisé) et l&apos;envoie par email, WhatsApp ou les deux. Aussi accessible à la demande via la commande WhatsApp <code>!synthese [début] [fin]</code>.
            </p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input type="checkbox" checked={!!form.synthese_enabled}
                 onChange={(e) => upd("synthese_enabled", e.target.checked)}
                 className="h-4 w-4" data-testid="synthese-enabled" />
          <span className="font-semibold">Synthèse activée</span>
        </label>
        <div className="grid sm:grid-cols-2 gap-3">
          <TextField label="Email destinataire" value={form.synthese_email_to}
                     onChange={(v) => upd("synthese_email_to", v)}
                     placeholder="boss@etablissement.com" testid="synthese-email" />
          <TextField label="Numéro WhatsApp (sans le +)" value={form.synthese_wa_to}
                     onChange={(v) => upd("synthese_wa_to", v)}
                     placeholder="22670000000" testid="synthese-wa" />
          <TextField label="Heure d'envoi (HH:MM)" value={form.synthese_hour}
                     onChange={(v) => upd("synthese_hour", v)}
                     placeholder="08:00" testid="synthese-hour" hint="Fuseau Africa/Abidjan" />
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Canaux</span>
            <select value={form.synthese_channels || "both"}
                    onChange={(e) => upd("synthese_channels", e.target.value)}
                    className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
                    data-testid="synthese-channels">
              <option value="both">📧 Email + 📱 WhatsApp</option>
              <option value="email">📧 Email uniquement</option>
              <option value="wa">📱 WhatsApp uniquement</option>
            </select>
          </label>
        </div>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Prompt envoyé à Liluvine</span>
          <textarea value={form.synthese_prompt || ""} onChange={(e) => upd("synthese_prompt", e.target.value)} rows={4}
                    placeholder="ex: Synthétise l'activité du jour en 5 puces actionnables, en français, avec emojis. Mets en gras les points critiques."
                    className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                    data-testid="synthese-prompt" />
          <p className="text-[10px] text-slate-400 mt-1">Les KPIs structurés (contacts, tickets, RDV, paiements…) sont injectés automatiquement après votre prompt.</p>
        </label>
        {/* Iter42b — Bouton test à la demande */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button onClick={testSynthese} disabled={synthTesting}
                  className="text-xs px-3 py-1.5 rounded ring-1 ring-fuchsia-300 text-fuchsia-700 hover:bg-fuchsia-50 inline-flex items-center gap-1 disabled:opacity-60"
                  data-testid="synthese-test-btn">
            {synthTesting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />} Tester la synthèse maintenant
          </button>
          {synthResult && (
            <span className={`text-[10px] px-2 py-0.5 rounded ${synthResult.ok ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`} data-testid="synthese-test-result-badge">
              {synthResult.ok ? `✅ email=${synthResult.sent_email ? "OK" : "—"} / wa=${synthResult.sent_wa ? "OK" : "—"}` : `⚠️ ${(synthResult.errors || [])[0] || "Échec"}`}
            </span>
          )}
        </div>
        {synthResult && (synthResult.preview || synthResult.errors?.length) && (
          <details className="text-xs ring-1 ring-slate-300 rounded bg-slate-50" data-testid="synthese-test-debug">
            <summary className="cursor-pointer px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100">
              🔍 Aperçu de la synthèse {synthResult.errors?.length > 0 && `(${synthResult.errors.length} erreur·s)`}
            </summary>
            <div className="p-3 space-y-2">
              {synthResult.errors?.length > 0 && (
                <div className="bg-rose-50 ring-1 ring-rose-200 rounded p-2 text-[11px] text-rose-800">
                  <p className="font-semibold">Erreurs :</p>
                  <ul className="list-disc list-inside">
                    {synthResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                  </ul>
                </div>
              )}
              {synthResult.preview && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Aperçu (500 premiers caractères)</p>
                  <pre className="bg-white ring-1 ring-slate-200 rounded p-2 text-[11px] whitespace-pre-wrap break-words max-h-60 overflow-auto">{synthResult.preview}</pre>
                </div>
              )}
              {synthResult.config && (
                <div className="text-[11px] text-slate-600">
                  <p>Config : enabled={String(synthResult.config.synthese_enabled)} • email_to=<code>{synthResult.config.email_to || "(vide)"}</code> • wa_to=<code>{synthResult.config.wa_to || "(vide)"}</code> • heure=<code>{synthResult.config.hour}</code></p>
                </div>
              )}
            </div>
          </details>
        )}
      </div>

      {/* === API Officines === */}
      <div className="ring-1 ring-slate-200 rounded-lg p-4 bg-white space-y-3" data-testid="s059-officines-block">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-emerald-100 flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-emerald-600" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">API « Officines » (lookup distribué)</h3>
            <p className="text-xs text-slate-500 mt-1">
              Endpoint POST qui retourne la liste des officines où un produit est disponible (prix moyen, disponibilité). Utilisé par le bouton « Voir officines » sur les fiches VIDAL et par la commande WhatsApp publique <code>!aizenta &lt;produit&gt;</code>.
            </p>
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <TextField label="URL endpoint POST" value={form.officines_api_url}
                     onChange={(v) => upd("officines_api_url", v)}
                     placeholder="https://votre-serveur.com/api/officines/lookup"
                     testid="officines-url" />
          <SecretField label="Token Bearer" value={form.officines_api_token}
                       onChange={(v) => upd("officines_api_token", v)}
                       placeholder="token secret" testid="officines-token" />
          <TextField label="Timeout HTTP (s)" type="number" value={form.officines_api_timeout}
                     onChange={(v) => upd("officines_api_timeout", v)}
                     placeholder="12" testid="officines-timeout" hint="2 à 60" />
          <TextField label="Quota !aizenta /jour /numéro" type="number"
                     value={form.officines_public_quota_per_day}
                     onChange={(v) => upd("officines_public_quota_per_day", v)}
                     placeholder="10" testid="officines-quota"
                     hint="0 = illimité (déconseillé)" />
        </div>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button onClick={testOfficines} disabled={testing}
                  className="text-xs px-3 py-1.5 rounded ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-50 inline-flex items-center gap-1 disabled:opacity-60"
                  data-testid="officines-test-btn">
            {testing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plug className="h-3 w-3" />} Tester l&apos;URL Officines
          </button>
          {testResult && (
            <span className={`text-[10px] px-2 py-0.5 rounded ${testResult.ok ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
              {testResult.ok ? `✅ HTTP ${testResult.debug?.response?.status_code}` : `❌ ${testResult.error}`}
            </span>
          )}
        </div>
        {testResult && testResult.debug && (
          <details className="text-xs ring-1 ring-slate-300 rounded bg-slate-50" data-testid="officines-debug-panel" open>
            <summary className="cursor-pointer px-3 py-2 font-semibold text-slate-700 hover:bg-slate-100">
              🔍 Debug verbose Officines (requête + réponse)
            </summary>
            <div className="p-3 space-y-3">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Requête envoyée</div>
                <div className="bg-white ring-1 ring-slate-200 rounded p-2 space-y-1 font-mono text-[11px]">
                  <div><span className="text-emerald-600 font-semibold">{testResult.debug.request?.method}</span> <span className="break-all">{testResult.debug.request?.url}</span></div>
                  <div><span className="text-slate-500">timeout:</span> {testResult.debug.request?.timeout_seconds}s</div>
                  <div className="text-slate-500">Headers :</div>
                  <pre className="bg-slate-50 rounded p-2 overflow-auto max-h-32">{JSON.stringify(testResult.debug.request?.headers || {}, null, 2)}</pre>
                  <div className="text-slate-500">Body :</div>
                  <pre className="bg-slate-50 rounded p-2 overflow-auto max-h-32">{JSON.stringify(testResult.debug.request?.body, null, 2)}</pre>
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Réponse reçue</div>
                {testResult.debug.error ? (
                  <div className="bg-rose-100 ring-1 ring-rose-200 rounded p-2 font-mono text-[11px] text-rose-800">Erreur : {testResult.debug.error}</div>
                ) : testResult.debug.response ? (
                  <div className="bg-white ring-1 ring-slate-200 rounded p-2 space-y-1 font-mono text-[11px]">
                    <div>
                      <span className="text-slate-500">Status :</span>{" "}
                      <span className={testResult.debug.response.status_code < 400 ? "text-emerald-700 font-semibold" : "text-rose-700 font-semibold"}>
                        {testResult.debug.response.status_code}
                      </span>
                      <span className="ml-3 text-slate-400">({testResult.debug.response.elapsed_ms} ms)</span>
                    </div>
                    <div><span className="text-slate-500">Content-Type :</span> {testResult.debug.response.content_type || "(inconnu)"}</div>
                    <div className="text-slate-500">Body preview {testResult.debug.response.body_truncated && "(tronqué 2000c)"} :</div>
                    <pre className="bg-slate-50 rounded p-2 overflow-auto max-h-60 whitespace-pre-wrap break-all">{testResult.debug.response.body_preview || "(vide)"}</pre>
                  </div>
                ) : null}
              </div>
            </div>
          </details>
        )}
      </div>

      {/* === Sidebar BG image === */}
      <div className="ring-1 ring-slate-200 rounded-lg p-4 bg-white space-y-3" data-testid="s059-sidebar-image-block">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-violet-100 flex items-center justify-center">
            <ImageIcon className="h-5 w-5 text-violet-600" />
          </div>
          <div className="flex-1">
            <h3 className="font-semibold text-slate-900">Image de fond de la sidebar du portail</h3>
            <p className="text-xs text-slate-500 mt-1">
              Alternative à la couleur unie (réglée dans S057). Si une image est définie ici, elle prime sur la couleur. Format recommandé : JPG/PNG 400×900px max, &lt; 2 MB.
            </p>
          </div>
        </div>
        {form.sidebar_bg_image_url ? (
          <div className="flex items-stretch gap-3">
            <img src={form.sidebar_bg_image_url} alt="Aperçu sidebar"
                 className="h-32 w-20 object-cover ring-1 ring-slate-200 rounded"
                 data-testid="sidebar-image-preview" />
            <div className="flex-1 space-y-2">
              <code className="block text-[11px] bg-slate-50 rounded p-2 ring-1 ring-slate-200 break-all" data-testid="sidebar-image-url-display">{form.sidebar_bg_image_url}</code>
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">Opacité ({form.sidebar_bg_image_opacity ?? 1})</span>
                <input type="range" min="0" max="1" step="0.05"
                       value={form.sidebar_bg_image_opacity ?? 1}
                       onChange={(e) => upd("sidebar_bg_image_opacity", parseFloat(e.target.value))}
                       className="w-full" data-testid="sidebar-image-opacity" />
              </label>
              <button onClick={() => upd("sidebar_bg_image_url", "")}
                      className="text-xs px-2 py-1 rounded ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50 inline-flex items-center gap-1"
                      data-testid="sidebar-image-remove">
                <X className="h-3 w-3" /> Retirer l&apos;image (revenir à la couleur S057)
              </button>
            </div>
          </div>
        ) : (
          <div>
            <input ref={fileRef} type="file" accept="image/*" hidden
                   onChange={(e) => handleUpload(e.target.files?.[0])}
                   data-testid="sidebar-image-input" />
            <button onClick={() => fileRef.current?.click()} disabled={uploading}
                    className="text-sm px-3 py-2 rounded bg-violet-600 hover:bg-violet-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
                    data-testid="sidebar-image-upload-btn">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Téléverser une image
            </button>
          </div>
        )}
      </div>

      <div className="sticky bottom-0 bg-white border-t border-slate-200 -mx-4 -mb-4 px-4 py-3 flex justify-end">
        <button onClick={save} disabled={saving}
                className="text-sm px-4 py-2 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
                data-testid="s059-save-btn">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer
        </button>
      </div>
    </div>
  );
}
