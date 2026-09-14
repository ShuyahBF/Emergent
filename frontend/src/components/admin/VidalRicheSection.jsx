// VIDAL riche — !doc / !rech (DCI + équivalences), quota simple/riche.
// Rubrique séparée de "Actions VIDAL configurables" : ces deux commandes
// (synonymes) exécutent une recherche spéciale (principe actif + équivalents),
// pas un simple appel REST templaté. Le niveau d'accès par contact ("Niveau
// VIDAL riche") se règle sur la fiche du contact, pas ici.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";
import { toast } from "sonner";

export default function VidalRicheSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [quota, setQuota] = useState(10);

  useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get("/admin/vidal/riche/settings");
        setEnabled(!!r.data?.enabled);
        setQuota(Number(r.data?.daily_quota_simple ?? 10));
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Chargement des réglages VIDAL riche impossible");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await apiClient.put("/admin/vidal/riche/settings", {
        enabled,
        daily_quota_simple: Math.max(0, parseInt(quota, 10) || 0),
      });
      setEnabled(!!r.data?.enabled);
      setQuota(Number(r.data?.daily_quota_simple ?? 10));
      toast.success("Réglages VIDAL riche enregistrés");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sauvegarde impossible");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <p className="text-sm text-slate-500 italic">Chargement…</p>;
  }

  return (
    <div className="space-y-4" data-testid="vidal-riche-section">
      <div className="text-sm text-slate-700 bg-fuchsia-50 ring-1 ring-fuchsia-200 p-3 rounded leading-relaxed">
        <p className="font-semibold mb-1">💊 Actions VIDAL riches</p>
        <p className="text-xs">
          Commande WhatsApp <code className="bg-fuchsia-100 px-1 rounded">!doc</code> (synonyme :{" "}
          <code className="bg-fuchsia-100 px-1 rounded">!rech</code>) — ex. <code className="bg-fuchsia-100 px-1 rounded">!doc doliprane 1000</code>.
          Retourne la documentation d&apos;un produit et son principe actif (DCI). Si le principe actif n&apos;est
          pas trouvé tel quel, la liste des produits équivalents (même DCI + dosage) est proposée — avec un
          bouton <strong>« Équivalences »</strong> sur WhatsApp.
        </p>
        <p className="text-xs mt-1">
          Niveau d&apos;accès par contact réglable sur sa fiche (<em>Niveau VIDAL riche</em>) :{" "}
          <strong>riche</strong> = accès illimité, contourne entièrement la passerelle essai/quota/abonnement
          ci-dessous (ex. médecins VIP, comptes de test internes).
        </p>
        <p className="text-xs mt-1 text-amber-700">
          ⚠️ Le quota quotidien ci-dessous n&apos;est plus utilisé pour les contacts non « riche » — c&apos;est
          désormais la passerelle essai/quota/abonnement (rubrique <strong>S058f — Abonnements Liluvine VIDAL</strong>,
          ci-dessous) qui gère leur accès. Ce champ reste modifiable mais sans effet, conservé pour compatibilité.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-3 max-w-lg">
        <label className="flex items-center gap-2 text-sm cursor-pointer p-2.5 rounded ring-1 ring-slate-200">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            data-testid="vidal-riche-enabled"
          />
          <span>Rubrique activée</span>
        </label>
        <div>
          <label className="block text-[10px] font-semibold text-slate-600 mb-0.5">
            Quota quotidien — accès simple (0 = illimité)
          </label>
          <input
            type="number"
            min={0}
            value={quota}
            onChange={(e) => setQuota(e.target.value)}
            className="w-full px-2 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-fuchsia-400 outline-none text-sm"
            data-testid="vidal-riche-quota"
          />
          <p className="text-[10px] text-slate-500 italic mt-0.5">
            Non cumulatif — remis à 0 chaque jour, quel que soit l&apos;usage de la veille.
          </p>
        </div>
      </div>

      <div className="flex justify-end pt-2 border-t border-slate-200">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="text-sm px-4 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white font-semibold disabled:opacity-50"
          data-testid="vidal-riche-save"
        >
          {saving ? "Enregistrement…" : "💾 Enregistrer"}
        </button>
      </div>
    </div>
  );
}
