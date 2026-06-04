/*
 * Iter38 — GRH (Gestion des Ressources Humaines).
 *
 * Phases livrées :
 *  1. Personnel — Liste, ajout, modification, suppression douce, restauration.
 *  2. Salaires  — Salaire de base, type (mensuel / horaire), devise.
 *  3. Présence  — Calcul automatique via access_logs (min/max par jour).
 *
 * Accès : admin / superviseur / tracked_role == "Comptable".
 */
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import {
  Users, UserPlus, Edit2, Trash2, RotateCcw, Calendar, Banknote,
  Briefcase, Building, X, Search, ChevronDown, RefreshCw, ArrowRight,
  AlertTriangle, Loader2,
} from "lucide-react";
import {
  WeeklyPresenceCard, AbsencesTab, TaxesTab, AdvancesTab, PayslipsTab, HrSettingsTab,
  HolidaysTab,
} from "./HumanResourcesAdvanced";
import PrimesIndemnitesTab from "./HrPrimesIndemnites";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const fmtDate = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("fr-FR"); }
  catch { return String(iso).slice(0, 10); }
};
const fmtHHMM = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }); }
  catch { return String(iso).slice(11, 16); }
};

function Empty({ label }) {
  return (
    <div className="text-center py-12 text-slate-400 text-sm italic" data-testid="hr-empty-state">
      {label}
    </div>
  );
}

function Tabs({ tab, setTab, hideTimesheet }) {
  const tabs = [
    { id: "personnel", label: "Personnel", icon: Users },
    { id: "salaries", label: "Salaires", icon: Banknote },
  ];
  if (!hideTimesheet) tabs.push({ id: "timesheet", label: "Présence", icon: Calendar });
  tabs.push({ id: "absences", label: "Absences", icon: Calendar });
  tabs.push({ id: "holidays", label: "Jours fériés", icon: Calendar });
  tabs.push({ id: "taxes", label: "Taxes", icon: Banknote });
  tabs.push({ id: "advances", label: "Avances", icon: Banknote });
  tabs.push({ id: "primes", label: "Primes & Indemnités", icon: Banknote });
  tabs.push({ id: "payslips", label: "Paie", icon: Briefcase });
  tabs.push({ id: "settings", label: "Réglages", icon: Briefcase });
  return (
    <div className="flex gap-1 mb-6 border-b border-slate-200 overflow-x-auto" data-testid="hr-tabs">
      {tabs.map((t) => {
        const Icon = t.icon;
        return (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            data-testid={`hr-tab-${t.id}`}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              tab === t.id
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            <Icon size={16} /> {t.label}
          </button>
        );
      })}
    </div>
  );
}

// =====================================================================
// Create / Edit Employee modal
// =====================================================================
function EmployeeForm({ employee, eligibleUsers, onSave, onCancel }) {
  const isEdit = !!employee;
  const [form, setForm] = useState(() => ({
    user_id: employee?.user_id || "",
    base_salary: employee?.base_salary ?? 0,
    pay_type: employee?.pay_type || "monthly",
    currency: employee?.currency || "XOF",
    hourly_rate: employee?.hourly_rate ?? 0,
    monthly_hours_baseline: employee?.monthly_hours_baseline ?? 160,
    department: employee?.department || "",
    job_title: employee?.job_title || "",
    notes: employee?.notes || "",
  }));
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!isEdit && !form.user_id) { toast.error("Sélectionnez un utilisateur"); return; }
    setSaving(true);
    try {
      if (isEdit) {
        const payload = { ...form };
        delete payload.user_id;
        await apiClient.patch(`/hr/employees/${employee.id}`, payload);
        toast.success("Employé mis à jour");
      } else {
        await apiClient.post("/hr/employees", form);
        toast.success("Employé ajouté");
      }
      onSave();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" data-testid="hr-employee-modal">
      <div className="bg-white rounded-2xl max-w-2xl w-full shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-slate-100">
          <h3 className="text-lg font-semibold text-slate-900">
            {isEdit ? "Modifier la fiche" : "Ajouter un employé"}
          </h3>
          <button onClick={onCancel} className="text-slate-400 hover:text-slate-600" data-testid="hr-employee-modal-close">
            <X size={20} />
          </button>
        </div>
        <div className="p-5 space-y-4">
          {!isEdit && (
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Utilisateur à enrôler *</label>
              <select
                value={form.user_id}
                onChange={(e) => setForm({ ...form, user_id: e.target.value })}
                data-testid="hr-employee-user-select"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
              >
                <option value="">— Choisir —</option>
                {eligibleUsers.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name || u.email} ({u.role}{u.tracked_role ? `/${u.tracked_role}` : ""})
                  </option>
                ))}
              </select>
              {eligibleUsers.length === 0 && (
                <p className="text-xs text-amber-600 mt-1">
                  Tous les utilisateurs de ce tenant sont déjà enrôlés.
                </p>
              )}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Intitulé du poste</label>
              <input
                value={form.job_title}
                onChange={(e) => setForm({ ...form, job_title: e.target.value })}
                data-testid="hr-employee-job-title"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
                placeholder="Ex: Technicien support"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Département</label>
              <input
                value={form.department}
                onChange={(e) => setForm({ ...form, department: e.target.value })}
                data-testid="hr-employee-department"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
                placeholder="Ex: Support technique"
              />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Type de paie</label>
              <select
                value={form.pay_type}
                onChange={(e) => setForm({ ...form, pay_type: e.target.value })}
                data-testid="hr-employee-pay-type"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
              >
                <option value="monthly">Mensuel (prorata heures)</option>
                <option value="hourly">Horaire</option>
                <option value="fixed">Forfaitaire (montant fixe)</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Salaire base</label>
              <input
                type="number"
                value={form.base_salary}
                onChange={(e) => setForm({ ...form, base_salary: parseFloat(e.target.value || 0) })}
                data-testid="hr-employee-base-salary"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
                disabled={form.pay_type === "hourly"}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Devise</label>
              <input
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
                data-testid="hr-employee-currency"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
                maxLength={8}
              />
            </div>
          </div>
          {form.pay_type === "hourly" ? (
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Taux horaire ({form.currency}/h)</label>
              <input
                type="number"
                value={form.hourly_rate}
                onChange={(e) => setForm({ ...form, hourly_rate: parseFloat(e.target.value || 0) })}
                data-testid="hr-employee-hourly-rate"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
              />
            </div>
          ) : form.pay_type === "fixed" ? (
            <div className="rounded-lg ring-1 ring-amber-300 bg-amber-50 p-3 text-xs text-amber-800" data-testid="hr-employee-fixed-info">
              <strong>Mode forfaitaire :</strong> l'agent recevra exactement <strong>{form.base_salary} {form.currency}</strong> chaque mois, indépendamment des heures travaillées ou des absences. Idéal pour les recrutements en fin de mois, périodes d'essai ou prestataires au forfait.
            </div>
          ) : (
            <div>
              <label className="text-xs font-medium text-slate-600 mb-1 block">Heures mensuelles contractuelles</label>
              <input
                type="number"
                value={form.monthly_hours_baseline}
                onChange={(e) => setForm({ ...form, monthly_hours_baseline: parseFloat(e.target.value || 0) })}
                data-testid="hr-employee-baseline-hours"
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
              />
              <p className="text-xs text-slate-400 mt-1">Utilisé pour proratiser le salaire selon les heures réellement travaillées.</p>
            </div>
          )}
          <div>
            <label className="text-xs font-medium text-slate-600 mb-1 block">Notes</label>
            <textarea
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              data-testid="hr-employee-notes"
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm"
              rows={2}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 p-5 border-t border-slate-100">
          <button
            onClick={onCancel}
            data-testid="hr-employee-cancel-btn"
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800"
          >
            Annuler
          </button>
          <button
            onClick={submit}
            disabled={saving}
            data-testid="hr-employee-save-btn"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2 disabled:opacity-60"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : null}
            {isEdit ? "Enregistrer" : "Créer la fiche"}
          </button>
        </div>
      </div>
    </div>
  );
}

// =====================================================================
// Timesheet view
// =====================================================================
function TimesheetView({ employees }) {
  const today = new Date();
  const defaultMonth = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [selectedId, setSelectedId] = useState(employees[0]?.id || "");
  const [month, setMonth] = useState(defaultMonth);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const employee = useMemo(
    () => employees.find((e) => e.id === selectedId),
    [selectedId, employees]
  );

  const load = async () => {
    if (!selectedId) return;
    setLoading(true);
    try {
      const r = await apiClient.get(`/hr/employees/${selectedId}/timesheet?month=${month}`);
      setData(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
      setData(null);
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [selectedId, month]);

  return (
    <div data-testid="hr-timesheet">
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div className="flex-1 min-w-[220px]">
          <label className="text-xs font-medium text-slate-600 mb-1 block">Employé</label>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            data-testid="hr-timesheet-employee-select"
            className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-white"
          >
            {employees.map((e) => (
              <option key={e.id} value={e.id}>
                {e.user?.full_name || e.name_snapshot || e.user?.email}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs font-medium text-slate-600 mb-1 block">Mois</label>
          <input
            type="month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            data-testid="hr-timesheet-month-input"
            className="px-3 py-2 border border-slate-200 rounded-lg text-sm"
          />
        </div>
        <button
          onClick={load}
          data-testid="hr-timesheet-refresh-btn"
          className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm rounded-lg flex items-center gap-2"
        >
          <RefreshCw size={14} /> Recalculer
        </button>
      </div>

      {loading ? (
        <Empty label="Chargement…" />
      ) : !data ? (
        <Empty label="Sélectionnez un employé pour voir sa présence." />
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4" data-testid="hr-totals-days">
              <p className="text-xs text-blue-700 font-medium">Jours travaillés</p>
              <p className="text-2xl font-bold text-blue-900 mt-1">{data.totals.days_worked}</p>
            </div>
            <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-4" data-testid="hr-totals-hours">
              <p className="text-xs text-emerald-700 font-medium">Heures cumulées</p>
              <p className="text-2xl font-bold text-emerald-900 mt-1">{data.totals.hours_worked} h</p>
              <p className="text-xs text-emerald-600 mt-1">sur {data.totals.expected_hours} attendues</p>
            </div>
            <div className="bg-amber-50 border border-amber-100 rounded-xl p-4" data-testid="hr-totals-type">
              <p className="text-xs text-amber-700 font-medium">Mode de calcul</p>
              <p className="text-base font-semibold text-amber-900 mt-1">
                {data.totals.pay_type === "hourly" ? "Horaire" : data.totals.pay_type === "fixed" ? "Forfaitaire" : "Mensuel"}
              </p>
              {data.totals.pay_type === "hourly" ? (
                <p className="text-xs text-amber-600 mt-1">{FCFA(data.totals.hourly_rate)} {data.totals.currency}/h</p>
              ) : data.totals.pay_type === "fixed" ? (
                <p className="text-xs text-amber-600 mt-1">Forfait {FCFA(data.totals.base_salary)} {data.totals.currency} · indép. des heures</p>
              ) : (
                <p className="text-xs text-amber-600 mt-1">Base {FCFA(data.totals.base_salary)} {data.totals.currency}</p>
              )}
            </div>
            <div className="bg-slate-900 text-white rounded-xl p-4" data-testid="hr-totals-gross">
              <p className="text-xs text-slate-300 font-medium">Salaire brut estimé</p>
              <p className="text-2xl font-bold mt-1">{FCFA(data.totals.computed_gross)} {data.totals.currency}</p>
            </div>
          </div>

          {data.days.length === 0 ? (
            <Empty label="Aucun jour de présence sur ce mois." />
          ) : (
            <div className="border border-slate-200 rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-slate-600 text-xs">
                  <tr>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Premier accès</th>
                    <th className="px-3 py-2 text-left">Dernier accès</th>
                    <th className="px-3 py-2 text-right">Heures présence</th>
                    <th className="px-3 py-2 text-right">Hits</th>
                  </tr>
                </thead>
                <tbody>
                  {data.days.map((d) => (
                    <tr key={d.date} className="border-t border-slate-100" data-testid={`hr-timesheet-row-${d.date}`}>
                      <td className="px-3 py-2 font-medium">{fmtDate(d.date)}</td>
                      <td className="px-3 py-2 text-slate-600">{fmtHHMM(d.first_seen)}</td>
                      <td className="px-3 py-2 text-slate-600">{fmtHHMM(d.last_seen)}</td>
                      <td className="px-3 py-2 text-right font-medium">{d.presence_hours} h</td>
                      <td className="px-3 py-2 text-right text-slate-500">{d.hits}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-slate-400 mt-3 flex items-start gap-1">
            <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
            Présence calculée automatiquement comme la plage min(login)→max(dernière action) du jour, à partir des logs d'accès. Les phases Absences / Taxes / Avances / PDF mensuel arrivent ensuite.
          </p>
        </>
      )}
    </div>
  );
}

// =====================================================================
// Salaries (read-only view of all employees with computed gross of current month)
// =====================================================================
function SalariesTable({ employees, refresh }) {
  const today = new Date();
  const month = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  const [computed, setComputed] = useState({});  // {empId: timesheet}
  const [loading, setLoading] = useState(false);

  const recompute = async () => {
    setLoading(true);
    const next = {};
    for (const e of employees) {
      try {
        const r = await apiClient.get(`/hr/employees/${e.id}/timesheet?month=${month}`);
        next[e.id] = r.data.totals;
      } catch { next[e.id] = null; }
    }
    setComputed(next);
    setLoading(false);
  };

  useEffect(() => { if (employees.length) recompute(); /* eslint-disable-next-line */ }, [employees.length]);

  if (employees.length === 0) return <Empty label="Aucun employé enrôlé." />;

  return (
    <div data-testid="hr-salaries">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-slate-600">Synthèse {month}</p>
        <button
          onClick={recompute}
          disabled={loading}
          data-testid="hr-salaries-refresh-btn"
          className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs rounded-lg flex items-center gap-2 disabled:opacity-60"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Recalculer
        </button>
      </div>
      <div className="border border-slate-200 rounded-xl overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-slate-50 text-slate-600 text-xs">
            <tr>
              <th className="px-3 py-2 text-left">Employé</th>
              <th className="px-3 py-2 text-left">Poste</th>
              <th className="px-3 py-2 text-left">Type</th>
              <th className="px-3 py-2 text-right">Salaire base</th>
              <th className="px-3 py-2 text-right">Heures faites</th>
              <th className="px-3 py-2 text-right">Brut estimé ({month})</th>
            </tr>
          </thead>
          <tbody>
            {employees.map((e) => {
              const c = computed[e.id];
              return (
                <tr key={e.id} className="border-t border-slate-100" data-testid={`hr-salary-row-${e.id}`}>
                  <td className="px-3 py-2 font-medium">{e.user?.full_name || e.name_snapshot}</td>
                  <td className="px-3 py-2 text-slate-600">{e.job_title || "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{e.pay_type === "hourly" ? "Horaire" : e.pay_type === "fixed" ? "Forfaitaire" : "Mensuel"}</td>
                  <td className="px-3 py-2 text-right">
                    {e.pay_type === "hourly"
                      ? `${FCFA(e.hourly_rate)} ${e.currency}/h`
                      : `${FCFA(e.base_salary)} ${e.currency}${e.pay_type === "fixed" ? " · forfait" : ""}`}
                  </td>
                  <td className="px-3 py-2 text-right">{c ? `${c.hours_worked} h` : "…"}</td>
                  <td className="px-3 py-2 text-right font-semibold">
                    {c ? `${FCFA(c.computed_gross)} ${c.currency}` : "…"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// =====================================================================
// Personnel (CRUD)
// =====================================================================
function PersonnelTable({ employees, includeDeleted, setIncludeDeleted, eligibleUsers, refresh }) {
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter((e) =>
      (e.user?.full_name || e.name_snapshot || "").toLowerCase().includes(q) ||
      (e.user?.email || e.email_snapshot || "").toLowerCase().includes(q) ||
      (e.job_title || "").toLowerCase().includes(q) ||
      (e.department || "").toLowerCase().includes(q)
    );
  }, [employees, query]);

  const removeEmp = async (e) => {
    if (!window.confirm(`Retirer ${e.user?.full_name || e.name_snapshot} de la liste du personnel ?`)) return;
    try {
      await apiClient.delete(`/hr/employees/${e.id}`);
      toast.success("Employé retiré");
      refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const restoreEmp = async (e) => {
    try {
      await apiClient.post(`/hr/employees/${e.id}/restore`);
      toast.success("Employé restauré");
      refresh();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div data-testid="hr-personnel">
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-2.5 text-slate-400" size={16} />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher un employé…"
            data-testid="hr-personnel-search"
            className="w-full pl-9 pr-3 py-2 border border-slate-200 rounded-lg text-sm"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
            data-testid="hr-personnel-show-deleted"
          />
          Afficher les fiches supprimées
        </label>
        <button
          onClick={() => setCreating(true)}
          data-testid="hr-personnel-add-btn"
          className="px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg flex items-center gap-2"
        >
          <UserPlus size={16} /> Ajouter un employé
        </button>
      </div>

      {filtered.length === 0 ? (
        <Empty label="Aucun employé." />
      ) : (
        <div className="border border-slate-200 rounded-xl overflow-x-auto">
          <table className="w-full text-sm min-w-[800px]">
            <thead className="bg-slate-50 text-slate-600 text-xs">
              <tr>
                <th className="px-3 py-2 text-left">Matricule</th>
                <th className="px-3 py-2 text-left">Nom</th>
                <th className="px-3 py-2 text-left">Email</th>
                <th className="px-3 py-2 text-left">Poste</th>
                <th className="px-3 py-2 text-left">Département</th>
                <th className="px-3 py-2 text-left">Type</th>
                <th className="px-3 py-2 text-right">Salaire / Taux</th>
                <th className="px-3 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => {
                const isDeleted = !!e.deleted_at;
                return (
                  <tr
                    key={e.id}
                    className={`border-t border-slate-100 ${isDeleted ? "opacity-50" : ""}`}
                    data-testid={`hr-personnel-row-${e.id}`}
                  >
                    <td className="px-3 py-2 text-xs font-mono text-slate-600" data-testid={`hr-personnel-matricule-${e.id}`}>
                      {e.matricule || <span className="text-amber-600 italic">—</span>}
                    </td>
                    <td className="px-3 py-2 font-medium">
                      {e.user?.full_name || e.name_snapshot}
                      {isDeleted && <span className="ml-2 text-xs text-rose-600">(supprimée)</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{e.user?.email || e.email_snapshot}</td>
                    <td className="px-3 py-2 text-slate-600">{e.job_title || "—"}</td>
                    <td className="px-3 py-2 text-slate-600">{e.department || "—"}</td>
                    <td className="px-3 py-2 text-slate-600">{e.pay_type === "hourly" ? "Horaire" : "Mensuel"}</td>
                    <td className="px-3 py-2 text-right font-medium">
                      {e.pay_type === "hourly"
                        ? `${FCFA(e.hourly_rate)} ${e.currency}/h`
                        : `${FCFA(e.base_salary)} ${e.currency}`}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex items-center justify-end gap-1">
                        {isDeleted ? (
                          <button
                            onClick={() => restoreEmp(e)}
                            data-testid={`hr-restore-btn-${e.id}`}
                            className="p-1.5 hover:bg-emerald-50 text-emerald-600 rounded"
                            title="Restaurer"
                          >
                            <RotateCcw size={14} />
                          </button>
                        ) : (
                          <>
                            <button
                              onClick={() => setEditing(e)}
                              data-testid={`hr-edit-btn-${e.id}`}
                              className="p-1.5 hover:bg-slate-100 text-slate-600 rounded"
                              title="Modifier"
                            >
                              <Edit2 size={14} />
                            </button>
                            <button
                              onClick={() => removeEmp(e)}
                              data-testid={`hr-delete-btn-${e.id}`}
                              className="p-1.5 hover:bg-rose-50 text-rose-600 rounded"
                              title="Retirer"
                            >
                              <Trash2 size={14} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {(creating || editing) && (
        <EmployeeForm
          employee={editing}
          eligibleUsers={eligibleUsers}
          onSave={() => { setCreating(false); setEditing(null); refresh(); }}
          onCancel={() => { setCreating(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

// =====================================================================
// Main page
// =====================================================================
export default function HumanResources() {
  const { user } = useAuth();
  const isAdminOrSup = user?.role === "admin" || user?.role === "superviseur";
  const isComptable = (user?.tracked_role || "") === "Comptable";
  const allowed = isAdminOrSup || isComptable;

  const [tab, setTab] = useState("personnel");
  const [employees, setEmployees] = useState([]);
  const [eligible, setEligible] = useState([]);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const [empR, eligR] = await Promise.all([
        apiClient.get(`/hr/employees?include_deleted=${includeDeleted}`),
        apiClient.get("/hr/eligible-users"),
      ]);
      setEmployees(empR.data || []);
      setEligible(eligR.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };

  useEffect(() => { if (allowed) refresh(); /* eslint-disable-next-line */ }, [includeDeleted, allowed]);

  if (!allowed) {
    return (
      <div className="p-6 text-center text-slate-500" data-testid="hr-access-denied">
        Module réservé aux administrateurs, superviseurs et comptables.
      </div>
    );
  }

  const activeEmployees = employees.filter((e) => !e.deleted_at);

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" data-testid="hr-page">
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
            <Briefcase className="text-blue-600" size={20} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Ressources Humaines</h1>
            <p className="text-sm text-slate-500">
              Personnel · Salaires · Présence · Absences · Jours fériés · Taxes · Avances · Paie
            </p>
          </div>
        </div>
      </div>

      <Tabs tab={tab} setTab={setTab} />

      {loading ? (
        <Empty label="Chargement…" />
      ) : tab === "personnel" ? (
        <>
          <WeeklyPresenceCard />
          <PersonnelTable
            employees={employees}
            includeDeleted={includeDeleted}
            setIncludeDeleted={setIncludeDeleted}
            eligibleUsers={eligible}
            refresh={refresh}
          />
        </>
      ) : tab === "salaries" ? (
        <SalariesTable employees={activeEmployees} refresh={refresh} />
      ) : tab === "timesheet" ? (
        <TimesheetView employees={activeEmployees} />
      ) : tab === "absences" ? (
        <AbsencesTab employees={activeEmployees} />
      ) : tab === "holidays" ? (
        <HolidaysTab />
      ) : tab === "taxes" ? (
        <TaxesTab />
      ) : tab === "advances" ? (
        <AdvancesTab employees={activeEmployees} />
      ) : tab === "primes" ? (
        <PrimesIndemnitesTab employees={activeEmployees} />
      ) : tab === "payslips" ? (
        <PayslipsTab employees={activeEmployees} />
      ) : tab === "settings" ? (
        <HrSettingsTab />
      ) : null}
    </div>
  );
}
