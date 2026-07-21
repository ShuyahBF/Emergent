/*
 * Iter43-fix24az-o (2026-07-21) — Section AdminSettings pour Liluvine Reactions.
 *
 * 3 features exposées :
 *   1. Fuzzy command matching (toggle + slider threshold)
 *   2. Auto-add nouveaux contacts + sélecteur du groupe par défaut
 *   3. CRUD templates de réponse aux publicités Facebook + stats
 */
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Sparkles, Loader2, Plus, Trash2, Edit2, BarChart3, Wand2, UserPlus, Save, X,
} from "lucide-react";

export default function LiluvineReactionsSection() {
  const [cfg, setCfg] = useState(null);
  const [groups, setGroups] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(null); // { id, name, trigger_text, ... }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, t, s] = await Promise.all([
        apiClient.get("/admin/liluvine/reactions-config"),
        apiClient.get("/admin/liluvine/reactions-templates"),
        apiClient.get("/admin/liluvine/reactions-stats"),
      ]);
      setCfg(c.data?.config || {});
      setGroups(c.data?.contact_groups || []);
      setTemplates(t.data?.templates || []);
      setStats(s.data || null);
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

  return (
    <section className="bg-white rounded-2xl border border-slate-200 p-6 space-y-6" data-testid="liluvine-reactions-section">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-lg bg-fuchsia-100 flex items-center justify-center shrink-0">
          <Sparkles className="h-5 w-5 text-fuchsia-700" />
        </div>
        <div className="flex-1">
          <h2 className="text-base font-semibold text-slate-800">Liluvine Reactions & Ad Auto-Replies</h2>
          <p className="text-sm text-slate-500 mt-0.5">
            Configurez la détection floue des commandes (ex: <code>! garde</code>, <code>pharmacies de garde</code>),
            l'ajout automatique de nouveaux contacts et les réponses préconfigurées aux messages de vos publicités Facebook.
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
                <p className="text-[11px] text-slate-400 mt-1">Créez d'abord vos groupes dans la section Contacts.</p>
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

          {/* ---- Templates CRUD ---- */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-slate-700">Modèles de réponses aux publicités</h3>
              <button
                type="button"
                onClick={startNew}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm"
                data-testid="new-template-btn"
              >
                <Plus className="h-4 w-4" /> Nouveau modèle
              </button>
            </div>
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
                  <label className="block text-xs font-medium text-slate-600 mb-1">URL média (image/vidéo courte, optionnel)</label>
                  <input type="url" value={editing.response_media_url || ""} onChange={(e) => setEditing({...editing, response_media_url: e.target.value})}
                    placeholder="https://…/promo.mp4"
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm"
                    data-testid="editor-media-url" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-600 mb-1">Type</label>
                  <select value={editing.response_media_kind || ""} onChange={(e) => setEditing({...editing, response_media_kind: e.target.value})}
                    className="w-full px-2 py-1.5 border border-slate-300 rounded-lg text-sm">
                    <option value="">—</option>
                    <option value="image">Image</option>
                    <option value="video">Vidéo</option>
                    <option value="audio">Audio</option>
                    <option value="doc">Document</option>
                  </select>
                </div>
              </div>
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
