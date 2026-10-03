// components/vidal/DonneesCliniquesPatient.jsx
// ------------------------------------------------
// § Revue d'implémentation VIDAL — formulaire "Données cliniques du
// patient" partagé par la page Sécurisation et la modale de l'ordonnance :
//   - reproche n°1 : bloc FEMME (affiché seulement si Sexe = Femme) avec
//     "Grossesse en cours" (date des dernières règles OU semaines
//     d'aménorrhée, conversion automatique dans les deux sens, 2 à 42 SA)
//     et "Allaitement en cours" (date de début OU durée approximative,
//     catégorie VIDAL déduite de la date) ;
//   - reproche n°2 : fonction rénale à 3 valeurs — créatininémie saisie
//     (µmol/L ou mg/dL), clairance de la créatinine et DFG CALCULÉS
//     (grisés, modifiables via "Saisie manuelle"), calculateurs VIDAL
//     appelés par le backend avec repli sur le calcul local ;
//   - reproche n°3 : listes déroulantes (sexe, insuffisance hépatique,
//     durée d'allaitement, unité de créatininémie), bornes, contrôles, et
//     TOUTES les unités entre parenthèses dans les libellés.
//   - MI VIDAL (2025.12 REV 03) : sexe "non renseigné" (nil) distinct de
//     "indéterminé", clairance transmise en entier (jamais 0), seul DFG
//     sans coefficient ethnique, avertissements > 41 SA et allaitement
//     > 2 ans, champ allergies unique (classes + substances) ;
//   - demande utilisateur : groupe de référence du DFG (paramétrable par
//     le gestionnaire de l'établissement) pour APPRÉCIER le DFG — aide visuelle locale,
//     jamais transmise à VIDAL.
// L'état est porté par le parent (`clinique` + `onChange(patch)`) ; les
// fonctions exportées en bas de fichier le créent, l'importent depuis le
// patient enregistré et le convertissent en payload VIDAL / profil clinique.
//
// Lot 56 (SAWALI) — repris de Ster ; seules différences : le profil vient du
// sous-document `profil_clinique` d'un patient de `vidal_patients` (ou de
// l'ancien `profile`), et le patient est désigné par `patientId`.

import { useEffect, useMemo, useRef, useState } from "react";
import { User, Baby, Activity, Loader2 } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import ChampTagsReferentiel from "./ChampTagsReferentiel";
import { chargerEtatValidation } from "./BandeauValidationVidal";
import {
  ALLAITEMENTS, optionsInsuffisanceHepatique, INSUFFISANCES_RENALES, BORNES, GROUPES_DFG_DEFAUT, SEUILS_DFG_DEFAUT, optionsDepuis,
  optionsSexe, donneesFemmeAutorisees, aujourdhuiISO, ageEnAnnees, formatDateFr, formatDateISO, mapperGenreVidal, saDepuisDdr,
  ddrDepuisSa, categorieAllaitementDepuisDate, mgDlVersUmolL, arrondi2, calculerFonctionRenaleLocale, avertissementsCliniques,
  groupeDfgParDefaut, interpreterDfg, messageErreurApi,
} from "@/lib/vidalReferentiels";

const DELAI_CALCULATEUR_MS = 700;

// § groupes de référence du DFG de l'établissement : chargés une fois par session
// (GET /vidal/groupes-dfg), valeurs préremplies en repli.
let promesseGroupesDfg = null;
export function chargerGroupesDfg(forcer = false) {
  if (!promesseGroupesDfg || forcer) {
    promesseGroupesDfg = api.get("/vidal/groupes-dfg")
      .then((r) => r.data)
      .catch(() => ({ groupes: GROUPES_DFG_DEFAUT, seuils: SEUILS_DFG_DEFAUT }));
  }
  return promesseGroupesDfg;
}

// ---------------------------------------------------------------------------
// Petits éléments d'interface
// ---------------------------------------------------------------------------
const STYLE_LIBELLE = { fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", gap: 6, marginBottom: 3, flexWrap: "wrap" };
const STYLE_CALCULE = { background: "var(--vidal-gris-clair)", color: "var(--vidal-gris-fonce)" };

export function Libelle({ children, saisiLe, obligatoire }) {
  return (
    <label className={obligatoire ? "libelle-obligatoire" : undefined} style={STYLE_LIBELLE}>
      {obligatoire ? "* " : ""}{children}
      {saisiLe && <span className="badge" style={{ fontSize: 10, fontWeight: 500, background: "var(--vidal-gris-clair)", color: "var(--vidal-gris-fonce)" }}>Saisi le {formatDateFr(saisiLe)}</span>}
    </label>
  );
}

export function MessageErreur({ message }) {
  if (!message) return null;
  return <div style={{ fontSize: 11, color: "var(--vidal-rouge)", marginTop: 3 }}>{message}</div>;
}

export function MessageAvertissement({ message }) {
  if (!message) return null;
  return <div style={{ fontSize: 11, color: "var(--vidal-orange)", marginTop: 3 }}>{message}</div>;
}

function styleChamp(erreur, calcule) {
  return { ...(calcule ? STYLE_CALCULE : {}), ...(erreur ? { borderColor: "var(--vidal-rouge)" } : {}) };
}

// ---------------------------------------------------------------------------
// Composant
// ---------------------------------------------------------------------------
export default function DonneesCliniquesPatient({ clinique: c, onChange, erreurs = {}, identiteVerrouillee = false, patientId = null }) {
  const aujourdhui = aujourdhuiISO();
  const avertissements = avertissementsCliniques(c);
  const [configDfg, setConfigDfg] = useState({ groupes: GROUPES_DFG_DEFAUT, seuils: SEUILS_DFG_DEFAUT });
  useEffect(() => {
    let actif = true;
    chargerGroupesDfg().then((config) => { if (actif) setConfigDfg(config); });
    return () => { actif = false; };
  }, []);
  const groupesActifs = (configDfg.groupes || []).filter((g) => g.actif).sort((a, b) => (a.ordre || 0) - (b.ordre || 0));
  const groupeDfg = groupesActifs.find((g) => g.id === c.groupeReferenceDfg) || groupeDfgParDefaut(configDfg.groupes);
  const interpretationDfg = groupeDfg ? interpreterDfg(c.glomerularFiltrationRate, groupeDfg.valeur_normale, configDfg.seuils) : null;
  const age = ageEnAnnees(c.dateOfBirth);
  const imc = c.weight && c.height ? Number(c.weight) / (Number(c.height) / 100) ** 2 : null;
  const creatUmol = c.creatinineSaisie === "" || c.creatinineSaisie == null
    ? null
    : c.creatinineUnite === "mg_dl" ? mgDlVersUmolL(c.creatinineSaisie) : Number(c.creatinineSaisie);

  // § calcul local IMMÉDIAT (affichage sans attente), puis confirmation par
  // les calculateurs VIDAL via le backend (voir effet ci-dessous).
  const calculLocal = useMemo(
    () => (creatUmol && c.dateOfBirth && c.weight ? calculerFonctionRenaleLocale({ dateOfBirth: c.dateOfBirth, gender: c.gender, weight: c.weight, creatUmol }) : null),
    [creatUmol, c.dateOfBirth, c.gender, c.weight],
  );
  const idCalculRef = useRef(0);
  // § mode validation VIDAL : AUCUNE valeur calculée localement — les 3
  // valeurs viennent des calculateurs VIDAL ou restent vides avec l'erreur
  // réelle. État inconnu (chargement) = traité comme mode validation.
  const [modeValidation, setModeValidation] = useState(null);
  useEffect(() => {
    let actif = true;
    chargerEtatValidation().then((e) => { if (actif) setModeValidation(e ? !!e.mode_validation : true); });
    return () => { actif = false; };
  }, []);
  const sansCalculLocal = modeValidation !== false;

  useEffect(() => {
    if (c.saisieManuelleRenale) return undefined;
    const monId = ++idCalculRef.current;
    if (!calculLocal || calculLocal.creatin == null) {
      // Créatininémie absente ou données insuffisantes : rien à transmettre (balise <creatin> nil).
      if (c.creatin !== "" || c.glomerularFiltrationRate !== "") onChange({ creatin: "", glomerularFiltrationRate: "", creatinCalculee: null, plafonnee: false, sourceRenale: null, insuffisanceRenale: null, stadeKdigo: null });
      return undefined;
    }
    if (sansCalculLocal) {
      onChange({ creatin: "", glomerularFiltrationRate: "", creatinCalculee: null, plafonnee: false, sourceRenale: null,
        insuffisanceRenale: null, stadeKdigo: null, calculRenalEnCours: true, erreurRenal: null });
    } else {
      onChange({
        creatin: String(calculLocal.creatin), glomerularFiltrationRate: calculLocal.glomerularFiltrationRate == null ? "" : String(calculLocal.glomerularFiltrationRate),
        creatinCalculee: calculLocal.creatin_calculee, plafonnee: calculLocal.plafonnee, sourceRenale: "local", calculRenalEnCours: true,
        insuffisanceRenale: calculLocal.insuffisanceRenale, stadeKdigo: null, erreurRenal: null,
      });
    }
    const minuteur = setTimeout(async () => {
      try {
        // § le groupe de référence du DFG n'est volontairement PAS envoyé (jamais transmis à VIDAL).
        const r = await api.post("/vidal/calculateurs/fonction-renale", {
          dateOfBirth: c.dateOfBirth, gender: c.gender, weight: Number(c.weight), height: c.height ? Number(c.height) : null,
          serumCreatinine: Number(c.creatinineSaisie), serumCreatinineUnit: c.creatinineUnite,
          // § mode validation VIDAL : patient fictif concerné (sinon calcul local, rien n'est envoyé).
          patient_id: patientId,
        });
        if (idCalculRef.current !== monId) return; // saisie modifiée entre-temps
        const d = r.data;
        onChange({
          creatin: d.creatin == null ? "" : String(d.creatin),
          glomerularFiltrationRate: d.glomerularFiltrationRate == null ? "" : String(d.glomerularFiltrationRate),
          creatinCalculee: d.creatin_calculee, plafonnee: d.plafonnee,
          insuffisanceRenale: d.insuffisanceRenale || null, stadeKdigo: d.stadeKdigo || null,
          sourceRenale: d.sources?.creatin === "vidal" || d.sources?.glomerularFiltrationRate === "vidal" ? "vidal" : "local",
          calculRenalEnCours: false, avertissementRenal: d.avertissement || null,
        });
      } catch (err) {
        if (idCalculRef.current !== monId) return;
        // Mode validation : erreur RÉELLE affichée, rien de rempli. Hors mode validation : le calcul local reste affiché.
        onChange(sansCalculLocal
          ? { calculRenalEnCours: false, erreurRenal: messageErreurApi(err, "Calculateur VIDAL en erreur.") }
          : { calculRenalEnCours: false });
      }
    }, DELAI_CALCULATEUR_MS);
    return () => clearTimeout(minuteur);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculLocal?.creatin_calculee, calculLocal?.glomerularFiltrationRate, c.saisieManuelleRenale, sansCalculLocal]);

  function changerMesure(patch) {
    onChange({ ...patch, weightDate: aujourdhui });
  }
  function changerCreatinine(patch) {
    onChange({ ...patch, renalDate: aujourdhui });
  }
  // § conversion automatique dans les deux sens : la date des dernières
  // règles donne les SA révolues ; des SA saisies donnent la date.
  function changerDdr(valeur) {
    const sa = saDepuisDdr(valeur);
    onChange({ lastMenstrualPeriodDate: valeur, weeksOfAmenorrhea: valeur && sa != null ? String(sa) : "" });
  }
  function changerSa(valeur) {
    const entier = /^\d+$/.test(valeur);
    onChange({ weeksOfAmenorrhea: valeur, lastMenstrualPeriodDate: entier ? ddrDepuisSa(Number(valeur)) : "" });
  }
  const categorieDeduite = c.breastFeedingStartDate ? categorieAllaitementDepuisDate(c.breastFeedingStartDate) : null;

  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}><User size={15} /> Données cliniques du patient</div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 10 }}>
        <div>
          <Libelle>Date de naissance (jj/mm/aaaa)</Libelle>
          <input type="date" className="champ-saisie" max={aujourdhui} value={c.dateOfBirth} disabled={identiteVerrouillee}
            onChange={(e) => onChange({ dateOfBirth: e.target.value })} style={styleChamp(erreurs.dateOfBirth, identiteVerrouillee)} />
          <MessageErreur message={erreurs.dateOfBirth} />
        </div>
        <div>
          <Libelle>Âge (ans)</Libelle>
          <input className="champ-saisie" value={age == null ? "" : age} readOnly tabIndex={-1} style={STYLE_CALCULE} placeholder="Calculé" />
        </div>
        <div>
          <Libelle>Sexe</Libelle>
          <select className="champ-saisie" value={c.gender} disabled={identiteVerrouillee} onChange={(e) => onChange({ gender: e.target.value })} style={styleChamp(null, identiteVerrouillee)}>
            {optionsSexe().map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <Libelle>Insuffisance hépatique</Libelle>
          <select className="champ-saisie" value={c.hepaticInsufficiency} onChange={(e) => onChange({ hepaticInsufficiency: e.target.value })}>
            {optionsInsuffisanceHepatique().map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginBottom: 12 }}>
        <div>
          <Libelle saisiLe={c.weight ? c.weightDate : null}>Poids (kg)</Libelle>
          <input type="number" className="champ-saisie" min={BORNES.poids_kg.min} max={BORNES.poids_kg.max} step="0.1" value={c.weight}
            onChange={(e) => changerMesure({ weight: e.target.value })} style={styleChamp(erreurs.weight)} placeholder="kg" />
          <MessageErreur message={erreurs.weight} />
        </div>
        <div>
          <Libelle saisiLe={c.height ? c.weightDate : null}>Taille (cm)</Libelle>
          <input type="number" className="champ-saisie" min={BORNES.taille_cm.min} max={BORNES.taille_cm.max} step="1" value={c.height}
            onChange={(e) => changerMesure({ height: e.target.value })} style={styleChamp(erreurs.height)} placeholder="cm" />
          <MessageErreur message={erreurs.height} />
        </div>
        <div>
          <Libelle>IMC (kg/m²)</Libelle>
          <input className="champ-saisie" readOnly tabIndex={-1} style={STYLE_CALCULE} value={imc ? imc.toFixed(1) : ""} placeholder="Calculé (indicatif)" />
        </div>
      </div>

      {/* § reproche VIDAL n°2 : les 3 valeurs de la fonction rénale. */}
      <div style={{ border: "1px solid var(--vidal-bordure)", borderRadius: 10, padding: 12, marginBottom: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <Activity size={14} /> Fonction rénale
          {c.renalDate && c.creatinineSaisie !== "" && <span className="badge" style={{ fontSize: 10, fontWeight: 500, background: "var(--vidal-gris-clair)", color: "var(--vidal-gris-fonce)" }}>Bilan saisi le {formatDateFr(c.renalDate)}</span>}
          {c.calculRenalEnCours && <Loader2 size={12} className="lucide-tourne" />}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
          <div>
            <Libelle>Créatininémie ({c.creatinineUnite === "mg_dl" ? "mg/dL" : "µmol/L"})</Libelle>
            <div style={{ display: "flex", gap: 6 }}>
              <input type="number" className="champ-saisie" step="any"
                min={c.creatinineUnite === "mg_dl" ? BORNES.creatininemie_mg_dl.min : BORNES.creatininemie_umol_l.min}
                max={c.creatinineUnite === "mg_dl" ? BORNES.creatininemie_mg_dl.max : BORNES.creatininemie_umol_l.max}
                value={c.creatinineSaisie} onChange={(e) => changerCreatinine({ creatinineSaisie: e.target.value })}
                style={styleChamp(erreurs.creatinineSaisie)} placeholder={c.creatinineUnite === "mg_dl" ? "mg/dL" : "µmol/L"} />
              <select className="champ-saisie" style={{ width: 105, flexShrink: 0 }} value={c.creatinineUnite}
                onChange={(e) => changerCreatinine({ creatinineUnite: e.target.value, creatinineSaisie: "" })} title="Unité de la créatininémie">
                <option value="umol_l">µmol/L</option>
                <option value="mg_dl">mg/dL</option>
              </select>
            </div>
            {c.creatinineUnite === "mg_dl" && creatUmol ? <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginTop: 3 }}>Transmise à VIDAL : {arrondi2(creatUmol)} µmol/L</div> : null}
            <MessageErreur message={erreurs.creatinineSaisie} />
          </div>
          <div>
            <Libelle>Clairance de la créatinine (ml/min)</Libelle>
            <input type="number" className="champ-saisie" step="1" min={BORNES.clairance_ml_min.min} max={BORNES.clairance_ml_min.max}
              readOnly={!c.saisieManuelleRenale} tabIndex={c.saisieManuelleRenale ? 0 : -1}
              value={c.creatin} onChange={(e) => onChange({ creatin: e.target.value, renalDate: aujourdhui })}
              style={styleChamp(erreurs.creatin, !c.saisieManuelleRenale)} placeholder={c.saisieManuelleRenale ? "Entier de 1 à 120" : "Calculée"} />
            {c.plafonnee && !c.saisieManuelleRenale && (
              <div style={{ fontSize: 10.5, color: "var(--vidal-gris-fonce)", marginTop: 3 }}>
                Calculée : {c.creatinCalculee} ml/min — transmise à {BORNES.clairance_ml_min.max} ml/min (borne VIDAL : fonction rénale normale).
              </div>
            )}
            {!c.plafonnee && c.creatinCalculee != null && !c.saisieManuelleRenale && (
              <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginTop: 3 }}>Calculée : {c.creatinCalculee} ml/min (transmise arrondie à l'entier).</div>
            )}
            {c.insuffisanceRenale && !c.saisieManuelleRenale && (
              <div style={{ fontSize: 10.5, color: c.insuffisanceRenale === "NONE" ? "var(--vidal-gris-fonce)" : "var(--vidal-orange)", marginTop: 3 }}>{INSUFFISANCES_RENALES[c.insuffisanceRenale]}</div>
            )}
            <MessageErreur message={erreurs.creatin} />
          </div>
          <div>
            <Libelle>Débit de filtration glomérulaire (ml/min/1,73 m²)</Libelle>
            <input type="number" className="champ-saisie" step="any" min={BORNES.dfg_ml_min_173.min} max={BORNES.dfg_ml_min_173.max}
              readOnly={!c.saisieManuelleRenale} tabIndex={c.saisieManuelleRenale ? 0 : -1}
              value={c.glomerularFiltrationRate} onChange={(e) => onChange({ glomerularFiltrationRate: e.target.value, renalDate: aujourdhui })}
              style={styleChamp(erreurs.glomerularFiltrationRate, !c.saisieManuelleRenale)} placeholder={c.saisieManuelleRenale ? "0 à 200" : "Calculé"} />
            {c.stadeKdigo && !c.saisieManuelleRenale && <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginTop: 3 }}>Stade KDIGO (VIDAL) : {c.stadeKdigo}</div>}
            <MessageErreur message={erreurs.glomerularFiltrationRate} />
          </div>
          {/* § demande utilisateur : le médecin précise le GROUPE de référence
              pour apprécier le DFG par rapport à la valeur normale de ce
              groupe (valeurs paramétrables par le gestionnaire). Aide
              visuelle uniquement : le DFG calculé/transmis ne change pas,
              et le groupe n'est JAMAIS transmis à VIDAL. */}
          <div>
            <Libelle>Groupe de référence du DFG</Libelle>
            <select className="champ-saisie" value={groupeDfg?.id || ""} onChange={(e) => onChange({ groupeReferenceDfg: e.target.value })}>
              {groupesActifs.map((g) => <option key={g.id} value={g.id}>{g.libelle}</option>)}
            </select>
            <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginTop: 3 }}>Aide à l'interprétation, non transmise à VIDAL.</div>
          </div>
        </div>
        {interpretationDfg && (
          <div style={{ marginTop: 8, padding: "7px 10px", borderRadius: 8, fontSize: 12.5, background: interpretationDfg.fond, color: interpretationDfg.couleur, borderLeft: `3px solid ${interpretationDfg.couleur}` }}>
            <strong>{interpretationDfg.libelle}</strong> — DFG {c.glomerularFiltrationRate} (ml/min/1,73 m²) — référence {groupeDfg.valeur_normale} (ml/min/1,73 m²) — {String(interpretationDfg.pourcentage).replace(".", ",")} % de la référence
            <span style={{ color: "var(--vidal-gris-fonce)" }}> (aide visuelle, pas un diagnostic)</span>
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginTop: 8, fontSize: 11.5, color: "var(--vidal-gris-fonce)" }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={!!c.saisieManuelleRenale} onChange={(e) => onChange({ saisieManuelleRenale: e.target.checked })} />
            Saisie manuelle de la clairance et du DFG (résultat de laboratoire)
          </label>
          {!c.saisieManuelleRenale && c.avertissementRenal && <span style={{ color: "var(--vidal-orange)" }}>{c.avertissementRenal} Calcul local appliqué.</span>}
          {!c.saisieManuelleRenale && c.erreurRenal && <span style={{ color: "var(--vidal-rouge)" }}>{c.erreurRenal} — aucune valeur calculée localement.</span>}
          {!c.saisieManuelleRenale && c.creatin !== "" && (
            <span>
              {c.sourceRenale === "vidal" ? "Calculé par les calculateurs VIDAL" : "Calcul local (hors mode validation) : Cockcroft & Gault (clairance), CKD-EPI 2009 (DFG)"}
            </span>
          )}
          {!c.saisieManuelleRenale && c.creatinineSaisie !== "" && (!c.dateOfBirth || !c.weight || (c.gender !== "MALE" && c.gender !== "FEMALE")) && (
            <span style={{ color: "var(--vidal-orange)" }}>Date de naissance, sexe (Homme/Femme) et poids requis pour le calcul.</span>
          )}
        </div>
      </div>

      {/* § reproche VIDAL n°1 : données cliniques femme — bloc affiché
          seulement si Sexe = Femme ; pour tout autre sexe, ces données ne
          sont jamais transmises (neutralisées aussi côté serveur). */}
      {donneesFemmeAutorisees(c.gender) && (
        <div style={{ border: "1px solid rgba(236,72,153,0.3)", background: "rgba(236,72,153,0.05)", borderRadius: 10, padding: 12, marginBottom: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}><Baby size={14} /> Grossesse et allaitement</div>
          {!c.gender && <div style={{ fontSize: 11, color: "var(--vidal-gris)", marginBottom: 6 }}>Sexe non renseigné : à compléter si la patiente est enceinte ou allaite.</div>}

          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600, cursor: "pointer", marginBottom: 6 }}>
            <input type="checkbox" checked={!!c.grossesse} onChange={(e) => onChange({ grossesse: e.target.checked })} /> Grossesse en cours
          </label>
          {c.grossesse && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 10, alignItems: "start", marginBottom: 10 }}>
              <div>
                <Libelle>Date des dernières règles (jj/mm/aaaa)</Libelle>
                <input type="date" className="champ-saisie" max={aujourdhui} value={c.lastMenstrualPeriodDate}
                  onChange={(e) => changerDdr(e.target.value)} style={styleChamp(erreurs.lastMenstrualPeriodDate)} />
                <MessageErreur message={erreurs.lastMenstrualPeriodDate} />
              </div>
              <div style={{ alignSelf: "center", fontSize: 12, color: "var(--vidal-gris)", paddingTop: 16 }}>ou</div>
              <div>
                <Libelle>Semaines d'aménorrhée (SA)</Libelle>
                <input type="number" className="champ-saisie" min={BORNES.semaines_amenorrhee.min} max={BORNES.semaines_amenorrhee.max} step="1"
                  value={c.weeksOfAmenorrhea} onChange={(e) => changerSa(e.target.value)} style={styleChamp(erreurs.weeksOfAmenorrhea)}
                  placeholder={`${BORNES.semaines_amenorrhee.min} à ${BORNES.semaines_amenorrhee.max}`} />
                <MessageErreur message={erreurs.weeksOfAmenorrhea} />
                {!erreurs.weeksOfAmenorrhea && <MessageAvertissement message={avertissements.weeksOfAmenorrhea} />}
              </div>
              <div style={{ gridColumn: "1 / -1", fontSize: 10.5, color: "var(--vidal-gris)" }}>
                Conversion automatique : la date des dernières règles donne les SA révolues à la date du jour, et inversement.
              </div>
            </div>
          )}

          <div>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600, cursor: "pointer", marginBottom: 6 }}>
              <input type="checkbox" checked={!!c.allaitement} onChange={(e) => onChange({ allaitement: e.target.checked })} /> Allaitement en cours
            </label>
          </div>
          {c.allaitement && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 10, alignItems: "start" }}>
              <div>
                <Libelle>Date de début d'allaitement (jj/mm/aaaa)</Libelle>
                <input type="date" className="champ-saisie" max={aujourdhui} value={c.breastFeedingStartDate}
                  onChange={(e) => onChange({ breastFeedingStartDate: e.target.value })} style={styleChamp(erreurs.breastFeedingStartDate)} />
                <MessageErreur message={erreurs.breastFeedingStartDate} />
                {!erreurs.breastFeedingStartDate && <MessageAvertissement message={avertissements.breastFeedingStartDate} />}
              </div>
              <div style={{ alignSelf: "center", fontSize: 12, color: "var(--vidal-gris)", paddingTop: 16 }}>ou</div>
              <div>
                <Libelle>Durée approximative</Libelle>
                <select className="champ-saisie" value={categorieDeduite || c.dureeAllaitement} disabled={!!categorieDeduite}
                  onChange={(e) => onChange({ dureeAllaitement: e.target.value })} style={styleChamp(null, !!categorieDeduite)}>
                  {optionsDepuis(ALLAITEMENTS, ["ALL", "LESS_THAN_ONE_MONTH", "MORE_THAN_ONE_MONTH"]).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                {categorieDeduite && <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginTop: 3 }}>Déduite de la date de début.</div>}
              </div>
            </div>
          )}
        </div>
      )}

      {/* § MI VIDAL §5.1.2.2 : UN seul champ allergie, recherchant à la fois
          les classes d'allergie (en italique) et les substances/excipients ;
          chaque sélection est ensuite rangée dans <allergies> ou <molecules>
          selon sa référence. */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10 }}>
        <ChampTagsReferentiel label="Allergies et intolérances (classes en italique, substances, excipients)" kind="allergy"
          values={[...c.allergies, ...c.molecules]}
          onChange={(v) => onChange({
            allergies: v.filter((t) => !String(t.ref || "").startsWith("vidal://molecule/")),
            molecules: v.filter((t) => String(t.ref || "").startsWith("vidal://molecule/")),
          })} />
        <ChampTagsReferentiel label="Pathologies (CIM-10)" kind="pathology" values={c.pathologies} onChange={(v) => onChange({ pathologies: v })} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// État, import depuis la fiche patient, payloads
// ---------------------------------------------------------------------------
export function cliniqueVide() {
  return {
    dateOfBirth: "", gender: "", weight: "", height: "", weightDate: "",
    hepaticInsufficiency: "",
    grossesse: false, lastMenstrualPeriodDate: "", weeksOfAmenorrhea: "",
    allaitement: false, breastFeedingStartDate: "", dureeAllaitement: "ALL",
    creatinineSaisie: "", creatinineUnite: "umol_l", creatin: "", glomerularFiltrationRate: "", renalDate: "",
    saisieManuelleRenale: false, creatinCalculee: null, plafonnee: false, sourceRenale: null, calculRenalEnCours: false,
    insuffisanceRenale: null, stadeKdigo: null, groupeReferenceDfg: "",
    allergies: [], molecules: [], pathologies: [],
  };
}

function texteNombre(v) {
  return v == null ? "" : String(v);
}

/** Ancien profil d'un patient enregistré avant le lot 56 (`profile`) -> clés du profil clinique (rien d'inventé). */
function profilDepuisAncienFormat(ancien) {
  const a = ancien || {};
  return {
    date_naissance: a.dateOfBirth || null, sexe: ["MALE", "FEMALE", "UNKNOWN"].includes(a.gender) ? a.gender : null,
    poids_kg: a.weight || null, taille_cm: a.height || null, derniere_creatininemie_umol_l: a.creatinine || null,
    insuffisance_hepatique: a.hepaticInsufficiency || null,
    allergies: a.allergies || [], molecules_a_eviter: a.molecules || [], pathologies: a.pathologies || [],
  };
}

/**
 * Importe le profil clinique d'un patient enregistré (`vidal_patients`) :
 * sous-document `profil_clinique`, ou ancien `profile`. Les SA sont
 * recalculées à la date du jour (jamais figées).
 */
export function cliniqueDepuisPatient(p) {
  const pc = p?.profil_clinique || profilDepuisAncienFormat(p?.profile);
  const ddr = formatDateISO(pc.date_dernieres_regles);
  const sa = ddr ? saDepuisDdr(ddr) : null;
  const grossesseEnCours = sa != null && sa >= BORNES.semaines_amenorrhee.min && sa <= BORNES.semaines_amenorrhee.max;
  const allaitement = pc.allaitement && pc.allaitement !== "NONE";
  const creat = pc.derniere_creatininemie_umol_l;
  // Clairance/DFG enregistrés SANS créatininémie : saisie manuelle (résultat de laboratoire).
  const manuel = creat == null && (pc.clairance_creatinine_ml_min != null || pc.dfg_ml_min_173 != null);
  return {
    ...cliniqueVide(),
    dateOfBirth: formatDateISO(pc.date_naissance),
    gender: pc.sexe || "",
    weight: texteNombre(pc.poids_kg), height: texteNombre(pc.taille_cm), weightDate: formatDateISO(pc.date_saisie_poids_taille),
    hepaticInsufficiency: pc.insuffisance_hepatique || "",
    grossesse: grossesseEnCours, lastMenstrualPeriodDate: grossesseEnCours ? ddr : "", weeksOfAmenorrhea: grossesseEnCours ? String(sa) : "",
    allaitement: !!allaitement, breastFeedingStartDate: allaitement ? formatDateISO(pc.date_debut_allaitement) : "",
    dureeAllaitement: allaitement && !pc.date_debut_allaitement ? pc.allaitement : "ALL",
    creatinineSaisie: texteNombre(creat), renalDate: formatDateISO(pc.date_bilan_renal),
    creatin: manuel && pc.clairance_creatinine_ml_min != null ? String(Math.round(pc.clairance_creatinine_ml_min)) : "",
    glomerularFiltrationRate: manuel ? texteNombre(pc.dfg_ml_min_173) : "",
    saisieManuelleRenale: manuel, groupeReferenceDfg: pc.groupe_reference_dfg || "",
    allergies: pc.allergies || [], molecules: pc.molecules_a_eviter || [], pathologies: pc.pathologies || [],
  };
}

function nombre(v) {
  if (v === "" || v == null) return null;
  const n = Number(String(v).replace(",", "."));
  return Number.isNaN(n) ? null : n;
}

/** Créatininémie saisie, toujours exprimée en µmol/L (2 décimales). */
export function creatininemieUmol(c) {
  const v = nombre(c.creatinineSaisie);
  if (v == null) return null;
  return arrondi2(c.creatinineUnite === "mg_dl" ? mgDlVersUmolL(v) : v);
}

/**
 * État clinique -> bloc `patient` du payload /vidal/securisation/analyze
 * (noms des balises VIDAL). § Le groupe de référence du DFG n'y figure
 * JAMAIS : c'est une aide d'interprétation locale.
 */
export function patientPourVidal(c) {
  const femme = donneesFemmeAutorisees(c.gender);
  const debutAllaitement = femme && c.allaitement ? c.breastFeedingStartDate || null : null;
  return {
    dateOfBirth: c.dateOfBirth || null, gender: c.gender || null,
    weight: nombre(c.weight), height: nombre(c.height), weightDate: c.weight || c.height ? c.weightDate || null : null,
    breastFeeding: femme ? (c.allaitement ? (debutAllaitement ? categorieAllaitementDepuisDate(debutAllaitement) : c.dureeAllaitement || "ALL") : "NONE") : null,
    breastFeedingStartDate: debutAllaitement,
    weeksOfAmenorrhea: femme && c.grossesse ? nombre(c.weeksOfAmenorrhea) : null,
    lastMenstrualPeriodDate: femme && c.grossesse ? c.lastMenstrualPeriodDate || null : null,
    creatin: nombre(c.creatin), serumCreatinine: creatininemieUmol(c), glomerularFiltrationRate: nombre(c.glomerularFiltrationRate),
    renalDate: c.renalDate || null,
    hepaticInsufficiency: c.hepaticInsufficiency || null,
    allergies: c.allergies, molecules: c.molecules, pathologies: c.pathologies,
  };
}

/** État clinique -> profil clinique du patient (PUT /vidal/patients/{id}/profil-clinique ; null explicite = effacer). */
export function profilPourFichePatient(c) {
  const femme = donneesFemmeAutorisees(c.gender);
  const debutAllaitement = femme && c.allaitement ? c.breastFeedingStartDate || null : null;
  return {
    // (SAWALI) date de naissance et sexe font partie du profil clinique (pas de fiche d'identité séparée).
    date_naissance: c.dateOfBirth || null, sexe: c.gender || null,
    poids_kg: nombre(c.weight), taille_cm: nombre(c.height),
    date_saisie_poids_taille: c.weightDate || null,
    insuffisance_hepatique: c.hepaticInsufficiency || null,
    derniere_creatininemie_umol_l: creatininemieUmol(c),
    clairance_creatinine_ml_min: nombre(c.creatin),
    dfg_ml_min_173: nombre(c.glomerularFiltrationRate),
    date_bilan_renal: c.renalDate || null,
    date_dernieres_regles: femme && c.grossesse ? c.lastMenstrualPeriodDate || null : null,
    allaitement: femme && c.allaitement ? (debutAllaitement ? categorieAllaitementDepuisDate(debutAllaitement) : c.dureeAllaitement || "ALL") : null,
    date_debut_allaitement: debutAllaitement,
    allergies: c.allergies, pathologies: c.pathologies, molecules_a_eviter: c.molecules,
    groupe_reference_dfg: c.groupeReferenceDfg || null,
  };
}
