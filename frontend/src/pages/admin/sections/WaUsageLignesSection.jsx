/*
  Lot 224 — Paramètres : « Suivi des lignes WhatsApp » — consommations par ligne et par période, pour suivre et facturer
  une plateforme dont la ligne est gérée par SAWALI (ex. ALBARKA).
    - Période : mois en cours, mois précédent ou dates libres (du … au) ; une ligne ou toutes.
    - Messages envoyés / reçus / envois refusés, par type (texte, modèle Meta, média, bouton) et par jour, par heure.
    - Modèles Meta : nombre par nom et par catégorie (MARKETING / UTILITY / AUTHENTICATION) — la catégorie fait le prix.
    - Consommation d'IA : appels, tokens et coût (XOF) des réponses de Liluvine sur la ligne.
    - Détail date et heure des derniers événements (jamais le texte, seulement les 4 derniers chiffres du correspondant) + export CSV.
  Les compteurs partent du déploiement du lot 224. API : GET /admin/wa-lignes/usage(.csv) (backend/routes/wa_usage_lignes.py).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Download, Loader2, RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";

// « AAAA-MM-JJ » d'une date locale
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const debutMois = (decalage = 0) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + decalage); return d; };
const finMois = (decalage = 0) => { const d = debutMois(decalage + 1); d.setDate(0); return d; };
const dateHeure = (t) => (t ? new Date(t).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "medium", timeZone: "UTC" }) : "");
const nombre = (n) => Number(n || 0).toLocaleString("fr-FR");
const TYPES = { texte: "Texte libre", modele: "Modèle Meta", media: "Média", interactif: "Bouton", ia: "IA (Liluvine)", text: "Texte reçu" };

export default function WaUsageLignesSection() {
  const [du, setDu] = useState(iso(debutMois()));
  const [au, setAu] = useState(iso(new Date()));
  const [ligne, setLigne] = useState("");
  const [data, setData] = useState(null);
  const [lignesDispo, setLignesDispo] = useState([]);
  const [charge, setCharge] = useState(false);

  // Lecture du rapport de la période choisie
  const lire = useCallback(async () => {
    setCharge(true);
    try {
      const r = await apiClient.get("/admin/wa-lignes/usage", { params: { du, au, ligne: ligne || undefined } });
      setData(r.data);
      if (!ligne) setLignesDispo(r.data.lignes.map((l) => ({ cle: l.cle, libelle: l.libelle })));
    } catch (e) { toast.error(e?.response?.data?.detail || "Suivi indisponible"); }
    finally { setCharge(false); }
  }, [du, au, ligne]);
  useEffect(() => { lire(); }, [lire]);

  // Export CSV (Excel) : téléchargement avec la session de l'administrateur
  const exporter = async () => {
    try {
      const r = await apiClient.get("/admin/wa-lignes/usage.csv", { params: { du, au, ligne: ligne || undefined }, responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = `lignes_whatsapp_${du}_${au}.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch { toast.error("Export impossible"); }
  };

  const t = data?.total;
  const Tuile = ({ titre, valeur, aide }) => (
    <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3" title={aide}>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{titre}</div>
      <div className="text-xl font-bold tabular-nums text-slate-900">{valeur}</div>
    </div>
  );
  const heures = t ? Object.entries(t.heures).map(([h, n]) => ({ heure: `${h}h`, messages: n })) : [];
  const modeles = t ? Object.entries(t.modeles).sort((a, b) => b[1] - a[1]) : [];

  return (
    <div className="space-y-4 text-sm" data-testid="wa-usage-lignes">
      <p className="text-xs text-slate-600">
        Messages, modèles Meta et consommation d'IA <b>par ligne WhatsApp</b> et par période : de quoi suivre, et facturer si besoin,
        une plateforme comme ALBARKA. Les heures sont en UTC (heure de Ouagadougou). Les compteurs partent du déploiement du suivi :
        l'historique antérieur n'est pas reconstitué.
      </p>

      {/* Période et ligne */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg ring-1 ring-slate-200 bg-white p-3">
        <label className="text-xs text-slate-600">Du
          <input type="date" value={du} max={au} onChange={(e) => setDu(e.target.value)} data-testid="usage-du" className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="text-xs text-slate-600">Au
          <input type="date" value={au} min={du} onChange={(e) => setAu(e.target.value)} data-testid="usage-au" className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="text-xs text-slate-600">Ligne
          <select value={ligne} onChange={(e) => setLigne(e.target.value)} data-testid="usage-ligne" className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm">
            <option value="">Toutes les lignes</option>
            {lignesDispo.map((l) => <option key={l.cle} value={l.cle}>{l.libelle}</option>)}
          </select>
        </label>
        <button type="button" className="text-xs text-sawali-blue underline" onClick={() => { setDu(iso(debutMois())); setAu(iso(new Date())); }}>Mois en cours</button>
        <button type="button" className="text-xs text-sawali-blue underline" onClick={() => { setDu(iso(debutMois(-1))); setAu(iso(finMois(-1))); }}>Mois précédent</button>
        <button type="button" onClick={lire} disabled={charge} className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50">
          {charge ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} Actualiser
        </button>
        <button type="button" onClick={exporter} data-testid="usage-csv" className="ml-auto inline-flex items-center gap-1 rounded-lg ring-1 ring-slate-300 px-3 py-1.5 text-xs">
          <Download className="h-3.5 w-3.5" /> Exporter en CSV
        </button>
      </div>

      {!data ? <Loader2 className="h-5 w-5 animate-spin text-slate-400" /> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
            <Tuile titre="Messages envoyés" valeur={nombre(t.sortants)} />
            <Tuile titre="Messages reçus" valeur={nombre(t.entrants)} />
            <Tuile titre="Modèles Meta" valeur={nombre(t.par_type.modele)} aide="Messages envoyés avec un modèle approuvé par Meta (facturés selon leur catégorie)" />
            <Tuile titre="Envois refusés" valeur={nombre(t.echecs)} />
            <Tuile titre="Réponses IA" valeur={nombre(t.ia.appels)} aide={`${nombre(t.ia.tokens)} tokens`} />
            <Tuile titre="Coût IA (XOF)" valeur={nombre(t.ia.cout_xof)} />
          </div>

          {/* Par ligne */}
          <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200 bg-white p-3">
            <h3 className="mb-2 font-semibold text-slate-800">Par ligne</h3>
            <table className="w-full text-xs">
              <thead><tr className="text-left text-slate-500">
                <th className="py-1 pr-2">Ligne</th><th className="pr-2 text-right">Envoyés</th><th className="pr-2 text-right">Reçus</th>
                <th className="pr-2 text-right">Texte</th><th className="pr-2 text-right">Modèles</th><th className="pr-2 text-right">Médias</th>
                <th className="pr-2 text-right">Boutons</th><th className="pr-2 text-right">Refusés</th><th className="pr-2 text-right">Réponses IA</th><th className="text-right">Coût IA (XOF)</th>
              </tr></thead>
              <tbody>
                {data.lignes.map((l) => (
                  <tr key={l.cle} className="border-t border-slate-100">
                    <td className="py-1 pr-2 font-medium">{l.libelle}{l.privee && <span className="ml-1 rounded bg-slate-200 px-1 text-[10px]">privée</span>}
                      {l.telephone && <span className="ml-1 text-slate-400">{l.telephone}</span>}</td>
                    <td className="pr-2 text-right tabular-nums">{nombre(l.sortants)}</td><td className="pr-2 text-right tabular-nums">{nombre(l.entrants)}</td>
                    <td className="pr-2 text-right tabular-nums">{nombre(l.par_type.texte)}</td><td className="pr-2 text-right tabular-nums">{nombre(l.par_type.modele)}</td>
                    <td className="pr-2 text-right tabular-nums">{nombre(l.par_type.media)}</td><td className="pr-2 text-right tabular-nums">{nombre(l.par_type.interactif)}</td>
                    <td className="pr-2 text-right tabular-nums">{nombre(l.echecs)}</td><td className="pr-2 text-right tabular-nums">{nombre(l.ia.appels)}</td>
                    <td className="text-right tabular-nums">{nombre(l.ia.cout_xof)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Graphiques : par jour et par heure */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3">
              <h3 className="mb-2 font-semibold text-slate-800">Messages par jour</h3>
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer><BarChart data={data.serie.map((j) => ({ ...j, jour: j.jour.slice(5) }))} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="jour" tick={{ fontSize: 10 }} /><YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                  <Tooltip /><Legend />
                  <Bar dataKey="sortants" name="Envoyés" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="entrants" name="Reçus" fill="#10b981" radius={[3, 3, 0, 0]} />
                </BarChart></ResponsiveContainer>
              </div>
            </div>
            <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3">
              <h3 className="mb-2 font-semibold text-slate-800">Messages par heure (UTC)</h3>
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer><BarChart data={heures} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="heure" tick={{ fontSize: 10 }} interval={1} /><YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
                  <Tooltip /><Bar dataKey="messages" name="Messages" fill="#8b5cf6" radius={[3, 3, 0, 0]} />
                </BarChart></ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Modèles Meta */}
          <div className="rounded-lg ring-1 ring-slate-200 bg-white p-3">
            <h3 className="mb-2 font-semibold text-slate-800">Modèles Meta utilisés</h3>
            <p className="mb-2 text-xs text-slate-600">
              Catégories : {Object.keys(t.categories).length === 0 ? "aucune détectée" :
                Object.entries(t.categories).map(([c, n]) => `${c} ${nombre(n)}`).join(" · ")}
              {" "}— la catégorie fait le prix côté Meta (Marketing &gt; Utilitaire &gt; Authentification).
            </p>
            {modeles.length === 0 ? <p className="text-xs text-slate-500">Aucun modèle envoyé sur la période.</p> : (
              <table className="text-xs"><thead><tr className="text-left text-slate-500"><th className="pr-6">Modèle</th><th className="text-right">Envois</th></tr></thead>
                <tbody>{modeles.map(([n, v]) => <tr key={n} className="border-t border-slate-100"><td className="pr-6 font-mono">{n}</td><td className="text-right tabular-nums">{nombre(v)}</td></tr>)}</tbody></table>
            )}
          </div>

          {/* Détail date et heure */}
          <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200 bg-white p-3">
            <h3 className="mb-2 font-semibold text-slate-800">Détail date et heure <span className="font-normal text-slate-500">({nombre(data.nb_evenements)} événement(s), les 300 plus récents affichés)</span></h3>
            <table className="w-full text-xs">
              <thead><tr className="text-left text-slate-500"><th className="py-1 pr-2">Date et heure (UTC)</th><th className="pr-2">Ligne</th><th className="pr-2">Sens</th><th className="pr-2">Type</th><th className="pr-2">Modèle</th><th className="pr-2">Catégorie</th><th className="pr-2">Fin du numéro</th><th className="text-right">IA</th></tr></thead>
              <tbody>
                {data.evenements.length === 0 && <tr><td colSpan={8} className="py-2 text-slate-500">Aucun événement sur la période.</td></tr>}
                {data.evenements.map((e, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="py-1 pr-2 whitespace-nowrap">{dateHeure(e.t)}</td><td className="pr-2">{e.ligne}</td>
                    <td className="pr-2">{e.sens === "in" ? "Reçu" : "Envoyé"}{e.ok === false && <span className="ml-1 text-rose-600">(refusé)</span>}</td>
                    <td className="pr-2">{TYPES[e.type] || e.type}</td><td className="pr-2 font-mono">{e.modele || ""}</td><td className="pr-2">{e.categorie || ""}</td>
                    <td className="pr-2 font-mono">{e.fin ? `…${e.fin}` : ""}</td>
                    <td className="text-right tabular-nums">{e.type === "ia" ? `${nombre(e.tokens)} tok · ${nombre(e.cout_xof)} XOF` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
