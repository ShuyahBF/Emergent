// PaiementOfficinesSection.jsx — Lot 386 : rubrique « 💳 Paiement au comptoir des officines » des Paramètres.
// Les pharmacies enregistrent leur code marchand (portail officines › Paiement) et impriment un QR : le client choisit son opérateur et son
// montant, et obtient la séquence USSD (Orange, Moov Africa, Telecel Faso). Ici : état, séquences utilisées et pharmacies qui l'ont activé.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export default function PaiementOfficinesSection() {
  const [d, setD] = useState(null);
  useEffect(() => { apiClient.get("/admin/officines-paiement").then((r) => setD(r.data)).catch(() => setD({ catalogue: {}, configurees: 0, total: 0, officines: [] })); }, []);
  if (!d) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-paiement-officines">
      <p className="text-xs text-slate-600">
        Décision du 13/11/2026 : le QR code reste le moyen principal pour les ordonnances ; pour le <b>paiement</b>, le client scanne le QR du comptoir et obtient
        la séquence USSD de son opérateur. Aucun paiement ne passe par SAWALI. Chaque pharmacie règle ses codes marchands dans son portail (onglet « Paiement »).
      </p>
      <table className="w-full text-xs">
        <thead className="text-left text-slate-500"><tr><th className="py-1">Opérateur</th><th>Séquence du paiement marchand</th></tr></thead>
        <tbody>{Object.entries(d.catalogue).map(([o, g]) => <tr key={o} className="border-t border-slate-100"><td className="py-1">{o}</td><td className="font-mono">{g}</td></tr>)}</tbody>
      </table>
      <p className="text-sm"><b>{d.configurees}</b> pharmacie(s) sur {d.total} ont activé le paiement au comptoir.</p>
      {d.officines.length > 0 && (
        <ul className="text-xs text-slate-700">{d.officines.map((o, i) => <li key={i}>{o.nom}{o.ville ? ` (${o.ville})` : ""} : {o.operateurs.join(", ")}</li>)}</ul>
      )}
    </div>
  );
}
