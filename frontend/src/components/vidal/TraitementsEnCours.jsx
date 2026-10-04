// components/vidal/TraitementsEnCours.jsx
// -------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § doc VIDAL : la sécurisation porte sur la nouvelle prescription ET sur
// les traitements courants (lignes des prescriptions antérieures non
// terminées à la date du jour). Ces lignes
// sont PROPOSÉES automatiquement (GET /vidal/securisation/
// traitements-en-cours/{patient}) et cochées par défaut quand leur fin est
// connue ; le médecin peut en décocher, en modifier le détail ou en
// ajouter à la main (traitement prescrit ailleurs).

import { useState } from "react";
import { Loader2, ChevronDown, ChevronRight } from "lucide-react";
import LignePrescriptionVidal, { ligneVide } from "./LignePrescriptionVidal";
import { formatDateFr, TYPES_DUREE } from "@/lib/vidalReferentiels";

function resumePeriode(t) {
  const morceaux = [];
  if (t.duration) morceaux.push(`${t.duration} ${(TYPES_DUREE[t.durationType] || "").toLowerCase()}`);
  else if (t.duree_texte) morceaux.push(t.duree_texte);
  if (t.startDate) morceaux.push(`du ${formatDateFr(t.startDate)}`);
  if (t.endDate) morceaux.push(`au ${formatDateFr(t.endDate)}`);
  else if (t.fin_estimee) morceaux.push(`(fin estimée ${formatDateFr(t.fin_estimee)}, non transmise)`);
  return morceaux.join(" ");
}

// Lot 56.10 — `onBasculer(idx)` : déplace un traitement en cours vers la nouvelle prescription.
export default function TraitementsEnCours({ traitements, onChange, chargement, erreurs = [], patientSelectionne, onBasculer = null }) {
  const [ouverts, setOuverts] = useState({});

  function majTraitement(idx, patch) {
    // § ligne à rapprocher : dès qu'un produit VIDAL est choisi, elle est incluse.
    const complement = patch.vidal_id ? { inclus: true } : {};
    onChange((prev) => prev.map((t, i) => (i === idx ? { ...t, ...patch, ...(t.aRapprocher ? complement : {}) } : t)));
  }

  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: 4, display: "flex", alignItems: "center", gap: 6 }}>
        Traitements en cours {chargement && <Loader2 size={13} className="lucide-tourne" />}
      </div>
      <div style={{ fontSize: 12, color: "var(--vidal-gris-fonce)", marginBottom: 10 }}>
        {patientSelectionne
          ? "Lignes des prescriptions antérieures (sécurisations précédentes) non terminées à la date du jour, transmises avec la nouvelle prescription (décochez pour exclure)."
          : "Chargez un patient enregistré pour retrouver automatiquement ses traitements en cours, ou ajoutez-les manuellement."}
      </div>
      {traitements.length === 0 && !chargement && patientSelectionne && (
        <div style={{ fontSize: 12.5, color: "var(--vidal-gris)", marginBottom: 8 }}>Aucun traitement en cours trouvé dans les prescriptions antérieures.</div>
      )}
      {traitements.map((t, idx) => {
        const ouvert = ouverts[idx] || !t.ordonnance_reference;
        const nbErreurs = Object.keys(erreurs[idx] || {}).length;
        return (
          <div key={idx} style={{ marginBottom: 8 }}>
            {t.ordonnance_reference && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", border: "1px solid var(--vidal-bordure)", borderRadius: 10, background: t.inclus ? "var(--vidal-blanc)" : "var(--vidal-gris-clair)", flexWrap: "wrap" }}>
                <input type="checkbox" checked={!!t.inclus} disabled={!t.vidal_id} onChange={(e) => majTraitement(idx, { inclus: e.target.checked })} title="Inclure dans la sécurisation" />
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{t.label || t.designationOrdonnance}
                    {t.aRapprocher && !t.vidal_id && <span style={{ fontWeight: 500, fontSize: 11.5, color: "var(--vidal-orange)" }}> — {t.candidatsVidal?.length ? "à choisir parmi les résultats VIDAL" : "à rechercher dans VIDAL (ouvrez le détail)"}</span>}
                  </div>
                  {/* § plusieurs résultats VIDAL réels : le testeur choisit, rien n'est choisi à sa place. */}
                  {t.aRapprocher && !t.vidal_id && t.candidatsVidal?.length > 0 && (
                    <select className="champ-saisie" style={{ fontSize: 12, marginTop: 4, maxWidth: 360 }} value="" onChange={(e) => {
                      const c = t.candidatsVidal.find((x) => x.ref === e.target.value);
                      if (c) majTraitement(idx, { vidal_id: c.vidal_id, label: c.label, query: "", listesChargees: false });
                    }}>
                      <option value="">Choisir le produit VIDAL…</option>
                      {t.candidatsVidal.map((c) => <option key={c.ref} value={c.ref}>{c.label}</option>)}
                    </select>
                  )}
                  <div style={{ fontSize: 11.5, color: "var(--vidal-gris-fonce)" }}>
                    Ordonnance {t.ordonnance_reference}{t.date_ordonnance ? ` du ${formatDateFr(t.date_ordonnance)}` : ""} — {resumePeriode(t) || "période non précisée"}
                    {!t.duree_connue && <span style={{ color: "var(--vidal-orange)" }}> — durée inconnue, vérifiez si le traitement est toujours en cours</span>}
                  </div>
                </div>
                {nbErreurs > 0 && <span style={{ fontSize: 11, color: "var(--vidal-rouge)" }}>{nbErreurs} champ(s) à corriger</span>}
                {onBasculer && (
                  <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} title="Déplacer vers la nouvelle prescription (pour modifier les prises)"
                    onClick={() => onBasculer(idx)}>⇄ Vers nouvelle prescription</button>
                )}
                <button type="button" className="bouton-secondaire" style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }} onClick={() => setOuverts({ ...ouverts, [idx]: !ouverts[idx] })}>
                  {ouverts[idx] ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Détail
                </button>
              </div>
            )}
            {ouvert && (
              <div style={{ marginTop: t.ordonnance_reference ? 6 : 0 }}>
                <LignePrescriptionVidal
                  ligne={t} estTraitementEnCours erreurs={erreurs[idx] || {}}
                  onChange={(patch) => majTraitement(idx, patch)}
                  onRetirer={t.ordonnance_reference ? null : () => onChange((prev) => prev.filter((_, i) => i !== idx))}
                  onBasculer={onBasculer ? () => onBasculer(idx) : null}
                />
              </div>
            )}
          </div>
        );
      })}
      <button className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={() => onChange((prev) => [...prev, { ...ligneVide("PREVIOUS_ORDER"), inclus: true }])}>
        + Ajouter un traitement en cours
      </button>
    </div>
  );
}
