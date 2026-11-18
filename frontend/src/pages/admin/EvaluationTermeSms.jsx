/**
 * Lot 435 — « Évaluer un terme » dans Transactions SMS (même principe que l'historique d'auRor).
 * On tape un terme (SONABEL, Pharmacie, un nom, un numéro…) : le nombre d'occurrences s'affiche après une courte pause ;
 * « Évaluer » donne ensuite les chiffres MOIS PAR MOIS (dépenses, recettes, moyenne, plus gros montant), la répartition
 * par opérateur et les dernières opérations, avec export CSV et impression. Seules les transactions comptent.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Search, RefreshCw, Download, Printer, ChevronDown, ChevronUp } from "lucide-react";   // règle 15 : pictogramme sur chaque action
import { apiClient } from "@/lib/api";

const fcfa = (v) => `${Number(v || 0).toLocaleString("fr-FR")} FCFA`;
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const libMois = (m) => `${MOIS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
const iso = (d) => d.toISOString().slice(0, 10);
const PERIODES = [["tout", "Toute la période"], ["an", "12 derniers mois"], ["annee", "Année en cours"], ["annee-1", "Année précédente"], ["perso", "Personnalisée…"]];

/** Dates « du » / « au » de la période choisie. */
function bornes(p, du, au) {
  const n = new Date(), a = n.getUTCFullYear();
  if (p === "an") { const d = new Date(); d.setUTCFullYear(a - 1); return { du: iso(d), au: iso(n) }; }
  if (p === "annee") return { du: `${a}-01-01`, au: iso(n) };
  if (p === "annee-1") return { du: `${a - 1}-01-01`, au: `${a - 1}-12-31` };
  if (p === "perso") return { du, au };
  return { du: "", au: "" };
}

export default function EvaluationTermeSms() {
  const [ouvert, setOuvert] = useState(false);
  const [terme, setTerme] = useState("");
  const [periode, setPeriode] = useState("tout");
  const [du, setDu] = useState("");
  const [au, setAu] = useState("");
  const [nombre, setNombre] = useState(null);       // occurrences trouvées pendant la frappe
  const [res, setRes] = useState(null);             // résultat complet après « Évaluer »
  const [enCours, setEnCours] = useState(false);
  const jeton = useRef(0);
  const t = terme.trim();
  const params = () => ({ terme: t, ...bornes(periode, du, au) });

  // Décompte automatique après 400 ms sans frappe (au moins 2 caractères)
  useEffect(() => {
    setNombre(null);
    if (t.length < 2) return undefined;
    const n = ++jeton.current;
    const id = setTimeout(() => {
      apiClient.get("/admin/transactions-sms/evaluation-terme", { params: params() })
        .then((r) => { if (n === jeton.current) setNombre(r.data.occurrences); }).catch(() => {});
    }, 400);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, periode, du, au]);

  /** Lance l'évaluation complète (toast « en cours » puis résultat — règle 17). */
  const evaluer = async () => {
    if (t.length < 2) { toast.error("Tapez au moins 2 caractères"); return; }
    setEnCours(true);
    const tid = toast.loading(`Évaluation de « ${t} » en cours…`);
    try {
      const { data } = await apiClient.get("/admin/transactions-sms/evaluation-terme", { params: { ...params(), evaluer: true } });
      setRes(data);
      toast.success(`« ${t} » : ${data.occurrences} occurrence(s) sur ${data.par_mois.length} mois`, { id: tid });
    } catch (e) { toast.error(e?.response?.data?.detail || "Évaluation impossible", { id: tid }); }
    setEnCours(false);
  };

  const maxMois = useMemo(() => Math.max(1, ...(res?.par_mois || []).map((m) => Math.max(m.depenses, m.recettes))), [res]);

  /** Export CSV (séparateur « ; », ouvrable dans Excel) généré dans le navigateur. */
  const exporter = () => {
    const l = ["Mois;Occurrences;Nb dépenses;Dépenses;Nb recettes;Recettes", ...res.par_mois.map((m) => [m.mois, m.occurrences, m.nb_depenses, m.depenses, m.nb_recettes, m.recettes].join(";"))];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + l.join("\n")], { type: "text/csv;charset=utf-8" }));
    a.download = `evaluation-${res.terme.replace(/\W+/g, "_")}.csv`; a.click();
    toast.success("Export CSV prêt");
  };

  const champ = "mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm";
  const bouton = "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-semibold";
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4" data-testid="evaluation-terme">
      <button type="button" className="flex w-full items-center justify-between text-left" onClick={() => setOuvert(!ouvert)} aria-expanded={ouvert}>
        <h2 className="flex items-center gap-2 text-lg font-bold"><Search size={18} className="text-sky-700" /> Évaluer un terme</h2>
        {ouvert ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
      </button>
      {ouvert && (
        <div className="mt-3 space-y-3">
          <p className="text-sm text-slate-600">Tapez un terme ou une expression (SONABEL, Pharmacie, un nom, un numéro…) : on compte ses occurrences et on donne les chiffres mois par mois. Seules les transactions comptent.</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-sm sm:col-span-2">Terme ou expression
              <input className={champ} value={terme} onChange={(e) => setTerme(e.target.value)} onKeyDown={(e) => e.key === "Enter" && evaluer()} placeholder="Ex. SONABEL" data-testid="terme" />
            </label>
            <label className="text-sm">Période
              <select className={champ} value={periode} onChange={(e) => setPeriode(e.target.value)}>{PERIODES.map(([v, n]) => <option key={v} value={v}>{n}</option>)}</select>
            </label>
            {periode === "perso" && (<>
              <label className="text-sm">Du<input type="date" className={champ} value={du} onChange={(e) => setDu(e.target.value)} /></label>
              <label className="text-sm">Au<input type="date" className={champ} value={au} onChange={(e) => setAu(e.target.value)} /></label>
            </>)}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={`${bouton} bg-sky-700 text-white disabled:opacity-50`} onClick={evaluer} disabled={enCours || t.length < 2}><Search size={15} /> Évaluer</button>
            {res && <button type="button" className={`${bouton} border border-emerald-600 text-emerald-700`} onClick={evaluer} disabled={enCours}><RefreshCw size={15} /> Actualiser</button>}
            {nombre !== null && <span className="text-sm text-slate-700" data-testid="nombre">{nombre} occurrence{nombre > 1 ? "s" : ""} trouvée{nombre > 1 ? "s" : ""}</span>}
          </div>

          {res && (
            <div className="space-y-4" data-testid="resultat-terme" id="zone-evaluation-terme">
              {res.occurrences === 0 ? <p className="text-sm text-slate-600">Aucune transaction ne contient « {res.terme} » sur cette période.</p> : (<>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {[["Dépenses", fcfa(res.depenses), `${res.nb_depenses} paiement(s)`, "text-red-700"], ["Moyenne par mois", fcfa(res.moyenne_mensuelle_depenses), "dépenses", "text-sky-800"],
                    ["Plus gros paiement", fcfa(res.plus_grosse_depense), `du ${res.premiere} au ${res.derniere}`, "text-red-700"], ["Recettes", fcfa(res.recettes), `${res.nb_recettes} reçu(s)`, "text-emerald-700"]].map(([n, v, s, c]) => (
                    <div key={n} className="rounded-lg border border-slate-200 p-3"><div className="text-xs text-slate-500">{n}</div><div className={`text-base font-bold tabular-nums ${c}`}>{v}</div><div className="text-xs text-slate-500">{s}</div></div>
                  ))}
                </div>
                <div className="space-y-1.5">
                  {res.par_mois.map((m) => (
                    <div key={m.mois} className="grid grid-cols-[5rem_1fr_auto] items-center gap-2 text-xs">
                      <span className="text-slate-600">{libMois(m.mois)}</span>
                      <div className="space-y-0.5">
                        <div className="h-3 rounded bg-red-500" style={{ width: `${(m.depenses / maxMois) * 100}%`, minWidth: m.depenses ? 3 : 0 }} title={`Dépenses ${fcfa(m.depenses)}`} />
                        {m.recettes > 0 && <div className="h-3 rounded bg-emerald-500" style={{ width: `${(m.recettes / maxMois) * 100}%`, minWidth: 3 }} title={`Recettes ${fcfa(m.recettes)}`} />}
                      </div>
                      <span className="text-right font-semibold tabular-nums"><span className="text-red-700">{fcfa(m.depenses)}</span>{m.recettes > 0 && <span className="block text-emerald-700">+ {fcfa(m.recettes)}</span>}</span>
                    </div>
                  ))}
                </div>
                <p className="text-sm text-slate-700">Par opérateur : {res.par_operateur.map((o) => `${o.operateur} (${o.nombre})`).join(" · ")}</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm"><thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Date</th><th>Opérateur</th><th>Tiers</th><th>Référence</th><th className="text-right">Montant</th></tr></thead>
                    <tbody>{res.operations.slice(0, 30).map((o, i) => (
                      <tr key={i} className="border-t border-slate-100"><td className="py-1">{new Date(o.ms).toLocaleDateString("fr-FR", { timeZone: "UTC" })}</td><td>{o.operateur}</td><td>{o.tiers}</td><td className="text-sky-800">{o.reference}</td>
                        <td className={`text-right font-semibold tabular-nums ${o.genre === "DEPENSE" ? "text-red-700" : "text-emerald-700"}`}>{o.genre === "DEPENSE" ? "−" : "+"} {fcfa(o.montant)}</td></tr>))}</tbody></table>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={`${bouton} border border-sky-700 text-sky-800`} onClick={exporter}><Download size={15} /> Exporter en CSV</button>
                  <button type="button" className={`${bouton} border border-slate-500 text-slate-700`} onClick={() => window.print()}><Printer size={15} /> Imprimer</button>
                </div>
              </>)}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
