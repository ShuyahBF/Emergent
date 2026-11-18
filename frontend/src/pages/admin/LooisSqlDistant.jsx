// LooisSqlDistant.jsx — Lot 446 : page « Plateformes → Loois → SQL Distant » (administrateur, utilisable sur téléphone).
//
// Demande du propriétaire (18/11/2026) : version Android du module de requêtes HFSQL distantes. Option retenue : une PAGE de l'administration
// SAWALI, ouverte dans le navigateur du téléphone (puis, plus tard, dans une application hybride avec verrou par empreinte).
//
// En résumé (pour un développeur WinDev) :
//   1. l'administrateur se connecte à SAWALI (code à usage unique) : son compte remplace la clé « SQL à distance » — AUCUNE clé n'est gardée sur le téléphone ;
//   2. il choisit un client (liste des clients dont le service Windows Loois est vu), tape sa requête (SELECT / INSERT / UPDATE / DELETE) ;
//   3. SAWALI la dépose ; UNE SEULE machine du client l'exécute ; l'écran suit l'avancement (attente → prise → terminée) et affiche le résultat
//      avec le NOM de la machine qui a répondu ;
//   4. toute MODIFICATION (INSERT / UPDATE / DELETE) passe par une confirmation renforcée : fenêtre avec rappel du client et de la requête,
//      et saisie du mot « MODIFIER » (un doigt qui glisse ne suffit pas).
// Routes : /api/admin/loois-sql/{clients, requetes, requetes/{id}} (backend/routes/loois_sql_distant.py).
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Clock, History, Play, RefreshCw, Server, ShieldCheck, X, XCircle } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const BASE = "/admin/loois-sql";
const MOT_CONFIRMATION = "MODIFIER";
const ETATS_FINAUX = ["terminee", "echec", "expiree", "sans_reponse"];

// Libellé, couleur et pictogramme de chaque état (règle 16 : jamais la couleur seule)
const ETATS = {
  attente: { texte: "En attente d'une machine", classe: "text-amber-700 bg-amber-50", Icone: Clock },
  prise: { texte: "Prise par une machine", classe: "text-sky-700 bg-sky-50", Icone: Server },
  terminee: { texte: "Terminée", classe: "text-emerald-700 bg-emerald-50", Icone: CheckCircle2 },
  echec: { texte: "Échec", classe: "text-red-700 bg-red-50", Icone: XCircle },
  expiree: { texte: "Expirée (non exécutée)", classe: "text-orange-700 bg-orange-50", Icone: AlertTriangle },
  sans_reponse: { texte: "Sans réponse de la machine", classe: "text-orange-700 bg-orange-50", Icone: AlertTriangle },
};

// Nature de la requête d'après son premier mot (même règle que le serveur : le contrôle réel est refait côté serveur)
const natureSql = (sql) => (/^\s*select\b/i.test(sql || "") ? "SELECT" : "MODIF");

// Date ISO → « JJ/MM/AAAA HH:MM:SS » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "short", timeStyle: "medium" });
};

// Pastille d'état (couleur + pictogramme + texte)
function PastilleEtat({ etat }) {
  const e = ETATS[etat] || { texte: etat || "—", classe: "text-slate-700 bg-slate-100", Icone: Clock };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${e.classe}`}>
      <e.Icone className="h-3.5 w-3.5" aria-hidden="true" />{e.texte}
    </span>
  );
}

// Tableau d'un résultat (colonnes triables, règle 19 ; défilement dans le cadre au-delà de 30 lignes, règle 24 : géré globalement)
function TableauResultat({ colonnes, lignes }) {
  const objets = useMemo(() => lignes.map((l) => Object.fromEntries(colonnes.map((c, i) => [c, l[i]]))), [colonnes, lignes]);
  const acces = useMemo(() => Object.fromEntries(colonnes.map((c) => [c, (o) => {
    const n = Number(o[c]);
    return o[c] !== "" && o[c] !== null && !Number.isNaN(n) && /^-?\d+([.,]\d+)?$/.test(String(o[c]).trim()) ? n : o[c];
  }])), [colonnes]);
  const { lignes: triees, tri, basculer } = useTri(objets, acces);
  if (!colonnes.length) return null;
  return (
    <div className="overflow-x-auto rounded border border-slate-200">
      <table className="min-w-full text-sm" data-testid="resultat-sql">
        <thead className="bg-sky-50 text-sky-900">
          <tr>{colonnes.map((c) => <ThTri key={c} cle={c} tri={tri} onTri={basculer} className="text-left whitespace-nowrap">{c}</ThTri>)}</tr>
        </thead>
        <tbody>
          {triees.map((o, i) => (
            <tr key={i} className="border-t border-slate-100">
              {colonnes.map((c) => <td key={c} className="p-2 whitespace-nowrap">{String(o[c] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Résultat complet d'une requête (utilisé sous le formulaire et dans la fenêtre de détail de l'historique)
function VueResultat({ r }) {
  if (!r) return null;
  return (
    <div className="space-y-2" data-testid="vue-resultat">
      <div className="flex flex-wrap items-center gap-2">
        <PastilleEtat etat={r.etat} />
        {r.machine && <span className="text-sm text-slate-700"><Server className="mr-1 inline h-4 w-4 text-sky-600" aria-hidden="true" />Machine : <b className="text-sky-800">{r.machine}</b>{r.machine_ip ? ` (${r.machine_ip})` : ""}</span>}
        {r.base && <span className="text-sm text-slate-700">Base : <b className="text-violet-700">{r.base}</b></span>}
        {r.duree_ms ? <span className="text-xs text-slate-500">{r.duree_ms} ms</span> : null}
      </div>
      {r.message && <p className={`text-sm ${r.ok === false ? "text-red-700" : "text-slate-700"}`}>{r.message}</p>}
      {r.tronque && <p className="text-xs text-orange-700"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" aria-hidden="true" />Résultat tronqué (200 lignes au plus).</p>}
      {r.lignes_affectees > 0 && <p className="text-sm text-emerald-700">Lignes affectées : <b>{r.lignes_affectees}</b></p>}
      <TableauResultat colonnes={r.colonnes || []} lignes={r.lignes || []} />
    </div>
  );
}

export default function LooisSqlDistant() {
  const [clients, setClients] = useState([]);
  const [client, setClient] = useState("");
  const [sql, setSql] = useState("");
  const [courante, setCourante] = useState(null);           // requête suivie (dernier résultat)
  const [historique, setHistorique] = useState([]);
  const [detail, setDetail] = useState(null);               // requête ouverte dans la fenêtre de détail
  const [confirmation, setConfirmation] = useState(false);  // fenêtre de confirmation renforcée
  const [motSaisi, setMotSaisi] = useState("");
  const [enCours, setEnCours] = useState(false);
  const minuteur = useRef(null);

  // Lecture des clients et de l'historique (bouton « Actualiser » : toast « en cours » puis résultat, règle 17)
  const charger = useCallback(async (avecToast = false) => {
    const t = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const [c, h] = await Promise.all([apiClient.get(`${BASE}/clients`), apiClient.get(`${BASE}/requetes`)]);
      setClients(c.data.clients || []);
      setHistorique(h.data.requetes || []);
      if (t) toast.success(`Actualisé : ${(c.data.clients || []).length} client(s), ${(h.data.requetes || []).length} requête(s) récente(s).`, { id: t });
    } catch (e) {
      const msg = e?.response?.data?.detail || "Lecture impossible.";
      if (t) toast.error(msg, { id: t }); else toast.error(msg);
    }
  }, []);
  useEffect(() => { charger(); return () => clearTimeout(minuteur.current); }, [charger]);

  // Suivi d'une requête déposée : on relit son état toutes les 2 secondes jusqu'à un état final (abandonné si l'écran se ferme)
  const suivre = useCallback((id) => {
    clearTimeout(minuteur.current);
    const tour = async () => {
      try {
        const r = (await apiClient.get(`${BASE}/requetes/${id}`)).data;
        setCourante(r);
        if (ETATS_FINAUX.includes(r.etat)) {
          setEnCours(false);
          charger();
          if (r.etat === "terminee") toast.success(`Terminée par ${r.machine || "une machine"}.`);
          else toast.error(ETATS[r.etat]?.texte || "Requête non terminée.");
          return;
        }
      } catch (e) {
        setEnCours(false);
        toast.error(e?.response?.data?.detail || "Suivi impossible.");
        return;
      }
      minuteur.current = setTimeout(tour, 2000);
    };
    tour();
  }, [charger]);

  // Dépôt de la requête (la confirmation renforcée est transmise pour une modification)
  const deposer = async (confirmeModification) => {
    setEnCours(true);
    setCourante(null);
    const t = toast.loading("Patientez… requête envoyée au client.");
    try {
      const r = (await apiClient.post(`${BASE}/requetes`, { client, sql, confirme_modification: confirmeModification })).data;
      toast.success("Requête déposée : une machine du client va la prendre.", { id: t });
      setCourante(r);
      suivre(r.id);
    } catch (e) {
      setEnCours(false);
      toast.error(e?.response?.data?.detail || "Envoi impossible.", { id: t });
    }
  };

  // Clic sur « Exécuter » : une lecture part tout de suite, une modification demande d'abord la confirmation renforcée
  const executer = () => {
    if (!client) return toast.error("Choisissez d'abord le client.");
    if (!sql.trim()) return toast.error("Saisissez la requête SQL.");
    if (natureSql(sql) === "MODIF") { setMotSaisi(""); setConfirmation(true); return; }
    deposer(false);
  };

  // Ouvre le détail d'une requête de l'historique (avec ses lignes) dans une fenêtre modale (règle 20)
  const ouvrirDetail = async (id) => {
    try { setDetail((await apiClient.get(`${BASE}/requetes/${id}`)).data); }
    catch (e) { toast.error(e?.response?.data?.detail || "Détail introuvable."); }
  };

  const { lignes: histoTrie, tri, basculer } = useTri(historique, {
    cree_le: (r) => r.cree_le, client: (r) => r.client, etat: (r) => r.etat, machine: (r) => r.machine, sql: (r) => r.sql,
  });
  const clientChoisi = clients.find((c) => c.code === client);

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-3 sm:p-6" data-testid="page-sql-distant">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">🧾 SQL Distant — Bases HFSQL Des Clients</h1>
          <p className="text-sm text-slate-600">
            <ShieldCheck className="mr-1 inline h-4 w-4 text-emerald-600" aria-hidden="true" />
            Connecté avec votre compte SAWALI : aucune clé n'est gardée sur cet appareil. Une seule machine du client exécute la requête.
          </p>
        </div>
        <button type="button" onClick={() => charger(true)} className="inline-flex items-center gap-1 rounded border border-sky-400 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-800">
          <RefreshCw className="h-4 w-4" aria-hidden="true" />Actualiser
        </button>
      </div>

      {/* Formulaire : client (liste déroulante, règle 10) + requête + bouton d'action principal */}
      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-3 sm:p-4">
        <label className="block text-sm font-medium text-slate-800">
          Client
          <select value={client} onChange={(e) => setClient(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 p-2 text-base" data-testid="choix-client">
            <option value="">— Choisir le client —</option>
            {clients.map((c) => <option key={c.code} value={c.code}>{c.code} · {c.en_ligne ? "en ligne" : "hors ligne"} · {c.machines.length} machine(s)</option>)}
          </select>
        </label>
        {clientChoisi && !clientChoisi.en_ligne && (
          <p className="text-sm text-orange-700"><AlertTriangle className="mr-1 inline h-4 w-4" aria-hidden="true" />Aucune machine de ce client n'a donné signe de vie depuis 12 minutes : la requête risque d'expirer sans être exécutée.</p>
        )}
        <label className="block text-sm font-medium text-slate-800">
          Requête SQL (SELECT, INSERT, UPDATE ou DELETE — UPDATE et DELETE avec WHERE)
          <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={5} spellCheck={false} placeholder="SELECT * FROM VenteClinique WHERE NumFacture = 'F001'"
                    className="mt-1 block w-full rounded border border-slate-300 p-2 font-mono text-sm" data-testid="saisie-sql" />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={executer} disabled={enCours} data-testid="bouton-executer"
                  className="inline-flex items-center gap-2 rounded bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
            {enCours ? <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" /> : <Play className="h-4 w-4" aria-hidden="true" />}
            Exécuter chez le client
          </button>
          {sql.trim() && natureSql(sql) === "MODIF" && <span className="text-sm text-red-700"><AlertTriangle className="mr-1 inline h-4 w-4" aria-hidden="true" />Modification de données : confirmation renforcée demandée.</span>}
        </div>
      </section>

      {courante && <section className="rounded-lg border border-slate-200 bg-white p-3 sm:p-4"><VueResultat r={courante} /></section>}

      {/* Historique : colonnes triables ; le détail s'ouvre dans une fenêtre modale */}
      <section className="rounded-lg border border-slate-200 bg-white p-3 sm:p-4">
        <h2 className="mb-2 flex items-center gap-2 font-semibold text-slate-900"><History className="h-4 w-4 text-violet-600" aria-hidden="true" />Dernières requêtes</h2>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm" data-testid="historique-sql">
            <thead className="bg-slate-50">
              <tr>
                <ThTri cle="cree_le" tri={tri} onTri={basculer} className="text-left">Date</ThTri>
                <ThTri cle="client" tri={tri} onTri={basculer} className="text-left">Client</ThTri>
                <ThTri cle="etat" tri={tri} onTri={basculer} className="text-left">État</ThTri>
                <ThTri cle="machine" tri={tri} onTri={basculer} className="text-left">Machine</ThTri>
                <ThTri cle="sql" tri={tri} onTri={basculer} className="text-left">Requête</ThTri>
                <th className="p-2" />
              </tr>
            </thead>
            <tbody>
              {histoTrie.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-sky-400/15">
                  <td className="whitespace-nowrap p-2">{dateHeure(r.cree_le)}</td>
                  <td className="p-2 font-semibold text-sky-800">{r.client}</td>
                  <td className="p-2"><PastilleEtat etat={r.etat} /></td>
                  <td className="p-2">{r.machine || "—"}</td>
                  <td className="max-w-[16rem] truncate p-2 font-mono text-xs" title={r.sql}>{r.sql}</td>
                  <td className="p-2">
                    <button type="button" onClick={() => ouvrirDetail(r.id)} title="Voir le détail" aria-label="Voir le détail de la requête"
                            className="inline-flex items-center gap-1 rounded border border-violet-400 bg-violet-50 px-2 py-1 text-xs font-medium text-violet-800">
                      <Server className="h-3.5 w-3.5" aria-hidden="true" />Détail
                    </button>
                  </td>
                </tr>
              ))}
              {!histoTrie.length && <tr><td colSpan={6} className="p-3 text-center text-slate-500">Aucune requête récente.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      {/* Fenêtre de détail d'une requête (règle 20) */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Requête {detail?.id} · {detail?.client}</DialogTitle>
            <DialogDescription>Déposée le {dateHeure(detail?.cree_le)}</DialogDescription>
          </DialogHeader>
          <pre className="whitespace-pre-wrap rounded bg-slate-50 p-2 font-mono text-xs">{detail?.sql}</pre>
          <VueResultat r={detail} />
          <button type="button" onClick={() => setDetail(null)} className="inline-flex items-center gap-1 self-end rounded border border-slate-400 px-3 py-2 text-sm"><X className="h-4 w-4" aria-hidden="true" />Fermer</button>
        </DialogContent>
      </Dialog>

      {/* Confirmation renforcée d'une MODIFICATION : rappel du client et de la requête, puis saisie du mot « MODIFIER » */}
      <Dialog open={confirmation} onOpenChange={setConfirmation}>
        <DialogContent className="max-h-[85dvh] max-w-md overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-red-700"><AlertTriangle className="mr-1 inline h-5 w-5" aria-hidden="true" />Confirmer la modification</DialogTitle>
            <DialogDescription>Cette requête va MODIFIER les données du client <b>{client}</b>. Elle ne sera exécutée qu'une seule fois, par une seule machine.</DialogDescription>
          </DialogHeader>
          <pre className="whitespace-pre-wrap rounded bg-red-50 p-2 font-mono text-xs text-red-900">{sql}</pre>
          <label className="block text-sm font-medium">
            Pour confirmer, saisissez le mot <b>{MOT_CONFIRMATION}</b>
            <input value={motSaisi} onChange={(e) => setMotSaisi(e.target.value)} autoComplete="off" autoCapitalize="characters" data-testid="mot-confirmation"
                   className="mt-1 block w-full rounded border border-slate-300 p-2 text-base" />
          </label>
          <div className="boutons-distincts flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => setConfirmation(false)} className="inline-flex items-center gap-1 rounded border border-slate-400 px-3 py-2 text-sm"><X className="h-4 w-4" aria-hidden="true" />Annuler</button>
            <button type="button" disabled={motSaisi.trim().toUpperCase() !== MOT_CONFIRMATION} data-testid="bouton-confirmer"
                    onClick={() => { setConfirmation(false); deposer(true); }}
                    className="inline-flex items-center gap-1 rounded bg-red-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />Modifier les données</button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
