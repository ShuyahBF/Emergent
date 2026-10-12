// PuceContrat.jsx — Lot 120 : petite puce CARRÉE indiquant l'état du contrat d'un contact
// dans le Centre de messagerie (liste des contacts).
//   - vert   : contrat valide (en cours et à jour) ;
//   - orange : contrat en retard de paiement (même règle que les alertes de retard, lot 79.7) ;
//   - rouge  : pas de contrat, contrat annulé / résilié / expiré.
// Au survol (souris), au focus (clavier) ou à l'appui (mobile), une infobulle affiche le détail :
// n° de contrat, statut, début / fin, durée en mois, mois écoulés / restants, jours de retard,
// prochaine échéance — JAMAIS de montant (le serveur n'en renvoie d'ailleurs aucun).
// Données : POST /api/me/contacts-contrats (une seule requête pour toute la liste).
import React, { useRef, useState } from "react";

// Lot 120 — couleur de la puce selon l'état renvoyé par le serveur
const COULEURS = {
  valide: { fond: "#16a34a", libelle: "Contrat valide" },
  retard: { fond: "#f97316", libelle: "Contrat en retard de paiement" },
  aucun: { fond: "#dc2626", libelle: "Pas de contrat valide" },
};

// Lot 120 — « 2026-10-15 » → « 15/10/2026 » (format français, sans décalage de fuseau)
function dateFr(iso) {
  if (!iso) return null;
  const [a, m, j] = String(iso).slice(0, 10).split("-");
  return a && m && j ? `${j}/${m}/${a}` : String(iso);
}

// Lot 120 — lignes de l'infobulle : seulement les informations connues (rien d'inventé, aucun montant)
function lignesDetail(c) {
  const lignes = [];
  if (c.client) lignes.push(["Client", c.client]);
  lignes.push(["N° de contrat", c.numero || "—"]);
  lignes.push(["Statut", c.statut_libelle || "—"]);
  if (c.debut) lignes.push(["Début", dateFr(c.debut)]);
  if (c.fin) lignes.push(["Fin", dateFr(c.fin)]);
  if (c.duree_mois != null) lignes.push(["Durée", `${c.duree_mois} mois`]);
  if (c.mois_ecoules != null) {
    lignes.push(["Mois écoulés", c.mois_restants != null
      ? `${c.mois_ecoules} (reste ${c.mois_restants} mois)`
      : String(c.mois_ecoules)]);
  }
  if (c.periodicite) lignes.push(["Périodicité", c.periodicite]);
  if (c.jours_retard != null) {
    lignes.push(["Retard", `${c.jours_retard} jour(s)${c.seuil_retard ? ` (seuil ${c.seuil_retard} j)` : ""}`]);
  }
  if (c.echeance_prochaine) lignes.push(["Prochaine échéance", dateFr(c.echeance_prochaine)]);
  if (c.services_suspendus?.length) lignes.push(["Services suspendus si échu", c.services_suspendus.join(", ")]);
  return lignes;
}

export default function PuceContrat({ contrat, testid, className = "" }) {
  const [pos, setPos] = useState(null);     // position de l'infobulle (null = fermée)
  const ref = useRef(null);
  // Pas de puce : contact interne (null) ou informations pas encore chargées (undefined)
  if (!contrat) return null;
  const teinte = COULEURS[contrat.etat] || COULEURS.aucun;
  const lignes = lignesDetail(contrat);
  // Texte lu par les lecteurs d'écran : état + toutes les lignes du détail
  const aria = `${teinte.libelle}. ${lignes.map(([k, v]) => `${k} : ${v}`).join(". ")}`;

  // Lot 120 — l'infobulle est en position « fixed » (calculée depuis la puce) pour ne pas être
  // coupée par le tableau qui défile horizontalement.
  const ouvrir = () => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const largeur = 260;
    const gauche = Math.max(8, Math.min(r.left, window.innerWidth - largeur - 8));
    const enBas = r.bottom + 6 + 220 < window.innerHeight;     // sinon au-dessus de la puce
    setPos({ left: gauche, top: enBas ? r.bottom + 6 : undefined, bottom: enBas ? undefined : window.innerHeight - r.top + 6 });
  };
  const fermer = () => setPos(null);

  return (
    <>
      <span
        ref={ref}
        role="img"
        tabIndex={0}
        aria-label={aria}
        // Survol (souris), focus (clavier) et appui (mobile : un appui ouvre, un second ferme)
        onMouseEnter={ouvrir}
        onMouseLeave={fermer}
        onFocus={ouvrir}
        onBlur={fermer}
        onClick={(e) => { e.stopPropagation(); if (pos) fermer(); else ouvrir(); }}
        onKeyDown={(e) => { if (e.key === "Escape") fermer(); }}
        className={`inline-block shrink-0 align-middle cursor-help outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${className}`}
        // Puce CARRÉE de 10 px, coins à peine arrondis (2 px)
        style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: teinte.fond }}
        data-testid={testid}
        data-etat={contrat.etat}
      />
      {pos && (
        <div
          role="tooltip"
          className="fixed z-[200] w-[260px] rounded-lg bg-slate-900/95 text-white text-[11px] leading-snug shadow-xl ring-1 ring-black/20 px-3 py-2 pointer-events-none"
          style={{ left: pos.left, top: pos.top, bottom: pos.bottom }}
          data-testid={testid ? `${testid}-detail` : undefined}
        >
          <div className="flex items-center gap-1.5 font-semibold mb-1">
            <span style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: teinte.fond, display: "inline-block" }} />
            {teinte.libelle}
          </div>
          {lignes.map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <span className="text-slate-300 shrink-0">{k} :</span>
              <span className="font-medium break-words">{v}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
