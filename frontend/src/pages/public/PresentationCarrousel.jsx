/*
 * Lot 111 — Page de présentation de TOUT un carrousel WhatsApp : /presentation/c/:id#carte-n
 *
 * Demande du propriétaire (11/10/2026) : « Permettre à une carte d'un carrousel WA d'afficher une page descriptive,
 * par exemple https://sawalismartsystems.com/presentation#cartex où cartex représente une position dans la page… »
 *
 * Le bouton d'une carte (lien court /api/public/carrousel/l/{code}) renvoie ici avec la position de la carte :
 * /presentation/c/<identifiant public>?depuis=<code>#carte-<n>. La page :
 *   - montre une section par carte (id="carte-1", "carte-2"…) : photo, titre, prix, texte, description détaillée
 *     (markdown simple : **gras**, *italique*, listes, liens) ;
 *   - après le chargement, défile en douceur jusqu'à la carte de l'adresse et la met en valeur quelques secondes ;
 *   - propose « Je suis intéressé » (WhatsApp de l'expéditeur, message prérempli citant la carte) et une
 *     navigation entre les cartes (barre de pastilles en haut, « Carte suivante » en bas de chaque section) ;
 *   - compte, par carte, la « vue » de la page arrivée sur cette carte et le clic « Je suis intéressé »
 *     (POST /api/public/carrousel/evenement, dédupliqué côté serveur sur 24 h).
 * Conçue d'abord pour le téléphone : elle est ouverte depuis WhatsApp. La version et la date de déploiement sont
 * affichées par le pied commun des pages publiques (MarketingLayout → VersionStamp).
 * Données : GET /api/public/carrousel/presentation/{id} (aucune donnée de destinataire).
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { ArrowDown, ArrowRight, ExternalLink, Loader2, MessageCircle, ShoppingBag, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Hauteur cachée par la barre du site (64 px) + la barre des cartes (environ 52 px) : marge de défilement
const MARGE_DEFILEMENT = 128;
const DUREE_MISE_EN_VALEUR = 4000;   // contour animé de la carte visée (ms)

// --- Markdown simple, sans HTML injecté : le texte est découpé en éléments React (aucun risque de script) ---
// Lignes « - » ou « * » → liste à puces ; « 1. » → liste numérotée ; ligne vide → nouveau paragraphe.
// Dans une ligne : **gras**, *italique*, [texte](https://lien) et adresses https://… rendues cliquables.
function enLigne(texte, cle) {
  const morceaux = [];
  const motif = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]+\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s<]+)/g;
  let dernier = 0;
  let m;
  let i = 0;
  while ((m = motif.exec(texte)) !== null) {
    if (m.index > dernier) morceaux.push(texte.slice(dernier, m.index));
    const t = m[0];
    const k = `${cle}-${i++}`;
    if (t.startsWith("**")) morceaux.push(<strong key={k} className="font-semibold text-white">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("[")) {
      const [, libelle, url] = t.match(/^\[([^\]]+)\]\((.+)\)$/);
      morceaux.push(<a key={k} href={url} target="_blank" rel="noopener noreferrer nofollow" className="text-sky-300 underline underline-offset-2">{libelle}</a>);
    } else if (t.startsWith("http")) {
      morceaux.push(<a key={k} href={t} target="_blank" rel="noopener noreferrer nofollow" className="break-all text-sky-300 underline underline-offset-2">{t}</a>);
    } else morceaux.push(<em key={k}>{t.slice(1, -1)}</em>);
    dernier = m.index + t.length;
  }
  if (dernier < texte.length) morceaux.push(texte.slice(dernier));
  return morceaux;
}

function MarkdownSimple({ texte }) {
  // Regroupement des lignes en blocs : paragraphe, liste à puces ou liste numérotée
  const blocs = [];
  (texte || "").split(/\r?\n/).forEach((ligne) => {
    const puce = ligne.match(/^\s*[-*•]\s+(.*)$/);
    const numero = ligne.match(/^\s*\d+[.)]\s+(.*)$/);
    const type = puce ? "ul" : numero ? "ol" : ligne.trim() ? "p" : "vide";
    const contenu = puce ? puce[1] : numero ? numero[1] : ligne.trim();
    const precedent = blocs[blocs.length - 1];
    if (type === "vide") { blocs.push({ type: "vide" }); return; }
    if (precedent && precedent.type === type) precedent.lignes.push(contenu);
    else blocs.push({ type, lignes: [contenu] });
  });
  return (
    <div className="space-y-3 text-[15px] leading-relaxed text-slate-300">
      {blocs.map((b, i) => {
        if (b.type === "ul") return <ul key={i} className="list-disc space-y-1 pl-5">{b.lignes.map((l, j) => <li key={j}>{enLigne(l, `${i}-${j}`)}</li>)}</ul>;
        if (b.type === "ol") return <ol key={i} className="list-decimal space-y-1 pl-5">{b.lignes.map((l, j) => <li key={j}>{enLigne(l, `${i}-${j}`)}</li>)}</ol>;
        if (b.type === "p") return <p key={i}>{b.lignes.map((l, j) => <React.Fragment key={j}>{j > 0 && <br />}{enLigne(l, `${i}-${j}`)}</React.Fragment>)}</p>;
        return null;
      })}
    </div>
  );
}

// Numéro de carte lu dans l'adresse (#carte-3 → 3), borné au nombre de cartes ; 1 par défaut
const carteDepuisAdresse = (hash, total) => {
  const m = (hash || "").match(/carte-(\d+)/);
  const n = m ? Number(m[1]) : 1;
  return Math.min(Math.max(1, n), Math.max(1, total));
};

export default function PresentationCarrousel() {
  const { id } = useParams();
  const { hash } = useLocation();
  const [donnees, setDonnees] = useState(null);       // { expediteur, message, contact_whatsapp, cartes[] }
  const [etat, setEtat] = useState("chargement");     // chargement | pret | introuvable
  const [active, setActive] = useState(1);            // carte visible (pastille surlignée)
  const [enValeur, setEnValeur] = useState(0);        // carte mise en valeur (contour animé), 0 = aucune
  const [interesses, setInteresses] = useState({});   // cartes déjà signalées « intéressé » (évite le double envoi)
  const barreRef = useRef(null);

  // 1. Lecture du carrousel (page publique : pas de connexion)
  useEffect(() => {
    let actif = true;
    apiClient.get(`/public/carrousel/presentation/${encodeURIComponent(id || "")}`)
      .then((r) => {
        if (!actif) return;
        setDonnees(r.data);
        setEtat("pret");
        document.title = `${r.data?.expediteur || "Présentation"} — SAWALI SMART SYSTEMS`;
      })
      .catch(() => { if (actif) setEtat("introuvable"); });
    return () => { actif = false; };
  }, [id]);

  const total = donnees?.cartes?.length || 0;

  // 2. Après le chargement : défilement doux jusqu'à la carte de l'adresse, mise en valeur, « vue » comptée
  useEffect(() => {
    if (etat !== "pret" || !total) return undefined;
    const n = carteDepuisAdresse(hash, total);
    const minuteur = setTimeout(() => {
      const el = document.getElementById(`carte-${n}`);
      if (el && (hash || n > 1)) el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActive(n);
      if (hash) setEnValeur(n);
    }, 150);   // laisse le temps aux images de prendre leur place
    const fin = setTimeout(() => setEnValeur(0), 150 + DUREE_MISE_EN_VALEUR);
    // Statistique : la page a été vue en arrivant sur cette carte (une fois par appareil et par 24 h côté serveur)
    apiClient.post("/public/carrousel/evenement", { campagne: id, carte: n, type: "vue" }).catch(() => {});
    return () => { clearTimeout(minuteur); clearTimeout(fin); };
  }, [etat, total, hash, id]);

  // 3. Pastille active = carte la plus visible à l'écran (suivi au défilement)
  useEffect(() => {
    if (etat !== "pret" || !total || typeof IntersectionObserver === "undefined") return undefined;
    const obs = new IntersectionObserver((entrees) => {
      const visible = entrees.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActive(Number(visible.target.dataset.n));
    }, { rootMargin: `-${MARGE_DEFILEMENT}px 0px -45% 0px`, threshold: [0.1, 0.4, 0.7] });
    document.querySelectorAll("[data-carte-presentation]").forEach((el) => obs.observe(el));
    return () => obs.disconnect();
  }, [etat, total]);

  // La pastille active reste visible dans la barre horizontale (téléphone)
  useEffect(() => {
    const p = barreRef.current?.querySelector(`[data-pastille="${active}"]`);
    if (p) p.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [active]);

  // Aller à une carte (pastilles, « Carte suivante ») : défilement doux et adresse mise à jour sans recharger
  const allerA = (n) => {
    const el = document.getElementById(`carte-${n}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#carte-${n}`);
    setActive(n);
  };

  // Lien WhatsApp prérempli qui cite la carte (numéro de l'expéditeur s'il est connu)
  const lienWhatsapp = useMemo(() => (carte) => {
    const texte = `Bonjour${donnees?.expediteur ? ` ${donnees.expediteur}` : ""}, je suis intéressé(e) par « ${carte.titre} »`
      + `${carte.produit?.prix ? ` (${carte.produit.prix})` : ""}, vu dans votre carrousel WhatsApp (carte ${carte.n}). `
      + "Pouvez-vous me donner plus d'informations ?";
    return donnees?.contact_whatsapp ? `https://wa.me/${donnees.contact_whatsapp}?text=${encodeURIComponent(texte)}` : "";
  }, [donnees]);

  // « Je suis intéressé » : statistique envoyée (sans attendre), puis WhatsApp s'ouvre par le lien lui-même
  const signalerInteret = (carte) => {
    if (!interesses[carte.n]) {
      apiClient.post("/public/carrousel/evenement", { campagne: id, carte: carte.n, type: "interesse" }).catch(() => {});
      setInteresses((x) => ({ ...x, [carte.n]: true }));
    }
    if (!donnees?.contact_whatsapp) {
      toast.success(`Merci ! Répondez au message WhatsApp${donnees?.expediteur ? ` de ${donnees.expediteur}` : ""} pour en parler.`);
    }
  };

  // Attente : jauge qui tourne + « Patientez… » (comme les autres pages publiques)
  if (etat === "chargement") {
    return (
      <div className="flex min-h-[50vh] items-center justify-center gap-3 text-slate-300" role="status">
        <Loader2 className="h-6 w-6 animate-spin text-sawali-blue-light" /> Patientez…
      </div>
    );
  }

  // Lien inconnu ou trop ancien : orientation vers le catalogue
  if (etat === "introuvable") {
    return (
      <div className="mx-auto max-w-xl px-4 py-20 text-center">
        <h1 className="text-3xl font-display font-bold text-white">Cette présentation n'est plus disponible</h1>
        <p className="mt-3 text-slate-400">Le lien a peut-être expiré. Retrouvez nos produits et services dans le catalogue.</p>
        <Link to="/catalogue" className="mt-6 inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-5 py-2.5 font-semibold text-white hover:opacity-90">
          Voir le catalogue <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    );
  }

  const cartes = donnees.cartes || [];
  return (
    <div className="pb-16">
      {/* Animation du contour de la carte visée (quelques secondes après l'arrivée) */}
      <style>{`
        @keyframes contour-carte { 0%,100% { box-shadow: 0 0 0 2px rgba(56,189,248,.9), 0 0 0 0 rgba(56,189,248,.45); }
                                   50% { box-shadow: 0 0 0 2px rgba(56,189,248,.9), 0 0 0 14px rgba(56,189,248,0); } }
        .carte-en-valeur { animation: contour-carte 1.2s ease-out 3; }
      `}</style>

      {/* En-tête : expéditeur et message du carrousel */}
      <header className="mx-auto max-w-3xl px-4 pt-6 sm:pt-10">
        {donnees.expediteur && (
          <p className="inline-flex items-center gap-1.5 rounded-full bg-white/5 px-3 py-1 text-xs text-slate-300 ring-1 ring-white/10">
            <Sparkles className="h-3.5 w-3.5 text-sky-300" /> Proposé par {donnees.expediteur}
          </p>
        )}
        {donnees.message && <h1 className="mt-3 text-2xl font-display font-bold leading-tight text-white sm:text-3xl">{donnees.message}</h1>}
        <p className="mt-1 text-sm text-slate-400">{cartes.length} présentation{cartes.length > 1 ? "s" : ""} · touchez une pastille pour passer de l'une à l'autre</p>
      </header>

      {/* Navigation entre les cartes : pastilles, collées sous la barre du site */}
      <nav aria-label="Cartes du carrousel" className="sticky top-16 z-40 mt-4 border-y border-white/5 bg-[#081226]/90 backdrop-blur-md">
        <div ref={barreRef} className="mx-auto flex max-w-3xl gap-2 overflow-x-auto px-4 py-2.5 [scrollbar-width:none]">
          {cartes.map((c) => (
            <button key={c.n} type="button" data-pastille={c.n} onClick={() => allerA(c.n)}
                    aria-current={active === c.n ? "true" : undefined}
                    className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition ${active === c.n
                      ? "bg-sky-400 text-[#081226]" : "bg-white/5 text-slate-300 ring-1 ring-white/10 hover:bg-white/10"}`}>
              {c.n}. {c.titre.length > 22 ? `${c.titre.slice(0, 21)}…` : c.titre}
            </button>
          ))}
        </div>
      </nav>

      {/* Une section par carte : id="carte-n" (position de l'adresse #carte-n) */}
      <div className="mx-auto mt-5 max-w-3xl space-y-6 px-4">
        {cartes.map((c) => {
          const p = c.produit;   // produit de la caisse (ou null pour une carte libre)
          const wa = lienWhatsapp(c);
          return (
            <section key={c.n} id={`carte-${c.n}`} data-carte-presentation data-n={c.n}
                     style={{ scrollMarginTop: MARGE_DEFILEMENT }}
                     className={`overflow-hidden rounded-2xl bg-white/[0.04] ring-1 ring-white/10 ${enValeur === c.n ? "carte-en-valeur" : ""}`}>
              <div className="md:grid md:grid-cols-5">
                {/* Photo de la carte */}
                <div className="relative md:col-span-2">
                  {c.image_url
                    ? <img src={c.image_url} alt={c.titre} loading={c.n <= 2 ? "eager" : "lazy"} className="aspect-square w-full object-cover" />
                    : <div className="grid aspect-square place-items-center text-slate-500"><ShoppingBag className="h-12 w-12" /></div>}
                  <span className="absolute left-3 top-3 rounded-full bg-black/55 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur">
                    {c.n} / {cartes.length}
                  </span>
                </div>

                {/* Titre, prix, texte, description détaillée, actions */}
                <div className="p-5 md:col-span-3 md:p-6">
                  <h2 className="text-2xl font-display font-bold leading-snug text-white">{c.titre}</h2>
                  {p?.prix && (
                    <p className="mt-2 text-xl font-bold text-sky-300">
                      {p.prix}{p.unite ? <span className="text-sm font-normal text-slate-400"> / {p.unite}</span> : null}
                    </p>
                  )}
                  {c.texte && c.texte !== p?.prix && c.texte !== "-" && <p className="mt-3 text-base text-slate-200">{c.texte}</p>}
                  {c.description_detaillee && <div className="mt-4"><MarkdownSimple texte={c.description_detaillee} /></div>}
                  {!c.description_detaillee && p?.description && (
                    <p className="mt-4 whitespace-pre-line text-[15px] leading-relaxed text-slate-300">{p.description}</p>
                  )}

                  <div className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:flex-wrap">
                    {/* Je suis intéressé : WhatsApp de l'expéditeur, message prérempli citant la carte */}
                    {wa ? (
                      <a href={wa} target="_blank" rel="noopener noreferrer" onClick={() => signalerInteret(c)}
                         className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-500 px-5 py-3 font-semibold text-white shadow-lg shadow-emerald-500/20 hover:bg-emerald-600">
                        <MessageCircle className="h-5 w-5" /> Je suis intéressé
                      </a>
                    ) : (
                      <button type="button" onClick={() => signalerInteret(c)}
                              className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-500 px-5 py-3 font-semibold text-white hover:bg-emerald-600">
                        <MessageCircle className="h-5 w-5" /> Je suis intéressé
                      </button>
                    )}
                    {c.lien && (
                      <a href={c.lien} target="_blank" rel="noopener noreferrer nofollow"
                         className="inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 font-semibold text-slate-100 ring-1 ring-white/20 hover:bg-white/5">
                        En savoir plus <ExternalLink className="h-4 w-4" />
                      </a>
                    )}
                    {c.n < cartes.length && (
                      <button type="button" onClick={() => allerA(c.n + 1)}
                              className="inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm text-slate-300 hover:bg-white/5 sm:ml-auto">
                        Carte suivante <ArrowDown className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                  {interesses[c.n] && <p className="mt-2 text-xs text-emerald-300">Merci, votre intérêt a été transmis.</p>}
                </div>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
