// Iter43-fix24az-ac (2026-07-22) — Standalone Prescription Analysis page.
// Extracted from Vidal.jsx (AnalyzeTab) so médecins can access it directly
// via sidebar link `/portal/prescription-analysis` without needing the
// Search/Catalogue tabs.
//
// The internal Vidal tab still re-uses this component so behavior remains
// identical between the standalone page and the Vidal tab.
import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
// Lot 56.1 — même garde-fou que la Sécurisation VIDAL v2 : bandeau du mode validation
import "@/components/vidal/vidalV2.css";
import BandeauValidationVidal, { chargerEtatValidation } from "@/components/vidal/BandeauValidationVidal";
import { AlertTriangle, Loader2, Plus, X, RotateCcw } from "lucide-react";
import VidalMedicationSearch from "@/components/VidalMedicationSearch";
// Lot 56.4 — listes au lieu de saisie libre, champs « spin », chronomètre de saisie :
// mêmes composants et mêmes référentiels que la Sécurisation VIDAL.
import ChampTagsReferentiel from "@/components/vidal/ChampTagsReferentiel";
import ChampNombre from "@/components/vidal/ChampNombre";
import ChronoSaisie, { useChronoSaisie } from "@/components/vidal/ChronoSaisie";
import { appliquerListes, chargerListesProduit, nouvelleLigneSaisie } from "@/components/vidal/LignePrescriptionVidal";
import {
  BORNES, TYPES_DUREE, TYPES_FREQUENCE, libelleChampDose, libelleChampDuree, optionsDepuis, validerLigne, versPayloadLigne,
} from "@/lib/vidalReferentiels";

// Lot 56.4 — préfixe des références VIDAL d'une molécule / d'un excipient : une
// allergie choisie dans la liste est rangée dans <allergies> ou <molecules>
// selon sa référence (même règle que la Sécurisation, MI VIDAL §5.1.2.2).
const PREFIXE_MOLECULE = "vidal://molecule/";

/**
 * Lot 56.4 — nouvelle ligne de posologie STRUCTURÉE (plus de texte libre).
 * Lot 56.5 — même fonction que la Sécurisation (`nouvelleLigneSaisie`) :
 * fréquence « Par jour », durée en « Jour(s) » ; dose et durée restent à saisir.
 */
const nouvelleLigne = nouvelleLigneSaisie;

/** Étiquette du profil clinique d'un patient fictif -> {label, ref}. */
function versEtiquette(x) {
  if (!x) return null;
  if (typeof x === "string") return { label: x, ref: null };
  const label = x.label || x.libelle || x.name || "";
  return label || x.ref ? { label: label || x.ref, ref: x.ref || null } : null;
}

/** Recherche de médicaments VIDAL pour le champ « Molécules / traitements en cours ». */
async function rechercherMedicaments(q) {
  const r = await apiClient.get("/vidal/search/parsed", { params: { q } });
  return (r.data?.results || [])
    .filter((m) => m.vidal_id)
    .map((m) => ({ label: m.title, ref: String(m.vidal_id), type: "PRODUCT" }));
}

export function PrescriptionAnalysisForm() {
  const [patient, setPatient] = useState({ birth_date: "", sex: "F", weight_kg: "", creatinine_clearance_ml_min: "" });
  // Lot 56.2 — mode « Validation VIDAL » : état de l'établissement, patients fictifs
  // de l'utilisateur et patient fictif choisi ("" = saisie anonymisée).
  const [validation, setValidation] = useState(false);
  const [patientsFictifs, setPatientsFictifs] = useState([]);
  const [patientFictifId, setPatientFictifId] = useState("");
  const [transmis, setTransmis] = useState(null); // ce que le serveur a réellement envoyé à VIDAL
  const [erreursSaisie, setErreursSaisie] = useState([]); // lot 56.3 — erreurs {champ, message} renvoyées par le serveur

  // Lot 56.4 — lignes de prescription STRUCTURÉES : médicament VIDAL, dose (nombre),
  // unité (liste du produit), fréquence (liste), durée (nombre) + unité de durée (liste), voie (liste).
  const [prescriptions, setPrescriptions] = useState([nouvelleLigne()]);
  // Lot 56.4 — étiquettes choisies dans les référentiels VIDAL ({label, ref}).
  const [allergies, setAllergies] = useState([]); // classes d'allergie + molécules / excipients
  const [pathologies, setPathologies] = useState([]); // CIM-10
  const [traitements, setTraitements] = useState([]); // médicaments déjà pris (traitements en cours)
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [errorState, setErrorState] = useState(null);
  // Lot 56.4 — erreurs de saisie détectées AVANT l'envoi (mêmes règles que le serveur), par ligne.
  const [erreursLignes, setErreursLignes] = useState([]);

  // Lot 56.4 — chronomètre de saisie (mode validation uniquement) : la « signature »
  // résume les données cliniques et la prescription ; toute variation = une modification.
  const signatureSaisie = useMemo(() => JSON.stringify({
    patient, patientFictifId, allergies, pathologies, traitements,
    lignes: prescriptions.map((l) => [l.vidal_id, l.query, l.dose, l.unitId, l.frequencyType, l.duration, l.durationType, l.route]),
  }), [patient, patientFictifId, allergies, pathologies, traitements, prescriptions]);
  const chrono = useChronoSaisie(signatureSaisie);

  // Lot 56.5 — « Nouvelle saisie » : formulaire vidé (patient, données cliniques,
  // prescription, résultat) et chronomètre remis à zéro, en attente de la première saisie.
  const nouvelleSaisie = () => {
    const patientVide = { birth_date: "", sex: "F", weight_kg: "", creatinine_clearance_ml_min: "" };
    const lignes = [nouvelleLigne()];
    setPatient(patientVide); setPatientFictifId("");
    setAllergies([]); setPathologies([]); setTraitements([]); setPrescriptions(lignes);
    setResult(null); setErrorState(null); setErreursSaisie([]); setErreursLignes([]); setTransmis(null);
    chrono.reinitialiser(JSON.stringify({
      patient: patientVide, patientFictifId: "", allergies: [], pathologies: [], traitements: [],
      lignes: lignes.map((l) => [l.vidal_id, l.query, l.dose, l.unitId, l.frequencyType, l.duration, l.durationType, l.route]),
    }));
  };

  // Lot 56.3 — patient fictif choisi : ses données PRÉ-REMPLISSENT les champs, qui restent
  // modifiables (VIDAL peut demander de vérifier les garde-fous de saisie).
  const choisirPatientFictif = async (id) => {
    setPatientFictifId(id);
    if (!id) return;
    // Lot 56.4 — choix d'un patient = départ (ou redépart à zéro) du chronomètre.
    chrono.demarrer();
    try {
      const r = await apiClient.get(`/vidal/patients/${id}`);
      const pc = r.data?.profil_clinique || r.data?.patient?.profil_clinique || {};
      setPatient({
        birth_date: pc.date_naissance || "",
        sex: pc.sexe === "MALE" ? "M" : "F",
        weight_kg: pc.poids_kg ?? "",
        creatinine_clearance_ml_min: pc.clairance_creatinine_ml_min ?? "",
      });
      // Lot 56.4 — les étiquettes VIDAL du profil sont reprises telles quelles (références comprises).
      const etiquettes = (liste) => (liste || []).map(versEtiquette).filter(Boolean);
      setAllergies([...etiquettes(pc.allergies), ...etiquettes(pc.molecules_a_eviter || pc.molecules)]);
      setPathologies(etiquettes(pc.pathologies));
    } catch {
      toast.error("Impossible de charger le patient fictif");
    }
  };
  // Message d'erreur d'un champ (affiché sous le champ concerné)
  const erreurDe = (champ) => erreursSaisie.find((e) => e.champ === champ)?.message;
  // Lot 56.4 — erreur d'un champ de ligne : contrôle local d'abord, sinon message du serveur.
  const erreurLigne = (idx, champ) => erreursLignes[idx]?.[champ] || erreurDe(`prescriptions[${idx}].${champ}`);
  useEffect(() => {
    let actif = true;
    chargerEtatValidation().then((etat) => {
      if (!actif || !etat?.mode_validation) return;
      setValidation(true);
      apiClient.get("/vidal/validation/patients-fictifs")
        .then((r) => { if (actif) setPatientsFictifs(r.data?.patients || []); })
        .catch(() => {});
    });
    return () => { actif = false; };
  }, []);

  const addRow = () => setPrescriptions((p) => [...p, nouvelleLigne()]);
  const removeRow = (idx) => setPrescriptions((p) => p.filter((_, i) => i !== idx));
  // Forme fonctionnelle : chaque mise à jour part de l'état le plus récent
  // (une ligne reçoit deux mises à jour quand un médicament est choisi).
  const updateRow = (idx, patch) => setPrescriptions((p) =>
    p.map((row, i) => (i === idx ? { ...row, ...patch } : row))
  );

  // Lot 56.4 — choix d'un médicament : chargement de SES listes VIDAL (unités, voies).
  // Pour limiter les clics, une liste qui ne propose qu'UN seul choix est présélectionnée.
  const choisirMedicament = async (idx, item) => {
    const base = {
      vidal_id: item.vidal_id || "", label: item.title || "", query: "",
      unitId: "", unitLabel: "", units: [], route: "", routes: [], listesChargees: false,
    };
    updateRow(idx, { ...base, chargementListes: !!item.vidal_id });
    if (!item.vidal_id) return;
    const listes = await chargerListesProduit(item.vidal_id, "PRODUCT");
    const patch = appliquerListes(base, listes);
    if (listes.units.length === 1) { patch.unitId = listes.units[0].id; patch.unitLabel = listes.units[0].label; }
    if (listes.routes.length === 1) patch.route = listes.routes[0].id;
    updateRow(idx, patch);
  };

  const run = async () => {
    // Lot 56.4 — le chronomètre s'arrête au clic sur « Analyser ».
    chrono.arreter();
    if (prescriptions.every((p) => !p.vidal_id)) {
      toast.warning("Choisissez au moins un médicament dans la recherche VIDAL");
      chrono.reprendre();
      return;
    }
    // Lot 56.4 — contrôles locaux (mêmes règles que le serveur) avant tout envoi.
    const controles = prescriptions.map((l) => (l.vidal_id ? validerLigne(l) : {}));
    setErreursLignes(controles);
    if (controles.some((e) => Object.keys(e).length)) {
      setErrorState("Posologie à compléter : voir les champs signalés en rouge.");
      chrono.reprendre(); // la correction fait partie de la saisie
      return;
    }
    setLoading(true);
    setErrorState(null);
    setErreursSaisie([]);
    setResult(null);
    // Règle permanente : attente longue = toast « Patientez… » avec jauge circulaire.
    const idToast = toast.loading("Patientez… analyse VIDAL en cours");
    try {
      const r = await apiClient.post("/vidal/prescription/analyze", {
        // Lot 56.4 — format structuré (listes + nombres), XML identique à la Sécurisation.
        structure: true,
        // Lot 56.3 — valeurs SAISIES (même pour un patient fictif) ; le serveur retire l'identité
        patient: {
          birth_date: patient.birth_date || null,
          sex: patient.sex,
          weight_kg: patient.weight_kg !== "" && patient.weight_kg != null ? parseFloat(patient.weight_kg) : null,
          creatinine_clearance_ml_min: patient.creatinine_clearance_ml_min !== "" && patient.creatinine_clearance_ml_min != null
            ? parseFloat(patient.creatinine_clearance_ml_min) : null,
        },
        patient_id: patientFictifId || null,
        // Lignes structurées : médicament, dose, unité, fréquence, durée, voie (pas de libellé
        // d'affichage ni de listes chargées : seuls les champs VIDAL partent).
        prescriptions: prescriptions.filter((p) => p.vidal_id).map((p) => ({ ...versPayloadLigne(p), vidal_id: p.vidal_id })),
        // Allergies : classes d'allergie -> <allergies>, molécules / excipients -> <molecules>.
        allergies: allergies.filter((t) => !String(t.ref || "").startsWith(PREFIXE_MOLECULE)),
        molecules: allergies.filter((t) => String(t.ref || "").startsWith(PREFIXE_MOLECULE)),
        pathologies,
        // Traitements en cours : médicaments VIDAL transmis comme ordonnance antérieure.
        traitements_en_cours: traitements.map((t) => ({ drugRef: t.ref, label: t.label })),
      });
      // Sanitize: strip debug fields (`_request`) before rendering so end-users
      // don't see the outbound VIDAL URL / app_id / body dumped as JSON.
      setTransmis(r.data?.validation || null);
      const raw = r.data?.data || r.data || {};
      const clean = { ...raw };
      delete clean._request;
      delete clean.request;
      delete clean.raw;
      setResult(clean);
      toast.success("Analyse VIDAL terminée", { id: idToast });
    } catch (e) {
      const brut = e?.response?.data?.detail;
      // Lot 56.3 — erreurs de saisie (422) : message général + détail champ par champ
      if (brut && typeof brut === "object" && Array.isArray(brut.erreurs)) {
        setErreursSaisie(brut.erreurs);
        setErrorState(brut.erreurs.map((x) => `• ${x.message}`).join("\n"));
        toast.error(brut.message || "Saisie à corriger", { id: idToast });
        chrono.reprendre(); // Lot 56.4 — saisie à corriger : le chronomètre continue
      } else {
        const detail = (typeof brut === "string" ? brut : null) || e?.message || "Erreur inconnue";
        setErrorState(detail);
        toast.error(detail, { id: idToast });
      }
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="vidal-v2 space-y-4" data-testid="prescription-analysis-form">
      {/* Lot 56.1 — mode « Validation VIDAL » actif : analyse refusée pour un vrai patient.
          Les patients fictifs se gèrent dans la page « Sécurisation VIDAL ». */}
      {/* Lot 56.2 — bandeau vert (police blanche) du mode « Validation VIDAL » */}
      <BandeauValidationVidal>
        Sur cette page, l'identité du patient (nom, prénoms, numéros de contact) n'est jamais transmise :
        seuls la date de naissance, le sexe et la fonction rénale partent chez VIDAL, ou les données d'un patient fictif.
      </BandeauValidationVidal>
      {/* Lot 56.2 — choix du patient en mode validation : saisie anonymisée ou patient fictif */}
      {validation && (
        <label className="block text-xs" data-testid="rx-choix-patient-fictif">
          <span className="block text-slate-600 mb-1">Patient</span>
          <select
            value={patientFictifId}
            onChange={(e) => choisirPatientFictif(e.target.value)}
            className="w-full sm:w-96 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
          >
            <option value="">Saisie anonymisée (date de naissance, sexe, fonction rénale) ou médicaments seuls</option>
            {patientsFictifs.map((p) => (
              <option key={p.id} value={p.id}>Patient fictif : {p.name || p.code_fictif}</option>
            ))}
          </select>
          {patientsFictifs.length === 0 && (
            <span className="block text-[11px] text-slate-500 mt-1">
              Aucun patient fictif : générez-les depuis la page « Sécurisation VIDAL ».
            </span>
          )}
        </label>
      )}
      {/* Patient (toujours modifiable, y compris pour un patient fictif) */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-4 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Date de naissance</span>
          <input
            type="date"
            value={patient.birth_date}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => setPatient({ ...patient, birth_date: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="rx-patient-birth"
          />
          {erreurDe("patient.birth_date") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurDe("patient.birth_date")}</span>}
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Sexe</span>
          <select
            value={patient.sex}
            onChange={(e) => setPatient({ ...patient, sex: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="rx-patient-sex"
          >
            <option value="F">F</option>
            <option value="M">M</option>
          </select>
        </label>
        {/* Lot 56.4 — « spin » : flèches haut/bas, jamais négatif, pas de 0,1 kg */}
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Poids (kg)</span>
          <ChampNombre
            min="0.5"
            max="400"
            step="0.1"
            value={patient.weight_kg}
            onChange={(e) => setPatient({ ...patient, weight_kg: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="rx-patient-weight"
          />
          {validation && !patientFictifId && <span className="block text-[10px] text-slate-400 mt-0.5">Non transmis en mode validation</span>}
          {erreurDe("patient.weight_kg") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurDe("patient.weight_kg")}</span>}
        </label>
        {/* Lot 56.2 — fonction rénale (facultative) : transmise même en mode validation.
            Lot 56.4 — « spin » entier de 1 à 120 (VIDAL la reçoit en entier). */}
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Clairance créatinine (mL/min)</span>
          <ChampNombre
            min={BORNES.clairance_ml_min.min}
            max={BORNES.clairance_ml_min.max}
            step="1"
            value={patient.creatinine_clearance_ml_min}
            onChange={(e) => setPatient({ ...patient, creatinine_clearance_ml_min: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="rx-patient-clairance"
          />
          {erreurDe("patient.creatinine_clearance_ml_min") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurDe("patient.creatinine_clearance_ml_min")}</span>}
        </label>
      </div>

      {/* Lot 56.4 — contexte clinique par LISTES VIDAL (plus de texte séparé par des virgules) */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid md:grid-cols-3 gap-3" data-testid="rx-contexte">
        <ChampTagsReferentiel
          label="Allergies (classes, molécules, excipients)"
          kind="allergy"
          values={allergies}
          onChange={setAllergies}
          testId="rx-allergies"
        />
        <ChampTagsReferentiel
          label="Pathologies (CIM-10)"
          kind="pathology"
          values={pathologies}
          onChange={setPathologies}
          testId="rx-pathologies"
        />
        <ChampTagsReferentiel
          label="Molécules / traitements en cours"
          kind="molecule"
          values={traitements}
          onChange={setTraitements}
          rechercher={rechercherMedicaments}
          texteLibre={false}
          aide="Médicaments déjà pris par le patient : transmis à VIDAL avec la prescription (interactions, redondances)."
          testId="rx-traitements"
        />
      </div>

      {/* Prescriptions — Lot 56.4 : posologie STRUCTURÉE (nombres + listes) */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <h4 className="text-xs font-semibold text-slate-700 mb-2">
          Médicaments prescrits (recherche VIDAL + posologie)
        </h4>
        {prescriptions.map((row, idx) => (
          <div key={idx} className="mb-3 pb-3 border-b border-slate-100 last:border-b-0" data-testid={`rx-ligne-${idx}`}>
            <div className="grid sm:grid-cols-[1fr_auto] gap-2 items-start">
              <div>
                <VidalMedicationSearch
                  query={row.label ? row.label : row.query}
                  onQueryChange={(q) => updateRow(idx, { query: q, label: "", vidal_id: "", units: [], unitId: "", unitLabel: "", routes: [], route: "", listesChargees: false })}
                  onSelect={(item) => choisirMedicament(idx, item)}
                  onClear={() => updateRow(idx, { query: "", label: "", vidal_id: "", units: [], unitId: "", unitLabel: "", routes: [], route: "", listesChargees: false })}
                  testId={`rx-med-search-${idx}`}
                />
                {row.vidal_id && (
                  <p className="text-[10px] text-slate-400 mt-0.5 font-mono" data-testid={`rx-id-${idx}`}>
                    ID VIDAL : {row.vidal_id}
                  </p>
                )}
                {erreurLigne(idx, "medicament") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurLigne(idx, "medicament")}</span>}
              </div>
              {prescriptions.length > 1 && (
                <button
                  onClick={() => removeRow(idx)}
                  className="text-rose-500 hover:text-rose-700 px-2 py-2"
                  title="Retirer ce médicament"
                  data-testid={`rx-remove-${idx}`}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
            {row.chargementListes && (
              <p className="text-[11px] text-slate-500 mt-1 inline-flex items-center gap-1">
                <Loader2 className="h-3 w-3 animate-spin" /> Chargement des unités et voies VIDAL…
              </p>
            )}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mt-2">
              {/* Dose : nombre (spin, pas de 0,5), jamais négative */}
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">{libelleChampDose(row.unitLabel, row.frequencyType)}</span>
                <ChampNombre
                  min="0" step="0.5" max={BORNES.dose.max}
                  value={row.dose}
                  onChange={(e) => updateRow(idx, { dose: e.target.value })}
                  className="champ-saisie" style={{ fontSize: 12.5 }}
                  data-testid={`rx-dose-${idx}`}
                />
                {erreurLigne(idx, "dose") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurLigne(idx, "dose")}</span>}
              </label>
              {/* Unité de prise : liste du produit (/product/{id}/units) */}
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">Unité de prise</span>
                <select
                  className="champ-saisie" style={{ fontSize: 12.5 }}
                  value={row.unitId} disabled={!row.units?.length}
                  onChange={(e) => updateRow(idx, { unitId: e.target.value, unitLabel: row.units.find((u) => u.id === e.target.value)?.label || "" })}
                  data-testid={`rx-unite-${idx}`}
                >
                  <option value="">{row.units?.length ? "Choisir…" : "—"}</option>
                  {(row.units || []).map((u) => <option key={u.id} value={u.id}>{u.label}</option>)}
                </select>
                {erreurLigne(idx, "unitId") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurLigne(idx, "unitId")}</span>}
              </label>
              {/* Fréquence : liste VIDAL, « Par jour » par défaut */}
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">Fréquence</span>
                <select
                  className="champ-saisie" style={{ fontSize: 12.5 }}
                  value={row.frequencyType}
                  onChange={(e) => updateRow(idx, { frequencyType: e.target.value })}
                  data-testid={`rx-frequence-${idx}`}
                >
                  {optionsDepuis(TYPES_FREQUENCE).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                {erreurLigne(idx, "frequencyType") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurLigne(idx, "frequencyType")}</span>}
              </label>
              {/* Durée : nombre entier (spin, minimum 1) */}
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">{libelleChampDuree(row.durationType)}</span>
                <ChampNombre
                  min={BORNES.duree.min} max={BORNES.duree.max} step="1"
                  value={row.duration}
                  onChange={(e) => updateRow(idx, { duration: e.target.value })}
                  className="champ-saisie" style={{ fontSize: 12.5 }}
                  data-testid={`rx-duree-${idx}`}
                />
                {erreurLigne(idx, "duration") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurLigne(idx, "duration")}</span>}
              </label>
              {/* Unité de durée : liste, « Jour(s) » par défaut */}
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">Unité de durée</span>
                <select
                  className="champ-saisie" style={{ fontSize: 12.5 }}
                  value={row.durationType}
                  onChange={(e) => updateRow(idx, { durationType: e.target.value })}
                  data-testid={`rx-type-duree-${idx}`}
                >
                  {optionsDepuis(TYPES_DUREE).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                {erreurLigne(idx, "durationType") && <span className="block text-[10px] text-rose-600 mt-0.5">{erreurLigne(idx, "durationType")}</span>}
              </label>
              {/* Voie d'administration : liste du produit (/product/{id}/routes) */}
              <label className="block text-xs">
                <span className="block text-slate-600 mb-1">Voie</span>
                <select
                  className="champ-saisie" style={{ fontSize: 12.5 }}
                  value={row.route} disabled={!row.routes?.length}
                  onChange={(e) => updateRow(idx, { route: e.target.value })}
                  data-testid={`rx-voie-${idx}`}
                >
                  <option value="">{row.routes?.length ? "Choisir…" : "—"}</option>
                  {(row.routes || []).map((r) => <option key={r.id} value={r.id}>{r.label}{r.hors_amm ? " (hors AMM)" : ""}</option>)}
                </select>
              </label>
            </div>
          </div>
        ))}
        <button
          onClick={addRow}
          className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="rx-add"
        >
          <Plus className="h-3 w-3" /> Ajouter un médicament
        </button>
      </div>

      {/* Lot 56.4 — chronomètre de saisie (mode « Validation VIDAL » uniquement),
          entre les données de la prescription et le bouton d'action. */}
      <ChronoSaisie chrono={chrono} />

      <div className="flex flex-wrap gap-2">
        {/* Lot 56.5 — repartir d'un formulaire vide (et d'un chronomètre à zéro) */}
        <button
          type="button"
          onClick={nouvelleSaisie}
          disabled={loading}
          className="text-sm px-4 py-2 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-50 text-slate-700 inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="rx-nouvelle-saisie"
        >
          <RotateCcw className="h-4 w-4" /> Nouvelle saisie
        </button>
        <button
          onClick={run}
          disabled={loading}
          className="text-sm px-4 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="rx-analyze-submit"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
          Analyser la prescription
        </button>
      </div>

      {errorState && (
        <div
          className="ring-1 ring-amber-200 rounded-lg p-3 bg-amber-50/60 text-xs text-amber-800"
          data-testid="rx-analyze-error"
        >
          <div className="font-semibold mb-1">Analyse impossible</div>
          <div className="whitespace-pre-wrap">{errorState}</div>
        </div>
      )}

      {/* Lot 56.2 — ce qui a réellement été transmis à VIDAL en mode validation */}
      {result && transmis?.actif && (
        <div className="text-[11px] text-slate-600" data-testid="rx-transmis">
          {transmis.origine === "patient_fictif" && "Données du patient fictif transmises."}
          {transmis.origine === "anonymise" && `Patient anonymisé : seuls ${transmis.patient_transmis.join(", ")} ont été transmis.`}
          {transmis.origine === "medicaments_seuls" && "Aucune donnée d'identification ni donnée clinique du patient transmise : analyse des médicaments (et des références VIDAL choisies)."}
          {transmis.champs_retires?.length > 0 && ` Retirés avant l'envoi : ${transmis.champs_retires.join(", ")}.`}
          {transmis.references_transmises > 0 && ` Références VIDAL transmises (allergies, molécules, pathologies) : ${transmis.references_transmises}.`}
        </div>
      )}
      {result && (
        <div className="ring-1 ring-rose-200 rounded-lg p-3 bg-rose-50/30" data-testid="rx-analyze-result">
          <h4 className="text-xs font-semibold text-rose-800 mb-2">Alertes VIDAL</h4>
          <pre className="text-[11px] bg-white ring-1 ring-rose-100 rounded p-3 overflow-auto max-h-96">
            {JSON.stringify(result, null, 2).slice(0, 8000)}
          </pre>
        </div>
      )}
    </div>
  );
}

// Standalone page. NOTE: the parent Route `/portal` already wraps children
// with <PortalLayout>, so we render the page content directly (no double
// wrapping — that was the "page vide" bug reported by the user on 2026-02-14).
export default function PrescriptionAnalysis() {
  return (
    <div className="space-y-4" data-testid="prescription-analysis-page">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-rose-100 ring-1 ring-rose-200 flex items-center justify-center">
          <AlertTriangle className="h-5 w-5 text-rose-600" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-slate-800">Analyse de prescription</h1>
          <p className="text-xs text-slate-500">
            Analyse VIDAL des interactions, contre-indications et posologies pour un patient donné.
          </p>
        </div>
      </div>
      <PrescriptionAnalysisForm />
    </div>
  );
}
