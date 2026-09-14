// Portage site-meetafrican (frontend/src/secure/content/securisation.html) —
// remplace "Analyse prescription" pour les médecins. Schéma XML réel
// (manuel VIDAL, voir backend/routes/vidal_securisation.py), calculateurs
// IMC + clairance de Cockcroft & Gault, 18 types d'alerte réels, recherche
// médicament réelle + voie d'administration réelle par produit.
//
// Ce qui reste volontairement informatif (non transmis à VIDAL) : allergies/
// pathologies/molécules (nécessiteraient une recherche référentielle jamais
// testée en réel) et le champ "indication" par ligne — même limite déjà
// actée pour Posologie, pas d'invention de référence VIDAL.
import React, { useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { AlertTriangle, Loader2, Plus, ShieldCheck, X } from "lucide-react";
import VidalMedicationSearch from "@/components/VidalMedicationSearch";
import { useVidalUiSettings } from "@/contexts/VidalUiSettingsContext";

const ALERT_TYPE_LABELS = {
  CONTRA_INDICATION: "Contre-indication", ALLERGY: "Allergie",
  DRUG_INTERACTION: "Interaction médicamenteuse", POSOLOGY: "Posologie",
  PRECAUTION: "Précaution", WARNING: "Mise en garde", SIDE_EFFECT: "Effet indésirable",
  PHYSICO_CHEMICAL_INTERACTION: "Interaction physico-chimique", SURVEILLANCE: "Surveillance",
  REDUNDANT_ACTIVE_INGREDIENT: "Principe actif redondant", SAME_DRUG: "Même médicament",
  FOOD_INTERACTION: "Interaction alimentaire", DISPENSING_RISK: "Risque de dispensation",
  PRESCRIPTION_CONTEXT: "Contexte patient", EXONERATION: "Exonération",
  INDICATOR: "Indicateur", FOCUS: "Point de vigilance", HAS: "Alerte HAS (SAM)",
};
const DEFAULT_ALERT_TYPES = ["CONTRA_INDICATION", "ALLERGY", "DRUG_INTERACTION", "POSOLOGY"];

function computeAge(dob) {
  if (!dob) return null;
  const d = new Date(dob);
  if (Number.isNaN(d.getTime())) return null;
  const diff = Date.now() - d.getTime();
  return Math.floor(diff / (365.25 * 24 * 3600 * 1000));
}
// Cockcroft & Gault — clairance créatinine estimée (mL/min). VIDAL attend
// cette clairance (balise <creatin>), pas la créatininémie brute.
function computeClairance(dob, gender, weight, creat) {
  const age = computeAge(dob);
  const w = Number(weight), c = Number(creat);
  if (age == null || !w || !c || (gender !== "MALE" && gender !== "FEMALE")) return null;
  const factor = gender === "MALE" ? 1.23 : 1.04;
  return (factor * w * (140 - age)) / c;
}
function computeBmi(weight, height) {
  const w = Number(weight), h = Number(height);
  if (!w || !h) return null;
  const m = h / 100;
  return w / (m * m);
}

function emptyLine() {
  return { vidal_id: "", label: "", query: "", dose: "", unitId: "", duration: "", durationType: "", frequencyType: "", route: "", routes: [], routesLoading: false };
}

function TagInput({ label, hint, values, onChange, testId }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    onChange([...values, v]);
    setDraft("");
  };
  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <div className="flex flex-wrap gap-1.5 p-2 rounded border min-h-[42px]" data-testid={testId}>
        {values.map((v, i) => (
          <span key={i} className="inline-flex items-center gap-1 text-xs bg-muted rounded-full px-2.5 py-1">
            {v}
            <button type="button" onClick={() => onChange(values.filter((_, j) => j !== i))}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="Ajouter… (Entrée)"
          className="flex-1 min-w-[100px] text-xs outline-none bg-transparent"
        />
      </div>
      {hint && <p className="text-[10px] text-muted-foreground mt-1">{hint}</p>}
    </div>
  );
}

function MedicationLine({ line, onChange, onRemove, testId }) {
  const selectMedication = async (item) => {
    onChange({ vidal_id: item.vidal_id || "", label: item.title || "", query: "", route: "", routes: [], routesLoading: true });
    if (!item.vidal_id) return;
    try {
      const r = await apiClient.get(`/vidal/product/${item.vidal_id}/detail`);
      onChange({ routes: r.data?.routes || [], routesLoading: false });
    } catch {
      onChange({ routesLoading: false });
    }
  };
  return (
    <div className="rounded-lg border p-3 space-y-2.5" data-testid={testId}>
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <VidalMedicationSearch
            query={line.label || line.query}
            onQueryChange={(q) => onChange({ query: q, label: "", vidal_id: "", routes: [], route: "" })}
            onSelect={selectMedication}
            onClear={() => onChange({ query: "", label: "", vidal_id: "", routes: [], route: "" })}
            testId={`${testId}-search`}
          />
        </div>
        <Button type="button" variant="ghost" size="icon" onClick={onRemove} data-testid={`${testId}-remove`}>
          <X className="h-4 w-4" />
        </Button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <Input placeholder="Dose" value={line.dose} onChange={(e) => onChange({ dose: e.target.value })} data-testid={`${testId}-dose`} />
        <Input placeholder="Fréquence" value={line.frequencyType} onChange={(e) => onChange({ frequencyType: e.target.value })} data-testid={`${testId}-frequency`} />
        <Input placeholder="Durée" value={line.duration} onChange={(e) => onChange({ duration: e.target.value })} data-testid={`${testId}-duration`} />
        <Input placeholder="Unité durée" value={line.durationType} onChange={(e) => onChange({ durationType: e.target.value })} data-testid={`${testId}-duration-type`} />
        <Select value={line.route} onValueChange={(v) => onChange({ route: v })} disabled={!line.routes.length}>
          <SelectTrigger data-testid={`${testId}-route`}><SelectValue placeholder={line.routes.length ? "Voie" : "—"} /></SelectTrigger>
          <SelectContent>
            {line.routes.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export default function VidalSecurisation() {
  const { vidalAdminNotes } = useVidalUiSettings();
  const [dob, setDob] = useState("");
  const [gender, setGender] = useState("FEMALE");
  const [weight, setWeight] = useState("");
  const [height, setHeight] = useState("");
  const [creatinine, setCreatinine] = useState("");
  const [hepatic, setHepatic] = useState("NONE");
  const [allergies, setAllergies] = useState([]);
  const [pathologies, setPathologies] = useState([]);
  const [molecules, setMolecules] = useState([]);

  const [currentTreatments, setCurrentTreatments] = useState([]);
  const [newLines, setNewLines] = useState([emptyLine()]);
  const [alertTypes, setAlertTypes] = useState(DEFAULT_ALERT_TYPES);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [errorState, setErrorState] = useState(null);

  const clairance = computeClairance(dob, gender, weight, creatinine);
  const bmi = computeBmi(weight, height);

  const updateLine = (list, setList, idx, patch) =>
    setList(list.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  const toggleAlertType = (t) =>
    setAlertTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const toLinePayload = (l) => ({
    drugRef: l.vidal_id || null, dose: l.dose || null, durationType: l.durationType || null,
    duration: l.duration || null, frequencyType: l.frequencyType || null, route: l.route || null,
  });

  const run = async () => {
    const hasLine = [...currentTreatments, ...newLines].some((l) => l.vidal_id);
    if (!hasLine) {
      toast.warning("Ajoutez au moins un médicament (recherche VIDAL) avant de sécuriser.");
      return;
    }
    setLoading(true);
    setErrorState(null);
    setResult(null);
    try {
      const r = await apiClient.post("/vidal/securisation/analyze", {
        patient: {
          dateOfBirth: dob || null,
          gender,
          weight: weight || null,
          height: height || null,
          clairance,
          hepaticInsufficiency: hepatic,
        },
        current_treatments: currentTreatments.filter((l) => l.vidal_id).map(toLinePayload),
        new_prescription_lines: newLines.filter((l) => l.vidal_id).map(toLinePayload),
        alert_types: alertTypes,
      });
      setResult(r.data);
    } catch (e) {
      const detail = e?.response?.data?.detail || e?.message || "Erreur inconnue";
      setErrorState(detail);
      toast.error(detail);
    }
    setLoading(false);
  };

  return (
    <div className="space-y-4" data-testid="vidal-securisation-page">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-rose-100 dark:bg-rose-950 ring-1 ring-rose-200 dark:ring-rose-800 flex items-center justify-center">
          <ShieldCheck className="h-5 w-5 text-rose-600 dark:text-rose-400" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-foreground">Sécurisation</h1>
          <p className="text-xs text-muted-foreground">Analyse VIDAL — interactions, contre-indications, posologie.</p>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Profil du patient</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid sm:grid-cols-4 gap-3">
            <div>
              <Label className="text-xs">Date de naissance</Label>
              <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} data-testid="sec-dob" />
            </div>
            <div>
              <Label className="text-xs">Sexe</Label>
              <Select value={gender} onValueChange={setGender}>
                <SelectTrigger data-testid="sec-gender"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="MALE">Homme</SelectItem>
                  <SelectItem value="FEMALE">Femme</SelectItem>
                  <SelectItem value="UNKNOWN">Indéterminé</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Poids (kg)</Label>
              <Input type="number" value={weight} onChange={(e) => setWeight(e.target.value)} data-testid="sec-weight" />
            </div>
            <div>
              <Label className="text-xs">Taille (cm)</Label>
              <Input type="number" value={height} onChange={(e) => setHeight(e.target.value)} data-testid="sec-height" />
            </div>
          </div>
          {bmi != null && (
            <p className="text-xs text-muted-foreground" data-testid="sec-bmi">
              IMC (indicatif, non transmis à VIDAL) : <strong>{bmi.toFixed(1)} kg/m²</strong>
            </p>
          )}
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Créatininémie (µmol/L)</Label>
              <Input type="number" value={creatinine} onChange={(e) => setCreatinine(e.target.value)} placeholder="ex : 70" data-testid="sec-creatinine" />
              {clairance != null && (
                <p className="text-[10px] text-muted-foreground mt-1">
                  Clairance estimée (Cockcroft &amp; Gault), envoyée à VIDAL : <strong>{clairance.toFixed(1)} mL/min</strong>
                </p>
              )}
            </div>
            <div>
              <Label className="text-xs">Insuffisance hépatique</Label>
              <Select value={hepatic} onValueChange={setHepatic}>
                <SelectTrigger data-testid="sec-hepatic"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="NONE">Aucune</SelectItem>
                  <SelectItem value="MODERATE">Modérée</SelectItem>
                  <SelectItem value="SEVERE">Sévère</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <TagInput label="Allergies connues" values={allergies} onChange={setAllergies} testId="sec-allergies"
              hint="Informatif — non transmis à VIDAL (recherche référentielle non branchée)." />
            <TagInput label="Pathologies connues" values={pathologies} onChange={setPathologies} testId="sec-pathologies"
              hint="Informatif — non transmis à VIDAL." />
            <TagInput label="Molécules à éviter" values={molecules} onChange={setMolecules} testId="sec-molecules"
              hint="Informatif — non transmis à VIDAL." />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Traitements en cours</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {currentTreatments.map((line, idx) => (
            <MedicationLine
              key={idx} line={line} testId={`sec-prev-${idx}`}
              onChange={(patch) => updateLine(currentTreatments, setCurrentTreatments, idx, patch)}
              onRemove={() => setCurrentTreatments(currentTreatments.filter((_, i) => i !== idx))}
            />
          ))}
          <Button type="button" variant="outline" size="sm" onClick={() => setCurrentTreatments([...currentTreatments, emptyLine()])} data-testid="sec-prev-add">
            <Plus className="h-3.5 w-3.5 mr-1.5" /> Ajouter un traitement en cours
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Nouvelle prescription</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {newLines.map((line, idx) => (
            <MedicationLine
              key={idx} line={line} testId={`sec-new-${idx}`}
              onChange={(patch) => updateLine(newLines, setNewLines, idx, patch)}
              onRemove={() => newLines.length > 1 && setNewLines(newLines.filter((_, i) => i !== idx))}
            />
          ))}
          <Button type="button" variant="outline" size="sm" onClick={() => setNewLines([...newLines, emptyLine()])} data-testid="sec-new-add">
            <Plus className="h-3.5 w-3.5 mr-1.5" /> Ajouter un médicament
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Alertes à vérifier</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {Object.entries(ALERT_TYPE_LABELS).map(([code, label]) => (
            <button
              key={code} type="button" onClick={() => toggleAlertType(code)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                alertTypes.includes(code) ? "bg-primary text-primary-foreground border-primary" : "bg-transparent text-muted-foreground"
              }`}
              data-testid={`sec-alert-${code}`}
            >
              {label}
            </button>
          ))}
        </CardContent>
      </Card>

      <Button onClick={run} disabled={loading} data-testid="sec-submit">
        {loading ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <ShieldCheck className="h-4 w-4 mr-2" />}
        Sécuriser
      </Button>

      {errorState && (
        <Card className="border-amber-300 dark:border-amber-700" data-testid="sec-error">
          <CardContent className="pt-4 flex items-start gap-2 text-xs text-amber-800 dark:text-amber-200">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> {errorState}
          </CardContent>
        </Card>
      )}

      {result && (
        <Card data-testid="sec-result">
          <CardHeader><CardTitle className="text-sm">Réponse VIDAL</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <Badge variant="outline">Analyse envoyée</Badge>
            <p className="text-xs text-muted-foreground">
              Affichage brut de la réponse VIDAL ci-dessous — le format exact de{" "}
              <code className="px-1 rounded bg-muted">/alerts/full</code> n'a pas encore été validé en conditions
              réelles dans ce projet ; une vue structurée (cartes d'alertes par gravité) suivra une fois ce format confirmé.
            </p>
            <pre className="text-[11px] bg-muted rounded p-3 overflow-auto max-h-96">
              {JSON.stringify(result.data?.raw ? { raw: result.data.raw } : result.data, null, 2).slice(0, 8000)}
            </pre>
          </CardContent>
        </Card>
      )}

      {vidalAdminNotes && (
        <Card className="border-dashed" data-testid="sec-admin-notes">
          <CardContent className="pt-6 text-xs text-muted-foreground space-y-1">
            <p className="font-semibold text-foreground">Notes VIDAL (admin)</p>
            <p>Schéma XML (patient/prescription-lines/alert-types) vérifié contre le manuel d'intégration VIDAL — voir backend/routes/vidal_securisation.py.</p>
            <p>Allergies/pathologies/molécules et l'indication par ligne restent informatifs : aucune référence VIDAL fiable disponible sans recherche référentielle testée en réel.</p>
            <p>Le format de réponse réel de /alerts/full n'a pas été validé — la vue structurée par gravité (critique/précaution/info) est différée jusqu'à confirmation.</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
