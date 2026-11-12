// Portage site-meetafrican (frontend/src/secure/content/posologie.html) —
// module Posologie : profil patient (chips + champs détaillés), sélection
// réelle du médicament (recherche VIDAL, remplace la maquette 100% simulée),
// voie d'administration ET indication réelles (confirmées contre le manuel
// VIDAL, voir /vidal/product/{id}/detail et /vidal/product/{id}/indications),
// et recherche de posologie EXPÉRIMENTALE (endpoint /posology-descriptors
// jamais validé en réel, contrairement aux deux listes ci-dessus).
import { Pastille, LegendePastilles } from "@/components/vidal/PastilleType";   // lot 376
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { AlertTriangle, Baby, Loader2, Pill, Search, Stethoscope, User, Users } from "lucide-react";
import VidalMedicationSearch from "@/components/VidalMedicationSearch";
import ChampDate from "@/components/vidal/ChampDate";
import { useVidalUiSettings } from "@/contexts/VidalUiSettingsContext";

// Profils rapides — mêmes valeurs de référence que la maquette d'origine
// (le profil "homme" correspond exactement à l'exemple du manuel
// d'intégration VIDAL : 1986-09-10, MALE, 178cm, 80kg).
const PROFILES = {
  bebe: { label: "Bébé", dob: "2026-01-15", gender: "MALE", height: 68, weight: 8 },
  fille: { label: "Fille", dob: "2018-05-02", gender: "FEMALE", height: 128, weight: 25 },
  garcon: { label: "Garçon", dob: "2018-02-20", gender: "MALE", height: 130, weight: 26 },
  femme: { label: "Femme", dob: "1991-04-12", gender: "FEMALE", height: 162, weight: 62 },
  enceinte: { label: "Enceinte", dob: "1998-06-30", gender: "FEMALE", height: 165, weight: 68 },
  homme: { label: "Homme", dob: "1986-09-10", gender: "MALE", height: 178, weight: 80 },
  renal: { label: "Rénal", dob: "1966-03-01", gender: "MALE", height: 170, weight: 75 },
  age: { label: "Âgé", dob: "1944-11-08", gender: "FEMALE", height: 158, weight: 58 },
};

const emptyPatient = { dob: "", gender: "UNKNOWN", hepatic: "NONE", height: "", weight: "" };

const TYPES_ELEMENT = {
  PRODUCT: { libelle: "Spécialité", pastille: "SPECIALITE" },
  PACK: { libelle: "Présentation", pastille: "PRESENTATION" },
  VMP: { libelle: "VMP", pastille: "VMP" },
  UCD: { libelle: "UCD", pastille: "UCD" },
};
const RESSOURCE_POSOLOGIE = { PRODUCT: "product", PACK: "package", VMP: "vmp", UCD: "ucd" };

export default function VidalPosologie() {
  const { vidalAdminNotes } = useVidalUiSettings();
  const [patient, setPatient] = useState(emptyPatient);
  const [allergies, setAllergies] = useState("");
  const [pathologies, setPathologies] = useState("");
  const [molecules, setMolecules] = useState("");

  // Lot 376 (remarque VIDAL n°8) — type d'élément à prescrire : spécialité (recherche), présentation, VMP, UCD (identifiant VIDAL saisi)
  const [typeElement, setTypeElement] = useState("PRODUCT");
  const [idSaisi, setIdSaisi] = useState("");
  const [medQuery, setMedQuery] = useState("");
  const [medication, setMedication] = useState(null); // {vidal_id, title}
  const [routes, setRoutes] = useState([]);
  const [routesLoading, setRoutesLoading] = useState(false);
  const [routeId, setRouteId] = useState("");
  const [indications, setIndications] = useState([]);
  const [indicationsLoading, setIndicationsLoading] = useState(false);
  const [indicationRef, setIndicationRef] = useState("");

  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState(null);

  const applyProfile = (key) => {
    if (key === "allergique") {
      setAllergies((prev) => (prev.trim() ? `${prev}, Pénicilline` : "Pénicilline"));
      return;
    }
    const p = PROFILES[key];
    if (!p) return;
    setPatient({
      dob: p.dob,
      gender: p.gender,
      hepatic: "NONE",
      height: String(p.height),
      weight: String(p.weight),
    });
  };

  const selectMedication = async (item) => {
    setMedication(item);
    setMedQuery("");
    setRoutes([]);
    setRouteId("");
    setIndications([]);
    setIndicationRef("");
    if (!item.vidal_id) return;
    setRoutesLoading(true);
    setIndicationsLoading(true);
    try {
      const [detailRes, indicationsRes] = await Promise.all([
        apiClient.get(`/vidal/product/${item.vidal_id}/detail`),
        apiClient.get(`/vidal/product/${item.vidal_id}/indications`).catch(() => null),
      ]);
      setRoutes(detailRes.data?.routes || []);
      setIndications(indicationsRes?.data?.indications || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Voies d'administration indisponibles");
    }
    setRoutesLoading(false);
    setIndicationsLoading(false);
  };

  // Présentation, VMP ou UCD : l'utilisateur choisit le type dans la liste et saisit l'identifiant VIDAL ; voies et indications se chargent
  // sur la ressource du même type (comme pour la prescription).
  const chargerElement = async (idDirect = null, titre = null) => {
    const id = String(idDirect ?? idSaisi).trim();
    if (!/^\d+$/.test(id)) { toast.warning("Saisissez l'identifiant VIDAL de l'élément (un nombre)."); return; }
    setMedication({ vidal_id: id, title: titre || `${TYPES_ELEMENT[typeElement].libelle} n° ${id}` });
    setRoutes([]); setRouteId(""); setIndications([]); setIndicationRef("");
    setRoutesLoading(true); setIndicationsLoading(true);
    const [voies, indic] = await Promise.allSettled([
      apiClient.get(`/vidal/medicament/${typeElement}/${id}/routes`),
      apiClient.get(`/vidal/medicament/${typeElement}/${id}/indications`),
    ]);
    if (voies.status === "fulfilled") setRoutes((voies.value.data?.routes || []).map((r) => ({ id: r.id, name: r.label })));
    else toast.error(voies.reason?.response?.data?.detail || "Voies d'administration indisponibles");
    if (indic.status === "fulfilled") setIndications(indic.value.data?.indications || []);
    setRoutesLoading(false); setIndicationsLoading(false);
  };

  // Lot 376 (remarque VIDAL n°5) — VIDAL ne propose AUCUNE posologie sans l'âge, le poids et le sexe du patient : l'utilisateur en est informé
  const manquants = [
    !patient.dob ? "l'âge (date de naissance)" : null,
    patient.gender !== "MALE" && patient.gender !== "FEMALE" ? "le sexe (Homme ou Femme)" : null,
    !patient.weight ? "le poids" : null,
  ].filter(Boolean);

  const runSearch = async () => {
    if (!medication?.vidal_id) {
      toast.warning("Sélectionnez d'abord un médicament dans la recherche.");
      return;
    }
    setSearching(true);
    setResult(null);
    try {
      const ressource = RESSOURCE_POSOLOGIE[typeElement] || "product";
      // Lot 377 : POST avec le profil du patient (corps XML construit côté serveur, validé par Ster). Âge / sexe / poids absents : jamais bloquant,
      // le serveur renvoie `message` (alerte) à afficher.
      const r = await apiClient.post(`/vidal/${ressource}/${medication.vidal_id}/posology-descriptors`, {
        route: routeId || undefined,
        patient: {
          dateOfBirth: patient.dob || undefined, gender: patient.gender || undefined,
          weight: patient.weight || undefined, height: patient.height || undefined,
          hepaticInsufficiency: patient.hepatic || undefined,
        },
      });
      setResult(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Recherche de posologie impossible");
    }
    setSearching(false);
  };

  return (
    <div className="space-y-4" data-testid="vidal-posologie-page">
      <div className="flex items-center gap-3">
        {/* #FDECEC/#BB2323 = couleurs exactes de l'icône d'en-tête de la
            maquette d'origine (échantillonnées sur capture réelle), à la
            place du bleu générique — même rouge que Sécurisation. */}
        <div className="w-10 h-10 rounded-lg bg-[#BB2323]/10 dark:bg-[#BB2323]/20 ring-1 ring-[#BB2323]/25 flex items-center justify-center">
          <Stethoscope className="h-5 w-5 text-[#BB2323]" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-foreground">Posologie</h1>
          <p className="text-xs text-muted-foreground">
            Profil patient + médicament VIDAL réel → recherche de la posologie indiquée.
          </p>
        </div>
      </div>

      <Card data-testid="poso-experimental-banner" className="border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40">
        <CardContent className="pt-4 flex items-start gap-2 text-xs text-amber-800 dark:text-amber-200">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <p>
            La recherche de posologie ci-dessous appelle l'endpoint VIDAL
            <code className="mx-1 px-1 rounded bg-amber-100 dark:bg-amber-900">/product/{"{id}"}/posology-descriptors</code>
            qui n'a <strong>jamais été testé</strong> contre l'API VIDAL réelle (contrairement à la recherche, la fiche
            produit ou les équivalences). Considérez le résultat comme expérimental.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2"><Users className="h-4 w-4" /> Profil rapide</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {Object.entries(PROFILES).map(([key, p]) => (
            <Button key={key} type="button" size="sm" variant="outline" onClick={() => applyProfile(key)} data-testid={`poso-profile-${key}`}>
              {p.label}
            </Button>
          ))}
          <Button type="button" size="sm" variant="outline" onClick={() => applyProfile("allergique")} data-testid="poso-profile-allergique">
            Allergique (pénicilline)
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2"><User className="h-4 w-4" /> Patient</CardTitle>
        </CardHeader>
        <CardContent className="grid sm:grid-cols-4 gap-3">
          <div>
            <Label className="text-xs">Date de naissance</Label>
            <ChampDate avecAge className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm" value={patient.dob} onChange={(e) => setPatient({ ...patient, dob: e.target.value })} data-testid="poso-dob" />
          </div>
          <div>
            <Label className="text-xs">Genre</Label>
            <Select value={patient.gender} onValueChange={(v) => setPatient({ ...patient, gender: v })}>
              <SelectTrigger data-testid="poso-gender"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="MALE">Masculin</SelectItem>
                <SelectItem value="FEMALE">Féminin</SelectItem>
                <SelectItem value="UNKNOWN">Non précisé</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Insuffisance hépatique</Label>
            <Select value={patient.hepatic} onValueChange={(v) => setPatient({ ...patient, hepatic: v })}>
              <SelectTrigger data-testid="poso-hepatic"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="NONE">Aucune</SelectItem>
                <SelectItem value="MODERATE">Modérée</SelectItem>
                <SelectItem value="SEVERE">Sévère</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Taille (cm)</Label>
              <Input type="number" value={patient.height} onChange={(e) => setPatient({ ...patient, height: e.target.value })} data-testid="poso-height" />
            </div>
            <div>
              <Label className="text-xs">Poids (kg)</Label>
              <Input type="number" value={patient.weight} onChange={(e) => setPatient({ ...patient, weight: e.target.value })} data-testid="poso-weight" />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2"><Baby className="h-4 w-4" /> Allergies, pathologies, molécules</CardTitle>
        </CardHeader>
        <CardContent className="grid sm:grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">Allergies</Label>
            <Input value={allergies} onChange={(e) => setAllergies(e.target.value)} placeholder="pénicilline, arachide…" data-testid="poso-allergies" />
          </div>
          <div>
            <Label className="text-xs">Pathologies (CIM10)</Label>
            <Input value={pathologies} onChange={(e) => setPathologies(e.target.value)} placeholder="diabète, insuffisance rénale…" data-testid="poso-pathologies" />
          </div>
          <div>
            <Label className="text-xs">Autres molécules en cours</Label>
            <Input value={molecules} onChange={(e) => setMolecules(e.target.value)} placeholder="warfarine…" data-testid="poso-molecules" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2"><Pill className="h-4 w-4" /> Médicament</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid sm:grid-cols-[220px_1fr] gap-3" data-testid="poso-type-element">
            <div>
              <Label className="text-xs flex items-center gap-1"><Pastille type={TYPES_ELEMENT[typeElement].pastille} /> Type d'élément</Label>
              <Select value={typeElement} onValueChange={(v) => { setTypeElement(v); setMedication(null); setRoutes([]); setRouteId(""); setIndications([]); setIndicationRef(""); setIdSaisi(""); }}>
                <SelectTrigger data-testid="poso-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(TYPES_ELEMENT).map(([k, t]) => <SelectItem key={k} value={k}>{t.libelle}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {typeElement !== "PRODUCT" && (
              <div>
                <Label className="text-xs">Identifiant VIDAL du {TYPES_ELEMENT[typeElement].libelle}</Label>
                <div className="flex gap-2">
                  <Input value={idSaisi} inputMode="numeric" onChange={(e) => setIdSaisi(e.target.value)} placeholder="ex. 12345" data-testid="poso-id-element"
                         onKeyDown={(e) => { if (e.key === "Enter") chargerElement(); }} />
                  <Button type="button" variant="outline" onClick={() => chargerElement()} data-testid="poso-charger-element">Charger</Button>
                </div>
              </div>
            )}
          </div>
          {typeElement === "PRODUCT" && <VidalMedicationSearch
            query={medication?.title ? medication.title : medQuery}
            onQueryChange={(q) => { setMedQuery(q); setMedication(null); setRoutes([]); setRouteId(""); setIndications([]); setIndicationRef(""); }}
            onSelect={selectMedication}
            onClear={() => { setMedQuery(""); setMedication(null); setRoutes([]); setRouteId(""); setIndications([]); setIndicationRef(""); }}
            testId="poso-med-search"
          />}
          {/* Lot 378 (remarque 8) : recherche PAR NOM d'une présentation, d'un VMP ou d'une UCD (l'identifiant reste saisissable ci-dessus) */}
          {typeElement !== "PRODUCT" && <VidalMedicationSearch
            key={typeElement}
            typeRecherche={RESSOURCE_POSOLOGIE[typeElement]} pastille={TYPES_ELEMENT[typeElement].pastille}
            placeholder={`Nom du ${TYPES_ELEMENT[typeElement].libelle.toLowerCase()}…`}
            query={medQuery} onQueryChange={setMedQuery} onClear={() => setMedQuery("")}
            onSelect={(item) => { setMedQuery(item.title); chargerElement(item.vidal_id, item.title); }}
            testId="poso-element-search"
          />}
          {medication?.title && typeElement !== "PRODUCT" && <div className="text-xs text-muted-foreground flex items-center gap-1"><Pastille type={TYPES_ELEMENT[typeElement].pastille} /> {medication.title}</div>}
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-xs flex items-center gap-1">
                Voie d'administration
                {routesLoading && <Loader2 className="h-3 w-3 animate-spin" />}
              </Label>
              <Select value={routeId} onValueChange={setRouteId} disabled={!routes.length}>
                <SelectTrigger data-testid="poso-route"><SelectValue placeholder={routes.length ? "Choisir…" : "Sélectionnez un médicament d'abord"} /></SelectTrigger>
                <SelectContent>
                  {routes.map((r) => (
                    <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs flex items-center gap-1">
                Indication
                {indicationsLoading && <Loader2 className="h-3 w-3 animate-spin" />}
              </Label>
              <Select value={indicationRef} onValueChange={setIndicationRef} disabled={!indications.length}>
                <SelectTrigger data-testid="poso-indication"><SelectValue placeholder={indications.length ? "Choisir…" : "Sélectionnez un médicament d'abord"} /></SelectTrigger>
                <SelectContent>
                  {indications.map((ind) => (
                    <SelectItem key={ind.ref} value={ind.ref}>{ind.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* #9C1616 = rouge exact du bouton d'action de la maquette d'origine
          (échantillonné sur capture réelle), pleine largeur — remplace le
          bleu par défaut, pour un rendu identique à Sécurisation. */}
      {manquants.length > 0 && (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 flex items-start gap-2" data-testid="poso-profil-incomplet">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>
            <strong>Profil patient incomplet.</strong> VIDAL ne propose <strong>aucune posologie</strong> sans l'âge, le poids et le sexe du patient :
            il manque {manquants.join(", ")}. Ce n'est pas bloquant : vous pouvez lancer la recherche, mais VIDAL n'en proposera aucune tant que ces informations manquent.
          </span>
        </div>
      )}
      <div className="flex justify-end"><LegendePastilles types={["SPECIALITE", "PRESENTATION", "VMP", "UCD"]} /></div>
      <Button
        onClick={runSearch} disabled={searching} data-testid="poso-search-submit"
        className="w-full bg-[#9C1616] hover:bg-[#7F1212] text-white"
      >
        {searching ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
        Rechercher la posologie indiquée
      </Button>

      {result && (
        <Card data-testid="poso-result">
          <CardHeader>
            <CardTitle className="text-sm">Posologies proposées par VIDAL</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {result.message && (
              <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900 flex items-start gap-2" data-testid="poso-message">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" /><span>{result.message}</span>
              </div>
            )}
            {(result.descripteurs || []).map((d, i) => (
              <div key={i} className="rounded border p-2" data-testid={`poso-descripteur-${i}`}>
                {d.indication && <div className="font-medium">{d.indication}{d.route ? ` — ${d.route}` : ""}</div>}
                {d.doses.map((x) => <div key={x}>{x}</div>)}
                {d.frequence && <div className="text-muted-foreground">{d.frequence}</div>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {vidalAdminNotes && (
        <Card className="border-dashed" data-testid="poso-admin-notes">
          <CardContent className="pt-6 text-xs text-muted-foreground space-y-1">
            <p className="font-semibold text-foreground">Notes VIDAL (admin)</p>
            <p>Champs réels, confirmés contre le manuel MI_APIREST REV_03 : recherche médicament, voies
              d'administration (/detail) et indications (/product/{"{id}"}/indications).</p>
            <p>Non confirmé : le résultat de /posology-descriptors lui-même — endpoint jamais appelé en
              conditions réelles.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
