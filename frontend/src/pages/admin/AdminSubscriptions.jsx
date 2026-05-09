import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Pencil, Save, X, Tag, Banknote, Globe, Send } from "lucide-react";

/*
  /admin/subscriptions — Manage subscription categories (max 4) + plans + orders.
  Each plan has an auto-generated code FMLYYYYNNNN.
*/
function fmtXOF(n) {
  return Number(n || 0).toLocaleString("fr-FR") + " XOF";
}
function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export default function AdminSubscriptions() {
  const [tab, setTab] = useState("plans");
  const [cats, setCats] = useState([]);
  const [plans, setPlans] = useState([]);
  const [orders, setOrders] = useState([]);
  const [editingCat, setEditingCat] = useState(null);
  const [editingPlan, setEditingPlan] = useState(null);

  const reload = async () => {
    try {
      const [c, p, o] = await Promise.all([
        apiClient.get("/admin/subscriptions/categories"),
        apiClient.get("/admin/subscriptions/plans"),
        apiClient.get("/admin/subscriptions/orders").catch(() => ({ data: [] })),
      ]);
      setCats(Array.isArray(c.data) ? c.data : []);
      setPlans(Array.isArray(p.data) ? p.data : []);
      setOrders(Array.isArray(o.data) ? o.data : []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    }
  };
  useEffect(() => { reload(); }, []);

  const catLabel = (id) => cats.find((c) => c.id === id)?.label || "Sans catégorie";

  return (
    <div className="space-y-6 max-w-full" data-testid="admin-subscriptions-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Site public</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <Tag className="h-5 w-5 text-sawali-blue" /> Abonnements
        </h1>
        <p className="text-sm text-slate-500 mt-1">Configurez les formules d'abonnement présentées sur le site public (max 4 catégories visuelles).</p>
      </div>

      <div className="flex gap-1 border-b border-slate-200" data-testid="subs-tabs">
        {["plans", "categories", "orders"].map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${tab === t ? "border-sawali-blue text-sawali-blue" : "border-transparent text-slate-500 hover:text-slate-900"}`}
            data-testid={`subs-tab-${t}`}
          >
            {t === "plans" ? "Formules" : t === "categories" ? "Catégories" : "Souscriptions"}
          </button>
        ))}
      </div>

      {tab === "plans" && (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <p className="text-sm text-slate-500">{plans.length} formule(s) configurée(s)</p>
            <button onClick={() => setEditingPlan({})} className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-sm hover:bg-sawali-blue-light" data-testid="plan-add-btn">
              <Plus className="h-4 w-4" /> Nouvelle formule
            </button>
          </div>
          <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[10px] uppercase text-slate-500">
                <tr>
                  <th className="text-left px-3 py-2">Code</th>
                  <th className="text-left px-3 py-2">Formule</th>
                  <th className="text-left px-3 py-2 hidden md:table-cell">Catégorie</th>
                  <th className="text-right px-3 py-2 hidden sm:table-cell">Mensuel</th>
                  <th className="text-right px-3 py-2 hidden sm:table-cell">Annuel</th>
                  <th className="text-center px-3 py-2 hidden lg:table-cell">Actif</th>
                  <th className="text-right px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {plans.length === 0 && <tr><td colSpan={7} className="px-3 py-10 text-center text-slate-400 italic">Aucune formule. Cliquez sur « Nouvelle formule » pour démarrer.</td></tr>}
                {plans.map((p) => (
                  <tr key={p.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`plan-row-${p.id}`}>
                    <td className="px-3 py-2 font-mono text-xs text-slate-700">{p.code}</td>
                    <td className="px-3 py-2 font-semibold">
                      {p.name}
                      {p.featured && <span className="ml-2 text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">★ Phare</span>}
                      <div className="md:hidden text-[10px] text-slate-500 mt-0.5">{catLabel(p.category_id)} • {fmtXOF(p.price_monthly_xof)}/mois</div>
                    </td>
                    <td className="px-3 py-2 hidden md:table-cell text-slate-600">{catLabel(p.category_id)}</td>
                    <td className="px-3 py-2 hidden sm:table-cell text-right font-mono">{fmtXOF(p.price_monthly_xof)}</td>
                    <td className="px-3 py-2 hidden sm:table-cell text-right font-mono">{fmtXOF(p.price_annual_xof)}</td>
                    <td className="px-3 py-2 hidden lg:table-cell text-center">{p.active ? <span className="text-emerald-600">●</span> : <span className="text-slate-400">○</span>}</td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button onClick={() => setEditingPlan(p)} className="text-slate-600 hover:text-sawali-blue px-1" data-testid={`plan-edit-${p.id}`}><Pencil className="h-3.5 w-3.5" /></button>
                      <button onClick={async () => { if (window.confirm(`Supprimer ${p.name} ?`)) { await apiClient.delete(`/admin/subscriptions/plans/${p.id}`); toast.success("Supprimée"); reload(); } }} className="text-slate-600 hover:text-rose-600 px-1" data-testid={`plan-del-${p.id}`}><Trash2 className="h-3.5 w-3.5" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "categories" && (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <p className="text-sm text-slate-500">{cats.length}/4 catégorie(s) configurée(s)</p>
            <button onClick={() => setEditingCat({})} disabled={cats.length >= 4} className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-sm hover:bg-sawali-blue-light disabled:opacity-40 disabled:cursor-not-allowed" data-testid="cat-add-btn">
              <Plus className="h-4 w-4" /> Nouvelle catégorie
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {cats.length === 0 && <p className="col-span-full text-center text-slate-400 italic py-8">Aucune catégorie pour l'instant.</p>}
            {cats.map((c) => (
              <div key={c.id} className="rounded-xl ring-1 ring-slate-200 bg-white p-4" style={{ borderTop: `4px solid ${c.color || "#0D6EFD"}` }} data-testid={`cat-card-${c.id}`}>
                <p className="font-semibold">{c.label}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">Position {c.position} • Animation {c.animated ? "ON" : "OFF"}</p>
                <p className="text-[10px] text-slate-500 font-mono mt-1">{c.color}</p>
                <div className="flex gap-2 mt-3">
                  <button onClick={() => setEditingCat(c)} className="text-xs text-sawali-blue hover:underline" data-testid={`cat-edit-${c.id}`}>Modifier</button>
                  <button onClick={async () => { if (window.confirm(`Supprimer ${c.label} ? Les formules seront détachées (non supprimées).`)) { await apiClient.delete(`/admin/subscriptions/categories/${c.id}`); toast.success("Supprimée"); reload(); } }} className="text-xs text-rose-600 hover:underline" data-testid={`cat-del-${c.id}`}>Supprimer</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "orders" && (
        <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-x-auto" data-testid="subs-orders-table">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[10px] uppercase text-slate-500">
              <tr>
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-left px-3 py-2">Client</th>
                <th className="text-left px-3 py-2 hidden md:table-cell">Formule</th>
                <th className="text-left px-3 py-2 hidden sm:table-cell">Période</th>
                <th className="text-right px-3 py-2">Montant</th>
                <th className="text-left px-3 py-2 hidden lg:table-cell">Statut</th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 && <tr><td colSpan={6} className="px-3 py-10 text-center text-slate-400 italic">Aucune souscription pour l'instant.</td></tr>}
              {orders.map((o) => (
                <tr key={o.id} className="border-t border-slate-100" data-testid={`order-row-${o.id}`}>
                  <td className="px-3 py-2 text-xs whitespace-nowrap">{fmtDate(o.created_at)}</td>
                  <td className="px-3 py-2">
                    <div className="font-semibold">{o.customer_name}</div>
                    <div className="text-[11px] text-slate-500 font-mono">{o.customer_phone}</div>
                  </td>
                  <td className="px-3 py-2 hidden md:table-cell text-xs">{o.plan_name} <code className="text-[10px] text-slate-500">({o.plan_code})</code></td>
                  <td className="px-3 py-2 hidden sm:table-cell text-xs">{o.period === "monthly" ? "Mensuel" : "Annuel"}</td>
                  <td className="px-3 py-2 text-right font-mono">{fmtXOF(o.amount_xof)}</td>
                  <td className="px-3 py-2 hidden lg:table-cell">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ring-1 ${o.status === "notified" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-amber-200"}`}>{o.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editingCat !== null && <CategoryEditModal cat={editingCat} onClose={() => setEditingCat(null)} onSaved={() => { setEditingCat(null); reload(); }} />}
      {editingPlan !== null && <PlanEditModal plan={editingPlan} cats={cats} onClose={() => setEditingPlan(null)} onSaved={() => { setEditingPlan(null); reload(); }} />}
    </div>
  );
}

const CategoryEditModal = ({ cat, onClose, onSaved }) => {
  const [form, setForm] = useState(() => cat?.id ? cat : { label: "", color: "#0D6EFD", position: 0, animated: true });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!form.label?.trim()) { toast.error("Libellé requis"); return; }
    setSaving(true);
    try {
      if (cat?.id) await apiClient.put(`/admin/subscriptions/categories/${cat.id}`, form);
      else await apiClient.post("/admin/subscriptions/categories", form);
      toast.success("Catégorie enregistrée");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="cat-edit-modal">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl p-6 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">{cat?.id ? "Modifier la catégorie" : "Nouvelle catégorie"}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <label className="text-xs font-semibold block">
          Libellé <input value={form.label || ""} onChange={(e) => setForm({ ...form, label: e.target.value })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="cat-form-label" />
        </label>
        <label className="text-xs font-semibold block">
          Couleur (hex) <input type="color" value={form.color || "#0D6EFD"} onChange={(e) => setForm({ ...form, color: e.target.value })} className="w-20 h-9 mt-1 rounded border border-slate-300 cursor-pointer" data-testid="cat-form-color" />
        </label>
        <label className="text-xs font-semibold block">
          Position (ordre d'affichage) <input type="number" value={form.position || 0} onChange={(e) => setForm({ ...form, position: parseInt(e.target.value, 10) || 0 })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="cat-form-position" />
        </label>
        <label className="text-xs font-semibold inline-flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={!!form.animated} onChange={(e) => setForm({ ...form, animated: e.target.checked })} data-testid="cat-form-animated" /> Animation au survol
        </label>
        <div className="flex justify-end gap-2 pt-3 border-t">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button onClick={save} disabled={saving} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-sawali-blue text-white px-4 py-2 hover:bg-sawali-blue-light disabled:opacity-50" data-testid="cat-form-save">
            <Save className="h-4 w-4" /> {saving ? "…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};

const PlanEditModal = ({ plan, cats, onClose, onSaved }) => {
  const [form, setForm] = useState(() => plan?.id ? plan : { name: "", description: "", price_monthly_xof: 0, price_annual_xof: 0, featured: false, active: true, category_id: cats[0]?.id || null, automation_url: "", whatsapp_notify_to: "" });
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (!form.name?.trim()) { toast.error("Nom requis"); return; }
    setSaving(true);
    try {
      if (plan?.id) await apiClient.put(`/admin/subscriptions/plans/${plan.id}`, form);
      else await apiClient.post("/admin/subscriptions/plans", form);
      toast.success("Formule enregistrée");
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="plan-edit-modal">
      <div className="w-full max-w-xl rounded-2xl bg-white shadow-2xl p-6 space-y-3 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-display font-bold">{plan?.id ? `Modifier ${plan.code}` : "Nouvelle formule"}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        {plan?.code && <p className="text-[11px] text-slate-500 font-mono">Code automatique : <strong>{plan.code}</strong></p>}
        <label className="text-xs font-semibold block">
          Nom de la formule <input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="plan-form-name" />
        </label>
        <label className="text-xs font-semibold block">
          Catégorie
          <select value={form.category_id || ""} onChange={(e) => setForm({ ...form, category_id: e.target.value || null })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="plan-form-cat">
            <option value="">— Sans catégorie —</option>
            {cats.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
          </select>
        </label>
        <label className="text-xs font-semibold block">
          Description (texte long)
          <textarea value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={4} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="plan-form-desc" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs font-semibold block">
            Tarif mensuel (XOF)
            <input type="number" min="0" value={form.price_monthly_xof || 0} onChange={(e) => setForm({ ...form, price_monthly_xof: parseInt(e.target.value, 10) || 0 })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="plan-form-monthly" />
          </label>
          <label className="text-xs font-semibold block">
            Tarif annuel (XOF)
            <input type="number" min="0" value={form.price_annual_xof || 0} onChange={(e) => setForm({ ...form, price_annual_xof: parseInt(e.target.value, 10) || 0 })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="plan-form-annual" />
          </label>
        </div>
        <label className="text-xs font-semibold block">
          Numéro WhatsApp à notifier (E.164)
          <input value={form.whatsapp_notify_to || ""} onChange={(e) => setForm({ ...form, whatsapp_notify_to: e.target.value })} placeholder="22507XXXXXXX" className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="plan-form-wa" />
        </label>
        <label className="text-xs font-semibold block">
          URL d'automatisation (webhook POST optionnel)
          <input value={form.automation_url || ""} onChange={(e) => setForm({ ...form, automation_url: e.target.value })} placeholder="https://n8n.example.com/webhook/sub" className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="plan-form-url" />
        </label>
        <div className="flex flex-wrap gap-4">
          <label className="text-xs font-semibold inline-flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={!!form.featured} onChange={(e) => setForm({ ...form, featured: e.target.checked })} data-testid="plan-form-featured" /> ★ Mettre en avant
          </label>
          <label className="text-xs font-semibold inline-flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={!!form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="plan-form-active" /> Actif (visible site public)
          </label>
        </div>
        <div className="flex justify-end gap-2 pt-3 border-t">
          <button onClick={onClose} className="text-sm rounded-lg bg-slate-100 hover:bg-slate-200 px-4 py-2">Annuler</button>
          <button onClick={save} disabled={saving} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-sawali-blue text-white px-4 py-2 hover:bg-sawali-blue-light disabled:opacity-50" data-testid="plan-form-save">
            <Save className="h-4 w-4" /> {saving ? "…" : "Enregistrer"}
          </button>
        </div>
      </div>
    </div>
  );
};
