import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { Calendar, Clock, ArrowRight, Tag, FileText, Eye } from "lucide-react";

export default function Blog() {
  const [items, setItems] = useState([]);
  const [tags, setTags] = useState([]);
  const [activeTag, setActiveTag] = useState(null);

  useEffect(() => {
    const url = activeTag ? `/blog?tag=${encodeURIComponent(activeTag)}` : "/blog";
    apiClient.get(url).then((r) => setItems(r.data)).catch(() => {});
  }, [activeTag]);

  useEffect(() => { apiClient.get("/blog/tags").then((r) => setTags(r.data)).catch(() => {}); }, []);

  const featured = items.find((p) => p.featured);
  const rest = items.filter((p) => !featured || p.id !== featured.id);

  return (
    <section className="py-20" data-testid="blog-page">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Blog technique</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">Insights & savoir-faire</h1>
        <p className="mt-4 text-slate-300 max-w-2xl">
          Décryptages, retours d'expérience et bonnes pratiques d'ingénierie logicielle, par l'équipe SAWALI.
        </p>

        {tags.length > 0 && (
          <div className="mt-8 flex flex-wrap gap-2" data-testid="blog-tags">
            <button onClick={() => setActiveTag(null)}
                    className={`text-xs px-3 py-1.5 rounded-full transition ${!activeTag ? "bg-sawali-blue text-white" : "bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10"}`}>
              Tous ({items.length || 0})
            </button>
            {tags.map((t) => (
              <button key={t.tag} onClick={() => setActiveTag(t.tag)}
                      className={`text-xs px-3 py-1.5 rounded-full transition inline-flex items-center gap-1 ${activeTag === t.tag ? "bg-sawali-blue text-white" : "bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10"}`}>
                <Tag className="h-3 w-3" /> {t.tag} <span className="opacity-60">·{t.count}</span>
              </button>
            ))}
          </div>
        )}

        {items.length === 0 ? (
          <div className="mt-12 rounded-xl border border-dashed border-white/10 p-16 text-center text-slate-400" data-testid="blog-empty">
            <FileText className="h-10 w-10 mx-auto text-sawali-blue-light/60" />
            <p className="mt-3">Aucun article pour le moment. Revenez bientôt.</p>
          </div>
        ) : (
          <>
            {featured && !activeTag && (
              <Link to={`/blog/${featured.slug}`} className="mt-12 grid lg:grid-cols-2 gap-8 group glow-card rounded-2xl overflow-hidden" data-testid={`blog-featured-${featured.slug}`}>
                <div className="relative h-64 lg:h-full bg-gradient-to-br from-sawali-navy to-sawali-navy-dark overflow-hidden">
                  {featured.cover_image_url ? <img src={featured.cover_image_url} alt={featured.title} className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-500" /> : <div className="grid-bg h-full" />}
                  <span className="absolute top-4 left-4 text-[10px] uppercase tracking-widest bg-sawali-blue px-2 py-1 rounded text-white">À la une</span>
                </div>
                <div className="p-6 lg:p-8 flex flex-col justify-center">
                  <Meta post={featured} />
                  <h2 className="mt-3 text-2xl lg:text-3xl font-display font-bold text-white leading-tight group-hover:text-sawali-blue-light transition">
                    {featured.title}
                  </h2>
                  {featured.excerpt && <p className="mt-4 text-slate-300 leading-relaxed">{featured.excerpt}</p>}
                  <span className="mt-6 text-sm text-sawali-blue-light inline-flex items-center gap-1 group-hover:gap-2 transition-all">
                    Lire l'article <ArrowRight className="h-4 w-4" />
                  </span>
                </div>
              </Link>
            )}

            <div className="mt-10 grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {(activeTag ? items : rest).map((p) => <Card key={p.id} p={p} />)}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

const Meta = ({ post }) => {
  const date = post.published_at || post.created_at;
  return (
    <div className="flex items-center gap-3 text-[10px] uppercase tracking-widest text-sawali-blue-light flex-wrap">
      {date && <span className="inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> {new Date(date).toLocaleDateString("fr-FR")}</span>}
      {post.reading_time_min > 0 && <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {post.reading_time_min} min</span>}
      {(post.views ?? 0) > 0 && <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" /> {post.views}</span>}
    </div>
  );
};

const Card = ({ p }) => (
  <Link to={`/blog/${p.slug}`} className="group glow-card rounded-xl overflow-hidden flex flex-col" data-testid={`blog-${p.slug}`}>
    <div className="h-44 bg-gradient-to-br from-sawali-navy to-sawali-navy-dark overflow-hidden">
      {p.cover_image_url ? <img src={p.cover_image_url} alt={p.title} className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-500" /> : <div className="grid-bg h-full" />}
    </div>
    <div className="p-5 flex-1 flex flex-col">
      <Meta post={p} />
      <h3 className="mt-2 font-display font-semibold text-white text-lg leading-tight group-hover:text-sawali-blue-light transition line-clamp-2">{p.title}</h3>
      {p.excerpt && <p className="mt-3 text-sm text-slate-300 line-clamp-3">{p.excerpt}</p>}
      {p.tags?.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {p.tags.slice(0, 3).map((t) => (
            <span key={t} className="text-[10px] px-2 py-0.5 rounded bg-sawali-blue/10 text-sawali-blue-light border border-sawali-blue/20">{t}</span>
          ))}
        </div>
      )}
      <div className="mt-5 pt-4 border-t border-white/10 flex items-center justify-between">
        <p className="text-xs text-slate-400 truncate">{p.author_name}</p>
        <ArrowRight className="h-4 w-4 text-sawali-blue-light group-hover:translate-x-1 transition-transform" />
      </div>
    </div>
  </Link>
);
