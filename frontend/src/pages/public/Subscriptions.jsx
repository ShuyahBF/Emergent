import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Check, ChevronRight, Sparkles, Zap, Star, Loader2 } from "lucide-react";
import { phonePlaceholder } from "@/lib/tenantMeta";

/*
  Public /subscriptions page.
  Visitors browse plans grouped by up to 4 admin-defined categories.
  A toggle switches all displayed prices between monthly and annual (with savings).
  Clicking a plan opens a review/validation modal that triggers a WhatsApp
  notification to the admin number configured per plan.
*/
function fmtXOF(n) {
  return Number(n || 0).toLocaleString("fr-FR") + " XOF";
}

export default function Subscriptions() {
  const [data, setData] = useState({ categories: [], plans: [] });
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState("monthly");
  const [activeCat, setActiveCat] = useState("__all__");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    apiClient.get("/public/subscriptions").then((r) => {
      setData({ categories: r.data?.categories || [], plans: r.data?.plans || [] });
    }).catch((err) => {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    }).finally(() => setLoading(false));
  }, []);

  const visiblePlans = useMemo(() => {
    if (activeCat === "__all__") return data.plans;
    return data.plans.filter((p) => p.category_id === activeCat);
  }, [data.plans, activeCat]);

  const totalSavings = (p) => {
    if (!p.price_monthly_xof || !p.price_annual_xof) return 0;
    return Math.max(0, (p.price_monthly_xof * 12) - p.price_annual_xof);
  };

  return (
    <>
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-sawali-blue/30 via-transparent to-transparent pointer-events-none" />
        <div className="max-w-6xl mx-auto px-6 py-16 sm:py-24 relative">
          <div className="text-center max-w-2xl mx-auto">
            <p className="text-xs uppercase tracking-[0.4em] text-sawali-blue-light flex items-center justify-center gap-2">
              <Sparkles className="h-3 w-3" /> Abonnements
            </p>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-display font-bold text-white mt-3" data-testid="subs-h1">
              Choisissez votre formule
            </h1>
            <p className="text-base text-slate-300 mt-5 max-w-xl mx-auto">
              Une tarification claire pour SAWALI SMART SYSTEMS — passez en mensuel ou annuel selon votre rythme.
            </p>

            {/* Toggle */}
            <div className="inline-flex mt-8 rounded-full bg-white/10 p-1 ring-1 ring-white/20" data-testid="subs-period-toggle">
              <button
                onClick={() => setPeriod("monthly")}
                className={`px-5 py-2 rounded-full text-sm font-semibold transition-all ${period === "monthly" ? "bg-white text-sawali-blue shadow" : "text-slate-300 hover:text-white"}`}
                data-testid="subs-period-monthly"
              >
                Mensuel
              </button>
              <button
                onClick={() => setPeriod("annual")}
                className={`px-5 py-2 rounded-full text-sm font-semibold transition-all ${period === "annual" ? "bg-white text-sawali-blue shadow" : "text-slate-300 hover:text-white"}`}
                data-testid="subs-period-annual"
              >
                Annuel <span className="ml-1 text-[10px] bg-emerald-500 text-white px-1.5 py-0.5 rounded-full">jusqu'à -2 mois</span>
              </button>
            </div>
          </div>

          {/* Category filters */}
          {data.categories.length > 0 && (
            <div className="mt-12 flex flex-wrap justify-center gap-2" data-testid="subs-category-filter">
              <button
                onClick={() => setActiveCat("__all__")}
                className={`text-sm px-4 py-1.5 rounded-full border transition-all ${activeCat === "__all__" ? "bg-white text-sawali-blue border-white" : "bg-transparent text-slate-300 border-white/20 hover:border-white/40 hover:text-white"}`}
              >
                Tout afficher
              </button>
              {data.categories.map((c) => (
                <button
                  key={c.id}
                  onClick={() => setActiveCat(c.id)}
                  className={`text-sm px-4 py-1.5 rounded-full border transition-all ${activeCat === c.id ? "text-white" : "text-slate-300 hover:text-white"}`}
                  style={activeCat === c.id ? { backgroundColor: c.color, borderColor: c.color } : { borderColor: c.color, borderWidth: "1.5px" }}
                  data-testid={`subs-cat-${c.id}`}
                >
                  {c.label}
                </button>
              ))}
            </div>
          )}

          {/* Plans grid */}
          {loading ? (
            <div className="flex justify-center mt-16"><Loader2 className="h-8 w-8 text-white animate-spin" /></div>
          ) : visiblePlans.length === 0 ? (
            <div className="text-center mt-16 text-slate-400">Aucune formule pour cette catégorie pour l'instant.</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-12" data-testid="subs-plans-grid">
              {visiblePlans.map((p) => {
                const cat = data.categories.find((c) => c.id === p.category_id);
                const price = period === "monthly" ? p.price_monthly_xof : p.price_annual_xof;
                const periodLabel = period === "monthly" ? "mois" : "an";
                const isFeatured = p.featured;
                const animated = cat?.animated !== false; // default ON
                return (
                  <button
                    key={p.id}
                    onClick={() => setSelected(p)}
                    className={`group relative text-left rounded-2xl bg-white/5 backdrop-blur ring-1 ring-white/10 p-6 transition-all duration-500 ${animated ? "hover:scale-[1.025] hover:bg-white/10 hover:ring-white/30 hover:shadow-2xl" : ""}`}
                    style={isFeatured ? { background: `linear-gradient(135deg, ${cat?.color || "#0D6EFD"}22, transparent)`, borderColor: cat?.color || "#0D6EFD" } : (cat ? { borderTopColor: cat.color, borderTopWidth: "3px" } : {})}
                    data-testid={`plan-card-${p.id}`}
                  >
                    {isFeatured && (
                      <span className="absolute -top-2 right-4 text-[10px] uppercase tracking-wider font-bold px-2 py-0.5 rounded-full text-white shadow" style={{ backgroundColor: cat?.color || "#0D6EFD" }}>
                        ★ Recommandée
                      </span>
                    )}
                    {cat && (
                      <p className="text-[10px] uppercase tracking-[0.25em] mb-3" style={{ color: cat.color || "#0D6EFD" }}>{cat.label}</p>
                    )}
                    <h3 className="text-2xl font-display font-bold text-white">{p.name}</h3>
                    <p className="text-sm text-slate-400 mt-2 leading-relaxed line-clamp-3 min-h-[3.75rem]">
                      {p.description || "—"}
                    </p>
                    <div className="mt-6 flex items-baseline gap-1.5">
                      <span className="text-4xl font-display font-bold text-white tabular-nums">
                        {Number(price || 0).toLocaleString("fr-FR")}
                      </span>
                      <span className="text-sm text-slate-400">XOF / {periodLabel}</span>
                    </div>
                    {period === "annual" && totalSavings(p) > 0 && (
                      <p className="text-xs text-emerald-400 mt-1">
                        Économisez {fmtXOF(totalSavings(p))} par an
                      </p>
                    )}
                    <p className="text-[10px] text-slate-500 mt-4 font-mono">Réf : {p.code}</p>
                    <div className={`mt-5 inline-flex items-center gap-1.5 text-sm font-semibold transition-all ${animated ? "group-hover:translate-x-1" : ""}`} style={{ color: cat?.color || "#fff" }}>
                      Souscrire <ChevronRight className="h-4 w-4" />
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </section>

      {selected && <SubscriptionOrderModal plan={selected} period={period} onClose={() => setSelected(null)} />}
    </>
  );
}

const SubscriptionOrderModal = ({ plan, period, onClose }) => {
  const [form, setForm] = useState({ customer_name: "", customer_email: "", customer_phone: "", message: "" });
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(null);
  const amount = period === "monthly" ? plan.price_monthly_xof : plan.price_annual_xof;

  const submit = async () => {
    if (!form.customer_name.trim() || !form.customer_phone.trim()) {
      toast.error("Nom et téléphone requis"); return;
    }
    setSubmitting(true);
    try {
      const r = await apiClient.post("/public/subscriptions/order", {
        plan_id: plan.id,
        period,
        ...form,
      });
      setDone(r.data || { ok: true });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="subs-order-modal">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl">
        {done ? (
          <div className="p-8 text-center">
            <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 mb-4">
              <Check className="h-7 w-7 text-emerald-600" />
            </div>
            <h2 className="text-xl font-display font-bold">Demande enregistrée !</h2>
            <p className="text-sm text-slate-600 mt-2">{done.next_step || "Notre équipe vous contactera très bientôt."}</p>
            {done.payment_link_url && (
              <div className="mt-5 rounded-xl ring-1 ring-emerald-200 bg-emerald-50 p-4 text-left">
                <p className="text-xs font-semibold text-emerald-900 inline-flex items-center gap-1.5">
                  <Zap className="h-3.5 w-3.5" /> Régler maintenant via Mobile Money
                </p>
                <p className="text-[11px] text-emerald-800 mt-1">
                  Vous pouvez payer immédiatement votre première échéance ({fmtXOF(amount)}) avec PawaPay (Orange / Moov / Telecel).
                </p>
                <a
                  href={done.payment_link_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm font-semibold hover:bg-emerald-700 shadow-sm"
                  data-testid="subs-pay-now-btn"
                >
                  Payer maintenant <ChevronRight className="h-4 w-4" />
                </a>
              </div>
            )}
            <button onClick={onClose} className="mt-6 inline-flex rounded-lg bg-sawali-blue text-white px-5 py-2 text-sm hover:bg-sawali-blue-light" data-testid="subs-modal-close-done">Fermer</button>
          </div>
        ) : (
          <>
            <div className="p-5 border-b">
              <p className="text-[10px] uppercase tracking-[0.3em] text-slate-500">Souscription</p>
              <h2 className="text-xl font-display font-bold mt-1" data-testid="subs-modal-title">{plan.name}</h2>
              <p className="text-[11px] text-slate-500 mt-1">
                Code <code className="font-mono">{plan.code}</code> • {period === "monthly" ? "Mensuel" : "Annuel"} • <strong>{fmtXOF(amount)}</strong>
              </p>
            </div>
            <div className="p-5 space-y-3">
              <label className="text-xs font-semibold block">
                Nom complet *
                <input value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="subs-form-name" required />
              </label>
              <label className="text-xs font-semibold block">
                Téléphone (WhatsApp idéalement) *
                <input value={form.customer_phone} onChange={(e) => setForm({ ...form, customer_phone: e.target.value })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" placeholder={phonePlaceholder()} data-testid="subs-form-phone" required />
              </label>
              <label className="text-xs font-semibold block">
                Email (optionnel)
                <input type="email" value={form.customer_email} onChange={(e) => setForm({ ...form, customer_email: e.target.value })} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="subs-form-email" />
              </label>
              <label className="text-xs font-semibold block">
                Message complémentaire
                <textarea value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} rows={3} className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="subs-form-message" />
              </label>
              <p className="text-[10px] text-slate-500 italic">En soumettant ce formulaire, vous acceptez d'être recontacté par notre équipe pour finaliser votre souscription.</p>
            </div>
            <div className="flex justify-end gap-2 p-5 border-t bg-slate-50 rounded-b-2xl">
              <button onClick={onClose} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2">Annuler</button>
              <button onClick={submit} disabled={submitting} className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-sawali-blue text-white px-4 py-2 hover:bg-sawali-blue-light disabled:opacity-50" data-testid="subs-form-submit">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                {submitting ? "Envoi…" : "Valider ma souscription"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
