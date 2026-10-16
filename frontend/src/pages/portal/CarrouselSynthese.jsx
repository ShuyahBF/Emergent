/*
  Lot 219 — Carrousel WhatsApp : onglet « Synthèse de vos envois ».
  Choisissez une période (du … au) : le tableau et les graphiques résument tous les carrousels envoyés sur la période.
    - Par carrousel (et par carte) : clics, vues de la présentation, « Je suis intéressé ».
    - Par destinataire : nombre de carrousels reçus, remis, lus, non remis.
  Les clics / vues / intéressés sont comptés PAR CARTE (le lien d'une carte est identique pour tous les destinataires) :
  ils ne sont donc pas rattachés à un destinataire précis. « Pas intéressé » vient du bouton de la page de présentation (une fois par appareil et par carte).
  API : GET {base}/synthese?du=AAAA-MM-JJ&au=AAAA-MM-JJ (base = /me/… ou /admin/whatsapp/carrousel).
*/
import React, { useCallback, useEffect, useState } from "react";
import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";

// « AAAA-MM-JJ » local, décalé de n jours (période par défaut : les 30 derniers jours)
const jourIso = (decalage = 0) => {
  const d = new Date(); d.setDate(d.getDate() + decalage);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const dateCourte = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }) : "");
const COULEURS = { clics: "#0ea5e9", vues: "#8b5cf6", interesses: "#10b981", pas_interesses: "#f59e0b", remis: "#38bdf8", lus: "#10b981", non_remis: "#f43f5e" };

export default function CarrouselSynthese({ base }) {
  const [du, setDu] = useState(jourIso(-30));
  const [au, setAu] = useState(jourIso(0));
  const [data, setData] = useState(null);
  const [charge, setCharge] = useState(false);

  // Relit la synthèse de la période choisie
  const lire = useCallback(async () => {
    setCharge(true);
    try {
      const r = await apiClient.get(`${base}/synthese`, { params: { du, au } });
      setData(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Synthèse indisponible");
    } finally { setCharge(false); }
  }, [base, du, au]);
  useEffect(() => { lire(); }, []); // eslint-disable-line react-hooks/exhaustive-deps — lecture à l'ouverture, ensuite au clic sur « Afficher »

  const t = data?.totaux;
  // Un point par carrousel (le plus ancien à gauche) pour le graphique « par carrousel »
  const serieCarrousels = (data?.carrousels || []).slice().reverse().map((c) => ({
    nom: `${dateCourte(c.cree_le)} · ${(c.message || c.modele || "").slice(0, 14)}`,
    clics: c.clics, vues: c.vues, interesses: c.interesses, pas_interesses: c.pas_interesses,
  }));
  // Cumul par rang de carte (carte 1, carte 2…) sur toute la période
  const serieCartes = [];
  (data?.carrousels || []).forEach((c) => c.cartes.forEach((x, i) => {
    serieCartes[i] = serieCartes[i] || { nom: `Carte ${i + 1}`, clics: 0, vues: 0, interesses: 0, pas_interesses: 0 };
    serieCartes[i].clics += x.clics; serieCartes[i].vues += x.vues; serieCartes[i].interesses += x.interesses; serieCartes[i].pas_interesses += x.pas_interesses;
  }));
  // Remise par destinataire : les 10 plus servis
  const serieDest = (data?.destinataires || []).slice(0, 10).map((d) => ({ nom: (d.nom || d.telephone).slice(0, 16), remis: d.remis, lus: d.lus, non_remis: d.non_remis }));

  const Tuile = ({ titre, valeur, couleur }) => (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{titre}</div>
      <div className="text-2xl font-bold tabular-nums" style={{ color: couleur }}>{valeur}</div>
    </div>
  );
  const Graphique = ({ titre, donnees, series }) => (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <h3 className="mb-2 text-sm font-semibold text-slate-800">{titre}</h3>
      {donnees.length === 0 ? <p className="text-sm text-slate-500">Aucune donnée sur la période.</p> : (
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <BarChart data={donnees} margin={{ top: 4, right: 8, left: -12, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="nom" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={60} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              {series.map(([cle, lib]) => <Bar key={cle} dataKey={cle} name={lib} fill={COULEURS[cle]} radius={[3, 3, 0, 0]} />)}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );

  return (
    <section className="space-y-4" data-testid="carrousel-synthese">
      {/* Choix de la période */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <label className="text-xs text-slate-600">Du
          <input type="date" value={du} max={au} onChange={(e) => setDu(e.target.value)} className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm" data-testid="synthese-du" />
        </label>
        <label className="text-xs text-slate-600">Au
          <input type="date" value={au} min={du} onChange={(e) => setAu(e.target.value)} className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm" data-testid="synthese-au" />
        </label>
        <Button type="button" size="sm" onClick={lire} disabled={charge} data-testid="synthese-afficher">
          {charge ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />} Afficher
        </Button>
        {[["7 jours", -7], ["30 jours", -30], ["90 jours", -90]].map(([lib, n]) => (
          <button key={lib} type="button" className="text-xs text-emerald-700 underline" onClick={() => { setDu(jourIso(n)); setAu(jourIso(0)); }}>{lib}</button>
        ))}
      </div>

      {!data ? <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
            <Tuile titre="Carrousels envoyés" valeur={t.envois} />
            <Tuile titre="Messages servis" valeur={t.servis} />
            <Tuile titre="Lus" valeur={t.lus} couleur={COULEURS.lus} />
            <Tuile titre="Non remis" valeur={t.non_remis} couleur={COULEURS.non_remis} />
            <Tuile titre="Clics" valeur={t.clics} couleur={COULEURS.clics} />
            <Tuile titre="Vues présentation" valeur={t.vues} couleur={COULEURS.vues} />
            <Tuile titre="Je suis intéressé" valeur={t.interesses} couleur={COULEURS.interesses} />
            <Tuile titre="Pas intéressé" valeur={t.pas_interesses} couleur={COULEURS.pas_interesses} />
          </div>
          <p className="text-xs text-slate-500">
            Les clics, vues et « Je suis intéressé » sont comptés par carte : le lien d'une carte est le même pour tous les destinataires,
            on ne peut donc pas savoir qui a cliqué. « Pas intéressé » vient du bouton de la page de présentation (une fois par appareil et par carte).
          </p>

          <div className="grid gap-4 lg:grid-cols-2">
            <Graphique titre="Par carrousel" donnees={serieCarrousels} series={[["clics", "Clics"], ["vues", "Vues présentation"], ["interesses", "Je suis intéressé"], ["pas_interesses", "Pas intéressé"]]} />
            <Graphique titre="Par carte (cumul de la période)" donnees={serieCartes} series={[["clics", "Clics"], ["vues", "Vues présentation"], ["interesses", "Je suis intéressé"], ["pas_interesses", "Pas intéressé"]]} />
          </div>
          <Graphique titre="Remise par destinataire (les 10 plus servis)" donnees={serieDest} series={[["remis", "Remis"], ["lus", "Lus"], ["non_remis", "Non remis"]]} />

          {/* Tableau par carrousel */}
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">Détail par carrousel</h3>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500">
                <th className="py-1 pr-2">Date</th><th className="pr-2">Message</th><th className="pr-2 text-right">Servis</th>
                <th className="pr-2 text-right">Clics</th><th className="pr-2 text-right">Vues</th><th className="pr-2 text-right">Intéressés</th><th className="text-right">Pas intéressés</th>
              </tr></thead>
              <tbody>
                {data.carrousels.length === 0 && <tr><td colSpan={7} className="py-2 text-slate-500">Aucun envoi sur la période.</td></tr>}
                {data.carrousels.map((c) => (
                  <tr key={c.id} className="border-t border-slate-100">
                    <td className="py-1 pr-2 whitespace-nowrap">{new Date(c.cree_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                    <td className="max-w-[260px] truncate pr-2">{c.message}</td>
                    <td className="pr-2 text-right tabular-nums">{c.servis}</td>
                    <td className="pr-2 text-right tabular-nums">{c.clics}</td>
                    <td className="pr-2 text-right tabular-nums">{c.vues}</td>
                    <td className="pr-2 text-right tabular-nums">{c.interesses}</td>
                    <td className="text-right tabular-nums">{c.pas_interesses}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Tableau par destinataire */}
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-3">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">Détail par destinataire</h3>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-500">
                <th className="py-1 pr-2">Destinataire</th><th className="pr-2">Téléphone</th><th className="pr-2 text-right">Reçus</th>
                <th className="pr-2 text-right">Remis</th><th className="pr-2 text-right">Lus</th><th className="text-right">Non remis</th>
              </tr></thead>
              <tbody>
                {data.destinataires.length === 0 && <tr><td colSpan={6} className="py-2 text-slate-500">Aucun destinataire sur la période.</td></tr>}
                {data.destinataires.map((d) => (
                  <tr key={d.telephone || d.nom} className="border-t border-slate-100">
                    <td className="py-1 pr-2">{d.nom}</td><td className="pr-2 font-mono text-xs">{d.telephone}</td>
                    <td className="pr-2 text-right tabular-nums">{d.recus}</td><td className="pr-2 text-right tabular-nums">{d.remis}</td>
                    <td className="pr-2 text-right tabular-nums">{d.lus}</td><td className="text-right tabular-nums">{d.non_remis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
