import React, { useEffect, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Plus, Edit, Trash2, X, FileText, ClipboardList } from "lucide-react";
import { toast } from "sonner";

const KIND_META = {
  reports: { label: "Rapports", icon: FileText, accent: "#1E90FF" },
  suivis: { label: "Suivis", icon: ClipboardList, accent: "#10B981" },
};

const empty = { title: "", content_html: "", tags: [] };

export default function UserNotesPage() {
  const { kind } = useParams();
  const meta = KIND_META[kind];
  const [items, setItems] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);

  const load = () => apiClient.get(`/me/notes/${kind}`).then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => { if (meta) load(); /* eslint-disable-next-line */ }, [kind]);

  if (!meta) return <Navigate to="/portal" replace />;

  const open = (it = null) => {
    setEditing(it);
    setForm(it ? { ...empty, ...it, tags: it.tags || [] } : empty);
    setIsOpen(true);
  };
  const close = () => { setIsOpen(false); setEditing(null); setForm(empty); };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.title.trim()) { toast.error("Titre requis"); return; }
    setBusy(true);
    try {
      if (editing?.id) await apiClient.put(`/me/notes/${kind}/${editing.id}`, form);
      else await apiClient.post(`/me/notes/${kind}`, form);
      toast.success("Enregistré"); close(); await load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer cette note ?")) return;
    await apiClient.delete(`/me/notes/${kind}/${id}`);
    toast.success("Supprimée"); await load();
  };

  const Icon = meta.icon;

  return (
    <div className="space-y-6" data-testid={`notes-${kind}-page`}>
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Icon className="h-6 w-6" style={{ color: meta.accent }} /> Mes {meta.label}
          </h1>
          <p className="text-sm text-slate-500">
            Saisissez et conservez vos {meta.label.toLowerCase()} avec mise en forme. Horodatage automatique à chaque modification.
          </p>
        </div>
        <button onClick={() => open()} className="inline-flex items-center gap-2 rounded-lg text-white px-4 py-2 text-sm hover:opacity-90" style={{ background: meta.accent }} data-testid={`new-${kind}-btn`}>
          <Plus className="h-4 w-4" /> Nouveau {kind === "reports" ? "rapport" : "suivi"}
        </button>
      </div>

      {items.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500">
          Aucun {kind === "reports" ? "rapport" : "suivi"} encore enregistré.
        </div>
      )}

      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((n) => (
          <article key={n.id} className="rounded-xl border border-slate-200 bg-white p-5 hover:border-sawali-blue/40 transition" data-testid={`note-${n.id}`}>
            <h3 className="font-display font-semibold text-slate-900 truncate" title={n.title}>{n.title}</h3>
            <div className="mt-2 text-sm text-slate-600 prose-sawali line-clamp-4" dangerouslySetInnerHTML={{ __html: n.content_html || "<p class=\"text-slate-400 italic\">Aucun contenu</p>" }} />
            <div className="mt-3 flex items-center justify-between gap-2 text-xs">
              <span className="text-slate-400">
                Modifié le {new Date(n.updated_at).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })}
              </span>
              <div className="flex gap-2">
                <button onClick={() => open(n)} className="text-slate-500 hover:text-sawali-blue" title="Modifier"><Edit className="h-3.5 w-3.5 inline" /></button>
                <button onClick={() => del(n.id)} className="text-slate-500 hover:text-rose-600" title="Supprimer"><Trash2 className="h-3.5 w-3.5 inline" /></button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-2xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">{editing?.id ? "Modifier" : "Nouveau"} {kind === "reports" ? "rapport" : "suivi"}</h3>
              <button onClick={close} aria-label="Fermer"><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3" data-testid="note-form">
              <div>
                <label className="block text-xs font-semibold mb-1">Titre *</label>
                <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none" />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Contenu (HTML, mise en forme rapide)</label>
                <RichEditor value={form.content_html} onChange={(v) => setForm({ ...form, content_html: v })} />
              </div>
              <button type="submit" disabled={busy} className="w-full rounded-lg text-white px-4 py-2 text-sm hover:opacity-90 disabled:opacity-50" style={{ background: meta.accent }} data-testid="save-note-btn">
                {busy ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function RichEditor({ value, onChange }) {
  const wrap = (tag) => {
    const sel = window.getSelection();
    const txt = sel?.toString();
    if (txt) onChange(value.replace(txt, `<${tag}>${txt}</${tag}>`));
  };
  return (
    <div>
      <div className="flex flex-wrap gap-1 mb-1 text-xs">
        {[["b", "Gras"], ["i", "Italique"], ["u", "Souligné"], ["h2", "Titre"], ["h3", "Sous-titre"], ["p", "Paragraphe"], ["ul", "Liste"], ["li", "Item"]].map(([t, l]) => (
          <button key={t} type="button" onClick={() => wrap(t)} className="px-2 py-1 rounded border border-slate-200 hover:bg-slate-50">{l}</button>
        ))}
      </div>
      <textarea rows={10} value={value} onChange={(e) => onChange(e.target.value)} placeholder="<p>Votre contenu...</p>" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" />
      {value && <div className="mt-2 rounded-lg border border-slate-200 p-3 prose-sawali bg-slate-50 max-h-48 overflow-auto" dangerouslySetInnerHTML={{ __html: value }} />}
    </div>
  );
}
