// S-iter39d (fix #4) — Read-only viewer for /app/memory/SUGGESTIONS.md.
// Admin/superviseur uniquement. Affiche le registre des suggestions
// numérotées (S001, S002, …) avec un rendu basique du Markdown.
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { ScrollText, Loader2, RefreshCw, Copy, Search, X } from "lucide-react";
import { toast } from "sonner";

// Iter40-suggestions-search — Tokenize a search query into individual words
// (lowercased, ≥2 chars). Every token must match somewhere in a suggestion
// block for that block to be kept (AND semantics).
function tokenize(q) {
  return (q || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "") // strip accents
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length >= 2);
}

// Split the markdown into "blocks" anchored on each "## " heading so the
// search returns whole suggestions (and not random matching lines).
function splitIntoBlocks(md) {
  if (!md) return [];
  const lines = md.split("\n");
  const blocks = [];
  let header = [];
  let current = null;
  for (const line of lines) {
    if (/^##\s+/.test(line)) {
      if (current) blocks.push(current);
      current = { heading: line.replace(/^##\s+/, "").trim(), body: [line] };
    } else if (current) {
      current.body.push(line);
    } else {
      // Lines before the first ## are part of the file preamble (top-level
      // # title + intro). Preserve them as a leading header block.
      header.push(line);
    }
  }
  if (current) blocks.push(current);
  return { headerMd: header.join("\n"), blocks };
}

function blockMatches(block, tokens) {
  if (tokens.length === 0) return true;
  const haystack = (block.body || []).join(" ")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
  return tokens.every((t) => haystack.includes(t));
}

function highlight(text, tokens) {
  if (!text || tokens.length === 0) return text;
  // Match against an accent-insensitive copy but preserve the original glyphs.
  let html = text;
  for (const t of tokens) {
    const re = new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
    html = html.replace(re, '<mark class="bg-yellow-200 rounded px-0.5">$1</mark>');
  }
  return html;
}

function renderMarkdown(md, tokens = []) {
  if (!md) return null;
  // Minimal markdown → HTML. Safe enough for an internal admin-only file we
  // control. Avoids pulling a full markdown lib for one page.
  const lines = md.split("\n");
  const out = [];
  let inUL = false;
  const flushUL = () => { if (inUL) { out.push("</ul>"); inUL = false; } };
  const applyHL = (s) => (tokens.length ? highlight(s, tokens) : s);
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    if (/^##\s+/.test(line)) {
      flushUL();
      out.push(`<h2 class="text-lg font-display font-bold text-sawali-blue mt-6 mb-2">${applyHL(line.replace(/^##\s+/, ""))}</h2>`);
    } else if (/^#\s+/.test(line)) {
      flushUL();
      out.push(`<h1 class="text-2xl font-display font-bold text-slate-900 mt-4 mb-3">${applyHL(line.replace(/^#\s+/, ""))}</h1>`);
    } else if (/^\s*-\s+/.test(line)) {
      if (!inUL) { out.push('<ul class="list-disc list-inside space-y-1 text-sm text-slate-700 ml-2">'); inUL = true; }
      let item = line.replace(/^\s*-\s+/, "");
      item = item
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-slate-900">$1</strong>')
        .replace(/`([^`]+)`/g, '<code class="bg-slate-100 px-1 rounded text-[11px] font-mono">$1</code>');
      out.push(`<li>${applyHL(item)}</li>`);
    } else if (line.trim() === "") {
      flushUL();
      out.push("");
    } else {
      flushUL();
      let p = line
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-slate-900">$1</strong>')
        .replace(/`([^`]+)`/g, '<code class="bg-slate-100 px-1 rounded text-[11px] font-mono">$1</code>');
      out.push(`<p class="text-sm text-slate-700 my-1">${applyHL(p)}</p>`);
    }
  }
  flushUL();
  return out.join("\n");
}

export default function AdminSuggestionsRegistry() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  // Iter40-suggestions-search — full-text search across all suggestion blocks
  const [query, setQuery] = useState("");

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

  // Iter40-suggestions-search — Compute filtered markdown based on query
  const { filteredMd, matchCount, totalCount } = useMemo(() => {
    if (!data?.markdown) return { filteredMd: "", matchCount: 0, totalCount: 0 };
    const { headerMd, blocks } = splitIntoBlocks(data.markdown);
    const tokens = tokenize(query);
    const matched = tokens.length === 0 ? blocks : blocks.filter((b) => blockMatches(b, tokens));
    const md = [headerMd, ...matched.map((b) => b.body.join("\n"))].join("\n");
    return { filteredMd: md, matchCount: matched.length, totalCount: blocks.length };
  }, [data, query]);
  const tokens = useMemo(() => tokenize(query), [query]);

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

      {/* Iter40-suggestions-search — Full-text search bar */}
      <div className="rounded-xl ring-1 ring-violet-200 bg-violet-50/40 p-3 flex flex-wrap items-center gap-2">
        <Search className="h-4 w-4 text-violet-600 shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher dans toutes les suggestions (mots-clés, statut, numéro S0XX…)"
          className="flex-1 min-w-[260px] bg-white rounded-lg ring-1 ring-violet-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
          data-testid="suggestions-search-input"
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            className="text-xs inline-flex items-center gap-1 px-2 py-1.5 rounded ring-1 ring-slate-200 bg-white hover:bg-slate-50 text-slate-600"
            data-testid="suggestions-search-clear"
          >
            <X className="h-3 w-3" /> Effacer
          </button>
        )}
        {query && (
          <span className="text-[11px] font-semibold text-violet-700 whitespace-nowrap" data-testid="suggestions-search-stats">
            {matchCount} / {totalCount} suggestion{matchCount > 1 ? "s" : ""}
          </span>
        )}
        <p className="text-[10px] text-slate-500 italic basis-full mt-1">
          Recherche insensible aux accents et à la casse. Plusieurs mots = ET logique (toutes les occurrences doivent être présentes dans la même suggestion).
        </p>
      </div>

      <article className="rounded-2xl ring-1 ring-slate-200 bg-white p-6 prose prose-sm max-w-none">
        {loading ? (
          <p className="text-sm text-slate-500 flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p>
        ) : data ? (
          <>
            <p className="text-[11px] text-slate-400 mb-3 not-prose">
              Dernière mise à jour : {new Date(data.updated_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })} · {(data.size_bytes / 1024).toFixed(1)} Ko
            </p>
            {query && matchCount === 0 ? (
              <p className="text-sm text-slate-500 italic" data-testid="suggestions-no-match">
                Aucune suggestion ne correspond à « {query} ». Essayez un autre mot-clé ou videz la recherche.
              </p>
            ) : (
              <div data-testid="suggestions-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(filteredMd, tokens) }} />
            )}
          </>
        ) : (
          <p className="text-sm text-slate-500 italic">Aucun registre disponible.</p>
        )}
      </article>
    </div>
  );
}
