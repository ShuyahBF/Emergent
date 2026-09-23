// ocr-core (module commun, source unique : dépôt ShuyahBF/Claude, dossier ocr-core/).
// Ne pas modifier dans un site : corriger dans ocr-core puis resynchroniser.
//
// Panneau « Analyses IA » d'une pièce, côté cabinet (staff) :
//  - une puce par analyse (modèle · coût FCFA · note) pour comparer les modèles ;
//  - relance de la même pièce avec un autre modèle ;
//  - détail de l'analyse choisie + évaluation humaine (étoiles, corrections).
// Le serveur calcule la précision réelle à partir des corrections ; les
// simples différences de format ("150 000" vs 150000) ne comptent pas.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import StarRating from "./StarRating";
import { displayValue, errorMessage, formatDuration, formatPercent, formatXof, shortModel } from "./format";

// Valeur éditable (texte) d'un champ : listes/objets en JSON.
function toEditable(value) {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
}

// Texte saisi → valeur : JSON si le champ d'origine était une liste/un objet.
function fromEditable(text, original) {
  if (original !== null && typeof original === "object") {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

// Contrat d'API commun (voir ocr-core/README.md) — `apiBase` vaut par ex.
// "/documents" (Albarka) ou "/ocr-pieces" (Sawali) :
//   GET  {apiBase}/{id}                      → { ..., ocr_runs: [analyses] }
//   POST {apiBase}/{id}/reanalyze            ← { model }
//   POST {apiBase}/ocr-runs/{runId}/review   ← { rating, comment, corrected_fields }
export default function OcrRunsPanel({ apiBase = "/documents", doc, models, defaultModel, onChanged }) {
  const [runs, setRuns] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [rerunModel, setRerunModel] = useState(defaultModel || "");

  // Recharge les analyses de la pièce ; garde l'analyse affichée si elle
  // existe encore, sinon montre la plus récente.
  const load = useCallback(async (keepId = null) => {
    try {
      const { data } = await apiClient.get(`${apiBase}/${doc.id}`);
      const list = data.ocr_runs || [];
      setRuns(list);
      const stillThere = keepId && list.some((r) => r.id === keepId);
      setSelectedId(stillThere ? keepId : list.length ? list[list.length - 1].id : null);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }, [apiBase, doc.id]);

  // Rechargé à l'ouverture et à chaque changement de statut (fin d'analyse).
  useEffect(() => { load(); }, [load, doc.status]);
  useEffect(() => { if (!rerunModel && defaultModel) setRerunModel(defaultModel); }, [defaultModel, rerunModel]);

  const rerun = async () => {
    try {
      await apiClient.post(`${apiBase}/${doc.id}/reanalyze`, { model: rerunModel });
      toast.success(`Analyse relancée avec ${shortModel(rerunModel)}…`);
      onChanged?.();
    } catch (err) {
      toast.error(errorMessage(err, "Impossible de relancer l'analyse"));
    }
  };

  const selected = runs.find((r) => r.id === selectedId);

  return (
    <div className="space-y-4" data-testid={`ocr-panel-${doc.id}`}>
      {/* Puces des analyses + relance avec un autre modèle */}
      <div className="flex flex-wrap items-center gap-2">
        {runs.map((run, i) => (
          <button
            key={run.id}
            type="button"
            onClick={() => setSelectedId(run.id)}
            className={`text-xs rounded-full border px-3 py-1 ${run.id === selectedId
              ? "bg-primary text-primary-foreground border-primary" : "bg-background hover:bg-muted"}`}
          >
            #{i + 1} {shortModel(run.model)} · {formatXof(run.cost_xof)}
            {run.review ? ` · ${run.review.rating}★` : " · à évaluer"}
          </button>
        ))}
        <div className="flex flex-wrap items-center gap-2 md:ml-auto">
          <Select value={rerunModel} onValueChange={setRerunModel}>
            <SelectTrigger className="w-64 h-9 bg-background" data-testid={`ocr-rerun-model-${doc.id}`}>
              <SelectValue placeholder="Modèle d'IA" />
            </SelectTrigger>
            <SelectContent>
              {models.map((m) => <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button size="sm" variant="outline" onClick={rerun} disabled={doc.status === "en_analyse" || !rerunModel}
            data-testid={`ocr-rerun-${doc.id}`}>
            <RefreshCw className="w-4 h-4 mr-1" /> Relancer avec ce modèle
          </Button>
        </div>
      </div>

      {doc.status === "en_analyse" && (
        <div className="text-sm text-muted-foreground">Analyse IA en cours…</div>
      )}
      {selected ? (
        <RunReview key={selected.id} apiBase={apiBase} run={selected} onReviewed={() => { load(selected.id); onChanged?.(); }} />
      ) : (
        doc.status !== "en_analyse" && <div className="text-sm text-muted-foreground">Aucune analyse disponible.</div>
      )}
    </div>
  );
}

// Détail d'UNE analyse + formulaire d'évaluation.
function RunReview({ apiBase, run, onReviewed }) {
  const extracted = useMemo(() => run.extracted_fields || {}, [run]);
  const uncertain = useMemo(() => new Set(run.uncertain_fields || []), [run]);
  const review = run.review;

  const [rating, setRating] = useState(review?.rating || 0);
  const [comment, setComment] = useState(review?.comment || "");
  const [values, setValues] = useState(() => {
    const corrected = review?.corrected_fields || {};
    const init = {};
    Object.entries(extracted).forEach(([k, v]) => { init[k] = toEditable(k in corrected ? corrected[k] : v); });
    return init;
  });
  // Champs oubliés par l'IA (comptent comme erreurs dans la précision).
  const [extra, setExtra] = useState(() => Object.entries(review?.corrected_fields || {})
    .filter(([k]) => !(k in extracted)).map(([key, value]) => ({ key, value: toEditable(value) })));
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!rating) {
      toast.error("Choisissez une note de 1 à 5 étoiles");
      return;
    }
    // Tous les champs sont envoyés : le serveur ne retient que ceux qui ont changé.
    const corrected = {};
    Object.entries(values).forEach(([k, text]) => { corrected[k] = fromEditable(text, extracted[k]); });
    extra.forEach(({ key, value }) => { if (key.trim()) corrected[key.trim()] = value; });
    setSaving(true);
    try {
      const { data } = await apiClient.post(`${apiBase}/ocr-runs/${run.id}/review`, {
        rating, comment, corrected_fields: corrected,
      });
      toast.success(`Évaluation enregistrée — précision réelle : ${formatPercent(data.accuracy)}`);
      onReviewed?.();
    } catch (err) {
      toast.error(errorMessage(err, "Échec de l'enregistrement"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Métriques : modèle, coût réel, tokens, durée, mode d'envoi */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
        <Metric label="Modèle" value={shortModel(run.model)} />
        <Metric label="Coût réel" value={formatXof(run.cost_xof)} />
        <Metric label="Tokens (entrée / sortie)" value={`${run.input_tokens ?? 0} / ${run.output_tokens ?? 0}`} />
        <Metric label="Durée · envoi" value={`${formatDuration(run.duration_ms)} · ${run.input_mode === "texte" ? "texte" : `${run.pages_analyzed || 0} image(s)`}`} />
      </div>

      {run.document_type_guess && (
        <div className="text-sm"><span className="text-muted-foreground">Type détecté : </span>
          <span className="font-medium">{run.document_type_guess}</span></div>
      )}
      {run.summary && <div className="text-sm leading-relaxed">{run.summary}</div>}
      <div className="text-xs text-muted-foreground">
        Confiance déclarée par le modèle : {formatPercent(run.confidence)} — indicative ; seule votre
        relecture ci-dessous mesure la précision réelle.
      </div>
      {run.flags?.length > 0 && (
        <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
          ⚠︎ {run.flags.join(" · ")}
        </div>
      )}

      {/* Champs extraits, corrigeables — orange = jugé incertain par le modèle */}
      {Object.keys(extracted).length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-semibold">Champs extraits (corrigez ce qui est faux)</div>
          {Object.entries(extracted).map(([key, original]) => {
            const isObject = original !== null && typeof original === "object";
            const changed = (values[key] ?? "") !== toEditable(original);
            const setVal = (e) => setValues((v) => ({ ...v, [key]: e.target.value }));
            return (
              <div key={key} className="grid grid-cols-1 md:grid-cols-3 gap-1 md:gap-3 items-start">
                <label className={`text-xs uppercase tracking-wider pt-2 ${uncertain.has(key) ? "text-amber-700 font-semibold" : "text-muted-foreground"}`}>
                  {key}{uncertain.has(key) && " (incertain)"}
                </label>
                <div className="md:col-span-2">
                  {isObject ? (
                    <Textarea rows={4} value={values[key] ?? ""} onChange={setVal}
                      className={`font-mono text-xs bg-background ${changed ? "border-blue-500" : ""}`} />
                  ) : (
                    <Input value={values[key] ?? ""} onChange={setVal}
                      className={`${uncertain.has(key) ? "bg-amber-50" : "bg-background"} ${changed ? "border-blue-500" : ""}`} />
                  )}
                  {changed && (
                    <div className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap">
                      Extrait par l'IA : {displayValue(original)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="space-y-2">
        {extra.map((f, i) => (
          <div key={i} className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <Input placeholder="Nom du champ (ex. ifu)" value={f.key} className="bg-background"
              onChange={(e) => setExtra((l) => l.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} />
            <Input placeholder="Valeur correcte" value={f.value} className="md:col-span-2 bg-background"
              onChange={(e) => setExtra((l) => l.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => setExtra((l) => [...l, { key: "", value: "" }])}>
          + Champ oublié par l'IA
        </Button>
      </div>

      {/* Note globale + commentaire */}
      <div className="border-t border-border pt-3 space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-semibold">Votre note :</span>
          <StarRating value={rating} onChange={setRating} size={22} />
          {review && (
            <span className="rounded-full px-2 py-0.5 text-xs bg-emerald-100 text-emerald-800">
              Évaluée · précision {formatPercent(review.accuracy)} ({review.fields_corrected}/{review.fields_total} corrigés)
            </span>
          )}
        </div>
        <Textarea rows={2} className="bg-background" value={comment} onChange={(e) => setComment(e.target.value)}
          placeholder="Commentaire (facultatif) : ce qui est faux, manuscrit mal lu, tampon…" />
        <Button onClick={submit} disabled={saving} data-testid={`ocr-review-submit-${run.id}`}>
          {saving ? "Enregistrement…" : review ? "Mettre à jour l'évaluation" : "Enregistrer l'évaluation"}
        </Button>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded border border-border bg-background px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}
