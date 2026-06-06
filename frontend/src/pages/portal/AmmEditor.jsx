// Iter41 Phase 2 (2026-02) — AMM Editor pour les utilisateurs avec rôle régulateur
// (ou admin / superviseur). Permet de saisir et tenir à jour les numéros d'AMM
// (Autorisation de Mise sur le Marché) qui complètent les fiches VIDAL.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import {
  ScrollText, Loader2, Plus, Search, Edit3, Trash2, X, Save
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
  laboratory: "",
  galenic_form: "",
  atc_class: "",
  status: "active",
  granted_at: "",
  expires_at: "",
  notes: "",
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
    if (!form.product_name?.trim() || !form.amm_number?.trim()) {
      toast.warning("Nom du produit et numéro AMM requis");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        vidal_product_id: form.vidal_product_id ? parseInt(form.vidal_product_id) : null,
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
            <span className="block text-slate-600 mb-1">Numéro AMM *</span>
            <input value={form.amm_number || ""} onChange={(e) => upd("amm_number", e.target.value)}
                   placeholder="ex: 3400930471722"
                   className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono" data-testid="amm-form-number" />
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
  const canEdit = user && ["admin", "superviseur", "regulateur"].includes(user.role);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState(null);

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
          <button onClick={() => { setEditing(null); setEditorOpen(true); }}
                  className="text-sm px-3 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-2"
                  data-testid="amm-new-btn">
            <Plus className="h-4 w-4" /> Nouvelle AMM
          </button>
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
                <th className="text-left px-3 py-2">Produit</th>
                <th className="text-left px-3 py-2">AMM</th>
                <th className="text-left px-3 py-2">Laboratoire</th>
                <th className="text-left px-3 py-2">Statut</th>
                <th className="text-left px-3 py-2">Validité</th>
                {canEdit && <th></th>}
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} className="border-t border-slate-100 hover:bg-rose-50/30" data-testid={`amm-row-${it.id}`}>
                  <td className="px-3 py-2">
                    <div className="font-semibold text-slate-800">{it.product_name}</div>
                    {it.vidal_product_id && <div className="text-[10px] text-slate-500 font-mono">VIDAL #{it.vidal_product_id}</div>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{it.amm_number}</td>
                  <td className="px-3 py-2 text-xs">{it.laboratory || "—"}</td>
                  <td className="px-3 py-2"><StatusBadge status={it.status} /></td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {it.granted_at ? <div>Du {it.granted_at}</div> : null}
                    {it.expires_at ? <div>au {it.expires_at}</div> : null}
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
    </div>
  );
}
