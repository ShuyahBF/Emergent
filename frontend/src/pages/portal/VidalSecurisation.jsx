// pages/portal/VidalSecurisation.jsx — page « Sécurisation » (/portal/vidal-securisation)
// ------------------------------------------------------------------------------------
// Lot 56 — Sécurisation VIDAL v2, portée depuis Ster (pages/VidalSecurisation.jsx),
// qui était elle-même partie de cette page SAWALI puis avait été alignée sur le
// manuel d'intégration VIDAL. La page assemble les composants de components/vidal/ :
//   - DonneesCliniquesPatient : données cliniques complètes (poids/taille datés,
//     créatininémie -> clairance + DFG, groupe de référence du DFG, grossesse /
//     allaitement pour une femme seulement, allergies, molécules, CIM-10) ;
//   - TraitementsEnCours : lignes encore en cours des prescriptions précédentes
//     du patient enregistré, cochées par défaut quand leur fin est connue ;
//   - LignePrescriptionVidal : lignes structurées (unité, voie, indication lues
//     dans VIDAL, dose par 24 h + fréquence, intervalles, période, ALD) ;
//   - ResultatSecurisation + RapportHtmlSecurisation (rapport HTML de VIDAL) ;
//   - BandeauValidationVidal + ValidationVidal : mode « Validation VIDAL »
//     (patients fictifs uniquement, journal des appels) ;
//   - HistoriqueDonneesCliniques : versions du profil clinique et instantanés.
// Les contrôles de saisie (lib/vidalReferentiels.js) sont les mêmes que ceux du
// serveur ; une erreur serveur 422 est affichée en clair.
//
// Fonctions SAWALI CONSERVÉES : patients enregistrés par praticien (nom,
// n° WhatsApp, bouton « Enregistrer » / « Historique »), historique de toutes
// les sécurisations, ordonnance PDF sécurisée (QR de vérification) et envoi
// WhatsApp de l'ordonnance.
import React, { useEffect, useState } from "react";
import { apiClient as api } from "@/lib/api";
import { toast } from "sonner";
import {
  AlertTriangle, ChevronDown, ChevronRight, FileText, Heart, HeartPulse, History, Loader2, MessageCircle,
  Printer, RotateCcw, Save, Search, Settings, UserPlus, X,
} from "lucide-react";
import "@/components/vidal/vidalV2.css";
import DonneesCliniquesPatient, { cliniqueVide, cliniqueDepuisPatient, profilPourFichePatient } from "@/components/vidal/DonneesCliniquesPatient";
import LignePrescriptionVidal, { ligneVide, ligneDepuisTraitement } from "@/components/vidal/LignePrescriptionVidal";
import TraitementsEnCours from "@/components/vidal/TraitementsEnCours";
import ResultatSecurisation from "@/components/vidal/ResultatSecurisation";
import RapportHtmlSecurisation from "@/components/vidal/RapportHtmlSecurisation";
import AlerteDonneesPatient from "@/components/vidal/AlerteDonneesPatient";
import BandeauValidationVidal, { BadgeFictif, chargerEtatValidation } from "@/components/vidal/BandeauValidationVidal";
import HistoriqueDonneesCliniques from "@/components/vidal/HistoriqueDonneesCliniques";
import ParametresGroupesDfg from "@/components/vidal/ParametresGroupesDfg";
import ValidationVidal from "@/components/vidal/ValidationVidal";
import { construirePayloadSecurisation, resumeErreurs, validerFormulaireSecurisation } from "@/components/vidal/payloadSecurisation";
// Lot 56.4 — chronomètre de saisie (mode « Validation VIDAL » uniquement).
import ChronoSaisie, { useChronoSaisie } from "@/components/vidal/ChronoSaisie";
import {
  LIBELLES_TYPES_ALERTE, META_SEVERITE, TYPES_ALERTE_DEFAUT, TYPES_DUREE, TYPES_FREQUENCE, donneesPatientManquantes, messageErreurApi,
} from "@/lib/vidalReferentiels";

const TOUS_CODES_ALERTE = Object.keys(LIBELLES_TYPES_ALERTE);
const ROUGE = "#9C1616"; // rouge de l'identité visuelle « Sécurisation » (déjà utilisé par l'ordonnance PDF)

// Lot 56.4 — champs SAISIS d'une ligne de prescription (ni libellés, ni listes chargées,
// ni indicateurs de chargement) : servent à détecter une modification pour le chronomètre.
const CHAMPS_LIGNE_SAISIS = ["vidal_id", "query", "forme", "drugType", "dose", "unitId", "frequencyType", "duration", "durationType",
  "route", "indication", "startDate", "endDate", "status", "groupType", "ald", "aldCode", "dosages", "inclus"];
// Lot 56.4 — valeurs CALCULÉES des données cliniques (fonction rénale...) : exclues de la détection.
const CHAMPS_CLINIQUES_CALCULES = ["calculRenalEnCours", "creatinCalculee", "plafonnee", "sourceRenale", "insuffisanceRenale",
  "stadeKdigo", "erreurRenal", "avertissementRenal"];

/** Lot 56.4 — « signature » de la saisie (données cliniques + prescription) pour le chronomètre. */
function signatureSaisie(clinique, nouvelles, traitements) {
  // Clairance et DFG ne sont des SAISIES qu'en saisie manuelle ; sinon ils sont calculés (exclus).
  const calcules = clinique.saisieManuelleRenale ? CHAMPS_CLINIQUES_CALCULES : [...CHAMPS_CLINIQUES_CALCULES, "creatin", "glomerularFiltrationRate"];
  const cliniqueSaisie = Object.fromEntries(Object.entries(clinique).filter(([cle]) => !calcules.includes(cle)));
  const ligne = (l) => CHAMPS_LIGNE_SAISIS.map((cle) => l[cle] ?? null);
  return JSON.stringify({ c: cliniqueSaisie, n: nouvelles.map(ligne), t: traitements.map(ligne) });
}

export default function VidalSecurisation() {
  // ---- Patient et données cliniques ----
  const [clinique, setClinique] = useState(cliniqueVide());
  const [patient, setPatient] = useState(null); // patient enregistré chargé (document de /vidal/patients)
  const [patientName, setPatientName] = useState("");
  const [patientWhatsapp, setPatientWhatsapp] = useState("");
  const [enregistrement, setEnregistrement] = useState(false);
  const [historiqueCliniqueOuvert, setHistoriqueCliniqueOuvert] = useState(false);
  // § Message affiché après « Copier » / « Coller dans la ligne » d'une prescription de test.
  const [messageCopie, setMessageCopie] = useState(null);

  // ---- Prescription ----
  const [traitementsEnCours, setTraitementsEnCours] = useState([]);
  const [chargementTraitements, setChargementTraitements] = useState(false);
  const [nouvellesLignes, setNouvellesLignes] = useState([ligneVide()]);
  const [typesAlerte, setTypesAlerte] = useState(TYPES_ALERTE_DEFAUT);

  // ---- Résultat ----
  const [enCours, setEnCours] = useState(false);
  const [resultat, setResultat] = useState(null);
  const [consultationPassee, setConsultationPassee] = useState(null); // sécurisation passée affichée (lecture seule)
  const [erreur, setErreur] = useState(null);
  const [rapport, setRapport] = useState(null);
  // § MI §4.7.1 : alerte interruptive "données patient manquantes" — {manquantes, action}.
  const [alerteDonnees, setAlerteDonnees] = useState(null);

  // ---- Historique (patients enregistrés + toutes les sécurisations) ----
  const [historiqueOuvert, setHistoriqueOuvert] = useState(false);
  const [rechercheHistorique, setRechercheHistorique] = useState("");
  const [patientsTrouves, setPatientsTrouves] = useState([]);
  const [chargementHistorique, setChargementHistorique] = useState(false);
  const [securisationsPassees, setSecurisationsPassees] = useState([]);

  // ---- Ordonnance PDF / WhatsApp ----
  const [impression, setImpression] = useState(false);
  const [derniereOrdonnanceId, setDerniereOrdonnanceId] = useState(null);
  const [envoiWa, setEnvoiWa] = useState(false);

  // ---- Mode validation VIDAL et paramètres ----
  const [etatValidation, setEtatValidation] = useState(null);
  const [patientsFictifs, setPatientsFictifs] = useState([]);
  const [cleBandeau, setCleBandeau] = useState(0);
  const [parametresOuverts, setParametresOuverts] = useState(false);

  // § contrôles de saisie recalculés à chaque frappe (mêmes règles que le serveur).
  const controle = validerFormulaireSecurisation(clinique, nouvellesLignes, traitementsEnCours);

  // Lot 56.4 — chronomètre de saisie : démarre à la première modification des données
  // cliniques ou de la prescription (ou au choix d'un patient), s'arrête au clic sur « Sécuriser ».
  const chrono = useChronoSaisie(signatureSaisie(clinique, nouvellesLignes, traitementsEnCours));

  // État du mode validation + liste des patients fictifs (pour les choisir rapidement).
  async function chargerValidation(forcer = false) {
    const etat = await chargerEtatValidation(forcer);
    setEtatValidation(etat);
    try {
      const r = await api.get("/vidal/patients", { params: { fictifs: true } });
      setPatientsFictifs((r.data?.results || []).sort((a, b) => String(a.code_fictif).localeCompare(String(b.code_fictif))));
    } catch {
      setPatientsFictifs([]);
    }
  }
  useEffect(() => { chargerValidation(); }, []);

  function majClinique(patch) {
    setClinique((prev) => ({ ...prev, ...patch }));
  }
  // Forme fonctionnelle de setState : chaque mise à jour part de l'état le plus récent
  // (une ligne reçoit deux mises à jour successives quand un médicament est choisi).
  function majLigne(idx, patch) {
    setNouvellesLignes((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function basculerTypeAlerte(t) {
    setTypesAlerte((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));
  }
  function basculerTousTypesAlerte() {
    setTypesAlerte((prev) => (prev.length === TOUS_CODES_ALERTE.length ? [] : TOUS_CODES_ALERTE));
  }

  // ---------------------------------------------------------------------
  // Patient enregistré : chargement, enregistrement, historique
  // ---------------------------------------------------------------------
  async function chargerPatient(p) {
    setHistoriqueOuvert(false);
    // Lot 56.4 — nouveau patient sélectionné : le chronomètre (re)part de zéro.
    chrono.demarrer();
    let doc = p;
    try {
      doc = (await api.get(`/vidal/patients/${p.id}`)).data;
    } catch {
      // On garde la ligne de la liste si le détail est indisponible.
    }
    setPatient(doc);
    setPatientName(doc.name || "");
    setPatientWhatsapp(doc.whatsapp_number || "");
    setClinique(cliniqueDepuisPatient(doc));
    setResultat(null); setConsultationPassee(null); setErreur(null); setDerniereOrdonnanceId(null);
    setNouvellesLignes([ligneVide()]);
    setTraitementsEnCours([]);
    setChargementTraitements(true);
    try {
      const r = await api.get(`/vidal/securisation/traitements-en-cours/${doc.id}`);
      setTraitementsEnCours((r.data?.traitements || []).map(ligneDepuisTraitement));
    } catch {
      setTraitementsEnCours([]);
    }
    setChargementTraitements(false);
    toast.success(`Patient « ${doc.name || doc.whatsapp_number} » chargé — données cliniques et traitements en cours repris.`);
  }

  async function enregistrerPatient() {
    if (!patientName.trim() && !patientWhatsapp.trim()) {
      toast.warning("Renseignez un nom ou un n° WhatsApp pour enregistrer le patient.");
      return;
    }
    if (Object.keys(controle.patient).length) {
      toast.error("Corrigez les données cliniques signalées en rouge avant d'enregistrer.");
      return;
    }
    setEnregistrement(true);
    try {
      // § historique clinique : une version datée est créée si quelque chose a changé.
      const r = await api.post("/vidal/patients", {
        patient_id: patient?.id || undefined,
        name: patientName || undefined,
        whatsapp_number: patientWhatsapp || undefined,
        profil_clinique: profilPourFichePatient(clinique),
      });
      setPatient(r.data);
      toast.success(r.data?.version_creee
        ? "Patient enregistré (nouvelle version de l'historique clinique) — ses traitements en cours seront repris à la prochaine consultation."
        : "Patient enregistré — profil clinique déjà à jour.");
    } catch (err) {
      toast.error(messageErreurApi(err, "Impossible d'enregistrer le patient."));
    }
    setEnregistrement(false);
  }

  async function ouvrirHistorique(q) {
    setHistoriqueOuvert(true);
    setChargementHistorique(true);
    try {
      const r = await api.get("/vidal/patients", { params: q ? { q } : {} });
      setPatientsTrouves(r.data?.results || []);
    } catch {
      setPatientsTrouves([]);
    }
    try {
      const r2 = await api.get("/vidal/securisation/history");
      setSecurisationsPassees(r2.data?.results || []);
    } catch {
      setSecurisationsPassees([]);
    }
    setChargementHistorique(false);
  }

  // Consulte une sécurisation passée (lecture seule) — n'affecte pas le formulaire en cours.
  async function voirSecurisation(a) {
    try {
      const r = await api.get(`/vidal/securisation/history/${a.id}`);
      setResultat({ analyse: r.data?.analyse || r.data?.parsed, id: a.id });
      setConsultationPassee({ created_at: r.data?.created_at, patient_name: r.data?.patient_name });
      setHistoriqueOuvert(false);
    } catch {
      toast.error("Impossible de charger cette sécurisation.");
    }
  }

  function reinitialiser() {
    setClinique(cliniqueVide());
    setPatient(null); setPatientName(""); setPatientWhatsapp("");
    setTraitementsEnCours([]); setNouvellesLignes([ligneVide()]); setTypesAlerte(TYPES_ALERTE_DEFAUT);
    setResultat(null); setConsultationPassee(null); setErreur(null); setRapport(null); setAlerteDonnees(null);
    setDerniereOrdonnanceId(null); setMessageCopie(null);
    // Lot 56.4 — nouveau patient vide : chronomètre remis à zéro, en attente de la première saisie.
    chrono.reinitialiser(signatureSaisie(cliniqueVide(), [ligneVide()], []));
  }

  // ---------------------------------------------------------------------
  // Validation VIDAL : prescriptions de test et références à résoudre
  // ---------------------------------------------------------------------

  // § ligne créée depuis une prescription de test. Demande utilisateur : TOUT
  // est vide (forme, dose, fréquence, durée) — seul le produit est repris,
  // tel que renvoyé par une VRAIE recherche VIDAL (ou choisi par le testeur
  // parmi les résultats réels, ou recherché ici). La posologie de test n'est
  // reprise QUE si le praticien clique « Coller dans la ligne ».
  function ajouterPrescriptionTest(t, candidat = null, indexTest = null) {
    const produit = candidat || (t.resolution?.statut === "trouve" ? t.resolution.reference : null);
    const ligne = {
      ...ligneVide(),
      ...(produit ? { vidal_id: produit.vidal_id, label: produit.label } : { query: t.recherche, rechercheAuto: true }),
      // Marqueur local (jamais envoyé à VIDAL) : relie la ligne à sa prescription de test pour « Coller ».
      origineTest: indexTest,
    };
    setNouvellesLignes((prev) => [...prev.filter((l) => l.vidal_id || l.query), ligne]);
  }

  // § Texte de la posologie de test pour le presse-papiers. IMPORTANT : ne
  // contient JAMAIS l'identité du patient — uniquement médicament et posologie.
  function textePosologieTest(t) {
    const unite = t.type_duree === "DAY" ? "jour(s)" : t.type_duree === "MONTH" ? "mois" : (t.type_duree || "");
    return [
      `Médicament : ${t.resolution?.reference?.label || t.recherche}`,
      t.forme ? `Forme : ${t.forme}` : null,
      `Dose par 24 h : ${t.dose ?? ""}`,
      t.frequence ? `Fréquence : ${TYPES_FREQUENCE[t.frequence] || t.frequence}` : null,
      `Durée : ${t.duree ?? ""} ${unite}`.trim(),
    ].filter(Boolean).join("\n");
  }

  async function copierPosologieTest(t, i) {
    try {
      await navigator.clipboard.writeText(textePosologieTest(t));
      setMessageCopie({ index: i, texte: "Posologie de test copiée (sans identité du patient)." });
    } catch {
      setMessageCopie({ index: i, texte: "Copie impossible dans ce navigateur : utilisez « Coller dans la ligne »." });
    }
  }

  // § « Coller dans la ligne » : remplit, à la demande, la ligne créée depuis
  // cette prescription de test. Seuls les champs de posologie sont touchés.
  function collerPosologieTest(t, i) {
    setNouvellesLignes((prev) => prev.map((l) => (l.origineTest === i ? {
      ...l, forme: t.forme || "", dose: String(t.dose ?? ""), frequencyType: t.frequence || "",
      duration: String(t.duree ?? ""), durationType: t.type_duree || "",
    } : l)));
    setMessageCopie({ index: i, texte: "Posologie de test collée dans la ligne : vérifiez-la avant de sécuriser." });
  }

  // § références « à choisir » du patient fictif : le testeur retient l'un des résultats RÉELS de VIDAL.
  function choisirReference(ref, candidat) {
    const champ = ref.champ;
    setClinique((prev) => ({ ...prev, [champ]: [...(prev[champ] || []).filter((x) => x.ref !== candidat.ref), { label: candidat.label, ref: candidat.ref }] }));
  }

  // ---------------------------------------------------------------------
  // Sécurisation, rapport HTML
  // ---------------------------------------------------------------------
  function payloadOuErreur() {
    const aUneLigne = [...traitementsEnCours.filter((l) => l.inclus), ...nouvellesLignes].some((l) => l.vidal_id);
    if (!aUneLigne) { setErreur("Ajoutez au moins un médicament (recherche VIDAL) avant de sécuriser."); return null; }
    if (!controle.ok) { setErreur(resumeErreurs(controle)); return null; }
    return construirePayloadSecurisation({
      clinique, nouvelles: nouvellesLignes, traitements: traitementsEnCours, typesAlerte,
      patientNom: patientName || null, patientWhatsapp: patientWhatsapp || null, patientId: patient?.id || null,
    });
  }

  // § MI §4.7.1 : avant d'analyser, vérifier que les données patient utilisées
  // par les médicaments prescrits sont saisies ; sinon le praticien complète
  // ou passe outre explicitement (clic).
  function verifierDonneesPatient(action) {
    const manquantes = donneesPatientManquantes(clinique, [...nouvellesLignes, ...traitementsEnCours.filter((l) => l.inclus)]);
    if (manquantes.interruptives.length || manquantes.informations.length) {
      setAlerteDonnees({ manquantes, action });
      return false;
    }
    return true;
  }

  async function lancerAnalyse(forcer = false) {
    // Lot 56.4 — le chronomètre s'arrête au clic sur « Sécuriser »...
    chrono.arreter();
    const payload = payloadOuErreur();
    // ... mais continue si la saisie est à corriger (la correction fait partie de la saisie).
    if (!payload) { chrono.reprendre(); return; }
    // Données patient manquantes : le médecin complète (chrono continue) ou passe outre (arrêt à ce clic).
    if (!forcer && !verifierDonneesPatient(() => lancerAnalyse(true))) { chrono.reprendre(); return; }
    setAlerteDonnees(null);
    setEnCours(true); setErreur(null); setResultat(null); setConsultationPassee(null); setDerniereOrdonnanceId(null);
    // Règle permanente : attente longue = toast « Patientez… » avec jauge circulaire.
    const idToast = toast.loading("Patientez… sécurisation VIDAL en cours");
    try {
      const r = await api.post("/vidal/securisation/analyze", payload);
      setResultat(r.data);
      if (r.data?.erreur_vidal) setErreur(`VIDAL a répondu ${r.data.erreur_vidal.statut} : ${r.data.erreur_vidal.message}`);
      toast.dismiss(idToast);
    } catch (err) {
      setErreur(messageErreurApi(err));
      toast.dismiss(idToast);
      // Saisie refusée par le serveur (422) : le chronomètre continue.
      if (err?.response?.status === 422) chrono.reprendre();
    }
    setEnCours(false);
  }

  // § options : { ancre } ouvre une rubrique précise, { rubriques } filtre le rapport (MI §6.5.5).
  async function ouvrirRapportHtml({ ancre = null, rubriques = [] } = {}) {
    const payload = payloadOuErreur();
    if (!payload) return;
    setRapport({ chargement: true, rubriques });
    try {
      const r = await api.post("/vidal/securisation/rapport-html", { ...payload, alert_display_types: rubriques.length ? rubriques : null }, { responseType: "text" });
      setRapport({ html: r.data, ancre, rubriques });
    } catch (err) {
      setRapport({ erreur: messageErreurApi(err, "Rapport HTML indisponible.") });
    }
  }

  // ---------------------------------------------------------------------
  // Ordonnance PDF sécurisée et envoi WhatsApp (fonctions SAWALI existantes)
  // ---------------------------------------------------------------------
  async function imprimerOrdonnance() {
    const lignes = nouvellesLignes.filter((l) => l.vidal_id).map((l) => ({
      label: l.label, dose: l.dose || null, unit: l.unitLabel || null,
      duration: l.duration || null, durationType: l.durationType ? (TYPES_DUREE[l.durationType] || l.durationType).toLowerCase() : null,
      frequency: l.frequencyType ? TYPES_FREQUENCE[l.frequencyType] || l.frequencyType : null,
      route: (l.routes || []).find((r) => r.id === l.route)?.label || null,
    }));
    if (!lignes.length) {
      toast.warning("Ajoutez au moins un médicament avant d'imprimer l'ordonnance.");
      return;
    }
    setImpression(true);
    try {
      const r = await api.post("/vidal/ordonnance/generate", {
        patient_name: patientName || undefined, patient_whatsapp: patientWhatsapp || undefined,
        patient: { dateOfBirth: clinique.dateOfBirth || null, gender: clinique.gender || null, height: clinique.height || null, weight: clinique.weight || null },
        lines: lignes,
        alerts_summary: (resultat?.analyse?.summary || []).filter((s) => s.severity && s.severity !== "NO_ALERT"),
      }, { responseType: "blob" });
      window.open(window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" })), "_blank");
      // L'identifiant voyage en en-tête (le corps de la réponse est le PDF) — nécessaire pour « Envoi WA ».
      setDerniereOrdonnanceId(r.headers?.["x-ordonnance-id"] || null);
    } catch {
      toast.error("Impossible de générer l'ordonnance");
    }
    setImpression(false);
  }

  async function envoyerOrdonnanceWhatsapp() {
    if (!derniereOrdonnanceId) {
      toast.warning("Imprimez d'abord l'ordonnance (elle doit être générée avant l'envoi).");
      return;
    }
    if (!patientWhatsapp.trim()) {
      toast.warning("Renseignez le n° WhatsApp du patient avant d'envoyer.");
      return;
    }
    setEnvoiWa(true);
    try {
      await api.post(`/vidal/ordonnance/${derniereOrdonnanceId}/send-whatsapp`, { phone: patientWhatsapp });
      toast.success("Ordonnance envoyée sur WhatsApp.");
    } catch (err) {
      toast.error(messageErreurApi(err, "Envoi WhatsApp impossible"));
    }
    setEnvoiWa(false);
  }

  const modeValidation = !!etatValidation?.mode_validation;
  const STYLE_ENCADRE_TEST = { border: "1px dashed #f5b971", background: "rgba(245,185,113,0.08)", borderRadius: 10, padding: 10, marginBottom: 12, fontSize: 12.5 };

  return (
    <div className="vidal-v2 space-y-4" data-testid="vidal-securisation-page">
      {/* En-tête : titre + bouton Historique (patients enregistrés et sécurisations passées). */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="w-10 h-10 rounded-lg bg-[#BB2323]/10 dark:bg-[#BB2323]/20 ring-1 ring-[#BB2323]/25 flex items-center justify-center">
            <Heart className="h-5 w-5 text-[#BB2323]" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-foreground">Sécurisation</h1>
            <p className="text-xs text-muted-foreground">Analyse VIDAL — interactions, contre-indications, posologie, allergies, grossesse/allaitement, fonction rénale.</p>
          </div>
        </div>
        <div style={{ position: "relative" }}>
          <button type="button" className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={() => (historiqueOuvert ? setHistoriqueOuvert(false) : ouvrirHistorique())} data-testid="sec-history-toggle">
            <History size={14} /> Historique
          </button>
          {historiqueOuvert && (
            <div className="carte" style={{ position: "absolute", right: 0, zIndex: 30, marginTop: 6, width: 340, maxHeight: 480, overflowY: "auto", padding: 12 }} data-testid="sec-history-panel">
              <div style={{ position: "relative", marginBottom: 8 }}>
                <Search size={13} style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "var(--vidal-gris)" }} />
                <input className="champ-saisie" style={{ paddingLeft: 28, fontSize: 12.5 }} placeholder="Nom ou n° WhatsApp…" value={rechercheHistorique}
                  onChange={(e) => { setRechercheHistorique(e.target.value); ouvrirHistorique(e.target.value); }} data-testid="sec-history-search" />
              </div>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--vidal-gris)", textTransform: "uppercase", marginBottom: 4 }}>Patients enregistrés</div>
              {chargementHistorique && <div style={{ fontSize: 12, color: "var(--vidal-gris)" }}>Recherche…</div>}
              {!chargementHistorique && patientsTrouves.length === 0 && <div style={{ fontSize: 12, color: "var(--vidal-gris)", marginBottom: 6 }}>Aucun patient enregistré.</div>}
              {patientsTrouves.map((p) => (
                <button key={p.id} type="button" onClick={() => chargerPatient(p)}
                  style={{ display: "block", width: "100%", textAlign: "left", border: "none", background: "transparent", padding: "6px 4px", borderBottom: "1px solid var(--vidal-bordure)", cursor: "pointer", fontSize: 12.5, color: "var(--vidal-texte)" }}>
                  <strong>{p.name || p.whatsapp_number}</strong><BadgeFictif patient={p} />
                  <div style={{ fontSize: 11, color: "var(--vidal-gris)" }}>{p.whatsapp_number || "—"}{p.last_consultation_at ? ` — dernière consultation le ${new Date(p.last_consultation_at).toLocaleDateString("fr-FR")}` : ""}</div>
                </button>
              ))}
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--vidal-gris)", textTransform: "uppercase", margin: "10px 0 4px" }}>Toutes les sécurisations</div>
              {!chargementHistorique && securisationsPassees.length === 0 && <div style={{ fontSize: 12, color: "var(--vidal-gris)" }}>Aucune sécurisation.</div>}
              {securisationsPassees.map((a) => (
                <button key={a.id} type="button" onClick={() => voirSecurisation(a)}
                  style={{ display: "flex", justifyContent: "space-between", gap: 6, width: "100%", textAlign: "left", border: "none", background: "transparent", padding: "6px 4px", borderBottom: "1px solid var(--vidal-bordure)", cursor: "pointer", fontSize: 12, color: "var(--vidal-texte)" }}>
                  <span>{new Date(a.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })} — {a.patient_name || "Patient non enregistré"} ({a.lines_count} ligne{a.lines_count > 1 ? "s" : ""})</span>
                  {a.top_severity && <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 999, color: "white", background: (META_SEVERITE[a.top_severity] || { couleur: "#94a3b8" }).couleur, height: "fit-content" }}>{(META_SEVERITE[a.top_severity] || { label: a.top_severity }).label}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <BandeauValidationVidal key={cleBandeau} />

      {/* Patient : identité interne (jamais transmise à VIDAL), enregistrement, historique clinique. */}
      <div className="carte">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}>
            Patient {patient && <BadgeFictif patient={patient} />}
            {patient && <span style={{ fontSize: 11.5, fontWeight: 500, color: "var(--vidal-gris)" }}>enregistré{patient.profil_fictif ? ` — ${patient.profil_fictif}` : ""}</span>}
          </div>
          {/* § mode validation : seuls les patients fictifs peuvent être envoyés à VIDAL. */}
          {modeValidation && (
            <select className="champ-saisie" style={{ width: 320, fontSize: 12.5 }} value="" onChange={(e) => {
              const p = patientsFictifs.find((x) => x.id === e.target.value);
              if (p) chargerPatient(p);
            }} data-testid="sec-patient-fictif">
              <option value="">{patientsFictifs.length ? `Choisir un patient fictif (${patientsFictifs.length})…` : "Aucun patient fictif : créez-les dans « Paramètres VIDAL »"}</option>
              {patientsFictifs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10, alignItems: "end" }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>Nom du patient (usage interne, jamais transmis à VIDAL)</label>
            <input className="champ-saisie" value={patientName} disabled={!!patient?.est_fictif} onChange={(e) => setPatientName(e.target.value)} placeholder="Nom" data-testid="sec-patient-name" />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, display: "block", marginBottom: 3 }}>N° WhatsApp (ordonnance)</label>
            <input className="champ-saisie" value={patientWhatsapp} disabled={!!patient?.est_fictif} onChange={(e) => setPatientWhatsapp(e.target.value)} placeholder="+226…" data-testid="sec-patient-whatsapp" />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button type="button" className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={enregistrerPatient} disabled={enregistrement} data-testid="sec-save-patient">
              {enregistrement ? <Loader2 size={13} className="lucide-tourne" /> : <Save size={13} />} Enregistrer
            </button>
            <button type="button" className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={() => setHistoriqueCliniqueOuvert(true)} disabled={!patient?.id} title={patient?.id ? "" : "Enregistrez ou chargez d'abord un patient"}>
              <FileText size={13} /> Historique clinique
            </button>
            <button type="button" className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={reinitialiser}>
              <UserPlus size={13} /> Nouveau patient
            </button>
          </div>
        </div>
      </div>

      <div className="carte">
        {/* § références VIDAL du patient fictif non résolues automatiquement : jamais de valeur
            inventée — choix parmi les résultats réels ou recherche manuelle ci-dessous. */}
        {patient?.est_fictif && patient.references_a_resoudre?.length > 0 && (
          <div style={STYLE_ENCADRE_TEST}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Références VIDAL à résoudre (allergies, molécules, pathologies)</div>
            {patient.references_a_resoudre.map((r, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 4 }}>
                <span><strong>{r.recherche}</strong> ({r.champ === "allergies" ? "classe d'allergie" : r.champ === "molecules" ? "molécule / excipient" : "pathologie CIM-10"})</span>
                {r.statut === "a_choisir" ? (
                  <select className="champ-saisie" style={{ width: 300, fontSize: 12 }} value="" onChange={(e) => {
                    const c = r.candidats.find((x) => x.ref === e.target.value);
                    if (c) choisirReference(r, c);
                  }}>
                    <option value="">Choisir parmi les {r.nombre_resultats} résultats VIDAL…</option>
                    {r.candidats.map((c) => <option key={c.ref} value={c.ref}>{c.label}</option>)}
                  </select>
                ) : (
                  <span style={{ color: "var(--vidal-orange)" }}>à rechercher dans VIDAL pendant la recette (champ de recherche ci-dessous){r.raison ? ` — ${r.raison}` : ""}</span>
                )}
              </div>
            ))}
          </div>
        )}
        <DonneesCliniquesPatient clinique={clinique} onChange={majClinique} erreurs={controle.patient} patientId={patient?.id || null} />
      </div>

      <div className="carte">
        <TraitementsEnCours traitements={traitementsEnCours} onChange={setTraitementsEnCours} chargement={chargementTraitements}
          erreurs={controle.traitements} patientSelectionne={patient} />
      </div>

      <div className="carte">
        <div style={{ fontWeight: 700, marginBottom: 10 }}>Nouvelle prescription</div>
        {/* § validation VIDAL : prescriptions de test du profil du patient fictif — le nom est
            recherché dans VIDAL (aucun identifiant inventé), le produit est choisi par le testeur. */}
        {patient?.est_fictif && patient.prescriptions_test_validation?.length > 0 && (
          <div style={STYLE_ENCADRE_TEST}>
            <div style={{ fontWeight: 600, marginBottom: 6 }}>Prescriptions de test — {patient.profil_fictif}</div>
            {patient.prescriptions_test_validation.map((t, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
                <span>
                  <strong>{t.recherche}</strong>
                  {t.resolution?.statut === "trouve" && <> → {t.resolution.reference.label}</>}
                  {t.resolution?.statut === "a_rechercher" && <span style={{ color: "var(--vidal-orange)" }}> (à rechercher dans VIDAL pendant la recette)</span>}
                  {" "}— dose par 24 h : {t.dose} (unité à choisir), durée : {t.duree} {t.type_duree === "DAY" ? "jour(s)" : t.type_duree === "MONTH" ? "mois" : t.type_duree} — <em>attendu : {t.attendu}</em>
                </span>
                {t.resolution?.statut === "a_choisir" ? (
                  <select className="champ-saisie" style={{ width: 280, fontSize: 12 }} value="" onChange={(e) => {
                    const c = t.resolution.candidats.find((x) => x.ref === e.target.value);
                    if (c) ajouterPrescriptionTest(t, c, i);
                  }}>
                    <option value="">Choisir parmi les {t.resolution.nombre_resultats} résultats VIDAL…</option>
                    {t.resolution.candidats.map((c) => <option key={c.ref} value={c.ref}>{c.label}</option>)}
                  </select>
                ) : (
                  <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} onClick={() => ajouterPrescriptionTest(t, null, i)}>Ajouter à la prescription</button>
                )}
                {/* § Copier / coller la posologie de test, à la demande (identité du patient jamais copiée). */}
                <span style={{ display: "inline-flex", gap: 6 }}>
                  <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} onClick={() => copierPosologieTest(t, i)} title="Copie le médicament et la posologie de test, sans l'identité du patient">Copier</button>
                  <button type="button" className="bouton-secondaire" style={{ fontSize: 11.5 }} disabled={!nouvellesLignes.some((l) => l.origineTest === i)}
                    onClick={() => collerPosologieTest(t, i)} title="Remplit la ligne ajoutée depuis cette prescription de test">Coller dans la ligne</button>
                </span>
                {messageCopie?.index === i && <span style={{ width: "100%", fontSize: 11.5, color: "var(--vidal-gris)" }}>{messageCopie.texte}</span>}
              </div>
            ))}
          </div>
        )}
        {nouvellesLignes.map((ligne, idx) => (
          <LignePrescriptionVidal key={idx} ligne={ligne} erreurs={controle.nouvelles[idx]} onChange={(patch) => majLigne(idx, patch)}
            onRetirer={nouvellesLignes.length > 1 ? () => setNouvellesLignes((prev) => prev.filter((_, i) => i !== idx)) : null} />
        ))}
        <button type="button" className="bouton-secondaire" style={{ fontSize: 12.5 }} onClick={() => setNouvellesLignes((prev) => [...prev, ligneVide()])}>+ Ajouter un médicament</button>
      </div>

      <div className="carte">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <div style={{ fontWeight: 700 }}>Alertes à vérifier</div>
          <button type="button" onClick={basculerTousTypesAlerte} style={{ border: "none", background: "none", color: ROUGE, fontWeight: 600, fontSize: 12, cursor: "pointer" }}>
            {typesAlerte.length === TOUS_CODES_ALERTE.length ? "Tout décocher" : "Tout cocher"}
          </button>
        </div>
        <div style={{ fontSize: 12, color: "var(--vidal-gris)", marginBottom: 10 }}>{typesAlerte.length} sélectionnée{typesAlerte.length > 1 ? "s" : ""} sur {TOUS_CODES_ALERTE.length} (le rapport HTML complet affiche toujours toutes les alertes)</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {Object.entries(LIBELLES_TYPES_ALERTE).map(([code, label]) => (
            <button type="button" key={code} onClick={() => basculerTypeAlerte(code)}
              style={{
                fontSize: 12, padding: "5px 12px", borderRadius: 999, cursor: "pointer",
                border: typesAlerte.includes(code) ? `1px solid ${ROUGE}` : "1px solid var(--vidal-bordure)",
                background: typesAlerte.includes(code) ? ROUGE : "transparent",
                color: typesAlerte.includes(code) ? "white" : "var(--vidal-gris-fonce)",
              }}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Lot 56.4 — chronomètre de saisie (mode « Validation VIDAL » uniquement),
          entre les données cliniques / la prescription et le bouton « Sécuriser ». */}
      <ChronoSaisie chrono={chrono} />

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button type="button" className="bouton-secondaire" onClick={reinitialiser}><RotateCcw size={13} /> Réinitialiser</button>
        <button type="button" className="bouton-primaire" style={{ background: ROUGE }} onClick={() => lancerAnalyse()} disabled={enCours} data-testid="sec-run">
          {enCours ? <><Loader2 size={14} className="lucide-tourne" /> Analyse en cours…</> : <><HeartPulse size={14} /> Sécuriser</>}
        </button>
        <button type="button" className="bouton-secondaire" onClick={() => ouvrirRapportHtml()}><FileText size={13} /> Rapport HTML complet</button>
        {resultat && <button type="button" className="bouton-secondaire" onClick={() => window.print()}><Printer size={13} /> Imprimer le résultat</button>}
        <button type="button" className="bouton-secondaire" onClick={imprimerOrdonnance} disabled={impression} data-testid="sec-print">
          {impression ? <Loader2 size={13} className="lucide-tourne" /> : <Printer size={13} />} Imprimer l'ordonnance
        </button>
        <button type="button" className="bouton-secondaire" onClick={envoyerOrdonnanceWhatsapp} disabled={envoiWa || !derniereOrdonnanceId}
          title={derniereOrdonnanceId ? "" : "Imprimez d'abord l'ordonnance"} data-testid="sec-send-wa">
          {envoiWa ? <Loader2 size={13} className="lucide-tourne" /> : <MessageCircle size={13} />} Envoi WA
        </button>
      </div>

      <AlerteDonneesPatient manquantes={alerteDonnees?.manquantes} onCompleter={() => setAlerteDonnees(null)} onPasserOutre={() => alerteDonnees?.action()} />

      {erreur && <div className="carte" style={{ color: "var(--vidal-orange)", display: "flex", alignItems: "center", gap: 6 }}><AlertTriangle size={14} /> {erreur}</div>}

      {resultat && (
        <div className="carte" data-testid="sec-result">
          <div style={{ fontWeight: 700, marginBottom: 12 }}>
            Résultat de l'analyse VIDAL
            {consultationPassee && (
              <span style={{ fontWeight: 500, fontSize: 12, color: "var(--vidal-gris)" }}>
                {" "}— historique du {new Date(consultationPassee.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                {consultationPassee.patient_name ? ` (${consultationPassee.patient_name})` : ""}, lecture seule
              </span>
            )}
          </div>
          <ResultatSecurisation analyse={resultat.analyse} onOuvrirRubrique={consultationPassee ? null : (ancre) => ouvrirRapportHtml({ ancre })} />
        </div>
      )}

      <RapportHtmlSecurisation rapport={rapport} onFermer={() => setRapport(null)} onFiltrer={(rubriques) => ouvrirRapportHtml({ rubriques })} />

      {/* Paramètres VIDAL : groupes de référence du DFG et mode « Validation VIDAL ». */}
      <div className="carte" style={{ padding: 0 }}>
        <button type="button" onClick={() => setParametresOuverts(!parametresOuverts)}
          style={{ width: "100%", display: "flex", alignItems: "center", gap: 6, border: "none", background: "transparent", padding: "12px 16px", cursor: "pointer", fontWeight: 700, color: "var(--vidal-texte)" }}>
          {parametresOuverts ? <ChevronDown size={14} /> : <ChevronRight size={14} />} <Settings size={14} /> Paramètres VIDAL (groupes du DFG, validation VIDAL)
        </button>
        {parametresOuverts && (
          <div style={{ padding: "0 16px 16px", display: "grid", gap: 16 }}>
            <ParametresGroupesDfg />
            <ValidationVidal onChangement={() => { chargerValidation(true); setCleBandeau((n) => n + 1); }} />
          </div>
        )}
      </div>

      {historiqueCliniqueOuvert && patient?.id && (
        <div role="dialog" aria-modal="true" onClick={() => setHistoriqueCliniqueOuvert(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(15,20,30,0.55)", zIndex: 1900, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
          <div className="carte" onClick={(e) => e.stopPropagation()} style={{ width: "min(1200px, 100%)", maxHeight: "92vh", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <div style={{ fontWeight: 700 }}>Historique des données cliniques — {patient.name || patient.whatsapp_number}</div>
              <button type="button" onClick={() => setHistoriqueCliniqueOuvert(false)} style={{ border: "none", background: "none", cursor: "pointer", display: "flex", color: "var(--vidal-texte)" }}><X size={18} /></button>
            </div>
            <HistoriqueDonneesCliniques patientId={patient.id} />
          </div>
        </div>
      )}
    </div>
  );
}
