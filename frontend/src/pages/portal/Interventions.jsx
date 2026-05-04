import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Plus, X, RefreshCw, Trash2, Wrench } from "lucide-react";
import { toast } from "sonner";

const ELEVATED = new Set(["Moderation", "Administrateur", "Superviseur"]);
const ADMIN_LEVEL = new Set(["Administrateur", "Superviseur"]);
function isElevated(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ELEVATED.has(user.tracked_role);
}
function canDelete(user) {
  if (!user) return false;
  if (user.role === "admin" || user.role === "superviseur") return true;
  return ADMIN_LEVEL.has(user.tracked_role);
}

const STATUSES = [
  { value: "planned", label: "Planifiée", color: "bg-sky-100 text-sky-700" },
  { value: "in_progress", label: "En cours", color: "bg-amber-100 text-amber-700" },
  { value: "completed", label: "Terminée", color: "bg-emerald-100 text-emerald-700" },
  { value: "cancelled", label: "Annulée", color: "bg-slate-100 text-slate-600" },
];

export default function ClientInterventions() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/interventions");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const del = async (id) => {
    if (!window.confirm("Supprimer cette intervention ?")) return;
    try {
      await apiClient.delete(`/me/interventions/${id}`);
      toast.success("Intervention supprimée");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const elevated = isElevated(user);
  const deletable = canDelete(user);

  return (
    <div className="space-y-6" data-testid="client-interventions-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">Historique de nos interventions</h1>
          <p className="text-sm text-slate-500">Détail de toutes les interventions réalisées sur votre compte.</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 px-3 py-2 text-sm disabled:opacity-60"
            data-testid="interventions-refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Actualiser
          </button>
          {elevated && (
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light"
              data-testid="interventions-create-btn"
            >
              <Plus className="h-4 w-4" /> Nouvelle intervention
            </button>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              <th className="text-left px-4 py-3">Référence</th>
              <th className="text-left px-4 py-3">Titre</th>
              <th className="text-left px-4 py-3">Date</th>
              <th className="text-left px-4 py-3">Technicien</th>
              <th className="text-left px-4 py-3">Statut</th>
              {deletable && <th className="text-right px-4 py-3">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Chargement…</td></tr>}
            {!loading && items.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">Aucune intervention enregistrée.</td></tr>
            )}
            {items.map((i) => {
              const status = STATUSES.find((s) => s.value === i.status) || { label: i.status, color: "bg-slate-100 text-slate-700" };
              return (
                <tr key={i.id} className="border-t border-slate-100" data-testid={`intervention-row-${i.id}`}>
                  <td className="px-4 py-3 text-xs font-mono text-slate-500">{i.intervention_number || "—"}</td>
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {i.title}
                    {i.description && <p className="text-xs text-slate-500 font-normal mt-0.5 line-clamp-1">{i.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{i.intervention_date && new Date(i.intervention_date).toLocaleDateString("fr-FR")}</td>
                  <td className="px-4 py-3 text-slate-600">{i.technician || "-"}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-1 rounded ${status.color}`}>{status.label}</span>
                  </td>
                  {deletable && (
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => del(i.id)}
                        className="inline-flex items-center gap-1 text-xs text-rose-600 hover:underline"
                        data-testid={`intervention-delete-${i.id}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Supprimer
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <CreateInterventionModal
          user={user}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }}
        />
      )}
    </div>
  );
}

const CreateInterventionModal = ({ user, onClose, onCreated }) => {
  const [form, setForm] = useState({
    title: "",
    description: "",
    intervention_date: new Date().toISOString().slice(0, 10),
    technician: "",
    status: "completed",
    duration_hours: "",
  });
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!form.title.trim()) { toast.error("Le titre est requis"); return; }
    if (!form.intervention_date) { toast.error("Date requise"); return; }
    setSaving(true);
    try {
      const client_id = user?.client_id || user?.id;
      const payload = {
        client_id,
        title: form.title.trim(),
        description: form.description || null,
        status: form.status,
        intervention_date: new Date(form.intervention_date).toISOString(),
        technician: form.technician || null,
        duration_hours: form.duration_hours ? Number(form.duration_hours) : null,
        attachments: [],
      };
      await apiClient.post("/me/interventions", payload);
      toast.success("Intervention créée");
      onCreated();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lors de la création");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      data-testid="intervention-create-modal"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Wrench className="h-5 w-5 text-sawali-blue" /> Nouvelle intervention
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900" data-testid="intervention-create-close"><X className="h-4 w-4" /></button>
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Titre *</label>
          <input
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Mise à jour du logiciel comptable"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="intervention-field-title"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold mb-1">Description</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={3}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            data-testid="intervention-field-description"
          />
        </div>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold mb-1">Date *</label>
            <input
              type="date"
              value={form.intervention_date}
              onChange={(e) => setForm({ ...form, intervention_date: e.target.value })}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="intervention-field-date"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Statut</label>
            <select
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value })}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="intervention-field-status"
            >
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Technicien</label>
            <input
              value={form.technician}
              onChange={(e) => setForm({ ...form, technician: e.target.value })}
              placeholder="Nom du technicien"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="intervention-field-technician"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Durée (heures)</label>
            <input
              type="number"
              step="0.25"
              value={form.duration_hours}
              onChange={(e) => setForm({ ...form, duration_hours: e.target.value })}
              placeholder="2.5"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              data-testid="intervention-field-duration"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button
            onClick={submit}
            disabled={saving}
            className="text-sm rounded-lg bg-sawali-blue hover:bg-sawali-blue-light text-white px-4 py-2 disabled:opacity-50"
            data-testid="intervention-create-save"
          >
            {saving ? "Création…" : "Créer"}
          </button>
        </div>
      </div>
    </div>
  );
};
