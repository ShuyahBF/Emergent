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
// Lot 56.4 — réutilisé par la page « Analyse prescription » (allergies,
// pathologies, traitements en cours). Props facultatives ajoutées, sans
// changer le comportement par défaut de la Sécurisation :
//   - `rechercher(q)` : fonction de recherche personnalisée (ex. médicaments
//     VIDAL pour les traitements en cours) renvoyant [{label, ref, type}] ;
//   - `texteLibre` (vrai par défaut) : faux = seul un résultat VIDAL peut
//     être ajouté (la touche Entrée n'ajoute plus de texte libre) ;
//   - `placeholder`, `aide`, `testId` : textes et repère de test.
// Lot 56.10 — « pourquoi pas de liste ? » (recette VIDAL) :
//   - une erreur de recherche ne COUPE plus la recherche pour toute la page
//     (avant : une seule erreur réseau = plus jamais de liste) ; le message
//     s'affiche et la frappe suivante réessaie ;
//   - au clic dans le champ (sans rien taper), une LISTE s'ouvre : les
//     références VIDAL déjà choisies récemment (ajout en un clic) et des
//     recherches fréquentes (un clic lance la recherche VIDAL du terme ; on
//     choisit ensuite le libellé exact renvoyé par VIDAL) ;
//   - « Recherche dans VIDAL… » pendant l'attente, « Aucun résultat » sinon.

import { useRef, useState } from "react";
import { X } from "lucide-react";
import { apiClient as api } from "@/lib/api";
// § règle commune : portions correspondant à la saisie en rouge.
import { highlightMatch } from "@/lib/highlightMatch";

// Recherches fréquentes proposées à l'ouverture du champ (ce ne sont que des
// TERMES DE RECHERCHE : seul le libellé renvoyé par VIDAL est ajouté).
const RECHERCHES_FREQUENTES = {
  allergy: ["Pénicillines", "Céphalosporines", "Sulfamides", "Aspirine", "Anti-inflammatoires non stéroïdiens", "Iode", "Latex", "Codéine", "Quinolones", "Macrolides", "Arachide", "Lactose"],
  molecule: ["Paracétamol", "Amoxicilline", "Ibuprofène", "Metformine", "Amlodipine", "Oméprazole", "Artéméther", "Quinine", "Cotrimoxazole", "Diclofénac"],
  pathology: ["Hypertension artérielle", "Diabète", "Asthme", "Insuffisance rénale", "Insuffisance cardiaque", "Insuffisance hépatique", "Épilepsie", "Ulcère gastrique", "Drépanocytose", "Paludisme", "Hépatite B", "VIH"],
};
const MAX_RECENTS = 12;

// Références VIDAL choisies récemment (par type de champ), gardées dans ce navigateur
const cleRecents = (kind) => `vidal_recents_${kind}`;
function lireRecents(kind) {
  try { return JSON.parse(localStorage.getItem(cleRecents(kind)) || "[]"); } catch { return []; }
}
function noterRecent(kind, item) {
  if (!item?.ref) return;
  try {
    const liste = [item, ...lireRecents(kind).filter((r) => r.ref !== item.ref)].slice(0, MAX_RECENTS);
    localStorage.setItem(cleRecents(kind), JSON.stringify(liste.map(({ label, ref, type }) => ({ label, ref, type }))));
  } catch { /* stockage indisponible */ }
}

/** Tags allergies/pathologies/molécules — un résultat choisi porte une vraie référence VIDAL (transmise à l'analyse), un tag libre reste informatif. */
export default function ChampTagsReferentiel({ label, kind, values, onChange, rechercher = null, texteLibre = true, placeholder = null, aide = null, testId = null }) {
  const [brouillon, setBrouillon] = useState("");
  const [resultats, setResultats] = useState([]);
  const [ouvert, setOuvert] = useState(false);
  // État de la dernière recherche : "" | "en_cours" | "vide" | "erreur"
  const [etat, setEtat] = useState("");
  const [termeCherche, setTermeCherche] = useState("");
  const timer = useRef(null);
  const numero = useRef(0); // ignore les réponses d'une recherche dépassée

  // Lance la recherche VIDAL d'un terme (frappe ou recherche fréquente)
  async function lancerRecherche(q) {
    const n = ++numero.current;
    setEtat("en_cours"); setTermeCherche(q); setOuvert(true);
    try {
      // Recherche personnalisée (lot 56.4) ou recherche référentielle VIDAL (allergies, molécules, CIM-10).
      const liste = rechercher ? await rechercher(q) : (await api.get("/vidal/referential/search", { params: { kind, q } })).data?.results;
      if (n !== numero.current) return;
      setResultats(liste || []);
      setEtat((liste || []).length ? "" : "vide");
    } catch {
      if (n !== numero.current) return;
      // Erreur passagère : message, et la frappe suivante réessaie (plus de coupure définitive)
      setResultats([]);
      setEtat("erreur");
    }
  }

  function surChangement(v) {
    setBrouillon(v);
    if (timer.current) clearTimeout(timer.current);
    const q = v.trim();
    if (q.length < 2) { setResultats([]); setEtat(""); return; }
    timer.current = setTimeout(() => lancerRecherche(q), 350);
  }
  function ajouterLibre() {
    const v = brouillon.trim();
    // Texte libre interdit (lot 56.4) : on choisit le premier résultat proposé, s'il y en a.
    if (!texteLibre) { if (resultats.length) ajouterResultat(resultats[0]); return; }
    if (!v) return;
    onChange([...values, { label: v, ref: null }]);
    setBrouillon(""); setOuvert(false); setResultats([]); setEtat("");
  }
  function ajouterResultat(item) {
    if (item.ref && values.some((v) => v.ref === item.ref)) { setOuvert(false); return; } // déjà présent
    onChange([...values, { label: item.label, ref: item.ref }]);
    noterRecent(kind, item);
    setBrouillon(""); setOuvert(false); setResultats([]); setEtat("");
  }

  // Liste affichée à l'ouverture du champ vide : récents + recherches fréquentes
  const recents = lireRecents(kind).filter((r) => !values.some((v) => v.ref === r.ref));
  const frequentes = rechercher ? [] : (RECHERCHES_FREQUENTES[kind] || []);
  const afficherSuggestions = ouvert && !brouillon.trim() && resultats.length === 0 && etat !== "en_cours" && (recents.length > 0 || frequentes.length > 0);
  const styleLigne = { padding: "6px 9px", cursor: "pointer", fontSize: 12.5, borderRadius: 6 };
  const survol = {
    onMouseEnter: (e) => (e.currentTarget.style.background = "var(--vidal-gris-clair)"),
    onMouseLeave: (e) => (e.currentTarget.style.background = "transparent"),
  };

  return (
    <div style={{ position: "relative" }} data-testid={testId || undefined}>
      <label className="libelle-champ" style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>{label}</label>
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
          onFocus={() => setOuvert(true)}
          onClick={() => setOuvert(true)}
          onBlur={() => setTimeout(() => setOuvert(false), 150)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); ajouterLibre(); } if (e.key === "Escape") setOuvert(false); }}
          placeholder={placeholder || (texteLibre ? "Cliquer pour la liste, ou rechercher… (Entrée = texte libre)" : "Cliquer pour la liste, ou rechercher dans VIDAL…")}
          style={{ flex: 1, minWidth: 100, border: "none", outline: "none", fontSize: 13, background: "transparent" }}
        />
      </div>

      {/* Résultats de la recherche VIDAL (ou état de la recherche) */}
      {ouvert && (resultats.length > 0 || etat) && (
        <div className="carte" style={{ position: "absolute", top: "100%", zIndex: 20, width: "100%", marginTop: 4, maxHeight: 240, overflowY: "auto", padding: 4 }}>
          {etat === "en_cours" && <div style={{ ...styleLigne, cursor: "default", color: "var(--vidal-gris)" }}>Recherche dans VIDAL « {termeCherche} »…</div>}
          {etat === "vide" && <div style={{ ...styleLigne, cursor: "default", color: "var(--vidal-gris)" }}>Aucun résultat dans VIDAL pour « {termeCherche} ».</div>}
          {etat === "erreur" && <div style={{ ...styleLigne, cursor: "default", color: "var(--vidal-rouge)" }}>Recherche VIDAL momentanément indisponible — continuez à taper pour réessayer.</div>}
          {resultats.map((r, i) => (
            <div key={i} onMouseDown={(e) => { e.preventDefault(); ajouterResultat(r); }} style={styleLigne} {...survol}>
              <span style={{ fontStyle: r.type === "ALLERGY" ? "italic" : "normal" }}>{highlightMatch(r.label, brouillon || termeCherche)}</span>
              {r.type === "MOLECULE" && <span style={{ fontSize: 10.5, color: "var(--vidal-gris)" }}> — substance</span>}
              {r.type === "ALLERGY" && <span style={{ fontSize: 10.5, color: "var(--vidal-gris)" }}> — classe d'allergie</span>}
            </div>
          ))}
        </div>
      )}

      {/* Lot 56.10 — liste à l'ouverture du champ : récents (ajout direct) + recherches fréquentes */}
      {afficherSuggestions && (
        <div className="carte" style={{ position: "absolute", top: "100%", zIndex: 20, width: "100%", marginTop: 4, maxHeight: 260, overflowY: "auto", padding: 4 }}>
          {recents.length > 0 && (
            <>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--vidal-gris)", padding: "4px 9px" }}>CHOISIS RÉCEMMENT (référence VIDAL)</div>
              {recents.map((r) => (
                <div key={r.ref} onMouseDown={(e) => { e.preventDefault(); ajouterResultat(r); }} style={styleLigne} {...survol}>
                  <span style={{ fontStyle: r.type === "ALLERGY" ? "italic" : "normal" }}>{r.label}</span>
                </div>
              ))}
            </>
          )}
          {frequentes.length > 0 && (
            <>
              <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--vidal-gris)", padding: "4px 9px" }}>RECHERCHES FRÉQUENTES (cliquer pour chercher dans VIDAL)</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5, padding: "2px 9px 6px" }}>
                {frequentes.map((t) => (
                  <button key={t} type="button" className="badge" onMouseDown={(e) => { e.preventDefault(); lancerRecherche(t); }}
                    style={{ cursor: "pointer", border: "1px solid var(--vidal-gris-clair)", background: "white" }}>
                    🔍 {t}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <div style={{ fontSize: 10, color: "var(--vidal-gris)", marginTop: 3 }}>
        {aide || "Un résultat choisi porte une vraie référence VIDAL ; sinon reste informatif."}
      </div>
    </div>
  );
}
