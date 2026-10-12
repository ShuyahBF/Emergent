// =====================================================================
// Lot 134 — Rubrique des Paramètres « 🎓 Portail e-Kol (élèves et parents) ».
// Le portail e-Kol (plateforme séparée) lit chez SAWALI, par une route signée, les tables e-Kol que Loois synchronise.
// Cette rubrique montre : la clé partagée EKOL_PORTAIL_HMAC est-elle configurée ? et, pour chaque école, quelles
// tables utiles au portail sont déjà synchronisées (sinon : les activer dans Plateformes → Loois → Synchro).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { RefreshCw, Check, X, KeyRound } from "lucide-react";

// Date lisible « 12/10/2026 14:05 »
const dateLisible = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function PortailEkolSection() {
  const [etat, setEtat] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState("");

  // Lecture de l'état (clé + tables synchronisées par école)
  const lire = useCallback(async () => {
    setChargement(true);
    try {
      const r = await apiClient.get("/admin/ekol-portail/etat");
      setEtat(r.data);
      setErreur("");
    } catch (e) {
      setErreur(e?.response?.status === 403 ? "Réservé à l'administrateur." : "État indisponible.");
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => { lire(); }, [lire]);

  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="portail-ekol-section">
      <p>
        Le <b>portail e-Kol</b> permet aux élèves et parents de suivre notes, paiements, alertes et relevés certifiés.
        Il lit ici, par une liaison signée, les tables e-Kol que Loois synchronise depuis chaque école.
      </p>
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-slate-500" aria-hidden="true" />
        <span>Clé partagée <code>EKOL_PORTAIL_HMAC</code> :</span>
        {etat && (etat.cle_configuree
          ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 text-xs font-semibold text-emerald-800"><Check className="h-3 w-3" />configurée</span>
          : <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 text-xs font-semibold text-rose-700"><X className="h-3 w-3" />à saisir sur Render (même valeur que sur le portail)</span>)}
        <button type="button" onClick={lire} disabled={chargement} title="Actualiser" className="ml-auto rounded-md p-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${chargement ? "animate-spin" : ""}`} />
        </button>
      </div>
      {erreur && <p className="text-xs text-rose-600">{erreur}</p>}
      {etat && etat.ecoles.length === 0 && (
        <p className="text-xs text-slate-500">Aucune école e-Kol ne synchronise encore de tables. Activez-les dans Plateformes → Loois → Synchro.</p>
      )}
      {etat && etat.ecoles.map((e) => (
        <div key={e.site} className="rounded-lg ring-1 ring-slate-200">
          <p className="border-b border-slate-100 px-3 py-1.5 font-semibold">{e.site}</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="px-3 py-1">Table utile au portail</th><th className="px-3 py-1">Synchronisée</th><th className="px-3 py-1">Lignes</th><th className="px-3 py-1">Dernière synchro</th></tr>
              </thead>
              <tbody>
                {etat.tables_utiles.map((t) => {
                  const info = e.tables[t];
                  return (
                    <tr key={t} className="border-t border-slate-100">
                      <td className="px-3 py-1">{t}</td>
                      <td className="px-3 py-1">{info ? <Check className="h-4 w-4 text-emerald-600" aria-label="oui" /> : <X className="h-4 w-4 text-rose-500" aria-label="non" />}</td>
                      <td className="px-3 py-1">{info?.nb_documents ?? "—"}</td>
                      <td className="px-3 py-1 whitespace-nowrap">{dateLisible(info?.derniere_synchro)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
