/*
 * Iter38b — GRH advanced tabs: Absences, Taxes, Avances, Paie, Réglages,
 * + mini-graph "Présence cette semaine" sticked on top of Personnel tab.
 */
import React, { useEffect, useMemo, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Plus, X, RotateCcw, Trash2, Edit2, Save, Loader2,
  Calendar, RefreshCw, Download, FileText, AlertTriangle, BarChart3, Search,
  CalendarDays, ChevronDown,
} from "lucide-react";

export const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
export const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("fr-FR"); } catch { return String(iso).slice(0, 10); }
};
export const Empty = ({ label }) => (
  <div className="text-center py-12 text-slate-400 text-sm italic">{label}</div>
);

// =====================================================================
// Weekly Presence mini-graph (shown on Personnel tab top)
// =====================================================================
export function WeeklyPresenceCard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/hr/dashboard/weekly-presence");
      setData(r.data);
    } catch { setData(null); } finally { setLoading(false); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  if (loading) return <div className="bg-slate-50 rounded-xl p-4 text-xs text-slate-500" data-testid="hr-weekly-loading">Chargement présence…</div>;
  if (!data || data.top.length === 0) {
    return (
      <div className="bg-slate-50 rounded-xl p-4 text-xs text-slate-500" data-testid="hr-weekly-empty">
        Aucune activité enregistrée cette semaine.
      </div>
    );
  }
  const maxHours = Math.max(...data.top.map((t) => t.hours), 1);
  return (
    <div className="bg-gradient-to-br from-blue-50 to-emerald-50 border border-blue-100 rounded-xl p-4 mb-5" data-testid="hr-weekly-card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-700 flex items-center gap-2">
          <BarChart3 size={16} className="text-blue-600" />
          Présence cette semaine
          <span className="text-xs text-slate-400 font-normal">({fmtDate(data.week_start)} → {fmtDate(data.week_end)})</span>
        </h3>
        <button onClick={refresh} className="text-slate-500 hover:text-slate-700" title="Rafraîchir" data-testid="hr-weekly-refresh">
          <RefreshCw size={14} />
        </button>
      </div>
      <div className="space-y-2">
        {data.top.map((t, idx) => {
          const pct = Math.round((t.hours / maxHours) * 100);
          return (
            <div key={t.employee_id} className="flex items-center gap-3" data-testid={`hr-weekly-bar-${idx}`}>
              <div className="w-32 text-xs text-slate-600 truncate">{t.name || "—"}</div>
              <div className="flex-1 bg-slate-200 rounded-full h-2.5 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="w-16 text-xs text-slate-700 font-medium text-right">{t.hours} h</div>
              <div className="w-10 text-xs text-slate-500 text-right">{t.days}j</div>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-slate-400 mt-3">Top 5 des employés par heures cumulées (lun→dim).</p>
    </div>
  );
}

// =====================================================================
// Absences tab
// =====================================================================
export function AbsencesTab({ employees }) {
  const [employeeId, setEmployeeId] = useState(employees[0]?.id || "");
  const today = new Date();
  const defaultMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);
  const [items, setItems] = useState([]);
  const [scanResults, setScanResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    start_date: "", end_date: "", hours_count: 8,
    abs_type: "non_justifiee", is_justified: false, justification: "",
  });

  const load = useCallback(async () => {
    if (!employeeId) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/absences?employee_id=${employeeId}&month=${month}`);
      setItems(r.data || []);
    } catch (err) { toast.error("Erreur de chargement"); } finally { setLoading(false); }
  }, [employeeId, month]);

  useEffect(() => { load(); }, [load]);

  const scan = async () => {
    try {
      const r = await apiClient.post(`/hr/absences/scan?employee_id=${employeeId}&month=${month}`);
      setScanResults(r.data?.suggestions || []);
      toast.success(`${r.data?.suggestions?.length || 0} jour(s) ouvré(s) sans connexion détecté(s)`);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur scan"); }
  };

  const persistSuggestion = async (s) => {
    try {
      await apiClient.post("/hr/absences", {
        employee_id: employeeId, start_date: s.date, end_date: s.date,
        hours_count: s.suggested_hours, abs_type: s.abs_type, is_justified: false,
      });
      toast.success(`Absence ${s.date} enregistrée`);
      setScanResults((prev) => prev.filter((x) => x.date !== s.date));
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const submit = async () => {
    if (!form.start_date || !form.end_date) { toast.error("Dates requises"); return; }
    try {
      await apiClient.post("/hr/absences", { ...form, employee_id: employeeId });
      toast.success("Absence enregistrée");
      setForm({ ...form, start_date: "", end_date: "", justification: "" });
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const remove = async (a) => {
    if (!window.confirm("Supprimer cette absence ?")) return;
    try {
      await apiClient.delete(`/hr/absences/${a.id}`);
      toast.success("Supprimée");
      load();
    } catch (err) { toast.error("Erreur"); }
  };

  const toggleJustified = async (a) => {
    try {
      await apiClient.patch(`/hr/absences/${a.id}`, { is_justified: !a.is_justified });
      load();
    } catch { toast.error("Erreur"); }
  };

  if (employees.length === 0) return <Empty label="Aucun employé enrôlé." />;

  return (
    <div data-testid="hr-absences">
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div className="flex-1 min-w-[220px]">
          <label className="text-xs font-medium text-slate-600 mb-1 block">Employé</label>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}
            data-testid="hr-absences-employee-select"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white">
            {employees.map((e) => (
              <option key={e.id} value={e.id}>{e.user?.full_name || e.name_snapshot}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-600 mb-1 block">Mois</label>
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="hr-absences-month"
            className="px-3 py-2 border border-slate-200 rounded-lg text-sm" />
        </div>
        <button onClick={scan} data-testid="hr-absences-scan-btn"
          className="px-3 py-2 bg-amber-500 hover:bg-amber-600 text-white text-sm rounded-lg flex items-center gap-2">
          <Search size={14} /> Scanner depuis les logs
        </button>
      </div>

      {scanResults.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4" data-testid="hr-absences-scan-results">
          <p className="text-sm font-semibold text-amber-900 mb-2">
            {scanResults.length} jour(s) ouvré(s) sans aucun accès :
          </p>
          <div className="flex flex-wrap gap-2">
            {scanResults.map((s) => (
              <button key={s.date} onClick={() => persistSuggestion(s)}
                data-testid={`hr-absences-suggest-${s.date}`}
                className="px-2.5 py-1 bg-white border border-amber-300 hover:bg-amber-100 text-xs rounded">
                + {s.date} ({s.weekday}) {s.suggested_hours}h
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4">
        <p className="text-sm font-semibold text-slate-700 mb-2">Enregistrer une absence manuelle</p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            data-testid="hr-absences-form-start" className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            data-testid="hr-absences-form-end" className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <input type="number" value={form.hours_count} step="0.5" onChange={(e) => setForm({ ...form, hours_count: parseFloat(e.target.value || 0) })}
            data-testid="hr-absences-form-hours" placeholder="Heures" className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <select value={form.abs_type} onChange={(e) => setForm({ ...form, abs_type: e.target.value })}
            data-testid="hr-absences-form-type" className="px-2 py-1.5 border border-slate-200 rounded text-sm">
            <option value="non_justifiee">Non justifiée</option>
            <option value="maladie">Maladie</option>
            <option value="conge">Congé</option>
            <option value="personnelle">Personnelle</option>
            <option value="autre">Autre</option>
          </select>
          <button onClick={submit} data-testid="hr-absences-form-submit"
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded flex items-center gap-1">
            <Plus size={14} /> Ajouter
          </button>
        </div>
        <div className="mt-2 flex gap-2 items-center">
          <label className="flex items-center gap-1 text-xs text-slate-600">
            <input type="checkbox" checked={form.is_justified}
              data-testid="hr-absences-form-justified"
              onChange={(e) => setForm({ ...form, is_justified: e.target.checked })} />
            Justifiée
          </label>
          <input type="text" value={form.justification} placeholder="Motif/justification (optionnel)"
            onChange={(e) => setForm({ ...form, justification: e.target.value })}
            data-testid="hr-absences-form-justif"
            className="flex-1 px-2 py-1.5 border border-slate-200 rounded text-sm" />
        </div>
      </div>

      {loading ? <Empty label="Chargement…" /> : items.length === 0 ? <Empty label="Aucune absence ce mois." /> : (
        <div className="border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="px-3 py-2 text-left">Période</th>
                <th className="px-3 py-2 text-right">Heures</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-left">Justification</th>
                <th className="px-3 py-2 text-center">Statut</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-t border-slate-100" data-testid={`hr-absence-row-${a.id}`}>
                  <td className="px-3 py-2">
                    {a.start_date}{a.end_date !== a.start_date ? ` → ${a.end_date}` : ""}
                    {a.auto_detected && <span className="ml-1 text-xs text-amber-600">(auto)</span>}
                  </td>
                  <td className="px-3 py-2 text-right">{a.hours_count}h</td>
                  <td className="px-3 py-2">{a.abs_type}</td>
                  <td className="px-3 py-2 text-slate-600 text-xs">{a.justification || "—"}</td>
                  <td className="px-3 py-2 text-center">
                    <button onClick={() => toggleJustified(a)}
                      data-testid={`hr-absence-toggle-${a.id}`}
                      className={`px-2 py-0.5 text-xs rounded ${a.is_justified ? "bg-emerald-100 text-emerald-700" : "bg-rose-100 text-rose-700"}`}>
                      {a.is_justified ? "Justifiée" : "Non justifiée"}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => remove(a)} data-testid={`hr-absence-delete-${a.id}`}
                      className="p-1.5 hover:bg-rose-50 text-rose-600 rounded">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Taxes tab
// =====================================================================
export function TaxesTab() {
  const [taxes, setTaxes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/hr/taxes");
      setTaxes(r.data || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const addLine = () => {
    if (taxes.length >= 5) { toast.error("Maximum 5 taxes"); return; }
    setTaxes([...taxes, { label: "", calc_type: "percentage", value: 0, applies_to: "gross", active: true, sort_order: taxes.length }]);
  };
  const updateLine = (idx, field, val) => {
    const next = [...taxes];
    next[idx] = { ...next[idx], [field]: val };
    setTaxes(next);
  };
  const removeLine = (idx) => setTaxes(taxes.filter((_, i) => i !== idx));

  const save = async () => {
    setSaving(true);
    try {
      const payload = { taxes: taxes.map((t, i) => ({ ...t, sort_order: i })) };
      const r = await apiClient.put("/hr/taxes", payload);
      setTaxes(r.data || []);
      toast.success("Taxes enregistrées");
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); } finally { setSaving(false); }
  };

  return (
    <div data-testid="hr-taxes">
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-slate-600">Jusqu'à 5 taxes configurables (libellé, % ou montant fixe).</p>
        <div className="flex gap-2">
          <button onClick={addLine} disabled={taxes.length >= 5} data-testid="hr-taxes-add-btn"
            className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm rounded disabled:opacity-50 flex items-center gap-1">
            <Plus size={14} /> Ajouter une taxe
          </button>
          <button onClick={save} disabled={saving} data-testid="hr-taxes-save-btn"
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded flex items-center gap-1 disabled:opacity-60">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Enregistrer
          </button>
        </div>
      </div>
      {loading ? <Empty label="Chargement…" /> : (
        <div className="border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="px-3 py-2 text-left">Libellé</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-right">Valeur</th>
                <th className="px-3 py-2 text-center">Actif</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {taxes.length === 0 ? (
                <tr><td colSpan={5} className="text-center py-6 text-slate-400 italic text-sm">Aucune taxe configurée.</td></tr>
              ) : taxes.map((t, idx) => (
                <tr key={idx} className="border-t border-slate-100" data-testid={`hr-tax-row-${idx}`}>
                  <td className="px-3 py-2">
                    <input value={t.label} onChange={(e) => updateLine(idx, "label", e.target.value)}
                      data-testid={`hr-tax-label-${idx}`} placeholder="Ex: IRPP, CNSS"
                      className="w-full px-2 py-1 border border-slate-200 rounded text-sm" />
                  </td>
                  <td className="px-3 py-2">
                    <select value={t.calc_type} onChange={(e) => updateLine(idx, "calc_type", e.target.value)}
                      data-testid={`hr-tax-type-${idx}`}
                      className="px-2 py-1 border border-slate-200 rounded text-sm">
                      <option value="percentage">Pourcentage (%)</option>
                      <option value="fixed">Montant fixe</option>
                    </select>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <input type="number" step="0.01" value={t.value}
                      onChange={(e) => updateLine(idx, "value", parseFloat(e.target.value || 0))}
                      data-testid={`hr-tax-value-${idx}`}
                      className="w-24 px-2 py-1 border border-slate-200 rounded text-sm text-right" />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <input type="checkbox" checked={t.active}
                      data-testid={`hr-tax-active-${idx}`}
                      onChange={(e) => updateLine(idx, "active", e.target.checked)} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => removeLine(idx)} data-testid={`hr-tax-delete-${idx}`}
                      className="p-1.5 hover:bg-rose-50 text-rose-600 rounded">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Advances tab
// =====================================================================
export function AdvancesTab({ employees }) {
  const [employeeId, setEmployeeId] = useState(employees[0]?.id || "");
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ amount: 0, currency: "XOF", motive: "", auto_deduct: true });
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!employeeId) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/advances?employee_id=${employeeId}`);
      setItems(r.data || []);
    } finally { setLoading(false); }
  }, [employeeId]);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    if (!form.amount) { toast.error("Montant requis"); return; }
    try {
      await apiClient.post("/hr/advances", { ...form, employee_id: employeeId });
      toast.success("Avance enregistrée");
      setForm({ amount: 0, currency: form.currency, motive: "", auto_deduct: true });
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const repay = async (a) => {
    const v = window.prompt(`Montant à imputer (max ${a.amount - a.repaid_amount}) ?`, "0");
    if (!v) return;
    const amount = parseFloat(v);
    if (!amount || amount <= 0) return;
    try {
      await apiClient.post(`/hr/advances/${a.id}/repay`, { repaid_amount: amount });
      toast.success("Remboursement enregistré");
      load();
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };

  const remove = async (a) => {
    if (!window.confirm("Supprimer cette avance ?")) return;
    try {
      await apiClient.delete(`/hr/advances/${a.id}`);
      toast.success("Supprimée");
      load();
    } catch { toast.error("Erreur"); }
  };

  if (employees.length === 0) return <Empty label="Aucun employé enrôlé." />;

  return (
    <div data-testid="hr-advances">
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div className="flex-1 min-w-[220px]">
          <label className="text-xs font-medium text-slate-600 mb-1 block">Employé</label>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}
            data-testid="hr-advances-employee-select"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white">
            {employees.map((e) => (<option key={e.id} value={e.id}>{e.user?.full_name || e.name_snapshot}</option>))}
          </select>
        </div>
      </div>
      <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4">
        <p className="text-sm font-semibold text-slate-700 mb-2">Nouvelle avance</p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <input type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: parseFloat(e.target.value || 0) })}
            data-testid="hr-advances-form-amount" placeholder="Montant"
            className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <input value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
            data-testid="hr-advances-form-currency" placeholder="XOF"
            className="px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <input value={form.motive} onChange={(e) => setForm({ ...form, motive: e.target.value })}
            data-testid="hr-advances-form-motive" placeholder="Motif (ex: santé, urgence)"
            className="md:col-span-2 px-2 py-1.5 border border-slate-200 rounded text-sm" />
          <button onClick={submit} data-testid="hr-advances-form-submit"
            className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded flex items-center gap-1">
            <Plus size={14} /> Accorder
          </button>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-600 mt-2">
          <input type="checkbox" checked={form.auto_deduct}
            data-testid="hr-advances-form-auto-deduct"
            onChange={(e) => setForm({ ...form, auto_deduct: e.target.checked })} />
          Déduire automatiquement sur la prochaine paie
        </label>
      </div>
      {loading ? <Empty label="Chargement…" /> : items.length === 0 ? <Empty label="Aucune avance." /> : (
        <div className="border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm min-w-[700px]">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2 text-left">Motif</th>
                <th className="px-3 py-2 text-right">Montant</th>
                <th className="px-3 py-2 text-right">Remboursé</th>
                <th className="px-3 py-2 text-right">Restant</th>
                <th className="px-3 py-2 text-center">Statut</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-t border-slate-100" data-testid={`hr-advance-row-${a.id}`}>
                  <td className="px-3 py-2">{a.granted_at}</td>
                  <td className="px-3 py-2 text-slate-600">{a.motive || "—"}</td>
                  <td className="px-3 py-2 text-right font-medium">{FCFA(a.amount)} {a.currency}</td>
                  <td className="px-3 py-2 text-right">{FCFA(a.repaid_amount)} {a.currency}</td>
                  <td className="px-3 py-2 text-right text-emerald-700">{FCFA(a.amount - a.repaid_amount)} {a.currency}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`px-2 py-0.5 text-xs rounded ${
                      a.status === "repaid" ? "bg-emerald-100 text-emerald-700" :
                      a.status === "partial" ? "bg-amber-100 text-amber-700" :
                      "bg-slate-200 text-slate-700"
                    }`}>
                      {a.status === "repaid" ? "Soldée" : a.status === "partial" ? "Partielle" : "En cours"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex gap-1 justify-end">
                      {a.status !== "repaid" && (
                        <button onClick={() => repay(a)} data-testid={`hr-advance-repay-${a.id}`}
                          className="px-2 py-1 text-xs bg-emerald-100 hover:bg-emerald-200 text-emerald-700 rounded">
                          Rembourser
                        </button>
                      )}
                      <button onClick={() => remove(a)} data-testid={`hr-advance-delete-${a.id}`}
                        className="p-1.5 hover:bg-rose-50 text-rose-600 rounded">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Payslips tab
// =====================================================================
export function PayslipsTab({ employees }) {
  const today = new Date();
  const defaultMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [employeeId, setEmployeeId] = useState(employees[0]?.id || "");
  const [month, setMonth] = useState(defaultMonth);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const compute = useCallback(async () => {
    if (!employeeId) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/employees/${employeeId}/payslip?month=${month}`);
      setData(r.data);
    } catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); setData(null); }
    finally { setLoading(false); }
  }, [employeeId, month]);

  useEffect(() => { compute(); }, [compute]);

  const downloadPdf = async () => {
    try {
      const resp = await apiClient.get(`/hr/employees/${employeeId}/payslip.pdf?month=${month}`, { responseType: "blob" });
      const blob = new Blob([resp.data], { type: "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `paie_${data?.employee?.full_name || employeeId}_${month}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (err) { toast.error("Erreur PDF"); }
  };

  if (employees.length === 0) return <Empty label="Aucun employé enrôlé." />;

  return (
    <div data-testid="hr-payslips">
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div className="flex-1 min-w-[220px]">
          <label className="text-xs font-medium text-slate-600 mb-1 block">Employé</label>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}
            data-testid="hr-payslips-employee-select"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white">
            {employees.map((e) => (<option key={e.id} value={e.id}>{e.user?.full_name || e.name_snapshot}</option>))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-600 mb-1 block">Mois</label>
          <input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
            data-testid="hr-payslips-month"
            className="px-3 py-2 border border-slate-200 rounded-lg text-sm" />
        </div>
        <button onClick={compute} data-testid="hr-payslips-refresh"
          className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm rounded-lg flex items-center gap-2">
          <RefreshCw size={14} /> Recalculer
        </button>
        <button onClick={downloadPdf} disabled={!data} data-testid="hr-payslips-pdf-btn"
          className="px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
          <Download size={14} /> Télécharger PDF
        </button>
      </div>

      {loading ? <Empty label="Calcul…" /> : !data ? <Empty label="Sélectionnez un employé." /> : (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="hr-payslip-gains">
            <h4 className="text-sm font-semibold text-slate-700 mb-3">Gains</h4>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-slate-600">Brut estimé</span><span className="font-medium">{FCFA(data.gross)} {data.employee.currency}</span></div>
              <div className="flex justify-between"><span className="text-slate-600">Heures faites</span><span>{data.hours_worked}h / {data.expected_hours}h</span></div>
              {(data.allowances || []).length > 0 && (
                <>
                  <div className="pt-2 mt-1 border-t border-slate-100 text-[11px] uppercase tracking-wider text-indigo-700 font-semibold">Indemnités fixes</div>
                  {data.allowances.map((al) => (
                    <div key={al.id} className="flex justify-between" data-testid={`payslip-allowance-${al.id}`}>
                      <span className="text-slate-600">{al.label}</span>
                      <span className="text-indigo-700">+ {FCFA(al.amount)} {data.employee.currency}</span>
                    </div>
                  ))}
                  <div className="flex justify-between font-medium">
                    <span className="text-slate-600">Total indemnités</span>
                    <span className="text-indigo-700">+ {FCFA(data.total_allowances)} {data.employee.currency}</span>
                  </div>
                </>
              )}
              {(data.bonuses || []).length > 0 && (
                <>
                  <div className="pt-2 mt-1 border-t border-slate-100 text-[11px] uppercase tracking-wider text-amber-600 font-semibold">Primes du mois</div>
                  {data.bonuses.map((b) => (
                    <div key={b.id} className="flex justify-between" data-testid={`payslip-bonus-${b.id}`}>
                      <span className="text-slate-600">{b.label}</span>
                      <span className="text-amber-700">+ {FCFA(b.amount)} {data.employee.currency}</span>
                    </div>
                  ))}
                  <div className="flex justify-between font-medium">
                    <span className="text-slate-600">Total primes</span>
                    <span className="text-amber-700">+ {FCFA(data.total_bonuses)} {data.employee.currency}</span>
                  </div>
                </>
              )}
              {(data.total_allowances > 0 || data.total_bonuses > 0) && (
                <div className="flex justify-between pt-2 mt-1 border-t border-slate-200 font-bold">
                  <span className="text-slate-700">Brut total (avec gains)</span>
                  <span className="text-slate-900">{FCFA(data.gross_with_gains || data.gross)} {data.employee.currency}</span>
                </div>
              )}
            </div>
            <h4 className="text-sm font-semibold text-slate-700 mb-2 mt-4">Absences</h4>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-slate-600">Justifiées</span><span>{data.absence_hours.justified}h</span></div>
              <div className="flex justify-between"><span className="text-slate-600">Non justifiées</span><span>{data.absence_hours.unjustified}h</span></div>
              <div className="flex justify-between"><span className="text-slate-600">Seuil toléré</span><span>{data.absence_threshold_hours}h</span></div>
              <div className="flex justify-between text-rose-600"><span>Déduction</span><span>- {FCFA(data.absence_deduction)} {data.employee.currency}</span></div>
            </div>
          </div>
          <div className="bg-white border border-slate-200 rounded-xl p-4" data-testid="hr-payslip-retenues">
            <h4 className="text-sm font-semibold text-slate-700 mb-3">Retenues</h4>
            <div className="space-y-1 text-sm">
              {data.taxes.length === 0 ? (
                <p className="text-xs text-slate-400 italic">Aucune taxe configurée. Configurez via l'onglet Taxes.</p>
              ) : data.taxes.map((t) => (
                <div key={t.id} className="flex justify-between">
                  <span className="text-slate-600">{t.label} ({t.calc_type === "percentage" ? `${t.value}%` : `${FCFA(t.value)} ${data.employee.currency}`})</span>
                  <span>- {FCFA(t.amount)} {data.employee.currency}</span>
                </div>
              ))}
              <div className="flex justify-between border-t pt-1 text-rose-600 font-medium">
                <span>Total taxes</span><span>- {FCFA(data.total_taxes)} {data.employee.currency}</span>
              </div>
            </div>
            {data.advances.length > 0 && (
              <>
                <h4 className="text-sm font-semibold text-slate-700 mb-2 mt-4">Avances déduites</h4>
                <div className="space-y-1 text-sm">
                  {data.advances.map((a) => (
                    <div key={a.id} className="flex justify-between">
                      <span className="text-slate-600">{a.motive || "Avance"}</span>
                      <span>- {FCFA(a.remaining)} {data.employee.currency}</span>
                    </div>
                  ))}
                  <div className="flex justify-between border-t pt-1 text-rose-600 font-medium">
                    <span>Total avances</span><span>- {FCFA(data.advances_deduction)} {data.employee.currency}</span>
                  </div>
                </div>
              </>
            )}
            <div className="mt-4 bg-slate-900 text-white rounded-lg p-3" data-testid="hr-payslip-net">
              <div className="flex justify-between items-center">
                <span className="text-xs uppercase tracking-wider text-slate-300">Net à payer</span>
                <span className="text-2xl font-bold">{FCFA(data.net)} {data.employee.currency}</span>
              </div>
            </div>
            {/* Iter38r-fix9j — Bouton "Payer via Mobile Money" (PawaPay Payouts) */}
            {data.net > 0 && (
              <button
                type="button"
                onClick={async () => {
                  const phone = data.employee?.whatsapp || data.employee?.phone || "";
                  if (!phone) {
                    toast.error("Aucun numéro Mobile Money configuré pour cet employé");
                    return;
                  }
                  if (!window.confirm(`Payer ${FCFA(data.net)} XOF à ${data.employee.full_name} (${phone}) via Mobile Money ?\n\nVous serez redirigé(e) vers la page Payouts pour confirmer le provider et envoyer.`)) return;
                  // Pre-fill via URL params and navigate
                  const params = new URLSearchParams({
                    amount: String(Math.round(data.net)),
                    msisdn: phone.replace(/\D/g, ""),
                    message: `Paie ${month}`.slice(0, 22),
                    related_kind: "payroll",
                    related_id: `${employeeId}:${month}`,
                  });
                  window.location.href = `/portal/payouts?${params.toString()}`;
                }}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-2 text-sm font-medium"
                data-testid="hr-payslip-pay-mobilemoney"
              >
                💸 Payer via Mobile Money
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Settings tab (thresholds + payslip template)
// =====================================================================
export function HrSettingsTab() {
  const [data, setData] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiClient.get("/hr/settings").then((r) => setData(r.data)).catch(() => setData({}));
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await apiClient.patch("/hr/settings", data);
      setData(r.data);
      toast.success("Réglages enregistrés");
    } catch (err) { toast.error("Erreur"); } finally { setSaving(false); }
  };

  if (!data) return <Empty label="Chargement…" />;
  const upd = (k, v) => setData({ ...data, [k]: v });

  return (
    <div data-testid="hr-settings" className="max-w-3xl space-y-4">
      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Seuil d'absence toléré</h3>
        <div className="flex items-center gap-2">
          <input type="number" value={data.absence_threshold_hours || 0} step="0.5"
            onChange={(e) => upd("absence_threshold_hours", parseFloat(e.target.value || 0))}
            data-testid="hr-settings-threshold"
            className="w-32 px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          <span className="text-sm text-slate-600">heures d'absence non justifiée tolérées par mois avant déduction sur le net.</span>
        </div>
        <p className="text-xs text-slate-400 mt-2">Override possible par employé (champ optionnel sur sa fiche). Si ce seuil est dépassé, l'excédent est facturé au taux horaire de l'employé.</p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">Modèle de fiche de paie (PDF)</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Nom employeur</label>
            <input value={data.payslip_company_name || ""} onChange={(e) => upd("payslip_company_name", e.target.value)}
              data-testid="hr-settings-payslip-name"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">N° employeur</label>
            <input value={data.payslip_employer_id || ""} onChange={(e) => upd("payslip_employer_id", e.target.value)}
              data-testid="hr-settings-payslip-empid"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs text-slate-500 mb-1 block">Adresse</label>
            <textarea value={data.payslip_address || ""} onChange={(e) => upd("payslip_address", e.target.value)}
              data-testid="hr-settings-payslip-address"
              rows={2} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs text-slate-500 mb-1 block">Mentions légales</label>
            <textarea value={data.payslip_legal_mentions || ""} onChange={(e) => upd("payslip_legal_mentions", e.target.value)}
              data-testid="hr-settings-payslip-legal"
              rows={2} className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div className="md:col-span-2">
            <label className="text-xs text-slate-500 mb-1 block">Pied de page</label>
            <input value={data.payslip_footer || ""} onChange={(e) => upd("payslip_footer", e.target.value)}
              data-testid="hr-settings-payslip-footer"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
        </div>
      </div>
      <div className="flex justify-end">
        <button onClick={save} disabled={saving} data-testid="hr-settings-save-btn"
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Enregistrer
        </button>
      </div>
    </div>
  );
}


// =====================================================================
// Iter38m — Holidays tab (Jours fériés)
// Allows admins / supervisors / Comptable to manage the list of public
// holidays of the year (CRUD + bulk import for the current country).
// =====================================================================
export function HolidaysTab() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null);
  const [country, setCountry] = useState("");
  const [importing, setImporting] = useState(false);

  // Fetch tenant country (BF default) for the import button label.
  useEffect(() => {
    apiClient.get("/me/tenant-meta")
      .then((r) => setCountry((r.data?.country_code || "BF").toUpperCase()))
      .catch(() => setCountry("BF"));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/holidays?year=${year}`);
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  }, [year]);

  useEffect(() => { load(); }, [load]);

  const doImport = async () => {
    if (!window.confirm(`Importer les jours fériés ${year} (${country || "BF"}) ?`)) return;
    setImporting(true);
    try {
      const r = await apiClient.post(`/hr/holidays/import?year=${year}${country ? `&country=${country}` : ""}`);
      const d = r.data || {};
      toast.success(`Importés: ${d.created_count || 0} · Ignorés (déjà présents): ${d.skipped_count || 0}`);
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'import");
    } finally { setImporting(false); }
  };

  const remove = async (h) => {
    if (!window.confirm(`Supprimer "${h.label}" du ${h.date} ?`)) return;
    try {
      await apiClient.delete(`/hr/holidays/${h.id}`);
      toast.success("Jour férié supprimé");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div data-testid="hr-holidays-tab" className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <label className="text-xs text-slate-500 mb-1 block">Année</label>
          <input
            type="number"
            value={year}
            min={2000}
            max={2100}
            onChange={(e) => setYear(parseInt(e.target.value || currentYear, 10))}
            data-testid="hr-holidays-year"
            className="w-24 px-3 py-2 border border-slate-200 rounded-lg text-sm"
          />
        </div>
        <button
          onClick={doImport}
          disabled={importing}
          data-testid="hr-holidays-import-btn"
          className="px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60"
          title={`Importe les jours fériés fixes ${country || "BF"} pour l'année sélectionnée. Les fêtes mobiles (Aïd, Mawlid) restent à saisir manuellement.`}
        >
          {importing ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          Importer fêtes {year} ({country || "BF"})
        </button>
        <button
          onClick={() => setCreating(true)}
          data-testid="hr-holidays-add-btn"
          className="px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2"
        >
          <Plus size={14} /> Ajouter un jour férié
        </button>
        <button onClick={load} className="p-2 text-slate-500 hover:text-slate-800" title="Rafraîchir" data-testid="hr-holidays-refresh">
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 flex items-start gap-2">
        <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
        <div>
          Les fêtes <strong>fixes</strong> (Indépendance, Travail, Noël…) sont importées automatiquement.
          Les fêtes <strong>mobiles</strong> (Aïd el-Fitr, Aïd el-Kébir, Mawlid) changent chaque année — saisissez-les manuellement.
        </div>
      </div>

      {loading ? (
        <Empty label="Chargement…" />
      ) : items.length === 0 ? (
        <Empty label={`Aucun jour férié pour ${year}. Cliquez sur "Importer" ou "Ajouter".`} />
      ) : (
        <div className="border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2 text-left">Jour</th>
                <th className="px-3 py-2 text-left">Libellé</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-center">Payé</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((h) => {
                const d = new Date(`${h.date}T00:00:00Z`);
                const weekday = d.toLocaleDateString("fr-FR", { weekday: "long", timeZone: "UTC" });
                return (
                  <tr key={h.id} className="border-t border-slate-100" data-testid={`hr-holiday-row-${h.id}`}>
                    <td className="px-3 py-2 font-mono text-xs">{h.date}</td>
                    <td className="px-3 py-2 text-slate-600 capitalize">{weekday}</td>
                    <td className="px-3 py-2 font-medium">{h.label}</td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        h.holiday_type === "national" ? "bg-blue-100 text-blue-700"
                        : h.holiday_type === "religious" ? "bg-violet-100 text-violet-700"
                        : "bg-slate-100 text-slate-700"
                      }`}>
                        {h.holiday_type === "national" ? "National" : h.holiday_type === "religious" ? "Religieux" : h.holiday_type === "local" ? "Local" : "Autre"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-center">
                      {h.is_paid ? <span className="text-emerald-600">✓</span> : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => setEditing(h)} className="p-1.5 hover:bg-blue-50 text-blue-600 rounded" data-testid={`hr-holiday-edit-${h.id}`} title="Modifier">
                        <Edit2 size={14} />
                      </button>
                      <button onClick={() => remove(h)} className="p-1.5 hover:bg-rose-50 text-rose-600 rounded ml-1" data-testid={`hr-holiday-delete-${h.id}`} title="Supprimer">
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(creating || editing) && (
        <HolidayFormModal
          initial={editing}
          year={year}
          onSave={() => { setCreating(false); setEditing(null); load(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function HolidayFormModal({ initial, year, onSave, onCancel }) {
  const isEdit = !!initial;
  const [form, setForm] = useState(initial || {
    date: `${year}-01-01`,
    label: "",
    holiday_type: "national",
    is_paid: true,
  });
  const [saving, setSaving] = useState(false);
  const submit = async () => {
    if (!form.date || !form.label) { toast.error("Date et libellé requis"); return; }
    setSaving(true);
    try {
      if (isEdit) {
        await apiClient.patch(`/hr/holidays/${initial.id}`, form);
        toast.success("Jour férié modifié");
      } else {
        await apiClient.post("/hr/holidays", form);
        toast.success("Jour férié ajouté");
      }
      onSave();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="hr-holiday-form-modal">
      <div className="bg-white rounded-2xl max-w-md w-full shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-lg font-semibold text-slate-900">{isEdit ? "Modifier" : "Ajouter"} un jour férié</h3>
          <button onClick={onCancel} className="text-slate-400" data-testid="hr-holiday-form-close"><X size={20} /></button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Date *</label>
            <input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })}
              data-testid="hr-holiday-form-date"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Libellé *</label>
            <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="Ex: Fête de l'Indépendance"
              data-testid="hr-holiday-form-label"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 mb-1 block">Type</label>
            <select value={form.holiday_type} onChange={(e) => setForm({ ...form, holiday_type: e.target.value })}
              data-testid="hr-holiday-form-type"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm">
              <option value="national">National</option>
              <option value="religious">Religieux</option>
              <option value="local">Local</option>
              <option value="other">Autre</option>
            </select>
          </div>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input type="checkbox" checked={form.is_paid} onChange={(e) => setForm({ ...form, is_paid: e.target.checked })}
              data-testid="hr-holiday-form-paid" />
            Jour férié payé
          </label>
        </div>
        <div className="flex justify-end gap-2 p-5 border-t border-slate-100">
          <button onClick={onCancel} className="px-4 py-2 text-sm text-slate-600" data-testid="hr-holiday-form-cancel">Annuler</button>
          <button onClick={submit} disabled={saving} data-testid="hr-holiday-form-submit"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} {isEdit ? "Enregistrer" : "Ajouter"}
          </button>
        </div>
      </div>
    </div>
  );
}
