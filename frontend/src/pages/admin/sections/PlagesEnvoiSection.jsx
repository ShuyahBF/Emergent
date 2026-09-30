/*
  Lot 42 — Paramètres Admin : plages horaires d'envoi des sondages et des liens de formulaires.
  Pour ne pas déranger les contacts : jours autorisés + plages (ex. 08:00–12:00 et
  15:00–19:00), heure de Ouagadougou par défaut. Hors plage, les envois attendent et
  reprennent seuls à l'ouverture suivante (le lendemain si besoin).
  API : GET/PUT /admin/plages-envoi (backend/routes/plages_envoi.py).
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Clock, Plus, Save, Trash2, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

const JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];

export default function PlagesEnvoiSection() {
  const [cfg, setCfg] = useState(null);
  const [enreg, setEnreg] = useState(false);

  useEffect(() => {
    apiClient.get("/admin/plages-envoi").then((r) => setCfg(r.data)).catch(() => toast.error("Réglage des plages indisponible"));
  }, []);
  if (!cfg) return <Loader2 className="h-5 w-5 animate-spin text-slate-400" />;

  const basculerJour = (j) => setCfg({ ...cfg, jours: cfg.jours.includes(j) ? cfg.jours.filter((x) => x !== j) : [...cfg.jours, j].sort() });
  const majPlage = (i, champ, v) => setCfg({ ...cfg, plages: cfg.plages.map((p, k) => (k === i ? { ...p, [champ]: v } : p)) });

  const enregistrer = async () => {
    setEnreg(true);
    try {
      const r = await apiClient.put("/admin/plages-envoi", { actif: cfg.actif, fuseau: cfg.fuseau, jours: cfg.jours, plages: cfg.plages });
      setCfg(r.data);
      toast.success("Plages horaires enregistrées");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnreg(false); }
  };

  return (
    <div className="space-y-3 text-sm" data-testid="plages-envoi-section">
      <p className="text-xs text-slate-600">
        Les envois de <b>sondages</b> et de <b>liens de formulaires</b> (WhatsApp et SMS) ne partent que pendant ces plages,
        pour ne pas déranger les contacts. Hors plage, un envoi lancé ou programmé attend, et un envoi en cours s'arrête puis
        reprend automatiquement à l'ouverture suivante (le lendemain si besoin).
      </p>
      <label className="inline-flex items-center gap-2 font-semibold text-slate-800">
        <input type="checkbox" checked={cfg.actif} onChange={(e) => setCfg({ ...cfg, actif: e.target.checked })} data-testid="plages-actif" />
        Restreindre les envois aux plages horaires ci-dessous
      </label>
      <div className="flex flex-wrap gap-1.5">
        {JOURS.map((j, i) => (
          <button key={j} type="button" onClick={() => basculerJour(i)} data-testid={`plages-jour-${i}`}
            className={`text-xs px-2.5 py-1 rounded-full ring-1 ${cfg.jours.includes(i) ? "bg-sawali-blue text-white ring-sawali-blue" : "bg-white ring-slate-300"}`}>
            {j}
          </button>
        ))}
      </div>
      <div className="space-y-1.5">
        {cfg.plages.map((p, i) => (
          <div key={i} className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-slate-400" />
            De <input type="time" value={p.de} onChange={(e) => majPlage(i, "de", e.target.value)} className="rounded border border-slate-300 px-2 py-1" />
            à <input type="time" value={p.a} onChange={(e) => majPlage(i, "a", e.target.value)} className="rounded border border-slate-300 px-2 py-1" />
            <button type="button" onClick={() => setCfg({ ...cfg, plages: cfg.plages.filter((_, k) => k !== i) })}
              className="p-1 text-rose-500 hover:bg-rose-50 rounded" title="Retirer la plage"><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
        <button type="button" onClick={() => setCfg({ ...cfg, plages: [...cfg.plages, { de: "08:00", a: "12:00" }] })}
          className="inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline"><Plus className="h-3.5 w-3.5" /> Ajouter une plage</button>
      </div>
      <label className="block text-xs text-slate-600">Fuseau horaire
        <input value={cfg.fuseau} onChange={(e) => setCfg({ ...cfg, fuseau: e.target.value })}
          className="mt-1 block w-64 rounded border border-slate-300 px-2 py-1 font-mono text-xs" />
      </label>
      <div className="flex items-center gap-3">
        <button type="button" onClick={enregistrer} disabled={enreg} data-testid="plages-enregistrer"
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 text-white px-3 py-1.5 text-xs hover:bg-slate-800 disabled:opacity-50">
          {enreg ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Enregistrer
        </button>
        <span className="text-[11px] text-slate-500">Actuellement : {cfg.resume}</span>
      </div>
    </div>
  );
}
