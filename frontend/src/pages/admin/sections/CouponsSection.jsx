// =====================================================================
// Iter38r-fix9o (P1) — Coupons CRUD admin section.
// Manages Stripe checkout discount coupons used by the public catalogue.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Tag, Plus, Trash2, Check, X, Calendar, Percent, Banknote, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const CouponsSection = () => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    code: "",
    discount_pct: "",
    discount_xof: "",
    valid_until: "",
    max_uses: "",
    active: true,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/coupons");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e?.preventDefault?.();
    const code = (form.code || "").trim().toUpperCase();
    if (!code) {
      toast.error("Code requis");
      return;
    }
    const pct = parseFloat(form.discount_pct);
    const xof = parseInt(form.discount_xof);
    if (!pct && !xof) {
      toast.error("Renseignez un pourcentage OU un montant XOF");
      return;
    }
    setBusy(true);
    try {
      const payload = {
        code,
        discount_pct: pct || null,
        discount_xof: xof || null,
        valid_until: form.valid_until || null,
        max_uses: form.max_uses ? parseInt(form.max_uses) : null,
        active: !!form.active,
      };
      await apiClient.post("/admin/coupons", payload);
      toast.success(`Coupon ${code} créé`);
      setForm({ code: "", discount_pct: "", discount_xof: "", valid_until: "", max_uses: "", active: true });
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur création");
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (c) => {
    try {
      await apiClient.put(`/admin/coupons/${c.id}`, { active: !c.active });
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (c) => {
    if (!window.confirm(`Supprimer le coupon ${c.code} ?`)) return;
    try {
      await apiClient.delete(`/admin/coupons/${c.id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <section className="rounded-2xl ring-1 ring-amber-200 bg-gradient-to-br from-amber-50/40 via-white to-orange-50/30 p-5" data-testid="admin-coupons-section">
      <header className="flex items-center gap-3 mb-3">
        <div className="rounded-full bg-amber-100 ring-1 ring-amber-200 p-2">
          <Tag className="h-5 w-5 text-amber-700" />
        </div>
        <div>
          <h3 className="font-display font-bold text-slate-900">Coupons de réduction (Stripe Checkout)</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Codes promo appliqués au catalogue public (paiement Stripe). Un coupon doit avoir un pourcentage <strong>ou</strong> un montant XOF.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="ml-auto text-xs rounded-lg ring-1 ring-slate-300 px-2 py-1 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="admin-coupons-refresh"
        >
          <RotateCw className="h-3.5 w-3.5" /> Recharger
        </button>
      </header>

      <form onSubmit={create} className="grid sm:grid-cols-6 gap-2 mb-4 p-3 rounded-xl bg-white ring-1 ring-amber-100">
        <label className="sm:col-span-1 block">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Code</span>
          <input
            type="text"
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
            placeholder="ETE2026"
            className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-2 py-1.5 font-mono uppercase"
            required
            data-testid="admin-coupons-form-code"
          />
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 inline-flex items-center gap-1"><Percent className="h-3 w-3" /> %</span>
          <input
            type="number"
            min="0" max="100" step="0.1"
            value={form.discount_pct}
            onChange={(e) => setForm({ ...form, discount_pct: e.target.value })}
            placeholder="10"
            className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-2 py-1.5"
            data-testid="admin-coupons-form-pct"
          />
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 inline-flex items-center gap-1"><Banknote className="h-3 w-3" /> XOF</span>
          <input
            type="number" min="0"
            value={form.discount_xof}
            onChange={(e) => setForm({ ...form, discount_xof: e.target.value })}
            placeholder="5000"
            className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-2 py-1.5"
            data-testid="admin-coupons-form-xof"
          />
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> Expiration</span>
          <input
            type="date"
            value={form.valid_until ? form.valid_until.slice(0, 10) : ""}
            onChange={(e) => setForm({ ...form, valid_until: e.target.value ? new Date(e.target.value).toISOString() : "" })}
            className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-2 py-1.5"
            data-testid="admin-coupons-form-valid-until"
          />
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Max utilisations</span>
          <input
            type="number" min="0"
            value={form.max_uses}
            onChange={(e) => setForm({ ...form, max_uses: e.target.value })}
            placeholder="illimité"
            className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-2 py-1.5"
            data-testid="admin-coupons-form-max-uses"
          />
        </label>
        <div className="flex items-end">
          <button
            type="submit"
            disabled={busy}
            className="w-full text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 inline-flex items-center justify-center gap-1 disabled:opacity-50"
            data-testid="admin-coupons-form-submit"
          >
            <Plus className="h-3.5 w-3.5" /> Créer
          </button>
        </div>
      </form>

      <div className="rounded-xl bg-white ring-1 ring-slate-200 overflow-hidden">
        <table className="w-full text-sm" data-testid="admin-coupons-table">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">Code</th>
              <th className="text-left px-3 py-2">Réduction</th>
              <th className="text-left px-3 py-2">Expiration</th>
              <th className="text-left px-3 py-2">Utilisé / Max</th>
              <th className="text-left px-3 py-2">Statut</th>
              <th className="text-right px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={6} className="text-center text-slate-500 py-6 text-xs">Chargement…</td></tr>
            )}
            {!loading && items.length === 0 && (
              <tr><td colSpan={6} className="text-center text-slate-500 py-6 text-xs">Aucun coupon. Créez-en un ci-dessus.</td></tr>
            )}
            {items.map((c) => (
              <tr key={c.id} className="border-t border-slate-100 hover:bg-amber-50/30" data-testid={`admin-coupons-row-${c.code}`}>
                <td className="px-3 py-2 font-mono font-semibold text-amber-900">{c.code}</td>
                <td className="px-3 py-2">
                  {c.discount_pct ? `${c.discount_pct} %` : ""}
                  {c.discount_pct && c.discount_xof ? " · " : ""}
                  {c.discount_xof ? `${c.discount_xof.toLocaleString("fr-FR")} XOF` : ""}
                  {!c.discount_pct && !c.discount_xof ? "—" : ""}
                </td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  {c.valid_until ? new Date(c.valid_until).toLocaleDateString("fr-FR") : "—"}
                </td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  {c.uses || 0}{c.max_uses ? ` / ${c.max_uses}` : " / ∞"}
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => toggleActive(c)}
                    className={`text-[10px] rounded-full px-2 py-0.5 ring-1 inline-flex items-center gap-1 ${c.active ? "bg-emerald-50 text-emerald-800 ring-emerald-200 hover:bg-emerald-100" : "bg-slate-100 text-slate-600 ring-slate-300 hover:bg-slate-200"}`}
                    data-testid={`admin-coupons-toggle-${c.code}`}
                  >
                    {c.active ? <><Check className="h-3 w-3" /> Actif</> : <><X className="h-3 w-3" /> Inactif</>}
                  </button>
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => remove(c)}
                    className="text-xs rounded-lg ring-1 ring-rose-200 text-rose-700 hover:bg-rose-50 px-2 py-1 inline-flex items-center gap-1"
                    data-testid={`admin-coupons-delete-${c.code}`}
                  >
                    <Trash2 className="h-3 w-3" /> Supprimer
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[10px] text-slate-500 mt-3">
        Les codes sont insensibles à la casse (toujours convertis en majuscules). Un coupon désactivé reste consultable mais ne s'applique plus aux paiements.
      </p>
    </section>
  );
};

export default CouponsSection;
