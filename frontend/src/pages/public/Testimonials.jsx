import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { Quote, Star, TrendingUp, MapPin, User as UserIcon } from "lucide-react";
import { useI18n } from "@/contexts/I18nContext";

export default function Testimonials() {
  const { t } = useI18n();
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
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.testi.kicker", "Voix de nos clients")}</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{t("public.testi.title", "Témoignages")}</h1>
        <p className="mt-4 text-slate-300 max-w-2xl">
          {t("public.testi.subtitle", "Des avis vérifiés, recueillis automatiquement après chaque mission terminée.")}
        </p>

        {stats && stats.count > 0 && (
          <div className="mt-10 grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="nps-stats">
            <NpsCard label={t("public.testi.nps_label", "Score NPS")} value={stats.nps} suffix="" icon={TrendingUp} highlight />
            <NpsCard label={t("public.testi.average_label", "Note moyenne")} value={stats.average_score} suffix="/10" icon={Star} />
            <NpsCard label={t("public.testi.promoters", "Promoteurs")} value={stats.promoters} sub={`${Math.round((stats.promoters / stats.count) * 100)}%`} />
            <NpsCard label={t("public.testi.published_count", "Avis publiés")} value={stats.count} />
          </div>
        )}

        {items.length === 0 ? (
          <div className="mt-12 rounded-xl border border-dashed border-white/10 p-16 text-center text-slate-400" data-testid="testimonials-empty">
            {t("public.testi.empty", "Aucun témoignage publié pour le moment.")}
          </div>
        ) : (
          <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {items.map((tx) => <Card key={tx.id} tx={tx} t={t} />)}
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

const Card = ({ tx, t }) => {
  const place = [tx.city, tx.country].filter(Boolean).join(", ");
  return (
    <article className="glow-card rounded-xl p-6 flex flex-col" data-testid={`testimonial-${tx.id}`}>
      <div className="flex items-start justify-between gap-3">
        <Quote className="h-7 w-7 text-sawali-blue-light/70" />
        {tx.rating_5 != null ? (
          <Stars value={tx.rating_5} />
        ) : (
          <span className="text-2xl font-display font-bold text-gradient-blue">{tx.score}<span className="text-sm text-slate-500">/10</span></span>
        )}
      </div>
      {tx.comment ? (
        <p className="mt-4 text-slate-200 leading-relaxed flex-1">"{tx.comment}"</p>
      ) : (
        <p className="mt-4 text-slate-500 italic flex-1">{t("public.testi.no_comment", "Avis sans commentaire écrit.")}</p>
      )}
      <div className="mt-5 pt-5 border-t border-white/10 flex items-center gap-3">
        {tx.photo_url ? (
          <img src={tx.photo_url} alt="" className="h-11 w-11 rounded-full object-cover ring-1 ring-white/20" />
        ) : (
          <div className="h-11 w-11 rounded-full bg-sawali-blue/15 ring-1 ring-sawali-blue/30 flex items-center justify-center">
            <UserIcon className="h-5 w-5 text-sawali-blue-light" />
          </div>
        )}
        <div className="min-w-0">
          <p className="text-sm font-display font-semibold text-white truncate">{tx.client_name}</p>
          {tx.client_company && <p className="text-xs text-sawali-blue-light truncate">{tx.client_company}</p>}
          {place && (
            <p className="text-[11px] text-slate-400 mt-0.5 inline-flex items-center gap-1">
              <MapPin className="h-3 w-3" /> {place}
            </p>
          )}
        </div>
      </div>
      {tx.subject && <p className="mt-3 text-[11px] text-slate-500">{t("public.testi.about", "À propos de :")} {tx.subject}</p>}
    </article>
  );
};

const Stars = ({ value }) => (
  <span className="inline-flex items-center gap-0.5">
    {[1, 2, 3, 4, 5].map((n) => (
      <Star key={n} className={`h-4 w-4 ${value >= n ? "fill-amber-400 text-amber-400" : "text-slate-600"}`} />
    ))}
  </span>
);
