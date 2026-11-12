// Lot 375 — « Automations vocales » pour le Superviseur (et l'administrateur) : annonces Alexa programmées ou déclenchées par un rendez-vous / un message.
import React from "react";
import { Volume2 } from "lucide-react";
import AutomationsVocales from "@/components/admin/AutomationsVocales";

export default function AutomationsVocalesPage() {
  return (
    <div className="max-w-6xl space-y-4" data-testid="automations-vocales-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Automations</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2"><Volume2 className="h-5 w-5 text-sky-600" /> Automations vocales (Alexa)</h1>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4"><AutomationsVocales /></div>
    </div>
  );
}
