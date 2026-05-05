import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  FileText, Plus, Trash2, RefreshCw, AlertTriangle, CheckCircle2, Clock, XCircle, Eye, MessageCircle, Wand2, Settings,
} from "lucide-react";
import { Link } from "react-router-dom";

/*
  Admin → Templates WhatsApp
  Visualise les templates Meta + soumet de nouveaux templates pour approbation
  directement depuis SAWALI (sans passer par Meta Business Suite).
*/
const STATUS_PILL = {
  APPROVED: ["bg-emerald-100 text-emerald-700", CheckCircle2],
  PENDING: ["bg-amber-100 text-amber-700", Clock],
  IN_APPEAL: ["bg-amber-100 text-amber-700", Clock],
  REJECTED: ["bg-rose-100 text-rose-700", XCircle],
  PAUSED: ["bg-slate-200 text-slate-700", Clock],
  DISABLED: ["bg-slate-200 text-slate-500", XCircle],
  DELETED: ["bg-slate-200 text-slate-500", XCircle],
};

export default function AdminWaTemplates() {
  const [resp, setResp] = useState({ configured: false, items: [] });
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [filter, setFilter] = useState("ALL");
  const [previewing, setPreviewing] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/whatsapp/templates");
      setResp(r.data || { configured: false, items: [] });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const remove = async (name) => {
    if (!window.confirm(`Supprimer DÉFINITIVEMENT le template "${name}" sur Meta ? Cette action supprime toutes les langues.`)) return;
    try {
      await apiClient.delete(`/admin/whatsapp/templates/${encodeURIComponent(name)}`);
      toast.success("Template supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur Meta");
    }
  };

  const items = (resp.items || []).filter(
    (t) => filter === "ALL" || (t.status || "").toUpperCase() === filter
  );

  const stats = useMemo(() => {
    const out = { APPROVED: 0, PENDING: 0, REJECTED: 0, OTHER: 0 };
    (resp.items || []).forEach((t) => {
      const k = (t.status || "").toUpperCase();
      if (k === "APPROVED" || k === "PENDING" || k === "REJECTED") out[k]++;
      else out.OTHER++;
    });
    return out;
  }, [resp.items]);

  return (
    <div className="max-w-7xl space-y-6" data-testid="admin-wa-templates-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Meta Business</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <FileText className="h-5 w-5 text-sawali-blue" /> Templates WhatsApp
          </h1>
          <p className="text-sm text-slate-500">
            Créez et soumettez vos templates Meta directement depuis SAWALI. Approbation par Meta sous quelques minutes à 24h.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/admin/messaging"
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="templates-to-messaging"
          >
            <MessageCircle className="h-3.5 w-3.5" /> Messagerie
          </Link>
          <button
            onClick={load}
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="templates-refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Rafraîchir
          </button>
          <button
            onClick={() => setShowForm(true)}
            disabled={!resp.configured}
            title={!resp.configured ? "Configurez WhatsApp d'abord" : ""}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-sm hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="templates-create-btn"
          >
            <Plus className="h-4 w-4" /> Nouveau template
          </button>
        </div>
      </div>

      {!resp.configured && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-900">
            <strong>WhatsApp Business API non configurée.</strong> Renseignez WABA ID, Phone Number ID, App ID et Access Token
            dans <Link to="/admin/settings" className="underline font-semibold inline-flex items-center gap-1"><Settings className="h-3 w-3" /> Paramètres</Link>.
          </div>
        </div>
      )}

      {/* Meta API error surfaced (invalid token, expired, insufficient perms…) */}
      {resp.configured && resp.error && (
        <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 flex items-start gap-3" data-testid="templates-meta-error">
          <AlertTriangle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />
          <div className="text-sm text-rose-900">
            <strong>Erreur côté Meta : {resp.error}</strong>
            <p className="mt-1 text-rose-800">
              Vos identifiants WhatsApp semblent invalides ou expirés. Ouvrez
              <Link to="/admin/settings" className="underline font-semibold mx-1"><Settings className="h-3 w-3 inline" /> Paramètres</Link>
              puis cliquez sur <em>"Tester la connexion Meta"</em> pour un diagnostic complet.
            </p>
          </div>
        </div>
      )}

      {/* Stats + filters */}
      {resp.configured && (
        <div className="grid grid-cols-4 gap-3">
          {[
            ["ALL", "Tous", (resp.items || []).length, "bg-slate-50"],
            ["APPROVED", "Approuvés", stats.APPROVED, "bg-emerald-50"],
            ["PENDING", "En attente", stats.PENDING, "bg-amber-50"],
            ["REJECTED", "Rejetés", stats.REJECTED, "bg-rose-50"],
          ].map(([k, label, n, bg]) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={`rounded-xl border p-3 text-left transition ${
                filter === k ? "border-sawali-blue ring-2 ring-sawali-blue/20" : "border-slate-200"
              } ${bg}`}
              data-testid={`templates-filter-${k}`}
            >
              <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
              <div className="text-2xl font-display font-bold text-slate-900">{n}</div>
            </button>
          ))}
        </div>
      )}

      {/* Templates list */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        {loading ? (
          <div className="text-center text-slate-500 py-10">Chargement…</div>
        ) : !resp.configured ? (
          <div className="text-center text-slate-400 py-10 italic text-sm">
            Configurez WhatsApp pour voir vos templates Meta.
          </div>
        ) : items.length === 0 ? (
          <div className="text-center text-slate-500 py-10 text-sm space-y-2" data-testid="templates-empty">
            <p className="italic">
              {filter !== "ALL"
                ? `Aucun template avec le filtre « ${filter} ».`
                : "Aucun template trouvé sur votre compte Meta."}
            </p>
            {filter === "ALL" && !resp.error && (
              <p className="text-xs text-slate-400 max-w-xl mx-auto">
                Votre compte WhatsApp Business n'a pas encore de template. Cliquez sur <strong>"Nouveau template"</strong> ci-dessus pour soumettre votre premier modèle à Meta (approbation en quelques minutes à 24h).
              </p>
            )}
          </div>
        ) : (
          <table className="min-w-full text-sm" data-testid="templates-table">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left py-2 px-3">Nom</th>
                <th className="text-left py-2 px-3">Langue</th>
                <th className="text-left py-2 px-3">Catégorie</th>
                <th className="text-left py-2 px-3">Statut</th>
                <th className="text-left py-2 px-3">Note descriptive</th>
                <th className="text-center py-2 px-3">Disponible<br/>utilisateurs</th>
                <th className="text-right py-2 px-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => {
                const status = (t.status || "").toUpperCase();
                const [pill, Icon] = STATUS_PILL[status] || ["bg-slate-100 text-slate-600", Clock];
                return (
                  <tr key={`${t.name}_${t.language}`} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`template-row-${t.name}`}>
                    <td className="py-2 px-3 font-mono text-[11px]">{t.name}</td>
                    <td className="py-2 px-3 text-slate-600 text-xs">{t.language}</td>
                    <td className="py-2 px-3 text-slate-600 text-xs">{t.category}</td>
                    <td className="py-2 px-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] ${pill}`}>
                        <Icon className="h-3 w-3" /> {status || "—"}
                      </span>
                      {t.rejected_reason && (
                        <div className="text-[10px] text-rose-600 mt-0.5">{t.rejected_reason}</div>
                      )}
                    </td>
                    <td className="py-2 px-3 max-w-xs">
                      <NoteCell template={t} onSaved={load} />
                    </td>
                    <td className="py-2 px-3 text-center">
                      <AvailabilityToggle template={t} onSaved={load} />
                    </td>
                    <td className="py-2 px-3 text-right">
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => setPreviewing(t)}
                          className="text-[11px] rounded bg-slate-700 text-white px-2 py-1 hover:bg-slate-800"
                          title="Aperçu complet"
                          data-testid={`template-preview-${t.name}`}
                        >
                          <Eye className="h-3 w-3" />
                        </button>
                        <button
                          onClick={() => remove(t.name)}
                          className="text-[11px] rounded bg-rose-500 text-white px-2 py-1 hover:bg-rose-600"
                          title="Supprimer sur Meta"
                          data-testid={`template-delete-${t.name}`}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {showForm && (
        <CreateTemplateModal
          onClose={() => setShowForm(false)}
          onCreated={async () => { setShowForm(false); await load(); }}
          creating={creating}
          setCreating={setCreating}
        />
      )}

      {previewing && (
        <PreviewModal template={previewing} onClose={() => setPreviewing(null)} />
      )}
    </div>
  );
}

function CreateTemplateModal({ onClose, onCreated, creating, setCreating }) {
  const [form, setForm] = useState({
    name: "",
    language: "fr",
    category: "UTILITY",
    body_text: "",
    body_examples: [],
    header_text: "",
    footer_text: "",
  });

  const nVars = useMemo(() => {
    const m = [...(form.body_text || "").matchAll(/\{\{\s*(\d+)\s*\}\}/g)].map((x) => parseInt(x[1], 10));
    return m.length ? Math.max(...m) : 0;
  }, [form.body_text]);

  useEffect(() => {
    setForm((f) => {
      const ex = [...(f.body_examples || [])];
      while (ex.length < nVars) ex.push("");
      ex.length = nVars;
      return { ...f, body_examples: ex };
    });
  }, [nVars]);

  const submit = async () => {
    if (!form.name.trim()) return toast.error("Nom requis");
    if (!form.body_text.trim()) return toast.error("Corps requis");
    if (nVars > 0 && form.body_examples.some((e) => !e || !e.trim())) {
      return toast.error(`Renseignez les ${nVars} exemple(s) de variables`);
    }
    setCreating(true);
    try {
      const r = await apiClient.post("/admin/whatsapp/templates", form);
      toast.success(`Template "${r.data.name}" soumis (${r.data.status})`);
      await onCreated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur Meta");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start md:items-center justify-center p-4 overflow-y-auto" data-testid="template-create-modal">
      <div className="bg-white rounded-xl w-full max-w-2xl my-6 shadow-2xl">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-display font-bold flex items-center gap-2">
            <Wand2 className="h-5 w-5 text-sawali-blue" /> Nouveau template Meta
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="template-modal-close">✕</button>
        </div>
        <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Nom *</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })}
                placeholder="ex: bienvenue_client"
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
                data-testid="template-name-input"
              />
              <p className="text-[11px] text-slate-500 mt-1">Minuscules, chiffres et _ uniquement.</p>
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Langue</label>
              <select
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="template-language-select"
              >
                {["fr", "en", "en_US", "ar", "es", "pt_BR", "es_ES"].map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Catégorie</label>
            <div className="flex gap-2">
              {["UTILITY", "MARKETING", "AUTHENTICATION"].map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setForm({ ...form, category: c })}
                  className={`flex-1 px-3 py-2 rounded-lg text-xs border transition ${
                    form.category === c
                      ? "bg-sawali-blue text-white border-sawali-blue"
                      : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
                  }`}
                  data-testid={`template-cat-${c}`}
                >
                  {c}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              <strong>UTILITY</strong> : confirmations, rappels (le plus permissif). <strong>MARKETING</strong> : promotions.
              <strong> AUTHENTICATION</strong> : codes OTP.
            </p>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Header (optionnel, max 60 car.)</label>
            <input
              value={form.header_text}
              onChange={(e) => setForm({ ...form, header_text: e.target.value })}
              placeholder="ex: SAWALI SMART SYSTEMS"
              maxLength={60}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="template-header-input"
            />
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
              Corps * (max 1024 car.) — utilisez {"{{1}}"}, {"{{2}}"}… pour les variables
            </label>
            <textarea
              value={form.body_text}
              onChange={(e) => setForm({ ...form, body_text: e.target.value })}
              rows={5}
              maxLength={1024}
              placeholder="Bonjour {{1}}, bienvenue chez SAWALI. Votre code client est {{2}}."
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="template-body-input"
            />
            <div className="flex justify-between text-[11px] text-slate-500 mt-1">
              <span>{nVars} variable(s) détectée(s)</span>
              <span>{(form.body_text || "").length}/1024</span>
            </div>
          </div>

          {nVars > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
              <p className="text-[11px] uppercase tracking-wider text-amber-800 font-semibold">
                Exemples requis ({nVars}) — Meta exige des valeurs réelles pour la validation
              </p>
              {Array.from({ length: nVars }).map((_, i) => (
                <div key={i} className="grid grid-cols-[60px_1fr] gap-2 items-center">
                  <span className="text-xs font-mono text-amber-700">{`{{${i + 1}}}`}</span>
                  <input
                    value={form.body_examples[i] || ""}
                    onChange={(e) => {
                      const ex = [...form.body_examples];
                      ex[i] = e.target.value;
                      setForm({ ...form, body_examples: ex });
                    }}
                    placeholder={`ex: ${i === 0 ? "Marie Dupont" : "ABC123"}`}
                    className="rounded border border-amber-300 bg-white px-2 py-1.5 text-xs"
                    data-testid={`template-example-${i + 1}`}
                  />
                </div>
              ))}
            </div>
          )}

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Footer (optionnel, max 60 car.)</label>
            <input
              value={form.footer_text}
              onChange={(e) => setForm({ ...form, footer_text: e.target.value })}
              placeholder="ex: SAWALI Smart Systems · 24h/24"
              maxLength={60}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="template-footer-input"
            />
          </div>

          {/* Live preview */}
          {form.body_text && (
            <div className="rounded-lg border-2 border-emerald-200 bg-emerald-50/30 p-3" data-testid="template-live-preview">
              <p className="text-[10px] uppercase tracking-wider text-emerald-700 mb-2 font-semibold">Aperçu</p>
              <div className="rounded-lg bg-white border border-emerald-200 p-3 text-sm whitespace-pre-line">
                {form.header_text && (
                  <div className="font-bold text-slate-900 mb-1">{form.header_text}</div>
                )}
                <div className="text-slate-700">{form.body_text}</div>
                {form.footer_text && (
                  <div className="text-[11px] text-slate-400 mt-2 pt-2 border-t border-slate-100">{form.footer_text}</div>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className="text-sm px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50" data-testid="template-cancel">
            Annuler
          </button>
          <button
            onClick={submit}
            disabled={creating}
            className="inline-flex items-center gap-2 text-sm rounded-lg bg-sawali-blue text-white px-4 py-1.5 hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="template-submit"
          >
            {creating ? "Soumission…" : (
              <>
                <CheckCircle2 className="h-4 w-4" /> Soumettre à Meta
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function PreviewModal({ template, onClose }) {
  const header = (template.components || []).find((c) => (c.type || "").toUpperCase() === "HEADER");
  const body = (template.components || []).find((c) => (c.type || "").toUpperCase() === "BODY");
  const footer = (template.components || []).find((c) => (c.type || "").toUpperCase() === "FOOTER");
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" data-testid="template-preview-modal">
      <div className="bg-white rounded-xl w-full max-w-md shadow-2xl">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="font-display font-bold flex items-center gap-2">
            <Eye className="h-4 w-4 text-sawali-blue" /> {template.name}
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900">✕</button>
        </div>
        <div className="p-5 space-y-2">
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-4 text-sm whitespace-pre-line">
            {header?.text && <div className="font-bold text-slate-900 mb-2">{header.text}</div>}
            <div className="text-slate-700">{body?.text || "—"}</div>
            {footer?.text && (
              <div className="text-[11px] text-slate-500 mt-3 pt-2 border-t border-slate-200">{footer.text}</div>
            )}
          </div>
          <div className="text-[11px] text-slate-500 grid grid-cols-2 gap-1 mt-3">
            <div>Langue : <span className="font-mono">{template.language}</span></div>
            <div>Catégorie : <span className="font-mono">{template.category}</span></div>
            <div>Statut : <span className="font-mono">{template.status}</span></div>
            <div>ID : <span className="font-mono text-[10px]">{template.id}</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Editable note cell (admin only) ---
function NoteCell({ template, onSaved }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(template.note_description || "");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put(`/admin/whatsapp/template-notes/${encodeURIComponent(template.name)}`, { description: val });
      toast.success("Note enregistrée");
      setEditing(false);
      if (onSaved) onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };
  if (editing) {
    return (
      <div className="flex flex-col gap-1" data-testid={`note-edit-${template.name}`}>
        <textarea
          value={val}
          onChange={(e) => setVal(e.target.value)}
          rows={2}
          placeholder="Décrivez à quoi sert ce template…"
          className="w-full text-xs rounded border border-slate-300 px-2 py-1"
          autoFocus
        />
        <div className="flex gap-1 text-[11px]">
          <button disabled={saving} onClick={save} className="px-2 py-0.5 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50" data-testid={`note-save-${template.name}`}>{saving ? "…" : "OK"}</button>
          <button onClick={() => { setEditing(false); setVal(template.note_description || ""); }} className="px-2 py-0.5 rounded bg-slate-200 text-slate-700">Annuler</button>
        </div>
      </div>
    );
  }
  return (
    <button
      onClick={() => setEditing(true)}
      className="text-left w-full text-xs text-slate-700 hover:text-sawali-blue line-clamp-2"
      title="Cliquer pour éditer"
      data-testid={`note-display-${template.name}`}
    >
      {template.note_description ? template.note_description : <span className="italic text-slate-400">Cliquez pour ajouter une note…</span>}
    </button>
  );
}

// --- Availability toggle (admin only) ---
function AvailabilityToggle({ template, onSaved }) {
  const [val, setVal] = useState(template.is_available_for_users !== false);
  const [pending, setPending] = useState(false);
  const flip = async () => {
    const next = !val;
    setVal(next);
    setPending(true);
    try {
      await apiClient.put(`/admin/whatsapp/template-notes/${encodeURIComponent(template.name)}`, { is_available_for_users: next });
      if (onSaved) onSaved();
    } catch (err) {
      setVal(!next);
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setPending(false);
    }
  };
  return (
    <button
      onClick={flip}
      disabled={pending}
      className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors disabled:opacity-50 ${val ? "bg-emerald-600" : "bg-slate-300"}`}
      title={val ? "Visible aux utilisateurs portail" : "Masqué aux utilisateurs"}
      data-testid={`availability-toggle-${template.name}`}
    >
      <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${val ? "translate-x-5" : "translate-x-1"}`} />
    </button>
  );
}
