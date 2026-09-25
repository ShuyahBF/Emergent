import React, { useState } from "react";
import { toast } from "sonner";
import { FileText, Tag, X, Plus, Sparkles, Loader2, Check, Folder, Trash2 } from "lucide-react";
import { apiClient } from "@/lib/api";

/*
  Lot 22 — Tags des documents de l'Explorateur Stockage R2 (Gestion de Stocks).

  R2FileRow : une ligne de fichier (liste d'un dossier OU résultat de
  recherche) avec ses tags, sa description et, si l'utilisateur en a le droit
  (`file.can_edit`, calculé par le serveur), un éditeur en ligne :
    - ajout/retrait de tags (suggestions = tags déjà utilisés par le client) ;
    - description ;
    - suggestions de l'IA (cliquer pour ajouter) et bouton « Suggérer des
      tags (IA) » si l'option est activée pour le client (`aiEnabled`).
  Le serveur nettoie toujours les tags (minuscules, 40 caractères, 15 max) :
  l'écran affiche ce qu'il renvoie.
*/

// Taille lisible (« 12,3 Ko ») et date courte française.
function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}
function formatDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
}

// Pastille de tag ; `onRemove` affiche une croix, `onClick` la rend cliquable.
export function TagChip({ tag, onRemove, onClick, active = false, variant = "teal" }) {
  const colors = variant === "ai"
    ? "bg-violet-50 text-violet-700 ring-violet-200 hover:bg-violet-100"
    : active
      ? "bg-teal-600 text-white ring-teal-600"
      : "bg-teal-50 text-teal-800 ring-teal-200";
  const Comp = onClick ? "button" : "span";
  return (
    <Comp type={onClick ? "button" : undefined} onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-full ring-1 px-2 py-0.5 text-[11px] ${colors}`}
      data-testid={`r2-tag-${variant}-${tag}`}>
      {variant === "ai" ? <Plus className="w-3 h-3" /> : <Tag className="w-3 h-3" />}
      {tag}
      {onRemove && (
        <X className="w-3 h-3 cursor-pointer hover:text-rose-600" onClick={(e) => { e.stopPropagation(); onRemove(); }} />
      )}
    </Comp>
  );
}

// Transforme un texte « facture, copharmed » en liste de tags (le serveur finalise).
export function parseTags(text) {
  return (text || "").split(/[,;\n]/).map((t) => t.trim().toLowerCase()).filter(Boolean);
}

export function R2FileRow({ file, onOpen, onChanged, onDeleted, knownTags = [], aiEnabled = false, showFolder = false, folderLabel = (f) => f }) {
  const [editing, setEditing] = useState(false);
  const [tags, setTags] = useState(file.tags || []);
  const [draft, setDraft] = useState("");
  const [description, setDescription] = useState(file.description || "");
  const [saving, setSaving] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [aiTags, setAiTags] = useState(file.ai_suggested_tags || []);
  const [aiDescription, setAiDescription] = useState(file.ai_suggested_description || "");

  // Ouvre l'éditeur avec les valeurs actuelles du fichier.
  const startEdit = (e) => {
    e.stopPropagation();
    setTags(file.tags || []); setDescription(file.description || ""); setDraft("");
    setAiTags(file.ai_suggested_tags || []); setAiDescription(file.ai_suggested_description || "");
    setEditing(true);
  };

  // Ajoute le(s) tag(s) saisi(s) dans la zone de saisie.
  const addDraft = () => {
    const extra = parseTags(draft).filter((t) => !tags.includes(t));
    if (extra.length) setTags([...tags, ...extra]);
    setDraft("");
  };

  // Enregistre tags + description (PUT /gestion-stocks/files/meta).
  const save = async () => {
    const finalTags = [...tags, ...parseTags(draft).filter((t) => !tags.includes(t))];
    setSaving(true);
    try {
      const r = await apiClient.put("/gestion-stocks/files/meta", { key: file.key, tags: finalTags, description });
      toast.success("Tags enregistrés");
      setEditing(false);
      onChanged?.({ ...file, ...r.data });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'enregistrement des tags");
    } finally {
      setSaving(false);
    }
  };

  // Demande à l'IA des tags pour ce fichier (POST /gestion-stocks/files/suggest-tags).
  const suggest = async () => {
    setSuggesting(true);
    try {
      const r = await apiClient.post("/gestion-stocks/files/suggest-tags", { key: file.key });
      setAiTags(r.data?.ai_suggested_tags || []);
      setAiDescription(r.data?.ai_suggested_description || "");
      if (r.data?.ai_error) toast.warning(r.data.ai_error);
      else toast.success(`Suggestions de l'IA prêtes (${Number(r.data?.cost_xof || 0).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} FCFA)`);
      onChanged?.({ ...file, ai_suggested_tags: r.data?.ai_suggested_tags || [], ai_suggested_description: r.data?.ai_suggested_description || "" }, { keepEditing: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Suggestion IA impossible");
    } finally {
      setSuggesting(false);
    }
  };

  // Lot 23 — suppression (admin/superviseur, ou Pharmacien suivi sur ses propres fichiers).
  const [deleting, setDeleting] = useState(false);
  const remove = async (e) => {
    e.stopPropagation();
    if (!window.confirm(`Supprimer définitivement « ${file.name} » du compartiment R2 ?`)) return;
    setDeleting(true);
    try {
      await apiClient.delete("/gestion-stocks/files", { params: { key: file.key } });
      toast.success(`« ${file.name} » supprimé`);
      onDeleted?.(file);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la suppression");
      setDeleting(false);
    }
  };

  const pendingAi = aiTags.filter((t) => !tags.includes(t));
  const listId = `r2-known-tags-${file.key}`;

  return (
    <li className="px-3 py-2 hover:bg-slate-50" data-testid="gestion-stocks-file-row">
      <div className="flex items-center justify-between gap-3 cursor-pointer" onDoubleClick={() => onOpen(file)} title="Double-cliquer pour afficher">
        <span className="flex items-center gap-2 text-sm text-slate-700 min-w-0">
          <FileText className="w-4 h-4 text-slate-400 shrink-0" />
          <span className="truncate">{file.name}</span>
          {/* Résultat de recherche : dossier où se trouve le fichier */}
          {showFolder && (
            <span className="inline-flex items-center gap-1 text-[10px] text-slate-500 bg-slate-100 rounded px-1.5 py-0.5 shrink-0"
              data-testid="r2-file-folder">
              <Folder className="w-3 h-3" /> {folderLabel(file.folder)}
            </span>
          )}
        </span>
        <span className="flex items-center gap-2 shrink-0">
          <span className="text-[11px] text-slate-400">{formatSize(file.size)} · {formatDate(file.last_modified)}</span>
          {file.can_edit && !editing && (
            <button type="button" onClick={startEdit} title="Modifier les tags"
              className="inline-flex items-center gap-1 text-[11px] text-teal-700 hover:underline" data-testid="r2-file-edit-tags">
              <Tag className="w-3.5 h-3.5" /> Tags
            </button>
          )}
          {/* Lot 23 — bouton de suppression (droit calculé par le serveur) */}
          {file.can_delete && !editing && (
            <button type="button" onClick={remove} disabled={deleting} title="Supprimer ce fichier"
              className="text-slate-400 hover:text-rose-600 disabled:opacity-50" data-testid="r2-file-delete">
              {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
            </button>
          )}
        </span>
      </div>

      {/* Lot 23 — résultat trouvé dans le texte du document : extrait correspondant */}
      {file.match_snippet && (
        <p className="mt-1 ml-6 text-[11px] text-slate-600 italic bg-amber-50 rounded px-2 py-1" data-testid="r2-file-snippet">
          « {file.match_snippet} »
        </p>
      )}

      {/* Lecture : tags, description, suggestions IA en attente */}
      {!editing && (file.tags?.length > 0 || file.description || file.ai_suggested_tags?.length > 0) && (
        <div className="mt-1 ml-6 space-y-1">
          {file.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1">{file.tags.map((t) => <TagChip key={t} tag={t} />)}</div>
          )}
          {file.description && <p className="text-[11px] text-slate-500">{file.description}</p>}
          {file.can_edit && file.ai_suggested_tags?.length > 0 && (
            <p className="text-[10px] text-violet-700 inline-flex items-center gap-1">
              <Sparkles className="w-3 h-3" /> {file.ai_suggested_tags.length} tag(s) suggéré(s) par l'IA — cliquez sur « Tags » pour les voir.
            </p>
          )}
        </div>
      )}

      {/* Édition en ligne */}
      {editing && (
        <div className="mt-2 ml-6 space-y-2 rounded-lg ring-1 ring-teal-200 bg-teal-50/40 p-2" onDoubleClick={(e) => e.stopPropagation()}
          data-testid="r2-file-tag-editor">
          <div className="flex flex-wrap gap-1">
            {tags.length === 0 && <span className="text-[11px] italic text-slate-400">Aucun tag</span>}
            {tags.map((t) => <TagChip key={t} tag={t} onRemove={() => setTags(tags.filter((x) => x !== t))} />)}
          </div>
          <div className="flex gap-2">
            <input value={draft} onChange={(e) => setDraft(e.target.value)} list={listId}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addDraft(); } }}
              placeholder="Ajouter un tag puis Entrée (ex. facture, copharmed, décembre 2024)"
              className="flex-1 px-2 py-1 rounded ring-1 ring-slate-300 text-xs bg-white" data-testid="r2-tag-input" />
            {/* Suggestions de saisie : tags déjà utilisés par ce client */}
            <datalist id={listId}>{knownTags.map((k) => <option key={k.tag} value={k.tag} />)}</datalist>
            <button type="button" onClick={addDraft} className="px-2 py-1 rounded text-xs ring-1 ring-teal-300 text-teal-800 bg-white">Ajouter</button>
          </div>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={500}
            placeholder="Description (facultative)" className="w-full px-2 py-1 rounded ring-1 ring-slate-300 text-xs bg-white"
            data-testid="r2-description-input" />

          {/* Suggestions de l'IA : jamais appliquées d'office, un clic pour ajouter */}
          {(pendingAi.length > 0 || (aiDescription && aiDescription !== description)) && (
            <div className="rounded bg-violet-50/60 ring-1 ring-violet-200 p-2 space-y-1" data-testid="r2-ai-suggestions">
              <p className="text-[10px] font-semibold text-violet-800 inline-flex items-center gap-1"><Sparkles className="w-3 h-3" /> Suggestions de l'IA (cliquez pour ajouter)</p>
              <div className="flex flex-wrap gap-1">
                {pendingAi.map((t) => <TagChip key={t} tag={t} variant="ai" onClick={() => setTags([...tags, t])} />)}
                {pendingAi.length > 1 && (
                  <button type="button" onClick={() => setTags([...tags, ...pendingAi])} className="text-[10px] text-violet-700 hover:underline">Tout ajouter</button>
                )}
              </div>
              {aiDescription && aiDescription !== description && (
                <button type="button" onClick={() => setDescription(aiDescription)} className="text-[10px] text-violet-700 hover:underline text-left"
                  data-testid="r2-ai-use-description">
                  Utiliser la description proposée : « {aiDescription} »
                </button>
              )}
            </div>
          )}

          <div className="flex items-center justify-between gap-2 flex-wrap">
            {aiEnabled ? (
              <button type="button" onClick={suggest} disabled={suggesting}
                className="inline-flex items-center gap-1 text-[11px] text-violet-700 hover:underline disabled:opacity-50" data-testid="r2-ai-suggest">
                {suggesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                {suggesting ? "Analyse en cours…" : "Suggérer des tags (IA)"}
              </button>
            ) : <span />}
            <span className="flex gap-2">
              <button type="button" onClick={() => setEditing(false)} className="px-2 py-1 rounded text-xs text-slate-600 hover:bg-slate-100">Annuler</button>
              <button type="button" onClick={save} disabled={saving}
                className="inline-flex items-center gap-1 px-3 py-1 rounded text-xs font-medium text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-50"
                data-testid="r2-tags-save">
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />} Enregistrer
              </button>
            </span>
          </div>
        </div>
      )}
    </li>
  );
}

export default R2FileRow;
