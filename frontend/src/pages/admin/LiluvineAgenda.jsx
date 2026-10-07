// LiluvineAgenda.jsx — Lot 70 : « Agenda d'appels de Liluvine ».
//
// Liluvine passe elle-même des appels WhatsApp planifiés : relances, recherche de prospects, anniversaires,
// suivi client, compte rendu de maintenance, rappels de rendez-vous… Pour chaque évènement on lui indique
// la date, l'heure, le contact, le type, l'objectif, les informations à recueillir (questions typées), un
// texte à lire, un contexte, la ligne appelante, la récurrence, les tentatives et la plage horaire.
// Écran :
//   • en-tête : totaux de la période (appels, terminés, sans réponse, durée, coût des appels et de l'IA) ;
//   • vues Mois / Semaine / Liste, filtres (type, statut, contact), pastilles colorées par statut ;
//   • création / modification / copie / annulation, « Appeler maintenant », export CSV ;
//   • tiroir de détail : résumé, informations recueillies (par question), action suivante, coût,
//     qualité audio, transcription, tentatives ;
//   • réglages de l'agenda et des anniversaires des utilisateurs suivis.
// Lot 71 : « Mode de l'appel » — objectif et questions (prompt, lot 70) OU formulaire SAWALI : les champs
// du formulaire deviennent les questions ; la réponse est enregistrée dans les réponses du formulaire
// (badge « 📞 Appel ») et le tiroir affiche les réponses champ par champ avec le lien vers la soumission.
// Heures : Africa/Ouagadougou (= UTC) ; affichage JJ/MM/AAAA HH:MM.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import TranscriptionAppelLiluvine from "@/components/TranscriptionAppelLiluvine";

// Fuseau du Burkina Faso (identique à UTC toute l'année)
const FUSEAU = "Africa/Ouagadougou";
// Couleurs des pastilles de statut
const COULEURS = {
  planifie: "bg-sky-100 text-sky-800 ring-sky-200",
  attente_autorisation: "bg-amber-100 text-amber-800 ring-amber-200",
  en_cours: "bg-violet-100 text-violet-800 ring-violet-200",
  termine: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  sans_reponse: "bg-orange-100 text-orange-800 ring-orange-200",
  echec: "bg-rose-100 text-rose-800 ring-rose-200",
  annule: "bg-slate-100 text-slate-500 ring-slate-200 line-through",
};
// Icône de chaque type d'évènement
const ICONES = {
  relance: "🔁", prospection: "🎯", anniversaire: "🎂", suivi_client: "🤝",
  compte_rendu_maintenance: "🛠️", rappel_rdv: "📅", autre: "📞",
};
const JOURS_SEMAINE = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const LIBELLES_QUESTION = { texte: "Texte", oui_non: "Oui / non", date: "Date", montant: "Montant", choix: "Choix" };

// Petite jauge circulaire transparente (attente)
const Jauge = () => (
  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-300 border-t-transparent align-middle" />
);

// ---------------------------------------------------------------------------
// Dates (toutes calculées en UTC = heure de Ouagadougou)
// ---------------------------------------------------------------------------
const jourIso = (d) => d.toISOString().slice(0, 10);                       // Date → « AAAA-MM-JJ »
const ajouterJours = (d, n) => new Date(d.getTime() + n * 86400000);
const lundiDe = (d) => ajouterJours(d, -((d.getUTCDay() + 6) % 7));        // lundi de la semaine
const debutMois = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
const finMois = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0));
const aujourdhui = () => { const n = new Date(); return new Date(Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate())); };
// ISO → « JJ/MM/AAAA HH:MM » (Ouagadougou)
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { timeZone: FUSEAU, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }).replace(",", "") : "");
const heure = (iso) => (iso ? new Date(iso).toLocaleTimeString("fr-FR", { timeZone: FUSEAU, hour: "2-digit", minute: "2-digit" }) : "");
// Secondes → « 1 min 05 s »
const duree = (s) => { const n = Math.round(Number(s) || 0); return n >= 60 ? `${Math.floor(n / 60)} min ${String(n % 60).padStart(2, "0")} s` : `${n} s`; };
// Valeur recueillie → texte lisible
const valeurLisible = (v) => (v === true ? "Oui" : v === false ? "Non" : v === null || v === undefined || v === "" ? "—" : String(v));

// Formulaire vide d'un nouvel évènement (demain 09:00)
const formulaireVide = () => ({
  date_heure: `${jourIso(ajouterJours(aujourdhui(), 1))}T09:00`, type: "relance", titre: "",
  contact: { source: "libre", id: null, nom: "", telephone: "", entreprise: "" },
  objectif: "", questions: [], texte_a_lire: "", contexte: "", maintenance: null, ligne_cle: "",
  recurrence: "aucune", tentatives_max: 3, intervalle_min: 30, plage_debut: "", plage_fin: "", priorite: "normale",
  creer_relance: false,
  mode: "prompt", formulaire: null, lien_formulaire: "auto",   // lot 71 : appel basé sur un formulaire
});
// Lot 71 — statut d'un champ du formulaire après l'appel (tiroir de détail)
const STATUTS_CHAMP = {
  rempli: { libelle: "rempli", classe: "bg-emerald-100 text-emerald-800" },
  vide: { libelle: "non renseigné", classe: "bg-slate-100 text-slate-600" },
  invalide: { libelle: "invalide", classe: "bg-rose-100 text-rose-800" },
  a_completer: { libelle: "à compléter", classe: "bg-amber-100 text-amber-800" },
};

export default function LiluvineAgenda() {
  const [vue, setVue] = useState("mois");                 // mois | semaine | liste
  const [reference, setReference] = useState(aujourdhui()); // jour de référence de la période affichée
  const [filtres, setFiltres] = useState({ type: "", statut: "", q: "" });
  const [donnees, setDonnees] = useState(null);           // réponse de GET /admin/liluvine-agenda
  const [chargement, setChargement] = useState(false);
  const [detail, setDetail] = useState(null);             // évènement ouvert dans le tiroir
  const [formulaire, setFormulaire] = useState(null);     // évènement en création / modification
  const [reglagesOuverts, setReglagesOuverts] = useState(false);
  const [occupe, setOccupe] = useState("");

  // Période affichée selon la vue
  const periode = useMemo(() => {
    if (vue === "semaine") { const l = lundiDe(reference); return { du: l, au: ajouterJours(l, 6) }; }
    return { du: debutMois(reference), au: finMois(reference) };
  }, [vue, reference]);

  // Lecture des évènements de la période (filtres compris)
  const charger = useCallback(async () => {
    setChargement(true);
    try {
      const r = await apiClient.get("/admin/liluvine-agenda", { params: {
        du: jourIso(periode.du), au: jourIso(periode.au),
        type: filtres.type || undefined, statut: filtres.statut || undefined, q: filtres.q || undefined } });
      setDonnees(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Agenda indisponible");
    } finally {
      setChargement(false);
    }
  }, [periode, filtres]);
  useEffect(() => { charger(); }, [charger]);
  // Relecture toutes les 30 s (statuts qui évoluent pendant les appels)
  useEffect(() => { const t = setInterval(() => { if (!document.hidden) charger(); }, 30000); return () => clearInterval(t); }, [charger]);

  // Action longue avec le toast « Patientez… »
  const action = async (nom, fn, succes) => {
    setOccupe(nom);
    const t = toast.loading("Patientez…");
    try {
      const r = await fn();
      toast.success(succes(r), { id: t });
      return r;
    } catch (err) {
      const d = err?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Action impossible", { id: t });
      return null;
    } finally {
      setOccupe("");
    }
  };

  // Ouvre le détail complet (transcription comprise)
  const ouvrir = async (ev) => {
    setDetail(ev);
    try { const r = await apiClient.get(`/admin/liluvine-agenda/${ev.id}`); setDetail(r.data); } catch { /* résumé de la liste */ }
  };

  // Export CSV de la liste filtrée
  const exporter = () => action("csv", async () => {
    const r = await apiClient.get("/admin/liluvine-agenda/export.csv", { responseType: "blob", params: {
      du: jourIso(periode.du), au: jourIso(periode.au), type: filtres.type || undefined,
      statut: filtres.statut || undefined, q: filtres.q || undefined } });
    const url = URL.createObjectURL(r.data);
    const a = document.createElement("a");
    a.href = url; a.download = `agenda-liluvine-${jourIso(periode.du)}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }, () => "Export prêt");

  // Navigation dans les périodes
  const decaler = (sens) => {
    if (vue === "semaine") setReference(ajouterJours(reference, 7 * sens));
    else setReference(new Date(Date.UTC(reference.getUTCFullYear(), reference.getUTCMonth() + sens, 1)));
  };

  const evenements = donnees?.evenements || [];
  const types = donnees?.types || {};
  const statuts = donnees?.statuts || {};
  const t = donnees?.totaux;
  // Évènements regroupés par jour (« AAAA-MM-JJ »)
  const parJour = useMemo(() => {
    const m = {};
    evenements.forEach((e) => { const k = (e.date_heure || "").slice(0, 10); (m[k] = m[k] || []).push(e); });
    return m;
  }, [evenements]);
  const titrePeriode = vue === "semaine"
    ? `Semaine du ${periode.du.toLocaleDateString("fr-FR", { timeZone: "UTC" })} au ${periode.au.toLocaleDateString("fr-FR", { timeZone: "UTC" })}`
    : `${MOIS[reference.getUTCMonth()]} ${reference.getUTCFullYear()}`;

  // Pastille d'un évènement (calendrier)
  const Pastille = ({ e }) => (
    <button type="button" onClick={() => ouvrir(e)} title={`${types[e.type] || e.type} — ${statuts[e.statut] || e.statut}`}
      className={`block w-full truncate rounded px-1 py-0.5 text-left text-[11px] ring-1 ${COULEURS[e.statut] || ""}`}
      data-testid={`pastille-${e.id}`}>
      {heure(e.date_heure)} {ICONES[e.type] || "📞"} {e.contact?.nom || `+${e.telephone}`}
    </button>
  );

  return (
    <div className="space-y-4" data-testid="liluvine-agenda">
      {/* En-tête : titre, actions, totaux de la période */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">📅 Agenda d'appels de Liluvine</h1>
          <p className="text-sm text-slate-500">Liluvine appelle vos contacts à la date prévue, suit vos consignes, pose vos questions et note les réponses.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => setFormulaire(formulaireVide())}
            className="rounded-lg bg-violet-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-violet-800" data-testid="nouvel-evenement">
            ➕ Nouvel évènement
          </button>
          <button type="button" onClick={exporter} disabled={!!occupe} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
            {occupe === "csv" ? <Jauge /> : "⬇️"} Export CSV
          </button>
          <button type="button" onClick={() => setReglagesOuverts(true)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
            ⚙️ Réglages et anniversaires
          </button>
        </div>
      </div>

      {t && (
        <div className="grid gap-2 text-sm sm:grid-cols-3 lg:grid-cols-6" data-testid="totaux-agenda">
          {[["Appels prévus", t.nombre], ["Terminés", t.par_statut?.termine || 0],
            ["Sans réponse", t.par_statut?.sans_reponse || 0], ["En attente d'autorisation", t.par_statut?.attente_autorisation || 0],
            ["Durée totale", duree(t.duree_s)], ["Coût estimé", `${Number(t.cout || 0).toLocaleString("fr-FR")} ${t.devise} + IA ${Number(t.ia_usd || 0).toFixed(3)} $`]]
            .map(([l, v]) => (
              <div key={l} className="rounded-xl bg-white p-2 ring-1 ring-slate-200">
                <p className="text-[11px] uppercase text-slate-500">{l}</p>
                <p className="font-semibold text-slate-800">{v}</p>
              </div>
            ))}
        </div>
      )}
      {donnees?.moteur && !donnees.moteur.disponible && (
        <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800 ring-1 ring-rose-200">Moteur d'appel absent sur le serveur (aiortc) : les appels ne peuvent pas partir.</p>
      )}
      {donnees?.reglages && !donnees.reglages.actif && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">Agenda désactivé dans les réglages : aucun appel automatique.</p>
      )}

      {/* Vue, période, filtres */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl bg-white p-2 ring-1 ring-slate-200 text-sm">
        {[["mois", "Mois"], ["semaine", "Semaine"], ["liste", "Liste"]].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setVue(k)}
            className={`rounded-lg px-3 py-1 ${vue === k ? "bg-violet-700 text-white" : "border border-slate-300 bg-white hover:bg-slate-50"}`}>{l}</button>
        ))}
        <span className="mx-2 h-5 w-px bg-slate-200" />
        <button type="button" onClick={() => decaler(-1)} className="rounded border border-slate-300 px-2 py-0.5">◀</button>
        <button type="button" onClick={() => setReference(aujourdhui())} className="rounded border border-slate-300 px-2 py-0.5">Aujourd'hui</button>
        <button type="button" onClick={() => decaler(1)} className="rounded border border-slate-300 px-2 py-0.5">▶</button>
        <span className="font-semibold capitalize text-slate-700">{titrePeriode}</span>
        {chargement && <Jauge />}
        <span className="flex-1" />
        <select value={filtres.type} onChange={(e) => setFiltres({ ...filtres, type: e.target.value })} className="rounded border border-slate-300 px-2 py-1">
          <option value="">Tous les types</option>
          {Object.entries(types).map(([k, l]) => <option key={k} value={k}>{ICONES[k]} {l}</option>)}
        </select>
        <select value={filtres.statut} onChange={(e) => setFiltres({ ...filtres, statut: e.target.value })} className="rounded border border-slate-300 px-2 py-1">
          <option value="">Tous les statuts</option>
          {Object.entries(statuts).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <input value={filtres.q} onChange={(e) => setFiltres({ ...filtres, q: e.target.value })} placeholder="Contact, numéro…"
          className="w-40 rounded border border-slate-300 px-2 py-1" />
      </div>

      {/* Légende des statuts */}
      <div className="flex flex-wrap gap-1.5 text-[11px]">
        {Object.entries(statuts).map(([k, l]) => <span key={k} className={`rounded px-1.5 py-0.5 ring-1 ${COULEURS[k]}`}>{l}</span>)}
      </div>

      {/* Vue Mois : grille de 7 colonnes (lundi → dimanche) */}
      {vue === "mois" && (
        <div className="grid grid-cols-7 gap-px overflow-hidden rounded-xl bg-slate-200 ring-1 ring-slate-200">
          {JOURS_SEMAINE.map((j) => <div key={j} className="bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-600">{j}</div>)}
          {(() => {
            const cases = [];
            const premier = lundiDe(debutMois(reference));
            const dernier = ajouterJours(lundiDe(finMois(reference)), 6);
            for (let d = premier; d <= dernier; d = ajouterJours(d, 1)) cases.push(d);
            return cases.map((d) => {
              const k = jourIso(d);
              const liste = parJour[k] || [];
              const horsMois = d.getUTCMonth() !== reference.getUTCMonth();
              return (
                <div key={k} className={`min-h-[92px] bg-white p-1 ${horsMois ? "opacity-50" : ""} ${k === jourIso(aujourdhui()) ? "ring-2 ring-inset ring-violet-400" : ""}`}>
                  <div className="flex items-center justify-between text-[11px] text-slate-500">
                    <span>{d.getUTCDate()}</span>
                    {!horsMois && (
                      <button type="button" title="Nouvel évènement ce jour" onClick={() => setFormulaire({ ...formulaireVide(), date_heure: `${k}T09:00` })}
                        className="rounded px-1 text-slate-400 hover:bg-violet-50 hover:text-violet-700">＋</button>
                    )}
                  </div>
                  <div className="mt-0.5 space-y-0.5">
                    {liste.slice(0, 4).map((e) => <Pastille key={e.id} e={e} />)}
                    {liste.length > 4 && <p className="text-[10px] text-slate-500">+ {liste.length - 4} autre(s)</p>}
                  </div>
                </div>
              );
            });
          })()}
        </div>
      )}

      {/* Vue Semaine : 7 colonnes, évènements triés par heure */}
      {vue === "semaine" && (
        <div className="grid gap-2 md:grid-cols-7">
          {Array.from({ length: 7 }, (_, i) => ajouterJours(periode.du, i)).map((d, i) => (
            <div key={i} className="min-h-[160px] rounded-xl bg-white p-2 ring-1 ring-slate-200">
              <p className="mb-1 text-xs font-semibold text-slate-600">{JOURS_SEMAINE[i]} {d.getUTCDate()}/{d.getUTCMonth() + 1}</p>
              <div className="space-y-1">{(parJour[jourIso(d)] || []).map((e) => <Pastille key={e.id} e={e} />)}</div>
            </div>
          ))}
        </div>
      )}

      {/* Vue Liste : tableau (ligne survolée bleu clair, ligne ouverte orange — CSS global) */}
      {vue === "liste" && (
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-600">
              <tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Contact</th>
                <th className="px-3 py-2">Statut</th><th className="px-3 py-2">Tentatives</th><th className="px-3 py-2">Résumé</th><th className="px-3 py-2">Coût</th></tr>
            </thead>
            <tbody>
              {evenements.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-500">Aucun évènement sur la période.</td></tr>}
              {evenements.map((e) => (
                <tr key={e.id} onClick={() => ouvrir(e)} className={`cursor-pointer border-t border-slate-100 ${detail?.id === e.id ? "ligne-selectionnee" : ""}`}>
                  <td className="whitespace-nowrap px-3 py-2">{dateHeure(e.date_heure)}</td>
                  <td className="px-3 py-2">{ICONES[e.type]} {types[e.type] || e.type}</td>
                  <td className="px-3 py-2">{e.contact?.nom}<span className="block text-[11px] opacity-70">+{e.telephone}</span></td>
                  <td className="px-3 py-2"><span className={`rounded px-1.5 py-0.5 text-xs ring-1 ${COULEURS[e.statut] || ""}`}>{statuts[e.statut] || e.statut}</span></td>
                  <td className="px-3 py-2">{e.tentatives || 0} / {e.tentatives_max}</td>
                  <td className="max-w-xs truncate px-3 py-2">{e.resultat?.resume || e.raison || e.objectif || ""}</td>
                  <td className="whitespace-nowrap px-3 py-2">{e.resultat?.cout ? `${e.resultat.cout.cout_total} ${e.resultat.cout.devise}` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <TiroirDetail ev={detail} types={types} statuts={statuts} occupe={occupe} fermer={() => setDetail(null)}
          modifier={() => { setFormulaire({ ...formulaireVide(), ...detail, date_heure: (detail.date_heure || "").slice(0, 16), ligne_cle: detail.ligne_cle || "" }); }}
          appeler={() => action("appeler", () => apiClient.post(`/admin/liluvine-agenda/${detail.id}/appeler-maintenant`),
            () => "Liluvine lance l'appel").then((r) => { if (r) { setDetail(null); setTimeout(charger, 1500); } })}
          dupliquer={() => action("dupliquer", () => apiClient.post(`/admin/liluvine-agenda/${detail.id}/dupliquer`, {}),
            () => "Évènement copié (demain, même heure)").then((r) => { if (r) { charger(); ouvrir(r.data); } })}
          annuler={() => { if (!window.confirm("Annuler cet évènement ?")) return; action("annuler", () => apiClient.post(`/admin/liluvine-agenda/${detail.id}/annuler`),
            () => "Évènement annulé").then((r) => { if (r) { setDetail(null); charger(); } }); }} />
      )}
      {formulaire && (
        <FormulaireEvenement initial={formulaire} donnees={donnees} fermer={() => setFormulaire(null)}
          enregistre={(ev) => { setFormulaire(null); charger(); if (ev) ouvrir(ev); }} />
      )}
      {reglagesOuverts && <ReglagesAgenda lignes={donnees?.lignes || []} fermer={() => { setReglagesOuverts(false); charger(); }} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tiroir de détail d'un évènement
// ---------------------------------------------------------------------------
function TiroirDetail({ ev, types, statuts, occupe, fermer, modifier, appeler, dupliquer, annuler }) {
  const r = ev.resultat || null;
  const modifiable = !["en_cours"].includes(ev.statut);
  // Journal au format attendu par TranscriptionAppelLiluvine (résumé, transcription, coût IA, qualité audio)
  const journal = r ? { resume: r.resume, fin: r.fin, transcription: r.transcription, cout: r.cout?.detail_ia,
    qualite_audio: r.qualite_audio, transfert_humain: r.transfert_humain } : null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={fermer}>
      <aside className="h-full w-full max-w-xl overflow-y-auto bg-white p-4 shadow-xl" onClick={(e) => e.stopPropagation()} data-testid="tiroir-agenda">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs text-slate-500">{ICONES[ev.type]} {types[ev.type] || ev.type} · {dateHeure(ev.date_heure)}</p>
            <h2 className="text-lg font-bold text-slate-800">{ev.titre}</h2>
            <p className="text-sm text-slate-600">{ev.contact?.nom} · +{ev.telephone}{ev.contact?.entreprise ? ` · ${ev.contact.entreprise}` : ""}</p>
          </div>
          <button type="button" onClick={fermer} className="rounded px-2 text-xl text-slate-400 hover:bg-slate-100">×</button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded px-1.5 py-0.5 ring-1 ${COULEURS[ev.statut] || ""}`}>{statuts[ev.statut] || ev.statut}</span>
          <span>Tentatives : {ev.tentatives || 0} / {ev.tentatives_max}</span>
          {ev.recurrence && ev.recurrence !== "aucune" && <span>🔁 {ev.recurrence}</span>}
          {ev.priorite === "haute" && <span className="text-rose-700">⚡ priorité haute</span>}
          {ev.raison && <span className="text-slate-500">· {ev.raison}</span>}
          {ev.report_raison && ev.statut === "planifie" && <span className="text-slate-500">· reporté : {ev.report_raison}</span>}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {["planifie", "attente_autorisation", "sans_reponse", "echec"].includes(ev.statut) && (
            <button type="button" onClick={appeler} disabled={!!occupe} className="rounded-lg bg-emerald-600 px-3 py-1 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50">
              {occupe === "appeler" ? <Jauge /> : "📞"} Appeler maintenant
            </button>
          )}
          {modifiable && <button type="button" onClick={modifier} className="rounded-lg border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">✏️ Modifier</button>}
          <button type="button" onClick={dupliquer} disabled={!!occupe} className="rounded-lg border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50 disabled:opacity-50">📄 Dupliquer</button>
          {["planifie", "attente_autorisation", "sans_reponse", "echec"].includes(ev.statut) && (
            <button type="button" onClick={annuler} disabled={!!occupe} className="rounded-lg border border-rose-300 px-3 py-1 text-sm text-rose-700 hover:bg-rose-50 disabled:opacity-50">🚫 Annuler</button>
          )}
        </div>

        {/* Consignes données à Liluvine */}
        <div className="mt-4 space-y-1 text-sm">
          {ev.mode === "formulaire" && ev.formulaire && (
            <p><strong>Formulaire :</strong> 📋 {ev.formulaire.titre || ev.formulaire.id}
              {ev.formulaire.nb_champs != null && <span className="text-xs text-slate-500"> · {ev.formulaire.nb_vocaux} champ(s) demandés au téléphone{ev.formulaire.nb_a_completer ? `, ${ev.formulaire.nb_a_completer} à compléter par écrit` : ""}</span>}
            </p>
          )}
          {ev.objectif && <p><strong>Objectif :</strong> {ev.objectif}</p>}
          {ev.texte_a_lire && <p><strong>Texte lu :</strong> {ev.texte_a_lire}</p>}
          {ev.contexte && <p><strong>Contexte :</strong> {ev.contexte}</p>}
          {ev.maintenance?.resume && <p><strong>Maintenance :</strong> {ev.maintenance.resume}</p>}
          {ev.statut === "attente_autorisation" && (
            <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
              Demande d'autorisation d'appel envoyée le {dateHeure(ev.autorisation_demandee_le)}{ev.autorisation_envoi?.raison ? ` (${ev.autorisation_envoi.raison})` : ""} : l'appel partira dès que le contact acceptera.
            </p>
          )}
        </div>

        {/* Résultat de l'appel */}
        {r && (
          <div className="mt-4 space-y-3">
            <h3 className="text-sm font-bold text-slate-700">Résultat de l'appel</h3>
            {/* Lot 71 — appel basé sur un formulaire : réponses champ par champ + lien vers la soumission */}
            {r.formulaire && (
              <div className="rounded-lg ring-1 ring-violet-200 bg-violet-50/40 p-2" data-testid="resultat-formulaire">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold text-violet-900">📋 {r.formulaire.titre}
                    <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] ${r.formulaire.complet ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
                      {r.formulaire.complet ? "complète" : "incomplète"}
                    </span>
                  </p>
                  {r.formulaire.soumission_id
                    ? <a href={r.formulaire.lien_soumission} className="text-xs font-semibold text-violet-800 underline">Voir la réponse dans le formulaire →</a>
                    : <span className="text-xs text-slate-500">Aucune réponse enregistrée{r.formulaire.erreur ? ` (${r.formulaire.erreur})` : " (aucun champ rempli)"}</span>}
                </div>
                <table className="mt-1 w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-600">
                    <tr><th className="px-2 py-1">Champ</th><th className="px-2 py-1">Réponse</th><th className="px-2 py-1">État</th><th className="px-2 py-1">Confiance</th></tr>
                  </thead>
                  <tbody>
                    {(r.formulaire.reponses || []).map((c) => (
                      <tr key={c.id} className="border-t border-slate-100">
                        <td className="px-2 py-1">{c.label}{c.required && <span className="text-rose-600"> *</span>}</td>
                        <td className="px-2 py-1 font-semibold">{Array.isArray(c.valeur) ? c.valeur.join(", ") : valeurLisible(c.valeur)}</td>
                        <td className="px-2 py-1">
                          <span className={`rounded px-1.5 py-0.5 text-[10px] ${(STATUTS_CHAMP[c.statut] || {}).classe || ""}`} title={c.motif || ""}>{(STATUTS_CHAMP[c.statut] || {}).libelle || c.statut}</span>
                        </td>
                        <td className="px-2 py-1">{c.valeur != null ? `${Math.round((c.confiance || 0) * 100)} %` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {r.formulaire.lien_envoye && (
                  <p className="mt-1 text-xs text-slate-600">🔗 Lien du formulaire par WhatsApp : {r.formulaire.lien_envoye.ok ? `envoyé (${r.formulaire.lien_envoye.mode === "modele" ? "modèle Meta" : "texte"})` : `non envoyé — ${r.formulaire.lien_envoye.erreur || ""}`}</p>
                )}
              </div>
            )}
            {!r.formulaire && (r.informations || []).length > 0 && (
              <table className="w-full text-sm" data-testid="informations-recueillies">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-600">
                  <tr><th className="px-2 py-1">Information</th><th className="px-2 py-1">Réponse</th><th className="px-2 py-1">Confiance</th></tr>
                </thead>
                <tbody>
                  {r.informations.map((i) => (
                    <tr key={i.id} className="border-t border-slate-100">
                      <td className="px-2 py-1">{i.libelle} <span className="text-[10px] text-slate-400">({LIBELLES_QUESTION[i.type] || i.type})</span></td>
                      <td className="px-2 py-1 font-semibold">{valeurLisible(i.valeur)}</td>
                      <td className="px-2 py-1">{i.confiance != null ? `${Math.round(i.confiance * 100)} %` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {r.action_suivante?.texte && (
              <p className="rounded bg-sky-50 px-2 py-1 text-sm text-sky-900">
                ➡️ Action suivante suggérée : {r.action_suivante.texte}{r.action_suivante.date ? ` (le ${dateHeure(r.action_suivante.date)})` : ""}
                {ev.relance_id && " — évènement de relance créé"}
              </p>
            )}
            <p className="text-xs text-slate-600">
              Durée {duree(r.duree_meta_s || r.duree_s)}{r.duree_meta_s ? " (Meta)" : ""}
              {r.cout && ` · coût de l'appel ${r.cout.cout_total} ${r.cout.devise} (${r.cout.secondes_facturees} s facturées) · IA ≈ ${Number(r.cout.ia_usd || 0).toFixed(3)} $`}
              {r.extraction_erreur && ` · ⚠️ ${r.extraction_erreur}`}
            </p>
            <TranscriptionAppelLiluvine l={journal} />
          </div>
        )}
        {ev.repli && (
          <p className="mt-3 text-xs text-slate-600">✉️ Message WhatsApp de repli : {ev.repli.ok ? `envoyé (${ev.repli.mode === "modele" ? "modèle Meta" : "texte"})` : `non envoyé — ${ev.repli.erreur || ""}`}</p>
        )}

        {/* Historique des tentatives */}
        {(ev.historique || []).length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-bold text-slate-700">Tentatives</h3>
            <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
              {ev.historique.map((h, i) => <li key={i}>{dateHeure(h.le)} — {h.resultat}{h.raison ? ` (${h.raison})` : ""}</li>)}
            </ul>
          </div>
        )}
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Formulaire : création / modification d'un évènement
// ---------------------------------------------------------------------------
function FormulaireEvenement({ initial, donnees, fermer, enregistre }) {
  const [f, setF] = useState(initial);
  const [recherche, setRecherche] = useState("");
  const [proposes, setProposes] = useState([]);
  const [rechercheMnt, setRechercheMnt] = useState("");
  const [maintenances, setMaintenances] = useState([]);
  const [enCours, setEnCours] = useState(false);
  // Lot 71 — formulaires disponibles (mode « Formulaire ») et aperçu des questions du formulaire choisi
  const [rechercheForm, setRechercheForm] = useState("");
  const [formulaires, setFormulaires] = useState([]);
  const [chargeForms, setChargeForms] = useState(false);
  const [apercu, setApercu] = useState(null);
  const types = donnees?.types || {};
  const maj = (cle, valeur) => setF((x) => ({ ...x, [cle]: valeur }));
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";

  // Recherche d'un contact (WhatsApp, client, utilisateur suivi) dès 2 caractères
  useEffect(() => {
    if (recherche.trim().length < 2) { setProposes([]); return undefined; }
    const t = setTimeout(async () => {
      try { const r = await apiClient.get("/admin/liluvine-agenda/contacts", { params: { q: recherche } }); setProposes(r.data.contacts || []); } catch { setProposes([]); }
    }, 300);
    return () => clearTimeout(t);
  }, [recherche]);
  // Recherche d'une fiche de maintenance (compte rendu)
  useEffect(() => {
    if (f.type !== "compte_rendu_maintenance") return undefined;
    const t = setTimeout(async () => {
      try { const r = await apiClient.get("/admin/liluvine-agenda/maintenances", { params: { q: rechercheMnt } }); setMaintenances(r.data.maintenances || []); } catch { setMaintenances([]); }
    }, 300);
    return () => clearTimeout(t);
  }, [rechercheMnt, f.type]);

  // Lot 71 — liste des formulaires (recherche par titre) quand le mode « Formulaire » est choisi
  useEffect(() => {
    if (f.mode !== "formulaire") return undefined;
    const t = setTimeout(async () => {
      setChargeForms(true);
      try { const r = await apiClient.get("/admin/liluvine-agenda/formulaires", { params: { q: rechercheForm } }); setFormulaires(r.data.formulaires || []); } catch { setFormulaires([]); }
      finally { setChargeForms(false); }
    }, 300);
    return () => clearTimeout(t);
  }, [rechercheForm, f.mode]);
  // Lot 71 — aperçu des questions que Liluvine posera pour le formulaire choisi
  useEffect(() => {
    const fid = f.mode === "formulaire" ? f.formulaire?.id : null;
    if (!fid) { setApercu(null); return; }
    apiClient.get(`/admin/liluvine-agenda/formulaires/${fid}/apercu`).then((r) => setApercu(r.data)).catch(() => setApercu(null));
  }, [f.mode, f.formulaire?.id]);

  // Questions : ajout, modification, retrait
  const majQuestion = (i, cle, valeur) => maj("questions", f.questions.map((q, j) => (j === i ? { ...q, [cle]: valeur } : q)));
  const ajouterQuestion = () => maj("questions", [...(f.questions || []), { libelle: "", type: "texte", choix: [] }]);

  // Enregistrement (création ou modification)
  const enregistrer = async (e) => {
    e.preventDefault();
    setEnCours(true);
    const t = toast.loading("Patientez…");
    try {
      const corps = { ...f, questions: (f.questions || []).filter((q) => (q.libelle || "").trim()),
        tentatives_max: Number(f.tentatives_max) || 3, intervalle_min: Number(f.intervalle_min) || 30 };
      const r = f.id ? await apiClient.put(`/admin/liluvine-agenda/${f.id}`, corps) : await apiClient.post("/admin/liluvine-agenda", corps);
      toast.success(f.id ? "Évènement modifié" : "Évènement planifié", { id: t });
      enregistre(r.data);
    } catch (err) {
      const d = err?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Enregistrement impossible", { id: t });
    } finally {
      setEnCours(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4">
      <form onSubmit={enregistrer} className="w-full max-w-3xl space-y-3 rounded-2xl bg-white p-4 shadow-xl" data-testid="formulaire-agenda">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">{f.id ? "Modifier l'évènement" : "Nouvel évènement"}</h2>
          <button type="button" onClick={fermer} className="rounded px-2 text-xl text-slate-400 hover:bg-slate-100">×</button>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block text-xs font-semibold">Date et heure (Ouagadougou)
            <input type="datetime-local" required value={f.date_heure} onChange={(e) => maj("date_heure", e.target.value)} className={champ} />
          </label>
          <label className="block text-xs font-semibold">Type d'évènement
            <select value={f.type} onChange={(e) => maj("type", e.target.value)} className={champ}>
              {Object.entries(types).map(([k, l]) => <option key={k} value={k}>{ICONES[k]} {l}</option>)}
            </select>
          </label>
          <label className="block text-xs font-semibold">Priorité
            <select value={f.priorite} onChange={(e) => maj("priorite", e.target.value)} className={champ}>
              <option value="haute">Haute</option><option value="normale">Normale</option><option value="basse">Basse</option>
            </select>
          </label>
        </div>

        {/* Contact : recherche ou saisie libre */}
        <div className="rounded-lg bg-slate-50 p-2">
          <p className="text-xs font-semibold text-slate-700">Contact</p>
          <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher : contact WhatsApp, client, utilisateur suivi (nom ou numéro)" className={champ} />
          {proposes.length > 0 && (
            <div className="mt-1 max-h-40 overflow-auto rounded border border-slate-200 bg-white">
              {proposes.map((c) => (
                <button type="button" key={`${c.source}-${c.id}`} className="block w-full px-2 py-1 text-left text-sm hover:bg-violet-50"
                  onClick={() => { maj("contact", { source: c.source, id: c.id, nom: c.nom, telephone: c.telephone, entreprise: c.entreprise || "" }); setRecherche(""); setProposes([]); }}>
                  {c.nom} · +{c.telephone} <span className="text-[11px] text-slate-500">({c.source === "contact" ? "contact WhatsApp" : c.source === "client" ? "client" : "utilisateur suivi"}{c.entreprise ? ` · ${c.entreprise}` : ""})</span>
                </button>
              ))}
            </div>
          )}
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <input value={f.contact.nom || ""} onChange={(e) => maj("contact", { ...f.contact, nom: e.target.value })} placeholder="Nom" className={champ} />
            <input value={f.contact.telephone || ""} onChange={(e) => maj("contact", { ...f.contact, telephone: e.target.value, source: f.contact.source || "libre" })} placeholder="N° WhatsApp (+226…)" required className={champ} />
            <input value={f.contact.entreprise || ""} onChange={(e) => maj("contact", { ...f.contact, entreprise: e.target.value })} placeholder="Entreprise" className={champ} />
          </div>
        </div>

        <label className="block text-xs font-semibold">Titre (facultatif)
          <input value={f.titre || ""} onChange={(e) => maj("titre", e.target.value)} placeholder={`${types[f.type] || ""} — ${f.contact.nom || "contact"}`} className={champ} />
        </label>
        <label className="block text-xs font-semibold">Objectif : consignes données à Liluvine
          <textarea rows={2} value={f.objectif} onChange={(e) => maj("objectif", e.target.value)} placeholder="Ex. Savoir si la commande a été reçue et proposer le réassort." className={champ} />
        </label>

        {/* Lot 71 — Mode de l'appel : objectif et questions (prompt) ou formulaire */}
        <div className="rounded-lg bg-violet-50/60 p-2" data-testid="mode-appel">
          <p className="text-xs font-semibold text-slate-700">Mode de l'appel</p>
          <div className="mt-1 flex flex-wrap gap-4 text-sm">
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" name="mode-appel" checked={f.mode !== "formulaire"} onChange={() => maj("mode", "prompt")} /> Objectif et questions (prompt)
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input type="radio" name="mode-appel" checked={f.mode === "formulaire"} onChange={() => maj("mode", "formulaire")} /> Formulaire
            </label>
          </div>
          {f.mode === "formulaire" && (
            <div className="mt-2 space-y-1">
              {f.formulaire?.id && (
                <p className="text-sm">✅ 📋 {f.formulaire.titre || f.formulaire.id}
                  <button type="button" onClick={() => maj("formulaire", null)} className="ml-2 text-xs text-rose-700">changer</button></p>
              )}
              {!f.formulaire?.id && (
                <>
                  <input value={rechercheForm} onChange={(e) => setRechercheForm(e.target.value)} placeholder="Rechercher un formulaire (titre)" className={champ} />
                  <div className="max-h-44 overflow-auto rounded border border-violet-200 bg-white">
                    {chargeForms && <p className="px-2 py-1 text-xs text-slate-500"><Jauge /> Patientez…</p>}
                    {!chargeForms && formulaires.length === 0 && <p className="px-2 py-1 text-xs text-slate-500">Aucun formulaire disponible.</p>}
                    {formulaires.map((x) => (
                      <button type="button" key={x.id} disabled={!x.nb_vocaux} className="block w-full px-2 py-1 text-left text-sm hover:bg-violet-50 disabled:opacity-50"
                        onClick={() => maj("formulaire", { id: x.id, titre: x.titre })} title={!x.nb_vocaux ? "Aucun champ ne peut être demandé au téléphone" : ""}>
                        📋 {x.titre}{x.number ? ` (n° ${x.number})` : ""}
                        <span className="text-[11px] text-slate-500"> · {x.nb_champs} champ(s){x.nb_a_completer ? `, dont ${x.nb_a_completer} à compléter par écrit` : ""}{x.is_public ? " · public" : ""}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
              {apercu && (
                <details className="rounded border border-violet-200 bg-white p-2 text-xs">
                  <summary className="cursor-pointer font-semibold text-violet-900">Questions que Liluvine posera ({(apercu.champs || []).length})</summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {(apercu.champs || []).map((c) => <li key={c.id}>{c.question}{c.required ? " (obligatoire)" : ""}</li>)}
                  </ul>
                  {(apercu.a_completer || []).length > 0 && (
                    <p className="mt-1 text-amber-800">À compléter par écrit (non demandés au téléphone) : {apercu.a_completer.map((c) => `${c.label} (${c.raison})`).join(", ")}</p>
                  )}
                  {!apercu.lien && <p className="mt-1 text-slate-500">Formulaire non public : aucun lien ne pourra être envoyé par WhatsApp.</p>}
                </details>
              )}
              <label className="block text-xs font-semibold">Envoyer le lien du formulaire par WhatsApp à la fin
                <select value={f.lien_formulaire || "auto"} onChange={(e) => maj("lien_formulaire", e.target.value)} className={champ}>
                  <option value="auto">Automatique : s'il reste des champs à compléter ou si le formulaire est incomplet</option>
                  <option value="toujours">Toujours</option>
                  <option value="jamais">Jamais</option>
                </select>
              </label>
            </div>
          )}
        </div>

        {/* Informations à recueillir (mode prompt seulement) */}
        {f.mode !== "formulaire" && (
        <div className="rounded-lg bg-slate-50 p-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-slate-700">Informations à recueillir (Liluvine pose les questions une par une)</p>
            <button type="button" onClick={ajouterQuestion} className="rounded border border-violet-300 px-2 py-0.5 text-xs text-violet-800 hover:bg-violet-50">＋ Question</button>
          </div>
          {(f.questions || []).map((q, i) => (
            <div key={i} className="mt-1 grid gap-1 sm:grid-cols-[1fr_130px_1fr_auto]">
              <input value={q.libelle} onChange={(e) => majQuestion(i, "libelle", e.target.value)} placeholder="Question ou information" className="rounded border border-slate-300 px-2 py-1 text-sm" />
              <select value={q.type} onChange={(e) => majQuestion(i, "type", e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm">
                {Object.entries(LIBELLES_QUESTION).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
              {q.type === "choix" ? (
                <input value={(q.choix || []).join(", ")} onChange={(e) => majQuestion(i, "choix", e.target.value.split(",").map((x) => x.trim()).filter(Boolean))}
                  placeholder="Choix séparés par des virgules" className="rounded border border-slate-300 px-2 py-1 text-sm" />
              ) : <span />}
              <button type="button" onClick={() => maj("questions", f.questions.filter((_, j) => j !== i))} className="rounded px-2 text-rose-600 hover:bg-rose-50">✕</button>
            </div>
          ))}
        </div>
        )}

        <label className="block text-xs font-semibold">Texte à lire (facultatif — variables {"{prenom}"} {"{nom}"} {"{entreprise}"})
          <textarea rows={2} value={f.texte_a_lire} onChange={(e) => maj("texte_a_lire", e.target.value)} className={champ} />
        </label>
        <label className="block text-xs font-semibold">Données de contexte (facultatif)
          <textarea rows={2} value={f.contexte} onChange={(e) => maj("contexte", e.target.value)} placeholder="Historique, dernière commande, remarques…" className={champ} />
        </label>

        {/* Compte rendu de maintenance : choix de la fiche (son résumé est donné à Liluvine) */}
        {f.type === "compte_rendu_maintenance" && (
          <div className="rounded-lg bg-amber-50 p-2">
            <p className="text-xs font-semibold text-amber-900">Fiche de maintenance ou intervention à présenter</p>
            {f.maintenance?.id && <p className="text-sm">✅ {f.maintenance.libelle || f.maintenance.resume || f.maintenance.id}
              <button type="button" onClick={() => maj("maintenance", null)} className="ml-2 text-xs text-rose-700">retirer</button></p>}
            <input value={rechercheMnt} onChange={(e) => setRechercheMnt(e.target.value)} placeholder="N° de fiche, matériel, client…" className={champ} />
            <div className="mt-1 max-h-36 overflow-auto rounded border border-amber-200 bg-white">
              {maintenances.map((m) => (
                <button type="button" key={`${m.source}-${m.id}`} className="block w-full px-2 py-1 text-left text-sm hover:bg-amber-50"
                  onClick={() => { maj("maintenance", { source: m.source, id: m.id, libelle: m.libelle }); if (!f.contact.telephone && m.telephone) maj("contact", { ...f.contact, nom: m.client_nom || f.contact.nom, telephone: m.telephone }); }}>
                  {m.source === "maintenance" ? "🛠️" : "🔧"} {m.libelle} <span className="text-[11px] text-slate-500">{m.date || ""}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-4">
          <label className="block text-xs font-semibold">Ligne WhatsApp appelante
            <select value={f.ligne_cle || ""} onChange={(e) => maj("ligne_cle", e.target.value)} className={champ}>
              <option value="">Ligne des réglages</option>
              {(donnees?.lignes || []).map((l) => <option key={l.cle} value={l.cle}>{l.libelle}</option>)}
            </select>
          </label>
          <label className="block text-xs font-semibold">Récurrence
            <select value={f.recurrence} onChange={(e) => maj("recurrence", e.target.value)} className={champ}>
              {["aucune", "quotidienne", "hebdomadaire", "mensuelle", "annuelle"].map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="block text-xs font-semibold">Tentatives au plus
            <input type="number" min="1" max="10" value={f.tentatives_max} onChange={(e) => maj("tentatives_max", e.target.value)} className={champ} />
          </label>
          <label className="block text-xs font-semibold">Intervalle (minutes)
            <input type="number" min="5" max="1440" value={f.intervalle_min} onChange={(e) => maj("intervalle_min", e.target.value)} className={champ} />
          </label>
          <label className="block text-xs font-semibold">Plage autorisée : de
            <input type="time" value={f.plage_debut || ""} onChange={(e) => maj("plage_debut", e.target.value)} className={champ} />
          </label>
          <label className="block text-xs font-semibold">à
            <input type="time" value={f.plage_fin || ""} onChange={(e) => maj("plage_fin", e.target.value)} className={champ} />
          </label>
          <label className="col-span-2 mt-5 inline-flex items-center gap-2 text-xs">
            <input type="checkbox" checked={!!f.creer_relance} onChange={(e) => maj("creer_relance", e.target.checked)} />
            Créer automatiquement l'évènement de relance suggéré par Liluvine
          </label>
        </div>
        <p className="text-[11px] text-slate-500">
          Meta exige que le contact ait autorisé les appels de votre numéro : sinon Liluvine lui envoie d'abord une demande
          d'autorisation (une seule), et l'appel part dès qu'il accepte.
        </p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={fermer} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Fermer</button>
          <button type="submit" disabled={enCours} className="rounded-lg bg-violet-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-violet-800 disabled:opacity-50">
            {enCours ? <Jauge /> : null} Enregistrer
          </button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Réglages de l'agenda et des anniversaires
// ---------------------------------------------------------------------------
// Lot 71.3 — aussi intégré tel quel dans Paramètres (integre = sans fenêtre ni bouton de fermeture ;
// les lignes WhatsApp sont alors lues ici, puisque la page de l'agenda n'est pas ouverte).
export function ReglagesAgenda({ lignes: lignesRecues, fermer, integre = false }) {
  const [f, setF] = useState(null);
  const [lignesLues, setLignesLues] = useState([]);
  const lignes = lignesRecues?.length ? lignesRecues : lignesLues;
  // Mode intégré : liste des lignes WhatsApp (Standard, VIP…) pour les listes déroulantes
  useEffect(() => {
    if (!integre) return;
    apiClient.get("/admin/liluvine-agenda").then((r) => setLignesLues(r.data?.lignes || [])).catch(() => setLignesLues([]));
  }, [integre]);
  const [apercu, setApercu] = useState("");
  const [occupe, setOccupe] = useState(false);
  const maj = (cle, valeur) => setF((x) => ({ ...x, [cle]: valeur }));
  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";

  // Lecture des réglages effectifs
  useEffect(() => {
    apiClient.get("/admin/liluvine-agenda/reglages").then((r) => {
      const e = r.data.effectif || {};
      setF({
        liluvine_agenda_actif: e.actif, liluvine_agenda_ligne: e.ligne, liluvine_agenda_plage_debut: e.plage_debut,
        liluvine_agenda_plage_fin: e.plage_fin, liluvine_agenda_jours: e.jours || [], liluvine_agenda_tentatives_max: e.tentatives_max,
        liluvine_agenda_intervalle_min: e.intervalle_min, liluvine_agenda_sonnerie_s: e.sonnerie_s,
        liluvine_agenda_attente_autorisation_h: e.attente_autorisation_h, liluvine_agenda_repli_message: e.repli_message,
        liluvine_agenda_repli_modele: e.repli_modele, liluvine_agenda_repli_modele_langue: e.repli_modele_langue,
        liluvine_agenda_relance_auto: e.relance_auto, liluvine_agenda_duree_max_min: e.duree_max_min,
        liluvine_agenda_silence_s: e.silence_s, liluvine_agenda_anniv_actif: e.anniv_actif, liluvine_agenda_anniv_heure: e.anniv_heure,
        liluvine_agenda_anniv_texte: e.anniv_texte, liluvine_agenda_anniv_ia: e.anniv_ia, liluvine_agenda_anniv_ligne: e.anniv_ligne,
        liluvine_agenda_anniv_repli: e.anniv_repli, liluvine_agenda_anniv_repetitions: e.anniv_repetitions,
      });
    }).catch(() => toast.error("Réglages indisponibles"));
  }, []);

  // Enregistrement, puis génération immédiate des anniversaires
  const enregistrer = async () => {
    setOccupe(true);
    const t = toast.loading("Patientez…");
    try {
      await apiClient.put("/admin/liluvine-agenda/reglages", { ...f, liluvine_agenda_jours: (f.liluvine_agenda_jours || []).join(",") });
      const g = await apiClient.post("/admin/liluvine-agenda/anniversaires/generer");
      toast.success(`Réglages enregistrés — anniversaires : ${g.data.crees} créé(s), ${g.data.mis_a_jour} mis à jour`, { id: t });
      if (!integre && fermer) fermer();   // en mode intégré (Paramètres), la rubrique reste ouverte
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible", { id: t });
    } finally {
      setOccupe(false);
    }
  };
  // Aperçu du texte d'anniversaire (personne fictive)
  const voirApercu = async () => {
    try { const r = await apiClient.post("/admin/liluvine-agenda/apercu-anniversaire", { texte: f.liluvine_agenda_anniv_texte }); setApercu(r.data.texte); } catch { setApercu(""); }
  };

  return (
    // Fenêtre par-dessus l'agenda, ou simple bloc dans la rubrique des Paramètres (integre)
    <div className={integre ? "" : "fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4"}>
      <div className={integre ? "space-y-3" : "w-full max-w-3xl space-y-3 rounded-2xl bg-white p-4 shadow-xl"} data-testid="reglages-agenda">
        {!integre && (
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold">⚙️ Réglages de l'agenda et des anniversaires</h2>
            <button type="button" onClick={fermer} className="rounded px-2 text-xl text-slate-400 hover:bg-slate-100">×</button>
          </div>
        )}
        {!f ? <p className="text-sm"><Jauge /> Patientez…</p> : (
          <>
            <label className="inline-flex items-center gap-2 text-sm font-semibold">
              <input type="checkbox" checked={!!f.liluvine_agenda_actif} onChange={(e) => maj("liluvine_agenda_actif", e.target.checked)} />
              Liluvine passe les appels de l'agenda
            </label>
            <div className="grid gap-3 text-xs sm:grid-cols-3">
              <label className="block font-semibold">Ligne appelante par défaut
                <select value={f.liluvine_agenda_ligne || "principal"} onChange={(e) => maj("liluvine_agenda_ligne", e.target.value)} className={champ}>
                  {lignes.map((l) => <option key={l.cle} value={l.cle}>{l.libelle}</option>)}
                </select>
              </label>
              <label className="block font-semibold">Appels autorisés de
                <input type="time" value={f.liluvine_agenda_plage_debut} onChange={(e) => maj("liluvine_agenda_plage_debut", e.target.value)} className={champ} />
              </label>
              <label className="block font-semibold">à
                <input type="time" value={f.liluvine_agenda_plage_fin} onChange={(e) => maj("liluvine_agenda_plage_fin", e.target.value)} className={champ} />
              </label>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              {JOURS_SEMAINE.map((j, i) => (
                <label key={j} className="inline-flex items-center gap-1">
                  <input type="checkbox" checked={(f.liluvine_agenda_jours || []).includes(i + 1)}
                    onChange={() => maj("liluvine_agenda_jours", (f.liluvine_agenda_jours || []).includes(i + 1) ? f.liluvine_agenda_jours.filter((x) => x !== i + 1) : [...(f.liluvine_agenda_jours || []), i + 1])} />
                  {j}
                </label>
              ))}
            </div>
            <div className="grid gap-3 text-xs sm:grid-cols-3">
              {[["liluvine_agenda_tentatives_max", "Tentatives au plus", 1, 10], ["liluvine_agenda_intervalle_min", "Intervalle entre tentatives (min)", 5, 1440],
                ["liluvine_agenda_sonnerie_s", "Sonnerie (s)", 10, 60], ["liluvine_agenda_attente_autorisation_h", "Attente de l'autorisation (h)", 1, 168],
                ["liluvine_agenda_duree_max_min", "Durée max. d'un appel (min)", 1, 30], ["liluvine_agenda_silence_s", "Raccrocher après … s de silence", 5, 120]]
                .map(([k, l, mi, ma]) => (
                  <label key={k} className="block font-semibold">{l}
                    <input type="number" min={mi} max={ma} value={f[k]} onChange={(e) => maj(k, e.target.value)} className={champ} />
                  </label>
                ))}
            </div>
            <label className="inline-flex items-center gap-2 text-xs">
              <input type="checkbox" checked={!!f.liluvine_agenda_repli_message} onChange={(e) => maj("liluvine_agenda_repli_message", e.target.checked)} />
              Message WhatsApp de repli si l'appel n'aboutit pas (contenu de l'appel, par écrit)
            </label>
            <div className="grid gap-3 text-xs sm:grid-cols-2">
              <label className="block font-semibold">Modèle Meta de repli (hors fenêtre de 24 h, 1 variable)
                <input value={f.liluvine_agenda_repli_modele || ""} onChange={(e) => maj("liluvine_agenda_repli_modele", e.target.value)} placeholder="nom_du_modele" className={champ} />
              </label>
              <label className="block font-semibold">Langue du modèle
                <input value={f.liluvine_agenda_repli_modele_langue || "fr"} onChange={(e) => maj("liluvine_agenda_repli_modele_langue", e.target.value)} className={champ} />
              </label>
            </div>
            <label className="inline-flex items-center gap-2 text-xs">
              <input type="checkbox" checked={!!f.liluvine_agenda_relance_auto} onChange={(e) => maj("liluvine_agenda_relance_auto", e.target.checked)} />
              Créer automatiquement l'évènement de relance suggéré par Liluvine (tous les évènements)
            </label>

            {/* Anniversaires des utilisateurs suivis */}
            <div className="space-y-2 rounded-xl bg-pink-50/70 p-3 ring-1 ring-pink-100">
              <p className="text-sm font-bold text-pink-900">🎂 Anniversaires des utilisateurs suivis</p>
              <label className="inline-flex items-center gap-2 text-xs">
                <input type="checkbox" checked={!!f.liluvine_agenda_anniv_actif} onChange={(e) => maj("liluvine_agenda_anniv_actif", e.target.checked)} />
                Liluvine appelle chaque utilisateur suivi le jour de son anniversaire (date de naissance renseignée sur sa fiche)
              </label>
              <div className="grid gap-3 text-xs sm:grid-cols-3">
                <label className="block font-semibold">Heure de l'appel
                  <input type="time" value={f.liluvine_agenda_anniv_heure} onChange={(e) => maj("liluvine_agenda_anniv_heure", e.target.value)} className={champ} />
                </label>
                <label className="block font-semibold">Ligne utilisée
                  <select value={f.liluvine_agenda_anniv_ligne || ""} onChange={(e) => maj("liluvine_agenda_anniv_ligne", e.target.value)} className={champ}>
                    <option value="">Ligne par défaut de l'agenda</option>
                    {lignes.map((l) => <option key={l.cle} value={l.cle}>{l.libelle}</option>)}
                  </select>
                </label>
                <label className="block font-semibold">Lire le message
                  <select value={f.liluvine_agenda_anniv_repetitions} onChange={(e) => maj("liluvine_agenda_anniv_repetitions", e.target.value)} className={champ}>
                    <option value={1}>une fois</option><option value={2}>deux fois</option><option value={3}>trois fois</option>
                  </select>
                </label>
              </div>
              <label className="block text-xs font-semibold">Texte lu par Liluvine (variables {"{prenom}"} {"{nom}"} {"{age}"} {"{entreprise}"})
                <textarea rows={4} value={f.liluvine_agenda_anniv_texte} onChange={(e) => maj("liluvine_agenda_anniv_texte", e.target.value)} className={champ} />
              </label>
              <button type="button" onClick={voirApercu} className="rounded border border-pink-300 bg-white px-2 py-0.5 text-xs text-pink-800">👁️ Aperçu</button>
              {apercu && <p className="rounded bg-white px-2 py-1 text-xs italic text-slate-700">{apercu}</p>}
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={!!f.liluvine_agenda_anniv_ia} onChange={(e) => maj("liluvine_agenda_anniv_ia", e.target.checked)} />
                Personnaliser avec l'IA (réécriture légère du texte pour chaque personne)
              </label>
              <label className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={!!f.liluvine_agenda_anniv_repli} onChange={(e) => maj("liluvine_agenda_anniv_repli", e.target.checked)} />
                Envoyer le message par WhatsApp si l'appel n'aboutit pas
              </label>
              <p className="text-[11px] text-slate-500">Personnes nées un 29 février : appel le 28 février les années non bissextiles.</p>
            </div>
            <div className="flex justify-end gap-2">
              {!integre && <button type="button" onClick={fermer} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Fermer</button>}
              <button type="button" onClick={enregistrer} disabled={occupe} className="rounded-lg bg-violet-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-violet-800 disabled:opacity-50">
                {occupe ? <Jauge /> : null} Enregistrer
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
