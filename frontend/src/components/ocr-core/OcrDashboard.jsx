// ocr-core (module commun, source unique : dépôt ShuyahBF/Claude, dossier ocr-core/).
// Ne pas modifier dans un site : corriger dans ocr-core puis resynchroniser.
//
// Tableau de bord OCR (cabinet) : par période et par modèle — nombre de
// pièces analysées, coût cumulé et moyen en FCFA, note et précision
// moyennes (évaluations humaines), confiance déclarée, durée moyenne.
// Sert à choisir le modèle au meilleur rapport précision / coût.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import StarRating from "./StarRating";
import { errorMessage, formatDuration, formatPercent, formatXof } from "./format";

const PERIODS = [
  { value: "today", label: "Aujourd'hui" },
  { value: "7d", label: "7 derniers jours" },
  { value: "30d", label: "30 derniers jours" },
  { value: "all", label: "Depuis le début" },
];

// Contrat d'API commun : GET {apiBase}/ocr-stats?period=today|7d|30d|all
export default function OcrDashboard({ apiBase = "/documents" }) {
  const [period, setPeriod] = useState("30d");
  const [stats, setStats] = useState(null);

  const load = useCallback(async () => {
    try {
      const { data } = await apiClient.get(`${apiBase}/ocr-stats`, { params: { period } });
      setStats(data);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }, [apiBase, period]);

  useEffect(() => { load(); }, [load]);
  const total = stats?.total;

  return (
    <div className="space-y-4" data-testid="ocr-dashboard">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          Coûts calculés sur les tokens réellement consommés · 1 USD = {stats?.usd_to_xof_rate ?? "…"} FCFA
        </p>
        <Select value={period} onValueChange={setPeriod}>
          <SelectTrigger className="w-56 bg-background" data-testid="ocr-period"><SelectValue /></SelectTrigger>
          <SelectContent>
            {PERIODS.map((p) => <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi title="Pièces analysées" value={total ? total.runs : "—"}
          hint={total ? `${total.reviewed} évaluée(s) · ${total.errors} en erreur` : ""} />
        <Kpi title="Coût cumulé" value={formatXof(total?.total_cost_xof)} />
        <Kpi title="Coût moyen par pièce" value={formatXof(total?.avg_cost_xof)} />
        <Kpi title="Précision réelle moyenne" value={formatPercent(total?.avg_accuracy)}
          hint={total?.avg_rating ? `Note moyenne ${total.avg_rating.toFixed(1)} / 5` : "Aucune évaluation"} />
      </div>

      <div className="rounded-lg border bg-card overflow-x-auto">
        <div className="p-4 border-b border-border">
          <div className="font-semibold">Comparaison des modèles</div>
          <div className="text-xs text-muted-foreground mt-1">
            La note et la précision réelle viennent uniquement de vos évaluations. La confiance est
            celle que le modèle s'attribue lui-même : elle n'est pas une garantie.
          </div>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Modèle</TableHead>
              <TableHead className="text-right">Pièces</TableHead>
              <TableHead className="text-right">Coût cumulé</TableHead>
              <TableHead className="text-right">Coût moyen</TableHead>
              <TableHead>Note moyenne</TableHead>
              <TableHead className="text-right">Précision réelle</TableHead>
              <TableHead className="text-right">Confiance déclarée</TableHead>
              <TableHead className="text-right">Durée moy.</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(stats?.models || []).map((m) => (
              <TableRow key={m.model}>
                <TableCell className="font-medium">{m.label}</TableCell>
                <TableCell className="text-right">{m.runs}{m.errors ? ` (${m.errors} err.)` : ""}</TableCell>
                <TableCell className="text-right">{formatXof(m.total_cost_xof)}</TableCell>
                <TableCell className="text-right">{formatXof(m.avg_cost_xof)}</TableCell>
                <TableCell>
                  {m.avg_rating ? (
                    <span className="inline-flex items-center gap-2">
                      <StarRating value={m.avg_rating} size={14} />
                      <span className="text-xs text-muted-foreground">{m.avg_rating.toFixed(1)} ({m.reviewed})</span>
                    </span>
                  ) : <span className="text-xs text-muted-foreground">non évalué</span>}
                </TableCell>
                <TableCell className="text-right">{formatPercent(m.avg_accuracy)}</TableCell>
                <TableCell className="text-right">{formatPercent(m.avg_confidence)}</TableCell>
                <TableCell className="text-right">{formatDuration(m.avg_duration_ms)}</TableCell>
              </TableRow>
            ))}
            {stats && stats.models.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                  Aucune analyse sur cette période.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Kpi({ title, value, hint }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className="text-xl font-semibold">{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-1">{hint}</div>}
    </div>
  );
}
