// DisponibiliteSection.jsx — Lot 95 : rubrique « 📈 Disponibilité (/uptime) — journal des sondes » des Paramètres.
// Demande du propriétaire (09/10/2026) : « Pour le /health permettre de remettre à zéro le journal pour que les
// anciens historiques ne soient plus présents. »
//   - état : disponibilité moyenne sur 24 h et 7 j, dernière remise à zéro ;
//   - « Remettre à zéro le journal » : efface l'historique des sondes (et, si coché, celui des incidents),
//     puis lance aussitôt une nouvelle série de sondes ;
//   - bouton vers le tableau de bord « Santé » (écran d'utilisation) et vers la page publique /uptime.
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Loader2, RotateCcw } from "lucide-react";
import { apiClient } from "@/lib/api";

export default function DisponibiliteSection() {
  const [etat, setEtat] = useState(null);          // {h24, j7, remise_a_zero_le, remise_a_zero_par}
  const [incidents, setIncidents] = useState(false); // effacer aussi l'historique des incidents ?
  const [enCours, setEnCours] = useState(false);

  // Lecture de la disponibilité sur 24 h et 7 jours
  const charger = async () => {
    try {
      const [a, b] = await Promise.all([
        apiClient.get("/admin/health/uptime/stats?window_hours=24"),
        apiClient.get("/admin/health/uptime/stats?window_hours=168"),
      ]);
      setEtat({ h24: a.data.overall_uptime_pct, j7: b.data.overall_uptime_pct,
                remise_a_zero_le: b.data.remise_a_zero_le, remise_a_zero_par: b.data.remise_a_zero_par });
    } catch { setEtat({ erreur: true }); }
  };
  useEffect(() => { charger(); }, []);

  // Remise à zéro (après confirmation), avec « Patientez… » pendant la première série de sondes
  const remettreAZero = async () => {
    const quoi = incidents ? "le journal des sondes ET l'historique des incidents" : "le journal des sondes";
    if (!window.confirm(`Effacer définitivement ${quoi} ? Les pourcentages repartiront de zéro.`)) return;
    setEnCours(true);
    const attente = toast.loading("Patientez… remise à zéro et nouvelle série de sondes");
    try {
      const r = await apiClient.post("/admin/health/uptime/reset", { incidents });
      toast.success(`Journal remis à zéro : ${r.data.sondes_effacees} relevé(s) effacé(s)`
        + (incidents ? `, ${r.data.incidents_effaces} incident(s)` : "")
        + (r.data.premiere_serie?.ok ? " — nouvelles sondes OK" : " — attention : une sonde est en échec"), { id: attente });
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Remise à zéro impossible", { id: attente });
    } finally { setEnCours(false); }
  };

  const pct = (v) => (v == null ? "—" : `${v} %`);
  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">Disponibilité indisponible (réservé au super-administrateur).</p>;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-disponibilite">
      <p className="text-xs text-slate-600">
        Chaque heure, le serveur interroge la base de données, l'API publique, le contenu CMS et le compteur de visites.
        Le résultat alimente la page publique <a href="/uptime" target="_blank" rel="noreferrer" className="text-sawali-blue underline">/uptime</a>.
      </p>
      {/* État : disponibilité moyenne et dernière remise à zéro */}
      <div className="flex flex-wrap gap-4 text-sm">
        <span>24 h : <b>{pct(etat.h24)}</b></span>
        <span>7 jours : <b>{pct(etat.j7)}</b></span>
        <span className="text-slate-500">
          Dernière remise à zéro : {etat.remise_a_zero_le
            ? `${new Date(etat.remise_a_zero_le).toLocaleString("fr-FR")}${etat.remise_a_zero_par ? ` (${etat.remise_a_zero_par})` : ""}`
            : "jamais"}
        </span>
      </div>
      {/* Remise à zéro du journal */}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={incidents} onChange={(e) => setIncidents(e.target.checked)} />
        Effacer aussi l'historique des incidents (l'incident en cours est gardé tant que le bandeau d'incident est activé)
      </label>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={remettreAZero} disabled={enCours}
                className="inline-flex items-center gap-2 rounded-lg bg-rose-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
                data-testid="uptime-remise-a-zero">
          {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
          Remettre à zéro le journal
        </button>
        <Link to="/admin/health" className="rounded-lg border border-slate-300 px-3.5 py-2 text-xs hover:bg-slate-50">
          Ouvrir le tableau de bord Santé
        </Link>
      </div>
    </div>
  );
}
