// components/vidal/ChampTagsReferentiel.jsx
// ----------------------------------------------
// Lot 56 (SAWALI) — repris de Ster (frontend/src/components/vidal/), styles via vidalV2.css.
// § Déplacé depuis pages/VidalSecurisation.jsx (sécurisation v2) pour être
// partagé par la page Sécurisation ET la modale de l'ordonnance : saisie
// des allergies (classes, "Term = Allergy"), allergies à une molécule ou
// un excipient ("Term = Molecule") et pathologies CIM-10 par autocomplétion
// sur les recherches référentielles de l'API VIDAL
// (/vidal/referential/search). Un résultat choisi porte une vraie référence
// VIDAL (transmise à l'analyse) ; un texte libre reste informatif.
// § MI VIDAL §5.1.2.2 : la recherche d'allergie renvoie à la fois des
// classes d'allergie et des substances — les classes sont affichées en
// italique pour les distinguer.

import { useState } from "react";
import { X } from "lucide-react";
import { apiClient as api } from "@/lib/api";
// § règle commune : portions correspondant à la saisie en rouge.
import { highlightMatch } from "@/lib/highlightMatch";

/** Tags allergies/pathologies/molécules — un résultat choisi porte une vraie référence VIDAL (transmise à l'analyse), un tag libre reste informatif. */
export default function ChampTagsReferentiel({ label, kind, values, onChange }) {
  const [brouillon, setBrouillon] = useState("");
  const [resultats, setResultats] = useState([]);
  const [ouvert, setOuvert] = useState(false);
  const [rechercheDesactivee, setRechercheDesactivee] = useState(false);
  const [timer, setTimer] = useState(null);

  function surChangement(v) {
    setBrouillon(v);
    if (timer) clearTimeout(timer);
    const q = v.trim();
    if (rechercheDesactivee || q.length < 2) { setResultats([]); return; }
    setTimer(setTimeout(async () => {
      try {
        const r = await api.get("/vidal/referential/search", { params: { kind, q } });
        setResultats(r.data?.results || []);
        setOuvert(true);
      } catch {
        setRechercheDesactivee(true);
        setResultats([]);
      }
    }, 350));
  }
  function ajouterLibre() {
    const v = brouillon.trim();
    if (!v) return;
    onChange([...values, { label: v, ref: null }]);
    setBrouillon(""); setOuvert(false); setResultats([]);
  }
  function ajouterResultat(item) {
    onChange([...values, { label: item.label, ref: item.ref }]);
    setBrouillon(""); setOuvert(false); setResultats([]);
  }

  return (
    <div style={{ position: "relative" }}>
      <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>{label}</label>
      <div className="champ-saisie" style={{ display: "flex", flexWrap: "wrap", gap: 5, minHeight: 40, alignItems: "center" }}>
        {values.map((v, i) => (
          <span key={i} title={v.ref ? "Référence VIDAL résolue — transmise à l'analyse" : "Texte libre — informatif, non transmis à VIDAL"}
            className={`badge ${v.ref ? "badge-bleu" : "badge-vert"}`} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontStyle: String(v.ref || "").startsWith("vidal://allergy/") ? "italic" : "normal" }}>
            {v.label}
            <span onClick={() => onChange(values.filter((_, j) => j !== i))} style={{ cursor: "pointer", display: "inline-flex" }}><X size={11} /></span>
          </span>
        ))}
        <input
          value={brouillon} onChange={(e) => surChangement(e.target.value)}
          onFocus={() => resultats.length > 0 && setOuvert(true)}
          onBlur={() => setTimeout(() => setOuvert(false), 150)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); ajouterLibre(); } }}
          placeholder="Rechercher ou ajouter en texte libre… (Entrée)"
          style={{ flex: 1, minWidth: 100, border: "none", outline: "none", fontSize: 13, background: "transparent" }}
        />
      </div>
      {ouvert && resultats.length > 0 && (
        <div className="carte" style={{ position: "absolute", top: "100%", zIndex: 20, width: "100%", marginTop: 4, maxHeight: 160, overflowY: "auto", padding: 4 }}>
          {resultats.map((r, i) => (
            <div key={i} onMouseDown={(e) => { e.preventDefault(); ajouterResultat(r); }} style={{ padding: "6px 9px", cursor: "pointer", fontSize: 12.5, borderRadius: 6 }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--vidal-gris-clair)")} onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
              <span style={{ fontStyle: r.type === "ALLERGY" ? "italic" : "normal" }}>{highlightMatch(r.label, brouillon)}</span>
              {r.type === "MOLECULE" && <span style={{ fontSize: 10.5, color: "var(--vidal-gris)" }}> — substance</span>}
              {r.type === "ALLERGY" && <span style={{ fontSize: 10.5, color: "var(--vidal-gris)" }}> — classe d'allergie</span>}
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 10, color: "var(--vidal-gris)", marginTop: 3 }}>
        {rechercheDesactivee ? "Recherche référentielle indisponible — saisie libre uniquement." : "Un résultat choisi porte une vraie référence VIDAL ; sinon reste informatif."}
      </div>
    </div>
  );
}
