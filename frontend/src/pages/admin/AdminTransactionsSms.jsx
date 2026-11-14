// AdminTransactionsSms.jsx — Lot 389 : option de menu « Transactions SMS » (administrateur, PAS dans les Paramètres).
// Les paiements lus dans les SMS d'un téléphone (application Concentration) sont vus ici avec les mêmes filtres que l'historique d'auRor :
// période, opérateur, sens, téléphone, plateforme associée, texte ; chiffres clés, opérateurs, histogramme jour / mois, classements, camembert, liste, export CSV.
// Toucher un opérateur, une barre ou un bénéficiaire filtre tout l'écran. On peut aussi ASSOCIER un numéro (ou un nom) à une plateforme (ALBARKA…) pour que
// celle-ci retrouve ses paiements sans les ressaisir. Voir backend/routes/transactions_sms.py.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { RefreshCw, RotateCcw, Download, Calendar, CalendarDays, Banknote, Hash, Link2, Plus, Trash2, Check, ChevronsDown } from "lucide-react";   // règle 15 : un pictogramme sur chaque action
import { apiClient } from "@/lib/api";

const fcfa = (v) => `${Number(v || 0).toLocaleString("fr-FR")} FCFA`;
const dateHeure = (ms) => new Date(ms).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short", timeZone: "UTC" });
const PERIODES = [["tout", "Toute la période"], ["aujourdhui", "Aujourd'hui"], ["7j", "7 derniers jours"], ["30j", "30 derniers jours"], ["mois", "Ce mois-ci"], ["mois-1", "Mois dernier"], ["an", "12 derniers mois"], ["perso", "Dates personnalisées…"]];
const COULEURS = ["#0E6BA8", "#F6A35B", "#2E9E6B", "#D64545", "#7C5CC4", "#0FA3B1", "#94A3B8"];
const PAS_DE_FILTRE = { periode: "tout", du: "", au: "", operateur: "", genre: "", source: "", plateforme: "", q: "" };
const TAILLE = 50;

const iso = (d) => d.toISOString().slice(0, 10);
const decale = (n) => { const d = new Date(); d.setUTCDate(d.getUTCDate() + n); return d; };

/** Dates « du » / « au » (incluses) de la période choisie (heure UTC = heure du Burkina). */
function bornes(f) {
  const auj = new Date();
  switch (f.periode) {
    case "aujourdhui": return { du: iso(auj), au: iso(auj) };
    case "7j": return { du: iso(decale(-6)), au: iso(auj) };
    case "30j": return { du: iso(decale(-29)), au: iso(auj) };
    case "mois": return { du: `${iso(auj).slice(0, 8)}01`, au: iso(auj) };
    case "mois-1": { const fin = new Date(Date.UTC(auj.getUTCFullYear(), auj.getUTCMonth(), 0)); return { du: `${iso(fin).slice(0, 8)}01`, au: iso(fin) }; }
    case "an": { const d = new Date(); d.setUTCFullYear(d.getUTCFullYear() - 1); return { du: iso(d), au: iso(auj) }; }
    case "perso": return { du: f.du, au: f.au };
    default: return { du: "", au: "" };
  }
}

function Chiffre({ titre, valeur, couleur }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{titre}</div>
      <div className="mt-1 text-lg font-bold tabular-nums" style={couleur ? { color: couleur } : undefined}>{valeur}</div>
    </div>
  );
}

/** Histogramme cliquable : une barre rouge (dépenses) et une verte (recettes) par jour / mois, ou une barre bleue du nombre. */
function Histogramme({ barres, enNombre, choisie, surChoix }) {
  if (!barres.length) return null;
  const max = Math.max(1, ...barres.map((b) => (enNombre ? b.nombre : Math.max(b.depenses, b.recettes))));
  return (
    <div className="flex h-40 items-end gap-0.5 overflow-x-auto rounded-lg bg-slate-50 p-2" role="img" aria-label="Histogramme des paiements">
      {barres.map((b) => (
        <button key={b.cle} type="button" title={`${b.cle} · dépenses ${fcfa(b.depenses)} · recettes ${fcfa(b.recettes)} · ${b.nombre} paiement(s)`}
          onClick={() => surChoix(b.cle)} className={`flex h-full min-w-[10px] flex-1 items-end justify-center gap-px rounded ${choisie === b.cle ? "bg-orange-200" : "hover:bg-sky-100"}`}>
          {enNombre ? <span className="w-full rounded-t bg-sky-700" style={{ height: `${(100 * b.nombre) / max}%` }} />
            : (<><span className="w-1/2 rounded-t bg-red-500" style={{ height: `${(100 * b.depenses) / max}%` }} /><span className="w-1/2 rounded-t bg-emerald-500" style={{ height: `${(100 * b.recettes) / max}%` }} /></>)}
        </button>
      ))}
    </div>
  );
}

/** Camembert (SVG) des parts de chaque bénéficiaire. */
function Camembert({ parts, total }) {
  if (!total) return null;
  let angle = -Math.PI / 2;
  const R = 50;
  const arcs = parts.map(([nom, v], i) => {
    const a2 = angle + (2 * Math.PI * v) / total;
    const g = a2 - angle > Math.PI ? 1 : 0;
    const d = `M60 60 L${60 + R * Math.cos(angle)} ${60 + R * Math.sin(angle)} A${R} ${R} 0 ${g} 1 ${60 + R * Math.cos(a2 - 0.0001)} ${60 + R * Math.sin(a2 - 0.0001)} Z`;
    angle = a2;
    return <path key={nom} d={d} fill={COULEURS[i % COULEURS.length]} />;
  });
  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 120 120" className="h-32 w-32" role="img" aria-label="Camembert des bénéficiaires">{arcs}</svg>
      <ul className="space-y-1 text-sm">
        {parts.map(([nom, v], i) => (<li key={nom}><span className="mr-2 inline-block h-3 w-3 rounded-full align-middle" style={{ background: COULEURS[i % COULEURS.length] }} />{nom} · {Math.round((100 * v) / total)} %</li>))}
      </ul>
    </div>
  );
}

export default function AdminTransactionsSms() {
  const [etat, setEtat] = useState(null);
  const [filtres, setFiltres] = useState(PAS_DE_FILTRE);
  const [recherche, setRecherche] = useState("");
  const [parMois, setParMois] = useState(false);
  const [enNombre, setEnNombre] = useState(false);
  const [classement, setClassement] = useState("DEPENSE");
  const [donnees, setDonnees] = useState(null);
  const [nb, setNb] = useState(TAILLE);
  const [barre, setBarre] = useState(null);
  const [selection, setSelection] = useState(null);
  const [nomTel, setNomTel] = useState("");
  const [cleAffichee, setCleAffichee] = useState(null);       // { id, cle } montrée UNE SEULE FOIS
  const [lien, setLien] = useState({ cle: "", pays: "226", plateforme: "", client_id: "", libelle: "" });
  const [suggestions, setSuggestions] = useState([]);       // payeurs de numéro connu (client de SAWALI) pas encore associés

  const erreur = (e) => toast.error(e?.response?.data?.detail || "Action impossible");
  const chargerEtat = useCallback(() => {
    apiClient.get("/admin/transactions-sms/suggestions").then((r) => setSuggestions(r.data.suggestions)).catch(() => {});
    return apiClient.get("/admin/transactions-sms/etat").then((r) => setEtat(r.data)).catch(erreur);
  }, []);
  useEffect(() => { chargerEtat(); }, [chargerEtat]);

  // Recherche : relue 400 ms après la dernière frappe
  useEffect(() => { const t = setTimeout(() => setFiltres((f) => (f.q === recherche ? f : { ...f, q: recherche })), 400); return () => clearTimeout(t); }, [recherche]);

  const params = useMemo(() => {
    const { du, au } = bornes(filtres);
    return Object.fromEntries(Object.entries({ du, au, operateur: filtres.operateur, genre: filtres.genre, source: filtres.source, plateforme: filtres.plateforme, q: filtres.q.trim() }).filter(([, v]) => v));
  }, [filtres]);
  const charger = useCallback(async (limite) => {
    try { const { data } = await apiClient.get("/admin/transactions-sms", { params: { ...params, par_mois: parMois, classement, limite } }); setDonnees(data); } catch (e) { erreur(e); }
  }, [params, parMois, classement]);
  useEffect(() => { setNb(TAILLE); charger(TAILLE); }, [charger]);

  const modifier = (k, v) => setFiltres((f) => ({ ...f, [k]: v }));
  const stats = donnees?.stats;
  const t = stats?.totaux || {};
  const filtreActif = JSON.stringify(filtres) !== JSON.stringify(PAS_DE_FILTRE);
  const plusDe = () => { const n = nb + TAILLE; setNb(n); charger(n); };

  const creerTel = async () => { try { const { data } = await apiClient.post("/admin/transactions-sms/sources", { nom: nomTel }); setCleAffichee(data); setNomTel(""); chargerEtat(); } catch (e) { erreur(e); } };
  const retirerTel = async (s) => { if (window.confirm(`Retirer « ${s.nom} » ? Il ne pourra plus envoyer (les transactions reçues sont conservées).`)) { try { await apiClient.delete(`/admin/transactions-sms/sources/${s.id}`); chargerEtat(); } catch (e) { erreur(e); } } };
  const creerLien = async () => { try { await apiClient.post("/admin/transactions-sms/liens", lien); setLien({ cle: "", pays: lien.pays, plateforme: lien.plateforme, client_id: "", libelle: "" }); await chargerEtat(); charger(nb); toast.success("Association enregistrée"); } catch (e) { erreur(e); } };
  const associerSuggestion = async (x) => { try { await apiClient.post("/admin/transactions-sms/liens", { cle: x.numero, client_id: x.client_id }); await chargerEtat(); charger(nb); toast.success(`Numéro associé à ${x.client_nom}`); } catch (e) { erreur(e); } };
  const retirerLien = async (l) => { try { await apiClient.delete(`/admin/transactions-sms/liens/${l.id}`); await chargerEtat(); charger(nb); } catch (e) { erreur(e); } };
  const exporter = async () => {
    try {
      const { data } = await apiClient.get("/admin/transactions-sms/export.csv", { params, responseType: "blob" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(data); a.download = "transactions_sms.csv"; a.click(); URL.revokeObjectURL(a.href);
    } catch (e) { erreur(e); }
  };
  const choisirBarre = (cle) => {
    setBarre(cle);
    const [a, m, j] = cle.split("-");
    const fin = j ? cle : iso(new Date(Date.UTC(+a, +m, 0)));
    setFiltres((f) => ({ ...f, periode: "perso", du: j ? cle : `${cle}-01`, au: fin }));
  };

  if (!etat) return <div className="p-6 text-sm text-slate-500">Chargement…</div>;
  // Clients de SAWALI qui ont au moins un numéro associé (pour le filtre)
  const clientsAssocies = [...new Map(etat.liens.filter((l) => l.client_id).map((l) => [l.client_id, { id: l.client_id, nom: l.client_nom }])).values()];
  const select = "mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm";

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6" data-testid="transactions-sms">
      <div>
        <h1 className="font-display text-xl font-bold">Transactions SMS</h1>
        <p className="text-sm text-slate-600">Paiements lus dans les SMS d'un téléphone (application Concentration, onglet Paiements → « Envoyer à SAWALI »). Réservé à l'administrateur.</p>
      </div>

      {/* Filtres : mêmes critères que l'historique d'auRor + téléphone et plateforme associée */}
      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="filtres">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-sm">Période<select className={select} value={filtres.periode} onChange={(e) => modifier("periode", e.target.value)}>{PERIODES.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select></label>
          {filtres.periode === "perso" && (<>
            <label className="text-sm">Du<input type="date" className={select} value={filtres.du} max={filtres.au || undefined} onChange={(e) => modifier("du", e.target.value)} /></label>
            <label className="text-sm">Au<input type="date" className={select} value={filtres.au} min={filtres.du || undefined} onChange={(e) => modifier("au", e.target.value)} /></label>
          </>)}
          <label className="text-sm">Opérateur<select className={select} value={filtres.operateur} onChange={(e) => modifier("operateur", e.target.value)}><option value="">Tous les opérateurs</option>{etat.operateurs.map((o) => <option key={o}>{o}</option>)}</select></label>
          <label className="text-sm">Sens<select className={select} value={filtres.genre} onChange={(e) => modifier("genre", e.target.value)}><option value="">Dépenses et recettes</option><option value="DEPENSE">Dépenses</option><option value="RECETTE">Recettes</option></select></label>
          <label className="text-sm">Téléphone<select className={select} value={filtres.source} onChange={(e) => modifier("source", e.target.value)}><option value="">Tous les téléphones</option>{etat.sources.map((s) => <option key={s.id} value={s.id}>{s.nom}</option>)}</select></label>
          <label className="text-sm">Association<select className={select} value={filtres.plateforme} onChange={(e) => modifier("plateforme", e.target.value)}>
            <option value="">Toutes</option><option value="*lie">Associées à une plateforme</option><option value="*non_lie">Non associées</option>{etat.plateformes.map((p) => <option key={p.code} value={p.code}>{p.nom}</option>)}
            {clientsAssocies.map((c) => <option key={c.id} value={`client:${c.id}`}>Client : {c.nom}</option>)}</select></label>
          <label className="text-sm sm:col-span-2 lg:col-span-3">Bénéficiaire, numéro, transaction ou texte du SMS
            <input className={select} value={recherche} placeholder="Ex. : pharmacie, +226 70 11 22 33, MP261113" onChange={(e) => setRecherche(e.target.value)} /></label>
        </div>
        <div className="boutons-distincts flex flex-wrap gap-2">
          <button type="button" className="rounded border border-slate-300 px-3 py-1 text-sm" onClick={() => { chargerEtat(); charger(nb); }}><RefreshCw className="mr-1 inline h-4 w-4" />Actualiser</button>
          {filtreActif && <button type="button" className="rounded border border-slate-300 px-3 py-1 text-sm" onClick={() => { setFiltres(PAS_DE_FILTRE); setRecherche(""); setBarre(null); }}><RotateCcw className="mr-1 inline h-4 w-4" />Réinitialiser les filtres</button>}
          <button type="button" className="rounded border border-slate-300 px-3 py-1 text-sm" onClick={exporter}><Download className="mr-1 inline h-4 w-4" />Exporter en CSV</button>
        </div>
      </section>

      {!donnees ? <div className="text-sm text-slate-500">Chargement…</div> : donnees.total === 0 ? (
        <p className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">Aucune transaction pour ces critères. {etat.sources.length === 0 ? "Commencez par ajouter un téléphone source ci-dessous." : ""}</p>
      ) : (<>
        <section className="grid grid-cols-2 gap-3 md:grid-cols-3" data-testid="chiffres">
          <Chiffre titre="Transactions" valeur={`${t.nombre} (${t.nb_depenses} dép. · ${t.nb_recettes} rec.)`} />
          <Chiffre titre="Dépenses" valeur={fcfa(t.depenses)} couleur="#D64545" />
          <Chiffre titre="Recettes" valeur={fcfa(t.recettes)} couleur="#2E9E6B" />
          <Chiffre titre="Solde net" valeur={`${t.net >= 0 ? "+" : "−"} ${fcfa(Math.abs(t.net))}`} couleur={t.net >= 0 ? "#2E9E6B" : "#D64545"} />
          <Chiffre titre="Dépense moyenne" valeur={fcfa(t.depense_moyenne)} />
          <Chiffre titre="Plus grosse dépense" valeur={fcfa(t.plus_grosse)} />
        </section>

        <section className="space-y-2">
          <h2 className="text-lg font-bold">Par opérateur</h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {stats.par_operateur.map((o, i) => (
              <button key={o.operateur} type="button" onClick={() => modifier("operateur", filtres.operateur === o.operateur ? "" : o.operateur)}
                className={`rounded-xl border p-3 text-left ${filtres.operateur === o.operateur ? "border-orange-400 bg-orange-50" : "border-slate-200 bg-white hover:bg-sky-50"}`}>
                <div className="flex items-center gap-2 font-semibold"><span className="h-3 w-3 rounded-full" style={{ background: COULEURS[i % COULEURS.length] }} />{o.operateur}</div>
                <div className="text-2xl font-bold tabular-nums">{o.nombre} <span className="text-sm font-medium text-slate-500">transaction(s)</span></div>
                <div className="text-xs text-slate-600">Dépenses {fcfa(o.depenses)} · Recettes {fcfa(o.recettes)}</div>
              </button>
            ))}
          </div>
        </section>

        <section className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold">Activité</h2>
            <div className="boutons-distincts flex flex-wrap gap-2 text-sm">
              <button type="button" className={`rounded border px-2 py-1 ${!parMois ? "bg-slate-900 text-white" : ""}`} onClick={() => { setParMois(false); setBarre(null); }}><Calendar className="mr-1 inline h-4 w-4" />Par jour</button>
              <button type="button" className={`rounded border px-2 py-1 ${parMois ? "bg-slate-900 text-white" : ""}`} onClick={() => { setParMois(true); setBarre(null); }}><CalendarDays className="mr-1 inline h-4 w-4" />Par mois</button>
              <button type="button" className={`rounded border px-2 py-1 ${!enNombre ? "bg-slate-900 text-white" : ""}`} onClick={() => setEnNombre(false)}><Banknote className="mr-1 inline h-4 w-4" />Montant</button>
              <button type="button" className={`rounded border px-2 py-1 ${enNombre ? "bg-slate-900 text-white" : ""}`} onClick={() => setEnNombre(true)}><Hash className="mr-1 inline h-4 w-4" />Nombre</button>
            </div>
          </div>
          <Histogramme barres={stats.barres.slice(parMois ? -24 : -60)} enNombre={enNombre} choisie={barre} surChoix={choisirBarre} />
          <p className="text-xs text-slate-500"><span className="text-red-600">■</span> dépenses · <span className="text-emerald-600">■</span> recettes · touchez une barre pour filtrer sur ce {parMois ? "mois" : "jour"}.</p>
        </section>

        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-bold">Classements</h2>
            <select className="rounded border border-slate-300 px-2 py-1 text-sm" value={classement} onChange={(e) => setClassement(e.target.value)} aria-label="Sens du classement">
              <option value="DEPENSE">Dépenses (bénéficiaires)</option><option value="RECETTE">Recettes (expéditeurs)</option></select>
          </div>
          <Camembert parts={stats.parts} total={stats.total_classement} />
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <p className="px-4 pt-3 font-semibold">Top 10 des {classement === "DEPENSE" ? "bénéficiaires" : "expéditeurs"}</p>
              <table className="tableau w-full text-sm"><thead><tr className="text-left"><th className="p-2">#</th><th className="p-2">Nom</th><th className="p-2 text-right">Total</th></tr></thead>
                <tbody>{stats.top_tiers.map((x, i) => (
                  <tr key={x.nom} className="cursor-pointer border-t border-slate-100" onClick={() => setRecherche(x.nom)}>
                    <td className="p-2">{i + 1}</td><td className="p-2">{x.nom}<div className="text-xs text-slate-500">{x.nombre} paiement(s)</div></td><td className="p-2 text-right font-semibold tabular-nums">{fcfa(x.total)}</td></tr>))}</tbody></table>
            </div>
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <p className="px-4 pt-3 font-semibold">Top 10 des montants</p>
              <table className="tableau w-full text-sm"><thead><tr className="text-left"><th className="p-2">#</th><th className="p-2">Nom</th><th className="p-2 text-right">Montant</th></tr></thead>
                <tbody>{stats.top_montants.map((x, i) => (
                  <tr key={`${x.ms}-${i}`} className="border-t border-slate-100"><td className="p-2">{i + 1}</td><td className="p-2">{x.tiers || "—"}<div className="text-xs text-slate-500">{x.operateur} · {dateHeure(x.ms)}</div></td>
                    <td className="p-2 text-right font-semibold tabular-nums">{fcfa(x.montant)}</td></tr>))}</tbody></table>
            </div>
          </div>
        </section>

        <section className="space-y-2">
          <h2 className="text-lg font-bold">Transactions ({donnees.total})</h2>
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
            <table className="tableau w-full text-sm" data-testid="liste">
              <thead><tr className="text-left"><th className="p-2">Date</th><th className="p-2">Opérateur</th><th className="p-2">Bénéficiaire / expéditeur</th><th className="p-2">Numéro</th><th className="p-2">Association</th><th className="p-2 text-right">Montant</th></tr></thead>
              <tbody>{donnees.transactions.map((p, i) => (
                <tr key={`${p.ms}-${i}`} aria-selected={selection === `${p.ms}-${i}`} className="cursor-pointer border-t border-slate-100" onClick={() => setSelection(`${p.ms}-${i}`)}>
                  <td className="whitespace-nowrap p-2">{dateHeure(p.ms)}</td><td className="p-2">{p.operateur}</td>
                  <td className="p-2">{p.tiers || "—"}{p.reference && <div className="font-mono text-xs text-slate-500">{p.reference}</div>}</td>
                  <td className="p-2 font-mono text-xs">{p.numero ? (<>{p.numero_affiche || p.numero} <button type="button" className="underline" title="Associer ce numéro à une plateforme" onClick={(e) => { e.stopPropagation(); setLien((l) => ({ ...l, cle: p.numero_affiche || p.numero })); }}><Link2 className="mr-1 inline h-4 w-4" />Associer</button></>) : "—"}</td>
                  <td className="p-2">{p.associe ? <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs">{[p.client_nom, p.plateforme].filter(Boolean).join(" · ") || p.lien_libelle}</span> : "—"}</td>
                  <td className={`p-2 text-right font-semibold tabular-nums ${p.genre === "RECETTE" ? "text-emerald-700" : "text-red-700"}`}>{p.genre === "RECETTE" ? "+" : "−"} {fcfa(p.montant)}</td></tr>))}</tbody>
            </table>
          </div>
          {donnees.total > nb && <button type="button" className="w-full rounded border border-slate-300 py-2 text-sm" onClick={plusDe}><ChevronsDown className="mr-1 inline h-4 w-4" />Afficher plus ({donnees.total - nb} restantes)</button>}
        </section>
      </>)}

      {/* Associer un numéro (ou un nom) à une plateforme : celle-ci retrouve ses paiements sans les ressaisir */}
      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="liens">
        <h2 className="text-lg font-bold">Associer un numéro à un client ou à une plateforme</h2>
        <p className="text-sm text-slate-600">Le numéro (avec ou sans indicatif : choisissez le pays, ou écrivez « +indicatif » dans le champ) ou le nom du payeur est lié à un CLIENT de SAWALI (liste « Clients ») et / ou à une PLATEFORME (ALBARKA…). Une plateforme liée à un client (fiche de l'émetteur) retrouve les paiements des numéros de ce client sans les ressaisir (ex. Services Web d'ALBARKA) ; elle ne voit jamais le texte des SMS.</p>
        {suggestions.length > 0 && (
          <div className="space-y-2 rounded-lg border border-sky-300 bg-sky-50 p-3" data-testid="suggestions">
            <div className="text-sm font-semibold">Payeurs de numéro connu, pas encore associés</div>
            <table className="tableau w-full text-sm"><thead><tr className="text-left"><th className="p-2">Numéro</th><th className="p-2">Client de SAWALI</th><th className="p-2 text-right">Paiements</th><th className="p-2 text-right">Reçu (FCFA)</th><th className="p-2" /></tr></thead>
              <tbody>{suggestions.map((x) => (<tr key={x.numero + x.client_id} className="border-t border-sky-100"><td className="p-2 font-mono text-xs">{x.numero_affiche || x.numero}</td><td className="p-2">{x.client_nom}</td>
                <td className="p-2 text-right tabular-nums">{x.nombre}</td><td className="p-2 text-right tabular-nums">{Number(x.total).toLocaleString("fr-FR")}</td>
                <td className="p-2 text-right"><button type="button" className="underline" onClick={() => associerSuggestion(x)}><Link2 className="mr-1 inline h-4 w-4" />Associer à ce client</button></td></tr>))}</tbody></table>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-6">
          <label className="text-sm">Pays (indicatif)<select className={select} value={lien.pays} onChange={(e) => setLien({ ...lien, pays: e.target.value })} data-testid="lien-pays">{etat.pays.map((x) => <option key={x.code} value={x.ind}>{x.nom} (+{x.ind})</option>)}</select></label>
          <label className="text-sm">Numéro ou nom<input className={select} value={lien.cle} placeholder="70 11 22 33 ou +33 6 12 34 56 78" onChange={(e) => setLien({ ...lien, cle: e.target.value })} data-testid="lien-cle" /></label>
          <label className="text-sm">Client de SAWALI<select className={select} value={lien.client_id} onChange={(e) => setLien({ ...lien, client_id: e.target.value })} data-testid="lien-client"><option value="">Aucun</option>{etat.clients.map((c) => <option key={c.id} value={c.id}>{c.nom}</option>)}</select></label>
          <label className="text-sm">Plateforme<select className={select} value={lien.plateforme} onChange={(e) => setLien({ ...lien, plateforme: e.target.value })} data-testid="lien-plateforme"><option value="">Aucune</option>{etat.plateformes.map((p) => <option key={p.code} value={p.code}>{p.nom}</option>)}</select></label>
          <label className="text-sm">Libellé (facultatif)<input className={select} value={lien.libelle} placeholder="Ex. Cabinet Dr BADINI" onChange={(e) => setLien({ ...lien, libelle: e.target.value })} /></label>
          <div className="flex items-end"><button type="button" className="w-full rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50" disabled={!lien.cle.trim() || (!lien.plateforme && !lien.client_id)} onClick={creerLien}><Link2 className="mr-1 inline h-4 w-4" />Associer</button></div>
        </div>
        {etat.liens.length > 0 && (
          <table className="tableau w-full text-sm"><thead><tr className="text-left"><th className="p-2">Numéro / nom</th><th className="p-2">Client de SAWALI</th><th className="p-2">Plateforme</th><th className="p-2">Libellé</th><th className="p-2" /></tr></thead>
            <tbody>{etat.liens.map((l) => (<tr key={l.id} className="border-t border-slate-100"><td className="p-2 font-mono text-xs">{l.cle_affichee || l.cle}</td><td className="p-2">{l.client_nom || "—"}</td><td className="p-2">{l.plateforme || "—"}</td><td className="p-2">{l.libelle}</td>
              <td className="p-2 text-right"><button type="button" className="underline" onClick={() => retirerLien(l)}><Trash2 className="mr-1 inline h-4 w-4" />Retirer</button></td></tr>))}</tbody></table>
        )}
      </section>

      {/* Téléphones source : un identifiant et une clé, montrés UNE SEULE FOIS, à saisir dans Concentration */}
      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4" data-testid="sources">
        <h2 className="text-lg font-bold">Téléphones source</h2>
        <p className="text-sm text-slate-600">Ajoutez un téléphone, puis saisissez son identifiant et sa clé dans Concentration (onglet Paiements → « Envoi à SAWALI »). La clé n'est montrée qu'une fois.</p>
        <div className="flex flex-wrap gap-2">
          <input className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1 text-sm" placeholder="Nom du téléphone (ex. Téléphone du bureau)" value={nomTel} onChange={(e) => setNomTel(e.target.value)} />
          <button type="button" className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50" disabled={nomTel.trim().length < 2} onClick={creerTel}><Plus className="mr-1 inline h-4 w-4" />Ajouter</button>
        </div>
        {cleAffichee && (
          <div className="space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm" data-testid="cle-affichee">
            <div className="font-semibold">À noter maintenant : cette clé ne sera plus jamais affichée.</div>
            <div>Identifiant : <span className="font-mono font-bold">{cleAffichee.id}</span></div>
            <div>Clé : <span className="break-all font-mono font-bold">{cleAffichee.cle}</span></div>
            <button type="button" className="underline" onClick={() => setCleAffichee(null)}><Check className="mr-1 inline h-4 w-4" />J'ai noté, fermer</button>
          </div>
        )}
        {etat.sources.length > 0 && (
          <table className="tableau w-full text-sm"><thead><tr className="text-left"><th className="p-2">Téléphone</th><th className="p-2">Identifiant</th><th className="p-2">Dernier envoi</th><th className="p-2 text-right">Reçues</th><th className="p-2" /></tr></thead>
            <tbody>{etat.sources.map((s) => (<tr key={s.id} className="border-t border-slate-100"><td className="p-2">{s.nom}</td><td className="p-2 font-mono text-xs">{s.id}</td>
              <td className="p-2">{s.dernier_envoi ? new Date(s.dernier_envoi).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "jamais"}</td><td className="p-2 text-right tabular-nums">{s.recues || 0}</td>
              <td className="p-2 text-right"><button type="button" className="underline" onClick={() => retirerTel(s)}><Trash2 className="mr-1 inline h-4 w-4" />Retirer</button></td></tr>))}</tbody></table>
        )}
      </section>
    </div>
  );
}
