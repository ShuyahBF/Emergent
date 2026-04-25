import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { ArrowLeft, Calendar, Clock, Tag, User as UserIcon, Eye, ArrowRight } from "lucide-react";

export default function BlogPost() {
  const { slug } = useParams();
  const [p, setP] = useState(null);
  const [error, setError] = useState(null);
  const [related, setRelated] = useState([]);

  useEffect(() => {
    apiClient.get(`/blog/${slug}`).then((r) => {
      setP(r.data);
      const tag = r.data.tags?.[0];
      if (tag) {
        apiClient.get(`/blog?tag=${encodeURIComponent(tag)}`).then((rel) => setRelated(rel.data.filter((x) => x.slug !== slug).slice(0, 3))).catch(() => {});
      }
    }).catch((e) => setError(e?.response?.data?.detail || "Introuvable"));
  }, [slug]);

  if (error) {
    return (
      <section className="py-20">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <h1 className="text-3xl font-display font-bold text-white">{error}</h1>
          <Link to="/blog" className="mt-6 inline-block text-sawali-blue-light underline">← Retour au blog</Link>
        </div>
      </section>
    );
  }
  if (!p) return <section className="py-20 text-center text-slate-400">Chargement...</section>;

  const date = p.published_at || p.created_at;
  return (
    <article className="py-16" data-testid="blog-post">
      <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8">
        <Link to="/blog" className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light hover:text-white inline-flex items-center gap-1">
          <ArrowLeft className="h-3 w-3" /> Tous les articles
        </Link>
        <div className="mt-6 flex items-center gap-3 text-[10px] uppercase tracking-widest text-sawali-blue-light flex-wrap">
          {date && <span className="inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> {new Date(date).toLocaleDateString("fr-FR", { dateStyle: "long" })}</span>}
          {p.reading_time_min > 0 && <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" /> {p.reading_time_min} min de lecture</span>}
          {(p.views ?? 0) > 0 && <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" /> {p.views} vues</span>}
        </div>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white leading-[1.05]">{p.title}</h1>
        {p.excerpt && <p className="mt-4 text-lg text-slate-300 leading-relaxed">{p.excerpt}</p>}

        <div className="mt-8 flex items-center gap-3">
          {p.author_photo_url ? (
            <img src={p.author_photo_url} alt={p.author_name} className="h-11 w-11 rounded-full object-cover ring-1 ring-white/20" />
          ) : (
            <div className="h-11 w-11 rounded-full bg-sawali-blue/15 ring-1 ring-sawali-blue/30 flex items-center justify-center">
              <UserIcon className="h-5 w-5 text-sawali-blue-light" />
            </div>
          )}
          <div>
            <p className="text-sm text-white font-display font-semibold">{p.author_name}</p>
            {p.author_role && <p className="text-xs text-slate-400">{p.author_role}</p>}
          </div>
        </div>

        {p.cover_image_url && (
          <div className="mt-10 rounded-2xl overflow-hidden border border-white/10">
            <img src={p.cover_image_url} alt={p.title} className="w-full max-h-[480px] object-cover" />
          </div>
        )}

        <div className="mt-10 prose-sawali prose-invert text-slate-200 max-w-none" dangerouslySetInnerHTML={{ __html: p.body_html || "" }} />

        {p.tags?.length > 0 && (
          <div className="mt-12 pt-8 border-t border-white/10">
            <p className="text-xs uppercase tracking-[0.25em] text-slate-400 mb-3">Tags</p>
            <div className="flex flex-wrap gap-2">
              {p.tags.map((t) => (
                <Link key={t} to={`/blog?tag=${encodeURIComponent(t)}`} className="text-xs px-3 py-1.5 rounded-full bg-sawali-blue/10 text-sawali-blue-light border border-sawali-blue/30 inline-flex items-center gap-1 hover:bg-sawali-blue/20">
                  <Tag className="h-3 w-3" /> {t}
                </Link>
              ))}
            </div>
          </div>
        )}

        {related.length > 0 && (
          <div className="mt-14">
            <h2 className="text-2xl font-display font-bold text-white mb-5">À lire ensuite</h2>
            <div className="grid sm:grid-cols-3 gap-4">
              {related.map((r) => (
                <Link key={r.id} to={`/blog/${r.slug}`} className="glow-card rounded-xl p-5 group">
                  <p className="text-[10px] uppercase tracking-widest text-sawali-blue-light">{r.published_at && new Date(r.published_at).toLocaleDateString("fr-FR")}</p>
                  <h3 className="mt-2 font-display font-semibold text-white text-sm group-hover:text-sawali-blue-light line-clamp-2">{r.title}</h3>
                  <span className="mt-3 inline-flex items-center gap-1 text-xs text-sawali-blue-light">Lire <ArrowRight className="h-3 w-3" /></span>
                </Link>
              ))}
            </div>
          </div>
        )}

        <div className="mt-14 rounded-2xl border border-sawali-blue/30 bg-gradient-to-br from-[#0E1F3D] to-[#081226] p-8">
          <h3 className="text-xl font-display font-bold text-white">Vous avez un projet ?</h3>
          <p className="mt-2 text-slate-300 text-sm">Échangeons sur votre besoin lors d'un appel découverte.</p>
          <Link to="/rdv" className="mt-4 btn-electric inline-flex items-center gap-2 rounded-lg px-5 py-2.5 text-sm font-medium">
            Réserver un RDV <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </article>
  );
}
