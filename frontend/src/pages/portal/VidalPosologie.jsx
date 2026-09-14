// Portage site-meetafrican (frontend/src/secure/content/posologie.html) —
// module Posologie : profil patient (chips + champs détaillés), sélection
// réelle du médicament (recherche VIDAL, remplace la maquette 100% simulée),
// voie d'administration ET indication réelles (confirmées contre le manuel
// VIDAL, voir /vidal/product/{id}/detail et /vidal/product/{id}/indications),
// et recherche de posologie EXPÉRIMENTALE (endpoint /posology-descriptors
// jamais validé en réel, contrairement aux deux listes ci-dessus).
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
import { AlertTriangle, Baby, Loader2, Pill, Stethoscope, User, Users } from "lucide-react";
import VidalMedicationSearch from "@/components/VidalMedicationSearch";
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

export default function VidalPosologie() {
  const { vidalAdminNotes } = useVidalUiSettings();
  const [patient, setPatient] = useState(emptyPatient);
  const [allergies, setAllergies] = useState("");
  const [pathologies, setPathologies] = useState("");
  const [molecules, setMolecules] = useState("");

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

  const runSearch = async () => {
    if (!medication?.vidal_id) {
      toast.warning("Sélectionnez d'abord un médicament dans la recherche.");
      return;
    }
    setSearching(true);
    setResult(null);
    try {
      const r = await apiClient.get(`/vidal/product/${medication.vidal_id}/posology-descriptors`, {
        params: {
          route: routeId || undefined,
          indication: indicationRef || undefined,
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
        <div className="w-10 h-10 rounded-lg bg-primary/10 ring-1 ring-primary/20 flex items-center justify-center">
          <Stethoscope className="h-5 w-5 text-primary" />
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
            <Input type="date" value={patient.dob} onChange={(e) => setPatient({ ...patient, dob: e.target.value })} data-testid="poso-dob" />
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
          <VidalMedicationSearch
            query={medication?.title ? medication.title : medQuery}
            onQueryChange={(q) => { setMedQuery(q); setMedication(null); setRoutes([]); setRouteId(""); setIndications([]); setIndicationRef(""); }}
            onSelect={selectMedication}
            onClear={() => { setMedQuery(""); setMedication(null); setRoutes([]); setRouteId(""); setIndications([]); setIndicationRef(""); }}
            testId="poso-med-search"
          />
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

      <Button onClick={runSearch} disabled={searching} data-testid="poso-search-submit">
        {searching ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Stethoscope className="h-4 w-4 mr-2" />}
        Rechercher la posologie indiquée
      </Button>

      {result && (
        <Card data-testid="poso-result">
          <CardHeader>
            <CardTitle className="text-sm text-amber-700 dark:text-amber-300">Résultat (expérimental)</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-[11px] bg-muted rounded p-3 overflow-auto max-h-96">
              {JSON.stringify(result.data?.raw ? { raw: result.data.raw } : result.data, null, 2).slice(0, 8000)}
            </pre>
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
