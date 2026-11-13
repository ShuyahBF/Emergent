// Paramètres → « 👪 Ma famille (Personnel de maison) » : ÉTAT du module (comptages seulement, jamais un nom ni un message).
// Les comptes, liens de vérification et messages sont gérés par les téléphones (application Personnel de maison) ; les messages sont chiffrés de bout en bout.
import React, { useEffect, useState } from "react";
import { apiClient } from "../../lib/api";

export default function FamilleSection() {
  const [etat, setEtat] = useState(null);
  useEffect(() => { apiClient.get("/admin/famille/etat").then((r) => setEtat(r.data)).catch(() => setEtat({ erreur: true })); }, []);
  if (!etat) return <div className="text-sm text-slate-500">Chargement…</div>;
  return (
    <div className="space-y-3" data-testid="famille-etat">
      <p className="text-sm text-slate-600">
        « Ma famille » relie les téléphones d'une même famille (application <strong>Personnel de maison</strong>) : liens vérifiés par un numéro de sécurité comparé de vive voix,
        puis messagerie chiffrée de bout en bout. SAWALI ne voit que du texte chiffré : aucun message n'est lisible ici.
      </p>
      {etat.erreur ? <div className="text-sm text-red-700">État indisponible.</div> : (
        <ul className="text-sm space-y-1">
          <li>Comptes famille : <strong>{etat.comptes}</strong></li>
          <li>Liens : <strong>{etat.liens}</strong> dont <strong>{etat.liens_verifies}</strong> vérifié(s) des deux côtés</li>
          <li>Messages chiffrés conservés : <strong>{etat.messages}</strong></li>
          <li>Invitations en cours (valables 15 minutes) : <strong>{etat.invitations_en_cours}</strong></li>
        </ul>
      )}
    </div>
  );
}
