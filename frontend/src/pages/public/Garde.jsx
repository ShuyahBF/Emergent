// Iter43-fix22b (2026-06) — Page publique des officines de garde.
// SEO-friendly : URL canonique /garde, balises title + meta description
// dynamiques avec semaine en cours + ville, contenu structuré pour les
// crawlers (LocalBusiness candidates listings).
import React, { useEffect, useState } from "react";
import { MapPin, Phone, MessageCircle, Calendar, RefreshCcw, Search } from "lucide-react";
import { apiClient } from "@/lib/api";

const _MONTHS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

function formatDateRange(monday, sunday) {
  if (!monday || !sunday) return "";
  try {
    const m = new Date(monday);
    const s = new Date(sunday);
    const sameMonth = m.getMonth() === s.getMonth();
    if (sameMonth) {
      return `du ${m.getDate()} au ${s.getDate()} ${_MONTHS_FR[s.getMonth()]} ${s.getFullYear()}`;
    }
    return `du ${m.getDate()} ${_MONTHS_FR[m.getMonth()]} au ${s.getDate()} ${_MONTHS_FR[s.getMonth()]} ${s.getFullYear()}`;
  } catch { return ""; }
}

export default function GardePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const load = () => {
    setLoading(true);
    apiClient.get("/public/officines/garde/current")
      .then((r) => setData(r.data))
      .catch(() => setData({ ok: false }))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  // Update document title for SEO
  useEffect(() => {
    if (data?.ok) {
      document.title = `Pharmacies de garde — Semaine ${data.week_number} — SAWALI SMART SYSTEMS`;
      const meta = document.querySelector('meta[name="description"]');
      if (meta) {
        meta.setAttribute(
          "content",
          `Liste des ${data.count} pharmacies de garde du Groupe ${data.groupe_garde} pour la semaine ${data.week_number} (${data.monday} → ${data.sunday}).`,
        );
      }
    }
    return () => { document.title = "SAWALI SMART SYSTEMS"; };
  }, [data]);

  const items = (data?.officines || []).filter((o) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      (o.name || "").toLowerCase().includes(q)
      || (o.intitule || "").toLowerCase().includes(q)
      || (o.address || "").toLowerCase().includes(q)
      || (o.city || "").toLowerCase().includes(q)
      || (o.location_hint || "").toLowerCase().includes(q)
    );
  });

  // Iter43-fix24az-r (2026-07-22) — Officines du groupe d'appui hebdo (italique)
  const assistItems = (data?.assist_officines || []).filter((o) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      (o.name || "").toLowerCase().includes(q)
      || (o.intitule || "").toLowerCase().includes(q)
      || (o.address || "").toLowerCase().includes(q)
      || (o.city || "").toLowerCase().includes(q)
      || (o.location_hint || "").toLowerCase().includes(q)
    );
  });

  const range = data?.ok ? formatDateRange(data.monday, data.sunday) : "";

  return (
    <section className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 py-12 lg:py-16 text-slate-200"
             data-testid="garde-public-page">
      {/* Iter43-fix24ak — CMS header (configurable from Admin Settings) */}
      {data?.cms_header && (
        <div
          className="mb-6 rounded-xl ring-1 ring-sawali-blue-light/30 bg-sawali-blue-light/5 p-4 text-center text-sawali-blue-light font-display text-lg whitespace-pre-wrap"
          data-testid="garde-cms-header"
        >
          {data.cms_header}
        </div>
      )}

      <header className="mb-8">
        <p className="text-xs uppercase tracking-[0.3em] text-sawali-blue-light mb-2">
          Service public · Liste hebdomadaire
        </p>
        <h1 className="text-3xl sm:text-4xl lg:text-5xl font-display font-bold text-white">
          🏥 Pharmacies de garde
        </h1>
        {data?.ok && (
          <p className="mt-3 text-lg text-slate-300">
            <Calendar className="h-4 w-4 inline mr-1 -mt-1 text-sawali-blue-light" />
            Semaine <strong className="text-white">{data.week_number}</strong>{" "}
            <span className="text-slate-400">{range}</span>{" "}
            · Groupe <strong className="text-white">{data.groupe_garde}</strong>
            · <strong className="text-white">{data.count}</strong> officine{data.count > 1 ? "s" : ""}
          </p>
        )}
        <p className="mt-2 text-sm text-slate-400 italic">
          💚 Cette liste est mise à jour automatiquement chaque lundi à 00:00.
          Vous pouvez aussi envoyer <code className="text-sawali-blue-light">!Garde</code> par WhatsApp pour la recevoir instantanément.
        </p>
      </header>

      {/* Recherche */}
      {data?.ok && data.count > 4 && (
        <div className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filtrer par nom, quartier, ville…"
            className="w-full pl-10 pr-4 py-3 rounded-xl bg-white/5 ring-1 ring-white/10 text-slate-100 placeholder-slate-500 focus:ring-sawali-blue-light/50 focus:outline-none"
            data-testid="garde-search-input"
          />
        </div>
      )}

      {loading && (
        <div className="rounded-xl ring-1 ring-white/10 bg-white/5 p-8 text-center text-slate-400" data-testid="garde-loading">
          Chargement de la liste…
        </div>
      )}

      {!loading && (!data?.ok || data?.count === 0) && (
        <div className="rounded-xl ring-1 ring-amber-300/20 bg-amber-500/5 p-8 text-center" data-testid="garde-empty">
          <p className="text-amber-300 font-semibold mb-2">⚠️ Liste indisponible</p>
          <p className="text-sm text-slate-300">
            {data?.reason === "no_groups_defined"
              ? "Les groupes de garde n'ont pas encore été configurés. Reviens plus tard."
              : "Aucune officine de garde n'est définie pour cette semaine."}
          </p>
        </div>
      )}

      {!loading && data?.ok && data.count > 0 && (
        <ul className="grid sm:grid-cols-2 gap-4" data-testid="garde-list">
          {items.map((o) => (
            <li
              key={o.id}
              className="group rounded-xl ring-1 ring-white/10 bg-white/5 hover:bg-white/10 hover:ring-sawali-blue-light/40 p-5 transition"
              data-testid={`garde-officine-${o.id}`}
            >
              <div className="flex items-start gap-3">
                <img
                  src={`/api/officines-registry/${o.id}/logo`}
                  alt=""
                  className="h-12 w-12 rounded-lg object-contain bg-white/10 ring-1 ring-white/10"
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                  loading="lazy"
                />
                <div className="flex-1 min-w-0">
                  <h2 className="font-display font-semibold text-white text-base group-hover:text-sawali-blue-light truncate">
                    {o.name}
                  </h2>
                  {o.intitule && o.intitule !== o.name && (
                    <p className="text-xs text-slate-400 italic truncate">{o.intitule}</p>
                  )}
                  <div className="mt-2 space-y-1 text-sm">
                    {(o.location_hint || o.address) && (
                      <p className="flex items-start gap-1.5 text-slate-300">
                        <MapPin className="h-3.5 w-3.5 mt-0.5 text-sawali-blue-light shrink-0" />
                        <span className="truncate">
                          {o.location_hint || o.address}
                          {o.city ? <span className="text-slate-500">, {o.city}</span> : null}
                        </span>
                      </p>
                    )}
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                      {o.phone && (
                        <a
                          href={`tel:${o.phone.replace(/\s/g, "")}`}
                          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 ring-1 ring-emerald-500/30"
                          data-testid={`garde-call-${o.id}`}
                        >
                          <Phone className="h-3 w-3" /> {o.phone}
                        </a>
                      )}
                      {o.whatsapp && (
                        <a
                          href={`https://wa.me/${o.whatsapp.replace(/\D/g, "")}`}
                          target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-emerald-600/30 text-emerald-200 hover:bg-emerald-600/40 ring-1 ring-emerald-600/40"
                          data-testid={`garde-wa-${o.id}`}
                        >
                          <MessageCircle className="h-3 w-3" /> WhatsApp
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Iter43-fix24az-r (2026-07-22) — Groupe d'appui hebdomadaire (italique + violet) */}
      {!loading && data?.ok && data.assist_group && assistItems.length > 0 && (
        <section className="mt-10" data-testid="garde-assist-section">
          <div className="rounded-xl ring-1 ring-purple-400/30 bg-purple-500/10 p-4 mb-4 flex items-start gap-3">
            <div className="text-2xl shrink-0">🤝</div>
            <div className="min-w-0">
              <h2 className="text-lg font-display font-semibold text-purple-200 italic">
                Groupe d&apos;appui — Groupe {data.assist_group}
              </h2>
              <p className="text-xs text-purple-300/80 mt-1 italic">
                Cette semaine, {data.assist_count} officine(s) du groupe {data.assist_group} viennent en appui au groupe standard.
              </p>
            </div>
          </div>
          <ul className="grid sm:grid-cols-2 gap-4" data-testid="garde-assist-list">
            {assistItems.map((o) => (
              <li
                key={`assist-${o.id}`}
                className="group rounded-xl ring-1 ring-purple-400/20 bg-purple-500/5 hover:bg-purple-500/10 hover:ring-purple-300/40 p-5 transition italic"
                data-testid={`garde-assist-officine-${o.id}`}
              >
                <div className="flex items-start gap-3">
                  <img
                    src={`/api/officines-registry/${o.id}/logo`}
                    alt=""
                    className="h-12 w-12 rounded-lg object-contain bg-white/10 ring-1 ring-white/10"
                    onError={(e) => { e.currentTarget.style.display = "none"; }}
                    loading="lazy"
                  />
                  <div className="flex-1 min-w-0">
                    <h3 className="font-display font-semibold text-purple-100 text-base group-hover:text-purple-50 truncate italic">
                      {o.name}
                    </h3>
                    {o.intitule && o.intitule !== o.name && (
                      <p className="text-xs text-purple-300/80 italic truncate">{o.intitule}</p>
                    )}
                    <div className="mt-2 space-y-1 text-sm">
                      {(o.location_hint || o.address) && (
                        <p className="flex items-start gap-1.5 text-purple-200/90 italic">
                          <MapPin className="h-3.5 w-3.5 mt-0.5 text-purple-300 shrink-0" />
                          <span className="truncate">
                            {o.location_hint || o.address}
                            {o.city ? <span className="text-purple-400/80">, {o.city}</span> : null}
                          </span>
                        </p>
                      )}
                      <div className="flex flex-wrap items-center gap-2 mt-2 not-italic">
                        {o.phone && (
                          <a
                            href={`tel:${o.phone.replace(/\s/g, "")}`}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-purple-500/25 text-purple-200 hover:bg-purple-500/40 ring-1 ring-purple-400/40"
                            data-testid={`garde-assist-call-${o.id}`}
                          >
                            <Phone className="h-3 w-3" /> {o.phone}
                          </a>
                        )}
                        {o.whatsapp && (
                          <a
                            href={`https://wa.me/${o.whatsapp.replace(/\D/g, "")}`}
                            target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-purple-600/30 text-purple-100 hover:bg-purple-600/50 ring-1 ring-purple-500/40"
                            data-testid={`garde-assist-wa-${o.id}`}
                          >
                            <MessageCircle className="h-3 w-3" /> WhatsApp
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-8 flex items-center justify-between text-xs text-slate-500">
        <p>
          💚 <em>Prompt rétablissement et bonne santé !</em>
        </p>
        <button onClick={load} className="inline-flex items-center gap-1 hover:text-slate-300" data-testid="garde-refresh">
          <RefreshCcw className="h-3 w-3" /> Rafraîchir
        </button>
      </div>

      {/* Iter43-fix24ak — CMS footer (configurable from Admin Settings) */}
      {data?.cms_footer && (
        <div
          className="mt-6 rounded-xl ring-1 ring-emerald-300/20 bg-emerald-500/5 p-4 text-center text-emerald-200 font-display text-lg whitespace-pre-wrap"
          data-testid="garde-cms-footer"
        >
          {data.cms_footer}
        </div>
      )}

      {/* Iter43-fix24ak — Persistent link to the main site + optional admin-uploaded "click-here" hint image */}
      <div className="mt-8 rounded-xl ring-1 ring-white/10 bg-white/5 p-5 text-center" data-testid="garde-cta-site">
        <p className="text-sm text-slate-300 mb-3">
          Retrouvez plus d&apos;informations et nos services sur notre site officiel :
        </p>
        <a
          href="https://sawalismartsystems.com"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block text-sawali-blue-light hover:text-white underline underline-offset-4 font-semibold text-base"
          data-testid="garde-site-link"
        >
          https://sawalismartsystems.com
        </a>
        {data?.cms_image_url && (
          <a
            href="https://sawalismartsystems.com"
            target="_blank"
            rel="noopener noreferrer"
            className="block mt-4 group"
            data-testid="garde-cms-image-link"
          >
            <img
              src={data.cms_image_url}
              alt={data.cms_image_caption || "Aperçu — cliquez pour visiter le site"}
              className="mx-auto max-h-80 rounded-lg ring-1 ring-white/10 group-hover:ring-sawali-blue-light/50 transition shadow-lg"
              loading="lazy"
              data-testid="garde-cms-image"
            />
            {data.cms_image_caption && (
              <p
                className="mt-2 text-xs text-slate-400 italic"
                data-testid="garde-cms-image-caption"
              >
                {data.cms_image_caption}
              </p>
            )}
          </a>
        )}
      </div>

      {/* JSON-LD pour SEO (rich results) */}
      {data?.ok && data.count > 0 && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "ItemList",
              name: `Pharmacies de garde — Semaine ${data.week_number}`,
              numberOfItems: data.count,
              itemListElement: items.slice(0, 25).map((o, i) => ({
                "@type": "ListItem",
                position: i + 1,
                item: {
                  "@type": "Pharmacy",
                  name: o.name,
                  telephone: o.phone || undefined,
                  address: {
                    "@type": "PostalAddress",
                    streetAddress: o.address || o.location_hint || undefined,
                    addressLocality: o.city || undefined,
                  },
                },
              })),
            }),
          }}
        />
      )}
    </section>
  );
}
