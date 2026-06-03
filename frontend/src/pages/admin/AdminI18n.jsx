// S046 (2026-02) — Admin i18n translations table.
// Allows admin/superviseur to manage the i18n_translations collection
// with inline edits, add/delete rows, and bulk save.
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Save, RefreshCw, Search, Languages, Loader2, FileText } from "lucide-react";

const BLANK_ROW = { key: "", fr: "", en: "", ar: "", lg1: "", lg2: "", context: "" };

export default function AdminI18n() {
  const [items, setItems] = useState([]);
  const [languages, setLanguages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(null); // row being edited
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/i18n/translations");
      setItems(r.data?.items || []);
      setLanguages(r.data?.languages || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => {
    if (!filter.trim()) return items;
    const q = filter.toLowerCase();
    return items.filter((it) =>
      (it.key || "").toLowerCase().includes(q) ||
      (it.fr || "").toLowerCase().includes(q) ||
      (it.en || "").toLowerCase().includes(q) ||
      (it.context || "").toLowerCase().includes(q)
    );
  }, [items, filter]);

  const save = async (row) => {
    if (!row.key?.trim() || !row.fr?.trim()) {
      toast.error("Clé et version FR sont requises");
      return;
    }
    setSaving(true);
    try {
      await apiClient.post("/admin/i18n/translations", row);
      toast.success(`Clé ${row.key} enregistrée`);
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const removeRow = async (key) => {
    if (!window.confirm(`Supprimer la traduction « ${key} » ? Cette action est irréversible.`)) return;
    try {
      await apiClient.delete(`/admin/i18n/translations/${key}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="space-y-4 p-4" data-testid="admin-i18n-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Languages className="h-6 w-6 text-sawali-blue" /> Traductions (i18n)
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            La colonne <strong>FR</strong> est la source. Les autres langues servent de remplacement —
            si vide, le texte FR s'affiche par défaut. <strong>LG1 = Gulmancema</strong>, <strong>LG2 = Mooré</strong>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 px-3 py-1.5 text-xs"
            data-testid="i18n-refresh"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          <button
            onClick={() => setEditing({ ...BLANK_ROW })}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-3 py-1.5 text-xs"
            data-testid="i18n-add"
          >
            <Plus className="h-3.5 w-3.5" /> Nouvelle clé
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-md">
          <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-2" />
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filtrer par clé, FR, EN, contexte…"
            className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-300 focus:ring-sawali-blue focus:outline-none"
            data-testid="i18n-filter"
          />
        </div>
        <span className="text-[11px] text-slate-500">
          {filtered.length}/{items.length} clé{filtered.length > 1 ? "s" : ""}
        </span>
      </div>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-xs min-w-[1200px]" data-testid="i18n-table">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="px-2 py-2 text-left w-[200px]">Clé</th>
              <th className="px-2 py-2 text-left">FR <span className="text-rose-500">*</span></th>
              <th className="px-2 py-2 text-left">EN</th>
              <th className="px-2 py-2 text-left">AR</th>
              <th className="px-2 py-2 text-left">LG1</th>
              <th className="px-2 py-2 text-left">LG2</th>
              <th className="px-2 py-2 text-left w-[140px]">Contexte</th>
              <th className="px-2 py-2 text-right w-[80px]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-400 italic">Chargement…</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-slate-400 italic">Aucune traduction.</td></tr>
            ) : filtered.map((row) => {
              const isEditing = editing && editing.key === row.key;
              const edit = isEditing ? editing : row;
              return (
                <tr key={row.key} className={`border-t border-slate-100 ${isEditing ? "bg-amber-50/50" : "hover:bg-slate-50"}`} data-testid={`i18n-row-${row.key}`}>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-slate-700 truncate max-w-[200px]" title={row.key}>{row.key}</td>
                  {["fr", "en", "ar", "lg1", "lg2", "context"].map((field) => (
                    <td key={field} className="px-1 py-1">
                      {isEditing ? (
                        <textarea
                          value={edit[field] || ""}
                          onChange={(e) => setEditing({ ...editing, [field]: e.target.value })}
                          rows={2}
                          className={`w-full rounded ring-1 ring-slate-300 px-1.5 py-1 text-xs focus:ring-sawali-blue focus:outline-none ${field === "ar" ? "text-right" : ""}`}
                          dir={field === "ar" ? "rtl" : "ltr"}
                          data-testid={`i18n-input-${row.key}-${field}`}
                        />
                      ) : (
                        <div
                          className={`truncate max-w-[200px] ${field === "ar" ? "text-right" : ""} ${(!row[field] && field !== "fr" && field !== "context") ? "text-slate-300 italic" : "text-slate-700"}`}
                          dir={field === "ar" ? "rtl" : "ltr"}
                          title={row[field] || (field !== "fr" ? "(vide — fallback FR)" : "")}
                        >
                          {row[field] || (field !== "fr" && field !== "context" ? "—" : "")}
                        </div>
                      )}
                    </td>
                  ))}
                  <td className="px-1 py-1 text-right">
                    <div className="inline-flex items-center gap-1">
                      {isEditing ? (
                        <>
                          <button
                            onClick={() => save(editing)}
                            disabled={saving}
                            className="text-[10px] rounded bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-0.5"
                            data-testid={`i18n-save-${row.key}`}
                          >
                            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
                          </button>
                          <button
                            onClick={() => setEditing(null)}
                            className="text-[10px] rounded ring-1 ring-slate-300 px-2 py-0.5 text-slate-600"
                          >
                            ✕
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => setEditing({ ...row })}
                            className="text-slate-500 hover:text-sawali-blue"
                            title="Éditer"
                            data-testid={`i18n-edit-${row.key}`}
                          >
                            <FileText className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => removeRow(row.key)}
                            className="text-slate-500 hover:text-rose-600"
                            title="Supprimer"
                            data-testid={`i18n-del-${row.key}`}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}

            {/* New row when adding */}
            {editing && !editing.key && (
              <tr className="border-t border-slate-100 bg-emerald-50/50">
                <td className="px-1 py-1">
                  <input
                    value={editing.key || ""}
                    onChange={(e) => setEditing({ ...editing, key: e.target.value })}
                    placeholder="nav.exemple"
                    className="w-full rounded ring-1 ring-slate-300 px-1.5 py-1 text-xs font-mono"
                    data-testid="i18n-new-key"
                  />
                </td>
                {["fr", "en", "ar", "lg1", "lg2", "context"].map((field) => (
                  <td key={field} className="px-1 py-1">
                    <textarea
                      value={editing[field] || ""}
                      onChange={(e) => setEditing({ ...editing, [field]: e.target.value })}
                      rows={2}
                      className={`w-full rounded ring-1 ring-slate-300 px-1.5 py-1 text-xs ${field === "ar" ? "text-right" : ""}`}
                      dir={field === "ar" ? "rtl" : "ltr"}
                      data-testid={`i18n-new-${field}`}
                    />
                  </td>
                ))}
                <td className="px-1 py-1 text-right">
                  <div className="inline-flex items-center gap-1">
                    <button
                      onClick={() => save(editing)}
                      disabled={saving}
                      className="text-[10px] rounded bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-0.5 inline-flex items-center gap-1"
                      data-testid="i18n-new-save"
                    >
                      {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                      Save
                    </button>
                    <button
                      onClick={() => setEditing(null)}
                      className="text-[10px] rounded ring-1 ring-slate-300 px-2 py-0.5 text-slate-600"
                    >
                      ✕
                    </button>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-[10px] text-slate-400">
        💡 Astuce : les langues vides retombent automatiquement sur le FR à l'affichage. Pour
        LG1 (Gulmancema) et LG2 (Mooré), remplissez ligne par ligne au rythme de la traduction
        manuelle. La sélection de langue est immédiate après enregistrement.
      </p>
    </div>
  );
}
