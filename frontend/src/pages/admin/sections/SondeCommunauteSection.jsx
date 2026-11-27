// ============================================================================
// Lot 485 — Paramètres → « 🌍 Sonde réseau — espace commun des téléphones ».
// L'application Android « Sonde Réseau » (téléphones identifiés par un compte Google, après un consentement écrit) envoie ses mesures à SAWALI. SAWALI ne garde
// pas les mesures une à une : il les ADDITIONNE par jour, zone de 2 km, type de connexion (Wi-Fi / mobile) et opérateur. Cet écran en fait la synthèse :
// cartes de résumé, détail par type et par opérateur, tableau par lieu (triable, totaux collés dessous) et liste des participants (fenêtre modale).
// Backend : GET /api/sonde-reseau/communaute, GET / POST / DELETE /api/sonde-reseau/communaute/participants (administrateur seul). Logique : backend/sonde_communaute.py.
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { Ban, MapPin, RefreshCw, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { COULEUR_NIVEAU } from "@/lib/sondeReseauCalculs";

const PERIODES = [{ j: 1, l: "Dernières 24 h" }, { j: 7, l: "7 derniers jours" }, { j: 30, l: "30 derniers jours" }, { j: 120, l: "120 jours (tout)" }];
const TYPES = [{ v: "", l: "Tous les types de connexion" }, { v: "wifi", l: "Wi-Fi" }, { v: "mobile", l: "Réseau mobile" }];
const num = (n, d = 1) => (n == null ? "—" : Number(n).toLocaleString("fr-FR", { maximumFractionDigits: d }));
const jourFr = (aaaammjj) => (aaaammjj && aaaammjj.length === 8 ? `${aaaammjj.slice(6)}/${aaaammjj.slice(4, 6)}/${aaaammjj.slice(0, 4)}` : "");
const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const libelleType = (t) => (t === "wifi" ? "Wi-Fi" : t === "mobile" ? "Mobile" : t);
// Une zone de 2 km s'ouvre sur OpenStreetMap (centre de la zone, jamais une position précise)
const lienCarte = (l) => `https://www.openstreetmap.org/?mlat=${l.lat}&mlon=${l.lon}#map=13/${l.lat}/${l.lon}`;
const nomZone = (l) => (l.lat == null ? "Lieu non partagé" : `${num(l.lat, 2)} ; ${num(l.lon, 2)}`);

function Carte({ titre, valeur, detail, niveau }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{titre}</p>
      <p className={`text-xl font-bold tabular-nums ${COULEUR_NIVEAU[niveau || "inconnu"]}`}>{valeur}</p>
      {detail && <p className="text-[11px] text-slate-500">{detail}</p>}
    </div>);
}

// Petit tableau « par type » ou « par opérateur » : une ligne par valeur
function TableauRepartition({ titre, donnees, libelle }) {
  const lignes = Object.entries(donnees || {});
  if (!lignes.length) return null;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <p className="px-3 pt-2 text-xs font-semibold text-slate-700">{titre}</p>
      <table className="w-full text-xs">
        <thead><tr className="text-left text-slate-500"><th className="p-2">{libelle}</th><th className="p-2 text-right">Mesures</th><th className="p-2 text-right">Perte %</th><th className="p-2 text-right">Latence ms</th><th className="p-2 text-right">↓ Mb/s</th></tr></thead>
        <tbody>{lignes.map(([cle, f]) => (
          <tr key={cle} className="border-t border-slate-100 hover:bg-sky-400/15">
            <td className="p-2 font-medium text-blue-800">{libelle === "Type" ? libelleType(cle) : cle}</td>
            <td className="p-2 text-right tabular-nums">{f.mesures}</td>
            <td className={`p-2 text-right font-semibold tabular-nums ${COULEUR_NIVEAU[f.niveau]}`}>{num(f.perte_pct)}</td>
            <td className="p-2 text-right tabular-nums">{num(f.latence_moy_ms)}</td>
            <td className="p-2 text-right tabular-nums">{num(f.debit_desc_mbps)}</td>
          </tr>))}</tbody>
      </table>
    </div>);
}

export default function SondeCommunauteSection() {
  const [jours, setJours] = useState(7);
  const [type, setType] = useState("");
  const [operateur, setOperateur] = useState("");
  const [data, setData] = useState(null);
  const [chargement, setChargement] = useState(false);
  const [modale, setModale] = useState(false);
  const [participants, setParticipants] = useState([]);

  // Relit la synthèse ; `avecToast` = vrai quand l'administrateur appuie sur « Actualiser » (règle 17 : toast « en cours » puis résultat)
  const charger = useCallback(async (avecToast) => {
    setChargement(true);
    if (avecToast) toast.info("Actualisation de l'espace commun en cours…");
    try {
      const r = await apiClient.get("/sonde-reseau/communaute", { params: { jours, type, operateur } });
      setData(r.data);
      if (avecToast) toast.success(`Espace commun relu : ${r.data.resume.mesures} mesure(s), ${r.data.lignes.length} ligne(s), ${r.data.participants} participant(s).`);
    } catch { if (avecToast) toast.error("Lecture de l'espace commun impossible"); }
    setChargement(false);
  }, [jours, type, operateur]);
  useEffect(() => { charger(false); }, [charger]);

  const lignes = data?.lignes || [];
  const { lignes: triees, tri, basculer } = useTri(lignes, {
    zone: (l) => nomZone(l), type: (l) => libelleType(l.type), operateur: (l) => l.operateur, mesures: (l) => l.mesures, perte: (l) => l.perte_pct,
    latence: (l) => l.latence_moy_ms, desc: (l) => l.debit_desc_mbps, mont: (l) => l.debit_mont_mbps, https: (l) => l.https_pct, jour: (l) => l.dernier_jour,
  });
  const total = lignes.reduce((s, l) => s + l.mesures, 0);                         // somme des lignes AFFICHÉES (jamais de somme sur un pourcentage : règle 25)

  const ouvrirParticipants = async () => {
    setModale(true);
    try { setParticipants((await apiClient.get("/sonde-reseau/communaute/participants")).data.participants || []); } catch { toast.error("Liste des participants indisponible"); }
  };
  const bloquer = async (p) => {
    toast.info(p.bloque ? "Déblocage en cours…" : "Blocage en cours…");
    try { await apiClient.post(`/sonde-reseau/communaute/participants/${p.id}/bloquer`, { bloque: !p.bloque }); toast.success(p.bloque ? "Participant débloqué." : "Participant bloqué."); await ouvrirParticipants(); } catch { toast.error("Action impossible"); }
  };
  const supprimer = async (p) => {
    if (!window.confirm(`Supprimer ${p.email} ? Sa fiche et ses appareils disparaissent (les cellules d'agrégation, anonymes, restent).`)) return;
    toast.info("Suppression en cours…");
    try { await apiClient.delete(`/sonde-reseau/communaute/participants/${p.id}`); toast.success("Participant supprimé."); await ouvrirParticipants(); await charger(false); } catch { toast.error("Suppression impossible"); }
  };

  const r = data?.resume;
  return (
    <div className="space-y-4" data-testid="sonde-communaute">
      <p className="text-sm text-slate-600">Les téléphones de l'application <b>Sonde Réseau</b> (compte Google obligatoire, consentement accepté à la première utilisation) envoient leurs mesures. Le lieu est une <b>zone de 2 km</b> (jamais une position précise) et SAWALI additionne les mesures sans les garder une à une.</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">Période<select value={jours} onChange={(e) => setJours(Number(e.target.value))} className="mt-1 block rounded border border-slate-300 p-2 text-sm" data-testid="communaute-periode">{PERIODES.map((p) => <option key={p.j} value={p.j}>{p.l}</option>)}</select></label>
        <label className="text-xs text-slate-600">Connexion<select value={type} onChange={(e) => setType(e.target.value)} className="mt-1 block rounded border border-slate-300 p-2 text-sm">{TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}</select></label>
        <label className="text-xs text-slate-600">Opérateur<select value={operateur} onChange={(e) => setOperateur(e.target.value)} className="mt-1 block rounded border border-slate-300 p-2 text-sm"><option value="">Tous les opérateurs</option>{(data?.operateurs || []).map((o) => <option key={o} value={o}>{o}</option>)}</select></label>
        <div className="boutons-distincts flex gap-2">
          <button type="button" onClick={() => charger(true)} disabled={chargement} className="inline-flex items-center gap-1 rounded bg-violet-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50" data-testid="communaute-actualiser"><RefreshCw className="h-4 w-4" aria-hidden="true" />Actualiser</button>
          <button type="button" onClick={ouvrirParticipants} className="inline-flex items-center gap-1 rounded bg-blue-700 px-3 py-2 text-sm font-medium text-white" data-testid="communaute-participants"><Users className="h-4 w-4" aria-hidden="true" />Participants{data ? ` (${data.participants})` : ""}</button>
        </div>
      </div>

      {r && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <Carte titre="Mesures" valeur={num(r.mesures, 0)} detail={`${data.participants} participant(s)`} />
          <Carte titre="Perte de paquets" valeur={`${num(r.perte_pct)} %`} detail={`${r.perdus} sur ${r.essais}`} niveau={r.niveau} />
          <Carte titre="Latence moyenne" valeur={`${num(r.latence_moy_ms)} ms`} />
          <Carte titre="Débit descendant" valeur={`${num(r.debit_desc_mbps)} Mb/s`} />
          <Carte titre="Débit montant" valeur={`${num(r.debit_mont_mbps)} Mb/s`} />
        </div>)}

      {data && <div className="grid gap-3 md:grid-cols-2"><TableauRepartition titre="Par type de connexion" donnees={data.par_type} libelle="Type" /><TableauRepartition titre="Par opérateur" donnees={data.par_operateur} libelle="Opérateur" /></div>}

      <div className="max-h-[32rem] overflow-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-xs" data-testid="communaute-tableau">
          <thead className="sticky top-0 bg-slate-100">
            <tr className="text-left">
              <ThTri cle="zone" tri={tri} onTri={basculer}>Lieu (zone de 2 km)</ThTri><ThTri cle="type" tri={tri} onTri={basculer}>Connexion</ThTri><ThTri cle="operateur" tri={tri} onTri={basculer}>Opérateur</ThTri>
              <ThTri cle="mesures" tri={tri} onTri={basculer} droite>Mesures</ThTri><ThTri cle="perte" tri={tri} onTri={basculer} droite>Perte %</ThTri><ThTri cle="latence" tri={tri} onTri={basculer} droite>Latence ms</ThTri>
              <ThTri cle="desc" tri={tri} onTri={basculer} droite>↓ Mb/s</ThTri><ThTri cle="mont" tri={tri} onTri={basculer} droite>↑ Mb/s</ThTri><ThTri cle="https" tri={tri} onTri={basculer} droite>HTTPS %</ThTri><ThTri cle="jour" tri={tri} onTri={basculer}>Dernier jour</ThTri>
            </tr>
          </thead>
          <tbody>
            {triees.map((l) => (
              <tr key={`${l.zone}-${l.type}-${l.operateur}`} className="border-t border-slate-100 hover:bg-sky-400/15">
                <td className="p-2">{l.lat == null ? <span className="text-slate-500">{nomZone(l)}</span> : <a href={lienCarte(l)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-blue-800 underline"><MapPin className="h-3.5 w-3.5" aria-hidden="true" />{nomZone(l)}</a>}</td>
                <td className="p-2">{libelleType(l.type)}</td><td className="p-2">{l.operateur}</td>
                <td className="p-2 text-right tabular-nums">{l.mesures}</td>
                <td className={`p-2 text-right font-semibold tabular-nums ${COULEUR_NIVEAU[l.niveau]}`}>{num(l.perte_pct)}</td>
                <td className="p-2 text-right tabular-nums">{num(l.latence_moy_ms)}</td><td className="p-2 text-right tabular-nums text-emerald-700">{num(l.debit_desc_mbps)}</td>
                <td className="p-2 text-right tabular-nums">{num(l.debit_mont_mbps)}</td><td className="p-2 text-right tabular-nums">{num(l.https_pct)}</td><td className="p-2">{jourFr(l.dernier_jour)}</td>
              </tr>))}
            {!lignes.length && <tr><td colSpan={10} className="p-4 text-center text-slate-500">{chargement ? "Chargement…" : "Aucune mesure sur cette période : elles arrivent dès qu'un téléphone connecté en envoie."}</td></tr>}
          </tbody>
          {lignes.length > 0 && <tfoot className="sticky bottom-0 bg-slate-200"><tr className="font-semibold"><td className="p-2">{lignes.length} ligne(s)</td><td /><td /><td className="p-2 text-right tabular-nums">{total}</td><td colSpan={6} /></tr></tfoot>}
        </table>
      </div>

      <Dialog open={modale} onOpenChange={setModale}>
        <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="communaute-modale">
          <DialogHeader><DialogTitle>Participants de la sonde ({participants.length})</DialogTitle></DialogHeader>
          <p className="text-xs text-slate-500">Données personnelles : visibles de l'administrateur seul. Supprimer un participant efface sa fiche (e-mail, consentement, appareils) ; ses mesures, déjà additionnées sans identité, restent dans la synthèse.</p>
          <div className="space-y-2">
            {participants.map((p) => (
              <div key={p.id} className="rounded border border-slate-200 p-2 text-xs">
                <p className="font-semibold text-blue-800">{p.email} {p.bloque && <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-700">bloqué</span>}</p>
                <p className="text-slate-600">{p.nom} · {p.appareils} appareil(s) · {p.mesures} mesure(s) · dernière : {quand(p.derniere)} · accord version {p.consentement?.version ?? "—"} le {quand(p.consentement?.le)}</p>
                <div className="boutons-distincts mt-1 flex gap-2">
                  <button type="button" onClick={() => bloquer(p)} className="inline-flex items-center gap-1 rounded bg-orange-600 px-2 py-1 text-white"><Ban className="h-3.5 w-3.5" aria-hidden="true" />{p.bloque ? "Débloquer" : "Bloquer"}</button>
                  <button type="button" onClick={() => supprimer(p)} className="inline-flex items-center gap-1 rounded bg-red-700 px-2 py-1 text-white"><Trash2 className="h-3.5 w-3.5" aria-hidden="true" />Supprimer</button>
                </div>
              </div>))}
            {!participants.length && <p className="text-sm text-slate-500">Aucun participant pour l'instant.</p>}
          </div>
        </DialogContent>
      </Dialog>
    </div>);
}
