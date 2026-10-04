// components/vidal/ApercuPdfIntegre.jsx
// ------------------------------------------------
// Lot 56.10 — règle du propriétaire (recette VIDAL) : « Tous les aperçus de PDF se
// font intégrés dans les pages. Aucun affichage externe et les téléchargements sont
// interdits. » Fenêtre d'aperçu posée PAR-DESSUS la page (jamais un nouvel onglet) :
//   - PDF (ordonnance, historique clinique, RCP / monographie VIDAL) : lecteur
//     interne PdfViewer (rendu image, clic droit et Ctrl+S bloqués), SANS bouton
//     de téléchargement, quel que soit le rôle ;
//   - page HTML VIDAL : affichée dans un cadre intégré.
// `apercu` = { src, titre, html } ; `src` peut être une adresse « blob: » (PDF
// généré par le serveur) : elle est libérée à la fermeture.
import { useEffect } from "react";
import { X } from "lucide-react";
import PdfViewer from "@/components/PdfViewer";

export default function ApercuPdfIntegre({ apercu, onFermer }) {
  // Libère la mémoire du PDF généré quand l'aperçu se ferme ou change
  useEffect(() => () => {
    if (apercu?.src?.startsWith("blob:")) window.URL.revokeObjectURL(apercu.src);
  }, [apercu?.src]);

  if (!apercu) return null;
  return (
    <div role="dialog" aria-modal="true" onClick={onFermer}
      style={{ position: "fixed", inset: 0, background: "rgba(15,20,30,0.6)", zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center", padding: 12 }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "min(1100px, 100%)", height: "92vh", background: "white", borderRadius: 12, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {apercu.html ? (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", borderBottom: "1px solid #e2e8f0" }}>
              <strong style={{ fontSize: 14 }}>{apercu.titre}</strong>
              <button type="button" onClick={onFermer} aria-label="Fermer" style={{ border: "none", background: "none", cursor: "pointer", display: "flex" }}><X size={18} /></button>
            </div>
            {/* Page VIDAL affichée dans la page (sandbox : pas d'ouverture de fenêtre ni de téléchargement) */}
            <iframe title={apercu.titre} src={apercu.src} sandbox="allow-scripts allow-same-origin" style={{ flex: 1, border: 0, width: "100%" }} />
          </>
        ) : (
          <PdfViewer src={apercu.src} title={apercu.titre} onClose={onFermer} allowDownload={false}
            messageLecture="🔒 Aperçu intégré uniquement — le téléchargement est désactivé." />
        )}
      </div>
    </div>
  );
}
