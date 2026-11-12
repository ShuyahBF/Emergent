// Lot 376 — Pastilles de couleur VIDAL : repère visuel du TYPE d'un élément (classe, molécule, spécialité, VMP, UCD, pathologie…)
// pour guider le prescripteur dans tous les champs de saisie (remarques de la démonstration VIDAL).
//   rouge = classe (classe d'allergie, classe thérapeutique) · bleu = molécule / substance · vert = spécialité · violet = VMP
//   orange = UCD · turquoise = pathologie (CIM-10) · gris = autre.
import React from "react";

export const TYPES_VIDAL = {
  CLASSE: { couleur: "#e0392b", libelle: "Classe" },
  MOLECULE: { couleur: "#1d6fd1", libelle: "Molécule" },
  SPECIALITE: { couleur: "#2fa84f", libelle: "Spécialité" },
  PRESENTATION: { couleur: "#0ea5a4", libelle: "Présentation" },
  VMP: { couleur: "#7c3aed", libelle: "VMP" },
  UCD: { couleur: "#d97706", libelle: "UCD" },
  PATHOLOGIE: { couleur: "#0f766e", libelle: "Pathologie" },
  ALD: { couleur: "#be185d", libelle: "ALD" },
  AUTRE: { couleur: "#94a3b8", libelle: "Autre" },
};

/**
 * Type visuel d'un élément VIDAL d'après son `type` (ALLERGY, MOLECULE, PRODUCT, VMP, UCD, PACK, PATHOLOGY, ALD…) ou, à défaut, le préfixe de sa
 * référence (vidal://allergy/…, vidal://molecule/…, vidal://product/…, vidal://vmp/…, vidal://ucd/…, vidal://package/…, vidal://cim10/…).
 */
export function typeVisuel(type, ref) {
  const t = String(type || "").toUpperCase();
  const r = String(ref || "").toLowerCase();
  if (t === "ALLERGY" || t === "CLASS" || t === "CLASSE" || r.startsWith("vidal://allergy/")) return "CLASSE";
  if (t === "MOLECULE" || r.startsWith("vidal://molecule/")) return "MOLECULE";
  if (t === "PRODUCT" || t === "SPECIALITE" || r.startsWith("vidal://product/")) return "SPECIALITE";
  if (t === "PACK" || t === "PACKAGE" || r.startsWith("vidal://package/")) return "PRESENTATION";
  if (t === "VMP" || r.startsWith("vidal://vmp/")) return "VMP";
  if (t === "UCD" || r.startsWith("vidal://ucd/")) return "UCD";
  if (t === "PATHOLOGY" || t === "CIM10" || r.startsWith("vidal://cim10/") || r.startsWith("vidal://pathology/")) return "PATHOLOGIE";
  if (t === "ALD" || r.startsWith("vidal://ald/")) return "ALD";
  return "AUTRE";
}

/** Petite pastille ronde de couleur (avec, si demandé, son libellé). Un `title` explique la couleur au survol. */
export function Pastille({ type = "AUTRE", avecLibelle = false, taille = 10, style }) {
  const t = TYPES_VIDAL[type] || TYPES_VIDAL.AUTRE;
  return (
    <span title={t.libelle} data-pastille={type} style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0, ...style }}>
      <span aria-hidden="true" style={{ width: taille, height: taille, borderRadius: "50%", background: t.couleur, display: "inline-block" }} />
      {avecLibelle ? <span style={{ fontSize: 10.5, color: "var(--vidal-gris, #64748b)" }}>{t.libelle}</span> : <span style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>{t.libelle}</span>}
    </span>
  );
}

/** Légende des couleurs (une ligne de pastilles avec leur nom) : `types` = clés de TYPES_VIDAL à afficher. */
export function LegendePastilles({ types = ["CLASSE", "MOLECULE", "SPECIALITE", "VMP", "UCD"], style }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, fontSize: 10.5, color: "var(--vidal-gris, #64748b)", ...style }} data-testid="legende-pastilles">
      {types.map((k) => <Pastille key={k} type={k} avecLibelle />)}
    </div>
  );
}
