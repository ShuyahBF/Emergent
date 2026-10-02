// =====================================================================
// Lot 51 — Section « Cycle de vie des abonnements (suspension J+110, archivage J+113) »
// (Paramètres, onglet Sécurité & Auth ; réservé au super-admin SAWALI).
// - Interrupteur général (désactivé par défaut), mode simulation, conservation des archives,
//   frais de réouverture (montant + devise).
// - Clients en retard, suspendus ou archivés : jours depuis l'échéance, calendrier des étapes,
//   actions prévues aujourd'hui ; « Lever la suspension », « Réouvrir » (archive restaurée).
// - « Simuler maintenant » (sans effet), « Lancer maintenant », dernier rapport, journal.
// Backend : routes/cycle_vie_abonnements.py (/api/admin/cycle-vie).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Play, RefreshCw, FlaskConical } from "lucide-react";
import { apiClient } from "@/lib/api";
import { formatDateHeure } from "@/components/DerniereSauvegarde";

const STATUTS = {
  ARCHIVE: ["Archivé", "bg-slate-800 text-white"],
  SUSPENDU_NON_RENOUVELE: ["Suspendu", "bg-red-100 text-red-800"],
  ACTIF: ["Accès ouvert", "bg-emerald-100 text-emerald-800"],
};
const LIBELLES = {
  AVERTISSEMENT_J103: "Avertissement J+103",
  AVERTISSEMENT_J110: "Avertissement J+110",
  AVERTISSEMENT_J112: "Avertissement J+112 (veille)",
  SUSPENSION: "Suspension",
  ARCHIVAGE: "Archivage puis suppression",
  LEVEE_PAIEMENT: "Levée (règlement saisi)",
  LEVEE_SANS_ECHEANCE: "Levée (sans échéance)",
  EFFACEMENT_ARCHIVE: "Effacement de l'archive",
};
const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const dateFr = (iso) => (iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00Z`).toLocaleDateString("fr-FR", { timeZone: "UTC" }) : "—");

export default function CycleVieAbonnementsSection() {
  const [donnees, setDonnees] = useState(null);
  const [refuse, setRefuse] = useState(false);
  const [saisie, setSaisie] = useState(null);
  const [simulation, setSimulation] = useState(null);
  const [journal, setJournal] = useState([]);
  const [occupe, setOccupe] = useState(false);
  const [reouverture, setReouverture] = useState(null);   // {client, mot_de_passe, confirmation, frais_encaisses, reference}

  const charger = useCallback(async () => {
    try {
      const [v, j] = await Promise.all([apiClient.get("/admin/cycle-vie"), apiClient.get("/admin/cycle-vie/journal")]);
      setDonnees(v.data);
      setJournal(j.data.journal || []);
      const r = v.data.reglages;
      setSaisie({ conservation_jours: r.conservation_jours, frais_montant: r.frais_reouverture.montant, frais_devise: r.frais_reouverture.devise });
    } catch (e) {
      if (e?.response?.status === 403) setRefuse(true);
      else toast.error(erreurDe(e, "Chargement impossible"));
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  async function action(fn, succes) {
    setOccupe(true);
    try {
      const r = await fn();
      if (succes) toast.success(succes);
      await charger();
      return r;
    } catch (e) {
      toast.error(erreurDe(e, "Action impossible"));
      return null;
    } finally {
      setOccupe(false);
    }
  }

  if (refuse) return <Cadre><p className="text-sm text-slate-600">Réservé au super-administrateur SAWALI.</p></Cadre>;
  if (!donnees || !saisie) {
    return <Cadre><p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p></Cadre>;
  }
  const reg = donnees.reglages;
  const cal = donnees.calendrier;
  const derniere = donnees.derniere_execution;
  const nbSusp = donnees.clients.filter((c) => c.statut === "SUSPENDU_NON_RENOUVELE").length;
  const nbArch = donnees.clients.filter((c) => c.statut === "ARCHIVE").length;

  return (
    <Cadre>
      <p className="text-xs text-slate-600">
        Échéance = dernier règlement + périodicité du contrat (comme la coupure). J+{cal.avertissement_suspension} : avertissement ;
        J+{cal.suspension} : suspension (plus aucun accès, « Voir en tant que » reste possible) ; J+{cal.avertissement_suppression} :
        dernier avis ; J+{cal.archivage} : archive chiffrée dans R2, relue et vérifiée, puis suppression des données du client
        (fiche conservée au statut « Archivé »). Avertissements par WhatsApp et e-mail, une seule fois chacun.
        Les délais sont des minimums : jamais de suspension sans 7 jours de préavis, jamais d'archivage sans 3 jours de suspension et un dernier avis la veille.
        Clients de test, démo et internes : exclus. Clients sans échéance : jamais concernés.
      </p>
      {donnees.archive_impossible && (
        <p className="rounded-lg border border-orange-200 bg-orange-50 p-2 text-xs text-orange-800" data-testid="cycle-vie-archive-impossible">
          Archivage et réouverture impossibles pour l'instant : {donnees.archive_impossible}. Aucun client ne sera supprimé tant que ce n'est pas réglé.
        </p>
      )}

      {/* ---------- Réglages ---------- */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={!!reg.actif} disabled={occupe} data-testid="toggle-cycle-vie"
              onChange={(e) => {
                const actif = e.target.checked;
                if (actif && !window.confirm("Activer le cycle de vie automatique ?\n\nFaites d'abord « Simuler maintenant » et vérifiez que les règlements sont bien saisis.")) return;
                action(() => apiClient.put("/admin/cycle-vie/reglages", { actif }), actif ? "Cycle de vie activé." : "Cycle de vie désactivé.");
              }} />
            <span><b>Cycle de vie automatique</b> (tâche quotidienne à 06:40)
              <span className="block text-xs text-slate-500">Désactivé par défaut : rien n'est envoyé, suspendu ni supprimé.</span></span>
          </label>
          <label className="flex items-start gap-2">
            <input type="checkbox" className="mt-1" checked={!!reg.simulation} disabled={occupe} data-testid="toggle-cycle-vie-simulation"
              onChange={(e) => {
                const sim = e.target.checked;
                if (!sim && !window.confirm("Quitter le mode simulation ?\n\nLes avertissements, suspensions, archivages et suppressions seront réellement faits.")) return;
                action(() => apiClient.put("/admin/cycle-vie/reglages", { simulation: sim }), sim ? "Mode simulation activé." : "Mode simulation désactivé.");
              }} />
            <span><b>Mode simulation</b>
              <span className="block text-xs text-slate-500">La tâche liste ce qui serait fait (rapport par e-mail) sans rien faire.</span></span>
          </label>
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="button" disabled={occupe} data-testid="cycle-vie-simuler"
              className="inline-flex items-center gap-1 rounded-lg bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
              onClick={async () => { const r = await action(() => apiClient.post("/admin/cycle-vie/simuler")); if (r) setSimulation(r.data); }}>
              <FlaskConical className="h-3 w-3" /> Simuler maintenant
            </button>
            {reg.actif && (
              <button type="button" disabled={occupe} data-testid="cycle-vie-lancer"
                className="inline-flex items-center gap-1 rounded-lg bg-red-700 px-3 py-1 text-xs font-semibold text-white hover:bg-red-800 disabled:opacity-50"
                onClick={() => window.confirm(reg.simulation ? "Lancer maintenant (mode simulation) ?" : "Lancer maintenant ? Les actions prévues aujourd'hui seront RÉELLEMENT faites.")
                  && action(() => apiClient.post("/admin/cycle-vie/lancer"), "Exécution lancée : actualisez dans un instant.")}>
                <Play className="h-3 w-3" /> Lancer maintenant
              </button>
            )}
          </div>
        </div>
        <div className="space-y-2 rounded-lg bg-slate-50 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-48">Conservation des archives (jours)</span>
            <input type="number" min={donnees.conservation.min} max={donnees.conservation.max} value={saisie.conservation_jours}
              onChange={(e) => setSaisie({ ...saisie, conservation_jours: e.target.value })}
              className="w-24 rounded-lg border border-slate-300 px-2 py-1 text-sm" data-testid="input-conservation" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-48">Frais de réouverture</span>
            <input type="number" min={0} value={saisie.frais_montant} onChange={(e) => setSaisie({ ...saisie, frais_montant: e.target.value })}
              className="w-28 rounded-lg border border-slate-300 px-2 py-1 text-sm" data-testid="input-frais-montant" />
            <input type="text" maxLength={8} value={saisie.frais_devise} onChange={(e) => setSaisie({ ...saisie, frais_devise: e.target.value })}
              className="w-20 rounded-lg border border-slate-300 px-2 py-1 text-sm uppercase" data-testid="input-frais-devise" />
          </div>
          <button type="button" disabled={occupe} className="rounded-lg bg-sky-700 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
            onClick={() => action(() => apiClient.put("/admin/cycle-vie/reglages", {
              conservation_jours: Number(saisie.conservation_jours), frais_montant: Number(saisie.frais_montant), frais_devise: saisie.frais_devise,
            }), "Réglages enregistrés.")}>
            Enregistrer
          </button>
          <p className="text-xs text-slate-500">
            Conservation de {donnees.conservation.min} à {donnees.conservation.max} jours ({donnees.conservation.defaut} par défaut) ; ensuite l'archive est effacée de R2 et la réouverture n'est plus possible.
          </p>
        </div>
      </div>

      {derniere && (
        <p className="text-xs text-slate-600" data-testid="cycle-vie-derniere">
          Dernière exécution : {formatDateHeure(derniere.le)} — {derniere.statut === "DESACTIVE" ? "interrupteur désactivé" : `${(derniere.actions || []).length} action(s)${derniere.simulation ? " (simulation)" : ""}`}
          {(derniere.alertes || []).length > 0 && <span className="ml-1 font-semibold text-red-700">— {derniere.alertes.length} alerte(s) : {derniere.alertes.join(" ; ")}</span>}
        </p>
      )}

      {simulation && (
        <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs" data-testid="cycle-vie-resultat-simulation">
          <p className="font-semibold text-sky-900">Simulation du {formatDateHeure(simulation.le)} : {simulation.actions.length} action(s) seraient faites (rien n'a été fait).</p>
          <ul className="mt-1 list-disc pl-5">
            {simulation.actions.map((a, i) => <li key={i}>{LIBELLES[a.action] || a.action} — {a.nom}{a.jours != null ? ` (J+${a.jours})` : ""}</li>)}
          </ul>
        </div>
      )}

      {/* ---------- Clients ---------- */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-600">{donnees.clients.length} client(s) en retard — {nbSusp} suspendu(s), {nbArch} archivé(s)</p>
        <button type="button" onClick={charger} className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900">
          <RefreshCw className="h-3 w-3" /> Actualiser
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="py-1 pr-2">Client</th><th className="py-1 pr-2">Statut</th><th className="py-1 pr-2">Échéance</th>
              <th className="py-1 pr-2">Jours</th><th className="py-1 pr-2">Calendrier</th><th className="py-1 pr-2">Aujourd'hui</th><th className="py-1" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {donnees.clients.map((c) => {
              const [libelle, classe] = STATUTS[c.statut] || [c.statut, "bg-slate-100"];
              const k = c.calendrier;
              return (
                <tr key={c.client_id} data-testid={`cycle-vie-${c.client_id}`}>
                  <td className="py-2 pr-2"><span className="font-semibold text-slate-800">{c.nom}</span>
                    <span className="block text-[10px] text-slate-500">{c.email}</span></td>
                  <td className="py-2 pr-2">
                    {c.exclu ? <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">Exclu : {c.exclu}</span>
                      : <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${classe}`}>{libelle}</span>}
                    {c.suspendu_le && c.statut !== "ACTIF" && <span className="block text-[10px] text-slate-500">suspendu le {dateFr(c.suspendu_le)}</span>}
                    {c.leve_par_admin && <span className="block text-[10px] text-slate-500">suspension levée par le super-admin</span>}
                  </td>
                  <td className="py-2 pr-2">{dateFr(c.echeance)}</td>
                  <td className="py-2 pr-2">{c.jours != null ? `J+${c.jours}` : "—"}</td>
                  <td className="py-2 pr-2 text-[10px] text-slate-600">
                    {k ? (<>
                      avert. {dateFr(k.avertissement_suspension)} · suspension {dateFr(k.suspension)}<br />
                      dernier avis {dateFr(k.avertissement_suppression)} · archivage {dateFr(k.archivage)}
                      {(c.avertissements || []).length > 0 && <><br />envoyés : {c.avertissements.join(", ")}</>}
                    </>) : c.archive ? (<>
                      archivé le {dateFr(c.archive.le)} · {c.archive.documents} document(s)<br />
                      {c.archive.effacee_le ? `archive effacée le ${dateFr(c.archive.effacee_le)}` : `conservée jusqu'au ${dateFr(c.archive.conservation_jusqu_au)}`}
                    </>) : "—"}
                  </td>
                  <td className="py-2 pr-2">{(c.actions || []).map((a) => <span key={a} className="mr-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-900">{LIBELLES[a] || a}</span>)}</td>
                  <td className="py-2 text-right">
                    {c.statut === "SUSPENDU_NON_RENOUVELE" && (
                      <button type="button" disabled={occupe} className="rounded-md px-2 py-1 text-[11px] text-sky-800 ring-1 ring-sky-200 hover:bg-sky-50"
                        onClick={() => window.confirm(`Lever la suspension de « ${c.nom} » sans règlement ? (Elle ne reviendra pas pour cette échéance.)`)
                          && action(() => apiClient.post(`/admin/cycle-vie/${c.client_id}/lever-suspension`), "Suspension levée.")}>
                        Lever la suspension
                      </button>
                    )}
                    {c.statut === "ARCHIVE" && c.archive && !c.archive.effacee_le && (
                      <button type="button" disabled={occupe} data-testid={`reouvrir-${c.client_id}`}
                        className="rounded-md bg-emerald-700 px-2 py-1 text-[11px] font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
                        onClick={() => setReouverture({ client: c, mot_de_passe: "", confirmation: "", frais_encaisses: false, reference: "" })}>
                        Réouvrir
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {reouverture && (
        <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm" data-testid="cycle-vie-reouverture">
          <p className="font-semibold text-emerald-900">Réouvrir « {reouverture.client.nom} »</p>
          <p className="text-xs text-emerald-900">
            L'archive est relue depuis R2, vérifiée, puis restaurée (seuls les documents de ce client sont remplacés). Le statut redevient actif
            et une nouvelle échéance part d'aujourd'hui. Frais de réouverture : <b>{reg.frais_reouverture.montant} {reg.frais_reouverture.devise}</b> (enregistrés comme règlement).
          </p>
          {reg.frais_reouverture.montant > 0 && (
            <label className="flex items-center gap-2 text-xs">
              <input type="checkbox" checked={reouverture.frais_encaisses} onChange={(e) => setReouverture({ ...reouverture, frais_encaisses: e.target.checked })} />
              Frais de réouverture encaissés
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <input type="text" placeholder="Référence du règlement (facultatif)" value={reouverture.reference}
              onChange={(e) => setReouverture({ ...reouverture, reference: e.target.value })} className="rounded-lg border border-slate-300 px-2 py-1 text-xs" />
            <input type="text" placeholder="Tapez REOUVRIR" value={reouverture.confirmation}
              onChange={(e) => setReouverture({ ...reouverture, confirmation: e.target.value })} className="rounded-lg border border-slate-300 px-2 py-1 text-xs" />
            <input type="password" placeholder="Votre mot de passe" value={reouverture.mot_de_passe} autoComplete="current-password"
              onChange={(e) => setReouverture({ ...reouverture, mot_de_passe: e.target.value })} className="rounded-lg border border-slate-300 px-2 py-1 text-xs" />
          </div>
          <div className="flex gap-2">
            <button type="button" disabled={occupe || reouverture.confirmation !== "REOUVRIR" || !reouverture.mot_de_passe}
              className="rounded-lg bg-emerald-700 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-800 disabled:opacity-50"
              onClick={async () => {
                const r = await action(() => apiClient.post(`/admin/cycle-vie/${reouverture.client.client_id}/reouvrir`, {
                  confirmation: reouverture.confirmation, mot_de_passe: reouverture.mot_de_passe,
                  frais_encaisses: reouverture.frais_encaisses, reference: reouverture.reference || null,
                }));
                if (r) { toast.success(`Client réouvert : ${r.data.documents} document(s) restauré(s).`); setReouverture(null); }
              }}>
              {occupe ? <Loader2 className="h-3 w-3 animate-spin" /> : "Confirmer la réouverture"}
            </button>
            <button type="button" className="rounded-lg px-3 py-1 text-xs text-slate-700 ring-1 ring-slate-300" onClick={() => setReouverture(null)}>Annuler</button>
          </div>
        </div>
      )}

      {journal.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold text-slate-700">Journal ({journal.length})</summary>
          <ul className="mt-2 divide-y divide-slate-100">
            {journal.map((j) => (
              <li key={j.id} className="py-1.5">
                <b>{j.action}</b> — {formatDateHeure(j.date)}{j.client_nom ? ` · ${j.client_nom}` : ""}{j.par?.email ? ` · ${j.par.email}` : ""}
                {j.erreur ? <span className="text-red-700"> · {j.erreur}</span> : null}
                {j.documents != null ? ` · ${j.documents} document(s)` : ""}
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
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200" data-testid="section-cycle-vie">
      <h2 className="font-display text-lg font-bold text-slate-900">🗄️ Cycle de vie des abonnements (suspension J+110, archivage J+113)</h2>
      {children}
    </section>
  );
}
