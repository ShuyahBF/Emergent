import React, { useEffect, useState, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { ArrowLeft, Calendar, Tag, TrendingUp, Layers, ChevronLeft, ChevronRight } from "lucide-react";

export default function CaseStudyDetail() {
  const { slug } = useParams();
  const [c, setC] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    apiClient.get(`/case-studies/${slug}`).then((r) => setC(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Introuvable"));
  }, [slug]);

  if (error) {
    return (
      <section className="py-20">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <h1 className="text-3xl font-display font-bold text-white">{error}</h1>
          <Link to="/etudes-de-cas" className="mt-6 inline-block text-sawali-blue-light underline">← Retour aux études de cas</Link>
        </div>
      </section>
    );
  }
  if (!c) return <section className="py-20 text-center text-slate-400">Chargement...</section>;

  return (
    <article className="py-16" data-testid="case-study-detail">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <Link to="/etudes-de-cas" className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light hover:text-white inline-flex items-center gap-1">
          <ArrowLeft className="h-3 w-3" /> Toutes les études
        </Link>
        <div className="mt-6 flex items-center gap-3 text-[10px] uppercase tracking-widest text-sawali-blue-light">
          {c.sector && <span>{c.sector}</span>}
          {c.year && <span className="inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> {c.year}</span>}
          {c.duration && <span>{c.duration}</span>}
        </div>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">{c.title}</h1>
        {c.client_name && <p className="mt-2 text-slate-400">Client : <span className="text-white">{c.client_name}</span></p>}
        {c.summary && <p className="mt-6 text-lg text-slate-300 leading-relaxed max-w-3xl">{c.summary}</p>}

        {c.cover_image_url && (
          <div className="mt-10 rounded-2xl overflow-hidden border border-white/10">
            <img src={c.cover_image_url} alt={c.title} className="w-full max-h-[480px] object-cover" />
          </div>
        )}

        {c.kpis?.length > 0 && (
          <div className="mt-10 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4" data-testid="case-study-kpis">
            {c.kpis.map((k, i) => (
              <div key={i} className="glow-card rounded-xl p-5">
                <p className="text-[10px] uppercase tracking-widest text-slate-400">{k.label}</p>
                <p className="mt-2 text-3xl font-display font-bold text-gradient-blue">
                  {k.value}<span className="text-base text-slate-400">{k.suffix || ""}</span>
                </p>
              </div>
            ))}
          </div>
        )}

        {(c.before_image_url || c.after_image_url) && (
          <div className="mt-12">
            <h2 className="text-2xl font-display font-bold text-white mb-5">Avant / Après</h2>
            <BeforeAfter before={c.before_image_url} after={c.after_image_url} />
          </div>
        )}

        <div className="mt-12 grid lg:grid-cols-3 gap-8">
          <Block title="Le défi" content={c.challenge} />
          <Block title="Notre solution" content={c.solution} />
          <Block title="Résultats" content={c.results} highlight />
        </div>

        {c.gallery?.length > 0 && (
          <div className="mt-14">
            <h2 className="text-2xl font-display font-bold text-white mb-5">Galerie</h2>
            <Gallery images={c.gallery} />
          </div>
        )}

        {c.tags?.length > 0 && (
          <div className="mt-12">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400 mb-3">Technologies utilisées</p>
            <div className="flex flex-wrap gap-2">
              {c.tags.map((t, i) => (
                <span key={i} className="text-xs px-3 py-1.5 rounded-full bg-sawali-blue/10 text-sawali-blue-light border border-sawali-blue/30 inline-flex items-center gap-1">
                  <Tag className="h-3 w-3" /> {t}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mt-16 rounded-2xl border border-sawali-blue/30 bg-gradient-to-br from-[#0E1F3D] to-[#081226] p-8 lg:p-10">
          <h3 className="text-2xl font-display font-bold text-white">Un projet similaire ?</h3>
          <p className="mt-2 text-slate-300">Échangeons sur votre besoin lors d'un appel découverte.</p>
          <Link to="/rdv" className="mt-5 btn-electric inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium">
            Réserver un RDV
          </Link>
        </div>
      </div>
    </article>
  );
}

const Block = ({ title, content, highlight }) => {
  if (!content) return null;
  return (
    <div className={`rounded-xl border p-6 ${highlight ? "border-sawali-blue/40 bg-sawali-blue/5" : "border-white/10 bg-white/[0.02]"}`}>
      <h3 className="text-lg font-display font-semibold text-white">{title}</h3>
      <div className="mt-3 text-sm text-slate-300 prose-sawali whitespace-pre-wrap leading-relaxed">{content}</div>
    </div>
  );
};

// Before/After draggable slider
const BeforeAfter = ({ before, after }) => {
  const [pos, setPos] = useState(50);
  const wrap = useRef(null);
  const onMove = (clientX) => {
    if (!wrap.current) return;
    const r = wrap.current.getBoundingClientRect();
    const p = ((clientX - r.left) / r.width) * 100;
    setPos(Math.max(0, Math.min(100, p)));
  };
  if (!before && after) return <img src={after} alt="" className="w-full rounded-2xl border border-white/10" />;
  if (before && !after) return <img src={before} alt="" className="w-full rounded-2xl border border-white/10" />;
  return (
    <div
      ref={wrap}
      className="relative rounded-2xl overflow-hidden border border-white/10 select-none cursor-ew-resize"
      onMouseMove={(e) => e.buttons === 1 && onMove(e.clientX)}
      onTouchMove={(e) => onMove(e.touches[0].clientX)}
      onClick={(e) => onMove(e.clientX)}
      data-testid="before-after-slider"
    >
      <img src={after} alt="Après" className="w-full block max-h-[520px] object-cover" />
      <div className="absolute inset-0 overflow-hidden" style={{ width: `${pos}%` }}>
        <img src={before} alt="Avant" className="w-full max-h-[520px] object-cover" style={{ width: wrap.current?.clientWidth || "100%" }} />
        <span className="absolute top-3 left-3 text-[10px] uppercase tracking-widest bg-black/60 text-white px-2 py-1 rounded">Avant</span>
      </div>
      <span className="absolute top-3 right-3 text-[10px] uppercase tracking-widest bg-black/60 text-white px-2 py-1 rounded">Après</span>
      <div className="absolute top-0 bottom-0 w-0.5 bg-sawali-blue" style={{ left: `${pos}%` }}>
        <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-9 w-9 rounded-full bg-sawali-blue text-white flex items-center justify-center shadow-lg">
          <ChevronLeft className="h-3 w-3" /><ChevronRight className="h-3 w-3" />
        </div>
      </div>
    </div>
  );
};

const Gallery = ({ images }) => (
  <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
    {images.map((src, i) => (
      <a key={i} href={src} target="_blank" rel="noreferrer" className="block rounded-xl overflow-hidden border border-white/10 group">
        <img src={src} alt="" className="w-full h-44 object-cover group-hover:scale-105 transition-transform duration-300" />
      </a>
    ))}
  </div>
);
