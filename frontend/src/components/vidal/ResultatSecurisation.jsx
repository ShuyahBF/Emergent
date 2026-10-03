// components/vidal/ResultatSecurisation.jsx
// ---------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § Sécurisation VIDAL v2 — affichage du résultat de /alerts/full (bandeau
// de pastilles par catégorie + alertes détaillées triées par gravité),
// auparavant dupliqué dans la page Sécurisation et la modale de
// l'ordonnance : un seul composant, un seul rendu.
// § MI VIDAL §6.5.4.14 : les alertes UNSECURIZED (médicament non sécurisé)
// et PATIENT (données incohérentes) doivent être montrées au prescripteur
// — elles sont mises en évidence en tête. §6.5.4.1 : chaque pastille de
// synthèse porte l'ancre de sa rubrique du rapport HTML (urlSuffix) ; un
// clic ouvre le rapport à cette rubrique.

import { AlertTriangle } from "lucide-react";
import { META_SEVERITE, fondSeverite } from "@/lib/vidalReferentiels";

export default function ResultatSecurisation({ analyse, onOuvrirRubrique }) {
  if (!analyse) return null;
  const resume = analyse.summary || [];
  const toutes = analyse.alerts || [];
  const nonSecurises = toutes.filter((a) => a.alert_type === "UNSECURIZED");
  const alertes = [...nonSecurises, ...toutes.filter((a) => a.alert_type === "PATIENT"), ...toutes.filter((a) => a.alert_type !== "UNSECURIZED" && a.alert_type !== "PATIENT")];
  const resumeAlerte = resume.filter((s) => s.severity && s.severity !== "NO_ALERT");

  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        {resumeAlerte.map((s, i) => {
          const meta = META_SEVERITE[s.severity] || { label: s.severity, couleur: "#94a3b8" };
          const cliquable = s.anchor && onOuvrirRubrique;
          return (
            <span key={i} onClick={cliquable ? () => onOuvrirRubrique(s.anchor) : undefined} title={cliquable ? "Ouvrir cette rubrique du rapport HTML" : undefined}
              style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 999, color: "white", background: meta.couleur, cursor: cliquable ? "pointer" : "default" }}>
              {s.label || s.category} — {meta.label}
            </span>
          );
        })}
        {resumeAlerte.length === 0 && <span className="badge badge-vert">Aucune alerte détectée</span>}
      </div>
      {nonSecurises.length > 0 && (
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "8px 10px", borderRadius: 8, background: "rgba(249,115,22,0.10)", color: "#ea580c", fontSize: 12.5, marginBottom: 10 }}>
          <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 2 }} />
          <span>{nonSecurises.length} médicament(s) non sécurisé(s) par VIDAL : l'absence d'alerte pour ces lignes ne signifie pas l'absence de risque.</span>
        </div>
      )}
      {alertes.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--vidal-gris)" }}>Aucune alerte détaillée dans la réponse.</div>
      ) : (
        alertes.map((a, i) => {
          const meta = META_SEVERITE[a.severity] || { label: a.severity || "—", couleur: "#94a3b8" };
          return (
            <div key={i} style={{ border: "1px solid var(--vidal-bordure)", background: fondSeverite(a.severity), borderLeft: `3px solid ${meta.couleur}`, borderRadius: 10, padding: 12, marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                <div style={{ fontWeight: 700, fontSize: 13.5 }}>{a.title || a.alert_type_label || "Alerte"}</div>
                <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 9px", borderRadius: 999, color: "white", background: meta.couleur, whiteSpace: "nowrap", height: "fit-content" }} title={a.alert_type_label}>
                  {a.alert_type_label ? `${a.alert_type_label} — ${meta.label}` : meta.label}
                </span>
              </div>
              {/* § whiteSpace "pre-line" : respecte les paragraphes renvoyés par le backend (risque / conduite à tenir). */}
              {a.content && <div style={{ fontSize: 12.5, whiteSpace: "pre-line" }}>{a.content}</div>}
              {a.detail && <div style={{ fontSize: 12, color: "var(--vidal-gris-fonce)", marginTop: 4, whiteSpace: "pre-line" }}>{a.detail}</div>}
              {a.source_label && <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginTop: 6 }}>Source : {a.source_label}</div>}
            </div>
          );
        })
      )}
    </div>
  );
}
