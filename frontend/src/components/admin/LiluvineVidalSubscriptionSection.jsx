// Abonnements Liluvine VIDAL — essai, quota gratuit, formules payantes
// (portage site-meetafrican, stockage R2 dédié VIDAL, voir
// backend/routes/liluvine_vidal_subscription.py). Un contact taggé
// "Niveau VIDAL riche" (rubrique S058d ci-dessus) contourne entièrement
// cette passerelle — accès illimité, indépendant de tout ce qui suit.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";

const FORMULA_LABELS = { jour: "Jour", semaine: "Semaine", mois: "Mois", trimestriel: "Trimestriel", annuel: "Annuel" };

export default function LiluvineVidalSubscriptionSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [config, setConfig] = useState(null);
  const [numbers, setNumbers] = useState([]);
  const [numbersLoading, setNumbersLoading] = useState(false);

  const load = async () => {
    try {
      const r = await apiClient.get("/admin/vidal/liluvine/config");
      setConfig(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement de la configuration Liluvine VIDAL impossible");
    } finally {
      setLoading(false);
    }
  };

  const loadNumbers = async () => {
    setNumbersLoading(true);
    try {
      const r = await apiClient.get("/admin/vidal/liluvine/numbers");
      setNumbers(r.data?.numbers || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Chargement des numéros impossible");
    } finally {
      setNumbersLoading(false);
    }
  };

  useEffect(() => { load(); loadNumbers(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await apiClient.put("/admin/vidal/liluvine/config", {
        free_requests_threshold: Number(config.free_requests_threshold),
        trial_days: Number(config.trial_days),
        formulas: config.formulas,
      });
      setConfig(r.data);
      toast.success("Configuration Liluvine VIDAL enregistrée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  };

  const updateFormula = (key, field, value) => {
    setConfig((c) => ({
      ...c,
      formulas: { ...c.formulas, [key]: { ...c.formulas[key], [field]: value } },
    }));
  };

  const authorize = async (phone) => {
    try {
      await apiClient.post(`/admin/vidal/liluvine/numbers/${phone}/authorize`);
      toast.success(`Numéro +${phone} autorisé (essai démarré)`);
      loadNumbers();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec de l'autorisation");
    }
  };

  const toggleBlock = async (phone, block) => {
    try {
      await apiClient.post(`/admin/vidal/liluvine/numbers/${phone}/${block ? "block" : "unblock"}`);
      loadNumbers();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  };

  if (loading || !config) {
    return <p className="text-sm text-slate-500 italic">Chargement…</p>;
  }

  return (
    <div className="space-y-5" data-testid="liluvine-vidal-subscription-section">
      <div className="text-sm text-slate-700 bg-emerald-50 ring-1 ring-emerald-200 p-3 rounded leading-relaxed">
        <p className="font-semibold mb-1">📱 Abonnements Liluvine VIDAL</p>
        <p className="text-xs">
          Un numéro WhatsApp non autorisé reçoit une invitation à s&apos;inscrire et vous êtes notifié.
          En l&apos;autorisant ci-dessous, il obtient un essai gratuit de <strong>{config.trial_days} jour(s)</strong>.
          Passé l&apos;essai, <strong>{config.free_requests_threshold} requête(s) gratuite(s)</strong> restent
          disponibles avant de devoir souscrire une formule.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-3 max-w-lg">
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Essai gratuit (jours)</label>
          <input
            type="number" min={0} value={config.trial_days}
            onChange={(e) => setConfig({ ...config, trial_days: e.target.value })}
            className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 text-sm"
            data-testid="liluvine-sub-trial-days"
          />
        </div>
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">Requêtes gratuites après essai</label>
          <input
            type="number" min={0} value={config.free_requests_threshold}
            onChange={(e) => setConfig({ ...config, free_requests_threshold: e.target.value })}
            className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 text-sm"
            data-testid="liluvine-sub-free-threshold"
          />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold text-slate-600 mb-1.5">
          Formules d&apos;abonnement (montants de démonstration — à ajuster)
        </p>
        <div className="grid sm:grid-cols-5 gap-2">
          {Object.entries(config.formulas).map(([key, f]) => (
            <div key={key} className="p-2 rounded ring-1 ring-slate-200 space-y-1">
              <p className="text-[10px] font-semibold text-slate-700">{FORMULA_LABELS[key] || key}</p>
              <input
                type="number" value={f.duration_days}
                onChange={(e) => updateFormula(key, "duration_days", Number(e.target.value))}
                className="w-full px-1.5 py-1 rounded ring-1 ring-slate-300 text-xs"
                placeholder="Jours"
                data-testid={`liluvine-sub-formula-${key}-days`}
              />
              <input
                type="number" value={f.price_fcfa}
                onChange={(e) => updateFormula(key, "price_fcfa", Number(e.target.value))}
                className="w-full px-1.5 py-1 rounded ring-1 ring-slate-300 text-xs"
                placeholder="FCFA"
                data-testid={`liluvine-sub-formula-${key}-price`}
              />
            </div>
          ))}
        </div>
      </div>

      <div className="flex justify-end pt-2 border-t border-slate-200">
        <button
          type="button" onClick={save} disabled={saving}
          className="text-sm px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white font-semibold disabled:opacity-50"
          data-testid="liluvine-sub-save"
        >
          {saving ? "Enregistrement…" : "💾 Enregistrer"}
        </button>
      </div>

      <div className="pt-3 border-t border-slate-200">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-slate-600">Numéros ({numbers.length})</p>
          <button type="button" onClick={loadNumbers} className="text-[11px] text-emerald-700 hover:underline" data-testid="liluvine-sub-refresh">
            {numbersLoading ? "Actualisation…" : "↻ Actualiser"}
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="liluvine-sub-numbers-table">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1 pr-2">Numéro</th>
                <th className="py-1 pr-2">Statut</th>
                <th className="py-1 pr-2">Requêtes</th>
                <th className="py-1 pr-2">Gratuites utilisées</th>
                <th className="py-1 pr-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {numbers.length === 0 && (
                <tr><td colSpan={5} className="py-2 text-slate-400 italic">Aucun numéro pour le moment.</td></tr>
              )}
              {numbers.map((n) => (
                <tr key={n.phone} className="border-b border-slate-100">
                  <td className="py-1.5 pr-2 font-mono">+{n.phone}</td>
                  <td className="py-1.5 pr-2">
                    {n.manual_blocked ? <span className="text-rose-600 font-semibold">Bloqué</span>
                      : n.authorized ? <span className="text-emerald-600">Autorisé</span>
                      : <span className="text-amber-600">En attente</span>}
                  </td>
                  <td className="py-1.5 pr-2">{n.request_count || 0}</td>
                  <td className="py-1.5 pr-2">{n.free_requests_used || 0} / {config.free_requests_threshold}</td>
                  <td className="py-1.5 pr-2 flex gap-1.5">
                    {!n.authorized && (
                      <button onClick={() => authorize(n.phone)} className="text-emerald-700 hover:underline" data-testid={`liluvine-sub-authorize-${n.phone}`}>
                        Autoriser
                      </button>
                    )}
                    <button onClick={() => toggleBlock(n.phone, !n.manual_blocked)} className="text-rose-600 hover:underline" data-testid={`liluvine-sub-toggle-block-${n.phone}`}>
                      {n.manual_blocked ? "Débloquer" : "Bloquer"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
