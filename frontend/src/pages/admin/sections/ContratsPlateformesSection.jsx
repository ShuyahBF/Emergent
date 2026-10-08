// ContratsPlateformesSection.jsx — Lot 81 : rubrique « 📑 Contrats des plateformes » des Paramètres.
// État de chaque contrat (à jour, échéance proche, renouvellement urgent), montant dû, et bouton vers l'écran
// « Plateformes en temps réel » où l'on définit le contrat et où l'on enregistre les paiements.
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";

export default function ContratsPlateformesSection() {
  const [contrats, setContrats] = useState(null);
  useEffect(() => {
    apiClient.get("/admin/plateformes/contrats").then((r) => setContrats(r.data.contrats)).catch(() => setContrats([]));
  }, []);
  if (!contrats) return <p className="text-sm text-slate-500">Patientez…</p>;
  // Couleur de la pastille selon l'état (orange avant / juste après l'échéance, rouge au-delà)
  const couleur = (e) => (e?.couleur === "rouge" ? "text-rose-700" : e?.couleur === "orange" ? "text-amber-700" : "text-slate-700");
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-contrats-plateformes">
      <p className="text-xs text-slate-600">
        Chaque plateforme cliente (ALBARKA…) est rattachée à son client SAWALI : n° de contrat, prestations et services,
        paiements et montant dû. Son DG voit un bandeau <b className="text-amber-700">orange</b> quelques jours avant l'échéance,
        puis une barre <b className="text-rose-700">rouge</b> quelques jours après (délais réglables par contrat) ; en dehors de
        cette fenêtre, aucun bandeau. Lot 82 : les <b>services cochés</b> sur le contrat (WhatsApp, e-mails, comptes rendus…)
        sont <b>suspendus automatiquement</b> chez la plateforme dès que le contrat est échu, et rouverts dès son renouvellement.
      </p>
      <table className="w-full text-xs">
        <thead className="text-left text-slate-500"><tr><th className="py-1">Plateforme</th><th>N° de contrat</th><th>Échéance</th><th>Montant dû</th><th>État</th><th>Suspendus</th></tr></thead>
        <tbody>
          {contrats.map((c) => (
            <tr key={c.code} className="border-t border-slate-100">
              <td className="py-1">{c.nom}</td><td className="font-mono">{c.numero || "—"}</td>
              <td>{c.fin ? String(c.fin).slice(0, 10).split("-").reverse().join("/") : "—"}</td>
              <td>{c.finances ? `${Math.round(c.finances.du).toLocaleString("fr-FR")} ${c.devise}` : "—"}</td>
              <td className={`font-semibold ${couleur(c.etat)}`}>{c.etat?.libelle}</td>
              <td>{(c.services_suspendus || []).length ? `⛔ ${c.services_suspendus.length}` : (c.services_a_suspendre || []).length ? `${c.services_a_suspendre.length} coché(s)` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Link to="/admin/plateformes-temps-reel#contrats-plateformes" className="inline-block rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white">
        Définir les contrats et les paiements</Link>
    </div>
  );
}
