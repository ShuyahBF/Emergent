/*
 * Lot 94 — Page de présentation d'une carte de carrousel WhatsApp : /presentation/:code
 *
 * Demande du propriétaire (09/10/2026) : « Sur les carrousels les cartes qui n'ont pas de lien affichent une
 * erreur quand on clique dessus. Je voudrais pouvoir alors rediriger les gens sur une page du site présentant
 * un produit. »
 *
 * Quand une carte n'a pas de lien (ni « lien par défaut »), son bouton WhatsApp mène ici : la page montre la
 * photo, le titre, le texte de la carte et, pour un produit de la caisse, son prix et sa description.
 * Données publiques lues par GET /api/public/carrousel/carte/{code} (aucune donnée personnelle).
 */
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Loader2, MessageCircle, ShoppingBag } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function PresentationCarte() {
  const { code } = useParams();
  const [carte, setCarte] = useState(null);      // contenu de la carte
  const [etat, setEtat] = useState("chargement"); // chargement | pret | introuvable

  // Lecture de la carte (page publique : pas de connexion)
  useEffect(() => {
    let actif = true;
    apiClient.get(`/public/carrousel/carte/${encodeURIComponent(code || "")}`)
      .then((r) => {
        if (!actif) return;
        setCarte(r.data);
        setEtat("pret");
        document.title = `${r.data?.titre || "Présentation"} — SAWALI SMART SYSTEMS`;
      })
      .catch(() => { if (actif) setEtat("introuvable"); });
    return () => { actif = false; };
  }, [code]);

  // Attente : jauge qui tourne + « Patientez… »
  if (etat === "chargement") {
    return (
      <div className="flex min-h-[50vh] items-center justify-center gap-3 text-slate-300" role="status">
        <Loader2 className="h-6 w-6 animate-spin text-sawali-blue-light" /> Patientez…
      </div>
    );
  }

  // Carte inconnue (lien trop ancien ou mal recopié) : orientation vers le catalogue
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

  const p = carte.produit;   // produit de la caisse (ou null pour une carte libre)
  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:py-16">
      <div className="grid items-start gap-8 md:grid-cols-2">
        {/* Photo de la carte */}
        <div className="overflow-hidden rounded-2xl bg-white/5 ring-1 ring-white/10">
          {carte.image_url
            ? <img src={carte.image_url} alt={carte.titre} className="aspect-square w-full object-cover" />
            : <div className="grid aspect-square place-items-center text-slate-500"><ShoppingBag className="h-12 w-12" /></div>}
        </div>

        {/* Titre, prix, texte, description, actions */}
        <div>
          {carte.expediteur && <p className="text-sm text-slate-400">Proposé par {carte.expediteur}</p>}
          <h1 className="mt-2 text-3xl sm:text-4xl font-display font-bold text-white">{carte.titre}</h1>
          {p?.prix && (
            <p className="mt-3 text-2xl font-bold text-sawali-blue-light">
              {p.prix}{p.unite ? <span className="text-base font-normal text-slate-400"> / {p.unite}</span> : null}
            </p>
          )}
          {carte.texte && carte.texte !== p?.prix && <p className="mt-4 text-lg text-slate-200">{carte.texte}</p>}
          {p?.description && <p className="mt-4 whitespace-pre-line leading-relaxed text-slate-300">{p.description}</p>}

          <div className="mt-8 flex flex-wrap gap-3">
            {/* Carrousel de SAWALI : demande de devis et catalogue ; carrousel d'un client : réponse sur WhatsApp */}
            {carte.plateforme ? (
              <>
                <Link to={`/rdv?product=${encodeURIComponent(p?.nom || carte.titre)}`}
                      className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-5 py-2.5 font-semibold text-white hover:opacity-90">
                  Demander un devis <ArrowRight className="h-4 w-4" />
                </Link>
                <Link to="/catalogue" className="inline-flex items-center gap-2 rounded-lg px-5 py-2.5 font-semibold text-slate-200 ring-1 ring-white/20 hover:bg-white/5">
                  Voir le catalogue
                </Link>
              </>
            ) : (
              <p className="inline-flex items-center gap-2 rounded-lg bg-white/5 px-4 py-3 text-sm text-slate-200 ring-1 ring-white/10">
                <MessageCircle className="h-4 w-4 text-emerald-400" />
                Pour commander ou poser une question, répondez au message WhatsApp{carte.expediteur ? ` de ${carte.expediteur}` : ""}.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
