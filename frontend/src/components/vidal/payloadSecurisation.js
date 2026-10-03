// components/vidal/payloadSecurisation.js
// -------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § Sécurisation VIDAL v2 — construction et contrôle du payload envoyé à
// POST /vidal/securisation/analyze (et /securisation/rapport-html),
// partagés par la page Sécurisation et la modale de l'ordonnance pour ne
// jamais diverger : mêmes contrôles de saisie que le serveur, mêmes lignes
// transmises (nouvelle prescription + traitements en cours cochés).

import { validerLigne, validerPatient, versPayloadLigne } from "@/lib/vidalReferentiels";
import { patientPourVidal } from "./DonneesCliniquesPatient";

/** Contrôle tout le formulaire. Retourne {ok, patient: {champ: msg}, nouvelles: [{...}], traitements: [{...}]}. */
export function validerFormulaireSecurisation(clinique, nouvelles, traitements) {
  const patient = validerPatient(clinique);
  const erreursNouvelles = nouvelles.map((l) => (l.vidal_id || l.query ? validerLigne(l) : {}));
  const erreursTraitements = traitements.map((l) => (l.inclus ? validerLigne(l) : {}));
  const ok = [patient, ...erreursNouvelles, ...erreursTraitements].every((e) => Object.keys(e).length === 0);
  return { ok, patient, nouvelles: erreursNouvelles, traitements: erreursTraitements };
}

// § historique clinique : `patientId` (patient enregistré de SAWALI) rattache
// l'instantané de sécurisation au patient ; le groupe de
// référence du DFG est envoyé au backend dans un champ LOCAL séparé
// (conservé dans l'instantané), jamais dans `patient` -> jamais à VIDAL.
export function construirePayloadSecurisation({ clinique, nouvelles, traitements, typesAlerte, patientNom, patientWhatsapp = null, patientId = null }) {
  return {
    patient_id: patientId,
    patient_whatsapp: patientWhatsapp || null,
    groupe_reference_dfg: clinique.groupeReferenceDfg || null,
    patient: patientPourVidal(clinique),
    current_treatments: traitements.filter((l) => l.inclus && l.vidal_id).map((l) => ({ ...versPayloadLigne(l), groupType: "PREVIOUS_ORDER" })),
    new_prescription_lines: nouvelles.filter((l) => l.vidal_id).map(versPayloadLigne),
    alert_types: typesAlerte,
    patient_name: patientNom || null,
  };
}

/** Résumé lisible des erreurs de saisie (bandeau au-dessus du bouton "Sécuriser"). */
export function resumeErreurs(controle) {
  const n = Object.keys(controle.patient).length
    + controle.nouvelles.reduce((t, e) => t + Object.keys(e).length, 0)
    + controle.traitements.reduce((t, e) => t + Object.keys(e).length, 0);
  return `${n} champ${n > 1 ? "s" : ""} à corriger avant la sécurisation (voir les messages en rouge).`;
}
