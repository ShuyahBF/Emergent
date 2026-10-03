// components/vidal/RapportHtmlSecurisation.jsx
// ------------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § doc VIDAL ("Obtenir la sécurisation en html") — affiche le document
// HTML exhaustif de POST /alerts/full/html (toutes les alertes, sources,
// rappel du dossier patient et de la prescription), avec une navigation
// par rubrique sur les ancres du "HTML V2" (menu_posology, menu_allergy,
// ..., menu_global). Isolation du document de VIDAL :
// <iframe srcDoc> (CSS/HTML tiers isolés),
// impression depuis la page, aucune ouverture d'onglet externe.
// § MI VIDAL §6.5.5 : rapport complet ou FILTRÉ sur des rubriques
// (<alert-display-types>) — `onFiltrer(rubriques)` relance la génération ;
// `rapport.ancre` ouvre directement une rubrique (pastille de synthèse).

import { useRef, useState } from "react";
import { FileText, Printer, X, Loader2, Filter } from "lucide-react";
import { ANCRES_RAPPORT_HTML, RUBRIQUES_RAPPORT_HTML } from "@/lib/vidalReferentiels";

function trouverAncre(doc, ancre) {
  if (!doc) return null;
  return doc.getElementById(ancre) || doc.querySelector(`[name="${ancre}"]`);
}

export default function RapportHtmlSecurisation({ rapport, onFermer, onFiltrer }) {
  const refIframe = useRef(null);
  const [ancresPresentes, setAncresPresentes] = useState(null);
  const [ancreActive, setAncreActive] = useState("menu_global");
  const [filtreOuvert, setFiltreOuvert] = useState(false);
  const [rubriques, setRubriques] = useState([]);
  if (!rapport) return null;

  // § seules les rubriques réellement présentes dans le document reçu sont
  // cliquables (une rubrique sans alerte peut ne pas exister).
  function surChargement() {
    const doc = refIframe.current?.contentDocument;
    setAncresPresentes(Object.keys(ANCRES_RAPPORT_HTML).filter((a) => a === "menu_global" || trouverAncre(doc, a)));
    if (rapport.ancre) allerA(rapport.ancre);
  }
  function allerA(ancre) {
    setAncreActive(ancre);
    const fenetre = refIframe.current?.contentWindow;
    const doc = refIframe.current?.contentDocument;
    const cible = trouverAncre(doc, ancre);
    if (cible) cible.scrollIntoView({ behavior: "smooth", block: "start" });
    else if (ancre === "menu_global") fenetre?.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div role="dialog" aria-modal="true" onClick={onFermer}
      style={{ position: "fixed", inset: 0, background: "rgba(15,20,30,0.55)", zIndex: 2100, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div className="carte" onClick={(e) => e.stopPropagation()}
        style={{ width: "min(1100px, 100%)", height: "min(90vh, 960px)", display: "flex", flexDirection: "column", padding: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderBottom: "1px solid var(--vidal-bordure)", flexShrink: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14, display: "flex", alignItems: "center", gap: 6 }}><FileText size={15} /> Rapport de sécurisation VIDAL (HTML)</div>
          <div style={{ display: "flex", gap: 8 }}>
            {onFiltrer && (
              <button className="bouton-secondaire" style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 5 }} onClick={() => setFiltreOuvert(!filtreOuvert)}>
                <Filter size={13} /> {rapport.rubriques?.length ? `Filtré (${rapport.rubriques.length})` : "Complet"}
              </button>
            )}
            <button className="bouton-secondaire" disabled={!rapport.html} style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 5 }} onClick={() => refIframe.current?.contentWindow?.print()}><Printer size={13} /> Imprimer</button>
            <button className="bouton-secondaire" style={{ fontSize: 12.5, display: "inline-flex", alignItems: "center", gap: 5 }} onClick={onFermer}><X size={13} /> Fermer</button>
          </div>
        </div>
        {filtreOuvert && onFiltrer && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--vidal-bordure)", display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", fontSize: 12.5 }}>
            {Object.entries(RUBRIQUES_RAPPORT_HTML).map(([code, libelle]) => (
              <label key={code} style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
                <input type="checkbox" checked={rubriques.includes(code)} onChange={() => setRubriques(rubriques.includes(code) ? rubriques.filter((r) => r !== code) : [...rubriques, code])} />
                {libelle}
              </label>
            ))}
            <button className="bouton-primaire" style={{ fontSize: 12 }} onClick={() => { setFiltreOuvert(false); onFiltrer(rubriques); }}>
              {rubriques.length ? "Afficher les rubriques cochées" : "Afficher le rapport complet"}
            </button>
            <span style={{ color: "var(--vidal-gris)" }}>Synthèse, profil patient et contenu de l'ordonnance restent toujours affichés.</span>
          </div>
        )}
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <nav style={{ width: 230, flexShrink: 0, borderRight: "1px solid var(--vidal-bordure)", overflowY: "auto", padding: 8 }}>
            {Object.entries(ANCRES_RAPPORT_HTML).map(([ancre, libelle]) => {
              const present = !ancresPresentes || ancresPresentes.includes(ancre);
              return (
                <button key={ancre} disabled={!present} onClick={() => allerA(ancre)}
                  style={{
                    display: "block", width: "100%", textAlign: "left", border: "none", borderRadius: 6, padding: "6px 9px", marginBottom: 2, fontSize: 12.5,
                    cursor: present ? "pointer" : "default", color: present ? "var(--vidal-texte)" : "var(--vidal-gris)",
                    background: ancreActive === ancre ? "var(--vidal-gris-clair)" : "transparent", fontWeight: ancreActive === ancre ? 700 : 500,
                  }}>
                  {libelle}
                </button>
              );
            })}
          </nav>
          {rapport.chargement ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, color: "var(--vidal-gris)" }}><Loader2 size={14} className="lucide-tourne" /> Génération du rapport…</div>
          ) : rapport.erreur ? (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--vidal-rouge)", padding: 20 }}>{rapport.erreur}</div>
          ) : (
            <iframe ref={refIframe} title="Rapport de sécurisation VIDAL" srcDoc={rapport.html} onLoad={surChargement}
              style={{ flex: 1, border: "none", width: "100%", background: "white" }} sandbox="allow-same-origin allow-modals" />
          )}
        </div>
      </div>
    </div>
  );
}
