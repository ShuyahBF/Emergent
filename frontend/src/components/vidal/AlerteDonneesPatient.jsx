// components/vidal/AlerteDonneesPatient.jsx
// ---------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § MI VIDAL §4.7.1 : quand un médicament prescrit utilise une donnée
// patient (indicateurs 26 âge, 27 poids, 30 fonction rénale, 31 sexe,
// 36 taille) et que cette donnée manque, l'alerte doit être INTERRUPTIVE :
// le médecin complète le dossier ou clique explicitement pour passer
// outre. Grossesse (28) et allaitement (29) : information du risque.

import { AlertTriangle, Info } from "lucide-react";

export default function AlerteDonneesPatient({ manquantes, onPasserOutre, onCompleter }) {
  if (!manquantes) return null;
  return (
    <div className="carte" role="alertdialog" style={{ border: "1px solid var(--vidal-orange)", background: "rgba(245,158,11,0.08)", marginBottom: 16 }}>
      {manquantes.interruptives.length > 0 && (
        <>
          <div style={{ fontWeight: 700, display: "flex", alignItems: "center", gap: 6, color: "#b45309", marginBottom: 6 }}>
            <AlertTriangle size={15} /> Données patient manquantes pour sécuriser correctement
          </div>
          <ul style={{ margin: "0 0 8px", paddingLeft: 18, fontSize: 12.5 }}>
            {manquantes.interruptives.map((m) => (
              <li key={m.id}><strong>{m.libelle}</strong> — utilisé(e) par VIDAL pour : {m.medicaments.join(", ")}</li>
            ))}
          </ul>
          <div style={{ fontSize: 12, color: "var(--vidal-gris-fonce)", marginBottom: 8 }}>
            Sans ces données, l'analyse n'est pas adaptée au profil du patient (aucune alerte ne signale leur absence).
          </div>
        </>
      )}
      {manquantes.informations.length > 0 && (
        <div style={{ fontSize: 12.5, display: "flex", alignItems: "flex-start", gap: 6, marginBottom: 8 }}>
          <Info size={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <span>Risque à prendre en compte : {manquantes.informations.map((m) => `${m.libelle} (${m.medicaments.join(", ")})`).join(" ; ")}.</span>
        </div>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="bouton-primaire" onClick={onCompleter}>Compléter les données</button>
        <button className="bouton-secondaire" onClick={onPasserOutre}>Passer outre et continuer</button>
      </div>
    </div>
  );
}
