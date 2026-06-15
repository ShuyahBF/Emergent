// Iter43-fix24f (2026-06) — Historique des suggestions IA de handlers Liluvine
// Permet de revoir, copier et marquer comme "appliqué" les codes générés par Claude
// via le bouton ✨ de la page Exclamations Reçues.
import React, { useCallback, useEffect, useState } from "react";
import { Sparkles, RefreshCcw, CheckCircle2, Trash2, Copy, X, Filter } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const fmtDate = (s) => {
  if (!s) return "—";
  try { return new Date(s).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return s; }
};

export default function AdminHandlerSuggestions() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterCmd, setFilterCmd] = useState("");
  const [filterApplied, setFilterApplied] = useState(""); // "", "applied", "pending"
  const [viewing, setViewing] = useState(null);
  const [editingNotes, setEditingNotes] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterCmd.trim()) params.set("command", filterCmd.trim().toLowerCase());
      if (filterApplied === "applied") params.set("applied", "true");
      if (filterApplied === "pending") params.set("applied", "false");
      params.set("limit", "200");
      const r = await apiClient.get(`/admin/liluvine-pro/handler-suggestions?${params.toString()}`);
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  }, [filterCmd, filterApplied]);
  useEffect(() => { load(); }, [load]);

  const toggleApplied = async (sugg) => {
    const newState = !sugg.applied;
    try {
      await apiClient.patch(`/admin/liluvine-pro/handler-suggestions/${sugg.id}`, { applied: newState });
      toast.success(newState ? "Marqué comme appliqué" : "Marqué comme en attente");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const saveNotes = async (sugg) => {
    const newNotes = editingNotes[sugg.id];
    if (newNotes === undefined) return;
    try {
      await apiClient.patch(`/admin/liluvine-pro/handler-suggestions/${sugg.id}`, { notes: newNotes });
      toast.success("Notes sauvegardées");
      setEditingNotes((m) => { const c = { ...m }; delete c[sugg.id]; return c; });
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (sugg) => {
    if (!window.confirm(`Supprimer la suggestion pour !${sugg.command} ?`)) return;
    try {
      await apiClient.delete(`/admin/liluvine-pro/handler-suggestions/${sugg.id}`);
      toast.success("Supprimé");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto" data-testid="handler-suggestions-page">
      <header className="flex items-center gap-3 mb-4">
        <Sparkles className="h-6 w-6 text-amber-500" />
        <div>
          <h1 className="text-2xl font-display font-bold">Suggestions Handlers IA</h1>
          <p className="text-xs text-slate-500">
            Historique du code Python généré par Claude Sonnet pour les <code className="px-1 bg-slate-100 rounded">!commandes</code> inconnues.
            Marquez comme "appliqué" une fois le code intégré à <code className="px-1 bg-slate-100 rounded">liluvine_wa_autoreply.py</code>.
          </p>
        </div>
      </header>

      <div className="flex flex-wrap gap-2 mb-3 items-center">
        <div className="relative">
          <Filter className="h-3 w-3 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            placeholder="Filtrer par !commande"
            value={filterCmd}
            onChange={(e) => setFilterCmd(e.target.value)}
            className="pl-7 pr-3 py-1.5 border rounded text-sm"
            data-testid="filter-command"
          />
        </div>
        <select
          value={filterApplied}
          onChange={(e) => setFilterApplied(e.target.value)}
          className="px-2 py-1.5 border rounded text-sm bg-white"
          data-testid="filter-applied"
        >
          <option value="">Tous statuts</option>
          <option value="pending">⏳ En attente</option>
          <option value="applied">✅ Appliqués</option>
        </select>
        <button onClick={load} className="text-xs px-3 py-1.5 rounded bg-white ring-1 ring-slate-300 hover:bg-slate-50">
          <RefreshCcw className="h-3 w-3 inline mr-1" /> Rafraîchir
        </button>
        <span className="text-xs text-slate-500 ml-auto">{items.length} suggestion(s)</span>
      </div>

      <div className="overflow-x-auto bg-white ring-1 ring-slate-200 rounded-lg">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-slate-600 text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-3 py-2">Commande</th>
              <th className="text-left px-3 py-2">Modèle</th>
              <th className="text-right px-3 py-2">Exemples</th>
              <th className="text-left px-3 py-2">Générée le</th>
              <th className="text-left px-3 py-2">Par</th>
              <th className="text-center px-3 py-2">Statut</th>
              <th className="text-left px-3 py-2">Notes</th>
              <th className="text-right px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} className="p-6 text-center text-slate-400">Chargement…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={8} className="p-6 text-center text-slate-400">
                Aucune suggestion. Allez sur <strong>Exclamations Reçues</strong> et cliquez sur ✨ à côté d'une commande inconnue.
              </td></tr>
            )}
            {!loading && items.map((s) => {
              const isEditing = editingNotes[s.id] !== undefined;
              return (
                <tr key={s.id} className="border-t hover:bg-slate-50" data-testid={`sugg-row-${s.id}`}>
                  <td className="px-3 py-2 font-mono">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-50 text-amber-800 ring-1 ring-amber-200 text-xs">
                      !{s.command}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">{(s.model || "").split("-").slice(0, 2).join(" ")}</td>
                  <td className="px-3 py-2 text-right text-xs">{s.samples_count}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{fmtDate(s.generated_at)}</td>
                  <td className="px-3 py-2 text-xs text-slate-600">{s.generated_by || "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <button onClick={() => toggleApplied(s)} className="inline-flex items-center gap-1" data-testid={`toggle-applied-${s.id}`}>
                      {s.applied ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 text-xs">
                          <CheckCircle2 className="h-3 w-3" /> Appliqué
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-50 text-amber-700 text-xs">
                          ⏳ En attente
                        </span>
                      )}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {isEditing ? (
                      <div className="flex gap-1 items-start">
                        <textarea
                          value={editingNotes[s.id]}
                          onChange={(e) => setEditingNotes((m) => ({ ...m, [s.id]: e.target.value }))}
                          rows={2}
                          className="w-48 px-2 py-1 border rounded text-xs"
                          data-testid={`notes-textarea-${s.id}`}
                        />
                        <button onClick={() => saveNotes(s)} className="text-xs px-2 py-1 bg-sawali-blue text-white rounded" data-testid={`notes-save-${s.id}`}>OK</button>
                      </div>
                    ) : (
                      <div onClick={() => setEditingNotes((m) => ({ ...m, [s.id]: s.notes || "" }))}
                           className="cursor-text text-slate-600 min-w-[60px] min-h-[20px]"
                           title="Cliquez pour éditer">
                        {s.notes || <span className="italic text-slate-400">— ajouter une note —</span>}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex gap-1">
                      <button onClick={() => setViewing(s)}
                              className="text-xs px-2 py-1 rounded bg-sawali-blue text-white hover:bg-sawali-blue/90"
                              data-testid={`view-code-${s.id}`}>
                        Voir le code
                      </button>
                      <button onClick={() => remove(s)}
                              className="text-xs px-2 py-1 rounded bg-rose-100 text-rose-700 hover:bg-rose-200"
                              data-testid={`delete-${s.id}`}>
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {viewing && <CodeViewerModal sugg={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

function CodeViewerModal({ sugg, onClose }) {
  const copy = () => {
    navigator.clipboard.writeText(sugg.generated_code || "");
    toast.success("Code copié");
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" data-testid="code-viewer-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="px-5 py-3 border-b bg-slate-50 flex items-center justify-between">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-500" />
            Code pour <code className="px-1 bg-slate-200 rounded">!{sugg.command}</code>
            <span className="text-xs text-slate-500 ml-2">généré le {fmtDate(sugg.generated_at)}</span>
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-5">
          <pre className="bg-slate-900 text-slate-100 text-xs rounded-lg p-4 overflow-auto whitespace-pre-wrap font-mono leading-relaxed">
            {sugg.generated_code || "(pas de code)"}
          </pre>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">Fermer</button>
          <button onClick={copy} className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 inline-flex items-center gap-1">
            <Copy className="h-3 w-3" /> Copier
          </button>
        </div>
      </div>
    </div>
  );
}
