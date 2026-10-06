// AdminPlateformesTempsReel.jsx — Lot 63 : suivi EN TEMPS RÉEL des plateformes (adLyn, Ster,
// beAuthentik, ALBARKA…), page réservée à l'administrateur.
//
// - Rafraîchissement automatique toutes les 30 secondes (statistiques internes relues chez
//   chaque plateforme au plus une fois par minute) ;
// - une carte par plateforme : pastille VERTE si au moins un utilisateur y est connecté
//   (actif ces 5 dernières minutes), grise sinon, « ? » si la plateforme ne le dit pas ;
// - indicateurs internes du jour (24 dernières heures), faits marquants, messages WhatsApp
//   transmis par SAWALI (envois, échecs, réponses) et dernier envoi.
import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";
import VersionsDeployees from "./VersionsDeployees";

const INTERVALLE_MS = 30000;

// Pastille de présence : verte (connectés), grise (personne), contour (inconnu)
function Pastille({ connectes }) {
  if (connectes === null || connectes === undefined) {
    return <span className="inline-block h-3 w-3 rounded-full ring-2 ring-slate-300" title="Présence non communiquée par la plateforme" />;
  }
  return connectes > 0 ? (
    <span className="relative inline-flex h-3 w-3" title={`${connectes} utilisateur(s) connecté(s)`}>
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
      <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-500" />
    </span>
  ) : (
    <span className="inline-block h-3 w-3 rounded-full bg-slate-300" title="Aucun utilisateur connecté" />
  );
}

export default function AdminPlateformesTempsReel() {
  const [donnees, setDonnees] = useState(null);
  const [erreur, setErreur] = useState("");
  const [maj, setMaj] = useState(null);
  const [chargement, setChargement] = useState(false);
  // Lot 64.10 — état de la surveillance des statistiques (bulles de notification)
  const [veille, setVeille] = useState(null);
  useEffect(() => {
    const surVeille = (e) => setVeille(e.detail);
    window.addEventListener("sawali:veille-stats", surVeille);
    return () => window.removeEventListener("sawali:veille-stats", surVeille);
  }, []);

  // Lecture de l'activité (24 dernières heures, mode temps réel)
  const lire = useCallback(async () => {
    setChargement(true);
    try {
      const r = await apiClient.get("/admin/plateformes-activite", { params: { jours: 1, temps_reel: true } });
      setDonnees(r.data); setErreur(""); setMaj(new Date());
    } catch (err) {
      setErreur(err?.response?.data?.detail || "Activité des plateformes indisponible");
    } finally {
      setChargement(false);
    }
  }, []);

  // Rafraîchissement automatique (seulement quand l'onglet est visible)
  useEffect(() => {
    lire();
    const t = setInterval(() => { if (!document.hidden) lire(); }, INTERVALLE_MS);
    return () => clearInterval(t);
  }, [lire]);

  const items = donnees?.items || [];
  const enLigne = items.filter((p) => (p.interne?.utilisateurs_connectes || 0) > 0).length;

  return (
    <div className="space-y-4" data-testid="plateformes-temps-reel">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold">🌐 Plateformes en temps réel</h1>
          <p className="text-xs text-slate-500">
            Activité des 24 dernières heures · actualisation automatique toutes les 30 s
            {maj && ` · dernière mise à jour ${maj.toLocaleTimeString("fr-FR")}`}
          </p>
          <p className="text-xs text-slate-500" data-testid="etat-veille-stats">
            🔔 Bulles de notification : {veille
              ? `dernière vérification ${new Date(veille.le).toLocaleTimeString("fr-FR")} · ${veille.changements} changement(s) détecté(s)`
              : "vérification toutes les 60 s (première lecture = référence, sans bulle)"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-700"><strong>{enLigne}</strong> / {items.length} plateforme(s) avec des utilisateurs connectés</span>
          {/* Lot 64.10 — bulle d'exemple, pour vérifier l'affichage des notifications */}
          <button type="button" onClick={() => window.dispatchEvent(new Event("sawali:test-bulle-stats"))}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50" data-testid="tester-bulle-stats">
            🔔 Tester la bulle
          </button>
          <button type="button" onClick={lire} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
            <RefreshCw className={`h-4 w-4 ${chargement ? "animate-spin" : ""}`} /> Actualiser
          </button>
        </div>
      </div>

      {erreur && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{erreur}</p>}
      {!donnees && !erreur && <p className="text-sm text-slate-500">Patientez…</p>}
      {donnees && items.length === 0 && (
        <p className="text-sm text-slate-500">Aucune plateforme enregistrée (Paramètres → Transmission WA Universelle Liluvine).</p>
      )}

      {/* Une carte par plateforme */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((p) => {
          const interne = p.interne;
          const connectes = interne?.ok ? interne.utilisateurs_connectes : null;
          return (
            <div key={p.code} className={`rounded-2xl bg-white p-4 shadow-sm ring-1 ${connectes > 0 ? "ring-emerald-300" : "ring-slate-200"} ${p.actif ? "" : "opacity-60"}`}
              data-testid={`plateforme-${p.code}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Pastille connectes={connectes} />
                  <h2 className="text-lg font-semibold">{p.nom}</h2>
                </div>
                <span className="text-xs text-slate-500">
                  {connectes === null || connectes === undefined ? "présence inconnue" : `${connectes} connecté(s)`}
                </span>
              </div>
              {/* Lot 65 — version déployée, si la plateforme la joint à ses statistiques */}
              {interne?.version && (
                <p className="mt-1 text-xs text-slate-500">
                  Version {interne.version}{interne.deploye_le && ` · déployée le ${new Date(interne.deploye_le).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "")}`}
                </p>
              )}

              {/* Indicateurs internes fournis par la plateforme */}
              <div className="mt-3">
                {interne?.ok ? (
                  <div className="grid grid-cols-2 gap-2">
                    {(interne.indicateurs || []).map((i) => (
                      <div key={i.cle} className="rounded-lg bg-slate-50 px-2 py-1.5">
                        <p className="text-[10px] uppercase tracking-wide text-slate-500">{i.libelle}</p>
                        <p className="text-base font-semibold tabular-nums">{i.valeur}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-rose-700">
                    {interne
                      ? `Statistiques internes indisponibles : ${interne.erreur}`
                      : (p.stats_manque || []).length
                        // Lot 64.7 — ce qui manque dans Paramètres → Transmission WA Universelle Liluvine
                        ? `Statistiques internes non branchées : renseignez ${p.stats_manque.join(", ")} de cet émetteur (Paramètres → Transmission WA Universelle Liluvine).`
                        : "Statistiques internes non branchées"}
                  </p>
                )}
                {(interne?.faits_marquants || []).length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-xs text-slate-700">
                    {interne.faits_marquants.map((f, k) => <li key={k}>◦ {f}</li>)}
                  </ul>
                )}
              </div>

              {/* Messages WhatsApp transmis par SAWALI pour cette plateforme */}
              <div className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-600">
                WhatsApp via SAWALI : <strong>{p.envois}</strong> envoi(s), {p.reussis} réussi(s),{" "}
                <span className={p.echecs ? "font-semibold text-rose-700" : ""}>{p.echecs} échec(s)</span>, {p.reponses} réponse(s)
                {p.incidents > 0 && <span className="font-semibold text-amber-700"> · ⚠️ {p.incidents} incident(s)</span>}
                <br />
                Dernier envoi : {p.dernier_envoi ? new Date(p.dernier_envoi).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"}
                {interne?.recu_le && <> · statistiques reçues à {new Date(interne.recu_le).toLocaleTimeString("fr-FR")}</>}
              </div>
            </div>
          );
        })}
      </div>

      {/* Lot 65 — versions déployées (SAWALI, plateformes, postes Loois) */}
      <VersionsDeployees />
    </div>
  );
}
