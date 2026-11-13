// TransactionsSmsSection.jsx — Lot 389 : rubrique « 💬 Transactions SMS » des Paramètres : ÉTAT seulement (téléphones, transactions, associations) et bouton vers l'écran.
// Les transactions elles-mêmes se consultent dans l'option de menu « Transactions SMS » (pas dans les Paramètres, demande du propriétaire du 14/11/2026).
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";

export default function TransactionsSmsSection() {
  const [etat, setEtat] = useState(null);
  const [total, setTotal] = useState(null);
  useEffect(() => {
    apiClient.get("/admin/transactions-sms/etat").then((r) => setEtat(r.data)).catch(() => setEtat(false));
    apiClient.get("/admin/transactions-sms", { params: { limite: 1 } }).then((r) => setTotal(r.data.total)).catch(() => {});
  }, []);
  return (
    <div className="space-y-2 text-sm" data-testid="transactions-sms-section">
      <p className="text-slate-600">Paiements lus dans les SMS d'un téléphone (application Concentration), avec les mêmes filtres que l'historique d'auRor, et association d'un numéro à une plateforme (ALBARKA…).</p>
      {etat === false ? <p className="text-red-600">État indisponible.</p> : etat && (
        <ul className="list-disc pl-5">
          <li>{etat.sources.length} téléphone(s) source · {total ?? "…"} transaction(s) reçue(s)</li>
          <li>{etat.liens.length} association(s) numéro → plateforme</li>
        </ul>
      )}
      <Link to="/admin/transactions-sms" className="inline-block rounded border border-slate-300 px-3 py-1.5">Ouvrir « Transactions SMS »</Link>
    </div>
  );
}
