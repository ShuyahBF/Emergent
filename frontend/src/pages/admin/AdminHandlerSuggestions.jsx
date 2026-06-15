// Iter43-fix24f (2026-06) — Historique des suggestions IA de handlers Liluvine
// Permet de revoir, copier et marquer comme "appliqué" les codes générés par Claude
// via le bouton ✨ de la page Exclamations Reçues.
import React, { useCallback, useEffect, useState } from "react";
import { Sparkles, RefreshCcw, CheckCircle2, Trash2, Copy, X, Filter, Play, Loader2 } from "lucide-react";
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

  // Iter43-fix24g — Dry-run sandbox : exécute la fonction _build_<cmd>_reply générée
  // sans avoir à modifier liluvine_wa_autoreply.py.
  const [dryRunArgs, setDryRunArgs] = useState("");
  const [dryRunResult, setDryRunResult] = useState(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [dryRunOpen, setDryRunOpen] = useState(false);

  const runDryRun = async () => {
    setDryRunLoading(true);
    setDryRunResult(null);
    try {
      const r = await apiClient.post(
        `/admin/liluvine-pro/handler-suggestions/${sugg.id}/dry-run`,
        { args: dryRunArgs, timeout_ms: 5000 }
      );
      setDryRunResult(r.data);
      if (r.data?.ok) {
        toast.success(`Handler exécuté en ${r.data.duration_ms} ms`);
      } else {
        toast.error("Échec — voir détails");
      }
    } catch (e) {
      const msg = e?.response?.data?.detail || "Erreur dry-run";
      setDryRunResult({ ok: false, error: msg, reply: null, duration_ms: null });
      toast.error(msg);
    } finally {
      setDryRunLoading(false);
    }
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
          <button onClick={onClose} className="text-slate-500 hover:text-slate-700" data-testid="code-viewer-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-5 space-y-3">
          <pre className="bg-slate-900 text-slate-100 text-xs rounded-lg p-4 overflow-auto whitespace-pre-wrap font-mono leading-relaxed">
            {sugg.generated_code || "(pas de code)"}
          </pre>

          {/* Dry-run panel */}
          <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50/40">
            <button
              onClick={() => setDryRunOpen((v) => !v)}
              className="w-full px-4 py-2 flex items-center justify-between text-left text-sm font-semibold text-emerald-800 hover:bg-emerald-50"
              data-testid="dry-run-toggle"
            >
              <span className="inline-flex items-center gap-2">
                <Play className="h-4 w-4" /> Tester ce handler en dry-run (sandbox)
              </span>
              <span className="text-xs text-emerald-700">{dryRunOpen ? "▴" : "▾"}</span>
            </button>
            {dryRunOpen && (
              <div className="px-4 pb-4 space-y-3" data-testid="dry-run-panel">
                <p className="text-[11px] text-emerald-900/80 leading-relaxed">
                  Exécute <code className="px-1 bg-white rounded ring-1 ring-emerald-200">_build_{sugg.command}_reply(db, args)</code> dans un
                  sandbox restreint (imports limités, builtins minimaux, timeout 5 s).
                  Les <strong>écritures MongoDB</strong> sont possibles — restez vigilant·e si le code généré contient des <code className="px-1 bg-white rounded ring-1 ring-emerald-200">insert/update/delete</code>.
                </p>
                <label className="block text-[10px] uppercase tracking-wider font-semibold text-emerald-900">
                  Arguments (chaîne, ex. "Ouaga")
                  <input
                    type="text"
                    value={dryRunArgs}
                    onChange={(e) => setDryRunArgs(e.target.value)}
                    placeholder="(vide = aucun argument)"
                    className="mt-1 w-full px-2 py-1.5 rounded border border-emerald-300 text-sm font-mono bg-white focus:ring-2 focus:ring-emerald-400 outline-none"
                    data-testid="dry-run-args-input"
                  />
                </label>
                <button
                  onClick={runDryRun}
                  disabled={dryRunLoading}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-1.5"
                  data-testid="dry-run-execute-btn"
                >
                  {dryRunLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  {dryRunLoading ? "Exécution…" : "Exécuter le dry-run"}
                </button>
                {dryRunResult && (
                  <div
                    className={`rounded-lg p-3 ring-1 text-xs ${
                      dryRunResult.ok
                        ? "bg-white ring-emerald-200"
                        : "bg-rose-50 ring-rose-200"
                    }`}
                    data-testid="dry-run-result"
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className={`font-semibold ${dryRunResult.ok ? "text-emerald-700" : "text-rose-700"}`}>
                        {dryRunResult.ok ? "✅ Réussi" : "❌ Échec"}
                      </span>
                      {dryRunResult.duration_ms != null && (
                        <span className="text-[10px] text-slate-500">{dryRunResult.duration_ms} ms</span>
                      )}
                    </div>
                    {dryRunResult.ok ? (
                      <div>
                        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
                          Réponse renvoyée par <code>_build_{sugg.command}_reply</code> :
                        </p>
                        <pre className="bg-slate-50 ring-1 ring-slate-200 rounded p-2 whitespace-pre-wrap font-mono text-slate-800" data-testid="dry-run-reply">
                          {dryRunResult.reply || "(réponse vide)"}
                        </pre>
                      </div>
                    ) : (
                      <pre className="text-rose-800 whitespace-pre-wrap font-mono" data-testid="dry-run-error">
                        {dryRunResult.error}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700">Fermer</button>
          <button onClick={copy} className="px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 inline-flex items-center gap-1" data-testid="code-viewer-copy">
            <Copy className="h-3 w-3" /> Copier
          </button>
        </div>
      </div>
    </div>
  );
}
