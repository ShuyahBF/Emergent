import React, { useCallback, useEffect, useImperativeHandle, useState, forwardRef } from "react";
import { HardDrive } from "lucide-react";
import { apiClient } from "@/lib/api";

/*
  Lot 20 — Jauge « espace occupé / espace alloué » de l'espace R2 Gestion de
  Stocks d'un tenant (tous ses dossiers). Utilisée :
    - sur le tableau de bord du Pharmacien suivi (portal/Dashboard.jsx) ;
    - dans l'Explorateur Stockage R2 (GestionStocks.jsx).
  Données : GET /gestion-stocks/storage (le serveur résout lui-même le tenant
  d'un utilisateur suivi ; `clientCode` n'est transmis que pour l'administration).
  Si le module n'est pas accessible ou pas configuré, la jauge ne s'affiche pas.
*/

// Octets → « 1,2 Go » / « 350 Mo » / « 12 Ko » (format français).
export function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  const units = [["Go", 1024 ** 3], ["Mo", 1024 ** 2], ["Ko", 1024]];
  for (const [unit, size] of units) {
    if (n >= size) return `${(n / size).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} ${unit}`;
  }
  return `${n} o`;
}

const R2StorageGauge = forwardRef(function R2StorageGauge({ clientCode = null, compact = false }, ref) {
  const [data, setData] = useState(null);

  // Rechargement (exposé au parent pour rafraîchir après un dépôt).
  const load = useCallback(async () => {
    try {
      const r = await apiClient.get("/gestion-stocks/storage", { params: clientCode ? { client_code: clientCode } : {} });
      setData(r.data);
    } catch {
      setData(null);
    }
  }, [clientCode]);

  useEffect(() => { load(); }, [load]);
  useImperativeHandle(ref, () => ({ reload: load }), [load]);

  if (!data) return null;
  const pct = data.quota_bytes ? Math.min(100, Math.round((data.used_bytes / data.quota_bytes) * 100)) : 0;
  const bar = pct >= 100 ? "bg-rose-600" : pct >= 80 ? "bg-amber-500" : "bg-teal-500";
  const quotaLabel = `${Number(data.quota_gb).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} Go`;

  return (
    <div className={`rounded-xl ring-1 ring-teal-200 bg-white ${compact ? "px-3 py-2" : "p-4"} flex items-center gap-3`}
      data-testid="r2-storage-gauge">
      <div className="h-9 w-9 rounded-lg bg-teal-50 flex items-center justify-center shrink-0">
        <HardDrive className="h-4 w-4 text-teal-600" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
          Espace de stockage Gestion de Stocks
        </p>
        <p className="text-sm text-slate-900 font-semibold tabular-nums" data-testid="r2-storage-text">
          {formatBytes(data.used_bytes)} <span className="font-normal text-slate-500">utilisés sur {quotaLabel}</span>
          <span className="font-normal text-slate-400"> · {data.files} fichier{data.files > 1 ? "s" : ""}</span>
        </p>
        <div className="mt-1 h-2 rounded-full bg-slate-100 overflow-hidden">
          <div className={`h-full ${bar} transition-all`} style={{ width: `${pct}%` }} />
        </div>
      </div>
      <span className="text-xs tabular-nums text-slate-500 shrink-0" data-testid="r2-storage-pct">{pct} %</span>
    </div>
  );
});

export default R2StorageGauge;
