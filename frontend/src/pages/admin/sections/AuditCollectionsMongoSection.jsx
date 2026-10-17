/*
  Lot 225 — Paramètres : « Audit des collections MongoDB » — en un clic, quelles collections ne servent plus depuis longtemps.
    - Bouton « Lancer l'analyse » : le calcul part en arrière-plan sur le serveur, la page suit l'avancement (jauge) puis affiche le rapport.
    - Pour chaque collection de chaque base du cluster : documents, taille, date de dernière utilisation connue (création du
      document le plus récent ou dernière mise à jour d'un champ date), accès d'index, statut et conseil.
    - Statuts : VIDE · ACTIVE (< 90 j) · PEU ACTIVE · INACTIVE (> 180 j) · INCONNUE. Une collection citée dans le code du serveur
      n'est JAMAIS proposée à la suppression. Lecture seule : cet écran ne supprime rien.
    - Graphiques : jauge du plafond de 500 collections, collections par base et par statut.
    - Inventaire des organisations / projets / clusters Atlas si la variable ATLAS_API_KEYS est renseignée dans Render.
  API : POST /admin/audit-mongo/lancer, GET /admin/audit-mongo/etat, /rapport, /rapport.csv (backend/routes/audit_collections_mongo.py).
*/
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { Database, Download, Loader2, Play } from "lucide-react";
import { apiClient } from "@/lib/api";

const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const nombre = (n) => Number(n || 0).toLocaleString("fr-FR");
// Couleurs des statuts (graphiques et pastilles)
const COULEURS = { ACTIVE: "#10b981", "PEU ACTIVE": "#f59e0b", INACTIVE: "#ef4444", VIDE: "#94a3b8", INCONNUE: "#8b5cf6" };
const STATUTS = ["ACTIVE", "PEU ACTIVE", "INACTIVE", "VIDE", "INCONNUE"];

export default function AuditCollectionsMongoSection() {
  const [rapport, setRapport] = useState(null);
  const [atlasConfigure, setAtlasConfigure] = useState(false);
  const [hote, setHote] = useState("");
  const [etat, setEtat] = useState(null);
  const [charge, setCharge] = useState(true);
  const [fBase, setFBase] = useState("");
  const [fStatut, setFStatut] = useState("");
  const [fVerdict, setFVerdict] = useState("");
  const [recherche, setRecherche] = useState("");
  const minuteur = useRef(null);

  // Lecture du dernier rapport enregistré
  const lireRapport = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/audit-mongo/rapport");
      setRapport(r.data.rapport);
      setAtlasConfigure(!!r.data.atlas_configure);
      setHote(r.data.hote_courant || "");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Rapport indisponible (réservé à l'administrateur principal)");
    } finally { setCharge(false); }
  }, []);

  // Suivi de l'avancement toutes les 2 s tant que l'analyse tourne, puis relecture du rapport
  const suivre = useCallback(() => {
    clearInterval(minuteur.current);
    minuteur.current = setInterval(async () => {
      try {
        const e = (await apiClient.get("/admin/audit-mongo/etat")).data;
        setEtat(e);
        if (!e.en_cours) {
          clearInterval(minuteur.current);
          if (e.erreur) toast.error(e.erreur); else toast.success("Analyse terminée");
          lireRapport();
        }
      } catch { clearInterval(minuteur.current); }
    }, 2000);
  }, [lireRapport]);

  useEffect(() => {
    lireRapport();
    // Une analyse déjà en cours (page rouverte) : on reprend le suivi
    apiClient.get("/admin/audit-mongo/etat").then((r) => { setEtat(r.data); if (r.data.en_cours) suivre(); }).catch(() => {});
    return () => clearInterval(minuteur.current);
  }, [lireRapport, suivre]);

  const lancer = async () => {
    try {
      const r = await apiClient.post("/admin/audit-mongo/lancer");
      setEtat(r.data);
      toast.message("Patientez… analyse en cours (lecture seule)");
      suivre();
    } catch (e) { toast.error(e?.response?.data?.detail || "Lancement impossible"); }
  };

  // Export CSV (avec le jeton de session de l'application)
  const exporter = async () => {
    try {
      const r = await apiClient.get("/admin/audit-mongo/rapport.csv", { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a"); a.href = url; a.download = "audit_collections_mongodb.csv"; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast.error("Export impossible"); }
  };

  const lignes = rapport?.lignes || [];
  const bases = useMemo(() => [...new Set(lignes.map((l) => l.base))], [lignes]);
  const verdicts = useMemo(() => [...new Set(lignes.map((l) => l.verdict))], [lignes]);
  const filtrees = useMemo(() => lignes.filter((l) =>
    (!fBase || l.base === fBase) && (!fStatut || l.statut === fStatut) && (!fVerdict || l.verdict === fVerdict)
    && (!recherche || l.collection.toLowerCase().includes(recherche.toLowerCase()))
  ).sort((a, b) => (b.jours_inactivite ?? -1) - (a.jours_inactivite ?? -1)), [lignes, fBase, fStatut, fVerdict, recherche]);

  // Données des graphiques : collections par base, ventilées par statut
  const parBase = useMemo(() => bases.map((b) => {
    const o = { base: b };
    STATUTS.forEach((s) => { o[s] = lignes.filter((l) => l.base === b && l.statut === s).length; });
    return o;
  }), [bases, lignes]);

  if (charge) return <Loader2 className="h-5 w-5 animate-spin text-slate-400" />;

  const resume = rapport?.resume;
  const plafond = resume?.plafond || 500;
  const pct = resume ? Math.min(100, Math.round((resume.total_collections / plafond) * 100)) : 0;
  const enCours = !!etat?.en_cours;
  const avance = etat?.total ? Math.round((etat.fait / etat.total) * 100) : 0;

  return (
    <div className="space-y-4 text-sm" data-testid="audit-mongo-section">
      <p className="text-xs text-slate-600">
        Pour <b>chaque collection de chaque base</b> du cluster MongoDB auquel SAWALI est connecté, cet outil cherche la date de
        dernière utilisation connue et vous dit lesquelles ne servent plus depuis longtemps. <b>Lecture seule : rien n'est supprimé.</b>{" "}
        MongoDB ne mémorise pas la dernière <i>lecture</i> d'une collection : la date est celle de la dernière écriture
        (création ou mise à jour), complétée par les accès d'index depuis le dernier redémarrage.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={lancer} disabled={enCours} data-testid="audit-mongo-lancer"
          className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 text-white px-3 py-1.5 text-xs hover:bg-slate-800 disabled:opacity-50">
          {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          {rapport ? "Relancer l'analyse" : "Lancer l'analyse"}
        </button>
        {rapport && (
          <button type="button" onClick={exporter} data-testid="audit-mongo-csv"
            className="inline-flex items-center gap-1.5 rounded-lg bg-white ring-1 ring-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50">
            <Download className="h-3.5 w-3.5" /> Exporter en CSV
          </button>
        )}
        {rapport && <span className="text-[11px] text-slate-500">Dernier rapport : {dateFr(rapport.genere_le)}</span>}
        {hote && <span className="text-[11px] text-slate-400 font-mono">Cluster : {hote}</span>}
      </div>

      {/* Jauge d'avancement pendant l'analyse */}
      {enCours && (
        <div className="rounded-lg ring-1 ring-sky-200 bg-sky-50 p-3" data-testid="audit-mongo-avancement">
          <p className="text-xs text-sky-900 mb-1.5">
            Analyse en cours… {nombre(etat.fait)} / {nombre(etat.total)} collections{etat.base ? ` · base « ${etat.base} »` : ""}
          </p>
          <div className="h-2 rounded-full bg-sky-100 overflow-hidden"><div className="h-full bg-sky-500 transition-all" style={{ width: `${avance}%` }} /></div>
        </div>
      )}
      {etat?.erreur && !enCours && <p className="text-xs text-rose-600">{etat.erreur}</p>}

      {!rapport && !enCours && (
        <p className="text-xs text-slate-500">Aucun rapport pour l'instant : cliquez sur « Lancer l'analyse » (compter environ une à deux minutes).</p>
      )}

      {resume && (
        <>
          {/* Tuiles de synthèse */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2" data-testid="audit-mongo-tuiles">
            <Tuile titre="Collections" valeur={`${nombre(resume.total_collections)} / ${nombre(plafond)}`} alerte={pct >= 90} />
            <Tuile titre="Vides" valeur={nombre(resume.par_statut.VIDE || 0)} />
            <Tuile titre="Inactives (> 180 j)" valeur={nombre(resume.par_statut.INACTIVE || 0)} />
            <Tuile titre="Candidates à la suppression" valeur={nombre(resume.candidates)} accent />
            <Tuile titre="À vérifier" valeur={nombre(resume.a_verifier)} />
          </div>

          {/* Jauge du plafond (paliers gratuit / Flex : 500 collections) */}
          <div data-testid="audit-mongo-plafond">
            <p className="text-xs text-slate-600 mb-1">
              <Database className="inline h-3.5 w-3.5 mr-1" />Plafond des paliers gratuit / Flex : <b>{pct} %</b> utilisé
              {pct >= 100 && <span className="text-rose-600 font-semibold"> — cluster plein : plus aucune collection ne peut être créée</span>}
            </p>
            <div className="h-3 rounded-full bg-slate-100 overflow-hidden">
              <div className={`h-full ${pct >= 90 ? "bg-rose-500" : pct >= 70 ? "bg-amber-500" : "bg-emerald-500"}`} style={{ width: `${pct}%` }} />
            </div>
            <p className="text-[11px] text-slate-500 mt-1">Un cluster M10 ou plus n'a pas ce plafond strict.</p>
          </div>

          {/* Graphique : collections par base et par statut */}
          <div className="rounded-lg ring-1 ring-slate-200 p-3" data-testid="audit-mongo-graphique">
            <p className="text-xs font-semibold text-slate-700 mb-2">Collections par base et par statut</p>
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <BarChart data={parBase}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="base" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip /><Legend />
                  {STATUTS.map((s) => <Bar key={s} dataKey={s} stackId="a" name={s} fill={COULEURS[s]} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Tableau des collections */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <select value={fBase} onChange={(e) => setFBase(e.target.value)} className="rounded border border-slate-300 px-2 py-1" data-testid="audit-mongo-f-base">
                <option value="">Toutes les bases</option>{bases.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
              <select value={fStatut} onChange={(e) => setFStatut(e.target.value)} className="rounded border border-slate-300 px-2 py-1" data-testid="audit-mongo-f-statut">
                <option value="">Tous les statuts</option>{STATUTS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select value={fVerdict} onChange={(e) => setFVerdict(e.target.value)} className="rounded border border-slate-300 px-2 py-1 max-w-[16rem]" data-testid="audit-mongo-f-verdict">
                <option value="">Tous les conseils</option>{verdicts.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
              <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Chercher une collection…"
                className="rounded border border-slate-300 px-2 py-1 w-52" data-testid="audit-mongo-recherche" />
              <span className="text-slate-500">{nombre(filtrees.length)} collection(s) — les plus anciennes d'abord</span>
            </div>
            <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
              <table className="min-w-full text-xs" data-testid="audit-mongo-tableau">
                <thead className="bg-slate-50 text-left text-slate-600">
                  <tr>
                    <th className="px-2 py-1.5">Base</th><th className="px-2 py-1.5">Collection</th><th className="px-2 py-1.5">Statut</th>
                    <th className="px-2 py-1.5 text-right">Documents</th><th className="px-2 py-1.5 text-right">Taille (Mo)</th>
                    <th className="px-2 py-1.5">Dernière activité</th><th className="px-2 py-1.5 text-right">Jours</th>
                    <th className="px-2 py-1.5 text-right" title="Accès d'index depuis le dernier redémarrage (reflète aussi les lectures)">Accès index</th>
                    <th className="px-2 py-1.5">Conseil</th>
                  </tr>
                </thead>
                <tbody>
                  {filtrees.slice(0, 600).map((l) => (
                    <tr key={`${l.base}.${l.collection}`} className="border-t border-slate-100 hover:bg-sky-400/15">
                      <td className="px-2 py-1">{l.base}</td>
                      <td className="px-2 py-1 font-mono">{l.collection}</td>
                      <td className="px-2 py-1">
                        <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-white" style={{ background: COULEURS[l.statut] }}>{l.statut}</span>
                      </td>
                      <td className="px-2 py-1 text-right">{nombre(l.documents)}</td>
                      <td className="px-2 py-1 text-right">{l.taille_mo ?? "—"}</td>
                      <td className="px-2 py-1" title={l.champ_date ? `champ « ${l.champ_date} »` : "création du dernier document"}>{dateFr(l.derniere_activite)}</td>
                      <td className="px-2 py-1 text-right">{l.jours_inactivite ?? "—"}</td>
                      <td className="px-2 py-1 text-right" title={l.acces_index_depuis ? `depuis le ${dateFr(l.acces_index_depuis)}` : ""}>{l.acces_index_ops ?? "—"}</td>
                      <td className={`px-2 py-1 ${l.verdict.startsWith("Candidate") ? "font-semibold text-rose-600" : ""}`}>{l.verdict}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {filtrees.length > 600 && <p className="text-[11px] text-slate-500">Les 600 premières lignes sont affichées : affinez les filtres ou exportez le CSV.</p>}
          </div>
        </>
      )}

      {/* Organisations › projets › clusters Atlas (facultatif) */}
      <div className="rounded-lg ring-1 ring-slate-200 p-3 space-y-1.5" data-testid="audit-mongo-atlas">
        <p className="font-semibold text-slate-800">Organisations, projets et clusters Atlas</p>
        {rapport?.atlas?.configure ? (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="text-left text-slate-600"><tr><th className="pr-3">Organisation</th><th className="pr-3">Projet</th><th className="pr-3">Cluster</th><th className="pr-3">Palier</th><th>Adresse</th></tr></thead>
                <tbody>
                  {rapport.atlas.clusters.map((c, i) => (
                    <tr key={i} className={`border-t border-slate-100 ${c.courant ? "bg-emerald-50" : ""}`}>
                      <td className="pr-3 py-1">{c.organisation}</td><td className="pr-3">{c.projet}</td><td className="pr-3">{c.cluster}</td>
                      <td className="pr-3">{c.palier}</td><td className="font-mono">{c.hote}{c.courant ? "  ← utilisé par SAWALI" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(rapport.atlas.erreurs || []).map((e, i) => <p key={i} className="text-xs text-amber-700">{e}</p>)}
          </>
        ) : (
          <p className="text-xs text-slate-600">
            Inventaire non activé. Pour lister vos organisations, projets et clusters (avec leur palier), créez dans Atlas une clé d'API
            en lecture seule (<i>Organization › Access Manager › API Keys</i>, rôle <i>Organization Read Only</i>), puis ajoutez dans Render,
            sur le service <code>sawali-backend</code>, la variable <code>ATLAS_API_KEYS</code> au format <code>clé_publique:clé_privée</code>
            (plusieurs organisations séparées par une virgule). La clé n'est jamais affichée ni enregistrée dans le rapport.
            L'analyse des collections ci-dessus fonctionne sans cette variable.
          </p>
        )}
      </div>
    </div>
  );
}

// Tuile de synthèse
function Tuile({ titre, valeur, accent, alerte }) {
  return (
    <div className={`rounded-lg ring-1 p-2.5 ${alerte ? "ring-rose-300 bg-rose-50" : accent ? "ring-amber-300 bg-amber-50" : "ring-slate-200 bg-white"}`}>
      <p className="text-[11px] text-slate-500">{titre}</p>
      <p className="text-lg font-semibold text-slate-900 tabular-nums">{valeur}</p>
    </div>
  );
}
