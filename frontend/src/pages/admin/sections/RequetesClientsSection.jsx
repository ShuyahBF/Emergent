// RequetesClientsSection.jsx — Lot 86 : rubrique « 🧾 Requêtes des clients » des Paramètres.
// État du module (requêtes par état, à évaluer, note moyenne) et bouton vers l'écran de traitement.
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";

export default function RequetesClientsSection() {
  const [res, setRes] = useState(null);
  useEffect(() => {
    apiClient.get("/admin/requetes").then((r) => setRes({ ...r.data.resume, etats: r.data.etats })).catch(() => setRes({}));
  }, []);
  if (!res) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-requetes-clients">
      <p className="text-xs text-slate-600">
        Vos clients (contractuels ou non) signalent dysfonctionnements, remarques, problèmes de logiciel ou d'équipement
        depuis leur portail (« Mes requêtes »), par écrit ou par message vocal. Chaque requête est numérotée par client et
        horodatée ; vous y ajoutez des observations, changez son état et la rangez dans un lot. Un lot « Déployé » invite
        chaque client concerné à évaluer (note de 1 à 5).
      </p>
      <div className="grid gap-2 text-sm sm:grid-cols-4">
        <div className="rounded-lg bg-slate-50 p-2"><p className="text-[11px] text-slate-500">Requêtes</p><p className="font-semibold">{res.total ?? 0}</p></div>
        <div className="rounded-lg bg-sky-50 p-2"><p className="text-[11px] text-slate-500">Nouvelles / en cours</p>
          <p className="font-semibold">{res.par_etat?.nouvelle ?? 0} / {res.par_etat?.en_cours ?? 0}</p></div>
        <div className="rounded-lg bg-amber-50 p-2"><p className="text-[11px] text-slate-500">En attente d'évaluation</p><p className="font-semibold">{res.a_evaluer ?? 0}</p></div>
        <div className="rounded-lg bg-emerald-50 p-2"><p className="text-[11px] text-slate-500">Note moyenne</p>
          <p className="font-semibold">{res.moyenne != null ? `${res.moyenne}/5 (${res.evaluees})` : "—"}</p></div>
      </div>
      <Link to="/admin/requetes" className="inline-block rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white">Traiter les requêtes et les lots</Link>
    </div>
  );
}
