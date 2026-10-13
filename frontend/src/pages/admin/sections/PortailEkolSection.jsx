// =====================================================================
// Lot 134 — Rubrique des Paramètres « 🎓 Portail e-Kol (élèves et parents) ».
// Le portail e-Kol (plateforme séparée) lit chez SAWALI, par une route signée, les tables e-Kol que Loois synchronise.
// Cette rubrique montre : la clé partagée EKOL_PORTAIL_HMAC est-elle configurée ? et, pour chaque école, quelles
// tables utiles au portail sont déjà synchronisées (sinon : les activer dans Plateformes → Loois → Synchro).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { RefreshCw, Check, X, KeyRound } from "lucide-react";

// Date lisible « 12/10/2026 14:05 »
const dateLisible = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");


// =====================================================================
// Lot 137 — « Enrôler une école » : une fiche (code, nom, ville) crée la clé de l'école ET l'école dans le portail,
// puis la checklist suit l'avancement école par école. Reste manuel : saisir la clé sur le poste de l'école.
// =====================================================================
function EnrolementEcole() {
  const [liste, setListe] = useState([]);            // écoles enrôlées + étapes
  const [form, setForm] = useState({ code: "", nom: "", ville: "" });
  const [attente, setAttente] = useState(false);      // "Patientez…" pendant l'appel
  const [resultat, setResultat] = useState(null);     // dernière réponse (clé montrée UNE fois)
  const [message, setMessage] = useState("");
  const [copie, setCopie] = useState(false);

  // Lecture de la liste (l'état du portail est interrogé côté serveur)
  const lire = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/ekol-enrolement");
      setListe(r.data.ecoles || []);
    } catch (e) {
      setMessage(e?.response?.status === 403 ? "Réservé à l'administrateur." : "Suivi indisponible.");
    }
  }, []);
  useEffect(() => { lire(); }, [lire]);

  // Envoi de la fiche : clé + école du portail
  const enroler = async (ev) => {
    ev.preventDefault();
    setAttente(true); setMessage(""); setResultat(null); setCopie(false);
    try {
      const r = await apiClient.post("/admin/ekol-enrolement", form);
      setResultat(r.data);
      setForm({ code: "", nom: "", ville: "" });
      await lire();
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Enrôlement impossible.");
    } finally { setAttente(false); }
  };

  // Nouvel essai d'enregistrement au portail
  const reessayer = async (code) => {
    setAttente(true);
    try { const r = await apiClient.post(`/admin/ekol-enrolement/${encodeURIComponent(code)}/portail`); setMessage(r.data.message); await lire(); }
    catch (e) { setMessage(e?.response?.data?.detail || "Échec."); }
    finally { setAttente(false); }
  };

  // Copie de la clé affichée une seule fois
  const copier = async () => {
    try { await navigator.clipboard.writeText(resultat.cle); setCopie(true); } catch { /* copie manuelle */ }
  };

  const champ = "rounded-md border border-slate-300 px-2 py-1 text-sm";
  return (
    <div className="space-y-3 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" data-testid="enrolement-ecole">
      <p className="font-semibold">Enrôler une école en un geste</p>
      <p className="text-xs text-slate-600">
        Crée la clé de l'école (application e-Kol) et l'enregistre dans le portail avec le même code. Reste à faire sur place :
        saisir la clé sur le poste de l'école (lien « Clé client Loois » ou <code>Loois.exe /ekol -msc</code>).
      </p>
      <form onSubmit={enroler} className="flex flex-wrap items-end gap-2">
        <label className="text-xs">Code du site<br /><input className={champ} required minLength={2} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="LYCEE-PRIVE-X" /></label>
        <label className="text-xs">Nom de l'école<br /><input className={champ} required minLength={2} value={form.nom} onChange={(e) => setForm({ ...form, nom: e.target.value })} /></label>
        <label className="text-xs">Ville<br /><input className={champ} value={form.ville} onChange={(e) => setForm({ ...form, ville: e.target.value })} /></label>
        <button type="submit" disabled={attente} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          {attente ? "Patientez…" : "Enrôler"}
        </button>
        {attente && <RefreshCw className="h-4 w-4 animate-spin text-slate-500" aria-label="Patientez" />}
      </form>
      {message && <p className="text-xs text-rose-600">{message}</p>}
      {resultat && (
        <div className="rounded-md bg-white p-2 text-xs ring-1 ring-emerald-300">
          <p><b>{resultat.code}</b> — {resultat.portail.ok ? "école enregistrée dans le portail." : `portail : ${resultat.portail.message}`}</p>
          {resultat.cle
            ? (<p className="mt-1">Clé à saisir sur le poste (affichée UNE seule fois) : <code className="select-all break-all">{resultat.cle}</code>{" "}
                <button type="button" onClick={copier} className="underline">{copie ? "copiée ✓" : "copier"}</button></p>)
            : <p className="mt-1">La clé de cette école existait déjà : elle n'est pas réaffichée (régénérez-la dans « Clés clients » si besoin).</p>}
        </div>
      )}
      {liste.map((e) => (
        <div key={e.code} className="rounded-md bg-white ring-1 ring-slate-200">
          <p className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-3 py-1.5 font-semibold">
            {e.code} <span className="font-normal text-slate-500">{e.nom}{e.ville ? ` · ${e.ville}` : ""}</span>
            {e.complet ? <span className="rounded-full bg-emerald-100 px-2 text-xs text-emerald-800">opérationnelle</span>
              : <span className="text-xs font-normal text-amber-700">à faire : {e.prochaine_action}</span>}
            {!e.etapes.find((s) => s.cle === "portail")?.fait && (
              <button type="button" onClick={() => reessayer(e.code)} className="ml-auto text-xs font-normal underline">Réessayer</button>)}
          </p>
          <ul className="grid gap-x-4 px-3 py-1.5 text-xs sm:grid-cols-2">
            {e.etapes.map((s) => (
              <li key={s.cle} className="flex items-start gap-1">
                {s.fait ? <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" /> : <X className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />}
                <span>{s.libelle}{s.detail ? <span className="text-slate-500"> — {s.detail}</span> : null}</span>
              </li>))}
          </ul>
        </div>))}
    </div>
  );
}

export default function PortailEkolSection() {
  const [etat, setEtat] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [erreur, setErreur] = useState("");

  // Lecture de l'état (clé + tables synchronisées par école)
  const lire = useCallback(async () => {
    setChargement(true);
    try {
      const r = await apiClient.get("/admin/ekol-portail/etat");
      setEtat(r.data);
      setErreur("");
    } catch (e) {
      setErreur(e?.response?.status === 403 ? "Réservé à l'administrateur." : "État indisponible.");
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => { lire(); }, [lire]);

  return (
    <div className="space-y-3 text-sm text-slate-700" data-testid="portail-ekol-section">
      <p>
        Le <b>portail e-Kol</b> permet aux élèves et parents de suivre notes, paiements, alertes et relevés certifiés.
        Il lit ici, par une liaison signée, les tables e-Kol que Loois synchronise depuis chaque école.
      </p>
      <EnrolementEcole />
      <div className="flex items-center gap-2">
        <KeyRound className="h-4 w-4 text-slate-500" aria-hidden="true" />
        <span>Clé partagée <code>EKOL_PORTAIL_HMAC</code> :</span>
        {etat && (etat.cle_configuree
          ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 text-xs font-semibold text-emerald-800"><Check className="h-3 w-3" />configurée</span>
          : <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 text-xs font-semibold text-rose-700"><X className="h-3 w-3" />à saisir sur Render (même valeur que sur le portail)</span>)}
        <button type="button" onClick={lire} disabled={chargement} title="Actualiser" className="ml-auto rounded-md p-1 text-slate-600 hover:bg-slate-100 disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${chargement ? "animate-spin" : ""}`} />
        </button>
      </div>
      {erreur && <p className="text-xs text-rose-600">{erreur}</p>}
      {etat && etat.ecoles.length === 0 && (
        <p className="text-xs text-slate-500">Aucune école e-Kol ne synchronise encore de tables. Activez-les dans Plateformes → Loois → Synchro.</p>
      )}
      {etat && etat.ecoles.map((e) => (
        <div key={e.site} className="rounded-lg ring-1 ring-slate-200">
          <p className="border-b border-slate-100 px-3 py-1.5 font-semibold">{e.site}</p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="px-3 py-1">Table utile au portail</th><th className="px-3 py-1">Synchronisée</th><th className="px-3 py-1">Lignes</th><th className="px-3 py-1">Dernière synchro</th></tr>
              </thead>
              <tbody>
                {etat.tables_utiles.map((t) => {
                  const info = e.tables[t];
                  return (
                    <tr key={t} className="border-t border-slate-100">
                      <td className="px-3 py-1">{t}</td>
                      <td className="px-3 py-1">{info ? <Check className="h-4 w-4 text-emerald-600" aria-label="oui" /> : <X className="h-4 w-4 text-rose-500" aria-label="non" />}</td>
                      <td className="px-3 py-1">{info?.nb_documents ?? "—"}</td>
                      <td className="px-3 py-1 whitespace-nowrap">{dateLisible(info?.derniere_synchro)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
