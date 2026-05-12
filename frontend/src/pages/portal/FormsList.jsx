import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { FileText, Plus, Edit, Trash2, Copy, Globe, Lock, PlayCircle, Download, Share2, BarChart3 } from "lucide-react";
import ShareFormModal from "@/components/ShareFormModal";

// Form catalogue : user's forms + public forms from other clients
export default function FormsList() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("mine");
  const [shareForm, setShareForm] = useState(null);
  // Iter34t — Modal-based "Nouveau formulaire" flow with title validation
  // and autocomplete suggestions (existing titles for the same client scope).
  const [createOpen, setCreateOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try { const r = await apiClient.get("/me/forms"); setItems(r.data || []); }
    catch { /* noop */ }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openCreate = async () => {
    setNewTitle("");
    setCreateOpen(true);
    try {
      const r = await apiClient.get("/me/forms/title-suggestions");
      setSuggestions(r.data?.items || []);
    } catch { setSuggestions([]); }
  };

  const titleConflict = (() => {
    const norm = newTitle.trim().toLowerCase();
    if (!norm) return null;
    return suggestions.find((s) => (s.title || "").trim().toLowerCase() === norm) || null;
  })();

  const filtered = items.filter((f) => {
    if (filter === "mine") return f.is_mine;
    if (filter === "public") return !f.is_mine && f.is_public;
    return true;
  });

  const create = async () => {
    const t = newTitle.trim();
    if (!t) { toast.error("Saisissez un titre"); return; }
    if (titleConflict) { toast.error(`« ${titleConflict.title} » existe déjà (${titleConflict.number})`); return; }
    setCreating(true);
    try {
      const r = await apiClient.post("/me/forms", { title: t, is_public: false });
      toast.success(`Formulaire ${r.data.number} créé`);
      setCreateOpen(false);
      navigate(`/portal/forms/${r.data.id}/edit`);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setCreating(false); }
  };

  const imp = async (id) => {
    try { const r = await apiClient.post(`/me/forms/${id}/import`); toast.success(`Importé sous ${r.data.number}`); await load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const del = async (id) => {
    if (!window.confirm("Supprimer ce formulaire et toutes ses saisies ?")) return;
    try { await apiClient.delete(`/me/forms/${id}`); toast.success("Supprimé"); await load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div className="max-w-6xl space-y-6" data-testid="forms-list-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Formulaires</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <FileText className="h-5 w-5 text-sawali-blue" /> Bibliothèque de formulaires
          </h1>
        </div>
        <button
          onClick={openCreate}
          disabled={creating}
          className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50"
          data-testid="form-create-btn"
        >
          <Plus className="h-4 w-4" /> Nouveau formulaire
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <Link
          to="/portal/forms/analytics"
          className="inline-flex items-center gap-2 rounded-lg border border-sawali-blue/30 bg-sawali-blue/5 text-sawali-blue px-3 py-1.5 text-xs hover:bg-sawali-blue hover:text-white transition"
          data-testid="forms-global-analytics-btn"
        >
          <BarChart3 className="h-3.5 w-3.5" /> Analytics global
        </Link>
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        {[["mine", "Mes formulaires"], ["public", "Formulaires publics"], ["all", "Tous"]].map(([k, l]) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`px-3 py-2 text-sm border-b-2 transition ${filter === k ? "border-sawali-blue text-sawali-blue font-semibold" : "border-transparent text-slate-500 hover:text-slate-900"}`}
            data-testid={`form-filter-${k}`}
          >{l}</button>
        ))}
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center text-slate-400 py-10 italic text-sm">Aucun formulaire.</div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="forms-grid">
          {filtered.map((f) => (
            <div key={f.id} className="rounded-xl border border-slate-200 bg-white p-4 flex flex-col" data-testid={`form-card-${f.id}`}>
              <div className="flex items-start justify-between gap-2 mb-2">
                <code className="text-[10px] font-mono bg-slate-100 px-1.5 py-0.5 rounded">{f.number}</code>
                <span className={`text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full ${f.is_public ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                  {f.is_public ? <><Globe className="h-3 w-3" /> Public</> : <><Lock className="h-3 w-3" /> Privé</>}
                </span>
              </div>
              <h3 className="text-sm font-display font-bold mb-1 line-clamp-2">{f.title}</h3>
              <p className="text-[11px] text-slate-500 line-clamp-2 mb-2">{f.description || "—"}</p>
              <p className="text-[10px] text-slate-400 mb-3">
                {f.uses_count} utilisation(s) · {new Date(f.updated_at || f.created_at).toLocaleDateString("fr-FR")}
                <br />Par <strong>{f.created_by_label}</strong>
              </p>
              <div className="mt-auto flex gap-1 flex-wrap">
                <Link to={`/portal/forms/${f.id}/fill`} className="inline-flex items-center gap-1 text-[11px] rounded bg-sawali-blue text-white px-2.5 py-1.5 hover:bg-sawali-blue-light" data-testid={`form-fill-${f.id}`}>
                  <PlayCircle className="h-3.5 w-3.5" /> Remplir
                </Link>
                {f.is_mine ? (
                  <>
                    <Link to={`/portal/forms/${f.id}/edit`} className="inline-flex items-center gap-1 text-[11px] rounded bg-slate-900 text-white px-2.5 py-1.5 hover:bg-slate-800"><Edit className="h-3.5 w-3.5" /> Éditer</Link>
                    <Link to={`/portal/forms/${f.id}/analytics`} className="inline-flex items-center gap-1 text-[11px] rounded bg-indigo-600 text-white px-2.5 py-1.5 hover:bg-indigo-700" data-testid={`form-analytics-${f.id}`} title="Analytics du formulaire"><BarChart3 className="h-3.5 w-3.5" /> Stats</Link>
                    {f.is_public && (
                      <button onClick={() => setShareForm(f)} className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2.5 py-1.5 hover:bg-emerald-700" data-testid={`form-share-${f.id}`} title="Partager publiquement"><Share2 className="h-3.5 w-3.5" /> Partager</button>
                    )}
                    <button onClick={() => del(f.id)} className="inline-flex items-center gap-1 text-[11px] rounded bg-rose-500 text-white px-2.5 py-1.5 hover:bg-rose-600" data-testid={`form-delete-${f.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
                  </>
                ) : (
                  <button onClick={() => imp(f.id)} className="inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2.5 py-1.5 hover:bg-emerald-700" data-testid={`form-import-${f.id}`}><Copy className="h-3.5 w-3.5" /> Importer</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {shareForm && <ShareFormModal form={shareForm} onClose={() => setShareForm(null)} />}

      {createOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4" onClick={() => !creating && setCreateOpen(false)} data-testid="form-create-modal">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 space-y-4" onClick={(e) => e.stopPropagation()}>
            <h2 className="font-display font-bold text-lg flex items-center gap-2">
              <FileText className="h-5 w-5 text-sawali-blue" /> Nouveau formulaire
            </h2>
            <p className="text-xs text-slate-600">
              Saisissez un titre unique pour ce formulaire. Les titres existants pour votre compte sont proposés ci-dessous — choisissez un nom différent pour éviter les doublons.
            </p>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Titre du formulaire</label>
              <input
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="Ex: Fiche d'admission patient"
                className={`w-full rounded-lg border px-3 py-2 text-sm ${titleConflict ? "border-rose-400 ring-2 ring-rose-200" : "border-slate-300 focus:border-sawali-blue"}`}
                list="form-title-suggestions"
                autoFocus
                data-testid="form-new-title-input"
              />
              <datalist id="form-title-suggestions">
                {suggestions.map((s) => <option key={s.number} value={s.title}>{s.number}</option>)}
              </datalist>
              {titleConflict && (
                <p className="mt-1 text-xs text-rose-600 flex items-center gap-1" data-testid="form-title-conflict">
                  ⚠️ Un formulaire portant ce titre existe déjà : <strong>{titleConflict.number}</strong>
                </p>
              )}
              {!titleConflict && suggestions.length > 0 && (
                <p className="mt-1 text-[10px] text-slate-400">{suggestions.length} titre(s) existant(s) — saisissez quelques lettres pour voir les suggestions</p>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={() => setCreateOpen(false)}
                disabled={creating}
                className="px-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-300 hover:bg-slate-50"
                data-testid="form-create-cancel"
              >Annuler</button>
              <button
                onClick={create}
                disabled={creating || !newTitle.trim() || !!titleConflict}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 text-sm font-semibold rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue-light disabled:opacity-50"
                data-testid="form-create-confirm"
              >
                <Plus className="h-3.5 w-3.5" /> Créer
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
