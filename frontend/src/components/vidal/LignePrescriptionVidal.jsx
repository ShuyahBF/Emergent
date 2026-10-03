// components/vidal/LignePrescriptionVidal.jsx
// -----------------------------------------------
// § Revue d'implémentation VIDAL (reproche n°3 : "listes déroulantes dès
// que les valeurs sont finies, contrôles de saisie") — une ligne de
// prescription STRUCTURÉE, conforme à <prescription-line> :
//   - médicament (recherche VIDAL filtrable par forme galénique, ex. "comp")
//     et type (PRODUCT, VMP, ...) ;
//   - dose décimale > 0 + unité de prise (liste /product/{id}/units) ;
//     le libellé suit l'unité choisie : "Dose (comprimé)" ;
//   - fréquence (liste), durée ENTIÈRE ≥ 1 + unité de durée (liste) ; le
//     libellé suit l'unité : "Durée (jours)" ;
//   - voie (liste /product/{id}/routes) et indication (liste
//     /product/{id}/indications) ;
//   - période (début ≤ fin ; fin calculée depuis la durée tant qu'elle
//     n'est pas saisie à la main), statut, groupe (perfusion), ALD + code ;
//   - intervalles entre prises (<dosages>) : min ≤ max, unité en liste.
// § MI VIDAL (2025.12 REV 03) : listes lues sur la ressource du type
// prescrit (/product, /package, /ucd, /vmp), voies triées par rang VIDAL
// avec les voies hors AMM signalées (non sécurisées), formes galéniques
// du référentiel /galenic-forms, spécialités non sécurisées signalées,
// indicateurs "données patient utilisées", <dose> = dose par 24 h liée à
// la fréquence (dose par prise + intervalle pour des prises espacées de
// plus de 24 h), code ALD recherché dans /alds.
// L'état est porté par le parent ; `ligneVide` / `ligneDepuis...` en bas
// de fichier créent cet état.

import { useEffect, useState } from "react";
import { X, Loader2, Plus, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { apiClient as api } from "@/lib/api";
import VidalMedicationSearch from "@/components/VidalMedicationSearch";
import { Libelle, MessageErreur } from "./DonneesCliniquesPatient";
import { chargerEtatValidation } from "./BandeauValidationVidal";
// Lot 56.4 — champs numériques « spin » (flèches, jamais négatifs).
import ChampNombre from "./ChampNombre";
import {
  TYPES_DUREE, TYPES_FREQUENCE, TYPES_MEDICAMENT, STATUTS_LIGNE, TYPES_GROUPE, UNITES_INTERVALLE, ORDRE_UNITES_INTERVALLE,
  FORMES_GALENIQUES, BORNES, INDICATEURS_DONNEES_PATIENT, TYPES_AVEC_LISTES, optionsDepuis,
  libelleChampDose, libelleChampDoseParPrise, libelleChampDuree, libelleChampIntervalle,
} from "@/lib/vidalReferentiels";

const STYLE_CALCULE = { background: "var(--vidal-gris-clair)", color: "var(--vidal-gris-fonce)" };
function styleChamp(erreur, calcule) {
  return { fontSize: 12.5, ...(calcule ? STYLE_CALCULE : {}), ...(erreur ? { borderColor: "var(--vidal-rouge)" } : {}) };
}

/**
 * Charge en parallèle les 4 listes propres au médicament (unités, voies,
 * indications, indicateurs) sur la ressource de SON type (MI §6.3) — une
 * liste en échec reste vide, jamais bloquant.
 */
export async function chargerListesProduit(vidalId, drugType = "PRODUCT") {
  const vides = { units: [], routes: [], indications: [], indicateurs: [] };
  if (!TYPES_AVEC_LISTES.includes(drugType)) return vides;
  const url = (liste) => `/vidal/medicament/${drugType}/${vidalId}/${liste}`;
  const [unites, voies, indications, indicateurs] = await Promise.allSettled([
    api.get(url("units")), api.get(url("routes")), api.get(url("indications")), api.get(url("indicators")),
  ]);
  const lire = (r, cle) => (r.status === "fulfilled" ? r.value.data?.[cle] || [] : []);
  return {
    units: lire(unites, "units"),
    routes: lire(voies, "routes").filter((r) => r.id),
    indications: lire(indications, "indications"),
    // § seuls les indicateurs "données patient utilisées" (âge, poids...) servent ici.
    indicateurs: lire(indicateurs, "indicators").filter((i) => INDICATEURS_DONNEES_PATIENT[i.id]),
  };
}

/** Applique les listes chargées à une ligne — § aucune présélection : unité et voie sont toujours choisies par le médecin. */
export function appliquerListes(ligne, listes) {
  const patch = { ...listes, listesChargees: true, chargementListes: false };
  if (ligne.unitId && !ligne.unitLabel) patch.unitLabel = listes.units.find((u) => u.id === ligne.unitId)?.label || "";
  return patch;
}

// § référentiel des formes galéniques VIDAL (/galenic-forms), chargé une fois ;
// repli sur la liste documentée d'abréviations si l'API ne répond pas.
let promesseFormes = null;
function chargerFormesGaleniques() {
  if (!promesseFormes) {
    promesseFormes = api.get("/vidal/formes-galeniques").then((r) => r.data?.formes || []).catch(() => []);
  }
  return promesseFormes;
}

export default function LignePrescriptionVidal({ ligne, onChange, onRetirer, erreurs = {}, estTraitementEnCours = false }) {
  const [intervallesOuverts, setIntervallesOuverts] = useState((ligne.dosages || []).length > 0);
  const [formesApi, setFormesApi] = useState([]);
  const [aldsProposees, setAldsProposees] = useState([]);
  const [modeValidation, setModeValidation] = useState(null);
  useEffect(() => { chargerEtatValidation().then((e) => setModeValidation(e ? !!e.mode_validation : true)); }, []);
  useEffect(() => {
    let actif = true;
    chargerFormesGaleniques().then((formes) => { if (actif) setFormesApi(formes); });
    return () => { actif = false; };
  }, []);

  // § ligne pré-remplie (ordonnance, traitement en cours) : les listes du
  // produit sont chargées à l'affichage, pour que unité/voie/indication
  // restent choisies dans des listes déroulantes.
  useEffect(() => {
    if (!ligne.vidal_id || ligne.listesChargees || ligne.chargementListes) return undefined;
    let annule = false;
    onChange({ chargementListes: true });
    chargerListesProduit(ligne.vidal_id, ligne.drugType || "PRODUCT").then((listes) => { if (!annule) onChange(appliquerListes(ligne, listes)); });
    return () => { annule = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ligne.vidal_id, ligne.drugType, ligne.listesChargees]);

  async function selectionnerMedicament(item) {
    const base = {
      vidal_id: item.vidal_id || "", label: item.title || "", query: "", drugType: "PRODUCT",
      unitId: "", unitLabel: "", units: [], route: "", routes: [], indication: "", indications: [], indicateurs: [], listesChargees: false,
      // § MI §6.4.2 : <vidal:safetyAlert>false</...> = spécialité non sécurisée par VIDAL.
      nonSecurise: item.safety_alert === false,
    };
    onChange({ ...base, chargementListes: !!item.vidal_id });
    if (!item.vidal_id) return;
    const listes = await chargerListesProduit(item.vidal_id, "PRODUCT");
    onChange(appliquerListes(base, listes));
  }

  async function rechercherAld(texte) {
    onChange({ aldCode: texte });
    if (texte.trim().length < 2 || /^\d{1,3}$/.test(texte.trim())) return;
    try {
      const r = await api.get("/vidal/referential/search", { params: { kind: "ald", q: texte.trim() } });
      setAldsProposees(r.data?.results || []);
    } catch {
      setAldsProposees([]);
    }
  }

  // § aucune date de fin devinée : la période n'est transmise que si le
  // médecin la saisit (la durée et son unité suffisent à VIDAL).
  function majAvecFin(patch) {
    onChange(patch);
  }
  function majDosage(i, patch) {
    onChange({ dosages: ligne.dosages.map((d, j) => (j === i ? { ...d, ...patch } : d)) });
  }

  const optionsGroupe = estTraitementEnCours
    ? optionsDepuis(TYPES_GROUPE, ["PREVIOUS_ORDER"])
    : optionsDepuis(TYPES_GROUPE, ["SAME_ORDER", "INFUSION"]);

  return (
    <div style={{ border: "1px solid var(--vidal-bordure)", borderRadius: 10, padding: 12, marginBottom: 8 }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(130px, 170px) 1fr minmax(150px, 190px) auto", gap: 8, alignItems: "end", marginBottom: 8 }}>
        <div>
          <Libelle>Forme recherchée</Libelle>
          <select className="champ-saisie" style={{ fontSize: 12.5 }} value={ligne.forme || ""} onChange={(e) => onChange({ forme: e.target.value })}>
            <option value="">Toutes les formes</option>
            {formesApi.length > 0
              ? formesApi.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)
              // § repli sur la liste documentée d'abréviations HORS mode validation uniquement.
              : modeValidation === false ? optionsDepuis(FORMES_GALENIQUES).map((o) => <option key={o.value} value={o.value}>{o.label}</option>) : null}
          </select>
        </div>
        <div>
          <Libelle obligatoire>Médicament</Libelle>
          <VidalMedicationSearch
            query={ligne.label || ligne.query}
            forme={ligne.forme || null}
            rechercheAutomatique={!!ligne.rechercheAuto && !ligne.vidal_id}
            onQueryChange={(q) => onChange({ query: q, label: "", vidal_id: "", units: [], unitId: "", unitLabel: "", routes: [], route: "", indications: [], indication: "", listesChargees: false })}
            onSelect={selectionnerMedicament}
            onClear={() => onChange({ query: "", label: "", vidal_id: "", units: [], unitId: "", unitLabel: "", routes: [], route: "", indications: [], indication: "", listesChargees: false })}
          />
          <MessageErreur message={erreurs.medicament} />
        </div>
        <div>
          <Libelle>Type de médicament</Libelle>
          <select className="champ-saisie" style={{ fontSize: 12.5 }} value={ligne.drugType || "PRODUCT"}
            onChange={(e) => onChange({ drugType: e.target.value, units: [], unitId: "", unitLabel: "", routes: [], route: "", indications: [], indication: "", indicateurs: [], listesChargees: false, chargementListes: false })}>
            {optionsDepuis(TYPES_MEDICAMENT).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        {onRetirer ? (
          <button onClick={onRetirer} title="Retirer cette ligne" style={{ border: "none", background: "none", color: "var(--vidal-rouge)", cursor: "pointer", display: "flex", padding: "8px 4px" }}><X size={16} /></button>
        ) : <span />}
      </div>

      {ligne.nonSecurise && (
        <div style={{ fontSize: 12, color: "var(--vidal-orange)", display: "flex", alignItems: "center", gap: 5, marginBottom: 6 }}>
          <AlertTriangle size={13} /> Spécialité non sécurisée par VIDAL : aucune alerte ne sera calculée pour elle — cela ne signifie pas l'absence de risque.
        </div>
      )}
      {ligne.indicateurs?.length > 0 && (
        <div style={{ fontSize: 11.5, color: "var(--vidal-gris-fonce)", marginBottom: 6 }}>
          Données patient utilisées par VIDAL pour ce médicament : {ligne.indicateurs.map((i) => INDICATEURS_DONNEES_PATIENT[i.id]).join(", ")}
        </div>
      )}
      {ligne.chargementListes && (
        <div style={{ fontSize: 11.5, color: "var(--vidal-gris)", display: "flex", alignItems: "center", gap: 5, marginBottom: 6 }}>
          <Loader2 size={12} className="lucide-tourne" /> Chargement des unités, voies et indications VIDAL…
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8, marginBottom: 8 }}>
        <div>
          <Libelle>{libelleChampDose(ligne.unitLabel, ligne.frequencyType)}</Libelle>
          <ChampNombre className="champ-saisie" min="0" step="0.5" max={BORNES.dose.max} value={ligne.dose}
            onChange={(e) => onChange({ dose: e.target.value })} style={styleChamp(erreurs.dose)} placeholder={ligne.unitLabel || "Quantité"} />
          <MessageErreur message={erreurs.dose} />
        </div>
        <div>
          <Libelle>Unité de prise</Libelle>
          <select className="champ-saisie" value={ligne.unitId} disabled={!ligne.units?.length} style={styleChamp(erreurs.unitId)}
            onChange={(e) => onChange({ unitId: e.target.value, unitLabel: ligne.units.find((u) => u.id === e.target.value)?.label || "" })}>
            <option value="">{ligne.units?.length ? "Choisir…" : "—"}</option>
            {(ligne.units || []).map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
          </select>
          <MessageErreur message={erreurs.unitId} />
        </div>
        <div>
          <Libelle>Fréquence</Libelle>
          <select className="champ-saisie" value={ligne.frequencyType} onChange={(e) => onChange({ frequencyType: e.target.value })} style={styleChamp(erreurs.frequencyType)}>
            <option value="">Aucune (prises espacées de plus de 24 h)</option>
            {optionsDepuis(TYPES_FREQUENCE).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <MessageErreur message={erreurs.frequencyType} />
        </div>
        <div>
          <Libelle>{libelleChampDuree(ligne.durationType)}</Libelle>
          <ChampNombre className="champ-saisie" min={BORNES.duree.min} max={BORNES.duree.max} step="1" value={ligne.duration}
            onChange={(e) => majAvecFin({ duration: e.target.value })} style={styleChamp(erreurs.duration)} placeholder="Nombre entier" />
          <MessageErreur message={erreurs.duration} />
        </div>
        <div>
          <Libelle>Unité de durée</Libelle>
          <select className="champ-saisie" value={ligne.durationType} onChange={(e) => majAvecFin({ durationType: e.target.value })} style={styleChamp(erreurs.durationType)}>
            <option value="">Choisir…</option>
            {optionsDepuis(TYPES_DUREE).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <MessageErreur message={erreurs.durationType} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8, marginBottom: 8 }}>
        <div>
          <Libelle>Voie d'administration</Libelle>
          <select className="champ-saisie" style={{ fontSize: 12.5 }} value={ligne.route} onChange={(e) => onChange({ route: e.target.value })} disabled={!ligne.routes?.length}>
            <option value="">{ligne.routes?.length ? "Choisir…" : "—"}</option>
            {(ligne.routes || []).map((r) => <option key={r.id} value={r.id}>{r.label}{r.hors_amm ? " (hors AMM — non sécurisée)" : ""}</option>)}
          </select>
          {(ligne.routes || []).find((r) => r.id === ligne.route)?.hors_amm && (
            <div style={{ fontSize: 11, color: "var(--vidal-orange)", marginTop: 3 }}>Voie hors AMM : VIDAL signalera une posologie impossible à vérifier.</div>
          )}
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <Libelle>Indication</Libelle>
          <select className="champ-saisie" style={{ fontSize: 12.5 }} value={ligne.indication} onChange={(e) => onChange({ indication: e.target.value })} disabled={!ligne.indications?.length}>
            <option value="">{ligne.indications?.length ? "Choisir…" : "—"}</option>
            {(ligne.indications || []).map((ind) => <option key={ind.ref} value={ind.ref}>{ind.label}</option>)}
          </select>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8, alignItems: "start" }}>
        <div>
          <Libelle>Début (jj/mm/aaaa)</Libelle>
          <input type="date" className="champ-saisie" style={{ fontSize: 12.5 }} value={ligne.startDate} onChange={(e) => majAvecFin({ startDate: e.target.value })} />
        </div>
        <div>
          <Libelle>Fin (jj/mm/aaaa)</Libelle>
          <input type="date" className="champ-saisie" min={ligne.startDate || undefined} value={ligne.endDate}
            onChange={(e) => onChange({ endDate: e.target.value, finManuelle: !!e.target.value })}
            style={styleChamp(erreurs.endDate)} title="Facultative : saisie par le médecin" />
          <MessageErreur message={erreurs.endDate} />
        </div>
        <div>
          <Libelle>Statut</Libelle>
          <select className="champ-saisie" style={{ fontSize: 12.5 }} value={ligne.status} onChange={(e) => onChange({ status: e.target.value })}>
            {optionsDepuis(STATUTS_LIGNE).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <Libelle>Groupe</Libelle>
          <select className="champ-saisie" style={{ fontSize: 12.5 }} value={estTraitementEnCours ? "PREVIOUS_ORDER" : ligne.groupType} disabled={estTraitementEnCours}
            onChange={(e) => onChange({ groupType: e.target.value })}>
            {optionsGroupe.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, marginBottom: 3, cursor: "pointer" }}>
            <input type="checkbox" checked={!!ligne.ald} onChange={(e) => onChange({ ald: e.target.checked, aldCode: e.target.checked ? ligne.aldCode : "" })} />
            Prise en charge ALD
          </label>
          <input className="champ-saisie" value={ligne.aldCode} disabled={!ligne.ald} maxLength={BORNES.code_ald_longueur_max}
            list={`ald-${ligne.vidal_id || "ligne"}`} onChange={(e) => rechercherAld(e.target.value)}
            style={styleChamp(erreurs.aldCode, !ligne.ald)} placeholder="Code ou libellé ALD" />
          <datalist id={`ald-${ligne.vidal_id || "ligne"}`}>
            {aldsProposees.filter((a) => a.code).map((a) => <option key={a.ref} value={a.code}>{a.label}</option>)}
          </datalist>
          <MessageErreur message={erreurs.aldCode} />
        </div>
      </div>

      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 10.5, color: "var(--vidal-gris)", marginBottom: 4 }}>
          Prises quotidiennes : dose par 24 h + fréquence, et dose par prise + intervalle minimum ci-dessous. Prises espacées de plus de 24 h : laissez la dose par 24 h vide, saisissez seulement dose par prise et intervalle.
        </div>
        <button type="button" onClick={() => setIntervallesOuverts(!intervallesOuverts)}
          style={{ border: "none", background: "none", padding: 0, cursor: "pointer", fontSize: 12, fontWeight: 600, color: "var(--vidal-bleu)", display: "inline-flex", alignItems: "center", gap: 4 }}>
          {intervallesOuverts ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Intervalles entre les prises ({(ligne.dosages || []).length})
        </button>
        {intervallesOuverts && (
          <div style={{ marginTop: 6 }}>
            {(ligne.dosages || []).map((d, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(110px, 1fr)) auto", gap: 8, alignItems: "start", marginBottom: 6 }}>
                <div>
                  <Libelle>{libelleChampDoseParPrise(ligne.unitLabel)}</Libelle>
                  <ChampNombre className="champ-saisie" min="0" step="0.5" value={d.dose} onChange={(e) => majDosage(i, { dose: e.target.value })} style={styleChamp(erreurs[`dosages.${i}.dose`])} />
                  <MessageErreur message={erreurs[`dosages.${i}.dose`]} />
                </div>
                <div>
                  <Libelle>{libelleChampIntervalle("Intervalle min.", d.intervalUnitId)}</Libelle>
                  <ChampNombre className="champ-saisie" min="0" step="0.5" value={d.intervalMin} onChange={(e) => majDosage(i, { intervalMin: e.target.value })} style={styleChamp(erreurs[`dosages.${i}.intervalMin`])} />
                  <MessageErreur message={erreurs[`dosages.${i}.intervalMin`]} />
                </div>
                <div>
                  <Libelle>{libelleChampIntervalle("Intervalle max.", d.intervalUnitId)}</Libelle>
                  <ChampNombre className="champ-saisie" min="0" step="0.5" value={d.intervalMax} onChange={(e) => majDosage(i, { intervalMax: e.target.value })} style={styleChamp(erreurs[`dosages.${i}.intervalMax`])} />
                  <MessageErreur message={erreurs[`dosages.${i}.intervalMax`]} />
                </div>
                <div>
                  <Libelle>Unité d'intervalle</Libelle>
                  <select className="champ-saisie" value={d.intervalUnitId} onChange={(e) => majDosage(i, { intervalUnitId: e.target.value })} style={styleChamp(erreurs[`dosages.${i}.intervalUnitId`])}>
                    <option value="">Choisir…</option>
                    {optionsDepuis(UNITES_INTERVALLE, ORDRE_UNITES_INTERVALLE).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                  <MessageErreur message={erreurs[`dosages.${i}.intervalUnitId`]} />
                </div>
                <button onClick={() => onChange({ dosages: ligne.dosages.filter((_, j) => j !== i) })} title="Retirer cet intervalle"
                  style={{ border: "none", background: "none", color: "var(--vidal-rouge)", cursor: "pointer", display: "flex", padding: "26px 4px 0" }}><X size={14} /></button>
              </div>
            ))}
            <button type="button" className="bouton-secondaire" style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }}
              onClick={() => onChange({ dosages: [...(ligne.dosages || []), { dose: "", intervalMin: "", intervalMax: "", intervalUnitId: "" }] })}>
              <Plus size={12} /> Ajouter un intervalle de prise
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// États de ligne
// ---------------------------------------------------------------------------
export function ligneVide(groupType = "SAME_ORDER") {
  return {
    vidal_id: "", label: "", query: "", forme: "", drugType: "PRODUCT",
    dose: "", unitId: "", unitLabel: "", units: [],
    // § aucune valeur par défaut susceptible de partir chez VIDAL : fréquence,
    // unité de durée et date de début sont choisies par le médecin.
    frequencyType: "", duration: "", durationType: "",
    route: "", routes: [], indication: "", indications: [],
    startDate: "", endDate: "", finManuelle: false,
    status: "ACTIVE", groupType, ald: false, aldCode: "", dosages: [],
    listesChargees: false, chargementListes: false, indicateurs: [], nonSecurise: false,
  };
}

/** Ligne de la nouvelle prescription pré-remplie depuis une ligne d'ordonnance (désignation + durée texte "7 jours"). */
export function ligneDepuisOrdonnance(ligneOrdonnance) {
  const deja = ligneOrdonnance.donnees_vidal || {};
  const ligne = { ...ligneVide(), vidal_id: ligneOrdonnance.vidal_id || "", label: ligneOrdonnance.designation || "" };
  const m = /(\d+)\s*(j|jours?|sem|semaines?|mois)\b/i.exec(ligneOrdonnance.duree || "");
  if (m) {
    ligne.duration = m[1];
    ligne.durationType = /^j/i.test(m[2]) ? "DAY" : /^s/i.test(m[2]) ? "WEEK" : "MONTH";
  }
  return versEtatLigne({ ...ligne, ...versChampsLigne(deja) });
}

/** Traitement en cours renvoyé par le backend -> état de ligne (groupe PREVIOUS_ORDER). */
export function ligneDepuisTraitement(t) {
  // § validation VIDAL : ligne d'ordonnance fictive à rapprocher -> nom pré-rempli, recherche lancée à l'ouverture.
  const aRapprocher = !!t.a_rapprocher;
  return versEtatLigne({
    ...ligneVide("PREVIOUS_ORDER"), ...versChampsLigne(t),
    vidal_id: t.drugRef || "", label: aRapprocher ? "" : t.label || "", query: aRapprocher ? t.recherche_vidal || "" : "",
    rechercheAuto: aRapprocher && !(t.candidats_vidal || []).length, aRapprocher, candidatsVidal: t.candidats_vidal || [],
    designationOrdonnance: t.label, inclus: !!t.coche_par_defaut,
    ordonnance_reference: t.ordonnance_reference, date_ordonnance: t.date_ordonnance, duree_connue: t.duree_connue, duree_texte: t.duree_texte,
    finManuelle: !!t.endDate,
  });
}

function versChampsLigne(d) {
  const champs = {};
  const texte = (v) => (v == null ? undefined : String(v));
  if (d.drugType) champs.drugType = d.drugType;
  if (d.dose != null) champs.dose = texte(d.dose);
  if (d.unitId) { champs.unitId = texte(d.unitId); champs.unitLabel = d.unitLabel || ""; }
  if (d.duration != null) champs.duration = texte(d.duration);
  if (d.durationType) champs.durationType = d.durationType;
  if (d.frequencyType) champs.frequencyType = d.frequencyType;
  if (d.route) champs.route = texte(d.route);
  if (d.indication) champs.indication = d.indication;
  if (d.startDate) champs.startDate = String(d.startDate).slice(0, 10);
  if (d.endDate) { champs.endDate = String(d.endDate).slice(0, 10); champs.finManuelle = true; }
  if (d.ald) { champs.ald = true; champs.aldCode = d.aldCode || ""; }
  if (Array.isArray(d.dosages)) {
    champs.dosages = d.dosages.map((x) => ({ dose: texte(x.dose) ?? "", intervalMin: texte(x.intervalMin) ?? "", intervalMax: texte(x.intervalMax) ?? "", intervalUnitId: texte(x.intervalUnitId) || "" }));
  }
  return champs;
}

function versEtatLigne(l) {
  return l;
}
