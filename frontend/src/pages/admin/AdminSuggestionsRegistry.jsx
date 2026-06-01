// S-iter39d (fix #4) — Read-only viewer for /app/memory/SUGGESTIONS.md.
// Admin/superviseur uniquement. Affiche le registre des suggestions
// numérotées (S001, S002, …) avec un rendu basique du Markdown.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { ScrollText, Loader2, RefreshCw, Copy } from "lucide-react";
import { toast } from "sonner";

function renderMarkdown(md) {
  if (!md) return null;
  // Minimal markdown → HTML. Safe enough for an internal admin-only file we
  // control. Avoids pulling a full markdown lib for one page.
  const lines = md.split("\n");
  const out = [];
  let inUL = false;
  const flushUL = () => { if (inUL) { out.push("</ul>"); inUL = false; } };
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    if (/^##\s+/.test(line)) {
      flushUL();
      out.push(`<h2 class="text-lg font-display font-bold text-sawali-blue mt-6 mb-2">${line.replace(/^##\s+/, "")}</h2>`);
    } else if (/^#\s+/.test(line)) {
      flushUL();
      out.push(`<h1 class="text-2xl font-display font-bold text-slate-900 mt-4 mb-3">${line.replace(/^#\s+/, "")}</h1>`);
    } else if (/^\s*-\s+/.test(line)) {
      if (!inUL) { out.push('<ul class="list-disc list-inside space-y-1 text-sm text-slate-700 ml-2">'); inUL = true; }
      let item = line.replace(/^\s*-\s+/, "");
      item = item
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-slate-900">$1</strong>')
        .replace(/`([^`]+)`/g, '<code class="bg-slate-100 px-1 rounded text-[11px] font-mono">$1</code>');
      out.push(`<li>${item}</li>`);
    } else if (line.trim() === "") {
      flushUL();
      out.push("");
    } else {
      flushUL();
      let p = line
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-slate-900">$1</strong>')
        .replace(/`([^`]+)`/g, '<code class="bg-slate-100 px-1 rounded text-[11px] font-mono">$1</code>');
      out.push(`<p class="text-sm text-slate-700 my-1">${p}</p>`);
    }
  }
  flushUL();
  return out.join("\n");
}

export default function AdminSuggestionsRegistry() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/suggestions-registry");
      setData(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lecture");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(data?.markdown || "");
      toast.success("Markdown copié dans le presse-papiers");
    } catch {
      toast.error("Copie impossible");
    }
  };

  return (
    <div className="space-y-4" data-testid="admin-suggestions-page">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-display font-bold text-slate-900 inline-flex items-center gap-2">
            <ScrollText className="h-6 w-6 text-violet-600" />
            Registre des suggestions (SUGGESTIONS.md)
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Liste de toutes les idées et améliorations numérotées (S001, S002, …) avec leur statut.
            Fichier source : <code className="bg-slate-100 px-1 rounded text-[11px] font-mono">/app/memory/SUGGESTIONS.md</code>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} disabled={loading} className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded-lg ring-1 ring-slate-200 hover:bg-slate-50 disabled:opacity-50" data-testid="suggestions-refresh">
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Rafraîchir
          </button>
          <button onClick={copy} disabled={!data?.markdown} className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded-lg ring-1 ring-violet-200 bg-violet-50 hover:bg-violet-100 text-violet-700 disabled:opacity-50" data-testid="suggestions-copy">
            <Copy className="h-3.5 w-3.5" /> Copier MD
          </button>
        </div>
      </header>
      <article className="rounded-2xl ring-1 ring-slate-200 bg-white p-6 prose prose-sm max-w-none">
        {loading ? (
          <p className="text-sm text-slate-500 flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p>
        ) : data ? (
          <>
            <p className="text-[11px] text-slate-400 mb-3 not-prose">
              Dernière mise à jour : {new Date(data.updated_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })} · {(data.size_bytes / 1024).toFixed(1)} Ko
            </p>
            <div data-testid="suggestions-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(data.markdown) }} />
          </>
        ) : (
          <p className="text-sm text-slate-500 italic">Aucun registre disponible.</p>
        )}
      </article>
    </div>
  );
}
