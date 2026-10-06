// VeilleStatsPlateformes.jsx — Lot 64.9 : bulle de notification à chaque statistique de
// plateforme reçue qui a CHANGÉ (en plus ou en moins), pour l'administrateur.
//
// - Monté dans PortalLayout (toutes les pages du portail), actif seulement pour le rôle « admin » ;
// - relit l'activité des plateformes (24 dernières heures, mode temps réel) toutes les 60 s,
//   seulement quand l'onglet est visible (le serveur garde lui-même 1 min de cache) ;
// - compare chaque indicateur (et le nombre d'utilisateurs connectés) à la lecture précédente :
//   une bulle par plateforme liste les changements, ▲ vert en hausse, ▼ rouge en baisse ;
// - la première lecture sert de référence (pas de bulle) ; la référence est gardée dans le
//   navigateur pour ne pas tout réannoncer à chaque rechargement de page.
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient } from "@/lib/api";

const INTERVALLE_MS = 60000;
const CLE_STOCKAGE = "sawali_veille_stats_plateformes";

// Valeur numérique d'un indicateur (« 1 250 », « 12,5 » …) ou null si ce n'est pas un nombre
function nombre(valeur) {
  if (typeof valeur === "number") return valeur;
  const t = String(valeur ?? "").replace(/[\s  ]/g, "").replace(",", ".");
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : null;
}

// Photographie des statistiques : { code: { nom, valeurs: { cle: { libelle, valeur } } } }
function photographier(items) {
  const photo = {};
  for (const p of items || []) {
    const interne = p.interne;
    if (!interne?.ok) continue;                         // statistiques indisponibles : rien à comparer
    const valeurs = {};
    for (const i of interne.indicateurs || []) valeurs[i.cle] = { libelle: i.libelle, valeur: i.valeur };
    if (interne.utilisateurs_connectes !== null && interne.utilisateurs_connectes !== undefined) {
      valeurs.__connectes = { libelle: "Utilisateurs connectés", valeur: interne.utilisateurs_connectes };
    }
    photo[p.code] = { nom: p.nom || p.code, valeurs };
  }
  return photo;
}

// Changements d'une plateforme entre deux photographies
function changements(avant, apres) {
  const liste = [];
  for (const [cle, v] of Object.entries(apres.valeurs)) {
    const ancien = avant.valeurs[cle];
    if (!ancien || String(ancien.valeur) === String(v.valeur)) continue;
    const a = nombre(ancien.valeur);
    const b = nombre(v.valeur);
    liste.push({ libelle: v.libelle, de: ancien.valeur, a: v.valeur, ecart: a !== null && b !== null ? b - a : null });
  }
  return liste;
}

// Contenu de la bulle : une ligne par indicateur modifié
function Bulle({ nom, liste }) {
  return (
    <div className="text-sm" data-testid="bulle-stats-plateforme">
      <p className="font-semibold">📊 {nom} — statistiques mises à jour</p>
      <ul className="mt-1 space-y-0.5 text-xs">
        {liste.slice(0, 8).map((c, k) => {
          const hausse = c.ecart === null ? null : c.ecart > 0;
          return (
            <li key={k} className="flex items-center gap-1">
              <span className={hausse === null ? "text-slate-500" : hausse ? "text-emerald-600" : "text-rose-600"}>
                {hausse === null ? "●" : hausse ? "▲" : "▼"}
              </span>
              <span className="text-slate-700">{c.libelle} :</span>
              <span className="tabular-nums">{String(c.de)} → <strong>{String(c.a)}</strong></span>
              {c.ecart !== null && (
                <span className={`tabular-nums ${hausse ? "text-emerald-600" : "text-rose-600"}`}>
                  ({c.ecart > 0 ? "+" : ""}{Math.round(c.ecart * 100) / 100})
                </span>
              )}
            </li>
          );
        })}
        {liste.length > 8 && <li className="text-slate-500">… et {liste.length - 8} autre(s)</li>}
      </ul>
    </div>
  );
}

export default function VeilleStatsPlateformes() {
  const { user } = useAuth();
  const actif = user?.role === "admin";               // la lecture « temps réel » est réservée à l'admin
  const photoRef = useRef(null);

  useEffect(() => {
    if (!actif) return undefined;
    // Référence mémorisée dans le navigateur (facultative : le stockage peut être indisponible)
    try { photoRef.current = JSON.parse(localStorage.getItem(CLE_STOCKAGE) || "null"); } catch { photoRef.current = null; }

    let annule = false;
    const lire = async () => {
      if (document.hidden) return;
      try {
        const r = await apiClient.get("/admin/plateformes-activite", { params: { jours: 1, temps_reel: true } });
        if (annule) return;
        const nouvelle = photographier(r.data?.items);
        const ancienne = photoRef.current;
        if (ancienne) {
          for (const [code, apres] of Object.entries(nouvelle)) {
            const avant = ancienne[code];
            if (!avant) continue;
            const liste = changements(avant, apres);
            if (liste.length) {
              toast(<Bulle nom={apres.nom} liste={liste} />, {
                duration: 10000,
                action: { label: "Voir", onClick: () => { window.location.href = "/admin/plateformes-temps-reel"; } },
              });
            }
          }
        }
        // La nouvelle lecture devient la référence (on garde l'ancienne pour une plateforme muette)
        photoRef.current = { ...(ancienne || {}), ...nouvelle };
        try { localStorage.setItem(CLE_STOCKAGE, JSON.stringify(photoRef.current)); } catch { /* stockage indisponible */ }
      } catch {
        /* lecture impossible : nouvel essai au prochain tour */
      }
    };

    lire();
    const t = setInterval(lire, INTERVALLE_MS);
    const surRetour = () => { if (!document.hidden) lire(); };
    document.addEventListener("visibilitychange", surRetour);
    return () => { annule = true; clearInterval(t); document.removeEventListener("visibilitychange", surRetour); };
  }, [actif]);

  return null;
}
