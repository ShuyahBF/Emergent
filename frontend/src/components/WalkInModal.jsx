/*
 * 2026-02 fork (P2) — Modal walk-in (patient sans RDV) — création/édition.
 * Utilisable par admin/superviseur/moderateur/médecin/secrétaire médicale.
 *
 * Champs :
 *   - Nom patient (obligatoire)
 *   - Téléphone patient (facultatif)
 *   - Médecin (dropdown → /me/planning/doctors)
 *   - Date (défaut = date sélectionnée dans Planning)
 *   - Motif (facultatif)
 */
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { X, Loader2, Save, Trash2, UserPlus } from "lucide-react";

export default function WalkInModal({ open, onClose, onSaved, onDeleted, defaultDate, doctors, existing }) {
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [form, setForm] = useState({
    patient: "",
    patient_phone: "",
    medecin_id: "",
    date: defaultDate || "",
    motif: "",
  });

  useEffect(() => {
    if (!open) return;
    if (existing) {
      setForm({
        patient: existing.patient || "",
        patient_phone: existing.patient_phone || "",
        medecin_id: existing.medecin_id || "",
        date: (existing.received_at || existing.created_at || defaultDate || "").slice(0, 10),
        motif: existing.motif || "",
      });
    } else {
      setForm({
        patient: "",
        patient_phone: "",
        medecin_id: doctors?.[0]?.id || "",
        date: defaultDate || "",
        motif: "",
      });
    }
  }, [open, existing, defaultDate, doctors]);

  if (!open) return null;

  const isEdit = !!existing;

  const canSave = form.patient.trim().length >= 1 && form.medecin_id;

  const save = async () => {
    if (!canSave) {
      toast.error("Nom du patient et médecin obligatoires");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        medecin_id: form.medecin_id,
        patient: form.patient.trim(),
        patient_phone: form.patient_phone.trim() || null,
        date: form.date || undefined,
        motif: form.motif.trim() || null,
      };
      let res;
      if (isEdit) {
        res = await apiClient.patch(`/me/planning/walk-in/${existing.id}`, payload);
        toast.success("Walk-in mis à jour");
      } else {
        res = await apiClient.post("/me/planning/walk-in", payload);
        toast.success(`Walk-in créé (n°${res.data?.walk_in?.numero_ordre ?? "?"})`);
      }
      onSaved && onSaved(res.data?.walk_in);
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur lors de l'enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!existing) return;
    if (!window.confirm(`Supprimer le walk-in #${existing.numero_ordre} — ${existing.patient} ?`)) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/me/planning/walk-in/${existing.id}`);
      toast.success("Walk-in supprimé");
      onDeleted && onDeleted(existing.id);
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur suppression");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="walk-in-modal"
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-emerald-600" />
            {isEdit ? `Modifier walk-in #${existing.numero_ordre}` : "Nouveau walk-in (sans RDV)"}
          </h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-100 rounded-lg"
            data-testid="walk-in-modal-close"
          >
            <X className="h-4 w-4 text-slate-500" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Nom du patient <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={form.patient}
              onChange={(e) => setForm((f) => ({ ...f, patient: e.target.value }))}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              placeholder="Ex. Jean Dupont"
              data-testid="walk-in-patient-input"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Téléphone patient
            </label>
            <input
              type="tel"
              value={form.patient_phone}
              onChange={(e) => setForm((f) => ({ ...f, patient_phone: e.target.value }))}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              placeholder="+226…"
              data-testid="walk-in-phone-input"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Médecin <span className="text-red-500">*</span>
            </label>
            <select
              value={form.medecin_id}
              onChange={(e) => setForm((f) => ({ ...f, medecin_id: e.target.value }))}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white"
              data-testid="walk-in-doctor-select"
            >
              <option value="">— Choisir un médecin —</option>
              {(doctors || []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.full_name || d.email}
                </option>
              ))}
            </select>
            {(doctors || []).length === 0 && (
              <p className="text-xs text-amber-600 mt-1">
                Aucun médecin trouvé dans votre client. Un utilisateur suivi avec le rôle « Médecin » est requis.
              </p>
            )}
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Date
            </label>
            <input
              type="date"
              value={form.date}
              onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              data-testid="walk-in-date-input"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Motif (facultatif)
            </label>
            <input
              type="text"
              value={form.motif}
              onChange={(e) => setForm((f) => ({ ...f, motif: e.target.value }))}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm"
              placeholder="Ex. Contrôle tension"
              data-testid="walk-in-motif-input"
            />
          </div>
        </div>
        <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-slate-200 bg-slate-50 rounded-b-2xl">
          {isEdit ? (
            <button
              onClick={remove}
              disabled={deleting || saving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 text-sm disabled:opacity-50"
              data-testid="walk-in-delete-btn"
            >
              {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Supprimer
            </button>
          ) : (
            <span />
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100"
              data-testid="walk-in-cancel-btn"
            >
              Annuler
            </button>
            <button
              onClick={save}
              disabled={!canSave || saving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50"
              data-testid="walk-in-save-btn"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {isEdit ? "Enregistrer" : "Créer"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
