/*
 * Iter43-fix24az-o (2026-07-21) + Iter43-fix24az-p (2026-07-22) — AdminSettings section pour Liluvine Reactions.
 *
 * Features exposées :
 *   1. Fuzzy command matching (toggle + slider threshold)
 *   2. Auto-add nouveaux contacts + sélecteur du groupe par défaut
 *   3. CRUD templates de réponse aux publicités Facebook + stats
 *   4. (fix24az-p) Import CSV en masse + guide de création de template Meta
 *   5. (fix24az-p) Suggestions auto depuis les messages entrants non-traités
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Loader2, Plus, Trash2, Edit2, BarChart3, Wand2, UserPlus, Save, X,
  Upload, FileText, Lightbulb, ExternalLink, Copy, ChevronDown, ChevronRight,
} from "lucide-react";

const CSV_TEMPLATE = `name,trigger_text,response_text,trigger_variations,response_media_url,response_media_kind,active
Promo Rentrée,Puis-je en savoir plus,Bonjour ! Merci pour votre intérêt. Voici nos offres...,plus d'infos|votre offre|détails,https://example.com/promo.jpg,image,true
Nouveauté Produit,Comment commander,Voici notre procédure de commande...,je veux commander|acheter|prix,,,true
`;

export default function LiluvineReactionsSection() {
  const [cfg, setCfg] = useState(null);
  const [groups, setGroups] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [stats, setStats] = useState(null);
  const [suggestions, setSuggestions] = useState({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null);
  // fix24az-p
  const [csvOpen, setCsvOpen] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [csvBusy, setCsvBusy] = useState(false);
  const [csvResult, setCsvResult] = useState(null);
  const [suggestionsOpen, setSuggestionsOpen] = useState(true);
  const [metaGuideOpen, setMetaGuideOpen] = useState(false);
  const [convertingSid, setConvertingSid] = useState(null);
  const [convertForm, setConvertForm] = useState({ name: "", response_text: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, t, s, u] = await Promise.all([
        apiClient.get("/admin/liluvine/reactions-config"),
        apiClient.get("/admin/liluvine/reactions-templates"),
        apiClient.get("/admin/liluvine/reactions-stats"),
        apiClient.get("/admin/liluvine/unmatched-suggestions?limit=30").catch(() => ({ data: { items: [], total: 0 } })),
      ]);
      setCfg(c.data?.config || {});
      setGroups(c.data?.contact_groups || []);
      setTemplates(t.data?.templates || []);
      setStats(s.data || null);
      setSuggestions(u.data || { items: [], total: 0 });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveConfig = async () => {
    setSaving(true);
    try {
      await apiClient.put("/admin/liluvine/reactions-config", cfg);
      toast.success("Configuration enregistrée");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const startNew = () => setEditing({
    id: null, name: "", trigger_text: "", trigger_variations: [],
    response_text: "", response_media_url: "", response_media_kind: "", active: true,
  });

  const startEdit = (t) => setEditing({ ...t, trigger_variations: t.trigger_variations || [] });

  const saveTemplate = async () => {
    if (!editing) return;
    if (!editing.name?.trim() || !editing.trigger_text?.trim() || !editing.response_text?.trim()) {
      toast.error("Nom, déclencheur et réponse sont obligatoires");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: editing.name,
        trigger_text: editing.trigger_text,
        trigger_variations: (editing.trigger_variations || []).filter(Boolean),
        response_text: editing.response_text,
        response_media_url: editing.response_media_url || null,
        response_media_kind: editing.response_media_kind || null,
        active: editing.active,
      };
      if (editing.id) {
        await apiClient.put(`/admin/liluvine/reactions-templates/${editing.id}`, payload);
        toast.success("Modèle mis à jour");
      } else {
        await apiClient.post("/admin/liluvine/reactions-templates", payload);
        toast.success("Modèle créé");
      }
      setEditing(null);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur sauvegarde");
    } finally {
      setSaving(false);
    }
  };

  const deleteTemplate = async (t) => {
    if (!window.confirm(`Supprimer le modèle « ${t.name} » ?`)) return;
    try {
      await apiClient.delete(`/admin/liluvine/reactions-templates/${t.id}`);
      toast.success("Modèle supprimé");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur suppression");
    }
  };

  const uploadCsv = async (dryRun) => {
    if (!csvText?.trim()) { toast.error("Collez d'abord le CSV"); return; }
    setCsvBusy(true);
    setCsvResult(null);
    try {
      const r = await apiClient.post("/admin/liluvine/reactions-templates/bulk-csv", {
        csv: csvText, dry_run: !!dryRun,
      });
      setCsvResult(r.data);
      if (dryRun) {
        toast.success(`Prévisualisation OK · ${r.data.rows?.length || 0} ligne(s) valides · ${r.data.errors?.length || 0} erreur(s)`);
      } else {
        toast.success(`${r.data.created || 0} modèle(s) importé(s) · ${r.data.errors?.length || 0} erreur(s)`);
        if (r.data.created > 0) { setCsvText(""); setCsvOpen(false); load(); }
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur import CSV");
    } finally { setCsvBusy(false); }
  };

  const onCsvFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 500 * 1024) { toast.error("Fichier > 500 Ko, réduisez-le"); return; }
    const text = await f.text();
    setCsvText(text);
    setCsvOpen(true);
  };

  const dismissSuggestion = async (sid) => {
    try {
      await apiClient.delete(`/admin/liluvine/unmatched-suggestions/${sid}`);
      toast.success("Suggestion écartée");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const startConvertSuggestion = (s) => {
    setConvertingSid(s.id);
    setConvertForm({ name: (s.body || "").slice(0, 60), response_text: "" });
  };

  const submitConvert = async () => {
    if (!convertForm.response_text?.trim()) { toast.error("Réponse obligatoire"); return; }
    try {
      await apiClient.post(`/admin/liluvine/unmatched-suggestions/${convertingSid}/convert`, {
        name: convertForm.name,
        response_text: convertForm.response_text,
      });
      toast.success("Suggestion convertie en modèle actif");
      setConvertingSid(null);
      setConvertForm({ name: "", response_text: "" });
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur conversion");
    }
  };

  const copyToClipboard = async (text) => {
    try { await navigator.clipboard.writeText(text); toast.success("Copié"); }
    catch { toast.error("Copie échouée"); }
  };

  return (
    <section className="bg-white rounded-2xl border border-slate-200 p-6 space-y-6" data-testid="liluvine-reactions-section">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-fuchsia-100 flex items-center justify-center shrink-0">
          <Sparkles className="h-5 w-5 text-fuchsia-700" />
        </div>
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-800">Liluvine Reactions & Ad Auto-Replies</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Détection floue des commandes, réponses préconfigurées aux publicités Facebook,
            <strong> médias natifs WhatsApp</strong> (image/vidéo affichée directement),
            <strong> import CSV en masse</strong> et <strong>suggestions auto</strong> depuis les messages non-traités.
          </p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</div>
      ) : (
        <>
          {/* ---- Config globale ---- */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
            <div className="border border-slate-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Wand2 className="h-4 w-4 text-slate-500" />
                <h3 className="text-sm font-medium text-slate-700">Détection floue des commandes</h3>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!cfg?.fuzzy_match_enabled}
                  onChange={(e) => setCfg({ ...cfg, fuzzy_match_enabled: e.target.checked })}
                  data-testid="fuzzy-match-toggle"
                />
                Activer la détection floue (répond même en cas de faute)
              </label>
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Seuil de similarité : <strong>{cfg?.fuzzy_threshold || 70}%</strong>
                </label>
                <input
                  type="range" min="50" max="95" step="1"
                  value={cfg?.fuzzy_threshold || 70}
                  onChange={(e) => setCfg({ ...cfg, fuzzy_threshold: parseInt(e.target.value, 10) })}
                  className="w-full"
                  data-testid="fuzzy-threshold-slider"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">
                  Message de correction (placeholders : <code>{"{intent}"}</code>, <code>{"{cmd}"}</code>)
                </label>
                <textarea
                  rows={2}
                  value={cfg?.correction_prefix_text || ""}
                  onChange={(e) => setCfg({ ...cfg, correction_prefix_text: e.target.value })}
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                  data-testid="correction-prefix"
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-600 pt-1 border-t border-slate-100">
                <input
                  type="checkbox"
                  checked={cfg?.unmatched_capture_enabled !== false}
                  onChange={(e) => setCfg({ ...cfg, unmatched_capture_enabled: e.target.checked })}
                  data-testid="unmatched-capture-toggle"
                />
                Capturer les messages non-traités pour proposer de nouveaux modèles
              </label>
            </div>

            <div className="border border-slate-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2">
                <UserPlus className="h-4 w-4 text-slate-500" />
                <h3 className="text-sm font-medium text-slate-700">Nouveaux contacts auto</h3>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!cfg?.auto_add_new_contacts}
                  onChange={(e) => setCfg({ ...cfg, auto_add_new_contacts: e.target.checked })}
                  data-testid="auto-add-toggle"
                />
                Ajouter automatiquement chaque nouveau numéro WA détecté
              </label>
              <div>
                <label className="block text-xs text-slate-500 mb-1">Groupe par défaut</label>
                <select
                  value={cfg?.default_new_contact_group_id || ""}
                  onChange={(e) => setCfg({ ...cfg, default_new_contact_group_id: e.target.value || null })}
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                  data-testid="default-group-select"
                  disabled={!cfg?.auto_add_new_contacts}
                >
                  <option value="">— Aucun (contact non groupé) —</option>
                  {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                </select>
                <p className="text-[11px] text-slate-400 mt-1">Créez d&apos;abord vos groupes dans la section Contacts.</p>
              </div>
            </div>
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={saveConfig}
              disabled={saving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-sm disabled:opacity-50"
              data-testid="save-config-btn"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Enregistrer la configuration
            </button>
          </div>

          {/* ---- Stats ---- */}
          {stats && (
            <div className="border border-slate-200 rounded-lg p-4 bg-gradient-to-br from-slate-50 to-white">
              <div className="flex items-center gap-2 mb-3">
                <BarChart3 className="h-4 w-4 text-slate-500" />
                <h3 className="text-sm font-medium text-slate-700">Statistiques (<code>!reactions</code>)</h3>
                <span className="text-xs text-slate-400 ml-auto">
                  Total : <strong>{stats.totals?.replied || 0}</strong> / {stats.totals?.received || 0} ({stats.totals?.reply_rate || 0}%)
                </span>
              </div>
              {stats.templates?.length === 0 ? (
                <p className="text-xs text-slate-400 italic">Aucun modèle configuré</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-200">
                        <th className="text-left py-1.5 font-medium">Modèle</th>
                        <th className="text-right py-1.5 font-medium">Reçus</th>
                        <th className="text-right py-1.5 font-medium">Répondus</th>
                        <th className="text-right py-1.5 font-medium">Taux</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.templates.map((t) => (
                        <tr key={t.id} className={`border-b border-slate-100 ${t.active ? "" : "opacity-50"}`}>
                          <td className="py-1.5 pr-2 truncate max-w-[280px]" title={t.trigger_text}>{t.name || t.trigger_text}</td>
                          <td className="py-1.5 text-right font-mono">{t.received}</td>
                          <td className="py-1.5 text-right font-mono">{t.replied}</td>
                          <td className="py-1.5 text-right font-mono">{t.reply_rate}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* ---- Templates CRUD + CSV ---- */}
          <div>
            <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
              <h3 className="text-sm font-medium text-slate-700">Modèles de réponses aux publicités</h3>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCsvOpen((v) => !v)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50 text-sm"
                  data-testid="toggle-csv-btn"
                >
                  <Upload className="h-4 w-4" /> Import CSV
                </button>
                <button
                  type="button"
                  onClick={startNew}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm"
                  data-testid="new-template-btn"
                >
                  <Plus className="h-4 w-4" /> Nouveau modèle
                </button>
              </div>
            </div>

            {csvOpen && (
              <div className="border border-slate-200 rounded-lg p-4 mb-3 bg-slate-50 space-y-2" data-testid="csv-upload-panel">
                <div className="flex items-center gap-2 text-xs text-slate-600">
                  <FileText className="h-4 w-4" />
                  Import en masse (CSV). Colonnes : <code>name, trigger_text, response_text, trigger_variations (séparé par |), response_media_url, response_media_kind, active</code>.
                </div>
                <div className="flex items-center gap-2">
                  <input type="file" accept=".csv,text/csv" onChange={onCsvFile} className="text-xs" data-testid="csv-file-input" />
                  <button
                    type="button"
                    onClick={() => setCsvText(CSV_TEMPLATE)}
                    className="text-xs text-fuchsia-600 hover:underline"
                    data-testid="csv-template-btn"
                  >
                    Charger le modèle d&apos;exemple
                  </button>
                </div>
                <textarea
                  value={csvText}
                  onChange={(e) => setCsvText(e.target.value)}
                  rows={6}
                  placeholder="Collez votre CSV ici (ou utilisez le sélecteur de fichier)"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-xs font-mono"
                  data-testid="csv-textarea"
                />
                {csvResult && (
                  <div className="text-xs text-slate-700 bg-white border border-slate-200 rounded p-2 space-y-1" data-testid="csv-result">
                    <p><strong>Import :</strong> {csvResult.dry_run ? "Prévisualisation" : "Effectué"}</p>
                    <p><strong>Créés :</strong> {csvResult.created || 0} · <strong>Erreurs :</strong> {csvResult.errors?.length || 0}</p>
                    {csvResult.errors?.length > 0 && (
                      <ul className="text-red-600 list-disc list-inside">
                        {csvResult.errors.slice(0, 5).map((err, i) => (
                          <li key={i}>Ligne {err.line} : {err.error}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => uploadCsv(true)}
                    disabled={csvBusy || !csvText.trim()}
                    className="px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-100 text-xs disabled:opacity-50"
                    data-testid="csv-preview-btn"
                  >
                    Prévisualiser
                  </button>
                  <button
                    type="button"
                    onClick={() => uploadCsv(false)}
                    disabled={csvBusy || !csvText.trim()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-xs disabled:opacity-50"
                    data-testid="csv-import-btn"
                  >
                    {csvBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                    Importer
                  </button>
                </div>
              </div>
            )}

            {templates.length === 0 ? (
              <div className="text-center py-6 text-sm text-slate-400 border border-dashed border-slate-300 rounded-lg">
                Aucun modèle. Créez-en un pour répondre automatiquement aux clics depuis vos publicités Facebook.
              </div>
            ) : (
              <ul className="divide-y divide-slate-100 border border-slate-200 rounded-lg">
                {templates.map((t) => (
                  <li key={t.id} className="p-3 flex items-start gap-3 hover:bg-slate-50">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`inline-block w-2 h-2 rounded-full ${t.active ? "bg-emerald-500" : "bg-slate-300"}`} />
                        <strong className="text-sm truncate">{t.name}</strong>
                        <span className="text-xs text-slate-400 truncate">— {t.trigger_text}</span>
                        {t.response_media_url && (
                          <span
                            className="text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-100 text-fuchsia-700"
                            title={`Média natif WhatsApp : ${t.response_media_kind || "image"}`}
                          >
                            📎 {t.response_media_kind || "media"}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-600 mt-1 truncate">{t.response_text}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => startEdit(t)}
                      className="p-1.5 rounded hover:bg-slate-100 text-slate-500"
                      data-testid={`edit-template-${t.id}`}
                    ><Edit2 className="h-4 w-4" /></button>
                    <button
                      type="button"
                      onClick={() => deleteTemplate(t)}
                      className="p-1.5 rounded hover:bg-red-50 text-red-500"
                      data-testid={`delete-template-${t.id}`}
                    ><Trash2 className="h-4 w-4" /></button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* ---- Meta template creation guide ---- */}
          <div className="border border-blue-200 bg-blue-50/50 rounded-lg" data-testid="meta-template-guide">
            <button
              type="button"
              onClick={() => setMetaGuideOpen((v) => !v)}
              className="w-full px-4 py-2.5 flex items-center gap-2 text-sm font-medium text-blue-800 hover:bg-blue-100/50 rounded-lg"
            >
              {metaGuideOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              <ExternalLink className="h-4 w-4" />
              Guide : créer un template WhatsApp <code>rdv_reminder_1h_fr</code> chez Meta (rappel RDV 1h avant)
            </button>
            {metaGuideOpen && (
              <div className="px-4 pb-4 text-xs text-slate-700 space-y-2 border-t border-blue-200">
                <p className="pt-2">
                  Le template Meta est <strong>obligatoire</strong> pour envoyer un message WhatsApp <strong>hors des 24h de la fenêtre client-support</strong>
                  (donc un rappel de RDV pour un nouveau contact). Créez-le une fois chez Meta et sélectionnez-le dans la config du Planning.
                </p>
                <ol className="list-decimal list-inside space-y-1.5 pl-2">
                  <li>Ouvrez <a href="https://business.facebook.com/wa/manage/message-templates" target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">Meta Business Manager → Message templates</a></li>
                  <li>Cliquez sur <strong>« Créer un modèle »</strong> · Catégorie : <code>UTILITY</code> · Langue : <code>Français (fr)</code></li>
                  <li>Nom du modèle : <code className="bg-white px-1 rounded">rdv_reminder_1h_fr</code>
                    <button onClick={() => copyToClipboard("rdv_reminder_1h_fr")} className="ml-2 inline-flex items-center gap-1 text-[10px] text-blue-600 hover:underline">
                      <Copy className="h-3 w-3" /> copier
                    </button>
                  </li>
                  <li>
                    Corps (variables <code>{"{{1}}"}</code> = patient, <code>{"{{2}}"}</code> = médecin, <code>{"{{3}}"}</code> = heure, <code>{"{{4}}"}</code> = motif) :
                    <pre className="mt-1 bg-white p-2 rounded border border-blue-200 text-[11px] whitespace-pre-wrap">
{`Bonjour {{1}}, rappel : votre rendez-vous avec {{2}} est prévu à {{3}}. 
Motif : {{4}}
À très vite ! (Réponse STOP pour annuler.)`}
                    </pre>
                  </li>
                  <li>Ajoutez 4 échantillons de valeurs pour approbation.</li>
                  <li>Soumettez pour review Meta (délai habituel : 1-24h). Une fois approuvé, il apparaîtra dans la section Planning → Config rappels.</li>
                </ol>
                <p className="text-[11px] text-slate-500 italic">
                  💡 Pour d&apos;autres cas d&apos;usage (promos, relances), créez des templates <code>MARKETING</code> avec la même procédure.
                </p>
              </div>
            )}
          </div>

          {/* ---- Iter43-fix24az-p — Suggestions auto ---- */}
          <div className="border border-amber-200 bg-amber-50/40 rounded-lg" data-testid="suggestions-panel">
            <button
              type="button"
              onClick={() => setSuggestionsOpen((v) => !v)}
              className="w-full px-4 py-2.5 flex items-center gap-2 text-sm font-medium text-amber-900 hover:bg-amber-100/60 rounded-lg"
              data-testid="toggle-suggestions-btn"
            >
              {suggestionsOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
              <Lightbulb className="h-4 w-4" />
              Suggestions de nouveaux modèles ({suggestions.total || 0})
              <span className="text-[10px] text-amber-700 ml-auto font-normal">
                Messages non-traités regroupés par similarité
              </span>
            </button>
            {suggestionsOpen && (
              <div className="px-4 pb-3 pt-2 border-t border-amber-200">
                {suggestions.items?.length === 0 ? (
                  <p className="text-xs text-slate-500 italic py-2">
                    Aucune suggestion. Les messages entrants sans match seront listés ici (une fois la capture activée).
                  </p>
                ) : (
                  <ul className="divide-y divide-amber-100">
                    {suggestions.items.map((s) => (
                      <li key={s.id} className="py-2" data-testid={`suggestion-${s.id}`}>
                        {convertingSid === s.id ? (
                          <div className="space-y-2 bg-white p-2 rounded border border-amber-200">
                            <p className="text-xs text-slate-700"><strong>Convertir :</strong> {s.body}</p>
                            <input
                              value={convertForm.name}
                              onChange={(e) => setConvertForm({ ...convertForm, name: e.target.value })}
                              placeholder="Nom du modèle"
                              className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-xs"
                              data-testid="convert-name-input"
                            />
                            <textarea
                              value={convertForm.response_text}
                              onChange={(e) => setConvertForm({ ...convertForm, response_text: e.target.value })}
                              placeholder="Texte de réponse (obligatoire)"
                              rows={3}
                              className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-xs"
                              data-testid="convert-response-input"
                            />
                            <div className="flex items-center justify-end gap-2">
                              <button onClick={() => setConvertingSid(null)} className="text-xs text-slate-500 hover:underline">Annuler</button>
                              <button
                                onClick={submitConvert}
                                className="inline-flex items-center gap-1 px-2 py-1 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-xs"
                                data-testid="convert-submit-btn"
                              >
                                <Save className="h-3 w-3" /> Créer modèle
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-start gap-3">
                            <div className="flex-1 min-w-0">
                              <p className="text-xs text-slate-800 truncate" title={s.body}>{s.body}</p>
                              <p className="text-[10px] text-slate-500 mt-0.5">
                                <strong>{s.count}×</strong> · {s.contact_name || "—"} · dernière fois : {new Date(s.last_seen_at).toLocaleString("fr-FR")}
                              </p>
                            </div>
                            <button
                              onClick={() => startConvertSuggestion(s)}
                              className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white"
                              data-testid={`convert-suggestion-${s.id}`}
                            >
                              <Plus className="h-3 w-3" /> Créer modèle
                            </button>
                            <button
                              onClick={() => dismissSuggestion(s.id)}
                              className="p-1 text-slate-400 hover:text-red-500"
                              title="Ignorer"
                              data-testid={`dismiss-suggestion-${s.id}`}
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {/* ---- Editor modal ---- */}
      {editing && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()} data-testid="template-editor-modal">
            <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
              <h3 className="text-base font-semibold">{editing.id ? "Modifier" : "Créer"} un modèle</h3>
              <button onClick={() => setEditing(null)} className="p-1 hover:bg-slate-100 rounded"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-5 space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Nom (affiché dans les stats)</label>
                <input type="text" value={editing.name || ""} onChange={(e) => setEditing({...editing, name: e.target.value})}
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                  data-testid="editor-name" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Texte déclencheur principal *</label>
                <input type="text" value={editing.trigger_text || ""} onChange={(e) => setEditing({...editing, trigger_text: e.target.value})}
                  placeholder="Ex: Puis-je en savoir plus sur votre entreprise ?"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                  data-testid="editor-trigger" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">
                  Variations (une par ligne) — Liluvine matchera aussi ces textes
                </label>
                <textarea
                  rows={3}
                  value={(editing.trigger_variations || []).join("\n")}
                  onChange={(e) => setEditing({...editing, trigger_variations: e.target.value.split("\n").filter(Boolean)})}
                  placeholder={"plus d'infos\nen savoir plus\nvotre entreprise"}
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm font-mono"
                  data-testid="editor-variations"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-600 mb-1">Réponse Liluvine (texte) *</label>
                <textarea
                  rows={5}
                  value={editing.response_text || ""}
                  onChange={(e) => setEditing({...editing, response_text: e.target.value})}
                  placeholder="Bonjour ! Merci pour votre intérêt..."
                  className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                  data-testid="editor-response"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    URL média (image/vidéo, optionnel — envoyée en <strong>natif WhatsApp</strong>)
                  </label>
                  <input type="url" value={editing.response_media_url || ""} onChange={(e) => setEditing({...editing, response_media_url: e.target.value})}
                    placeholder="https://…/promo.jpg ou .mp4"
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                    data-testid="editor-media-url" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
                  <select value={editing.response_media_kind || ""} onChange={(e) => setEditing({...editing, response_media_kind: e.target.value})}
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                    data-testid="editor-media-kind">
                    <option value="">—</option>
                    <option value="image">Image</option>
                    <option value="video">Vidéo</option>
                    <option value="audio">Audio</option>
                    <option value="document">Document (PDF, etc.)</option>
                  </select>
                </div>
              </div>
              {editing.response_media_url && (
                <p className="text-[11px] text-emerald-700 bg-emerald-50 rounded p-2">
                  ✅ Le média sera envoyé en natif WhatsApp (l&apos;utilisateur verra l&apos;image/vidéo directement, sans lien à cliquer).
                </p>
              )}
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!editing.active} onChange={(e) => setEditing({...editing, active: e.target.checked})} />
                Actif (répond automatiquement aux messages correspondants)
              </label>
            </div>
            <div className="px-5 py-3 border-t border-slate-200 flex items-center justify-end gap-2 bg-slate-50">
              <button onClick={() => setEditing(null)} className="px-3 py-1.5 rounded-lg text-sm hover:bg-slate-100">Annuler</button>
              <button
                onClick={saveTemplate}
                disabled={saving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-sm disabled:opacity-50"
                data-testid="save-template-btn"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {editing.id ? "Enregistrer" : "Créer"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
