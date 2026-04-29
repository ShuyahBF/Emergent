import React, { useEffect, useRef, useState } from "react";
import { useParams, Navigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import {
  Plus, Edit, Trash2, X, FileText, ClipboardList,
  Bold, Italic, Underline, Strikethrough,
  Heading2, Heading3, List, ListOrdered, Quote,
  AlignLeft, AlignCenter, AlignRight,
  Link as LinkIcon, Undo2, Redo2, Eraser, Code,
} from "lucide-react";
import { toast } from "sonner";

const KIND_META = {
  reports: { label: "Rapports", singular: "rapport", icon: FileText, accent: "#1E90FF" },
  suivis: { label: "Suivis", singular: "suivi", icon: ClipboardList, accent: "#10B981" },
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
    try {
      await apiClient.delete(`/me/notes/${kind}/${id}`);
      toast.success("Supprimée"); await load();
    } catch (err) { toast.error("Erreur"); }
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
        <button
          onClick={() => open()}
          className="inline-flex items-center gap-2 rounded-lg text-white px-4 py-2 text-sm hover:opacity-90"
          style={{ background: meta.accent }}
          data-testid={`new-${kind}-btn`}
        >
          <Plus className="h-4 w-4" /> Nouveau {meta.singular}
        </button>
      </div>

      {items.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500" data-testid={`empty-${kind}`}>
          Aucun {meta.singular} encore enregistré. Cliquez sur « Nouveau {meta.singular} » pour commencer.
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
                <button onClick={() => open(n)} className="text-slate-500 hover:text-sawali-blue inline-flex items-center gap-1" title="Modifier" data-testid={`edit-note-${n.id}`}>
                  <Edit className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => del(n.id)} className="text-slate-500 hover:text-rose-600 inline-flex items-center gap-1" title="Supprimer" data-testid={`delete-note-${n.id}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={close}>
          <div className="bg-white rounded-xl w-full max-w-3xl max-h-[92vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-display font-semibold">
                {editing?.id ? "Modifier" : "Nouveau"} {meta.singular}
              </h3>
              <button onClick={close} aria-label="Fermer"><X className="h-4 w-4" /></button>
            </div>
            <form onSubmit={submit} className="p-4 space-y-3" data-testid="note-form">
              <div>
                <label className="block text-xs font-semibold mb-1">Titre *</label>
                <input
                  required
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none"
                  data-testid="note-title-input"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold mb-1">Contenu</label>
                <RichEditor
                  value={form.content_html}
                  onChange={(v) => setForm({ ...form, content_html: v })}
                  accent={meta.accent}
                />
              </div>
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-lg text-white px-4 py-2 text-sm hover:opacity-90 disabled:opacity-50"
                style={{ background: meta.accent }}
                data-testid="save-note-btn"
              >
                {busy ? "Enregistrement..." : "Enregistrer"}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

// ====================================================================
// Rich Text Editor — WYSIWYG, contentEditable + execCommand
// ====================================================================
const TEXT_COLORS = ["#0F172A", "#1E90FF", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#0EA5E9"];
const HIGHLIGHTS = ["transparent", "#FEF3C7", "#DBEAFE", "#DCFCE7", "#FEE2E2", "#EDE9FE"];

function RichEditor({ value, onChange, accent = "#1E90FF" }) {
  const ref = useRef(null);
  const [showColors, setShowColors] = useState(false);
  const [showHighlights, setShowHighlights] = useState(false);

  // Initialize once and only sync from prop if editor is empty (to avoid caret jumps)
  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== (value || "")) {
      const empty = !ref.current.innerHTML || ref.current.innerHTML === "<br>";
      if (empty) ref.current.innerHTML = value || "";
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const emit = () => { if (ref.current) onChange(ref.current.innerHTML); };

  const exec = (cmd, arg = null) => {
    ref.current?.focus();
    document.execCommand(cmd, false, arg);
    emit();
  };

  const setLink = () => {
    const url = window.prompt("URL du lien :", "https://");
    if (!url) return;
    exec("createLink", url);
  };

  const Btn = ({ onClick, title, active, children, testid }) => (
    <button
      type="button"
      title={title}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={`p-1.5 rounded hover:bg-slate-100 text-slate-600 ${active ? "bg-slate-200 text-slate-900" : ""}`}
      data-testid={testid}
    >
      {children}
    </button>
  );

  return (
    <div className="rounded-lg border border-slate-300 focus-within:border-sawali-blue overflow-hidden">
      <div className="flex items-center flex-wrap gap-0.5 border-b border-slate-200 bg-slate-50/60 px-2 py-1.5" data-testid="rte-toolbar">
        <Btn onClick={() => exec("bold")} title="Gras (Ctrl+B)" testid="rte-bold"><Bold className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("italic")} title="Italique (Ctrl+I)" testid="rte-italic"><Italic className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("underline")} title="Souligné" testid="rte-underline"><Underline className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("strikeThrough")} title="Barré" testid="rte-strike"><Strikethrough className="h-3.5 w-3.5" /></Btn>

        <span className="w-px h-5 bg-slate-200 mx-1" />

        <Btn onClick={() => exec("formatBlock", "h2")} title="Titre" testid="rte-h2"><Heading2 className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("formatBlock", "h3")} title="Sous-titre" testid="rte-h3"><Heading3 className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("formatBlock", "blockquote")} title="Citation" testid="rte-quote"><Quote className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("formatBlock", "pre")} title="Bloc de code" testid="rte-code"><Code className="h-3.5 w-3.5" /></Btn>

        <span className="w-px h-5 bg-slate-200 mx-1" />

        <Btn onClick={() => exec("insertUnorderedList")} title="Liste à puces" testid="rte-ul"><List className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("insertOrderedList")} title="Liste numérotée" testid="rte-ol"><ListOrdered className="h-3.5 w-3.5" /></Btn>

        <span className="w-px h-5 bg-slate-200 mx-1" />

        <Btn onClick={() => exec("justifyLeft")} title="Aligner à gauche" testid="rte-left"><AlignLeft className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("justifyCenter")} title="Centrer" testid="rte-center"><AlignCenter className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("justifyRight")} title="Aligner à droite" testid="rte-right"><AlignRight className="h-3.5 w-3.5" /></Btn>

        <span className="w-px h-5 bg-slate-200 mx-1" />

        <div className="relative">
          <Btn onClick={() => { setShowColors((v) => !v); setShowHighlights(false); }} title="Couleur de texte" testid="rte-color">
            <span className="inline-flex flex-col items-center leading-none">
              <span className="font-bold text-[10px]">A</span>
              <span className="block w-3 h-0.5" style={{ background: accent }} />
            </span>
          </Btn>
          {showColors && (
            <div className="absolute left-0 top-full mt-1 z-10 bg-white border border-slate-200 rounded-lg shadow-lg p-2 flex gap-1">
              {TEXT_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => { exec("foreColor", c); setShowColors(false); }}
                  className="h-5 w-5 rounded-full border border-slate-200"
                  style={{ background: c }}
                  title={c}
                />
              ))}
            </div>
          )}
        </div>

        <div className="relative">
          <Btn onClick={() => { setShowHighlights((v) => !v); setShowColors(false); }} title="Surlignage" testid="rte-highlight">
            <span className="inline-flex flex-col items-center leading-none">
              <span className="font-bold text-[10px]">H</span>
              <span className="block w-3 h-0.5 bg-yellow-300" />
            </span>
          </Btn>
          {showHighlights && (
            <div className="absolute left-0 top-full mt-1 z-10 bg-white border border-slate-200 rounded-lg shadow-lg p-2 flex gap-1">
              {HIGHLIGHTS.map((c) => (
                <button
                  key={c}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => { exec("hiliteColor", c); setShowHighlights(false); }}
                  className="h-5 w-5 rounded-full border border-slate-200"
                  style={{ background: c === "transparent" ? "repeating-linear-gradient(45deg,#fff,#fff 3px,#eee 3px,#eee 6px)" : c }}
                  title={c}
                />
              ))}
            </div>
          )}
        </div>

        <span className="w-px h-5 bg-slate-200 mx-1" />

        <Btn onClick={setLink} title="Insérer un lien" testid="rte-link"><LinkIcon className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("removeFormat")} title="Effacer la mise en forme" testid="rte-clear"><Eraser className="h-3.5 w-3.5" /></Btn>

        <span className="w-px h-5 bg-slate-200 mx-1" />

        <Btn onClick={() => exec("undo")} title="Annuler" testid="rte-undo"><Undo2 className="h-3.5 w-3.5" /></Btn>
        <Btn onClick={() => exec("redo")} title="Rétablir" testid="rte-redo"><Redo2 className="h-3.5 w-3.5" /></Btn>
      </div>

      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        onInput={emit}
        onBlur={emit}
        className="prose-sawali min-h-[220px] max-h-[420px] overflow-auto px-3 py-2 text-sm focus:outline-none"
        style={{ caretColor: accent }}
        data-testid="rte-content"
      />
    </div>
  );
}
