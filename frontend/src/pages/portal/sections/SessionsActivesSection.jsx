// =====================================================================
// Lot 50 — B. « Mon compte » : sessions ouvertes du compte.
// Au plus N appareils connectés en même temps (réglage du super-admin, 5 par défaut) :
// à la connexion suivante, la session inactive depuis le plus longtemps est fermée.
// Chaque ligne : appareil / navigateur, IP, ouverture, dernière activité, « Fermer ».
// Backend : GET /api/me/sessions, DELETE /api/me/sessions/{sid}.
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, MonitorSmartphone, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { formatDateHeure } from "@/components/DerniereSauvegarde";

export default function SessionsActivesSection() {
  const [donnees, setDonnees] = useState(null);
  const [enCours, setEnCours] = useState(null);

  const charger = useCallback(() => {
    apiClient.get("/me/sessions").then((r) => setDonnees(r.data)).catch(() => setDonnees({ sessions: [], erreur: true }));
  }, []);
  useEffect(() => { charger(); }, [charger]);

  async function fermer(s) {
    if (!window.confirm(`Fermer la session « ${s.appareil} » (${s.ip || "IP inconnue"}) ? L'appareil devra se reconnecter.`)) return;
    setEnCours(s.id);
    try {
      await apiClient.delete(`/me/sessions/${s.id}`);
      toast.success("Session fermée.");
      charger();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Fermeture impossible");
    } finally {
      setEnCours(null);
    }
  }

  return (
    <section className="rounded-2xl bg-white p-5 ring-1 ring-slate-200" data-testid="section-sessions-actives">
      <h2 className="mb-1 flex items-center gap-2 font-display text-sm font-semibold text-slate-700">
        <MonitorSmartphone className="h-4 w-4 text-sawali-blue" /> Sessions actives (appareils connectés)
      </h2>
      {!donnees ? (
        <p className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-3 w-3 animate-spin" /> Chargement…</p>
      ) : (
        <>
          <p className="mb-3 text-xs text-slate-500">
            Au plus <b>{donnees.max_par_compte || 5}</b> appareils connectés en même temps à ce compte : à la connexion
            suivante, celui qui est inactif depuis le plus longtemps est déconnecté.
            {donnees.apercu_admin ? " (Aperçu « Voir en tant que » : votre session d'administrateur n'apparaît pas ici.)" : ""}
          </p>
          {donnees.sessions?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500">
                  <tr><th className="py-1 pr-3">Appareil</th><th className="py-1 pr-3">IP</th><th className="py-1 pr-3">Ouverture</th>
                    <th className="py-1 pr-3">Dernière activité</th><th className="py-1" /></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {donnees.sessions.map((s) => (
                    <tr key={s.id} data-testid={`session-${s.id}`}>
                      <td className="py-2 pr-3">
                        <span className="font-semibold text-slate-800" title={s.navigateur}>{s.appareil}</span>
                        {s.courante && <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">cet appareil</span>}
                      </td>
                      <td className="py-2 pr-3 font-mono">{s.ip || "—"}</td>
                      <td className="py-2 pr-3">{formatDateHeure(s.ouverte_le)}</td>
                      <td className="py-2 pr-3">{formatDateHeure(s.derniere_activite)}</td>
                      <td className="py-2 text-right">
                        {!s.courante && (
                          <button type="button" disabled={enCours === s.id} onClick={() => fermer(s)}
                            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-700 ring-1 ring-red-200 hover:bg-red-50 disabled:opacity-50">
                            <X className="h-3 w-3" /> Fermer
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              {donnees.erreur ? "Liste indisponible." : "Aucune session enregistrée (connexion antérieure à cette fonction : reconnectez-vous pour la voir apparaître)."}
            </p>
          )}
        </>
      )}
    </section>
  );
}
