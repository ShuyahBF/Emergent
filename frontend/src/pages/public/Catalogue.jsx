/*
 * Iter38f — Public Catalogue page.
 * Two sections:
 *   1. Produits & Services (from db.products where is_public=true)
 *      → grouped by category, with "Demander un devis" CTA
 *   2. Brochures & fiches (from db.catalog, the original admin-managed PDFs)
 */
import React, { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { FileText, Download, ImageIcon, Layers, Search, ShoppingBag, Sparkles, ArrowRight, Share2 } from "lucide-react";

const FCFA = (n) => Number(n || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 });
const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

// Iter38n — Fire-and-forget analytics tracking (no auth required)
function trackCatalogEvent(eventType, product = {}) {
  try {
    fetch(`${BACKEND}/api/public/catalog/track`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: eventType,
        product_id: product.id,
        product_sku: product.sku,
        product_name: product.name,
      }),
      // keepalive lets the request finish even if user navigates away
      keepalive: true,
    }).catch(() => {});
  } catch { /* noop */ }
}

function shareProduct(product) {
  const url = `${BACKEND}/api/public/og/product/${product.id}`;
  const text = `Découvrez "${product.name}" — SAWALI SMART SYSTEMS`;
  trackCatalogEvent("product_share", product);
  if (navigator.share) {
    navigator.share({ title: product.name, text, url }).catch(() => {});
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(url).then(() => {
      // eslint-disable-next-line no-alert
      alert("Lien copié dans le presse-papier !");
    });
  }
}

export default function Catalogue() {
  const [products, setProducts] = useState({ count: 0, categories: [] });
  const [brochures, setBrochures] = useState([]);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState("Tous");

  useEffect(() => {
    document.title = "Catalogue — SAWALI SMART SYSTEMS";
    apiClient.get("/public/products").then((r) => setProducts(r.data || { count: 0, categories: [] })).catch(() => {});
    apiClient.get("/catalog").then((r) => setBrochures(r.data || [])).catch(() => {});
  }, []);

  const allCategories = useMemo(
    () => ["Tous", ...(products.categories || []).map((c) => c.label)],
    [products],
  );

  const filteredProducts = useMemo(() => {
    const q = query.trim().toLowerCase();
    const groups = activeCategory === "Tous"
      ? (products.categories || [])
      : (products.categories || []).filter((c) => c.label === activeCategory);
    return groups
      .map((g) => ({
        ...g,
        items: g.items.filter((it) =>
          !q || (it.name || "").toLowerCase().includes(q) || (it.description || "").toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [products, query, activeCategory]);

  const resolveImg = (url) => {
    if (!url) return null;
    return url.startsWith("http") ? url : `${BACKEND}${url.startsWith("/") ? "" : "/"}${url}`;
  };

  return (
    <section className="py-20" data-testid="catalogue-page">
      <div className="mx-auto max-w-screen-2xl px-4 sm:px-6 lg:px-8">
        <p className="text-xs uppercase tracking-[0.25em] text-sawali-blue-light">Nos solutions</p>
        <h1 className="mt-3 text-4xl sm:text-5xl font-display font-bold text-white">Catalogue</h1>
        <p className="mt-4 text-slate-300 max-w-2xl">
          Découvrez nos produits, services et brochures. Pour chaque offre,
          demandez un devis personnalisé en un clic — notre équipe vous recontacte sous 24h.
        </p>

        {/* ============= Section 1: Produits & Services (publics) ============= */}
        {products.count > 0 && (
          <div className="mt-12" data-testid="catalog-products-section">
            <div className="flex items-center gap-3 mb-6">
              <ShoppingBag className="h-5 w-5 text-sawali-blue-light" />
              <h2 className="text-2xl font-display font-bold text-white">Produits & Services</h2>
              <span className="text-xs text-slate-400 bg-white/5 px-2 py-0.5 rounded-full ring-1 ring-white/10">
                {products.count} offre{products.count > 1 ? "s" : ""}
              </span>
            </div>

            {/* Search + category pills */}
            <div className="flex flex-wrap items-center gap-3 mb-5">
              <div className="relative flex-1 min-w-[240px] max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Rechercher un produit, un service…"
                  className="w-full rounded-lg bg-white/5 border border-white/10 text-slate-200 placeholder:text-slate-500 pl-9 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue-light"
                  data-testid="catalog-products-search"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                {allCategories.map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setActiveCategory(cat)}
                    className={`text-xs px-3 py-1.5 rounded-full ring-1 transition ${
                      activeCategory === cat
                        ? "bg-sawali-blue-light text-sawali-navy ring-sawali-blue-light font-semibold"
                        : "bg-white/5 text-slate-300 ring-white/10 hover:bg-white/10"
                    }`}
                    data-testid={`catalog-cat-${cat}`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            {filteredProducts.length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/10 p-12 text-center text-slate-400">
                Aucun produit ne correspond à votre recherche.
              </div>
            ) : (
              filteredProducts.map((group) => (
                <div key={group.label} className="mb-10" data-testid={`catalog-group-${group.label}`}>
                  <h3 className="text-sm uppercase tracking-wider text-sawali-blue-light/80 mb-3">{group.label}</h3>
                  <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
                    {group.items.map((p) => {
                      const img = resolveImg(p.image_url);
                      return (
                        <article key={p.id} className="glow-card rounded-xl overflow-hidden bg-sawali-navy-dark/40 ring-1 ring-white/5 flex flex-col" data-testid={`catalog-product-${p.id}`}>
                          {img ? (
                            <img src={img} alt={p.name} className="h-44 w-full object-cover" onError={(e) => { e.target.style.display = "none"; }} />
                          ) : (
                            <div className="h-44 w-full bg-gradient-to-br from-sawali-navy to-sawali-navy-dark flex items-center justify-center">
                              <ImageIcon className="h-12 w-12 text-sawali-blue-light/40" />
                            </div>
                          )}
                          <div className="p-5 flex-1 flex flex-col">
                            <h4 className="font-display font-semibold text-white">{p.name}</h4>
                            {p.description && <p className="mt-1 text-sm text-slate-400 line-clamp-3">{p.description}</p>}
                            <div className="mt-3 flex items-baseline gap-2">
                              <span className="text-xl font-display font-bold text-sawali-blue-light">{FCFA(p.unit_price_ht)} FCFA</span>
                              <span className="text-xs text-slate-500">HT / {p.unit || "pièce"}</span>
                            </div>
                            {p.tva_pct > 0 && (
                              <p className="text-[10px] text-slate-500 mt-0.5">TVA {p.tva_pct}% en sus</p>
                            )}
                            <Link
                              to={`/rdv?product=${encodeURIComponent(p.name)}&sku=${encodeURIComponent(p.sku || "")}`}
                              onClick={() => trackCatalogEvent("product_quote_click", p)}
                              className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-sawali-blue-light text-sawali-navy hover:bg-white px-4 py-2 text-sm font-semibold transition mt-auto"
                              data-testid={`catalog-quote-${p.id}`}
                            >
                              <Sparkles className="h-4 w-4" /> Demander un devis
                              <ArrowRight className="h-4 w-4" />
                            </Link>
                            {/* Iter38g — Share with rich OG preview (WhatsApp / FB / LinkedIn) */}
                            <button
                              type="button"
                              onClick={() => shareProduct(p)}
                              className="mt-2 inline-flex items-center justify-center gap-2 rounded-lg ring-1 ring-white/15 bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white px-3 py-1.5 text-xs"
                              data-testid={`catalog-share-${p.id}`}
                              title="Partager ce produit avec un aperçu riche"
                            >
                              <Share2 className="h-3.5 w-3.5" /> Partager
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ============= Section 2: Brochures & fiches ============= */}
        <div className="mt-16" data-testid="catalog-brochures-section">
          <div className="flex items-center gap-3 mb-6">
            <Layers className="h-5 w-5 text-sawali-blue-light" />
            <h2 className="text-2xl font-display font-bold text-white">Brochures & Fiches produits</h2>
          </div>
          {brochures.length === 0 && products.count === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 p-16 text-center text-slate-400" data-testid="catalog-empty">
              <Layers className="h-10 w-10 mx-auto text-sawali-blue-light/60" />
              <p className="mt-3">Le catalogue sera bientôt disponible. Revenez prochainement.</p>
            </div>
          ) : brochures.length === 0 ? (
            <p className="text-sm text-slate-400">Aucune brochure pour le moment.</p>
          ) : (
            <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
              {brochures.map((it) => (
                <article key={it.id} className="glow-card rounded-xl overflow-hidden" data-testid={`catalog-item-${it.id}`}>
                  {it.cover_image_url ? (
                    <img src={it.cover_image_url} alt={it.title} className="h-44 w-full object-cover" />
                  ) : (
                    <div className="h-44 w-full bg-gradient-to-br from-sawali-navy to-sawali-navy-dark flex items-center justify-center">
                      {it.file_type === "image" ? <ImageIcon className="h-10 w-10 text-sawali-blue-light/70" /> : <FileText className="h-10 w-10 text-sawali-blue-light/70" />}
                    </div>
                  )}
                  <div className="p-5">
                    <h3 className="font-display font-semibold text-white">{it.title}</h3>
                    {it.description && <p className="mt-1 text-sm text-slate-400 line-clamp-3">{it.description}</p>}
                    <div className="mt-4 flex items-center gap-3">
                      {it.file_url && (
                        <a
                          href={`${BACKEND}${it.file_url}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-2 text-sm text-sawali-blue-light hover:text-white"
                          data-testid={`catalog-download-${it.id}`}
                        >
                          <Download className="h-4 w-4" /> Télécharger
                        </a>
                      )}
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
