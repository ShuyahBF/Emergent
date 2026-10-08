import React, { useEffect, useState } from "react";
import { libelleVersion } from "@/components/EtatConnexion";

/*
  Tiny version pill rendered at the bottom-left of any page.
  Shows the running build version + last restart time.
  Re-fetches every 5 minutes so a redeploy is reflected without a full page reload.
  Visual style (color / size / opacity / weight / italic) is configurable
  by the super-admin in /admin/settings → "Version stamp".
*/
const SIZE_PX = { xs: 10, sm: 12, md: 14, lg: 16 };

// Lot 79.13 — sur téléphone, le libellé flottant (position fixe en bas à gauche) passait PAR-DESSUS le contenu
// (tableaux, boutons). Deux variantes :
//   - « flottant » (par défaut) : position fixe, seulement sur grand écran (lg et plus) ;
//   - « pied » : ligne normale en bas de la page, seulement sur petit écran — à placer à la fin du contenu.
// La règle 2 (version et date toujours affichées) est donc respectée partout, sans rien masquer.
export default function VersionStamp({ variante = "flottant" }) {
  const [info, setInfo] = useState(null);
  const [style, setStyle] = useState({
    color: null,
    size: "xs",
    opacity: 70,
    style: "normal",
  });

  useEffect(() => {
    let alive = true;
    const fetchVer = () => {
      fetch("/api/version")
        .then((r) => r.json())
        .then((j) => { if (alive) setInfo(j); })
        .catch(() => {});
    };
    const fetchStyle = () => {
      fetch("/api/company-info")
        .then((r) => r.json())
        .then((j) => {
          if (!alive) return;
          const v = j?.version_stamp || {};
          setStyle({
            color: v.color || null,
            size: v.size || "xs",
            opacity: typeof v.opacity === "number" ? v.opacity : 70,
            style: v.style || "normal",
          });
        })
        .catch(() => {});
    };
    fetchVer();
    fetchStyle();
    const id = setInterval(fetchVer, 5 * 60 * 1000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!info) return null;
  // Règle du 04/10/2026 : hors administration, « Version X · déployée le JJ/MM/AAAA HH:MM »
  // (plus de lot ni de commit) — même libellé que la page de connexion et la barre latérale.
  const texte = libelleVersion(info, false);

  const fontSize = SIZE_PX[style.size] || SIZE_PX.xs;
  const fontWeight = (style.style || "").includes("bold") ? 700 : 400;
  const fontStyle = (style.style || "").includes("italic") ? "italic" : "normal";
  const opacity = Math.max(10, Math.min(100, style.opacity || 70)) / 100;
  // Default falls back to slate-500 when no color is configured.
  const color = style.color || "#64748b";

  return (
    <div
      className={variante === "pied"
        ? "lg:hidden block w-full text-center py-2 select-none tracking-wide"
        : "hidden lg:block fixed bottom-2 left-3 z-30 select-none pointer-events-none tracking-wide"}
      data-testid={variante === "pied" ? "version-stamp-pied" : "version-stamp"}
      title={texte}
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize,
        fontWeight,
        fontStyle,
        opacity,
        color,
      }}
    >
      {/* Règle permanente : version + date de déploiement (lot et commit réservés à l'administration) */}
      {texte}
    </div>
  );
}
