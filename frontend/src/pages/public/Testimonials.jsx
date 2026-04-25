import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Quote, Star, TrendingUp } from "lucide-react";

export default function Testimonials() {
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    Promise.all([
      apiClient.get("/testimonials"),
      apiClient.get("/testimonials/stats"),
    ]).then(([a, b]) => { setItems(a.data); setStats(b.data); }).catch(() => {});
  }, []);

  return (
    <section className="py-20" data-testid="testimonials-page">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Voix de nos clients</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">Témoignages</h1>
        <p className="mt-4 text-slate-300 max-w-2xl">
          Des avis vérifiés, recueillis automatiquement après chaque mission terminée.
        </p>

        {stats && stats.count > 0 && (
          <div className="mt-10 grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="nps-stats">
            <NpsCard label="Score NPS" value={stats.nps} suffix="" icon={TrendingUp} highlight />
            <NpsCard label="Note moyenne" value={stats.average_score} suffix="/10" icon={Star} />
            <NpsCard label="Promoteurs" value={stats.promoters} sub={`${Math.round((stats.promoters / stats.count) * 100)}%`} />
            <NpsCard label="Avis publiés" value={stats.count} />
          </div>
        )}

        {items.length === 0 ? (
          <div className="mt-12 rounded-xl border border-dashed border-white/10 p-16 text-center text-slate-400" data-testid="testimonials-empty">
            Aucun témoignage publié pour le moment.
          </div>
        ) : (
          <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {items.map((t) => <Card key={t.id} t={t} />)}
          </div>
        )}
      </div>
    </section>
  );
}

const NpsCard = ({ label, value, suffix = "", sub, icon: Icon, highlight }) => (
  <div className={`glow-card rounded-xl p-5 ${highlight ? "border-sawali-blue/60" : ""}`}>
    <div className="flex items-center justify-between">
      <p className="text-[10px] uppercase tracking-[0.2em] text-slate-400">{label}</p>
      {Icon && <Icon className="h-4 w-4 text-sawali-blue-light" />}
    </div>
    <p className="mt-2 text-3xl font-display font-bold text-gradient-blue">
      {value !== null && value !== undefined ? value : "—"}<span className="text-base text-slate-400">{suffix}</span>
    </p>
    {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
  </div>
);

const Card = ({ t }) => {
  const tone = t.score >= 9 ? "text-emerald-300" : t.score >= 7 ? "text-sky-300" : "text-amber-300";
  return (
    <article className="glow-card rounded-xl p-6 flex flex-col" data-testid={`testimonial-${t.id}`}>
      <div className="flex items-center justify-between">
        <Quote className="h-7 w-7 text-sawali-blue-light/70" />
        <span className={`text-2xl font-display font-bold ${tone}`}>{t.score}<span className="text-sm text-slate-500">/10</span></span>
      </div>
      {t.comment ? (
        <p className="mt-4 text-slate-200 leading-relaxed flex-1">"{t.comment}"</p>
      ) : (
        <p className="mt-4 text-slate-500 italic flex-1">Avis sans commentaire écrit.</p>
      )}
      <div className="mt-5 pt-5 border-t border-white/10">
        <p className="text-sm font-display font-semibold text-white">{t.client_name}</p>
        {t.client_company && <p className="text-xs text-sawali-blue-light">{t.client_company}</p>}
        {t.subject && <p className="text-xs text-slate-500 mt-1">À propos de : {t.subject}</p>}
      </div>
    </article>
  );
};
