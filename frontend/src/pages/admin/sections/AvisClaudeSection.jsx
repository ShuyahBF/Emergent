// AvisClaudeSection.jsx — Lot 91 : rubrique « 🧠 Avis Claude sur les demandes » des Paramètres.
// Quand un client du support (Loois ou plateforme web) demande l'ajout ou la correction d'une fonctionnalité,
// Liluvine le fait patienter et transmet la demande à Claude, qui lit le code du dépôt GitHub et rend un avis
// (verdict, complexité, durée estimée). Liluvine rend la réponse au client. Les demandes APPROUVÉES arrivent ici
// (et par e-mail) : le propriétaire décide (accepter, refuser, en attente) et peut écrire un mot au client.
// Règle des tableaux : survol bleu, sélection orange (CSS global, classe « ligne-selectionnee »).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

// Libellés et couleurs des états d'une demande
const STATUTS = {
  analyse: { libelle: "⏳ Analyse en cours", classe: "bg-sky-100 text-sky-800" },
  a_decider: { libelle: "✅ Approuvée — à décider", classe: "bg-emerald-100 text-emerald-800" },
  a_preciser: { libelle: "❓ À préciser (client)", classe: "bg-amber-100 text-amber-800" },
  non_faisable: { libelle: "⛔ Non faisable", classe: "bg-rose-100 text-rose-800" },
  acceptee: { libelle: "👍 Acceptée", classe: "bg-emerald-600 text-white" },
  refusee: { libelle: "👎 Refusée", classe: "bg-slate-200 text-slate-700" },
  erreur: { libelle: "⚠️ Analyse impossible", classe: "bg-rose-100 text-rose-800" },
  // Lot 98 — le client n'a pas répondu aux questions pendant 24 h : la demande est abandonnée (consultable)
  abandonnee: { libelle: "💤 Abandonnée (pas de réponse)", classe: "bg-slate-100 text-slate-500" },
};

// Date courte « 09/10/2026 14:05 »
const dateCourte = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
};

export default function AvisClaudeSection() {
  const { user } = useAuth();
  const estAdmin = user?.role === "admin";
  const [donnees, setDonnees] = useState(null);
  const [selection, setSelection] = useState(null);
  const [message, setMessage] = useState("");
  const [reglages, setReglages] = useState(null);
  const [enCours, setEnCours] = useState(false);

  // Lecture des réglages et des demandes
  const charger = useCallback(async () => {
    try {
      const r = (await apiClient.get("/admin/avis-claude")).data;
      setDonnees(r);
      setReglages((avant) => avant || { ...r.reglages, depotsTexte: Object.entries(r.reglages.depots || {}).map(([c, d]) => `${c}=${d}`).join("\n") });
    } catch (e) { toast.error(e?.response?.data?.detail || "Avis Claude indisponible"); setDonnees({ demandes: [], reglages: {} }); }
  }, []);
  useEffect(() => { charger(); const t = setInterval(charger, 30_000); return () => clearInterval(t); }, [charger]);

  // Enregistrement des réglages (administrateur) : dépôts saisis « code=propriétaire/nom », un par ligne
  const enregistrer = async () => {
    const depots = {};
    (reglages.depotsTexte || "").split("\n").map((l) => l.trim()).filter(Boolean).forEach((l) => {
      const [code, depot] = l.split("=").map((x) => (x || "").trim());
      if (code) depots[code] = depot || "";
    });
    const attente = toast.loading("Patientez…");
    try {
      const r = (await apiClient.put("/admin/avis-claude/reglages", { actif: !!reglages.actif, modele: reglages.modele, email: reglages.email, depots })).data;
      setReglages({ ...r, depotsTexte: Object.entries(r.depots || {}).map(([c, d]) => `${c}=${d}`).join("\n") });
      toast.success("Réglages enregistrés", { id: attente });
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible", { id: attente }); }
  };

  // Décision du propriétaire sur la demande sélectionnée (message facultatif transmis au client par Liluvine)
  const decider = async (decision) => {
    if (!selection) return;
    setEnCours(true);
    const attente = toast.loading("Patientez…");
    try {
      await apiClient.post(`/admin/avis-claude/demandes/${selection}/decision`, { decision, message_client: message });
      toast.success(decision === "acceptee" ? "Demande acceptée" : decision === "refusee" ? "Demande refusée" : "Demande mise en attente", { id: attente });
      setMessage("");
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Décision impossible", { id: attente }); }
    finally { setEnCours(false); }
  };

  // Nouvelle analyse (ex. après avoir ajouté le jeton GitHub ou corrigé le dépôt) — le client n'est pas relancé
  const reanalyser = async () => {
    if (!selection) return;
    const attente = toast.loading("Patientez… Claude relit le code");
    try {
      await apiClient.post(`/admin/avis-claude/demandes/${selection}/reanalyser`);
      toast.success("Analyse relancée : résultat dans un instant", { id: attente });
      setTimeout(charger, 4000);
    } catch (e) { toast.error(e?.response?.data?.detail || "Relance impossible", { id: attente }); }
  };

  if (!donnees || !reglages) return <p className="text-sm text-slate-500">Patientez…</p>;
  const demandes = donnees.demandes || [];
  const d = demandes.find((x) => x.id === selection);
  const a = d?.avis || {};
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-avis-claude">
      <p className="text-xs text-slate-600">
        Quand un client du support (Loois ou plateforme web) demande l'<b>ajout</b> ou la <b>correction</b> d'une
        fonctionnalité, Liluvine le fait patienter et transmet la demande à Claude, qui lit le code du dépôt et évalue
        la faisabilité (complexité, durée). Liluvine rend la réponse au client. Seules les demandes <b>approuvées</b>{" "}
        vous parviennent (ici et par e-mail) : vous décidez. Demande floue : Liluvine pose les questions de Claude ;
        non faisable : réponse polie au client, demande archivée ci-dessous.
      </p>

      {/* État des clés : présentes ou non (jamais leur valeur) */}
      <div className="flex flex-wrap gap-2 text-xs">
        <span className={`rounded-full px-2 py-0.5 font-semibold ${donnees.cle_ia ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}>
          {donnees.cle_ia ? "✅ Clé IA (ANTHROPIC_API_KEY)" : "⚠️ Clé IA absente"}
        </span>
        <span className={`rounded-full px-2 py-0.5 font-semibold ${donnees.jeton_github ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}
              title="Jeton GitHub en lecture seule, à saisir dans Render → Environment (GITHUB_TOKEN)">
          {donnees.jeton_github ? "✅ Lecture du code (GITHUB_TOKEN)" : "⚠️ GITHUB_TOKEN absent : analyse sans lire le code"}
        </span>
        {donnees.a_decider > 0 && <span className="rounded-full bg-orange-100 px-2 py-0.5 font-semibold text-orange-800">{donnees.a_decider} demande(s) à décider</span>}
      </div>

      {/* Réglages (administrateur) */}
      {estAdmin && (
        <div className="grid gap-3 rounded-lg border border-slate-200 p-3 sm:grid-cols-2">
          <label className="flex items-center gap-2 text-sm font-semibold sm:col-span-2">
            <input type="checkbox" checked={!!reglages.actif} onChange={(e) => setReglages({ ...reglages, actif: e.target.checked })} />
            Activer l'avis de Claude sur les demandes de fonctionnalités
          </label>
          <label className="text-xs text-slate-600">Modèle d'analyse
            <input value={reglages.modele || ""} onChange={(e) => setReglages({ ...reglages, modele: e.target.value })}
                   className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-xs text-slate-600">E-mail d'alerte (vide = e-mail de santé du serveur)
            <input value={reglages.email || ""} onChange={(e) => setReglages({ ...reglages, email: e.target.value })}
                   className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm" placeholder="vous@exemple.com" />
          </label>
          <label className="text-xs text-slate-600 sm:col-span-2">Dépôt GitHub de chaque plateforme (une ligne « code=propriétaire/dépôt »)
            <textarea rows={5} value={reglages.depotsTexte || ""} onChange={(e) => setReglages({ ...reglages, depotsTexte: e.target.value })}
                      className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-xs" />
          </label>
          <div className="sm:col-span-2">
            <button onClick={enregistrer} className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white">Enregistrer</button>
          </div>
        </div>
      )}

      {/* Demandes reçues */}
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr><th className="px-2 py-2">N°</th><th className="px-2">Reçue le</th><th className="px-2">Plateforme</th><th className="px-2">Client</th>
              <th className="px-2">Demande</th><th className="px-2">Complexité</th><th className="px-2">Durée</th><th className="px-2">État</th></tr>
          </thead>
          <tbody>
            {demandes.length === 0 && (
              <tr><td colSpan={8} className="px-2 py-4 text-center text-slate-500">Aucune demande pour l'instant : elles apparaîtront dès qu'un client en fera une au support.</td></tr>
            )}
            {demandes.map((x) => {
              const st = STATUTS[x.statut] || { libelle: x.statut, classe: "bg-slate-100" };
              return (
                <tr key={x.id} onClick={() => { setSelection(x.id); setMessage(""); }} aria-selected={selection === x.id}
                    className={`cursor-pointer border-t border-slate-100 ${selection === x.id ? "ligne-selectionnee" : ""}`}>
                  <td className="px-2 py-1.5 font-mono text-xs">{x.numero}</td>
                  <td className="px-2 text-xs">{dateCourte(x.creee_le)}</td>
                  <td className="px-2">{x.plateforme_nom}</td>
                  <td className="px-2">{x.demandeur_nom}</td>
                  <td className="max-w-[280px] truncate px-2" title={x.texte}>{x.avis?.resume || x.texte}</td>
                  <td className="px-2">{x.avis?.complexite || "—"}</td>
                  <td className="px-2">{x.avis?.duree_estimee || "—"}</td>
                  <td className="px-2"><span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${st.classe}`}>{st.libelle}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Détail de la demande sélectionnée et décision */}
      {d && (
        <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm" data-testid="avis-claude-detail">
          <p><b>{d.numero}</b> · {d.plateforme_nom} · dépôt {d.depot || "aucun"}</p>
          <p className="whitespace-pre-wrap"><b>Demande du client :</b> {d.texte}</p>
          {a.analyse_technique && <p className="whitespace-pre-wrap"><b>Analyse de Claude :</b> {a.analyse_technique}</p>}
          {a.questions?.length > 0 && <p><b>Questions au client :</b> {a.questions.join(" · ")}</p>}
          {a.reponse_client && <p className="whitespace-pre-wrap text-slate-600"><b>Réponse envoyée par Liluvine :</b> {a.reponse_client}</p>}
          {d.erreur && <p className="text-rose-700">Erreur : {d.erreur}</p>}
          {d.decision && <p><b>Décision :</b> {d.decision} par {d.decision_par} le {dateCourte(d.decision_le)}</p>}
          {estAdmin && (
            <>
              <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={1500}
                        placeholder="Message au client (facultatif, transmis par Liluvine dans son chat du support)"
                        className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
              <div className="flex flex-wrap gap-2">
                <button disabled={enCours} onClick={() => decider("acceptee")} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Accepter</button>
                <button disabled={enCours} onClick={() => decider("refusee")} className="rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Refuser</button>
                <button disabled={enCours} onClick={() => decider("en_attente")} className="rounded-lg bg-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-800 disabled:opacity-50">Mettre en attente</button>
                <button disabled={enCours} onClick={reanalyser} className="ml-auto rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-semibold disabled:opacity-50">Relancer l'analyse</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
