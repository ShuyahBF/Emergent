import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { ArrowRight, TrendingUp, Layers, Tag, Calendar } from "lucide-react";
import { useI18n } from "@/contexts/I18nContext";

export default function CaseStudies() {
  const { t } = useI18n();
  const [items, setItems] = useState([]);
  useEffect(() => { apiClient.get("/case-studies").then((r) => setItems(r.data)).catch(() => {}); }, []);

  return (
    <section
      className="py-20"
      style={{
        background: "var(--block-experience-bg, transparent)",
        color: "var(--block-experience-text, inherit)",
      }}
      data-testid="case-studies-page"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.cases.kicker", "Réalisations")}</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{t("public.cases.title", "Études de cas")}</h1>
        <p className="mt-4 text-slate-300 max-w-2xl">
          {t("public.cases.subtitle", "Plongez dans nos missions livrées : contexte, défis, solutions et résultats mesurés.")}
        </p>

        {items.length === 0 ? (
          <div className="mt-12 rounded-xl border border-dashed border-white/10 p-16 text-center text-slate-400" data-testid="case-studies-empty">
            <Layers className="h-10 w-10 mx-auto text-sawali-blue-light/60" />
            <p className="mt-3">{t("public.cases.empty", "Aucune étude de cas publiée. Revenez prochainement.")}</p>
          </div>
        ) : (
          <div className="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {items.map((c) => <Card key={c.id} c={c} t={t} />)}
          </div>
        )}
      </div>
    </section>
  );
}

const Card = ({ c, t }) => (
  <Link to={`/etudes-de-cas/${c.slug}`} className="group glow-card rounded-xl overflow-hidden flex flex-col" data-testid={`case-study-${c.slug}`}>
    <div className="relative h-44 bg-gradient-to-br from-sawali-navy to-sawali-navy-dark overflow-hidden">
      {c.cover_image_url ? (
        <img src={c.cover_image_url} alt={c.title} className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-500" />
      ) : (
        <div className="h-full w-full grid-bg flex items-center justify-center">
          <Layers className="h-10 w-10 text-sawali-blue-light/50" />
        </div>
      )}
      {c.featured && (
        <span className="absolute top-3 left-3 text-[10px] uppercase tracking-widest bg-sawali-blue px-2 py-1 rounded text-white">{t("public.cases.featured", "Mise en avant")}</span>
      )}
    </div>
    <div className="p-5 flex-1 flex flex-col">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-sawali-blue-light">
        {c.sector && <span>{c.sector}</span>}
        {c.sector && c.year && <span>•</span>}
        {c.year && <span className="inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> {c.year}</span>}
      </div>
      <h3 className="mt-2 font-display font-semibold text-white text-lg leading-tight">{c.title}</h3>
      {c.client_name && <p className="text-xs text-slate-400 mt-1">{t("public.cases.client_label", "Client")} : {c.client_name}</p>}
      {c.summary && <p className="mt-3 text-sm text-slate-300 line-clamp-3">{c.summary}</p>}

      {c.kpis?.length > 0 && (
        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          {c.kpis.slice(0, 3).map((k, i) => (
            <div key={i} className="rounded-lg border border-white/10 bg-white/[0.03] p-2">
              <p className="text-base font-display font-bold text-gradient-blue leading-tight">{k.value}{k.suffix || ""}</p>
              <p className="text-[9px] uppercase tracking-widest text-slate-400 mt-0.5 line-clamp-1">{k.label}</p>
            </div>
          ))}
        </div>
      )}

      {c.tags?.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {c.tags.slice(0, 4).map((tag, i) => (
            <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-sawali-blue/10 text-sawali-blue-light border border-sawali-blue/20">{tag}</span>
          ))}
        </div>
      )}

      <span className="mt-5 text-sm text-sawali-blue-light inline-flex items-center gap-1 group-hover:gap-2 transition-all">
        {t("public.cases.read_more", "Lire l'étude")} <ArrowRight className="h-4 w-4" />
      </span>
    </div>
  </Link>
);
