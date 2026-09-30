// Lot 44 — Journal des sessions « Voir en tant que » (Paramètres Admin → Diagnostics & Logs).
// Chaque session : Admin, compte visité, début / fin / expiration, IP réelle, navigateur,
// et la liste des actions (écritures autorisées, refus, changements de mode).
import React, { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";

const date = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR"); } catch { return iso; }
};

const COULEUR_STATUT = {
  "en cours": "bg-rose-100 text-rose-700",
  "terminée": "bg-slate-100 text-slate-700",
  "expirée": "bg-amber-100 text-amber-800",
};

const LIBELLE_ACTION = { ecriture: "Écriture", refus: "Refusé", mode: "Mode" };

export default function JournalVoirEnTantQueSection() {
  const [items, setItems] = useState([]);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState("");
  const [ouverte, setOuverte] = useState(null);

  const charger = async () => {
    setChargement(true);
    setErreur("");
    try {
      const r = await apiClient.get("/admin/voir-en-tant-que/journal", { params: { limit: 100 } });
      setItems(r.data?.items || []);
    } catch (err) {
      setErreur(err?.response?.data?.detail || "Chargement impossible");
    } finally { setChargement(false); }
  };
  useEffect(() => { charger(); }, []);

  return (
    <div className="space-y-3" data-testid="journal-voir-en-tant-que">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs text-slate-500">
          Sessions ouvertes par l'Admin avec « Voir en tant que » (30 min, lecture seule par défaut) et actions menées pendant chacune.
        </p>
        <button onClick={charger} disabled={chargement} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">
          <RefreshCw className={`h-3.5 w-3.5 ${chargement ? "animate-spin" : ""}`} /> Actualiser
        </button>
      </div>
      {erreur && <p className="text-sm text-rose-600">{erreur}</p>}
      {!erreur && items.length === 0 && !chargement && <p className="text-sm text-slate-500">Aucune session.</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead className="text-xs uppercase text-slate-500">
            <tr>
              <th className="text-left py-2 pr-3">Début</th>
              <th className="text-left py-2 pr-3">Admin</th>
              <th className="text-left py-2 pr-3">Compte visité</th>
              <th className="text-left py-2 pr-3">Statut</th>
              <th className="text-left py-2 pr-3">Fin / expiration</th>
              <th className="text-left py-2 pr-3">IP</th>
              <th className="text-right py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <React.Fragment key={s.id}>
                <tr className="border-t border-slate-100 align-top">
                  <td className="py-2 pr-3 whitespace-nowrap">{date(s.debut)}</td>
                  <td className="py-2 pr-3">{s.admin_nom}</td>
                  <td className="py-2 pr-3">{s.cible_nom} <span className="text-xs text-slate-500">({s.cible_role})</span><div className="text-[11px] text-slate-400 break-all">{s.cible_email}</div></td>
                  <td className="py-2 pr-3"><span className={`text-xs px-2 py-0.5 rounded ${COULEUR_STATUT[s.statut] || ""}`}>{s.statut}</span></td>
                  <td className="py-2 pr-3 whitespace-nowrap text-xs">{s.fin ? date(s.fin) : `expire ${date(s.expire_le)}`}</td>
                  <td className="py-2 pr-3 text-xs"><span className="font-mono">{s.ip || "—"}</span><div className="text-[10px] text-slate-400 max-w-[220px] truncate" title={s.navigateur}>{s.navigateur}</div></td>
                  <td className="py-2 text-right">
                    <button onClick={() => setOuverte(ouverte === s.id ? null : s.id)} className="text-xs text-sawali-blue hover:underline">
                      {(s.actions || []).length} action(s)
                    </button>
                  </td>
                </tr>
                {ouverte === s.id && (
                  <tr className="bg-slate-50">
                    <td colSpan={7} className="px-3 py-2">
                      {(s.actions || []).length === 0 ? (
                        <p className="text-xs text-slate-500">Aucune action d'écriture pendant cette session.</p>
                      ) : (
                        <ul className="space-y-1 text-xs">
                          {s.actions.map((a) => (
                            <li key={a.id} className="font-mono">
                              {date(a.horodatage)} · <strong>{LIBELLE_ACTION[a.action] || a.action}</strong> · {a.methode} {a.chemin} · {a.statut}
                              {a.detail ? <span className="text-slate-500"> — {a.detail}</span> : null}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
