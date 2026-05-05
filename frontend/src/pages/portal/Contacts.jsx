import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Users, Plus, Trash2, MessageCircle, Tag, Share2, Lock,
  Send, X, History, RefreshCw, Pencil, Check, Clock,
  CheckCheck, AlertCircle, ArrowDownLeft, ArrowUpRight,
  Upload, Image as ImageIcon, FileText as FileTextIcon, Video, Info,
} from "lucide-react";
import { parseTemplate, buildComponentsPayload, validateTemplateValues, renderPreview } from "@/lib/waTemplate";

/*
  Portal → Directory + WhatsApp.
  - CRUD contacts scoped to current client.
  - Inline edit of WhatsApp number (no full form needed).
  - Send WA template from the row.
  - Click a row to view the full conversation timeline.
*/
export default function Contacts() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [modal, setModal] = useState(null); // {type:'edit'|'wa'|'history', contact?}

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/contacts");
      setItems(Array.isArray(r.data) ? r.data : []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer ce contact ?")) return;
    try {
      await apiClient.delete(`/me/contacts/${id}`);
      toast.success("Contact supprimé");
      await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const filtered = items.filter((c) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return [c.name, c.phone, c.whatsapp, c.email, c.company, (c.tags || []).join(" ")]
      .some((v) => (v || "").toLowerCase().includes(q));
  });

  return (
    <div className="max-w-6xl space-y-5" data-testid="contacts-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Communication</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Users className="h-5 w-5 text-sawali-blue" /> Répertoire & WhatsApp
          </h1>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
            data-testid="contacts-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Actualiser
          </button>
          <button
            onClick={() => setModal({ type: "edit" })}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light"
            data-testid="contact-add-btn"
          >
            <Plus className="h-4 w-4" /> Nouveau contact
          </button>
        </div>
      </div>

      <div className="flex gap-3 items-center flex-wrap">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Rechercher nom, tél, email, société, tag…"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm min-w-[220px]"
          data-testid="contact-search"
        />
        <span className="text-xs text-slate-500">{filtered.length} contact(s)</span>
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-slate-400 py-10 italic text-sm">
          Aucun contact. Créez-en un avec "Nouveau contact".
        </div>
      ) : (
        <div className="rounded-xl bg-white border border-slate-200 overflow-x-auto" data-testid="contacts-table">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>
                <th className="text-left px-3 py-2">Nom</th>
                <th className="text-left px-3 py-2">Société</th>
                <th className="text-left px-3 py-2">Téléphone</th>
                <th className="text-left px-3 py-2">WhatsApp</th>
                <th className="text-left px-3 py-2">Email</th>
                <th className="text-left px-3 py-2">Partage</th>
                <th className="text-right px-3 py-2 min-w-[260px]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <ContactRow
                  key={c.id}
                  c={c}
                  onReload={load}
                  onEdit={() => setModal({ type: "edit", contact: c })}
                  onWa={() => setModal({ type: "wa", contact: c })}
                  onHistory={() => setModal({ type: "history", contact: c })}
                  onDelete={() => del(c.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal?.type === "edit" && (
        <ContactEditModal
          contact={modal.contact}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
        />
      )}
      {modal?.type === "wa" && (
        <WhatsAppModal contact={modal.contact} onClose={() => setModal(null)} onSent={load} />
      )}
      {modal?.type === "history" && (
        <ConversationModal contact={modal.contact} onClose={() => setModal(null)} />
      )}
    </div>
  );
}

// --- Contact row with inline WhatsApp edit ---
const ContactRow = ({ c, onReload, onEdit, onWa, onHistory, onDelete }) => {
  const [editingWa, setEditingWa] = useState(false);
  const [waValue, setWaValue] = useState(c.whatsapp || "");
  const [saving, setSaving] = useState(false);

  const saveWa = async () => {
    const trimmed = (waValue || "").trim();
    if (trimmed === (c.whatsapp || "")) { setEditingWa(false); return; }
    setSaving(true);
    try {
      await apiClient.put(`/me/contacts/${c.id}`, { whatsapp: trimmed });
      toast.success("Numéro WhatsApp mis à jour");
      setEditingWa(false);
      await onReload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className="border-t border-slate-100 hover:bg-slate-50" data-testid={`contact-row-${c.id}`}>
      <td className="px-3 py-2">
        <button
          onClick={onHistory}
          className="font-semibold text-slate-900 hover:text-sawali-blue hover:underline text-left"
          title="Voir la conversation WhatsApp"
          data-testid={`contact-name-${c.id}`}
        >
          {c.name}
        </button>
        {c.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {c.tags.map((t) => (
              <span key={t} className="text-[10px] bg-slate-100 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
                <Tag className="h-2.5 w-2.5" /> {t}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="px-3 py-2 text-slate-600">{c.company || "—"}</td>
      <td className="px-3 py-2 text-slate-600 font-mono text-[12px]">{c.phone || "—"}</td>
      <td className="px-3 py-2 text-slate-600 font-mono text-[12px]">
        {editingWa ? (
          <div className="flex items-center gap-1">
            <input
              autoFocus
              value={waValue}
              onChange={(e) => setWaValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") saveWa(); if (e.key === "Escape") { setEditingWa(false); setWaValue(c.whatsapp || ""); } }}
              placeholder="+225xxxxxxxx"
              className="w-36 rounded border border-sawali-blue px-2 py-1 text-[12px]"
              data-testid={`contact-wa-inline-${c.id}`}
            />
            <button
              onClick={saveWa}
              disabled={saving}
              className="text-emerald-700 hover:text-emerald-900 p-1"
              title="Enregistrer"
              data-testid={`contact-wa-save-${c.id}`}
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              onClick={() => { setEditingWa(false); setWaValue(c.whatsapp || ""); }}
              className="text-slate-500 hover:text-slate-800 p-1"
              title="Annuler"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setEditingWa(true)}
            className="group inline-flex items-center gap-1 text-slate-600 hover:text-sawali-blue"
            title="Modifier le numéro WhatsApp"
            data-testid={`contact-wa-edit-${c.id}`}
          >
            <span>{c.whatsapp || "—"}</span>
            <Pencil className="h-3 w-3 opacity-40 group-hover:opacity-100 transition" />
          </button>
        )}
      </td>
      <td className="px-3 py-2 text-slate-600">{c.email || "—"}</td>
      <td className="px-3 py-2">
        {c.shared ? (
          <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
            <Share2 className="h-2.5 w-2.5" /> Partagé
          </span>
        ) : (
          <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
            <Lock className="h-2.5 w-2.5" /> Privé
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        <div className="inline-flex gap-1 items-center">
          <button
            onClick={onWa}
            disabled={!c.whatsapp}
            title={c.whatsapp ? "Envoyer un WhatsApp" : "Ajoutez d'abord un numéro WhatsApp"}
            className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2 py-1 hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed"
            data-testid={`contact-wa-${c.id}`}
          >
            <MessageCircle className="h-3 w-3" /> WhatsApp
          </button>
          <button
            onClick={onHistory}
            title="Voir les messages échangés"
            className="inline-flex items-center gap-1 text-[11px] rounded bg-slate-700 text-white px-2 py-1 hover:bg-slate-800"
            data-testid={`contact-history-${c.id}`}
          >
            <History className="h-3 w-3" /> Messages
          </button>
          <button
            onClick={onEdit}
            className="text-[11px] text-slate-600 hover:underline px-1"
            data-testid={`contact-edit-${c.id}`}
          >
            Éditer
          </button>
          <button
            onClick={onDelete}
            className="text-rose-500 hover:text-rose-700 p-1"
            data-testid={`contact-delete-${c.id}`}
            title="Supprimer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </td>
    </tr>
  );
};

// --- Full edit modal ---
const ContactEditModal = ({ contact, onClose, onSaved }) => {
  const [form, setForm] = useState(() => contact || {
    name: "", phone: "", whatsapp: "", email: "", company: "", notes: "", tags: [], shared: false,
  });
  const [saving, setSaving] = useState(false);
  const [tagInput, setTagInput] = useState("");

  const save = async () => {
    if (!form.name.trim()) { toast.error("Le nom est requis"); return; }
    setSaving(true);
    try {
      if (contact?.id) await apiClient.put(`/me/contacts/${contact.id}`, form);
      else await apiClient.post("/me/contacts", form);
      toast.success("Contact enregistré");
      onSaved();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSaving(false); }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (!t) return;
    setForm({ ...form, tags: [...(form.tags || []), t] });
    setTagInput("");
  };
  const rmTag = (t) => setForm({ ...form, tags: (form.tags || []).filter((x) => x !== t) });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="contact-edit-modal"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">
            {contact?.id ? "Modifier le contact" : "Nouveau contact"}
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="contact-edit-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="Nom *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testid="contact-field-name" />
          <Input label="Société" value={form.company} onChange={(v) => setForm({ ...form, company: v })} testid="contact-field-company" />
          <Input label="Téléphone (E.164)" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} placeholder="+225xxxxxxxx" testid="contact-field-phone" />
          <Input label="WhatsApp (E.164)" value={form.whatsapp} onChange={(v) => setForm({ ...form, whatsapp: v })} placeholder="+225xxxxxxxx" testid="contact-field-whatsapp" />
          <Input label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} testid="contact-field-email" />
          <label className="flex items-center gap-2 text-sm mt-6">
            <input
              type="checkbox"
              checked={!!form.shared}
              onChange={(e) => setForm({ ...form, shared: e.target.checked })}
              data-testid="contact-field-shared"
            />
            Partager avec les autres utilisateurs de mon client
          </label>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Notes</label>
          <textarea
            value={form.notes || ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            rows={2}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="contact-field-notes"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Catégories / Tags</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {(form.tags || []).map((t) => (
              <span key={t} className="text-xs bg-slate-100 px-2 py-0.5 rounded inline-flex items-center gap-1">
                {t}
                <button onClick={() => rmTag(t)}><X className="h-3 w-3" /></button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              placeholder="Fournisseur, Client, Technique…"
              className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
              data-testid="contact-field-tag-input"
            />
            <button onClick={addTag} className="text-xs rounded bg-slate-900 text-white px-3">Ajouter</button>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button
            onClick={save}
            disabled={saving}
            className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
            data-testid="contact-edit-save"
          >
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// --- WhatsApp send modal (supports HEADER text/media + BODY variables + URL button params) ---
const WhatsAppModal = ({ contact, onClose, onSent }) => {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [templateName, setTemplateName] = useState("");
  const [language, setLanguage] = useState("fr");
  const [tokens, setTokens] = useState([]);
  const [headerText, setHeaderText] = useState("");
  const [headerMedia, setHeaderMedia] = useState(null); // { link, kind, filename }
  const [headerUploading, setHeaderUploading] = useState(false);
  const [bodyVars, setBodyVars] = useState([]);
  const [buttonVars, setButtonVars] = useState([]); // [[...], [...]]
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const [configured, setConfigured] = useState(true);

  useEffect(() => {
    Promise.all([
      apiClient.get("/me/whatsapp/templates"),
      apiClient.get("/me/messaging/variable-tokens").catch(() => ({ data: { tokens: [] } })),
    ]).then(([tplRes, tokRes]) => {
      const items = tplRes.data?.items || [];
      setTemplates(items);
      setTokens(tokRes.data?.tokens || []);
      setConfigured(!!tplRes.data?.configured);
      if (items[0]) {
        setTemplateName(items[0].name);
        setLanguage(items[0].language || "fr");
      }
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.name === templateName),
    [templates, templateName],
  );
  const parsed = useMemo(() => parseTemplate(selectedTemplate), [selectedTemplate]);

  // Reset inputs whenever the template selection changes
  useEffect(() => {
    setHeaderText("");
    setHeaderMedia(null);
    setBodyVars(Array(parsed.body.varCount).fill(""));
    setButtonVars((parsed.buttons || []).map((b) => Array(b.urlVarCount || 0).fill("")));
    setResult(null);
  }, [templateName, parsed.body.varCount, parsed.buttons]);

  const uploadHeader = async (file) => {
    if (!file) return;
    setHeaderUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiClient.post("/me/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      const link = r.data?.public_url || r.data?.url || r.data?.file_url;
      if (!link) throw new Error("URL publique manquante");
      const ct = (r.data?.content_type || "").toLowerCase();
      const kind = ct.startsWith("image") ? "image" : ct.startsWith("video") ? "video" : "document";
      setHeaderMedia({ link, kind, filename: r.data?.filename || file.name });
      toast.success("Fichier prêt pour l'en-tête");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'upload");
    } finally {
      setHeaderUploading(false);
    }
  };

  const send = async () => {
    if (!templateName) { toast.error("Sélectionnez un template"); return; }
    const values = { headerText, headerMedia, bodyVars, buttonVars };
    const v = validateTemplateValues(parsed, values);
    if (!v.ok) { toast.error(v.message); return; }
    setSending(true); setResult(null);
    try {
      const components = buildComponentsPayload(parsed, values);
      const r = await apiClient.post("/me/whatsapp/send", {
        to: contact.whatsapp,
        template_name: templateName,
        language_code: language,
        components: components.length > 0 ? components : null,
        contact_id: contact.id,
      });
      setResult(r.data);
      if (r.data?.ok) {
        toast.success("Message WhatsApp envoyé");
        if (onSent) onSent();
      } else {
        toast.error(r.data?.error || "Échec d'envoi");
      }
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSending(false); }
  };

  const previewBody = useMemo(
    () => renderPreview(parsed, { bodyVars }, tokens, contact),
    [parsed, bodyVars, tokens, contact],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="whatsapp-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[92vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <MessageCircle className="h-5 w-5 text-emerald-600" /> Envoyer un WhatsApp
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-sm text-slate-600">
            À : <strong>{contact.name}</strong>
            <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded ml-1">{contact.whatsapp}</code>
          </p>
          {loading ? (
            <p className="text-sm text-slate-500">Chargement des templates…</p>
          ) : !configured ? (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
              WhatsApp Business API non configurée. Contactez l'administrateur.
            </div>
          ) : templates.length === 0 ? (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
              Aucun template disponible. L'administrateur doit créer/activer des templates.
            </div>
          ) : (
            <>
              <div className="grid sm:grid-cols-[1fr_120px] gap-3">
                <div>
                  <label className="text-xs font-semibold block mb-1">Template</label>
                  <select
                    value={templateName}
                    onChange={(e) => {
                      setTemplateName(e.target.value);
                      const t = templates.find((x) => x.name === e.target.value);
                      if (t?.language) setLanguage(t.language);
                    }}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="wa-template-select"
                  >
                    {templates.map((t) => (
                      <option key={`${t.name}_${t.language}`} value={t.name}>
                        {t.name} ({t.language}){t.note_description ? ` — ${t.note_description.slice(0, 80)}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1">Langue</label>
                  <input
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    data-testid="wa-language-input"
                  />
                </div>
              </div>

              {/* Admin-maintained description */}
              {selectedTemplate?.note_description && (
                <div className="rounded-lg bg-sky-50 ring-1 ring-sky-200 p-3 text-xs text-sky-900 flex items-start gap-2" data-testid="wa-template-note">
                  <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  <span>{selectedTemplate.note_description}</span>
                </div>
              )}

              {/* HEADER */}
              {parsed.header && (
                <HeaderBlock
                  header={parsed.header}
                  headerText={headerText}
                  setHeaderText={setHeaderText}
                  headerMedia={headerMedia}
                  clearMedia={() => setHeaderMedia(null)}
                  uploadHeader={uploadHeader}
                  uploading={headerUploading}
                  tokens={tokens}
                />
              )}

              {/* BODY */}
              {parsed.body.text && (
                <div className="rounded-lg bg-slate-50 ring-1 ring-slate-200 p-3 text-xs text-slate-700 whitespace-pre-wrap">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Corps du template Meta</p>
                  {parsed.body.text}
                </div>
              )}

              {parsed.body.varCount > 0 && (
                <VarGrid
                  label={`Variables du corps (${parsed.body.varCount})`}
                  values={bodyVars}
                  onChange={setBodyVars}
                  testPrefix="wa-variable"
                  tokens={tokens}
                />
              )}

              {/* BUTTONS with dynamic URLs */}
              {(parsed.buttons || []).some((b) => b.type === "URL" && b.urlVarCount > 0) && (
                <div className="space-y-3">
                  <p className="text-xs font-semibold text-slate-700">Boutons dynamiques</p>
                  {parsed.buttons.map((btn, bi) => (
                    btn.type === "URL" && btn.urlVarCount > 0 ? (
                      <div key={bi} className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid={`wa-button-row-${bi}`}>
                        <p className="text-[11px] text-slate-500">
                          Bouton : <strong className="text-slate-800">{btn.text}</strong>
                          <code className="ml-2 bg-slate-100 px-1 rounded text-[10px]">{btn.url}</code>
                        </p>
                        <VarGrid
                          label=""
                          values={buttonVars[bi] || []}
                          onChange={(arr) => setButtonVars((prev) => {
                            const n = prev.map((x) => [...(x || [])]);
                            n[bi] = arr;
                            return n;
                          })}
                          testPrefix={`wa-button-${bi}-var`}
                          tokens={tokens}
                        />
                      </div>
                    ) : null
                  ))}
                </div>
              )}

              {previewBody && (
                <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900" data-testid="wa-preview">
                  <p className="text-[10px] uppercase tracking-wider text-emerald-700 mb-1">Aperçu du corps pour {contact.name}</p>
                  <p className="whitespace-pre-line">{previewBody}</p>
                </div>
              )}
            </>
          )}
          {result && (
            <div
              className={`rounded-lg ring-1 p-3 text-xs ${
                result.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-300 text-rose-900"
              }`}
              data-testid="wa-result"
            >
              {result.ok ? (
                <><strong>Envoyé !</strong> ID message : <code>{result.message_id}</code></>
              ) : (
                <><strong>Échec :</strong> {result.error || "Erreur inconnue"} (HTTP {result.http_status || "—"})</>
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Fermer</button>
          <button
            onClick={send}
            disabled={sending || templates.length === 0 || !configured}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 disabled:opacity-50"
            data-testid="wa-send-btn"
          >
            <Send className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer"}
          </button>
        </div>
      </div>
    </div>
  );
};

// --- HEADER block: text var OR media upload ---
const HeaderBlock = ({ header, headerText, setHeaderText, headerMedia, clearMedia, uploadHeader, uploading, tokens }) => {
  const fmt = header.format;
  if (fmt === "TEXT" && header.varCount > 0) {
    return (
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid="wa-header-text-block">
        <p className="text-xs font-semibold text-slate-700">En-tête (texte)</p>
        <p className="text-[11px] text-slate-500 whitespace-pre-wrap bg-slate-50 rounded px-2 py-1">{header.text}</p>
        <div className="flex gap-2">
          <input
            value={headerText}
            onChange={(e) => setHeaderText(e.target.value)}
            placeholder="Valeur pour la variable de l'en-tête"
            className="flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
            data-testid="wa-header-text-input"
          />
          <select
            onChange={(e) => {
              const tk = e.target.value;
              if (tk) { setHeaderText((prev) => (prev || "") + tk); e.target.value = ""; }
            }}
            className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
            defaultValue=""
            title="Insérer un token dynamique"
            data-testid="wa-header-text-token-picker"
          >
            <option value="">+ Token…</option>
            {(tokens || []).map((t) => <option key={t.token} value={t.token}>{t.label}</option>)}
          </select>
        </div>
      </div>
    );
  }
  if (["IMAGE", "DOCUMENT", "VIDEO"].includes(fmt)) {
    const Ico = fmt === "IMAGE" ? ImageIcon : fmt === "VIDEO" ? Video : FileTextIcon;
    const accept = fmt === "IMAGE" ? "image/*" : fmt === "VIDEO" ? "video/*" : ".pdf,application/pdf";
    return (
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3 space-y-2" data-testid={`wa-header-${fmt.toLowerCase()}-block`}>
        <p className="text-xs font-semibold text-slate-700 inline-flex items-center gap-1.5">
          <Ico className="h-3.5 w-3.5" /> En-tête ({fmt === "IMAGE" ? "image" : fmt === "VIDEO" ? "vidéo" : "document PDF"})
        </p>
        {headerMedia?.link ? (
          <div className="flex items-center gap-2">
            {fmt === "IMAGE" && <img src={headerMedia.link} alt="" className="h-16 w-16 object-cover rounded" />}
            <div className="flex-1 text-xs">
              <p className="font-mono break-all text-slate-600">{headerMedia.filename}</p>
              <a href={headerMedia.link} target="_blank" rel="noreferrer" className="text-[11px] text-sawali-blue hover:underline">Ouvrir</a>
            </div>
            <button onClick={clearMedia} className="text-xs text-rose-600 hover:underline" data-testid="wa-header-media-clear">Changer</button>
          </div>
        ) : (
          <label className="inline-flex items-center gap-2 text-xs cursor-pointer rounded bg-slate-100 hover:bg-slate-200 px-3 py-2">
            <Upload className="h-3.5 w-3.5" /> {uploading ? "Upload…" : "Sélectionner un fichier"}
            <input type="file" accept={accept} onChange={(e) => uploadHeader(e.target.files?.[0])} className="hidden" data-testid="wa-header-media-input" />
          </label>
        )}
      </div>
    );
  }
  return null;
};

// --- Reusable variable grid (body or button) ---
const VarGrid = ({ label, values, onChange, testPrefix, tokens }) => {
  const update = (i, v) => {
    const n = [...values]; n[i] = v; onChange(n);
  };
  const append = (i, token) => {
    const n = [...values]; n[i] = (n[i] || "") + token; onChange(n);
  };
  return (
    <div className="space-y-2">
      {label && <p className="text-xs font-semibold text-slate-700">{label}</p>}
      {(values || []).map((_, i) => (
        <div key={i} className="grid grid-cols-[64px_1fr_auto] gap-2 items-center" data-testid={`${testPrefix}-row-${i + 1}`}>
          <label className="text-[11px] uppercase tracking-wider text-slate-500 font-mono text-center bg-slate-100 rounded py-2">
            {`{{${i + 1}}}`}
          </label>
          <input
            value={values[i] || ""}
            onChange={(e) => update(i, e.target.value)}
            placeholder="Texte ou tokens"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-mono"
            data-testid={`${testPrefix}-input-${i + 1}`}
          />
          <select
            onChange={(e) => {
              const tk = e.target.value;
              if (tk) { append(i, tk); e.target.value = ""; }
            }}
            className="rounded-lg border border-slate-300 bg-white px-2 py-2 text-[11px]"
            defaultValue=""
            title="Insérer un token dynamique"
            data-testid={`${testPrefix}-token-picker-${i + 1}`}
          >
            <option value="">+ Token…</option>
            {(tokens || []).map((t) => (
              <option key={t.token} value={t.token}>{t.label}</option>
            ))}
          </select>
        </div>
      ))}
    </div>
  );
};

// --- Conversation history modal ---
const ConversationModal = ({ contact, onClose }) => {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ messages: [] });

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/me/contacts/${contact.id}/messages`);
      setData(r.data || { messages: [] });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [contact.id]);

  const messages = data.messages || [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="conversation-modal"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white shadow-2xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <div>
            <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
              <History className="h-5 w-5 text-sawali-blue" /> Conversation
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              <strong className="text-slate-800">{contact.name}</strong>
              {contact.whatsapp && <code className="ml-2 bg-slate-100 px-1.5 py-0.5 rounded">{contact.whatsapp}</code>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-2.5 py-1.5 text-xs"
              data-testid="conversation-refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
            </button>
            <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-5 space-y-3 bg-slate-50/50">
          {loading ? (
            <p className="text-center text-slate-500 text-sm">Chargement…</p>
          ) : messages.length === 0 ? (
            <p className="text-center text-slate-400 italic text-sm py-8">Aucun message échangé pour l'instant.</p>
          ) : (
            messages.map((m) => <MessageBubble key={m.id} m={m} />)
          )}
        </div>
        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-500 flex items-center justify-between">
          <span>{messages.length} message(s)</span>
          <span>Les statuts (envoyé / distribué / lu) sont mis à jour via le webhook Meta.</span>
        </div>
      </div>
    </div>
  );
};

// --- Chat bubble ---
const MessageBubble = ({ m }) => {
  const outbound = m.direction === "outbound";
  const statusIcon = outbound
    ? (m.read_at ? { Icon: CheckCheck, color: "text-sky-500", label: "Lu" }
      : m.delivered_at ? { Icon: CheckCheck, color: "text-slate-400", label: "Distribué" }
      : m.failed_at ? { Icon: AlertCircle, color: "text-rose-500", label: "Échec" }
      : m.sent_at ? { Icon: Check, color: "text-slate-400", label: "Envoyé" }
      : { Icon: Clock, color: "text-slate-400", label: "En attente" })
    : null;

  const primaryTs = outbound
    ? (m.sent_at || m.created_at)
    : (m.received_at || m.created_at);
  const body = m.body || `Template : ${m.template_name || "—"}`;

  return (
    <div className={`flex ${outbound ? "justify-end" : "justify-start"}`} data-testid={`msg-${m.id}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
          outbound ? "bg-sawali-blue text-white" : "bg-white ring-1 ring-slate-200 text-slate-900"
        }`}
      >
        <div className="flex items-center gap-1.5 text-[10px] opacity-75 mb-0.5">
          {outbound
            ? <ArrowUpRight className="h-3 w-3" />
            : <ArrowDownLeft className="h-3 w-3" />}
          <span>{outbound ? "Envoyé" : "Reçu"}</span>
          {outbound && m.template_name && (
            <code className={`px-1 rounded ${outbound ? "bg-white/20" : "bg-slate-100"}`}>
              {m.template_name}
            </code>
          )}
        </div>
        <p className="whitespace-pre-wrap">{body}</p>
        <div className={`flex items-center justify-between gap-3 mt-1.5 text-[10px] ${outbound ? "text-white/80" : "text-slate-400"}`}>
          <span>{fmtDate(primaryTs)}</span>
          {statusIcon && (
            <span className={`inline-flex items-center gap-1 ${outbound ? "" : statusIcon.color}`} title={statusIcon.label}>
              <statusIcon.Icon className="h-3 w-3" /> {statusIcon.label}
            </span>
          )}
        </div>
        {outbound && (m.delivered_at || m.read_at || m.failed_at) && (
          <div className={`text-[10px] mt-1 ${outbound ? "text-white/70" : "text-slate-400"}`}>
            {m.delivered_at && <div>Distribué : {fmtDate(m.delivered_at)}</div>}
            {m.read_at && <div>Lu : {fmtDate(m.read_at)}</div>}
            {m.failed_at && <div>Échec : {fmtDate(m.failed_at)} {m.wa_error_message && `— ${m.wa_error_message}`}</div>}
          </div>
        )}
      </div>
    </div>
  );
};

const fmtDate = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
};

const Input = ({ label, value, onChange, placeholder, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input
      value={value || ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue"
      data-testid={testid}
    />
  </div>
);
