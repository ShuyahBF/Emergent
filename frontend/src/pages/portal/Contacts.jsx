import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Users, Plus, Trash2, MessageCircle, Phone, Mail, Building2, Tag, Share2, Lock, Send, X, History } from "lucide-react";

// Phone directory per client + integrated WhatsApp sender.
// Contacts are owned by their creator; flagged `shared` ones are visible
// to all users of the same client.
export default function Contacts() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [modal, setModal] = useState(null); // {type: 'edit'|'wa', contact?}

  const load = async () => {
    setLoading(true);
    try { const r = await apiClient.get("/me/contacts"); setItems(r.data || []); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer ce contact ?")) return;
    try { await apiClient.delete(`/me/contacts/${id}`); toast.success("Supprimé"); await load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
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
          <h1 className="text-2xl font-display font-bold flex items-center gap-2"><Users className="h-5 w-5 text-sawali-blue" /> Répertoire & WhatsApp</h1>
        </div>
        <button onClick={() => setModal({ type: "edit" })} className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light" data-testid="contact-add-btn"><Plus className="h-4 w-4" /> Nouveau contact</button>
      </div>

      <div className="flex gap-3 items-center flex-wrap">
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Rechercher nom, tél, email, société, tag…" className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm min-w-[220px]" data-testid="contact-search" />
        <span className="text-xs text-slate-500">{filtered.length} contact(s)</span>
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-slate-400 py-10 italic text-sm">Aucun contact. Créez-en un avec "Nouveau contact".</div>
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
                <th className="text-right px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`contact-row-${c.id}`}>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-slate-900">{c.name}</div>
                    {c.tags?.length > 0 && <div className="flex flex-wrap gap-1 mt-1">{c.tags.map((t) => <span key={t} className="text-[10px] bg-slate-100 px-1.5 py-0.5 rounded inline-flex items-center gap-1"><Tag className="h-2.5 w-2.5" /> {t}</span>)}</div>}
                  </td>
                  <td className="px-3 py-2 text-slate-600">{c.company || "—"}</td>
                  <td className="px-3 py-2 text-slate-600 font-mono text-[12px]">{c.phone || "—"}</td>
                  <td className="px-3 py-2 text-slate-600 font-mono text-[12px]">{c.whatsapp || "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{c.email || "—"}</td>
                  <td className="px-3 py-2">
                    {c.shared ? <span className="text-[10px] bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded inline-flex items-center gap-1"><Share2 className="h-2.5 w-2.5" /> Partagé</span>
                              : <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded inline-flex items-center gap-1"><Lock className="h-2.5 w-2.5" /> Privé</span>}
                  </td>
                  <td className="px-3 py-2 text-right space-x-1">
                    {c.whatsapp && <button onClick={() => setModal({ type: "wa", contact: c })} className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2 py-1 hover:bg-emerald-700" title="Envoyer WhatsApp" data-testid={`contact-wa-${c.id}`}><MessageCircle className="h-3 w-3" /> WhatsApp</button>}
                    <button onClick={() => setModal({ type: "edit", contact: c })} className="text-[11px] text-slate-600 hover:underline px-1" data-testid={`contact-edit-${c.id}`}>Éditer</button>
                    <button onClick={() => del(c.id)} className="text-rose-500 hover:text-rose-700 p-1" data-testid={`contact-delete-${c.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal?.type === "edit" && <ContactEditModal contact={modal.contact} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} />}
      {modal?.type === "wa" && <WhatsAppModal contact={modal.contact} onClose={() => setModal(null)} />}
    </div>
  );
}

const ContactEditModal = ({ contact, onClose, onSaved }) => {
  const [form, setForm] = useState(() => contact || { name: "", phone: "", whatsapp: "", email: "", company: "", notes: "", tags: [], shared: false });
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

  const addTag = () => { const t = tagInput.trim(); if (!t) return; setForm({ ...form, tags: [...(form.tags || []), t] }); setTagInput(""); };
  const rmTag = (t) => setForm({ ...form, tags: (form.tags || []).filter((x) => x !== t) });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="contact-edit-modal">
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">{contact?.id ? "Modifier le contact" : "Nouveau contact"}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="contact-edit-close"><X className="h-4 w-4" /></button>
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <Input label="Nom *" value={form.name} onChange={(v) => setForm({ ...form, name: v })} testid="contact-field-name" />
          <Input label="Société" value={form.company} onChange={(v) => setForm({ ...form, company: v })} testid="contact-field-company" />
          <Input label="Téléphone (E.164)" value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} placeholder="+225xxxxxxxx" testid="contact-field-phone" />
          <Input label="WhatsApp (E.164)" value={form.whatsapp} onChange={(v) => setForm({ ...form, whatsapp: v })} placeholder="+225xxxxxxxx" testid="contact-field-whatsapp" />
          <Input label="Email" value={form.email} onChange={(v) => setForm({ ...form, email: v })} testid="contact-field-email" />
          <label className="flex items-center gap-2 text-sm mt-6"><input type="checkbox" checked={form.shared} onChange={(e) => setForm({ ...form, shared: e.target.checked })} data-testid="contact-field-shared" /> Partager avec les autres utilisateurs de mon client</label>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Notes</label>
          <textarea value={form.notes || ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="contact-field-notes" />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Catégories / Tags</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {(form.tags || []).map((t) => (
              <span key={t} className="text-xs bg-slate-100 px-2 py-0.5 rounded inline-flex items-center gap-1">{t} <button onClick={() => rmTag(t)}><X className="h-3 w-3" /></button></span>
            ))}
          </div>
          <div className="flex gap-2">
            <input value={tagInput} onChange={(e) => setTagInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }} placeholder="Fournisseur, Client, Technique…" className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" data-testid="contact-field-tag-input" />
            <button onClick={addTag} className="text-xs rounded bg-slate-900 text-white px-3">Ajouter</button>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button onClick={save} disabled={saving} className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50" data-testid="contact-edit-save">{saving ? "Enregistrement…" : "Enregistrer"}</button>
        </div>
      </div>
    </div>
  );
};

const WhatsAppModal = ({ contact, onClose }) => {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [templateName, setTemplateName] = useState("");
  const [language, setLanguage] = useState("fr");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    apiClient.get("/admin/whatsapp/templates").then((r) => {
      setTemplates(r.data?.items || []);
      if (r.data?.items?.[0]) setTemplateName(r.data.items[0].name);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const send = async () => {
    if (!templateName) { toast.error("Sélectionnez un template"); return; }
    setSending(true); setResult(null);
    try {
      const r = await apiClient.post("/me/whatsapp/send", {
        to: contact.whatsapp,
        template_name: templateName,
        language_code: language,
        contact_id: contact.id,
      });
      setResult(r.data);
      if (r.data?.ok) toast.success("Message WhatsApp envoyé"); else toast.error(r.data?.error || "Échec d'envoi");
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setSending(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="whatsapp-modal">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2"><MessageCircle className="h-5 w-5 text-emerald-600" /> Envoyer un WhatsApp</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <p className="text-sm text-slate-600">À : <strong>{contact.name}</strong> <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded ml-1">{contact.whatsapp}</code></p>
        {loading ? <p className="text-sm text-slate-500">Chargement des templates…</p> : templates.length === 0 ? (
          <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900">
            Aucun template approuvé. L'administrateur doit soumettre et faire approuver des templates dans Meta Business Suite &rarr; WhatsApp &rarr; Templates de messages.
          </div>
        ) : (
          <>
            <div>
              <label className="text-xs font-semibold block mb-1">Template</label>
              <select value={templateName} onChange={(e) => setTemplateName(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="wa-template-select">
                {templates.map((t) => <option key={t.name} value={t.name}>{t.name} ({t.language})</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Langue</label>
              <input value={language} onChange={(e) => setLanguage(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="wa-language-input" />
            </div>
          </>
        )}
        {result && (
          <div className={`rounded-lg ring-1 p-3 text-xs ${result.ok ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-rose-50 ring-rose-300 text-rose-900"}`} data-testid="wa-result">
            {result.ok ? (
              <><strong>Envoyé !</strong> ID message : <code>{result.message_id}</code></>
            ) : (
              <><strong>Échec :</strong> {result.error || "Erreur inconnue"} (HTTP {result.http_status || "—"})</>
            )}
          </div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Fermer</button>
          <button onClick={send} disabled={sending || templates.length === 0} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 disabled:opacity-50" data-testid="wa-send-btn"><Send className="h-4 w-4" /> {sending ? "Envoi…" : "Envoyer"}</button>
        </div>
      </div>
    </div>
  );
};

const Input = ({ label, value, onChange, placeholder, testid }) => (
  <div>
    <label className="block text-xs font-semibold mb-1">{label}</label>
    <input value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:border-sawali-blue" data-testid={testid} />
  </div>
);
