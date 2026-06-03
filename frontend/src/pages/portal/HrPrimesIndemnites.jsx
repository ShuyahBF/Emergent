/*
 * S-iter39s (2026-02) — GRH : Primes & Indemnités tab.
 *
 *  - Indemnités fixes  (allowances) : récurrentes chaque mois, par employé.
 *    CRUD complet, peuvent être désactivées (toggle active) sans suppression.
 *  - Primes variables (bonuses) : rattachées à un mois précis (YYYY-MM).
 *    Peuvent être absentes ou présentes d'un mois à l'autre.
 *
 *  Les deux sommes s'ajoutent au salaire brut AVANT la déduction d'absence
 *  et le calcul des taxes côté backend `_compute_payslip`. La fiche de paie
 *  PDF + l'onglet "Paie" reflètent ce détail.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Plus, Trash2, Edit2, Save, X, Loader2, Calendar, Banknote,
  ToggleLeft, ToggleRight, Sparkles, Briefcase, Copy, BookOpen, ArrowRightLeft,
} from "lucide-react";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });

function Empty({ label }) {
  return <div className="text-center py-8 text-slate-400 text-xs italic">{label}</div>;
}

// =====================================================================
// Allowances (indemnités fixes)
// =====================================================================
function AllowancesCard({ employee, currency }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ label: "", amount: "", notes: "", active: true });
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});

  const load = useCallback(async () => {
    if (!employee?.id) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/employees/${employee.id}/allowances`);
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement des indemnités");
    } finally { setLoading(false); }
  }, [employee?.id]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.label.trim()) { toast.error("Libellé requis"); return; }
    const amt = parseFloat(form.amount || 0);
    if (Number.isNaN(amt) || amt < 0) { toast.error("Montant invalide"); return; }
    setSaving(true);
    try {
      await apiClient.post(`/hr/employees/${employee.id}/allowances`, {
        label: form.label.trim(),
        amount: amt,
        currency: currency || "XOF",
        active: form.active,
        notes: form.notes.trim() || null,
      });
      toast.success("Indemnité ajoutée");
      setForm({ label: "", amount: "", notes: "", active: true });
      setCreating(false);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const beginEdit = (it) => {
    setEditingId(it.id);
    setEditForm({ label: it.label, amount: it.amount, notes: it.notes || "", active: it.active });
  };

  const saveEdit = async () => {
    if (!editForm.label.trim()) { toast.error("Libellé requis"); return; }
    try {
      await apiClient.patch(`/hr/allowances/${editingId}`, {
        label: editForm.label.trim(),
        amount: parseFloat(editForm.amount || 0),
        notes: editForm.notes.trim() || null,
        active: editForm.active,
      });
      toast.success("Indemnité mise à jour");
      setEditingId(null);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const toggleActive = async (it) => {
    try {
      await apiClient.patch(`/hr/allowances/${it.id}`, { active: !it.active });
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const remove = async (it) => {
    if (!window.confirm(`Supprimer l'indemnité « ${it.label} » ?`)) return;
    try {
      await apiClient.delete(`/hr/allowances/${it.id}`);
      toast.success("Supprimée");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const totalActive = useMemo(
    () => items.filter((i) => i.active).reduce((s, i) => s + Number(i.amount || 0), 0),
    [items],
  );

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="hr-allowances-card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Briefcase size={16} className="text-indigo-600" />
            Indemnités fixes
          </h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Ajoutées au brut chaque mois automatiquement (transport, logement, panier, ancienneté…). Restent identiques jusqu'à modification.
          </p>
        </div>
        {!creating && (
          <button
            onClick={() => setCreating(true)}
            data-testid="hr-allowance-add-btn"
            className="px-2.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs rounded-lg flex items-center gap-1"
          >
            <Plus size={14} /> Ajouter
          </button>
        )}
      </div>

      {creating && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-3 mb-3 space-y-2" data-testid="hr-allowance-create-form">
          <input
            placeholder="Libellé (ex: Indemnité transport)"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
            data-testid="hr-allowance-label"
            className="w-full px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
          />
          <div className="flex gap-2">
            <input
              type="number"
              placeholder="Montant"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              data-testid="hr-allowance-amount"
              className="flex-1 px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
            />
            <span className="text-xs text-slate-500 self-center">{currency || "XOF"}</span>
          </div>
          <input
            placeholder="Notes (optionnel)"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            data-testid="hr-allowance-notes"
            className="w-full px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => { setCreating(false); setForm({ label: "", amount: "", notes: "", active: true }); }}
              className="px-2.5 py-1.5 text-xs rounded-md ring-1 ring-slate-300 hover:bg-slate-50"
              data-testid="hr-allowance-cancel"
            >Annuler</button>
            <button
              onClick={create}
              disabled={saving}
              className="px-2.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs rounded-md inline-flex items-center gap-1 disabled:opacity-60"
              data-testid="hr-allowance-save"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Enregistrer
            </button>
          </div>
        </div>
      )}

      {loading ? <Empty label="Chargement…" /> : items.length === 0 ? (
        <Empty label="Aucune indemnité." />
      ) : (
        <div className="space-y-1.5">
          {items.map((it) => (
            <div
              key={it.id}
              data-testid={`hr-allowance-row-${it.id}`}
              className={`rounded-lg ring-1 p-2.5 ${it.active ? "ring-slate-200 bg-white" : "ring-slate-200 bg-slate-50 opacity-70"}`}
            >
              {editingId === it.id ? (
                <div className="space-y-2">
                  <input
                    value={editForm.label}
                    onChange={(e) => setEditForm({ ...editForm, label: e.target.value })}
                    className="w-full px-2 py-1 text-sm rounded border border-slate-300"
                    data-testid={`hr-allowance-edit-label-${it.id}`}
                  />
                  <div className="flex gap-2">
                    <input
                      type="number"
                      value={editForm.amount}
                      onChange={(e) => setEditForm({ ...editForm, amount: e.target.value })}
                      className="flex-1 px-2 py-1 text-sm rounded border border-slate-300"
                      data-testid={`hr-allowance-edit-amount-${it.id}`}
                    />
                    <span className="text-xs text-slate-500 self-center">{currency || "XOF"}</span>
                  </div>
                  <input
                    value={editForm.notes}
                    onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                    placeholder="Notes"
                    className="w-full px-2 py-1 text-xs rounded border border-slate-300"
                  />
                  <div className="flex justify-end gap-1.5">
                    <button onClick={() => setEditingId(null)} className="text-xs px-2 py-1 rounded ring-1 ring-slate-300"><X size={12} /></button>
                    <button onClick={saveEdit} className="text-xs px-2 py-1 rounded bg-emerald-600 text-white inline-flex items-center gap-1" data-testid={`hr-allowance-save-${it.id}`}>
                      <Save size={12} /> Sauver
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => toggleActive(it)}
                    className="text-slate-400 hover:text-indigo-600 shrink-0"
                    title={it.active ? "Désactiver" : "Activer"}
                    data-testid={`hr-allowance-toggle-${it.id}`}
                  >
                    {it.active ? <ToggleRight size={20} className="text-emerald-600" /> : <ToggleLeft size={20} />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 truncate">{it.label}</p>
                    {it.notes && <p className="text-[10px] text-slate-500 truncate">{it.notes}</p>}
                  </div>
                  <div className="text-sm font-semibold text-slate-900 tabular-nums shrink-0">
                    {FCFA(it.amount)} <span className="text-[10px] text-slate-500">{it.currency || currency}</span>
                  </div>
                  <button onClick={() => beginEdit(it)} className="text-slate-400 hover:text-slate-700 p-1" data-testid={`hr-allowance-edit-${it.id}`}>
                    <Edit2 size={14} />
                  </button>
                  <button onClick={() => remove(it)} className="text-rose-400 hover:text-rose-700 p-1" data-testid={`hr-allowance-delete-${it.id}`}>
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
          ))}
          <div className="flex justify-between pt-2 mt-1 border-t border-slate-200 text-sm">
            <span className="text-slate-600">Total mensuel actif</span>
            <span className="font-bold text-indigo-700 tabular-nums" data-testid="hr-allowance-total">
              + {FCFA(totalActive)} {currency}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}


// =====================================================================
// Bonuses (primes variables par mois)
// =====================================================================
function BonusesCard({ employee, currency, defaultMonth }) {
  const [month, setMonth] = useState(defaultMonth);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ label: "", amount: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const [duplicating, setDuplicating] = useState(false);

  const load = useCallback(async () => {
    if (!employee?.id) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/employees/${employee.id}/bonuses?month=${month}`);
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement des primes");
    } finally { setLoading(false); }
  }, [employee?.id, month]);

  useEffect(() => { load(); }, [load]);

  const previousMonth = useMemo(() => {
    // YYYY-MM → previous YYYY-MM
    if (!/^\d{4}-\d{2}$/.test(month)) return null;
    const [y, m] = month.split("-").map(Number);
    const d = new Date(y, m - 2, 1);  // m-1 (zero-based) - 1
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }, [month]);

  const duplicateFromPreviousMonth = async () => {
    if (!previousMonth) return;
    if (items.length > 0) {
      if (!window.confirm(
        `Le mois ${month} contient déjà ${items.length} prime(s). Voulez-vous ajouter celles de ${previousMonth} par-dessus (sans écraser) ?`,
      )) return;
    }
    setDuplicating(true);
    try {
      // Fetch previous month bonuses
      const r = await apiClient.get(`/hr/employees/${employee.id}/bonuses?month=${previousMonth}`);
      const prev = r.data || [];
      if (prev.length === 0) {
        toast.error(`Aucune prime à dupliquer (${previousMonth} est vide).`);
        setDuplicating(false);
        return;
      }
      // Create each one for the current month
      let created = 0;
      for (const b of prev) {
        try {
          await apiClient.post(`/hr/employees/${employee.id}/bonuses`, {
            month,
            label: b.label,
            amount: Number(b.amount || 0),
            currency: b.currency || currency || "XOF",
            notes: b.notes || null,
          });
          created += 1;
        } catch (err) {
          /* keep going */
        }
      }
      toast.success(`${created} prime(s) dupliquée(s) depuis ${previousMonth}.`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de duplication");
    } finally { setDuplicating(false); }
  };

  const create = async () => {
    if (!form.label.trim()) { toast.error("Libellé requis"); return; }
    const amt = parseFloat(form.amount || 0);
    if (Number.isNaN(amt) || amt < 0) { toast.error("Montant invalide"); return; }
    setSaving(true);
    try {
      await apiClient.post(`/hr/employees/${employee.id}/bonuses`, {
        month,
        label: form.label.trim(),
        amount: amt,
        currency: currency || "XOF",
        notes: form.notes.trim() || null,
      });
      toast.success("Prime ajoutée");
      setForm({ label: "", amount: "", notes: "" });
      setCreating(false);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const remove = async (it) => {
    if (!window.confirm(`Supprimer la prime « ${it.label} » de ${it.month} ?`)) return;
    try {
      await apiClient.delete(`/hr/bonuses/${it.id}`);
      toast.success("Prime supprimée");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const total = useMemo(
    () => items.reduce((s, i) => s + Number(i.amount || 0), 0),
    [items],
  );

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="hr-bonuses-card">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <Sparkles size={16} className="text-amber-500" />
            Primes variables
          </h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Variables d'un mois à l'autre (rendement, performance, treizième mois…). Saisies pour un mois précis.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            data-testid="hr-bonus-month"
            className="px-2 py-1 rounded-md border border-slate-200 text-xs"
          />
          {previousMonth && (
            <button
              onClick={duplicateFromPreviousMonth}
              disabled={duplicating}
              data-testid="hr-bonus-duplicate-prev"
              title={`Recopier toutes les primes de ${previousMonth} vers ${month}`}
              className="px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs rounded-lg inline-flex items-center gap-1 disabled:opacity-60"
            >
              {duplicating ? <Loader2 size={12} className="animate-spin" /> : <Copy size={12} />}
              Dupliquer {previousMonth}
            </button>
          )}
          {!creating && (
            <button
              onClick={() => setCreating(true)}
              data-testid="hr-bonus-add-btn"
              className="px-2.5 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs rounded-lg flex items-center gap-1"
            >
              <Plus size={14} /> Ajouter
            </button>
          )}
        </div>
      </div>

      {creating && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3 space-y-2" data-testid="hr-bonus-create-form">
          <input
            placeholder="Libellé (ex: Prime de rendement Q1)"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
            data-testid="hr-bonus-label"
            className="w-full px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
          />
          <div className="flex gap-2">
            <input
              type="number"
              placeholder="Montant"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              data-testid="hr-bonus-amount"
              className="flex-1 px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
            />
            <span className="text-xs text-slate-500 self-center">{currency || "XOF"} pour {month}</span>
          </div>
          <input
            placeholder="Notes (optionnel)"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => { setCreating(false); setForm({ label: "", amount: "", notes: "" }); }}
              className="px-2.5 py-1.5 text-xs rounded-md ring-1 ring-slate-300 hover:bg-slate-50"
              data-testid="hr-bonus-cancel"
            >Annuler</button>
            <button
              onClick={create}
              disabled={saving}
              className="px-2.5 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs rounded-md inline-flex items-center gap-1 disabled:opacity-60"
              data-testid="hr-bonus-save"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Enregistrer
            </button>
          </div>
        </div>
      )}

      {loading ? <Empty label="Chargement…" /> : items.length === 0 ? (
        <Empty label={`Aucune prime pour ${month}.`} />
      ) : (
        <div className="space-y-1.5">
          {items.map((it) => (
            <div key={it.id} data-testid={`hr-bonus-row-${it.id}`} className="rounded-lg ring-1 ring-slate-200 bg-white p-2.5 flex items-center gap-2">
              <Calendar size={14} className="text-amber-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-slate-800 truncate">{it.label}</p>
                {it.notes && <p className="text-[10px] text-slate-500 truncate">{it.notes}</p>}
              </div>
              <div className="text-sm font-semibold text-amber-700 tabular-nums shrink-0">
                + {FCFA(it.amount)} <span className="text-[10px] text-slate-500">{it.currency || currency}</span>
              </div>
              <button onClick={() => remove(it)} className="text-rose-400 hover:text-rose-700 p-1" data-testid={`hr-bonus-delete-${it.id}`}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <div className="flex justify-between pt-2 mt-1 border-t border-slate-200 text-sm">
            <span className="text-slate-600">Total primes — {month}</span>
            <span className="font-bold text-amber-700 tabular-nums" data-testid="hr-bonus-total">
              + {FCFA(total)} {currency}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}


// =====================================================================
// 0-3 (2026-02) — Catalog of pay items (standalone templates)
// =====================================================================
function CatalogCard({ employee, onApplied, defaultMonth }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ kind: "allowance", label: "", default_amount: "", description: "" });
  const [applyingId, setApplyingId] = useState(null);
  const [applyForm, setApplyForm] = useState({ amount: "", bonus_month: defaultMonth });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/hr/pay-catalog");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement du catalogue");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.label.trim()) { toast.error("Libellé requis"); return; }
    try {
      await apiClient.post("/hr/pay-catalog", {
        kind: form.kind,
        label: form.label.trim(),
        default_amount: parseFloat(form.default_amount || 0),
        description: form.description.trim() || null,
      });
      toast.success("Élément catalogue ajouté");
      setForm({ kind: "allowance", label: "", default_amount: "", description: "" });
      setCreating(false);
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const remove = async (it) => {
    if (!window.confirm(`Supprimer « ${it.label} » du catalogue ? (Les indemnités/primes déjà attachées aux employés ne sont pas touchées.)`)) return;
    try {
      await apiClient.delete(`/hr/pay-catalog/${it.id}`);
      toast.success("Supprimé");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const apply = async (it) => {
    if (!employee?.id) { toast.error("Sélectionnez d'abord un employé"); return; }
    const data = new FormData();
    if (applyForm.amount) data.append("amount", applyForm.amount);
    if (it.kind === "bonus") {
      if (!applyForm.bonus_month) { toast.error("Mois requis pour une prime"); return; }
      data.append("bonus_month", applyForm.bonus_month);
    }
    try {
      await apiClient.post(`/hr/employees/${employee.id}/apply-catalog/${it.id}`, data, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`« ${it.label} » appliqué à ${employee.user?.full_name || employee.matricule}`);
      setApplyingId(null);
      setApplyForm({ amount: "", bonus_month: defaultMonth });
      onApplied?.();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="hr-catalog-card">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
            <BookOpen size={16} className="text-violet-600" />
            Catalogue des primes & indemnités
          </h3>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Définissez vos rubriques (transport, logement, treizième mois…) une seule fois.
            Appliquez-les ensuite à n'importe quel agent en un clic. Codes auto-générés.
          </p>
        </div>
        {!creating && (
          <button
            onClick={() => setCreating(true)}
            data-testid="hr-catalog-add-btn"
            className="px-2.5 py-1.5 bg-violet-600 hover:bg-violet-700 text-white text-xs rounded-lg flex items-center gap-1"
          >
            <Plus size={14} /> Nouvelle rubrique
          </button>
        )}
      </div>

      {creating && (
        <div className="bg-violet-50 border border-violet-200 rounded-lg p-3 mb-3 space-y-2" data-testid="hr-catalog-create-form">
          <div className="flex gap-2">
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
              data-testid="hr-catalog-kind"
              className="px-2.5 py-1.5 rounded-md border border-slate-200 text-sm bg-white"
            >
              <option value="allowance">📌 Indemnité (fixe / mois)</option>
              <option value="bonus">✨ Prime (variable / mois)</option>
            </select>
            <input
              placeholder="Libellé (ex: Indemnité Transport)"
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              data-testid="hr-catalog-label"
              className="flex-1 px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
            />
          </div>
          <input
            type="number"
            placeholder="Montant par défaut (modifiable à l'application)"
            value={form.default_amount}
            onChange={(e) => setForm({ ...form, default_amount: e.target.value })}
            data-testid="hr-catalog-default-amount"
            className="w-full px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
          />
          <input
            placeholder="Description / règle (optionnel)"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-md border border-slate-200 text-sm"
          />
          <div className="flex justify-end gap-2">
            <button onClick={() => { setCreating(false); setForm({ kind: "allowance", label: "", default_amount: "", description: "" }); }} className="px-2.5 py-1.5 text-xs rounded-md ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
            <button onClick={create} data-testid="hr-catalog-save" className="px-2.5 py-1.5 bg-violet-600 hover:bg-violet-700 text-white text-xs rounded-md inline-flex items-center gap-1">
              <Save size={12} /> Enregistrer
            </button>
          </div>
        </div>
      )}

      {loading ? <Empty label="Chargement…" /> : items.length === 0 ? (
        <Empty label="Aucune rubrique. Créez votre première !" />
      ) : (
        <div className="space-y-1.5">
          {items.map((it) => (
            <div key={it.id} data-testid={`hr-catalog-row-${it.id}`} className="rounded-lg ring-1 ring-slate-200 bg-white p-2.5">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${it.kind === "allowance" ? "bg-indigo-100 text-indigo-700" : "bg-amber-100 text-amber-700"}`}>
                  {it.code}
                </span>
                <span className={`text-[10px] uppercase tracking-wider ${it.kind === "allowance" ? "text-indigo-600" : "text-amber-600"}`}>
                  {it.kind === "allowance" ? "Indemnité" : "Prime"}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-800 truncate">{it.label}</p>
                  {it.description && <p className="text-[10px] text-slate-500 truncate">{it.description}</p>}
                </div>
                <div className="text-xs text-slate-600 tabular-nums shrink-0">
                  ~ {FCFA(it.default_amount)} {it.currency || "XOF"}
                </div>
                <button
                  onClick={() => { setApplyingId(applyingId === it.id ? null : it.id); setApplyForm({ amount: "", bonus_month: defaultMonth }); }}
                  data-testid={`hr-catalog-apply-${it.id}`}
                  disabled={!employee}
                  title={employee ? `Appliquer à ${employee.user?.full_name || employee.matricule}` : "Sélectionnez un employé d'abord"}
                  className="px-2 py-1 text-[11px] rounded bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-40 inline-flex items-center gap-1"
                >
                  → Appliquer
                </button>
                <button onClick={() => remove(it)} className="text-rose-400 hover:text-rose-700 p-1" data-testid={`hr-catalog-delete-${it.id}`}>
                  <Trash2 size={14} />
                </button>
              </div>
              {applyingId === it.id && employee && (
                <div className="mt-2 pt-2 border-t border-slate-100 flex flex-wrap items-center gap-2" data-testid={`hr-catalog-apply-form-${it.id}`}>
                  <input
                    type="number"
                    placeholder={`Montant (def. ${FCFA(it.default_amount)})`}
                    value={applyForm.amount}
                    onChange={(e) => setApplyForm({ ...applyForm, amount: e.target.value })}
                    className="px-2 py-1 rounded border border-slate-300 text-xs w-40"
                  />
                  {it.kind === "bonus" && (
                    <input
                      type="month"
                      value={applyForm.bonus_month}
                      onChange={(e) => setApplyForm({ ...applyForm, bonus_month: e.target.value })}
                      className="px-2 py-1 rounded border border-slate-300 text-xs"
                    />
                  )}
                  <button onClick={() => apply(it)} className="px-2 py-1 text-[11px] rounded bg-emerald-600 hover:bg-emerald-700 text-white" data-testid={`hr-catalog-confirm-${it.id}`}>
                    Confirmer
                  </button>
                  <button onClick={() => setApplyingId(null)} className="px-2 py-1 text-[11px] rounded ring-1 ring-slate-300 text-slate-600">
                    Annuler
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// =====================================================================
// 0-3 (2026-02) — Copy primes/indemnités from src to target employee
// =====================================================================
function CopyButton({ employees, srcEmployee, onCopied, defaultMonth }) {
  const [open, setOpen] = useState(false);
  const [targetId, setTargetId] = useState("");
  const [includeAllowances, setIncludeAllowances] = useState(true);
  const [includeBonuses, setIncludeBonuses] = useState(false);
  const [bonusMonth, setBonusMonth] = useState(defaultMonth);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!targetId) { toast.error("Sélectionnez un employé cible"); return; }
    if (!includeAllowances && !includeBonuses) { toast.error("Au moins une option (indemnités ou primes)"); return; }
    setBusy(true);
    try {
      const r = await apiClient.post(`/hr/employees/${srcEmployee.id}/copy-pay-items`, {
        target_employee_id: targetId,
        include_allowances: includeAllowances,
        include_bonuses: includeBonuses,
        bonus_month: includeBonuses ? bonusMonth : null,
      });
      const d = r.data || {};
      toast.success(`✓ ${d.copied_allowances || 0} indemnité(s) + ${d.copied_bonuses || 0} prime(s) recopiées.`);
      setOpen(false);
      setTargetId("");
      onCopied?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setBusy(false); }
  };

  const otherEmployees = employees.filter((e) => e.id !== srcEmployee?.id);

  if (!srcEmployee) return null;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        data-testid="hr-copy-pay-items-btn"
        className="px-3 py-2 bg-sky-50 hover:bg-sky-100 text-sky-700 ring-1 ring-sky-200 rounded-lg text-xs inline-flex items-center gap-1.5"
        title="Reporter les primes & indemnités d'un agent à un autre"
      >
        <ArrowRightLeft size={14} /> Reporter vers un autre agent
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" data-testid="hr-copy-modal">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <ArrowRightLeft size={16} className="text-sky-600" />
                Reporter les rubriques de paie
              </h3>
              <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700" data-testid="hr-copy-modal-close">
                <X size={18} />
              </button>
            </div>
            <div className="text-xs text-slate-600 bg-slate-50 rounded p-2">
              <p>De : <strong>{srcEmployee.user?.full_name || srcEmployee.matricule}</strong></p>
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-700 mb-1 block">Vers</label>
              <select
                value={targetId}
                onChange={(e) => setTargetId(e.target.value)}
                data-testid="hr-copy-target-select"
                className="w-full px-2.5 py-2 rounded border border-slate-300 text-sm"
              >
                <option value="">— Choisir un employé —</option>
                {otherEmployees.map((e) => (
                  <option key={e.id} value={e.id}>{e.user?.full_name || e.name_snapshot || e.matricule}</option>
                ))}
              </select>
            </div>
            <label className="flex items-start gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={includeAllowances}
                onChange={(e) => setIncludeAllowances(e.target.checked)}
                data-testid="hr-copy-include-allowances"
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-slate-700">Indemnités fixes (actives uniquement)</span>
                <span className="block text-[10px] text-slate-500">Récurrentes — recopiées telles quelles, état actif.</span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                checked={includeBonuses}
                onChange={(e) => setIncludeBonuses(e.target.checked)}
                data-testid="hr-copy-include-bonuses"
                className="mt-0.5"
              />
              <span>
                <span className="font-semibold text-slate-700">Primes d'un mois précis</span>
                <span className="block text-[10px] text-slate-500">Spécifiez le mois ; les primes de ce mois seront recopiées.</span>
              </span>
            </label>
            {includeBonuses && (
              <input
                type="month"
                value={bonusMonth}
                onChange={(e) => setBonusMonth(e.target.value)}
                data-testid="hr-copy-bonus-month"
                className="ml-6 px-2 py-1 rounded border border-slate-300 text-xs"
              />
            )}
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setOpen(false)} className="px-3 py-1.5 text-xs rounded ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
              <button onClick={submit} disabled={busy || !targetId} data-testid="hr-copy-submit" className="px-3 py-1.5 bg-sky-600 hover:bg-sky-700 text-white text-xs rounded inline-flex items-center gap-1 disabled:opacity-50">
                {busy ? <Loader2 size={12} className="animate-spin" /> : <Copy size={12} />} Reporter
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


// =====================================================================
// Main tab
// =====================================================================
export default function PrimesIndemnitesTab({ employees }) {
  const today = new Date();
  const defaultMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [selectedId, setSelectedId] = useState(employees[0]?.id || "");
  const [refreshKey, setRefreshKey] = useState(0);

  const selected = useMemo(
    () => employees.find((e) => e.id === selectedId) || null,
    [employees, selectedId],
  );

  if (employees.length === 0) return <Empty label="Aucun employé enrôlé." />;

  const triggerRefresh = () => setRefreshKey((k) => k + 1);

  return (
    <div className="space-y-4" data-testid="hr-primes-indemnites-tab">
      <div className="flex items-end gap-3 flex-wrap">
        <div className="flex-1 min-w-[220px]">
          <label className="text-xs font-medium text-slate-600 mb-1 block">Employé</label>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            data-testid="hr-primes-employee-select"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white"
          >
            {employees.map((e) => (
              <option key={e.id} value={e.id}>
                {e.user?.full_name || e.name_snapshot || e.matricule}
              </option>
            ))}
          </select>
        </div>
        {selected && (
          <>
            <div className="text-xs text-slate-500 px-2 py-2 inline-flex items-center gap-2">
              <Banknote size={14} className="text-emerald-600" />
              Salaire de base : <strong className="text-slate-700">{FCFA(selected.base_salary)} {selected.currency || "XOF"}</strong>
            </div>
            <CopyButton
              employees={employees}
              srcEmployee={selected}
              defaultMonth={defaultMonth}
              onCopied={triggerRefresh}
            />
          </>
        )}
      </div>

      {selected && (
        <div className="grid lg:grid-cols-2 gap-4" key={refreshKey}>
          <AllowancesCard employee={selected} currency={selected.currency || "XOF"} />
          <BonusesCard employee={selected} currency={selected.currency || "XOF"} defaultMonth={defaultMonth} />
        </div>
      )}

      {/* 0-3 — Standalone catalog of pay items (independent of any employee) */}
      <CatalogCard employee={selected} defaultMonth={defaultMonth} onApplied={triggerRefresh} />

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-[11px] text-blue-800">
        💡 Les <strong>indemnités fixes</strong> et <strong>primes du mois</strong> sont automatiquement
        ajoutées au salaire brut dans le calcul de la fiche de paie. Vous pouvez consulter le bulletin
        détaillé dans l'onglet <strong>Paie</strong>.
      </div>
    </div>
  );
}
