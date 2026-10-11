// AlertesConnexionsSection.jsx — Lot 109 : rubrique « 🔔 Connexions aux plateformes (alerte WhatsApp) » des Paramètres.
// Demande du propriétaire (11/10/2026) : un WhatsApp à chaque connexion sur adLyn, bfmobility, sTer, beAuthentik et
// ZandGo — plateforme, date/heure, adresse IP, utilisateur / numéro (si le client est connecté) et un bouton
// « Visiter le site ».
//   - réglages : alerte activée, connexions de comptes, visites anonymes, délai anti-répétition, plafond par jour,
//     IP exclues (les vôtres), plateformes désactivées ;
//   - modèle Meta « sawali_connexion_plateforme » (hors fenêtre de 24 h) : état + bouton de création ;
//   - bouton « Envoyer un essai » ;
//   - tableau des plateformes (adresse du site, alertes des dernières 24 h) et journal des 50 dernières alertes.
// Règle des tableaux : survol bleu clair, ligne sélectionnée orange (CSS global, classe « ligne-selectionnee »).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// Date ISO → « JJ/MM/AAAA HH:MM » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "short", timeStyle: "short" });
};
// Libellé et couleur du statut d'une alerte
const STATUTS = {
  envoyee: ["Envoyée", "bg-emerald-100 text-emerald-800"],
  en_cours: ["En cours", "bg-sky-100 text-sky-800"],
  ignoree: ["Ignorée", "bg-slate-100 text-slate-600"],
  echec: ["Échec", "bg-rose-100 text-rose-800"],
};
// Couleur de l'état du modèle Meta
const ETAT_MODELE = { APPROVED: "text-emerald-700", PENDING: "text-amber-700", REJECTED: "text-rose-700", ABSENT: "text-rose-700" };

export default function AlertesConnexionsSection() {
  const [donnees, setDonnees] = useState(null);
  const [form, setForm] = useState(null);           // réglages en cours de saisie
  const [modele, setModele] = useState(null);       // état du modèle Meta
  const [occupe, setOccupe] = useState(false);
  const [selection, setSelection] = useState(null);

  // Lecture des réglages, des plateformes et du journal
  const charger = useCallback(async () => {
    try {
      const d = (await apiClient.get("/admin/alertes-connexions")).data;
      setDonnees(d);
      const r = d.reglages;
      setForm({
        alerte_cnx_actif: r.actif, alerte_cnx_connexions: r.connexions, alerte_cnx_visites: r.visites,
        alerte_cnx_delai_min: r.delai_min, alerte_cnx_plafond_jour: r.plafond_jour,
        alerte_cnx_ip_exclues: (r.ip_exclues || []).join(", "),
        alerte_cnx_plateformes_exclues: (r.plateformes_exclues || []).join(", "),
      });
    } catch (e) { setDonnees({ erreur: e?.response?.data?.detail || "Rubrique indisponible" }); }
  }, []);
  // État du modèle chez Meta (lecture séparée : appel à Meta)
  const lireModele = useCallback(async () => {
    try { setModele((await apiClient.get("/admin/alertes-connexions/modele")).data); }
    catch (e) { setModele({ etat: "INCONNU", erreur: e?.response?.data?.detail }); }
  }, []);
  useEffect(() => { charger(); lireModele(); }, [charger, lireModele]);
  // Lot 109.2 — tant que Meta examine le modèle (PENDING), l'état est relu tout seul toutes les 30 s ;
  // la relecture s'arrête d'elle-même dès qu'il est APPROVED, REJECTED… (ou quand on quitte la page).
  useEffect(() => {
    if (modele?.etat !== "PENDING") return undefined;
    const minuterie = setInterval(lireModele, 30_000);
    return () => clearInterval(minuterie);
  }, [modele?.etat, lireModele]);
  // Annonce du verdict de Meta quand l'état change après une attente (toast)
  const etatPrecedent = React.useRef(null);
  useEffect(() => {
    const avant = etatPrecedent.current;
    etatPrecedent.current = modele?.etat || null;
    if (avant !== "PENDING" || !modele?.etat || modele.etat === "PENDING") return;
    if (modele.etat === "APPROVED") toast.success("Meta a approuvé le modèle : les alertes peuvent partir à tout moment");
    else toast.error(`Meta n'a pas approuvé le modèle (${modele.etat})`);
  }, [modele?.etat]);

  // Action avec toast « Patientez… »
  const agir = async (libelle, fn) => {
    setOccupe(true);
    const t = toast.loading(`Patientez… ${libelle}`);
    try { await fn(); toast.dismiss(t); }
    catch (e) { toast.error(e?.response?.data?.detail || "Action impossible", { id: t }); }
    finally { setOccupe(false); }
  };
  const enregistrer = () => agir("enregistrement", async () => {
    await apiClient.put("/admin/alertes-connexions/reglages", form);
    toast.success("Réglages enregistrés");
    await charger();
  });
  const creerModele = () => agir("envoi du modèle à Meta", async () => {
    const r = (await apiClient.post("/admin/alertes-connexions/modele")).data;
    toast.success(`Modèle soumis à Meta (${r.etat})`);
    await lireModele();
  });
  const essai = () => agir("envoi de l'essai", async () => {
    const r = (await apiClient.post("/admin/alertes-connexions/tester", {})).data;
    const e = (r.envois || [])[0] || {};
    if (r.ok) toast.success(`Essai envoyé (${e.mode === "modele" ? "modèle Meta" : "message avec bouton"})`);
    else toast.error(e.erreur || "Essai non envoyé");
    await charger();
  });

  if (!donnees || !form) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (donnees.erreur) return <p className="text-sm text-rose-600">{donnees.erreur}</p>;
  const champ = "rounded-md border border-slate-300 px-2 py-1 text-sm";
  const coche = (cle, libelle) => (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={!!form[cle]} onChange={(e) => setForm({ ...form, [cle]: e.target.checked })} /> {libelle}
    </label>
  );
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-alertes-connexions">
      <p className="text-xs text-slate-600">
        À chaque <b>connexion</b> d'un compte (et, si vous le souhaitez, à chaque <b>nouvelle visite</b> d'un visiteur non
        connecté) sur adLyn, bfmobility, sTer, beAuthentik ou ZandGo, Liluvine vous envoie un WhatsApp : plateforme,
        date et heure, adresse IP, utilisateur et numéro, avec un bouton <b>« Visiter le site »</b>. Destinataires : les
        numéros de la rubrique « Liluvine appelle le propriétaire »
        {donnees.destinataires?.length ? <> (<b>{donnees.destinataires.join(", ")}</b>)</> : <b className="text-rose-700"> — aucun numéro saisi</b>}.
        Si vous avez écrit au numéro SAWALI depuis moins de 24 h, le message part avec un vrai bouton lien (gratuit) ;
        sinon par le modèle Meta ci-dessous (payant, comme tout message modèle).
      </p>

      {/* Réglages */}
      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-2">
          {coche("alerte_cnx_actif", "Alerte activée")}
          {coche("alerte_cnx_connexions", "Connexions de comptes (clients, équipe…)")}
          {coche("alerte_cnx_visites", "Visites de visiteurs non connectés")}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
          <label>Une alerte par personne toutes les (min)
            <input type="number" min={1} value={form.alerte_cnx_delai_min} className={`${champ} mt-1 w-full`}
                   onChange={(e) => setForm({ ...form, alerte_cnx_delai_min: e.target.value })} /></label>
          <label>Plafond par plateforme et par jour
            <input type="number" min={1} value={form.alerte_cnx_plafond_jour} className={`${champ} mt-1 w-full`}
                   onChange={(e) => setForm({ ...form, alerte_cnx_plafond_jour: e.target.value })} /></label>
          <label className="col-span-2">IP exclues (les vôtres, séparées par des virgules)
            <input value={form.alerte_cnx_ip_exclues} className={`${champ} mt-1 w-full`} placeholder="154.66.162.235"
                   onChange={(e) => setForm({ ...form, alerte_cnx_ip_exclues: e.target.value })} /></label>
          <label className="col-span-2">Plateformes sans alerte (codes, séparés par des virgules)
            <input value={form.alerte_cnx_plateformes_exclues} className={`${champ} mt-1 w-full`} placeholder="ex. bfmobility"
                   onChange={(e) => setForm({ ...form, alerte_cnx_plateformes_exclues: e.target.value })} /></label>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={enregistrer} disabled={occupe} className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">Enregistrer</button>
        <button onClick={essai} disabled={occupe} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Envoyer un essai</button>
        <button onClick={() => { charger(); lireModele(); }} className="text-xs text-slate-600 underline">Actualiser</button>
      </div>

      {/* Modèle Meta (hors fenêtre de 24 h) */}
      <div className="rounded-lg bg-slate-50 p-3 text-sm">
        <p>Modèle Meta <code className="text-xs">{donnees.modele}</code> :{" "}
          <b className={ETAT_MODELE[modele?.etat] || "text-slate-700"}>{modele ? modele.etat : "…"}</b>
          {modele?.motif_refus && modele.motif_refus !== "NONE" && <span className="text-rose-700"> — {modele.motif_refus}</span>}
          {modele?.etat === "PENDING" && <span className="ml-1 text-xs text-slate-500">(en revue chez Meta — état relu automatiquement toutes les 30 s)</span>}
        </p>
        {modele && ["ABSENT", "REJECTED"].includes(modele.etat) && (
          <button onClick={creerModele} disabled={occupe} className="mt-2 rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
            Créer le modèle chez Meta
          </button>
        )}
        {modele?.erreur && <p className="mt-1 text-xs text-rose-700">{modele.erreur}</p>}
      </div>

      {/* Plateformes */}
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr><th className="px-2 py-2">Plateforme</th><th className="px-2">Adresse du site (bouton)</th><th className="px-2 text-right">Signaux 24 h</th><th className="px-2 text-right">Alertes envoyées 24 h</th></tr>
          </thead>
          <tbody>
            {donnees.plateformes.map((p) => {
              const c = donnees.compteurs_24h?.[p.code] || {};
              return (
                <tr key={p.code} className="border-t border-slate-100">
                  <td className="px-2 py-1.5">{p.nom} <span className="text-xs text-slate-400">({p.code})</span></td>
                  <td className="px-2">{p.url_site ? <a href={p.url_site} target="_blank" rel="noreferrer" className="text-sky-700 underline">{p.url_site}</a> : <span className="text-xs text-slate-400">connue au premier signal</span>}</td>
                  <td className="px-2 text-right tabular-nums">{c.recues || 0}</td>
                  <td className="px-2 text-right tabular-nums">{c.envoyees || 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Journal des dernières alertes */}
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr><th className="px-2 py-2">Date</th><th className="px-2">Plateforme</th><th className="px-2">Type</th><th className="px-2">Utilisateur</th><th className="px-2">IP</th><th className="px-2">Statut</th></tr>
          </thead>
          <tbody>
            {donnees.dernieres.length === 0 && (
              <tr><td colSpan={6} className="px-2 py-4 text-center text-slate-500">Aucun signal reçu pour l'instant : les plateformes l'enverront à la prochaine connexion.</td></tr>
            )}
            {donnees.dernieres.map((a) => {
              const [lib, coul] = STATUTS[a.statut] || [a.statut, "bg-slate-100"];
              const erreur = (a.envois || []).find((e) => !e.ok)?.erreur;
              return (
                <tr key={a.id} onClick={() => setSelection(a.id)} aria-selected={selection === a.id}
                    className={`cursor-pointer border-t border-slate-100 ${selection === a.id ? "ligne-selectionnee" : ""}`}>
                  <td className="whitespace-nowrap px-2 py-1.5">{dateHeure(a.le)}</td>
                  <td className="px-2">{a.plateforme}</td>
                  <td className="px-2">{a.type === "connexion" ? "Connexion" : "Visite"}</td>
                  <td className="px-2">{a.utilisateur || (a.telephone ? `+${a.telephone}` : "Visiteur non connecté")}{a.role ? <span className="text-xs opacity-70"> · {a.role}</span> : null}</td>
                  <td className="whitespace-nowrap px-2 font-mono text-xs">{a.ip || "—"}</td>
                  <td className="px-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${coul}`}>{lib}</span>
                    {(a.raison || erreur) && <span className="block text-[11px] opacity-70">{a.raison || erreur}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
