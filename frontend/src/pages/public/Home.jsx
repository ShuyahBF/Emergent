import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ShieldCheck, Sparkles, Code2, Database, Smartphone, Globe2, Cpu, Quote, Star, MapPin, User as UserIcon, MessageCircle } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useI18n } from "@/contexts/I18nContext";
import { HERO_BG, OFFICE_IMG, CODE_IMG } from "@/lib/brand";
import DeploymentsMap from "@/components/DeploymentsMap";
import HeroVideoSection from "@/components/HeroVideoSection";
import HomeStatsTicker from "@/components/HomeStatsTicker";
import TeamPresenceBadge from "@/components/TeamPresenceBadge";
import AdBannerSlot from "@/components/AdBannerSlot";
import WeatherWidget from "@/components/WeatherWidget";

const ICONS = { Globe: Globe2, Smartphone, Database, Cpu, Code: Code2 };

export default function Home() {
  const { lang, t } = useI18n();
  const [home, setHome] = useState(null);
  const [exp, setExp] = useState(null);
  const [spec, setSpec] = useState(null);
  const [testimonials, setTestimonials] = useState([]);
  const [npsStats, setNpsStats] = useState(null);

  // Iter43-fix24as (2026-02) — TikTok validation : la page d'accueil DOIT
  // afficher le nom de l'app exactement (« sawalismartsystems ») dans le
  // titre de la fenêtre/onglet du navigateur.
  useEffect(() => {
    document.title = "sawalismartsystems — SAWALI SMART SYSTEMS";
  }, []);

  // Iter40-content-i18n — Re-fetch content whenever the active language changes.
  useEffect(() => {
    apiClient.get("/content", { params: { lang } }).then((r) => {
      const map = Object.fromEntries(r.data.map((c) => [c.slug, c]));
      setHome(map.home_hero);
      setExp(map.experience);
      setSpec(map.specialisations);
    }).catch(() => {});
  }, [lang]);

  useEffect(() => {
    apiClient.get("/testimonials").then((r) => setTestimonials(r.data.slice(0, 3))).catch(() => {});
    apiClient.get("/testimonials/stats").then((r) => setNpsStats(r.data)).catch(() => {});
  }, []);

  const metrics = exp?.metadata?.metrics || [];
  const specs = spec?.metadata?.items || [];

  return (
    <>
      {/* Iter38r-fix9w — Monetized ad banner */}
      <AdBannerSlot placement="public" />
      {/* HERO */}
      <section
        className="relative min-h-[88vh] flex items-center overflow-hidden"
        style={{
          background: "var(--block-hero-bg, transparent)",
          color: "var(--block-hero-text, inherit)",
        }}
        data-testid="home-hero"
      >
        <div className="absolute inset-0 -z-10">
          <img src={HERO_BG} alt="" className="w-full h-full object-cover" />
          <div className="absolute inset-0 bg-[#081226]/80" />
          <div className="absolute inset-0 grid-bg opacity-50" />
        </div>
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-24 grid lg:grid-cols-12 gap-10">
          <div className="lg:col-span-7 animate-fade-up">
            <div className="mb-5">
              <HomeStatsTicker />
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-sawali-blue/40 bg-sawali-blue/10 px-3 py-1 text-xs uppercase tracking-[0.25em] text-sawali-blue-light">
              <Sparkles className="h-3 w-3" />
              {home?.metadata?.kicker || t("public.home.hero.kicker", "sawalismartsystems · Software Engineering")}
            </div>
            <div className="mt-3">
              <TeamPresenceBadge tone="dark" />
            </div>
            <h1 className="mt-6 text-4xl sm:text-5xl lg:text-6xl font-display font-bold leading-[1.05] text-white">
              {home?.title || t("public.home.hero.title", "L'ingénierie logicielle au service de votre transformation.")}
            </h1>
            <div
              className="mt-6 max-w-2xl text-base sm:text-lg text-slate-300 prose-sawali"
              dangerouslySetInnerHTML={{ __html: home?.body_html || `<p>${t("public.home.hero.body", "Solutions sur-mesure, robustes et évolutives pour les entreprises africaines exigeantes.")}</p>` }}
            />
            <div className="mt-10 flex flex-wrap gap-3">
              <Link to="/rdv" className="btn-electric inline-flex items-center gap-2 rounded-lg px-5 py-3 font-medium" data-testid="hero-cta-rdv">
                {t("public.home.hero.cta_rdv", "Réserver un rendez-vous")} <ArrowRight className="h-4 w-4" />
              </Link>
              <Link to="/specialisations" className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-5 py-3 text-white hover:bg-white/5 transition" data-testid="hero-cta-specs">
                {t("public.home.hero.cta_specs", "Découvrir nos spécialisations")}
              </Link>
              <Link to="/login" className="inline-flex items-center gap-2 rounded-lg border border-sawali-blue-light/40 px-5 py-3 text-sawali-blue-light hover:bg-sawali-blue/10 transition" data-testid="hero-cta-login">
                <ShieldCheck className="h-4 w-4" /> {t("public.home.hero.cta_loois", "Espace Loois")}
              </Link>
              {/* Iter38r-fix9o — Conversion CTA: WhatsApp express access */}
              <Link
                to="/login?wa=1"
                className="group inline-flex items-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 px-5 py-3 text-white font-medium shadow-lg shadow-emerald-900/40 transition transform hover:-translate-y-0.5"
                data-testid="hero-cta-whatsapp"
              >
                <MessageCircle className="h-4 w-4" />
                <span>{t("public.home.hero.cta_whatsapp", "Découvrir en 30s via WhatsApp")}</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </div>
          </div>

          <div className="lg:col-span-5 grid grid-cols-2 gap-4 self-end">
            {/* Iter43-fix20 — Weather widget détaillé (placement hero) */}
            <div className="col-span-2">
              <WeatherWidget variant="detailed" placement="public" />
            </div>
            {(metrics.length ? metrics : [
              { label: t("public.home.metric.years", "Années d'expérience"), value: "10+" },
              { label: t("public.home.metric.projects", "Projets livrés"), value: "50+" },
              { label: t("public.home.metric.clients", "Clients"), value: "30+" },
              { label: t("public.home.metric.availability", "Disponibilité"), value: "24/7" },
            ]).map((m, i) => (
              <div key={i} className="glow-card rounded-xl p-5" data-testid={`hero-metric-${i}`}>
                <div className="text-3xl sm:text-4xl font-display font-bold text-gradient-blue">{m.value}</div>
                <div className="text-xs uppercase tracking-[0.2em] text-slate-400 mt-2">{m.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* SPECIALISATIONS PREVIEW */}
      <section
        className="py-24"
        style={{
          background: "var(--block-specialisations-bg, #0a1730)",
          color: "var(--block-specialisations-text, inherit)",
        }}
        data-testid="home-specialisations"
      >
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex items-end justify-between flex-wrap gap-6 mb-10">
            <div>
              <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.home.specs.kicker", "Nos savoir-faire")}</p>
              <h2 className="mt-2 text-3xl lg:text-4xl font-display font-bold text-white">{t("public.home.specs.title", "Spécialisations")}</h2>
            </div>
            <Link to="/specialisations" className="text-sm text-sawali-blue-light hover:text-white inline-flex items-center gap-1">
              {t("public.home.specs.see_all", "Voir tout")} <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {(specs.length ? specs : []).map((s, i) => {
              const Icon = ICONS[s.icon] || Code2;
              return (
                <div key={i} className="glow-card rounded-xl p-6" data-testid={`spec-card-${i}`}>
                  <Icon className="h-7 w-7 text-sawali-blue-light" />
                  <h3 className="mt-4 text-lg font-display font-semibold text-white">{s.title}</h3>
                  <p className="mt-2 text-sm text-slate-400 leading-relaxed">{s.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* HERO VIDEO SECTION (parametrable) */}
      <HeroVideoSection />

      {/* DEPLOYMENTS MAP */}
      <DeploymentsMap />

      {/* TESTIMONIALS */}
      {testimonials.length > 0 && (
        <section className="py-24 bg-[#0a1730]" data-testid="home-testimonials">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex items-end justify-between flex-wrap gap-6 mb-10">
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.home.testi.kicker", "Voix de nos clients")}</p>
                <h2 className="mt-2 text-3xl lg:text-4xl font-display font-bold text-white">{t("public.home.testi.title", "Ils témoignent")}</h2>
                {npsStats && npsStats.count > 0 && (
                  <p className="mt-2 text-sm text-slate-400">
                    {t("public.home.testi.nps_label", "Score NPS")} : <span className="text-gradient-blue font-display font-bold text-lg">{npsStats.nps}</span> · {t("public.home.testi.average_label", "Note moyenne")} : <span className="text-white">{npsStats.average_score}/10</span> · {t("public.home.testi.published_count", "{count} avis publiés").replace("{count}", String(npsStats.count))}
                  </p>
                )}
              </div>
              <Link to="/temoignages" className="text-sm text-sawali-blue-light hover:text-white inline-flex items-center gap-1">
                {t("public.home.testi.see_all", "Voir tous les avis")} <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {testimonials.map((t) => {
                const place = [t.city, t.country].filter(Boolean).join(", ");
                return (
                  <article key={t.id} className="glow-card rounded-xl p-6 flex flex-col" data-testid={`home-testimonial-${t.id}`}>
                    <div className="flex items-center justify-between">
                      <Quote className="h-6 w-6 text-sawali-blue-light/70" />
                      {t.rating_5 != null ? (
                        <span className="inline-flex items-center gap-0.5">
                          {[1, 2, 3, 4, 5].map((n) => (
                            <Star key={n} className={`h-4 w-4 ${t.rating_5 >= n ? "fill-amber-400 text-amber-400" : "text-slate-600"}`} />
                          ))}
                        </span>
                      ) : (
                        <span className="text-2xl font-display font-bold text-gradient-blue">{t.score}<span className="text-xs text-slate-500">/10</span></span>
                      )}
                    </div>
                    {t.comment && <p className="mt-4 text-slate-200 text-sm leading-relaxed flex-1 line-clamp-4">"{t.comment}"</p>}
                    <div className="mt-5 pt-4 border-t border-white/10 flex items-center gap-3">
                      {t.photo_url ? (
                        <img src={t.photo_url} alt="" className="h-10 w-10 rounded-full object-cover ring-1 ring-white/20" />
                      ) : (
                        <div className="h-10 w-10 rounded-full bg-sawali-blue/15 ring-1 ring-sawali-blue/30 flex items-center justify-center">
                          <UserIcon className="h-4 w-4 text-sawali-blue-light" />
                        </div>
                      )}
                      <div className="min-w-0">
                        <p className="text-sm font-display font-semibold text-white truncate">{t.client_name}</p>
                        {t.client_company && <p className="text-xs text-sawali-blue-light truncate">{t.client_company}</p>}
                        {place && <p className="text-[11px] text-slate-400 inline-flex items-center gap-1"><MapPin className="h-3 w-3" /> {place}</p>}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* CULTURE / OFFICE */}
      <section className="py-24" data-testid="home-culture">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 grid lg:grid-cols-2 gap-12 items-center">
          <div className="relative rounded-2xl overflow-hidden border border-white/10">
            <img src={OFFICE_IMG} alt="Studio SAWALI" className="w-full h-[420px] object-cover" />
            <div className="absolute inset-0 bg-gradient-to-tr from-[#081226]/80 via-transparent to-transparent" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">{t("public.home.exp.kicker", "L'expérience SAWALI")}</p>
            <h2 className="mt-2 text-3xl lg:text-4xl font-display font-bold text-white">{t("public.home.exp.title", "Une équipe, une exigence : la qualité.")}</h2>
            <p className="mt-5 text-slate-300 leading-relaxed">
              {t("public.home.exp.body", "Nous combinons rigueur d'ingénierie et proximité humaine. Chaque projet est suivi par un référent dédié, livré avec une documentation claire et une supervision continue.")}
            </p>
            <div className="mt-8 grid grid-cols-2 gap-4">
              {[
                { k: t("public.home.exp.method_k", "Méthodologie"), v: t("public.home.exp.method_v", "Agile + Code review systématique") },
                { k: t("public.home.exp.stack_k", "Stack"), v: t("public.home.exp.stack_v", "Web, Mobile, Cloud, IA") },
                { k: t("public.home.exp.support_k", "Support"), v: t("public.home.exp.support_v", "SLA & maintenance") },
                { k: t("public.home.exp.security_k", "Sécurité"), v: t("public.home.exp.security_v", "Bonnes pratiques OWASP") },
              ].map((b, i) => (
                <div key={i} className="rounded-lg border border-white/10 p-4 bg-white/[0.02]">
                  <p className="text-[10px] uppercase tracking-[0.2em] text-sawali-blue-light">{b.k}</p>
                  <p className="text-sm text-white mt-1">{b.v}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20" data-testid="home-cta">
        <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
          <div className="relative overflow-hidden rounded-2xl border border-sawali-blue/30 bg-gradient-to-br from-[#0E1F3D] to-[#081226] p-8 lg:p-12">
            <div className="absolute -right-20 -bottom-20 h-72 w-72 rounded-full bg-sawali-blue/20 blur-3xl" />
            <div className="relative grid lg:grid-cols-3 gap-6 items-center">
              <div className="lg:col-span-2">
                <h3 className="text-2xl lg:text-3xl font-display font-bold text-white">{t("public.home.cta.title", "Un projet en tête ? Parlons-en.")}</h3>
                <p className="mt-2 text-slate-300">{t("public.home.cta.body", "Réservez un rendez-vous gratuit avec notre équipe d'ingénierie.")}</p>
              </div>
              <Link to="/rdv" className="btn-electric inline-flex items-center justify-center gap-2 rounded-lg px-6 py-3 font-medium" data-testid="cta-bottom-rdv">
                {t("public.home.cta.button", "Prendre rendez-vous")} <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
