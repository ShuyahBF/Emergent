/*
 * Iter38c — Cashier Expenses tab.
 *
 * Anyone with can_cash (or admin/superviseur/Comptable) can:
 *  - Create a new expense (cash | check)
 *  - View the list of expenses for a month, filtered by status
 *  - Justify their own expense (rejected if past the deadline)
 *
 * Only Admins can edit, delete, or toggle the 'is_justified' flag (with force).
 *
 * The justification deadline is admin-configurable in Admin Settings
 * (settings.expense_justification_deadline_hours, 0 = no limit).
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  Plus, Trash2, CheckCircle2, XCircle, Clock, AlertTriangle, Banknote,
  FileText, RefreshCw, Edit2, Save, Loader2, X, ShieldAlert,
} from "lucide-react";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const fmtDateTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
};
const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("fr-FR"); } catch { return iso; }
};

const STATUS_FILTERS = [
  { id: "all", label: "Toutes", icon: FileText },
  { id: "unjustified", label: "Non justifiées", icon: Clock },
  { id: "justified", label: "Justifiées", icon: CheckCircle2 },
  { id: "late_unjustified", label: "Hors délai", icon: AlertTriangle },
];

function ExpenseForm({ onSave, onCancel }) {
  const [form, setForm] = useState({
    amount: 0, currency: "XOF", method: "cash", payee: "",
    motif: "", expense_date: new Date().toISOString().slice(0, 10),
    note: "",
    attribution_type: "third_party",
    employee_id: "",
  });
  const [employees, setEmployees] = useState([]);
  const [saving, setSaving] = useState(false);

  // Iter38m — Load employees list for the dropdown
  useEffect(() => {
    apiClient.get("/cashier/expenses/employees-list")
      .then((r) => setEmployees(r.data || []))
      .catch(() => setEmployees([]));
  }, []);

  const submit = async () => {
    if (!form.amount || form.amount <= 0) { toast.error("Montant requis"); return; }
    if (!form.motif) { toast.error("Motif requis"); return; }
    if (form.attribution_type === "employee" && !form.employee_id) {
      toast.error("Sélectionnez l'employé concerné"); return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      if (payload.attribution_type === "third_party") {
        delete payload.employee_id;
      }
      await apiClient.post("/cashier/expenses", payload);
      toast.success("Dépense enregistrée");
      onSave();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="expense-form-modal">
      <div className="bg-white rounded-2xl max-w-lg w-full shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-lg font-semibold text-slate-900">Nouvelle dépense</h3>
          <button onClick={onCancel} className="text-slate-400 hover:text-slate-600" data-testid="expense-form-close">
            <X size={20} />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Montant *</label>
              <input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: parseFloat(e.target.value || 0) })}
                data-testid="expense-form-amount"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Devise</label>
              <input value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
                data-testid="expense-form-currency"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Mode *</label>
              <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}
                data-testid="expense-form-method"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
                <option value="cash">Caisse (espèces)</option>
                <option value="check">Chèque</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Date de la dépense</label>
              <input type="date" value={form.expense_date} onChange={(e) => setForm({ ...form, expense_date: e.target.value })}
                data-testid="expense-form-date"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Attribuer la dépense à</label>
            <div className="flex gap-2 mb-2" data-testid="expense-form-attribution">
              <button
                type="button"
                onClick={() => setForm({ ...form, attribution_type: "third_party", employee_id: "" })}
                data-testid="expense-form-attr-thirdparty"
                className={`flex-1 px-3 py-2 text-xs rounded-lg border ${form.attribution_type === "third_party" ? "bg-blue-50 border-blue-400 text-blue-700 font-semibold" : "bg-white border-slate-200 text-slate-600 hover:border-slate-300"}`}
              >
                Tiers / Fournisseur
              </button>
              <button
                type="button"
                onClick={() => setForm({ ...form, attribution_type: "employee" })}
                data-testid="expense-form-attr-employee"
                className={`flex-1 px-3 py-2 text-xs rounded-lg border ${form.attribution_type === "employee" ? "bg-rose-50 border-rose-400 text-rose-700 font-semibold" : "bg-white border-slate-200 text-slate-600 hover:border-slate-300"}`}
              >
                Employé
              </button>
            </div>
            {form.attribution_type === "third_party" ? (
              <input value={form.payee} onChange={(e) => setForm({ ...form, payee: e.target.value })}
                data-testid="expense-form-payee" placeholder="Nom du fournisseur, prestataire…"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
            ) : (
              <select
                value={form.employee_id}
                onChange={(e) => {
                  const emp = employees.find((x) => x.id === e.target.value);
                  setForm({ ...form, employee_id: e.target.value, payee: emp ? emp.name : "" });
                }}
                data-testid="expense-form-employee"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white">
                <option value="">— Choisir un employé —</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.matricule ? `[${e.matricule}] ` : ""}{e.name}{e.job_title ? ` — ${e.job_title}` : ""}
                  </option>
                ))}
              </select>
            )}
            {form.attribution_type === "employee" && (
              <p className="text-xs text-rose-600 mt-1 flex items-center gap-1">
                <AlertTriangle size={11} />
                L'employé recevra un rappel si la dépense n'est pas justifiée dans les délais.
              </p>
            )}
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Motif *</label>
            <textarea value={form.motif} onChange={(e) => setForm({ ...form, motif: e.target.value })}
              data-testid="expense-form-motif" rows={2}
              placeholder="Ex: Achat papier A4 + cartouches imprimante"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Note interne (optionnel)</label>
            <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
              data-testid="expense-form-note"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-100">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800" data-testid="expense-form-cancel">
            Annuler
          </button>
          <button onClick={submit} disabled={saving} data-testid="expense-form-submit"
            className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />} Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}

function JustifyModal({ expense, onSave, onCancel, isAdmin }) {
  const [text, setText] = useState("");
  const [proofUrl, setProofUrl] = useState("");
  const [force, setForce] = useState(false);
  const [saving, setSaving] = useState(false);
  const isLate = expense.is_late_unjustified;
  const submit = async () => {
    setSaving(true);
    try {
      const payload = { justification_text: text, justification_proof_url: proofUrl };
      if (isAdmin && force) payload.force = true;
      await apiClient.post(`/cashier/expenses/${expense.id}/justify`, payload);
      toast.success("Justification enregistrée");
      onSave();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="expense-justify-modal">
      <div className="bg-white rounded-2xl max-w-lg w-full shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-lg font-semibold text-slate-900">Justifier la dépense</h3>
          <button onClick={onCancel} className="text-slate-400" data-testid="expense-justify-close">
            <X size={20} />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div className="bg-slate-50 rounded-lg p-3 text-sm">
            <div className="flex justify-between"><span className="text-slate-500">Montant</span><span className="font-semibold">{FCFA(expense.amount)} {expense.currency}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Motif</span><span>{expense.motif}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Date dépense</span><span>{fmtDate(expense.expense_date)}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Créée le</span><span>{fmtDateTime(expense.created_at)}</span></div>
            {expense.deadline_at && (
              <div className="flex justify-between"><span className="text-slate-500">Délai jusqu'au</span><span className={isLate ? "text-rose-600 font-semibold" : ""}>{fmtDateTime(expense.deadline_at)}</span></div>
            )}
          </div>
          {isLate && (
            <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-lg p-3 text-sm flex gap-2" data-testid="expense-justify-late-warning">
              <ShieldAlert size={18} className="flex-shrink-0 mt-0.5" />
              <div>
                <strong>Délai dépassé.</strong> La justification sera refusée pour cette dépense.
                {isAdmin && (
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)}
                      data-testid="expense-justify-force" />
                    <span className="text-xs">Forcer la justification (Administrateur)</span>
                  </label>
                )}
              </div>
            </div>
          )}
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Justification (texte) *</label>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
              data-testid="expense-justify-text"
              placeholder="Ex: Facture N°123 du fournisseur ABC fournie"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">URL preuve / pièce jointe (optionnel)</label>
            <input value={proofUrl} onChange={(e) => setProofUrl(e.target.value)}
              data-testid="expense-justify-proof"
              placeholder="https://…"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-100">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-slate-600" data-testid="expense-justify-cancel">Annuler</button>
          <button onClick={submit} disabled={saving || (isLate && !force)} data-testid="expense-justify-submit"
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
            {saving ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />} Valider la justification
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ExpensesTab({ isAdmin }) {
  const { user } = useAuth();
  const today = new Date();
  const defaultMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);
  const [status, setStatus] = useState("all");
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [justifying, setJustifying] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ month });
      if (status !== "all") params.set("status", status);
      const [lst, sum] = await Promise.all([
        apiClient.get(`/cashier/expenses?${params.toString()}`),
        apiClient.get(`/cashier/expenses/monthly-summary?month=${month}`),
      ]);
      setItems(lst.data || []);
      setSummary(sum.data || null);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setLoading(false); }
  }, [month, status]);
  useEffect(() => { load(); }, [load]);

  const remove = async (e) => {
    if (!window.confirm("Supprimer cette dépense (admin) ?")) return;
    try {
      await apiClient.delete(`/cashier/expenses/${e.id}`);
      toast.success("Supprimée");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const toggleJustified = async (e) => {
    if (!e.is_justified) { setJustifying(e); return; }
    if (!window.confirm("Décocher la justification (admin) ?")) return;
    try {
      await apiClient.post(`/cashier/expenses/${e.id}/unjustify`);
      toast.success("Justification annulée");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="space-y-4" data-testid="expenses-tab">
      <div className="flex flex-wrap gap-2 items-center justify-between">
        <div className="flex gap-2 items-center flex-wrap">
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="expenses-month-picker"
            className="px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          <div className="flex gap-1 bg-slate-100 p-1 rounded-lg">
            {STATUS_FILTERS.map((f) => {
              const Icon = f.icon;
              return (
                <button key={f.id} onClick={() => setStatus(f.id)}
                  data-testid={`expenses-filter-${f.id}`}
                  className={`px-3 py-1 text-xs rounded flex items-center gap-1 ${status === f.id ? "bg-white shadow-sm" : "text-slate-600 hover:text-slate-900"}`}>
                  <Icon size={12} /> {f.label}
                </button>
              );
            })}
          </div>
          <button onClick={load} className="p-2 text-slate-500 hover:text-slate-800" title="Rafraîchir" data-testid="expenses-refresh">
            <RefreshCw size={16} />
          </button>
        </div>
        <button onClick={() => setCreating(true)}
          data-testid="expenses-add-btn"
          className="px-3 py-2 bg-rose-600 hover:bg-rose-700 text-white text-sm rounded-lg flex items-center gap-2">
          <Plus size={16} /> Ajouter une dépense
        </button>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="expenses-summary">
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-3">
            <p className="text-xs text-slate-500">Total {month}</p>
            <p className="text-xl font-bold text-slate-900">{FCFA(summary.total)} XOF</p>
            <p className="text-xs text-slate-400 mt-1">{summary.count} opération(s)</p>
          </div>
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3">
            <p className="text-xs text-emerald-700">Justifiées</p>
            <p className="text-xl font-bold text-emerald-900">{FCFA(summary.justified)}</p>
          </div>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3">
            <p className="text-xs text-amber-700">Non justifiées</p>
            <p className="text-xl font-bold text-amber-900">{FCFA(summary.unjustified)}</p>
          </div>
          <div className="bg-rose-50 border border-rose-200 rounded-xl p-3">
            <p className="text-xs text-rose-700">Hors délai (déduit paie)</p>
            <p className="text-xl font-bold text-rose-900">{FCFA(summary.late_unjustified)}</p>
            <p className="text-xs text-rose-600 mt-1">
              Délai admin: {summary.deadline_hours === 0 ? "illimité" : `${summary.deadline_hours}h`}
            </p>
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-slate-400 italic text-sm">Chargement…</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12 text-slate-400 italic text-sm" data-testid="expenses-empty">Aucune dépense pour cette période/filtre.</div>
      ) : (
        <div className="border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm min-w-[900px]">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2 text-left">Mode</th>
                <th className="px-3 py-2 text-left">Auteur</th>
                <th className="px-3 py-2 text-left">Motif</th>
                <th className="px-3 py-2 text-left">Attribuée à</th>
                <th className="px-3 py-2 text-right">Montant</th>
                <th className="px-3 py-2 text-center">Statut</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id} className="border-t border-slate-100" data-testid={`expense-row-${e.id}`}>
                  <td className="px-3 py-2">{fmtDate(e.expense_date)}</td>
                  <td className="px-3 py-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs ${e.method === "cash" ? "bg-emerald-100 text-emerald-700" : "bg-blue-100 text-blue-700"}`}>
                      {e.method === "cash" ? <Banknote size={10} /> : <FileText size={10} />}
                      {e.method === "cash" ? "Caisse" : "Chèque"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-600 text-xs">
                    <div className="font-medium">{e.created_by_name || "—"}</div>
                    <div className="text-slate-400">{fmtDateTime(e.created_at).split(" ")[1] || ""}</div>
                  </td>
                  <td className="px-3 py-2">
                    <div>{e.motif}</div>
                    {e.payee && <div className="text-xs text-slate-400">→ {e.payee}</div>}
                  </td>
                  <td className="px-3 py-2">
                    {e.attribution_type === "employee" && e.employee_name_snapshot ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-rose-50 text-rose-700 border border-rose-200" data-testid={`expense-employee-${e.id}`}>
                        <Banknote size={10} /> {e.employee_name_snapshot}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold">{FCFA(e.amount)} {e.currency}</td>
                  <td className="px-3 py-2 text-center">
                    {e.is_justified ? (
                      <button onClick={() => isAdmin && toggleJustified(e)} disabled={!isAdmin}
                        data-testid={`expense-status-${e.id}`}
                        className="px-2 py-0.5 bg-emerald-100 text-emerald-700 text-xs rounded inline-flex items-center gap-1">
                        <CheckCircle2 size={10} /> Justifiée
                        {e.forced_justification && <span title="Forcée par admin">⚡</span>}
                      </button>
                    ) : e.is_late_unjustified ? (
                      <button onClick={() => setJustifying(e)} data-testid={`expense-status-${e.id}`}
                        className="px-2 py-0.5 bg-rose-100 text-rose-700 text-xs rounded inline-flex items-center gap-1">
                        <AlertTriangle size={10} /> Hors délai
                      </button>
                    ) : (
                      <button onClick={() => setJustifying(e)} data-testid={`expense-status-${e.id}`}
                        className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs rounded inline-flex items-center gap-1">
                        <Clock size={10} /> À justifier
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {/* Iter38o — Creator/admin/sup/attributed-employee can edit while not justified */}
                    {!e.is_justified && (
                      (user?.role === "admin" || user?.role === "superviseur" ||
                       e.created_by === user?.id || e.employee_user_id === user?.id) && (
                        <button onClick={() => setEditing(e)} data-testid={`expense-edit-${e.id}`}
                          className="p-1.5 hover:bg-blue-50 text-blue-600 rounded mr-1" title="Modifier (tant que non clôturée)">
                          <Edit2 size={14} />
                        </button>
                      )
                    )}
                    {isAdmin && (
                      <button onClick={() => remove(e)} data-testid={`expense-delete-${e.id}`}
                        className="p-1.5 hover:bg-rose-50 text-rose-600 rounded" title="Supprimer (admin)">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {creating && <ExpenseForm onSave={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} />}
      {editing && <ExpenseEditForm expense={editing} onSave={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />}
      {justifying && <JustifyModal expense={justifying} isAdmin={isAdmin} onSave={() => { setJustifying(null); load(); }} onCancel={() => setJustifying(null)} />}
    </div>
  );
}

// =====================================================================
// Iter38o — Expense edit modal (for non-clôturée expenses only)
// =====================================================================
function ExpenseEditForm({ expense, onSave, onCancel }) {
  const [form, setForm] = useState({
    amount: expense.amount || 0,
    method: expense.method || "cash",
    motif: expense.motif || "",
    payee: expense.payee || "",
    expense_date: expense.expense_date || new Date().toISOString().slice(0, 10),
    note: expense.note || "",
    attribution_type: expense.attribution_type || "third_party",
    employee_id: expense.employee_id || "",
  });
  const [employees, setEmployees] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient.get("/cashier/expenses/employees-list")
      .then((r) => setEmployees(r.data || []))
      .catch(() => setEmployees([]));
  }, []);

  const submit = async () => {
    if (!form.amount || form.amount <= 0) { toast.error("Montant requis"); return; }
    if (!form.motif) { toast.error("Motif requis"); return; }
    if (form.attribution_type === "employee" && !form.employee_id) {
      toast.error("Sélectionnez l'employé"); return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      if (payload.attribution_type === "third_party") delete payload.employee_id;
      await apiClient.patch(`/cashier/expenses/${expense.id}`, payload);
      toast.success("Dépense modifiée");
      onSave();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="expense-edit-modal">
      <div className="bg-white rounded-2xl max-w-md w-full shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-lg font-semibold text-slate-900">Modifier la dépense</h3>
          <button onClick={onCancel} className="text-slate-400" data-testid="expense-edit-close"><X size={20} /></button>
        </div>
        <div className="p-5 space-y-3">
          <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg p-2 text-xs flex items-start gap-2">
            <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
            Modification autorisée uniquement tant que la dépense n'est pas clôturée (justifiée).
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Date</label>
              <input type="date" value={form.expense_date} onChange={(e) => setForm({ ...form, expense_date: e.target.value })}
                data-testid="expense-edit-date"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
            </div>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Mode</label>
              <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}
                data-testid="expense-edit-method"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white">
                <option value="cash">Caisse</option>
                <option value="check">Chèque</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Montant *</label>
            <input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: parseFloat(e.target.value || 0) })}
              data-testid="expense-edit-amount"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Motif *</label>
            <input value={form.motif} onChange={(e) => setForm({ ...form, motif: e.target.value })}
              data-testid="expense-edit-motif"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Attribuer à</label>
            <div className="flex gap-2 mb-2">
              <button type="button" onClick={() => setForm({ ...form, attribution_type: "third_party", employee_id: "" })}
                className={`flex-1 px-3 py-2 text-xs rounded-lg border ${form.attribution_type === "third_party" ? "bg-blue-50 border-blue-400 text-blue-700 font-semibold" : "bg-white border-slate-200 text-slate-600"}`}>
                Tiers
              </button>
              <button type="button" onClick={() => setForm({ ...form, attribution_type: "employee" })}
                className={`flex-1 px-3 py-2 text-xs rounded-lg border ${form.attribution_type === "employee" ? "bg-rose-50 border-rose-400 text-rose-700 font-semibold" : "bg-white border-slate-200 text-slate-600"}`}>
                Employé
              </button>
            </div>
            {form.attribution_type === "third_party" ? (
              <input value={form.payee} onChange={(e) => setForm({ ...form, payee: e.target.value })}
                data-testid="expense-edit-payee"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
            ) : (
              <select value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })}
                data-testid="expense-edit-employee"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white">
                <option value="">— Choisir un employé —</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.matricule ? `[${e.matricule}] ` : ""}{e.name}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Note (optionnel)</label>
            <textarea value={form.note} rows={2} onChange={(e) => setForm({ ...form, note: e.target.value })}
              data-testid="expense-edit-note"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-100">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-slate-600" data-testid="expense-edit-cancel">Annuler</button>
          <button onClick={submit} disabled={saving} data-testid="expense-edit-submit"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Enregistrer
          </button>
        </div>
      </div>
    </div>
  );
}
