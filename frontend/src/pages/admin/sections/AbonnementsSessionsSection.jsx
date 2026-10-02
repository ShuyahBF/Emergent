// =====================================================================
// Lot 50 — Section « Abonnements (grâce et coupure) et sessions des comptes »
// (Paramètres, onglet Sécurité & Auth ; réservé au super-admin SAWALI).
// A. Échéance de chaque client sous contrat (périodicité + dernier règlement), délai de
//    grâce par client (0 à 30 j, 3 par défaut), « Renouveler la grâce (+3 j) » (3 fois au
//    plus par échéance impayée), interrupteur général de la coupure automatique.
// B. Nombre maximal d'appareils connectés par compte (1 à 20, 5 par défaut), sessions par
//    compte d'un client, fermeture d'une session ou de toutes les sessions d'un compte.
// Backend : routes/abonnements_sessions.py (/api/admin/abonnements, /api/admin/sessions).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, RefreshCw, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { formatDateHeure } from "@/components/DerniereSauvegarde";

const STATUTS = {
  expire: ["Coupé (grâce terminée)", "bg-red-100 text-red-800"],
  grace: ["En grâce", "bg-orange-100 text-orange-800"],
  a_jour: ["À jour", "bg-emerald-100 text-emerald-800"],
  sans_echeance: ["Sans échéance", "bg-slate-100 text-slate-600"],
};
const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const dateFr = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("fr-FR", { timeZone: "UTC" }) : "—");

export default function AbonnementsSessionsSection() {
  const [donnees, setDonnees] = useState(null);
  const [refuse, setRefuse] = useState(false);
  const [maxSessions, setMaxSessions] = useState(5);
  const [ouvert, setOuvert] = useState(null);       // client dont les sessions sont affichées
  const [sessionsClient, setSessionsClient] = useState(null);
  const [graces, setGraces] = useState({});         // saisies du délai de grâce par client
  const [journal, setJournal] = useState([]);
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [a, s, j] = await Promise.all([
        apiClient.get("/admin/abonnements"), apiClient.get("/admin/sessions/reglages"),
        apiClient.get("/admin/abonnements/journal"),
      ]);
      setDonnees(a.data);
      setMaxSessions(s.data.max_par_compte);
      setJournal(j.data.journal || []);
    } catch (e) {
      if (e?.response?.status === 403) setRefuse(true);
      else toast.error(erreurDe(e, "Chargement impossible"));
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const chargerSessions = useCallback(async (clientId) => {
    setSessionsClient(null);
    try {
      const r = await apiClient.get(`/admin/sessions/client/${clientId}`);
      setSessionsClient(r.data);
    } catch (e) { toast.error(erreurDe(e, "Sessions indisponibles")); }
  }, []);

  async function action(fn, succes) {
    setOccupe(true);
    try {
      await fn();
      if (succes) toast.success(succes);
      await charger();
      if (ouvert) await chargerSessions(ouvert);
    } catch (e) {
      toast.error(erreurDe(e, "Action impossible"));
    } finally {
      setOccupe(false);
    }
  }

  if (refuse) {
    return <Cadre><p className="text-sm text-slate-600">Réservé au super-administrateur SAWALI.</p></Cadre>;
  }
  if (!donnees) {
    return <Cadre><p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p></Cadre>;
  }
  const reg = donnees.reglages || {};
  const nbCoupes = donnees.clients.filter((c) => c.statut === "expire").length;
  const nbGrace = donnees.clients.filter((c) => c.statut === "grace").length;

  return (
    <Cadre>
      {/* ---------- Réglages ---------- */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
          <p className="font-semibold text-slate-800">A. Coupure après la période de grâce</p>
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={!!reg.coupure_active} disabled={occupe} data-testid="toggle-coupure-abonnement"
              onChange={(e) => {
                const actif = e.target.checked;
                if (actif && !window.confirm(`Activer la coupure automatique ?\n\n${nbCoupes} client(s) seraient coupés dès maintenant et ${nbGrace} sont en période de grâce. Vérifiez d'abord que les derniers règlements sont bien saisis.`)) return;
                action(() => apiClient.put("/admin/abonnements/reglages", { coupure_active: actif }),
                  actif ? "Coupure automatique activée." : "Coupure automatique désactivée.");
              }} />
            <span>
              Couper l'accès des clients dont l'échéance est impayée après la grâce (bandeau rouge pendant la grâce).
              <span className="block text-xs text-slate-500">
                Désactivé : seul cet écran montre l'état des abonnements ; les clients ne voient rien.
                Grâce par défaut {reg.grace_defaut} j ; « Renouveler la grâce » ajoute {reg.renouvellement_jours} j, {reg.renouvellements_max} fois au plus par échéance.
              </span>
            </span>
          </label>
        </div>
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
          <p className="font-semibold text-slate-800">B. Appareils connectés par compte</p>
          <div className="flex flex-wrap items-center gap-2">
            <input type="number" min={1} max={20} value={maxSessions} onChange={(e) => setMaxSessions(e.target.value)}
              className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-sm" data-testid="input-max-sessions" />
            <button type="button" disabled={occupe} className="rounded-lg bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
              onClick={() => action(() => apiClient.put("/admin/sessions/reglages", { max_par_compte: Number(maxSessions) }), "Limite enregistrée.")}>
              Enregistrer
            </button>
          </div>
          <p className="text-xs text-slate-500">
            De 1 à 20 (5 par défaut). À la connexion suivante, la session inactive depuis le plus longtemps est fermée ;
            l'appareil voit « Session fermée : nombre maximal d'appareils atteint pour ce compte ». Les sessions
            « Voir en tant que » ne comptent pas.
          </p>
        </div>
      </div>

      {/* ---------- Clients ---------- */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-600">{donnees.clients.length} client(s) — {nbCoupes} coupé(s), {nbGrace} en grâce</p>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900">
          <RefreshCw className="h-3 w-3" /> Actualiser
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="py-1 pr-2">Client</th><th className="py-1 pr-2">Statut</th><th className="py-1 pr-2">Échéance</th>
              <th className="py-1 pr-2">Fin de grâce</th><th className="py-1 pr-2">Grâce (j)</th><th className="py-1 pr-2">Renouv.</th>
              <th className="py-1 pr-2">Sessions</th><th className="py-1" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {donnees.clients.map((c) => {
              const [libelle, classe] = STATUTS[c.statut] || [c.statut, "bg-slate-100"];
              const saisie = graces[c.client_id] ?? c.grace_jours;
              return (
                <React.Fragment key={c.client_id}>
                  <tr data-testid={`abonnement-${c.client_id}`}>
                    <td className="py-2 pr-2"><span className="font-semibold text-slate-800">{c.nom}</span>
                      <span className="block text-[10px] text-slate-500">{c.periodicite_libelle || "périodicité non renseignée"}{c.account_status && c.account_status !== "active" ? ` · compte ${c.account_status}` : ""}</span></td>
                    <td className="py-2 pr-2"><span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${classe}`}>{libelle}</span>
                      {c.statut === "grace" && <span className="block text-[10px] text-orange-700">{c.jours_restants} j restant(s)</span>}</td>
                    <td className="py-2 pr-2">{dateFr(c.echeance)}</td>
                    <td className="py-2 pr-2">{c.fin_grace ? formatDateHeure(c.fin_grace) : "—"}</td>
                    <td className="py-2 pr-2">
                      <div className="flex items-center gap-1">
                        <input type="number" min={0} max={30} value={saisie} className="w-14 rounded border border-slate-300 px-1 py-0.5"
                          onChange={(e) => setGraces((g) => ({ ...g, [c.client_id]: e.target.value }))} />
                        {String(saisie) !== String(c.grace_jours) && (
                          <button type="button" disabled={occupe} className="rounded bg-sky-700 px-1.5 py-0.5 text-[10px] font-semibold text-white"
                            onClick={() => action(() => apiClient.put(`/admin/abonnements/${c.client_id}/grace`, { jours: Number(saisie) }), "Délai de grâce enregistré.")
                              .then(() => setGraces((g) => { const n = { ...g }; delete n[c.client_id]; return n; }))}>
                            OK
                          </button>
                        )}
                      </div>
                    </td>
                    <td className="py-2 pr-2">{c.renouvellements}/{c.renouvellements_max}</td>
                    <td className="py-2 pr-2">
                      <button type="button" className="text-sky-700 underline" onClick={() => {
                        const n = ouvert === c.client_id ? null : c.client_id;
                        setOuvert(n);
                        if (n) chargerSessions(n);
                      }}>{c.sessions} · {c.comptes} compte(s)</button>
                    </td>
                    <td className="py-2 text-right">
                      {(c.statut === "grace" || c.statut === "expire") && c.renouvellements < c.renouvellements_max && (
                        <button type="button" disabled={occupe} data-testid={`renouveler-grace-${c.client_id}`}
                          className="rounded-md bg-orange-600 px-2 py-1 text-[11px] font-semibold text-white hover:bg-orange-700 disabled:opacity-50"
                          onClick={() => window.confirm(`Renouveler la grâce de « ${c.nom} » de ${reg.renouvellement_jours} jours ?`)
                            && action(() => apiClient.post(`/admin/abonnements/${c.client_id}/renouveler-grace`), "Grâce renouvelée (+3 j).")}>
                          Renouveler la grâce (+{reg.renouvellement_jours} j)
                        </button>
                      )}
                    </td>
                  </tr>
                  {ouvert === c.client_id && (
                    <tr><td colSpan={8} className="bg-slate-50 p-3">
                      <SessionsClient donnees={sessionsClient} occupe={occupe}
                        fermer={(sid) => action(() => apiClient.delete(`/admin/sessions/${sid}`), "Session fermée.")}
                        fermerTout={(uid) => window.confirm("Fermer toutes les sessions de ce compte ?")
                          && action(() => apiClient.post(`/admin/sessions/compte/${uid}/fermer-tout`), "Sessions fermées.")} />
                    </td></tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {journal.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold text-slate-700">Journal des actions ({journal.length})</summary>
          <ul className="mt-2 divide-y divide-slate-100">
            {journal.map((j) => (
              <li key={j.id} className="py-1.5">
                <b>{j.action}</b> — {formatDateHeure(j.date)}{j.client_nom ? ` · ${j.client_nom}` : ""}{j.par?.email ? ` · ${j.par.email}` : ""}
                {j.renouvellement ? ` · renouvellement ${j.renouvellement}` : ""}{j.apres !== undefined && j.apres !== null ? ` · grâce ${j.apres} j` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Cadre>
  );
}

function Cadre({ children }) {
  return (
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200" data-testid="section-abonnements-sessions">
      <h2 className="font-display text-lg font-bold text-slate-900">🧾 Abonnements (grâce et coupure) et sessions des comptes</h2>
      {children}
    </section>
  );
}

function SessionsClient({ donnees, occupe, fermer, fermerTout }) {
  if (!donnees) return <p className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-3 w-3 animate-spin" /> Chargement…</p>;
  return (
    <div className="space-y-3">
      {donnees.comptes.map((c) => (
        <div key={c.id} className="rounded-lg bg-white p-2 ring-1 ring-slate-200">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs"><b>{c.full_name || c.email}</b> <span className="text-slate-500">{c.email} · {c.tracked_role || c.role}</span>
              {" "}— <b>{c.sessions.length}</b> / {donnees.max_par_compte} session(s)</p>
            {c.sessions.length > 0 && (
              <button type="button" disabled={occupe} onClick={() => fermerTout(c.id)}
                className="rounded px-2 py-0.5 text-[11px] text-red-700 ring-1 ring-red-200 hover:bg-red-50">Tout fermer</button>
            )}
          </div>
          {c.sessions.length > 0 && (
            <ul className="mt-1 divide-y divide-slate-100">
              {c.sessions.map((s) => (
                <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-1 text-[11px]">
                  <span>{s.appareil} · <span className="font-mono">{s.ip || "—"}</span> · ouverte {formatDateHeure(s.ouverte_le)} · activité {formatDateHeure(s.derniere_activite)}</span>
                  <button type="button" disabled={occupe} onClick={() => fermer(s.id)}
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-red-700 ring-1 ring-red-200 hover:bg-red-50"><X className="h-3 w-3" /> Fermer</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
