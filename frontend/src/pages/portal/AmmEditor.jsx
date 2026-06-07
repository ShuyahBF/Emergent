// Iter41 Phase 2 (2026-02) — AMM Editor pour les utilisateurs avec rôle régulateur
// (ou admin / superviseur). Permet de saisir et tenir à jour les numéros d'AMM
// (Autorisation de Mise sur le Marché) qui complètent les fiches VIDAL.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import {
  ScrollText, Loader2, Plus, Search, Edit3, Trash2, X, Save, Upload, ArrowUpDown
} from "lucide-react";

const STATUSES = [
  { value: "active", label: "Active", cls: "bg-emerald-100 text-emerald-700" },
  { value: "withdrawn", label: "Retirée", cls: "bg-slate-100 text-slate-600" },
  { value: "suspended", label: "Suspendue", cls: "bg-amber-100 text-amber-800" },
];

const EMPTY = {
  vidal_product_id: "",
  product_name: "",
  amm_number: "",
  country_code: "",
  laboratory: "",
  galenic_form: "",
  atc_class: "",
  status: "active",
  granted_at: "",
  expires_at: "",
  notes: "",
  cip1: "", cip2: "", cip3: "", cip4: "", cip5: "",
};

function StatusBadge({ status }) {
  const cfg = STATUSES.find((s) => s.value === status) || STATUSES[0];
  return <span className={`text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full ${cfg.cls}`}>{cfg.label}</span>;
}

function AmmEditor({ initial, onClose, onSaved }) {
  const isEdit = !!initial?.id;
  const [form, setForm] = useState({ ...EMPTY, ...(initial || {}) });
  const [saving, setSaving] = useState(false);

  const upd = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    // Iter42b — amm_number et cip1 peuvent être NULL (autorité ou pays sans AMM
    // officiel). Seul product_name reste requis.
    if (!form.product_name?.trim()) {
      toast.warning("Nom du produit requis");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        vidal_product_id: form.vidal_product_id ? parseInt(form.vidal_product_id) : null,
        country_code: (form.country_code || "").toUpperCase().slice(0, 2) || null,
      };
      let res;
      if (isEdit) {
        res = await apiClient.put(`/amm/${initial.id}`, payload);
      } else {
        res = await apiClient.post("/amm", payload);
      }
      toast.success(isEdit ? "AMM mise à jour" : "AMM créée");
      onSaved(res.data.amm);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setSaving(false), 0);
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" data-testid="amm-editor-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-100 px-4 py-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-800 inline-flex items-center gap-2">
            <ScrollText className="h-4 w-4 text-rose-600" />
            {isEdit ? "Modifier l'AMM" : "Nouvelle AMM"}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4 grid sm:grid-cols-2 gap-3">
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Nom du produit *</span>
            <input value={form.product_name || ""} onChange={(e) => upd("product_name", e.target.value)}
                   placeholder="ex: Doliprane 1000mg"
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-name" />
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Numéro AMM</span>
            <input value={form.amm_number || ""} onChange={(e) => upd("amm_number", e.target.value)}
                   placeholder="ex: 3400930471722 (optionnel)"
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="amm-form-number" />
            <p className="text-[10px] text-slate-400 mt-0.5">Optionnel — un numéro interne sera autogénéré sinon.</p>
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Code pays (ISO-2)</span>
            <input value={form.country_code || ""} onChange={(e) => upd("country_code", e.target.value.toUpperCase().slice(0, 2))}
                   placeholder="ex: BF, CI, FR, SN" maxLength={2}
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="amm-form-country" />
            <p className="text-[10px] text-slate-400 mt-0.5">Pays de l&apos;autorité ayant délivré l&apos;AMM. Pré-rempli depuis Admin Settings.</p>
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">ID VIDAL (optionnel)</span>
            <input type="number" value={form.vidal_product_id || ""} onChange={(e) => upd("vidal_product_id", e.target.value)}
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="amm-form-vidal-id" />
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Laboratoire</span>
            <input value={form.laboratory || ""} onChange={(e) => upd("laboratory", e.target.value)}
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-lab" />
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Forme galénique</span>
            <input value={form.galenic_form || ""} onChange={(e) => upd("galenic_form", e.target.value)}
                   placeholder="comprimé, sirop, injection…"
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-galenic" />
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Classe ATC</span>
            <input value={form.atc_class || ""} onChange={(e) => upd("atc_class", e.target.value)}
                   placeholder="N02BE01"
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="amm-form-atc" />
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Statut</span>
            <select value={form.status || "active"} onChange={(e) => upd("status", e.target.value)}
                    className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-status">
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Date d&apos;octroi</span>
            <input type="date" value={form.granted_at || ""} onChange={(e) => upd("granted_at", e.target.value)}
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-granted" />
          </label>
          <label className="block text-xs">
            <span className="block text-slate-600 mb-1">Expiration</span>
            <input type="date" value={form.expires_at || ""} onChange={(e) => upd("expires_at", e.target.value)}
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-expires" />
          </label>
          <label className="block text-xs sm:col-span-2">
            <span className="block text-slate-600 mb-1">Notes</span>
            <textarea value={form.notes || ""} onChange={(e) => upd("notes", e.target.value)} rows={3}
                      className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300" data-testid="amm-form-notes" />
          </label>
          <fieldset className="sm:col-span-2 ring-1 ring-slate-200 rounded p-3 bg-slate-50">
            <legend className="text-[10px] uppercase tracking-wider text-slate-500 px-1">Codes CIP (selon laboratoire / distributeur)</legend>
            <div className="grid sm:grid-cols-5 gap-2 mt-1">
              {[1,2,3,4,5].map((n) => (
                <label key={n} className="block text-xs">
                  <span className="block text-slate-600 mb-1">CIP{n}</span>
                  <input value={form[`cip${n}`] || ""} onChange={(e) => upd(`cip${n}`, e.target.value)}
                         placeholder="ex: 3400930471722"
                         className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                         data-testid={`amm-form-cip${n}`} />
                </label>
              ))}
            </div>
          </fieldset>
        </div>
        <div className="sticky bottom-0 bg-white border-t border-slate-100 px-4 py-3 flex justify-end gap-2">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
          <button onClick={save} disabled={saving}
                  className="text-xs px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-1 disabled:opacity-60"
                  data-testid="amm-form-save">
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AmmEditorPage() {
  const { user } = useAuth();
  // Iter42b — editeur_vidal a un accès LECTURE SEULE (recherche/filtre/tri).
  const canEdit = user && ["admin", "superviseur", "regulateur"].includes(user.role);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [importOpen, setImportOpen] = useState(false);
  // Iter42b — tri côté client (utile pour le rôle editeur_vidal)
  const [sortKey, setSortKey] = useState("created_at");
  const [sortDir, setSortDir] = useState("desc");

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (status) params.set("status", status);
      const r = await apiClient.get(`/amm?${params}`);
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  useEffect(() => { load(); }, []);

  const remove = async (amm) => {
    if (!window.confirm(`Supprimer l'AMM ${amm.amm_number} ?`)) return;
    try {
      await apiClient.delete(`/amm/${amm.id}`);
      toast.success("Supprimée");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="portal-amm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-800 inline-flex items-center gap-2">
          <ScrollText className="h-6 w-6 text-rose-600" />
          Numéros AMM
        </h1>
        {canEdit && (
          <div className="flex items-center gap-2">
            <button onClick={() => setImportOpen(true)}
                    className="text-sm px-3 py-2 rounded ring-1 ring-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 inline-flex items-center gap-2"
                    data-testid="amm-import-csv-btn">
              <Upload className="h-4 w-4" /> Importer CSV
            </button>
            <button onClick={() => { setEditing(null); setEditorOpen(true); }}
                    className="text-sm px-3 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-2"
                    data-testid="amm-new-btn">
              <Plus className="h-4 w-4" /> Nouvelle AMM
            </button>
          </div>
        )}
      </div>

      <p className="text-xs text-slate-600">
        Table des Autorisations de Mise sur le Marché tenue à jour par le régulateur SAWALI. Ces données complètent les fiches VIDAL (consultables sous <code>/portal/vidal</code>).
        {!canEdit && <em> Vous êtes en lecture seule (rôle <code>{user?.role}</code>).</em>}
      </p>

      <div className="flex flex-wrap items-end gap-2 ring-1 ring-slate-200 bg-white rounded-lg p-3">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-slate-600 mb-1">Recherche</label>
          <input type="text" value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && load()}
                 placeholder="nom, numéro AMM, laboratoire…"
                 className="w-full text-sm px-3 py-2 rounded ring-1 ring-slate-300"
                 data-testid="amm-search-input" />
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">Statut</label>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
                  className="text-sm px-3 py-2 rounded ring-1 ring-slate-300"
                  data-testid="amm-status-filter">
            <option value="">Tous</option>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </div>
        <button onClick={load} className="text-sm px-3 py-2 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1" data-testid="amm-search-btn">
          <Search className="h-4 w-4" /> Filtrer
        </button>
      </div>

      <div className="ring-1 ring-slate-200 rounded-lg bg-white overflow-hidden">
        {loading ? (
          <div className="p-6 text-sm text-slate-500 flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        ) : items.length === 0 ? (
          <div className="p-6 text-sm text-slate-500 italic text-center" data-testid="amm-empty-state">
            Aucune AMM enregistrée pour le moment.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>
                <SortableTh label="Produit" k="product_name" sortKey={sortKey} sortDir={sortDir} onSort={(k) => toggleSort(k, sortKey, sortDir, setSortKey, setSortDir)} />
                <SortableTh label="AMM" k="amm_number" sortKey={sortKey} sortDir={sortDir} onSort={(k) => toggleSort(k, sortKey, sortDir, setSortKey, setSortDir)} />
                <SortableTh label="Pays" k="country_code" sortKey={sortKey} sortDir={sortDir} onSort={(k) => toggleSort(k, sortKey, sortDir, setSortKey, setSortDir)} />
                <SortableTh label="Laboratoire" k="laboratory" sortKey={sortKey} sortDir={sortDir} onSort={(k) => toggleSort(k, sortKey, sortDir, setSortKey, setSortDir)} />
                <SortableTh label="Statut" k="status" sortKey={sortKey} sortDir={sortDir} onSort={(k) => toggleSort(k, sortKey, sortDir, setSortKey, setSortDir)} />
                <SortableTh label="Expiration" k="expires_at" sortKey={sortKey} sortDir={sortDir} onSort={(k) => toggleSort(k, sortKey, sortDir, setSortKey, setSortDir)} />
                {canEdit && <th></th>}
              </tr>
            </thead>
            <tbody>
              {sortItems(items, sortKey, sortDir).map((it) => (
                <tr key={it.id} className="border-t border-slate-100 hover:bg-rose-50/30" data-testid={`amm-row-${it.id}`}>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-slate-800">{it.product_name}</div>
                    {it.vidal_product_id && <div className="text-[10px] text-slate-500 font-mono">VIDAL #{it.vidal_product_id}</div>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{it.amm_number || <span className="text-slate-400">—</span>}</td>
                  <td className="px-3 py-2 text-xs">
                    {it.country_code ? (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200 font-mono">{it.country_code}</span>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-3 py-2 text-xs">{it.laboratory || "—"}</td>
                  <td className="px-3 py-2"><StatusBadge status={it.status} /></td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {it.expires_at || "—"}
                  </td>
                  {canEdit && (
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button onClick={() => { setEditing(it); setEditorOpen(true); }} className="text-slate-500 hover:text-rose-600 p-1" data-testid={`amm-edit-${it.id}`}>
                        <Edit3 className="h-4 w-4" />
                      </button>
                      <button onClick={() => remove(it)} className="text-slate-500 hover:text-rose-600 p-1 ml-1" data-testid={`amm-delete-${it.id}`}>
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editorOpen && (
        <AmmEditor
          initial={editing}
          onClose={() => { setEditorOpen(false); setEditing(null); }}
          onSaved={() => { setEditorOpen(false); setEditing(null); load(); }}
        />
      )}
      {importOpen && (
        <CsvImportModal
          onClose={() => setImportOpen(false)}
          onDone={() => { setImportOpen(false); load(); }}
        />
      )}
    </div>
  );
}

// ----- Iter42b — helpers tri + CSV import ---------------------------------
function toggleSort(k, currentKey, currentDir, setKey, setDir) {
  if (k === currentKey) {
    setDir(currentDir === "asc" ? "desc" : "asc");
  } else {
    setKey(k); setDir("asc");
  }
}
function sortItems(arr, key, dir) {
  const mult = dir === "asc" ? 1 : -1;
  return [...arr].sort((a, b) => {
    const av = (a?.[key] ?? "").toString().toLowerCase();
    const bv = (b?.[key] ?? "").toString().toLowerCase();
    if (av < bv) return -1 * mult;
    if (av > bv) return 1 * mult;
    return 0;
  });
}
function SortableTh({ label, k, sortKey, sortDir, onSort }) {
  const active = k === sortKey;
  return (
    <th className="text-left px-3 py-2 select-none">
      <button onClick={() => onSort(k)} className={`inline-flex items-center gap-1 ${active ? "text-rose-700 font-semibold" : "hover:text-slate-900"}`} data-testid={`amm-sort-${k}`}>
        {label} <ArrowUpDown className={`h-3 w-3 ${active ? "" : "opacity-40"}`} />
        {active && <span className="text-[10px]">{sortDir === "asc" ? "▲" : "▼"}</span>}
      </button>
    </th>
  );
}

function CsvImportModal({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [conflicts, setConflicts] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setResult(null); setConflicts(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await apiClient.post("/amm/import-csv", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(r.data);
      toast.success(`${r.data.imported} ligne(s) importée(s)`);
      setTimeout(() => onDone(), 1500);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (detail && typeof detail === "object" && (detail.intra_file_conflicts || detail.database_conflicts)) {
        setConflicts(detail);
        toast.error("Import refusé — conflits détectés");
      } else {
        toast.error(typeof detail === "string" ? detail : "Erreur import");
      }
    }
    setTimeout(() => setBusy(false), 0);
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" data-testid="amm-import-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold text-slate-800 inline-flex items-center gap-2">
            <Upload className="h-4 w-4 text-rose-600" /> Importer un fichier CSV
          </h2>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="amm-import-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3 text-sm">
          <div className="bg-slate-50 ring-1 ring-slate-200 rounded p-3 text-xs text-slate-700">
            <p className="font-medium">Format attendu (1ère ligne = en-têtes, séparateur , ou ; ) :</p>
            <pre className="mt-1 bg-white border rounded p-2 text-[11px] overflow-x-auto">Nom du produit, AMM, CIP1, date expiration, Laboratoire, Note</pre>
            <ul className="mt-2 list-disc list-inside space-y-0.5 text-[11px] text-slate-600">
              <li>AMM et CIP1 peuvent être vides (un numéro interne sera autogénéré)</li>
              <li>En cas de doublons (DB ou intra-fichier), l&apos;import est <strong>refusé en totalité</strong></li>
              <li>Taille max : 5 Mo</li>
            </ul>
          </div>
          <label className="block">
            <span className="block text-xs text-slate-600 mb-1">Fichier CSV</span>
            <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] || null)}
                   className="block w-full text-sm" data-testid="amm-import-file" />
          </label>
          {result && (
            <div className="bg-emerald-50 ring-1 ring-emerald-200 rounded p-3 text-xs text-emerald-800" data-testid="amm-import-result">
              ✅ {result.imported} ligne(s) importée(s) avec succès. {result.skipped_empty > 0 && `(${result.skipped_empty} lignes vides ignorées)`}
            </div>
          )}
          {conflicts && (
            <div className="bg-rose-50 ring-1 ring-rose-200 rounded p-3 text-xs text-rose-800 space-y-2" data-testid="amm-import-conflicts">
              <p className="font-semibold">{conflicts.message}</p>
              {conflicts.intra_file_conflicts?.length > 0 && (
                <div>
                  <p className="font-medium">Conflits dans le fichier ({conflicts.intra_file_conflicts.length}) :</p>
                  <ul className="list-disc list-inside ml-2 mt-0.5">
                    {conflicts.intra_file_conflicts.slice(0, 20).map((c, i) => (
                      <li key={i}>Ligne {c.line} — {c.field} « {c.value} » → {c.conflict_with}</li>
                    ))}
                  </ul>
                </div>
              )}
              {conflicts.database_conflicts?.length > 0 && (
                <div>
                  <p className="font-medium">Conflits avec la base ({conflicts.database_conflicts.length}) :</p>
                  <ul className="list-disc list-inside ml-2 mt-0.5">
                    {conflicts.database_conflicts.slice(0, 20).map((c, i) => (
                      <li key={i}>Ligne {c.line} — {c.field} « {c.value} » → {c.conflict_with}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="px-4 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300" data-testid="amm-import-cancel">
            Fermer
          </button>
          <button type="submit" disabled={!file || busy} className="px-3 py-2 rounded text-sm bg-rose-600 hover:bg-rose-700 text-white disabled:opacity-50 inline-flex items-center gap-1" data-testid="amm-import-submit">
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
            {busy ? "Import en cours…" : "Importer"}
          </button>
        </div>
      </form>
    </div>
  );
}
