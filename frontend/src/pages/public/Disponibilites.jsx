/*
  Lot 41 — Page publique /disponibilites/:jeton : disponibilités partagées depuis une
  discussion WhatsApp. Seulement « occupé » en grisé (aucun détail), créneaux libres en blanc.
  Lien valable 14 jours. API : GET /public/calendrier/{jeton}.
*/
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CalendarDays, ChevronLeft, ChevronRight, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import CalendrierSemaine from "@/components/CalendrierSemaine";

export default function Disponibilites() {
  const { jeton } = useParams();
  const [debut, setDebut] = useState(null);
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");

  useEffect(() => {
    apiClient.get(`/public/calendrier/${jeton}`, { params: debut ? { debut } : {} })
      .then((r) => setDonnees(r.data))
      .catch((e) => setErreur(e?.response?.data?.detail || "Lien expiré ou inconnu"));
  }, [jeton, debut]);

  const decaler = (n) => {
    const d = new Date(donnees.debut);
    d.setDate(d.getDate() + n * 7);
    setDebut(d.toISOString().slice(0, 10));
  };

  if (erreur) return <div className="min-h-screen flex items-center justify-center p-6 text-slate-600">{erreur}</div>;
  if (!donnees) return <div className="min-h-screen flex items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>;
  return (
    <div className="min-h-screen bg-slate-50 p-4">
      <div className="mx-auto max-w-4xl rounded-xl bg-white p-4 shadow ring-1 ring-slate-200 space-y-3">
        <h1 className="flex items-center gap-2 text-lg font-bold text-slate-800">
          <CalendarDays className="h-5 w-5 text-indigo-600" /> Disponibilités — {donnees.titre}
        </h1>
        <p className="text-sm text-slate-600">Les moments en gris sont déjà occupés ; les créneaux blancs sont libres.
          Répondez sur WhatsApp avec le créneau qui vous convient.</p>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => decaler(-1)} className="p-1.5 rounded border border-slate-300"><ChevronLeft className="h-4 w-4" /></button>
          <button type="button" onClick={() => decaler(1)} className="p-1.5 rounded border border-slate-300"><ChevronRight className="h-4 w-4" /></button>
          <span className="text-xs text-slate-500">Lien valable jusqu'au {new Date(donnees.expire_le).toLocaleDateString("fr-FR")}</span>
        </div>
        <CalendrierSemaine debut={donnees.debut} jours={7} horaires={donnees.horaires} occupations={donnees.occupations} />
        <p className="text-[11px] text-slate-400">SAWALI SMART SYSTEMS · contact@sawalismartsystems.com · +226 25 65 81 65</p>
      </div>
    </div>
  );
}
