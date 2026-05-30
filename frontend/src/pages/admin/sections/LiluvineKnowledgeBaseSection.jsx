// =====================================================================
// Iter38r-fix9c — Liluvine PRO : Base de connaissance (FAQ + PDF/TXT)
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Brain, Plus, FileText, Upload, Trash2, Pencil, Save, X, BookOpen, FileBox, ScanText, Clipboard } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const MAX_CHAR_PREVIEW = 280;

export default function LiluvineKnowledgeBaseSection() {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState({ total: 0, enabled: 0, total_chars: 0, context_budget_chars: 6000 });
  const [editing, setEditing] = useState(null); // { id?, title, content, tags }
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/liluvine-pro/kb");
      setItems(r.data?.items || []);
      setStats(r.data?.stats || { total: 0, enabled: 0, total_chars: 0, context_budget_chars: 6000 });
    } catch {
      toast.error("Erreur chargement Base de connaissance");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Iter38r-fix9k — Paste screenshot from clipboard (Ctrl+V) anywhere on the
  // section triggers an OCR upload automatically.
  useEffect(() => {
    const handler = async (e) => {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const it of items) {
        if (it.type && it.type.startsWith("image/")) {
          const blob = it.getAsFile();
          if (!blob) continue;
          const ext = (it.type.split("/")[1] || "png").replace("jpeg", "jpg");
          const file = new File([blob], `clipboard-${Date.now()}.${ext}`, { type: it.type });
          e.preventDefault();
          await upload(file, { ocr: true, source: "clipboard" });
          break;
        }
      }
    };
    window.addEventListener("paste", handler);
    return () => window.removeEventListener("paste", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openCreate = () => setEditing({ title: "", content: "", tags: "" });
  const openEdit = (it) => setEditing({
    id: it.id, title: it.title || "", content: it.content || "",
    tags: (it.tags || []).join(", "), enabled: it.enabled !== false,
  });
  const closeEditor = () => setEditing(null);

  const save = async () => {
    if (!editing?.title?.trim() || !editing?.content?.trim()) {
      toast.error("Titre et contenu sont requis");
      return;
    }
    const payload = {
      title: editing.title.trim(),
      content: editing.content,
      tags: (editing.tags || "").split(",").map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (editing.id) {
        if (editing.enabled !== undefined) payload.enabled = !!editing.enabled;
        await apiClient.put(`/admin/liluvine-pro/kb/${editing.id}`, payload);
        toast.success("Entrée mise à jour");
      } else {
        await apiClient.post("/admin/liluvine-pro/kb", payload);
        toast.success("Entrée créée");
      }
      closeEditor();
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur d'enregistrement");
    }
  };

  const toggleEnabled = async (it) => {
    try {
      await apiClient.put(`/admin/liluvine-pro/kb/${it.id}`, { enabled: !it.enabled });
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (it) => {
    if (!window.confirm(`Supprimer définitivement « ${it.title} » ?`)) return;
    try {
      await apiClient.delete(`/admin/liluvine-pro/kb/${it.id}`);
      toast.success("Supprimée");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const upload = async (file, { ocr = false, source = "file" } = {}) => {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      toast.error("Fichier trop volumineux (max 5 Mo)");
      return;
    }
    const baseTitle = (file.name || "Document").replace(/\.(pdf|txt|png|jpe?g|webp)$/i, "");
    const isClipboard = source === "clipboard";
    const title = isClipboard
      ? (window.prompt("Titre de l'entrée (capture d'écran) :", `Capture ${new Date().toLocaleString("fr-FR")}`) || baseTitle)
      : window.prompt("Titre de l'entrée (sera affiché dans la base) :", baseTitle);
    if (!title?.trim()) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", title.trim());
      if (ocr) fd.append("force_ocr", "true");
      const r = await apiClient.post("/admin/liluvine-pro/kb/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`${r.data?.chunks || 0} entrée(s) créée(s)${isClipboard ? " depuis le presse-papier" : ""}${ocr ? " (OCR)" : ""}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur upload");
    } finally {
      setUploading(false);
    }
  };

  const usagePct = stats.context_budget_chars > 0
    ? Math.min(100, Math.round((stats.total_chars / stats.context_budget_chars) * 100))
    : 0;

  return (
    <section className="rounded-xl border border-violet-200 bg-gradient-to-br from-violet-50/40 to-white p-5 space-y-4" data-testid="liluvine-kb-section">
      <header className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="text-base font-display font-bold inline-flex items-center gap-2 text-violet-900">
          <Brain className="h-5 w-5 text-violet-600" /> Liluvine PRO — Base de connaissance
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="inline-flex items-center gap-1 cursor-pointer rounded-lg ring-1 ring-violet-300 hover:bg-violet-50 text-violet-700 px-2.5 py-1.5 text-xs font-medium" data-testid="liluvine-kb-upload" title="PDF/TXT — extraction texte native, pas d'OCR">
            <Upload className="h-3.5 w-3.5" /> {uploading ? "Upload…" : "Importer PDF / TXT"}
            <input type="file" accept=".pdf,.txt,application/pdf,text/plain" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f, { ocr: false }); e.target.value = ""; }} />
          </label>
          <label className="inline-flex items-center gap-1 cursor-pointer rounded-lg ring-1 ring-sky-300 hover:bg-sky-50 text-sky-700 px-2.5 py-1.5 text-xs font-medium" data-testid="liluvine-kb-upload-ocr" title="Image (PNG/JPG/WEBP) — OCR via Claude Vision">
            <ScanText className="h-3.5 w-3.5" /> {uploading ? "OCR…" : "Importer Image (OCR)"}
            <input type="file" accept=".png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f, { ocr: true }); e.target.value = ""; }} />
          </label>
          <button type="button" onClick={openCreate}
            className="inline-flex items-center gap-1 rounded-lg bg-violet-600 hover:bg-violet-700 text-white px-2.5 py-1.5 text-xs font-medium"
            data-testid="liluvine-kb-add">
            <Plus className="h-3.5 w-3.5" /> Ajouter
          </button>
        </div>
      </header>

      <p className="text-xs text-slate-600 leading-relaxed">
        Alimentez Liluvine PRO avec votre FAQ, vos procédures internes, et la documentation de vos logiciels SAWALI.
        Le contenu est injecté automatiquement dans chaque conversation (chat + WhatsApp auto-réponse). Limité à <strong>{stats.context_budget_chars.toLocaleString()} caractères</strong> par conversation.
      </p>
      <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50/60 p-2.5 text-[11px] text-sky-900 inline-flex items-center gap-1.5" data-testid="liluvine-kb-clipboard-hint">
        <Clipboard className="h-3.5 w-3.5" /> <strong>Astuce :</strong> faites <kbd className="rounded bg-white ring-1 ring-sky-300 px-1.5 py-0.5 text-[10px] font-mono">Ctrl+V</kbd> ici pour importer une capture d'écran directement avec OCR.
      </div>

      {/* Stats / usage bar */}
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg bg-violet-50 ring-1 ring-violet-200 p-2.5">
          <p className="text-[10px] uppercase tracking-wider text-violet-700">Entrées totales</p>
          <p className="text-xl font-display font-bold text-violet-900">{stats.total}</p>
        </div>
        <div className="rounded-lg bg-emerald-50 ring-1 ring-emerald-200 p-2.5">
          <p className="text-[10px] uppercase tracking-wider text-emerald-700">Actives</p>
          <p className="text-xl font-display font-bold text-emerald-900">{stats.enabled}</p>
        </div>
        <div className="rounded-lg bg-sky-50 ring-1 ring-sky-200 p-2.5">
          <p className="text-[10px] uppercase tracking-wider text-sky-700">Caractères stockés</p>
          <p className="text-xl font-display font-bold text-sky-900">{stats.total_chars.toLocaleString()}</p>
        </div>
      </div>
      <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden" data-testid="liluvine-kb-usage-bar">
        <div className={`h-full ${usagePct > 80 ? "bg-amber-500" : "bg-violet-500"} transition-all`} style={{ width: `${usagePct}%` }} />
      </div>
      {usagePct > 80 && (
        <p className="text-[11px] text-amber-700">⚠️ La base dépasse {usagePct}% du budget par conversation. Les dernières entrées seront tronquées dans le contexte injecté.</p>
      )}

      {/* List */}
      <div className="space-y-2 max-h-[480px] overflow-y-auto pr-1">
        {items.length === 0 ? (
          <p className="text-sm text-slate-500 text-center py-6">
            <BookOpen className="h-5 w-5 inline mr-1 text-slate-400" />
            Aucune entrée pour le moment. Cliquez sur <strong>Ajouter</strong> ou importez un PDF.
          </p>
        ) : items.map((it) => (
          <div key={it.id} className={`rounded-lg ring-1 ${it.enabled ? "ring-slate-200 bg-white" : "ring-slate-200 bg-slate-50 opacity-60"} p-3`}
            data-testid={`liluvine-kb-item-${it.id}`}>
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  {it.kind === "pdf" ? <FileBox className="h-4 w-4 text-rose-500" /> :
                   it.kind === "txt" ? <FileText className="h-4 w-4 text-slate-500" /> :
                   it.kind === "image_ocr" ? <FileText className="h-4 w-4 text-sky-500" /> :
                                       <BookOpen className="h-4 w-4 text-violet-500" />}
                  <p className="text-sm font-semibold text-slate-800 truncate">{it.title}</p>
                  <span className="text-[10px] rounded-full bg-slate-100 ring-1 ring-slate-200 text-slate-600 px-1.5 py-0.5">{it.char_count || (it.content || "").length} car.</span>
                </div>
                <p className="text-xs text-slate-600 mt-1 line-clamp-2">{(it.content || "").slice(0, MAX_CHAR_PREVIEW)}{(it.content || "").length > MAX_CHAR_PREVIEW ? "…" : ""}</p>
                {it.tags?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {it.tags.map((t) => <span key={t} className="text-[10px] rounded bg-violet-50 text-violet-700 px-1.5 py-0.5">#{t}</span>)}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <button type="button" onClick={() => toggleEnabled(it)} title={it.enabled ? "Désactiver" : "Activer"}
                  className={`text-xs px-2 py-1 rounded ${it.enabled ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-200" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                  data-testid={`liluvine-kb-toggle-${it.id}`}>
                  {it.enabled ? "Actif" : "Inactif"}
                </button>
                <button type="button" onClick={() => openEdit(it)} className="p-1 text-slate-500 hover:text-violet-700"
                  data-testid={`liluvine-kb-edit-${it.id}`}><Pencil className="h-3.5 w-3.5" /></button>
                <button type="button" onClick={() => remove(it)} className="p-1 text-slate-500 hover:text-rose-700"
                  data-testid={`liluvine-kb-delete-${it.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Editor modal */}
      {editing && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onClick={closeEditor}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
            <header className="px-5 py-3 border-b border-slate-200 flex items-center justify-between">
              <h3 className="font-display font-semibold text-slate-800">
                {editing.id ? "Modifier" : "Nouvelle entrée"} de la base de connaissance
              </h3>
              <button onClick={closeEditor} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
            </header>
            <div className="p-5 space-y-3 overflow-y-auto flex-1">
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Titre</label>
                <input type="text" value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                  placeholder="ex: Comment configurer WhatsApp Cloud API"
                  className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
                  data-testid="liluvine-kb-editor-title" maxLength={200} />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  Contenu <span className="text-slate-400">({editing.content?.length || 0} / 8000 car.)</span>
                </label>
                <textarea value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })}
                  placeholder="Décrivez la procédure, la FAQ, ou collez votre documentation ici…"
                  rows={14} maxLength={8000}
                  className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2 font-mono"
                  data-testid="liluvine-kb-editor-content" />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-700 mb-1">Tags (séparés par virgule)</label>
                <input type="text" value={editing.tags} onChange={(e) => setEditing({ ...editing, tags: e.target.value })}
                  placeholder="faq, whatsapp, configuration"
                  className="w-full text-sm rounded-lg border border-slate-300 px-3 py-2"
                  data-testid="liluvine-kb-editor-tags" />
              </div>
              {editing.id && (
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={!!editing.enabled}
                    onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })}
                    className="h-4 w-4 rounded text-violet-600" />
                  <span className="text-sm text-slate-800">Entrée active (injectée dans Liluvine)</span>
                </label>
              )}
            </div>
            <footer className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
              <button type="button" onClick={closeEditor}
                className="px-3 py-2 text-sm rounded-lg ring-1 ring-slate-300 text-slate-600 hover:bg-slate-50">Annuler</button>
              <button type="button" onClick={save}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-violet-600 hover:bg-violet-700 text-white"
                data-testid="liluvine-kb-editor-save">
                <Save className="h-4 w-4" /> Enregistrer
              </button>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
}
