// SecuritePostes.jsx — Lot 373 : onglet « 🛡️ Sécurité des postes » de la page Plateformes → Loois → Synchro (administrateur).
//
// Demande du propriétaire (11/11/2026) : des tiers non agréés installent des outils sur les postes des clients (Aizenta, Biolog,
// eKol) ; leurs communications perturbent celles avec les serveurs HFSQL (ports) et des clés USB infectées sont branchées.
// Le service Windows Loois observe chaque poste et envoie ses alertes ici ; le propriétaire SEUL approuve ou ignore.
//
// Ce que fait l'écran :
//   - UNE LIGNE PAR POSTE (client, site, version du service, dernier contact, alertes nouvelles, éléments déjà approuvés) ;
//   - clic sur un poste : ses alertes (les plus graves et les nouvelles d'abord) avec les boutons « Approuver » / « Ignorer » /
//     « Rouvrir » ; une approbation part vers le poste à son prochain contact (dans les 10 minutes) et il cesse d'alerter ;
//   - export CSV de toutes les alertes.
// Rien n'est bloqué sur le réseau des clients à cette étape : on observe, on alerte et le blocage USB (exécution) est posé par Loois.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";

const BASE = "/admin/securite-postes";

// Date ISO → « JJ/MM/AAAA HH:MM » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "short", timeStyle: "short" });
};

// Pastille de gravité (haute = rouge, moyenne = orange, info = bleu)
const GRAVITES = {
  haute: ["Haute", "bg-rose-100 text-rose-800"],
  moyenne: ["Moyenne", "bg-amber-100 text-amber-800"],
  info: ["Info", "bg-sky-100 text-sky-800"],
};
const STATUTS = { nouvelle: ["Nouvelle", "bg-rose-50 text-rose-700"], approuvee: ["Approuvée", "bg-emerald-100 text-emerald-800"], ignoree: ["Ignorée", "bg-slate-100 text-slate-600"] };

export default function SecuritePostes() {
  const [vue, setVue] = useState(null);          // {postes, nouvelles, libelles_types}
  const [ouvert, setOuvert] = useState(null);    // machine dont les alertes sont affichées
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(async () => {
    setOccupe(true);
    try {
      setVue((await apiClient.get(BASE)).data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Lecture impossible");
    } finally {
      setOccupe(false);
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Décision du propriétaire sur une alerte
  const decider = async (machine, alerte, decision) => {
    const t = toast.loading("Patientez…");
    try {
      await apiClient.post(`${BASE}/decision`, { machine, cle: alerte.cle, decision });
      toast.success(decision === "approuver" ? "Approuvé : le poste en sera informé à son prochain contact" : decision === "ignorer" ? "Alerte ignorée" : "Alerte rouverte", { id: t });
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: t });
    }
  };

  // Export CSV (fichier téléchargé par le navigateur)
  const exporter = async () => {
    const t = toast.loading("Patientez… préparation du CSV");
    try {
      const r = await apiClient.get(`${BASE}/export.csv`, { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = "securite_postes.csv"; a.click();
      URL.revokeObjectURL(url);
      toast.success("CSV prêt", { id: t });
    } catch {
      toast.error("Export impossible", { id: t });
    }
  };

  if (!vue) return <p className="text-sm text-slate-500" data-testid="securite-postes">Patientez…</p>;
  const postes = vue.postes || [];
  const libelleType = (t) => (vue.libelles_types || {})[t] || t;

  return (
    <div className="space-y-4" data-testid="securite-postes">
      {/* En haut : ce qui demande une décision */}
      <div className={`rounded-xl border p-4 ${vue.nouvelles ? "border-rose-300 bg-rose-50" : "border-emerald-200 bg-emerald-50"}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {vue.nouvelles ? `🛡️ ${vue.nouvelles} alerte(s) à traiter` : "🛡️ Aucune alerte à traiter"}
            </h2>
            <p className="text-xs text-slate-600">
              Postes des clients surveillés par le service Windows Loois : nouveaux logiciels, programmes inconnus qui communiquent,
              port HFSQL occupé, clés USB. Vous seul approuvez : l'approbation est envoyée au poste dans les 10 minutes.
            </p>
          </div>
          <div className="flex gap-2 boutons-distincts">
            <button type="button" onClick={charger} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
              <RefreshCw className={`h-4 w-4 ${occupe ? "animate-spin" : ""}`} /> Actualiser
            </button>
            <button type="button" onClick={exporter} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50" data-testid="securite-export">
              ⬇ CSV
            </button>
          </div>
        </div>
      </div>

      {postes.length === 0 ? (
        <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
          Aucun poste n'a encore envoyé de signal de sécurité. Il faut le service Windows Loois à jour (version avec « AgentSecurite ») et une
          clé client Loois sur le poste ; la première alerte est « Référence du poste créée ».
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm tableau" data-testid="securite-tableau">
            <thead className="bg-slate-50 text-left text-xs text-slate-600">
              <tr>
                <th className="px-3 py-2">Poste</th><th className="px-3 py-2">Client / site</th><th className="px-3 py-2">Service</th>
                <th className="px-3 py-2">Dernier contact</th><th className="px-3 py-2 text-right">À traiter</th>
                <th className="px-3 py-2 text-right">Approuvés</th>
              </tr>
            </thead>
            <tbody>
              {postes.map((p) => (
                <React.Fragment key={p.machine}>
                  <tr className={`cursor-pointer border-t border-slate-100 hover:bg-sky-50 ${ouvert === p.machine ? "ligne-selectionnee" : ""}`}
                    onClick={() => setOuvert(ouvert === p.machine ? null : p.machine)} data-testid={`poste-${p.machine}`}>
                    <td className="px-3 py-2 font-semibold">{p.gravite_max === "haute" ? "🔴" : p.nouvelles ? "🟠" : "🟢"} {p.machine}</td>
                    <td className="px-3 py-2">{[p.client, p.site].filter(Boolean).join(" · ") || "—"}</td>
                    <td className="px-3 py-2">{p.version || "—"}</td>
                    <td className="px-3 py-2">{dateHeure(p.derniere_synchro)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.nouvelles}</td>
                    <td className="px-3 py-2 text-right tabular-nums" title="logiciels / programmes / clés USB">
                      {p.approuves.logiciels + p.approuves.chemins + p.approuves.usb}
                    </td>
                  </tr>
                  {ouvert === p.machine && (
                    <tr className="border-t border-slate-100 bg-slate-50">
                      <td colSpan={6} className="px-3 py-3">
                        <ul className="space-y-2" data-testid="securite-alertes">
                          {p.alertes.map((a) => (
                            <li key={a.cle} className="flex flex-wrap items-start justify-between gap-2 rounded-lg border border-slate-200 bg-white p-2">
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2 text-xs">
                                  <span className={`rounded px-1.5 py-0.5 font-semibold ${(GRAVITES[a.gravite] || GRAVITES.info)[1]}`}>{(GRAVITES[a.gravite] || GRAVITES.info)[0]}</span>
                                  <span className="font-semibold text-slate-800">{libelleType(a.type)}</span>
                                  <span className={`rounded px-1.5 py-0.5 ${(STATUTS[a.statut] || STATUTS.nouvelle)[1]}`}>{(STATUTS[a.statut] || STATUTS.nouvelle)[0]}</span>
                                  <span className="text-slate-500">{dateHeure(a.vu_le)}</span>
                                </div>
                                <p className="mt-1 break-words text-sm text-slate-700">{a.detail}</p>
                                {a.decide_par && <p className="text-xs text-slate-500">Décidé par {a.decide_par} le {dateHeure(a.decide_le)}</p>}
                              </div>
                              <div className="flex gap-1.5 boutons-distincts">
                                {a.statut === "nouvelle" && !["reference_creee", "usb_politique_modifiee"].includes(a.type) && (
                                  <button type="button" onClick={() => decider(p.machine, a, "approuver")} className="rounded-lg border border-emerald-400 px-2.5 py-1 text-xs hover:bg-emerald-50"
                                    data-testid="securite-approuver">✔ Approuver</button>
                                )}
                                {a.statut === "nouvelle" && (
                                  <button type="button" onClick={() => decider(p.machine, a, "ignorer")} className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-100">Ignorer</button>
                                )}
                                {a.statut === "ignoree" && (
                                  <button type="button" onClick={() => decider(p.machine, a, "reouvrir")} className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs hover:bg-slate-100">Rouvrir</button>
                                )}
                              </div>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
