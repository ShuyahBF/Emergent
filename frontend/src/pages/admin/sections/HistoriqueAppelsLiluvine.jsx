// HistoriqueAppelsLiluvine.jsx — Lot 67.1 : historique des appels automatiques émis par Liluvine.
//
// Chaque message d'un client déclenche (lot 67) un relais WhatsApp puis un appel vocal au propriétaire.
// Cette section suit ces appels :
//   1. Carte de synthèse : période (Aujourd'hui / 7 jours / Ce mois / Cette année / personnalisée) avec
//      les cumuls (appels émis, décrochés, sans réponse / échecs, relais seuls, durée totale et moyenne,
//      coût total) et un petit tableau par jour / semaine / mois avec une ligne de totaux ;
//   2. Tableau de l'historique : Date/Heure, Client (qui a écrit), Destinataire, Ligne, Durée
//      (sonnerie + conversation), Résultat, Relais (écrit / modèle), Coût — filtres, pagination,
//      export CSV et actualisation automatique toutes les 60 secondes.
// Le coût de chaque appel est calculé et FIGÉ au moment de l'appel (tarif des réglages avancés).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const BASE = "/admin/appel-proprietaire";

// Libellés et couleurs des résultats (badges)
const RESULTATS = {
  decroche: ["Décroché", "bg-emerald-100 text-emerald-800"],
  sans_reponse: ["Sans réponse", "bg-amber-100 text-amber-800"],
  echec: ["Échec", "bg-rose-100 text-rose-800"],
  relais_seul: ["Relais seul", "bg-slate-100 text-slate-700"],
};

// Périodes de la carte de synthèse
const PERIODES = [
  ["jour", "Aujourd'hui"],
  ["7j", "7 jours"],
  ["mois", "Ce mois"],
  ["annee", "Cette année"],
  ["perso", "Personnalisée"],
];

// Petite jauge circulaire transparente (attente)
const Jauge = () => (
  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-violet-300 border-t-transparent align-middle" />
);

// Date du jour « AAAA-MM-JJ » en UTC (= heure de Ouagadougou), décalée de n jours
const jourUtc = (decalage = 0) => {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + decalage);
  return d.toISOString().slice(0, 10);
};

// Bornes (du, au) d'une période prédéfinie
const bornes = (periode) => {
  const aujourdhui = jourUtc(0);
  if (periode === "jour") return [aujourdhui, aujourdhui];
  if (periode === "7j") return [jourUtc(-6), aujourdhui];
  if (periode === "mois") return [`${aujourdhui.slice(0, 7)}-01`, aujourdhui];
  if (periode === "annee") return [`${aujourdhui.slice(0, 4)}-01-01`, aujourdhui];
  return [null, null];
};

// Durée en secondes → « hh:mm:ss »
export const hms = (secondes) => {
  const s = Math.max(0, Math.round(Number(secondes) || 0));
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
};

// Montant « 1 234,5 FCFA » (2 décimales au plus)
const montant = (valeur, devise) => {
  if (valeur === null || valeur === undefined) return "—";
  const n = Number(valeur).toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  return `${n} ${devise || ""}`.trim();
};

// Coût total d'un cumul (une seule devise, sinon détail par devise)
const coutTotal = (t) => {
  if (!t) return "—";
  if (t.cout_total !== null && t.cout_total !== undefined) return montant(t.cout_total, t.devise);
  return Object.entries(t.couts || {}).map(([d, v]) => montant(v, d)).join(" + ");
};

// Date/heure « JJ/MM/AAAA HH:MM:SS » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou" }) : "");

// Petite tuile de cumul de la carte de synthèse
const Tuile = ({ titre, valeur, detail }) => (
  <div className="rounded-lg bg-white/80 p-2 ring-1 ring-slate-200">
    <p className="text-[11px] text-slate-500">{titre}</p>
    <p className="text-lg font-semibold text-slate-800">{valeur}</p>
    {detail && <p className="text-[11px] text-slate-500">{detail}</p>}
  </div>
);

export default function HistoriqueAppelsLiluvine() {
  // --- Carte de synthèse ---
  const [periode, setPeriode] = useState("mois");          // période choisie
  const [perso, setPerso] = useState({ du: jourUtc(-30), au: jourUtc(0) });   // période personnalisée
  const [decoupage, setDecoupage] = useState("jour");     // détail par jour / semaine / mois
  const [synthese, setSynthese] = useState(null);
  // --- Tableau de l'historique ---
  // Filtres du tableau : au départ, les dates de la période « Ce mois »
  const [filtres, setFiltres] = useState(() => {
    const [d, a] = bornes("mois");
    return { du: d, au: a, client: "", resultat: "" };
  });
  const [page, setPage] = useState(1);
  const [historique, setHistorique] = useState(null);
  const [selection, setSelection] = useState(null);       // ligne sélectionnée (surlignée en orange)
  const [occupe, setOccupe] = useState(false);

  // Bornes effectives de la carte de synthèse
  const [du, au] = periode === "perso" ? [perso.du, perso.au] : bornes(periode);

  // Lecture de la synthèse (cumuls + détail par période)
  const chargerSynthese = useCallback(async () => {
    const r = await apiClient.get(`${BASE}/synthese`, { params: { periode: decoupage, du, au } });
    setSynthese(r.data);
  }, [decoupage, du, au]);

  // Lecture d'une page de l'historique filtré
  const chargerHistorique = useCallback(async () => {
    const params = { page, par_page: 25 };
    Object.entries(filtres).forEach(([k, v]) => { if (v) params[k] = v; });
    const r = await apiClient.get(`${BASE}/historique`, { params });
    setHistorique(r.data);
  }, [filtres, page]);

  // Actualisation complète ; avec « Patientez… » quand elle est demandée par l'utilisateur
  const actualiser = useCallback(async (visible = false) => {
    const t = visible ? toast.loading("Patientez…") : null;
    if (visible) setOccupe(true);
    try {
      await Promise.all([chargerSynthese(), chargerHistorique()]);
      if (t) toast.dismiss(t);
    } catch (err) {
      if (t) toast.error(err?.response?.data?.detail || "Historique indisponible", { id: t });
    } finally {
      if (visible) setOccupe(false);
    }
  }, [chargerSynthese, chargerHistorique]);

  // Chargement au changement de période / filtre, puis actualisation automatique toutes les 60 s
  useEffect(() => {
    actualiser(false);
    const minuterie = setInterval(() => actualiser(false), 60000);
    return () => clearInterval(minuterie);
  }, [actualiser]);

  // Le choix d'une période recopie ses dates dans les filtres du tableau
  const choisirPeriode = (p) => {
    setPeriode(p);
    const [d, a] = p === "perso" ? [perso.du, perso.au] : bornes(p);
    setFiltres((f) => ({ ...f, du: d || "", au: a || "" }));
    setPage(1);
  };
  const filtrer = (cle, valeur) => { setFiltres((f) => ({ ...f, [cle]: valeur })); setPage(1); };

  // Export CSV du filtre courant (téléchargé avec le jeton de connexion)
  const exporter = async () => {
    const t = toast.loading("Patientez…");
    try {
      const params = {};
      Object.entries(filtres).forEach(([k, v]) => { if (v) params[k] = v; });
      const r = await apiClient.get(`${BASE}/historique.csv`, { params, responseType: "blob" });
      const lien = document.createElement("a");
      lien.href = URL.createObjectURL(r.data);
      lien.download = `historique_appels_liluvine_${jourUtc(0)}.csv`;
      lien.click();
      setTimeout(() => URL.revokeObjectURL(lien.href), 5000);
      toast.success("Export CSV téléchargé", { id: t });
    } catch {
      toast.error("Export impossible", { id: t });
    }
  };

  const tot = synthese?.totaux;
  const champ = "rounded border border-slate-300 px-1.5 py-1 text-xs";

  return (
    <div className="space-y-4" data-testid="historique-appels-liluvine">
      {/* 1. Carte de synthèse : cumuls de la période */}
      <div className="rounded-xl bg-violet-50/60 p-3 ring-1 ring-violet-200">
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-2 text-sm font-semibold text-violet-900">Synthèse des appels de Liluvine</p>
          {PERIODES.map(([cle, libelle]) => (
            <button key={cle} type="button" onClick={() => choisirPeriode(cle)}
              className={`rounded-full px-2.5 py-0.5 text-xs ${periode === cle ? "bg-violet-700 text-white" : "bg-white text-violet-800 ring-1 ring-violet-200 hover:bg-violet-100"}`}>
              {libelle}
            </button>
          ))}
          {periode === "perso" && (
            <span className="flex items-center gap-1 text-xs">
              du <input type="date" value={perso.du} className={champ}
                onChange={(e) => { setPerso((p) => ({ ...p, du: e.target.value })); filtrer("du", e.target.value); }} />
              au <input type="date" value={perso.au} className={champ}
                onChange={(e) => { setPerso((p) => ({ ...p, au: e.target.value })); filtrer("au", e.target.value); }} />
            </span>
          )}
          <button type="button" onClick={() => actualiser(true)} disabled={occupe}
            className="ml-auto rounded-lg border border-slate-300 bg-white px-2 py-0.5 text-xs hover:bg-slate-50 disabled:opacity-50">
            {occupe ? <Jauge /> : "🔄"} Actualiser
          </button>
        </div>

        {!tot ? (
          <p className="mt-2 text-xs text-slate-500"><Jauge /> Patientez…</p>
        ) : (
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            <Tuile titre="Appels émis" valeur={tot.appels} />
            <Tuile titre="Décrochés" valeur={tot.decroches} />
            <Tuile titre="Sans réponse / échecs" valeur={`${tot.sans_reponse} / ${tot.echecs}`} />
            <Tuile titre="Relais seuls" valeur={tot.relais_seuls} detail="heures calmes, autorisation…" />
            <Tuile titre="Durée totale" valeur={hms(tot.duree_totale_s)} />
            <Tuile titre="Durée moyenne" valeur={hms(tot.duree_moyenne_s)} detail="par appel décroché" />
            <Tuile titre="Coût total" valeur={coutTotal(tot)} />
          </div>
        )}

        {/* Détail par jour / semaine / mois, avec ligne de totaux */}
        <div className="mt-3 flex items-center gap-2 text-xs">
          <span className="font-semibold text-slate-700">Détail par</span>
          <select value={decoupage} onChange={(e) => setDecoupage(e.target.value)} className={champ}>
            <option value="jour">jour</option>
            <option value="semaine">semaine</option>
            <option value="mois">mois</option>
          </select>
        </div>
        {synthese && (
          <div className="mt-2 max-h-64 overflow-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="px-2 py-1 text-left">Période</th>
                  <th className="px-2 py-1 text-right">Appels</th>
                  <th className="px-2 py-1 text-right">Décrochés</th>
                  <th className="px-2 py-1 text-right">Sans réponse</th>
                  <th className="px-2 py-1 text-right">Échecs</th>
                  <th className="px-2 py-1 text-right">Relais seuls</th>
                  <th className="px-2 py-1 text-right">Durée totale</th>
                  <th className="px-2 py-1 text-right">Durée moyenne</th>
                  <th className="px-2 py-1 text-right">Coût</th>
                </tr>
              </thead>
              <tbody>
                {synthese.lignes.length === 0 && (
                  <tr><td colSpan={9} className="px-2 py-2 text-center text-slate-500">Aucun appel sur la période.</td></tr>
                )}
                {synthese.lignes.map((li) => (
                  <tr key={li.cle} className="border-t border-slate-100">
                    <td className="whitespace-nowrap px-2 py-1">{li.libelle}</td>
                    <td className="px-2 py-1 text-right">{li.appels}</td>
                    <td className="px-2 py-1 text-right">{li.decroches}</td>
                    <td className="px-2 py-1 text-right">{li.sans_reponse}</td>
                    <td className="px-2 py-1 text-right">{li.echecs}</td>
                    <td className="px-2 py-1 text-right">{li.relais_seuls}</td>
                    <td className="px-2 py-1 text-right">{hms(li.duree_totale_s)}</td>
                    <td className="px-2 py-1 text-right">{hms(li.duree_moyenne_s)}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-right">{coutTotal(li)}</td>
                  </tr>
                ))}
              </tbody>
              {synthese.lignes.length > 0 && (
                <tfoot className="border-t-2 border-slate-300 font-semibold">
                  <tr>
                    <td className="px-2 py-1">Total</td>
                    <td className="px-2 py-1 text-right">{tot.appels}</td>
                    <td className="px-2 py-1 text-right">{tot.decroches}</td>
                    <td className="px-2 py-1 text-right">{tot.sans_reponse}</td>
                    <td className="px-2 py-1 text-right">{tot.echecs}</td>
                    <td className="px-2 py-1 text-right">{tot.relais_seuls}</td>
                    <td className="px-2 py-1 text-right">{hms(tot.duree_totale_s)}</td>
                    <td className="px-2 py-1 text-right">{hms(tot.duree_moyenne_s)}</td>
                    <td className="whitespace-nowrap px-2 py-1 text-right">{coutTotal(tot)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </div>

      {/* 2. Historique détaillé : filtres, tableau, pagination, export */}
      <div className="flex flex-wrap items-end gap-2 text-xs">
        <label>Du<br /><input type="date" value={filtres.du} onChange={(e) => filtrer("du", e.target.value)} className={champ} /></label>
        <label>Au<br /><input type="date" value={filtres.au} onChange={(e) => filtrer("au", e.target.value)} className={champ} /></label>
        <label>Client (nom ou numéro)<br />
          <input value={filtres.client} onChange={(e) => filtrer("client", e.target.value)} placeholder="ex. Awa, 70 00…" className={champ} />
        </label>
        <label>Résultat<br />
          <select value={filtres.resultat} onChange={(e) => filtrer("resultat", e.target.value)} className={champ}>
            <option value="">Tous</option>
            {Object.entries(RESULTATS).map(([cle, [libelle]]) => <option key={cle} value={cle}>{libelle}</option>)}
          </select>
        </label>
        <button type="button" onClick={exporter}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1 hover:bg-slate-50">⬇️ Export CSV</button>
        <span className="ml-auto text-slate-500">Actualisation automatique toutes les 60 s</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="px-2 py-1 text-left">Date/Heure</th>
              <th className="px-2 py-1 text-left">Client (qui a écrit)</th>
              <th className="px-2 py-1 text-left">Destinataire</th>
              <th className="px-2 py-1 text-left">Ligne</th>
              <th className="px-2 py-1 text-left">Durée</th>
              <th className="px-2 py-1 text-left">Résultat</th>
              <th className="px-2 py-1 text-left">Relais</th>
              <th className="px-2 py-1 text-right">Coût</th>
            </tr>
          </thead>
          <tbody>
            {!historique && (
              <tr><td colSpan={8} className="px-2 py-2 text-slate-500"><Jauge /> Patientez…</td></tr>
            )}
            {historique && historique.items.length === 0 && (
              <tr><td colSpan={8} className="px-2 py-2 text-center text-slate-500">Aucun appel pour ces filtres.</td></tr>
            )}
            {(historique?.items || []).map((a) => {
              const [libelle, couleur] = RESULTATS[a.categorie] || [a.resultat, "bg-slate-100 text-slate-700"];
              return (
                <tr key={a.id} className={`cursor-pointer border-t border-slate-100 ${selection === a.id ? "ligne-selectionnee" : ""}`}
                  onClick={() => setSelection(a.id)}>
                  <td className="whitespace-nowrap px-2 py-1">
                    {dateHeure(a.created_at)}
                    {a.test && <span className="ml-1 rounded bg-sky-100 px-1 text-[10px] text-sky-800">essai</span>}
                  </td>
                  <td className="px-2 py-1">{a.client_nom || (a.client_telephone ? `+${a.client_telephone}` : "—")}</td>
                  <td className="whitespace-nowrap px-2 py-1">{a.destinataire ? `+${a.destinataire}` : "—"}</td>
                  <td className="whitespace-nowrap px-2 py-1">{a.ligne_libelle || a.ligne_cle || "—"}</td>
                  <td className="whitespace-nowrap px-2 py-1"
                    title={a.duree_source === "meta" ? "Durée de conversation fournie par Meta" : "Durée mesurée par le serveur"}>
                    🔔 {hms(a.sonnerie_s)} + 🗣️ {hms(a.conversation_s)}
                  </td>
                  <td className="px-2 py-1">
                    <span className={`rounded-full px-2 py-0.5 ${couleur}`} title={a.raison || ""}>{libelle}</span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1" title={a.relais_erreur || ""}>
                    {a.relais_envoye ? (a.relais_mode === "modele" ? `Modèle (${a.relais_modele || "?"})` : "Écrit") : "Non"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1 text-right"
                    title={`Appel ${montant(a.cout_appel, a.devise)} (${a.secondes_facturees || 0} s facturées) · relais ${montant(a.cout_relais, a.devise)} · voix ${montant(a.cout_tts, a.devise)}`}>
                    {montant(a.cout_total, a.devise)}
                  </td>
                </tr>
              );
            })}
          </tbody>
          {historique && historique.items.length > 0 && (
            <tfoot className="border-t-2 border-slate-300 font-semibold">
              <tr>
                <td className="px-2 py-1" colSpan={4}>Total du filtre ({historique.total} lignes)</td>
                <td className="whitespace-nowrap px-2 py-1">🗣️ {hms(historique.totaux?.duree_totale_s)}</td>
                <td className="px-2 py-1" colSpan={2}>{historique.totaux?.decroches} décroché(s) / {historique.totaux?.appels} appel(s)</td>
                <td className="whitespace-nowrap px-2 py-1 text-right">{coutTotal(historique.totaux)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* Pagination */}
      {historique && historique.pages > 1 && (
        <div className="flex items-center justify-center gap-2 text-xs">
          <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 disabled:opacity-40">◀ Précédente</button>
          <span>Page {historique.page} / {historique.pages}</span>
          <button type="button" disabled={page >= historique.pages} onClick={() => setPage((p) => p + 1)}
            className="rounded border border-slate-300 bg-white px-2 py-0.5 disabled:opacity-40">Suivante ▶</button>
        </div>
      )}
    </div>
  );
}
