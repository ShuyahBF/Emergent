// Paramètres → « 🔔 Rappels vocaux Alexa (annonces programmées) » : ÉTAT des automations vocales et accès à leur écran.
// Depuis le lot 375, la programmation et les tests se font dans la page Automations (administrateur) ou « Automations vocales » (Superviseur).
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "../../lib/api";

export default function RappelsVocauxSection() {
  const [donnees, setDonnees] = useState(null);
  useEffect(() => { apiClient.get("/admin/rappels-vocaux").then((r) => setDonnees(r.data)).catch(() => setDonnees({ erreur: true })); }, []);
  if (!donnees) return <div className="text-sm text-slate-500">Chargement…</div>;
  const regles = donnees.rappels || [];
  const actives = regles.filter((r) => r.actif !== false && ["en_attente", "actif"].includes(r.statut)).length;
  return (
    <div className="space-y-3" data-testid="rappels-vocaux-etat">
      <p className="text-sm text-slate-600">
        Alexa peut annoncer une phrase à une date et une heure (GMT), quelques minutes avant un rendez-vous, ou à l'arrivée d'un message WhatsApp.
        La programmation et les tests se font dans la page <strong>Automations</strong> (le Superviseur y accède par « Automations vocales »).
      </p>
      {donnees.erreur ? <div className="text-sm text-red-700">État indisponible.</div> : (
        <ul className="text-sm space-y-1">
          <li>Alexa : {donnees.alexa_pret ? "✅ prête" : "⚠️ pas prête — activez-la dans « Notifications vocales Alexa (Voice Monkey) »"}</li>
          <li>Automations vocales actives : <strong>{actives}</strong> sur {regles.length}</li>
        </ul>
      )}
      <Link to="/admin/automations" className="inline-flex rounded border px-4 py-2 text-sm" data-testid="ouvrir-automations-vocales">Ouvrir les Automations</Link>
    </div>
  );
}
