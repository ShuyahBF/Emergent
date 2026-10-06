// ActivitePlateformesPanel.jsx — Lot 61.1 : tableau « Activité des plateformes » (adLyn,
// beAuthentik, Ster, ALBARKA…) dans Administration → Paramètres → Synthèse Liluvine.
// Mêmes chiffres que le bloc « 🌐 Activité des plateformes » de la synthèse quotidienne :
// messages WhatsApp transmis par SAWALI pour chaque plateforme (envois, réussite, remise,
// lecture), réponses des clients, désinscriptions, incidents et usage du quota.
// Lot 62 : + activité INTERNE fournie par chaque plateforme (connexions, ventes, inscriptions…).
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

export default function ActivitePlateformesPanel() {
  const [jours, setJours] = useState(1);            // période : 1, 7 ou 30 derniers jours
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");

  // Lot 62 — interroge tout de suite une plateforme (sans cache) et affiche sa réponse
  const tester = async (code) => {
    try {
      const r = await apiClient.post(`/admin/plateformes-activite/${encodeURIComponent(code)}/tester`);
      setDonnees((d) => d && ({ ...d, items: d.items.map((p) => (p.code === code ? { ...p, interne: r.data } : p)) }));
      if (r.data?.ok) toast.success("Statistiques reçues"); else toast.error(`Échec : ${r.data?.erreur || "inconnu"}`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Test impossible");
    }
  };

  // Lecture de l'activité à chaque changement de période
  useEffect(() => {
    setDonnees(null); setErreur("");
    apiClient.get("/admin/plateformes-activite", { params: { jours } })
      .then((r) => setDonnees(r.data))
      .catch((err) => setErreur(err?.response?.data?.detail || "Activité des plateformes indisponible"));
  }, [jours]);

  return (
    <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50/40 p-3 space-y-2" data-testid="activite-plateformes">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-sky-900">🌐 Activité des plateformes</p>
        <select value={jours} onChange={(e) => setJours(Number(e.target.value))}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs">
          <option value={1}>24 dernières heures</option>
          <option value={7}>7 derniers jours</option>
          <option value={30}>30 derniers jours</option>
        </select>
      </div>
      <p className="text-[10px] text-slate-600">
        Messages WhatsApp que chaque plateforme fait envoyer par SAWALI (Transmission WA universelle). Ce bloc est
        aussi ajouté à la synthèse quotidienne et à la commande <code>!synthese</code>.
      </p>
      {erreur ? (
        <p className="text-xs text-rose-700">{erreur}</p>
      ) : !donnees ? (
        <p className="text-xs text-slate-500">Patientez…</p>
      ) : donnees.items.length === 0 ? (
        <p className="text-xs text-slate-500">
          Aucune plateforme enregistrée. Ajoutez-les dans « Transmission WA Universelle Liluvine (webhook entrant) ».
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs bg-white rounded">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="px-2 py-1.5 text-left">Plateforme</th>
                <th className="px-2 py-1.5 text-right">Envois</th>
                <th className="px-2 py-1.5 text-right">Réussis</th>
                <th className="px-2 py-1.5 text-right">Échecs</th>
                <th className="px-2 py-1.5 text-right">Remis</th>
                <th className="px-2 py-1.5 text-right">Lus</th>
                <th className="px-2 py-1.5 text-right">Réponses</th>
                <th className="px-2 py-1.5 text-right">Désinscr.</th>
                <th className="px-2 py-1.5 text-right">Incidents</th>
                <th className="px-2 py-1.5 text-right">Quota</th>
                <th className="px-2 py-1.5 text-left">Dernier envoi</th>
                <th className="px-2 py-1.5 text-left">Activité interne (fournie par la plateforme)</th>
              </tr>
            </thead>
            <tbody>
              {donnees.items.map((p) => (
                <tr key={p.code} className={`border-t border-slate-100 ${p.actif ? "" : "opacity-50"}`}>
                  <td className="px-2 py-1.5 font-semibold">{p.nom}{!p.actif && " (désactivée)"}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{p.envois}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-emerald-700">{p.reussis}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${p.echecs ? "text-rose-700 font-semibold" : ""}`}>{p.echecs}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{p.remis}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{p.lus}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{p.reponses}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{p.desinscriptions}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${p.incidents ? "text-amber-700 font-semibold" : ""}`}>{p.incidents}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{p.usage_quota_pct != null ? `${p.usage_quota_pct} %` : "—"}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    {p.dernier_envoi ? new Date(p.dernier_envoi).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}
                  </td>
                  {/* Lot 62 — statistiques internes : indicateurs choisis par chaque plateforme */}
                  <td className="px-2 py-1.5 min-w-[220px]">
                    {p.interne?.ok ? (
                      <div className="space-y-1">
                        <div className="flex flex-wrap gap-1">
                          {(p.interne.indicateurs || []).map((i) => (
                            <span key={i.cle} className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] text-sky-900">
                              {i.libelle} <strong>{i.valeur}</strong>
                            </span>
                          ))}
                        </div>
                        {(p.interne.faits_marquants || []).map((f, k) => (
                          <p key={k} className="text-[10px] text-slate-600">◦ {f}</p>
                        ))}
                      </div>
                    ) : p.interne ? (
                      <span className="text-[10px] text-rose-700">Indisponible : {p.interne.erreur}</span>
                    ) : (
                      <span className="text-[10px] text-slate-400">
                        {p.stats_configurees ? "—" : "Non branchée (URL de retour ou URL des statistiques à renseigner)"}
                      </span>
                    )}
                    {p.stats_configurees && (
                      <button type="button" onClick={() => tester(p.code)}
                        className="ml-1 text-[10px] text-sky-700 hover:underline" data-testid={`stats-tester-${p.code}`}>
                        Tester
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
