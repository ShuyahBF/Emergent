// components/vidal/BandeauValidationVidal.jsx
// ----------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § décision de l'utilisateur (validation VIDAL) : « Vrais appels (pas de
// sandbox), avec des patients fictifs ». Bandeau affiché sur tous les
// écrans qui appellent VIDAL tant que le mode validation est actif :
// « Mode validation VIDAL — patients fictifs uniquement — appels réels
// (production) ». État lu une fois par session (GET /vidal/validation/etat).

import { useEffect, useState } from "react";
import { FlaskConical } from "lucide-react";
import { apiClient as api } from "@/lib/api";

let promesseEtat = null;
export function chargerEtatValidation(forcer = false) {
  if (!promesseEtat || forcer) {
    promesseEtat = api.get("/vidal/validation/etat").then((r) => r.data).catch(() => null);
  }
  return promesseEtat;
}

export default function BandeauValidationVidal() {
  const [etat, setEtat] = useState(null);
  useEffect(() => {
    let actif = true;
    chargerEtatValidation().then((e) => { if (actif) setEtat(e); });
    return () => { actif = false; };
  }, []);
  if (!etat?.mode_validation) return null;
  return (
    <div role="status" style={{ display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", borderRadius: 10, marginBottom: 14, background: "rgba(245,185,113,0.15)", border: "1px solid #f5b971", color: "var(--vidal-orange)", fontSize: 13 }}>
      <FlaskConical size={16} />
      <span>
        <strong>Mode validation VIDAL — patients fictifs uniquement — appels réels (production)</strong>
        {!etat.identifiants_production_configures && " — identifiants de production non configurés (AdminSettings → VIDAL)."}
      </span>
    </div>
  );
}

/** Badge « FICTIF » affiché à côté de tout patient fictif de validation. */
export function BadgeFictif({ patient }) {
  if (!patient?.est_fictif) return null;
  return <span className="badge" style={{ background: "#8a4b00", color: "white", fontSize: 10, marginLeft: 6 }}>FICTIF</span>;
}
