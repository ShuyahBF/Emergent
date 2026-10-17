/*
  Lot 42 — Paramètres Admin : plages horaires d'envoi des sondages et des liens de formulaires.
  Pour ne pas déranger les contacts : jours autorisés + plages (ex. 08:00–12:00 et
  15:00–19:00), heure de Ouagadougou par défaut. Hors plage, les envois attendent et
  reprennent seuls à l'ouverture suivante (le lendemain si besoin).
  API : GET/PUT /admin/plages-envoi (backend/routes/plages_envoi.py).
  Lot 114 — les mêmes plages s'appliquent aux CARROUSELS WhatsApp (portail et administration, sponsorisés compris),
  qui peuvent aussi être programmés : état des carrousels programmés / en attente / en cours et bouton vers l'écran
  d'envoi. API : GET /admin/whatsapp/carrousel/programmation/etat (backend/routes/carrousel_whatsapp.py).
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Clock, ExternalLink, GalleryHorizontalEnd, Plus, Save, Trash2, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";   // lot 114 : bouton vers l'écran Carrousel WhatsApp
import { apiClient } from "@/lib/api";

const JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];

export default function PlagesEnvoiSection() {
  const [cfg, setCfg] = useState(null);
  const [enreg, setEnreg] = useState(false);
  const [carrousels, setCarrousels] = useState(null);   // lot 114 : état des carrousels programmés / en attente

  useEffect(() => {
    apiClient.get("/admin/plages-envoi").then((r) => setCfg(r.data)).catch(() => toast.error("Réglage des plages indisponible"));
    // Lot 114 — état des carrousels (facultatif : la rubrique reste utilisable sans)
    apiClient.get("/admin/whatsapp/carrousel/programmation/etat").then((r) => setCarrousels(r.data)).catch(() => setCarrousels(null));
  }, []);
  // Lot 114 — date et heure françaises d'un instant ISO
  const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
  if (!cfg) return <Loader2 className="h-5 w-5 animate-spin text-slate-400" />;

  const basculerJour = (j) => setCfg({ ...cfg, jours: cfg.jours.includes(j) ? cfg.jours.filter((x) => x !== j) : [...cfg.jours, j].sort() });
  const majPlage = (i, champ, v) => setCfg({ ...cfg, plages: cfg.plages.map((p, k) => (k === i ? { ...p, [champ]: v } : p)) });

  // Lot 216 — pauses : intervalles « vides » entre deux plages (ex. 12:00 → 15:00), triées par heure de début
  const triees = [...cfg.plages].sort((a, b) => a.de.localeCompare(b.de));
  const pauses = triees.slice(1).map((p, i) => ({ de: triees[i].a, a: p.de })).filter((x) => x.de < x.a);
  // Lot 216 — « Plage continue » : une seule plage du plus tôt au plus tard
  const plageContinue = () => setCfg({ ...cfg, plages: [{ de: triees[0].de, a: triees[triees.length - 1].a }] });

  const enregistrer = async () => {
    setEnreg(true);
    try {
      const r = await apiClient.put("/admin/plages-envoi", { actif: cfg.actif, fuseau: cfg.fuseau, jours: cfg.jours, plages: cfg.plages, carrousels_weekend: !!cfg.carrousels_weekend });
      setCfg(r.data);
      toast.success("Plages horaires enregistrées");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnreg(false); }
  };

  return (
    <div className="space-y-3 text-sm" data-testid="plages-envoi-section">
      <p className="text-xs text-slate-600">
        Les envois de <b>sondages</b>, de <b>liens de formulaires</b> (WhatsApp et SMS) et de <b>carrousels WhatsApp</b>
        (portail, administration et carrousels sponsorisés) ne partent que pendant ces plages,
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
      {/* Lot 240 — carrousels : lever l'exclusion du samedi et du dimanche (mêmes heures), sans toucher aux sondages ni aux formulaires */}
      <label className="flex items-start gap-2 rounded-lg bg-slate-50 ring-1 ring-slate-200 p-2 text-xs text-slate-700" data-testid="plages-carrousels-weekend-label">
        <input type="checkbox" className="mt-0.5" checked={!!cfg.carrousels_weekend} onChange={(e) => setCfg({ ...cfg, carrousels_weekend: e.target.checked })} data-testid="plages-carrousels-weekend" />
        <span><b>Carrousels WhatsApp : autoriser aussi le samedi et le dimanche</b> (mêmes heures), même si ces jours sont exclus ci-dessus.
          Les sondages et les liens de formulaires gardent les jours choisis.</span>
      </label>
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
        {/* Lot 216 — avertissement : une pause existe entre deux plages */}
        {pauses.length > 0 && (
          <div className="rounded-lg bg-amber-50 ring-1 ring-amber-300 p-2 text-xs text-amber-900" data-testid="plages-pause">
            ⚠️ Pause : aucun envoi de {pauses.map((x) => `${x.de} à ${x.a}`).join(" ni de ")}.
            Si vous voulez seulement une heure de début et une heure de fin,{" "}
            <button type="button" onClick={plageContinue} data-testid="plages-continue" className="font-semibold underline">
              cliquez sur « Plage continue »
            </button>.
          </div>
        )}
        <button type="button" onClick={() => setCfg({ ...cfg, plages: [...cfg.plages, { de: "08:00", a: "12:00" }] })}
          className="inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline"><Plus className="h-3.5 w-3.5" /> Ajouter une plage (pause entre deux plages)</button>
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
      {/* Lot 114 — carrousels WhatsApp programmés ou en attente d'une plage : état et accès à l'écran d'envoi */}
      <div className="rounded-lg ring-1 ring-slate-200 p-3 space-y-1.5" data-testid="plages-carrousels-etat">
        <p className="flex items-center gap-1.5 font-semibold text-slate-800">
          <GalleryHorizontalEnd className="h-4 w-4" /> Carrousels WhatsApp programmés
        </p>
        <p className="text-xs text-slate-600">
          Un carrousel peut partir « maintenant » ou être programmé à une date et une heure (heure de Ouagadougou).
          Hors plage, il passe « En attente » et reprend seul à l'ouverture suivante, sans jamais renvoyer aux destinataires
          déjà servis. Un envoi programmé ou en attente peut être annulé depuis l'écran Carrousel WhatsApp.
        </p>
        {carrousels ? (
          <p className="text-xs text-slate-700">
            <b>{carrousels.programmees}</b> programmé(s) · <b>{carrousels.en_attente}</b> en attente · <b>{carrousels.en_cours}</b> en cours
            {carrousels.prochaine_reprise && <> · prochain départ le <b>{dateFr(carrousels.prochaine_reprise)}</b></>}
            {" · "}{carrousels.ouvert_maintenant ? "envois ouverts maintenant" : `prochaine ouverture le ${dateFr(carrousels.prochaine_ouverture)}`}
          </p>
        ) : <p className="text-xs text-slate-400">État des carrousels indisponible.</p>}
        <Link to="/admin/whatsapp-carrousel" data-testid="ouvrir-carrousel-wa" className="inline-flex items-center gap-1 text-xs text-sawali-blue hover:underline">
          <ExternalLink className="h-3.5 w-3.5" /> Ouvrir l'écran Carrousel WhatsApp
        </Link>
      </div>
    </div>
  );
}
