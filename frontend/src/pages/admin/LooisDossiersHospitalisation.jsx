// LooisDossiersHospitalisation.jsx — Lot 448 : page web « Loois SQL distant → Dossiers d'hospitalisation » (administrateur, téléphone compris).
//
// Même liste que l'écran Loois « Gestion des dossiers d'hospitalisation », lue CHEZ LE CLIENT par le canal « SQL Distant » (lot 446) :
// SAWALI dépose une requête, UNE machine du client (service Windows Loois) l'exécute sur HFSQL et renvoie le résultat. LECTURE SEULE (SELECT).
// Méthode validée le 18/11/2026 sur IPM (chaque requête ~0,4 s) : dernier numéro (MAX), puis fenêtres de 200 numéros du plus récent au plus ancien,
// puis noms des patients par paquets. Toute la logique de requêtes est dans lib/dossiersHospitalisation.js (testée).
//
// Sécurité (règle 21) : accès réservé au compte ADMINISTRATEUR (routes /admin/loois-sql) ; lectures « éphémères » (SAWALI efface les lignes après
// la première lecture : aucune donnée de patient n'est gardée dans la base SAWALI) ; rien n'est écrit chez le client.
// Retour du propriétaire (18/11/2026) : un clic ne relance JAMAIS une lecture en cours, et l'attente se VOIT (durée, avancement, bouton renommé).
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Banknote, CheckCircle2, Eye, Loader2, RefreshCw, Search, Server, Stethoscope, XCircle } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  BUDGET_MS, FENETRES_MAX, PAQUET_PATIENTS, PAQUETS_MAX, PERIODES, PERIODE_DEFAUT, dansLaPeriode, dateFr, dureeMmSs, fenetre, jourIso, libellePatient, lireDossier,
  JOINTURE_ACTIVE, lireNoms, lireNomsJointure, periodeDepassee, plusRecentsDabord, prendrePaquet, sqlFenetre, sqlFenetreJointure, sqlFenetreToutes, sqlMax, sqlPatients, TAILLE_FENETRE,
} from "@/lib/dossiersHospitalisation";

const BASE = "/admin/loois-sql";
const ETATS_FINAUX = ["terminee", "echec", "expiree", "sans_reponse"];
const ATTENTE_REPONSE_MS = 60000;            // une requête sans réponse de la machine du client au bout de 1 minute : lecture arrêtée avec un message clair
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

/** Erreur « lecture annulée par l'utilisateur » (jamais montrée comme un échec). */
class Annulation extends Error {}

export default function LooisDossiersHospitalisation() {
  const [clients, setClients] = useState([]);
  const [client, setClient] = useState("");
  const [periode, setPeriode] = useState(PERIODE_DEFAUT);        // 7 jours au départ (usage courant) ; 30, 60 ou 90 jours à de rares occasions
  const [recherche, setRecherche] = useState("");
  const [dossiers, setDossiers] = useState([]);
  const [noms, setNoms] = useState({});
  const [interroges, setInterroges] = useState(() => new Set());   // codes de patients dont le nom a été DEMANDÉ au client (trouvé ou non) : « nom non trouvé » seulement pour ceux-là
  const [arretee, setArretee] = useState(false);                   // lecture des dossiers arrêtée par l'utilisateur (liste incomplète voulue)
  const [dernier, setDernier] = useState(0);
  const [enCours, setEnCours] = useState(false);
  const [secondes, setSecondes] = useState(0);
  const [avancement, setAvancement] = useState("");
  const [partielle, setPartielle] = useState(false);
  const [erreur, setErreur] = useState("");
  const [machine, setMachine] = useState("");
  const [base, setBase] = useState("");
  const [detail, setDetail] = useState(null);
  const enCoursRef = useRef(false);            // garde : une seule lecture à la fois (posée AVANT de lancer, lue par tous les clics)
  const annulerRef = useRef(false);            // arrêt TOTAL (2e appui sur « Arrêter » ou fermeture de la page)
  const arretDossiersRef = useRef(false);      // 1er appui sur « Arrêter » : on arrête les dossiers mais on lit quand même les noms des patients des dossiers déjà lus
  const phaseRef = useRef("dossiers");         // « dossiers » puis « noms »
  const debutRef = useRef(0);

  // Clients dont un service Loois a donné signe de vie
  const chargerClients = useCallback(async () => {
    try {
      const c = (await apiClient.get(`${BASE}/clients`)).data.clients || [];
      setClients(c);
      setClient((actuel) => actuel || (c.find((x) => x.en_ligne)?.code ?? c[0]?.code ?? ""));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Liste des clients illisible.");
    }
  }, []);
  useEffect(() => { chargerClients(); return () => { annulerRef.current = true; }; }, [chargerClients]);

  // Durée écoulée affichée chaque seconde pendant une lecture (on voit que SAWALI travaille)
  useEffect(() => {
    if (!enCours) return undefined;
    const t = setInterval(() => setSecondes(Math.floor((Date.now() - debutRef.current) / 1000)), 1000);
    return () => clearInterval(t);
  }, [enCours]);

  // Envoie UNE requête SELECT au client et attend son résultat (suivi toutes les 0,7 s) ; lève une erreur claire en cas de refus ou de silence
  const executer = async (clientLu, sql) => {
    const depot = (await apiClient.post(`${BASE}/requetes`, { client: clientLu, sql, ephemere: true })).data;
    const attenteDebut = Date.now();
    for (;;) {
      if (annulerRef.current) throw new Annulation();
      await pause(700);
      const r = (await apiClient.get(`${BASE}/requetes/${depot.id}`)).data;
      if (ETATS_FINAUX.includes(r.etat)) {
        if (r.etat !== "terminee" || r.ok === false) {
          throw new Error(`${r.message || "La machine du client n'a pas pu exécuter la requête."} (requête : ${sql})`);
        }
        if (r.machine) setMachine(r.machine);
        if (r.base) setBase(r.base);
        return r;
      }
      if (Date.now() - attenteDebut > ATTENTE_REPONSE_MS) throw new Error(`Aucune machine du client ${clientLu} n'a répondu en 1 minute (requête : ${sql}).`);
    }
  };

  // Lecture complète : dernier numéro → fenêtres de dossiers → noms des patients
  const lire = async () => {
    if (!client) { toast.error("Choisissez d'abord le client."); return; }
    // Une lecture est déjà en cours : on NE relance PAS une deuxième lecture (clics répétés), on le dit clairement
    if (enCoursRef.current) { toast.info(`Lecture déjà en cours… patientez (${BUDGET_MS / 60000} minutes au plus).`); return; }
    enCoursRef.current = true; annulerRef.current = false; arretDossiersRef.current = false; phaseRef.current = "dossiers";
    setArretee(false); setInterroges(new Set());
    debutRef.current = Date.now();
    setEnCours(true); setSecondes(0); setErreur(""); setPartielle(false); setDossiers([]); setNoms({}); setMachine(""); setBase("");
    setAvancement("Interrogation du serveur du client…");
    const toastId = toast.loading("Patientez… lecture des dossiers chez le client.");
    const clientLu = client;
    const jours = PERIODES.find((p) => p.code === periode)?.jours ?? 30;
    const debutIso = jourIso(new Date(), jours);
    const finIso = jourIso(new Date(), 0);
    let cumul = [];
    let termine = false;
    let retenus = [];
    let toutesColonnes = false;          // repli : lecture avec toutes les colonnes si le nom exact d'une colonne est refusé
    let modeJointure = JOINTURE_ACTIVE;  // dossiers ET noms en UNE requête (jointure) : désactivée (le pilote HFSQL ne gère pas les jointures) ; sinon repli sur « dossiers puis noms » si HFSQL la refuse
    // ---- Noms des patients EN PARALLÈLE des dossiers (retour du propriétaire, 18/11/2026) : la lecture des dossiers dépose les codes de patients dans une FILE
    // (les plus récents d'abord) ; ce travail les prend par paquets de 150 pendant que les dossiers continuent d'être lus, et affiche chaque nom dès qu'il arrive.
    // Chez un client à UNE seule machine les requêtes passent l'une après l'autre (le temps total est le même) mais les noms apparaissent tout de suite ;
    // avec plusieurs machines les deux lectures avancent vraiment en même temps.
    const file = [];                     // codes de patients à interroger
    const mis = new Set();               // codes déjà mis en file (jamais deux fois)
    let dossiersFinis = false;           // vrai quand plus aucun dossier ne sera lu : le travail vide alors la file et s'arrête
    let arretTravail = false;            // vrai quand la lecture est terminée ou en erreur
    let nomsLus = {};
    const travailNoms = async () => {
      let faits = 0;
      while (!arretTravail && faits < PAQUETS_MAX) {
        if (annulerRef.current) throw new Annulation();
        const paquet = prendrePaquet(file, PAQUET_PATIENTS, dossiersFinis);
        if (paquet === null) { if (dossiersFinis) break; await pause(250); continue; }
        const sql = sqlPatients(paquet);
        if (!sql) continue;
        try {
          const r = await executer(clientLu, sql);
          nomsLus = { ...nomsLus, ...lireNoms(r.lignes, r.colonnes) };
          setNoms(nomsLus);
          setInterroges((s) => new Set([...s, ...paquet]));                                       // ces codes ont été demandés : sans nom = vraiment introuvables
          faits++;
        } catch (e) {
          if (e instanceof Annulation) throw e;
          toast.warning("Noms des patients indisponibles : les codes sont affichés à la place.");  // la liste reste affichée, les codes aussi
          break;
        }
      }
    };
    let tacheNoms = Promise.resolve();
    try {
      // 1. Dernier numéro de dossier
      const rMax = await executer(clientLu, sqlMax());
      let haut = Number.parseInt(rMax.lignes?.[0]?.[0], 10);
      if (!Number.isInteger(haut) || haut <= 0) throw new Error("Dernier numéro de dossier illisible dans la réponse du client.");
      setDernier(haut);
      tacheNoms = travailNoms().catch((e) => ({ erreur: e }));          // démarre EN PARALLÈLE : il attend que la file se remplisse
      // 2. Fenêtres de 200 numéros, du plus récent au plus ancien ; on s'arrête dès que la période est dépassée
      for (let n = 0; n < FENETRES_MAX && haut > 0; n++) {
        if (Date.now() - debutRef.current > BUDGET_MS) break;                                   // limite de temps : lecture partielle
        if (arretDossiersRef.current) { setArretee(true); break; }                              // arrêt demandé : on garde ce qui est lu et on passe aux noms
        const { bas, haut: h } = fenetre(haut);
        setAvancement(`Dossiers n° ${bas} à ${h} (tranche ${n + 1} sur ${FENETRES_MAX} au plus) · noms de patients lus : ${Object.keys(nomsLus).length}…`);
        let r;
        let nomsJoints = null;
        if (modeJointure) {
          // Chaque base est complète et autonome (propriétaire, 18/11/2026) : dossiers et patients sont dans la même base, une jointure donne les deux en une requête
          try {
            r = await executer(clientLu, sqlFenetreJointure(bas, h));
            nomsJoints = lireNomsJointure(r.lignes, r.colonnes);
            if (nomsJoints === null) throw new Error("Résultat de la jointure sans colonnes Nom / Prénoms.");
          } catch (e) {
            if (e instanceof Annulation || n > 0) throw e;                    // le repli ne sert qu'à la PREMIÈRE tranche
            modeJointure = false; r = undefined; nomsJoints = null;
            toast.info("Jointure dossiers + patients non acceptée : lecture en deux temps (dossiers puis noms).");
          }
        }
        if (!modeJointure) {
          try {
            r = await executer(clientLu, toutesColonnes ? sqlFenetreToutes(bas, h) : sqlFenetre(bas, h));
          } catch (e) {
            if (e instanceof Annulation || toutesColonnes || n > 0) throw e;   // le repli ne sert qu'à la PREMIÈRE tranche
            toutesColonnes = true;
            toast.warning("Une colonne a été refusée : lecture avec toutes les colonnes.");
            r = await executer(clientLu, sqlFenetreToutes(bas, h));
          }
        }
        if (r.tronque && r.lignes.length < TAILLE_FENETRE) throw new Error("Résultat trop volumineux pour une réponse distante : réduisez la période.");
        const lus = r.lignes.map((l) => lireDossier(l, r.colonnes)).filter(Boolean);
        cumul = cumul.concat(lus);
        retenus = dansLaPeriode(cumul, debutIso, finIso);
        setDossiers(plusRecentsDabord(retenus));                                                // on affiche d'abord ce qui est prêt (règle 7), du plus récent au plus ancien
        if (modeJointure && nomsJoints) {
          // Jointure : les noms de cette tranche sont déjà là ; les codes de la tranche sont « interrogés » (sans nom = patient vraiment introuvable)
          nomsLus = { ...nomsLus, ...nomsJoints }; setNoms(nomsLus);
          setInterroges((s) => new Set([...s, ...lus.map((d) => d.codePatient).filter(Boolean)]));
        } else {
          for (const d of dansLaPeriode(lus, debutIso, finIso)) {                                // deux temps : les patients de cette tranche rejoignent la file des noms
            if (d.codePatient && !mis.has(d.codePatient)) { mis.add(d.codePatient); file.push(d.codePatient); }
          }
        }
        haut = bas - 1;
        if (periodeDepassee(lus, debutIso) || haut <= 0) { termine = true; break; }
      }
      setPartielle(!termine);
      phaseRef.current = "noms";
      if (arretDossiersRef.current) toast.loading(`Lecture des dossiers arrêtée (${retenus.length} lus) : noms des patients en cours…`, { id: toastId });
      // 3. Fin des noms : les dossiers sont tous lus, le travail des noms vide ce qui reste dans la file (un échec n'empêche pas d'afficher la liste : le code reste visible)
      dossiersFinis = true;
      setAvancement(`Noms des patients : fin de la lecture (${file.length} code(s) restants)…`);
      const suite = await tacheNoms;
      if (suite?.erreur) throw suite.erreur;
      const s = Math.floor((Date.now() - debutRef.current) / 1000);
      toast.success(`${retenus.length} dossier(s) lus chez ${clientLu} en ${dureeMmSs(s)}${termine ? "." : arretDossiersRef.current ? " — lecture arrêtée : liste incomplète." : " — lecture PARTIELLE (limite de temps ou de tranches atteinte) : réduisez la période."}`, { id: toastId });
    } catch (e) {
      if (e instanceof Annulation) { toast.info("Lecture arrêtée.", { id: toastId }); }
      else {
        const msg = e?.response?.data?.detail || e?.message || "Lecture impossible.";
        setErreur(msg);
        toast.error(msg, { id: toastId });
      }
    } finally {
      arretTravail = true;                         // le travail des noms s'arrête (erreur, arrêt ou fin)
      enCoursRef.current = false;
      setEnCours(false);
      setAvancement("");
    }
  };

  // Recherche (numéro, libellé ou patient) dans les dossiers déjà lus
  const filtres = useMemo(() => {
    const t = recherche.trim().toLowerCase();
    if (!t) return dossiers;
    return dossiers.filter((d) => String(d.numero).includes(t) || d.libelle.toLowerCase().includes(t) || libellePatient(d, noms).toLowerCase().includes(t));
  }, [dossiers, noms, recherche]);

  // Tri de TOUTES les colonnes (règle 19) ; ordre d'origine = du plus récent au plus ancien
  const { lignes: triees, tri, basculer } = useTri(filtres, {
    numero: (d) => d.numero, libelle: (d) => d.libelle, date: (d) => (d.date ? `${d.date} ${d.heure}` : ""), patient: (d) => libellePatient(d, noms),
  });

  const periodeLibelle = PERIODES.find((p) => p.code === periode)?.libelle;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-3 sm:p-6" data-testid="dossiers-hospitalisation">
      <h1 className="flex items-center gap-2 text-xl font-bold text-slate-900">
        <Stethoscope className="h-6 w-6 text-sky-700" aria-hidden="true" />Dossiers d'hospitalisation
      </h1>
      <p className="text-sm text-slate-600">
        Liste lue <b>chez le client</b> (lecture seule) : SAWALI demande à une machine du client, qui lit le fichier « DOSSIER EXAMEN ».
        Les données de patients ne sont <b>pas conservées</b> dans SAWALI.
      </p>

      {/* Choix du client et de la période, lecture */}
      <div className="grid gap-3 rounded border border-slate-200 bg-white p-3 sm:grid-cols-[1fr_1fr_auto]">
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-slate-700">Client</span>
          <select value={client} onChange={(e) => setClient(e.target.value)} disabled={enCours} className="w-full rounded border border-slate-300 p-2" data-testid="choix-client">
            <option value="">— Choisir —</option>
            {clients.map((c) => <option key={c.code} value={c.code}>{c.code}{c.en_ligne ? " · en ligne" : " · hors ligne"}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-semibold text-slate-700">Période</span>
          <select value={periode} onChange={(e) => setPeriode(e.target.value)} disabled={enCours} className="w-full rounded border border-slate-300 p-2" data-testid="choix-periode">
            {PERIODES.map((p) => <option key={p.code} value={p.code}>{p.libelle}</option>)}
          </select>
        </label>
        <div className="flex items-end gap-2">
          {/* Bouton grisé et renommé pendant la lecture : plus de clics répétés, et l'on voit que SAWALI travaille */}
          <button type="button" onClick={lire} disabled={enCours || !client} data-testid="afficher"
                  className="inline-flex items-center gap-2 rounded bg-sky-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
            {enCours ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
            {enCours ? "En cours…" : dossiers.length ? "Actualiser" : "Afficher"}
          </button>
          {enCours && (
            <button type="button" data-testid="arreter"
                    onClick={() => {
                      // 1er appui : on arrête les dossiers mais on lit les noms des dossiers déjà lus ; 2e appui (ou pendant les noms) : arrêt total
                      if (phaseRef.current === "dossiers" && !arretDossiersRef.current) {
                        arretDossiersRef.current = true;
                        toast.info("Arrêt demandé : la tranche en cours se termine, puis les noms des patients sont lus. Appuyez encore pour tout arrêter.");
                      } else annulerRef.current = true;
                    }}
                    className="inline-flex items-center gap-2 rounded border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-700">
              <XCircle className="h-4 w-4" aria-hidden="true" />Arrêter
            </button>
          )}
        </div>
      </div>

      {/* Bande d'état : où l'on lit, durée écoulée et avancement */}
      <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded px-3 py-2 text-sm font-semibold ${enCours ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-900"}`} data-testid="bande">
        {enCours
          ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />Lecture en cours… {dureeMmSs(secondes)} — {avancement} (inutile de recliquer)</>
          : <><Server className="h-4 w-4" aria-hidden="true" />{client ? `Client ${client}${base ? ` · base ${base}` : ""}${machine ? ` · machine ${machine}` : ""}` : "Aucun client choisi"}{dernier ? ` · dernier n° ${dernier}` : ""}</>}
      </div>

      {erreur && (
        <div className="flex items-start gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert" data-testid="erreur">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span className="break-words">{erreur}</span>
        </div>
      )}
      {partielle && !enCours && (
        <div className="flex items-start gap-2 rounded border border-orange-200 bg-orange-50 p-3 text-sm text-orange-800" role="status" data-testid="partielle">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {arretee
            ? <span><b>Lecture arrêtée</b> : la liste est incomplète ({dossiers.length} dossier(s) lus). Appuyez sur « Actualiser » pour la relire en entier.</span>
            : <span><b>Lecture PARTIELLE</b> : la liste est incomplète (limite de {FENETRES_MAX} tranches ou de {BUDGET_MS / 60000} minutes). Choisissez une période plus courte.</span>}
        </div>
      )}

      {/* Liste : toutes les colonnes sont triables ; clic sur une ligne = détail dans une fenêtre modale */}
      {dossiers.length > 0 && (
        <>
          <label className="flex items-center gap-2 rounded border border-slate-300 bg-white px-2 text-sm">
            <Search className="h-4 w-4 text-slate-500" aria-hidden="true" />
            <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher un n°, un libellé ou un patient" className="w-full p-2 outline-none" data-testid="recherche" />
          </label>
          <p className="text-xs text-slate-500">{triees.length} dossier(s) · {periodeLibelle}</p>
          <div className="overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="min-w-full text-sm" data-testid="liste-dossiers">
              <thead className="bg-sky-50 text-sky-900">
                <tr>
                  {/* Téléphone (demande du propriétaire, 18/11/2026) : DEUX cellules seulement — « N° dossier » avec la date et l'heure dessous, « N° patient » avec le nom
                      dessous (libellé en petit) ; les colonnes « Date » et « Libellé » séparées n'apparaissent qu'à partir de la tablette */}
                  <ThTri cle="numero" tri={tri} onTri={basculer} droite>N°<span className="md:hidden"> · Date</span></ThTri>
                  <ThTri cle="date" tri={tri} onTri={basculer} className="hidden text-left md:table-cell">Date</ThTri>
                  <ThTri cle="patient" tri={tri} onTri={basculer} className="text-left"><span className="md:hidden">N° · </span>Patient</ThTri>
                  <ThTri cle="libelle" tri={tri} onTri={basculer} className="hidden text-left md:table-cell">Libellé</ThTri>
                  <th className="p-2 text-left font-semibold"><span className="sr-only md:not-sr-only">Détail</span></th>
                </tr>
              </thead>
              <tbody>
                {triees.map((d) => (
                  <tr key={d.numero} className="border-t border-slate-100">
                    <td className="p-2 text-right tabular-nums">
                      <span className="block font-semibold text-sky-800">{d.numero}</span>
                      {/* Téléphone : date et heure sous le numéro du dossier */}
                      <span className="block text-xs text-slate-500 md:hidden">{dateFr(d.date)}{d.heure ? ` ${d.heure}` : ""}</span>
                    </td>
                    <td className="hidden whitespace-nowrap p-2 text-slate-700 md:table-cell">{dateFr(d.date)}{d.heure ? ` ${d.heure}` : ""}</td>
                    <td className="p-2 text-violet-800">
                      {/* Téléphone : numéro du patient au-dessus de son nom (nom pas lu : « nom non trouvé »), libellé du dossier en petit dessous */}
                      <span className="block text-xs tabular-nums text-slate-500 md:hidden">{d.codePatient === null ? "—" : `n° ${d.codePatient}`}</span>
                      <span className="block">{noms[d.codePatient] || (d.codePatient === null ? "—" : <i className="text-slate-400">{interroges.has(d.codePatient) ? "nom non trouvé" : enCours ? "nom en cours de lecture…" : "nom non lu"}</i>)}</span>
                      <span className="block text-xs text-slate-500 md:hidden">{d.libelle || "—"}</span>
                    </td>
                    <td className="hidden p-2 md:table-cell">{d.libelle || "—"}</td>
                    <td className="p-2">
                      {/* Pictogramme seul sur téléphone (info-bulle et libellé d'accessibilité), avec la légende « Voir » dès la tablette (règle 15) */}
                      <button type="button" onClick={() => setDetail(d)} title={`Voir le dossier ${d.numero}`} aria-label={`Voir le dossier ${d.numero}`}
                              className="inline-flex items-center gap-1 rounded border border-sky-300 px-2 py-1 text-xs font-semibold text-sky-800">
                        <Eye className="h-3.5 w-3.5" aria-hidden="true" /><span className="hidden md:inline">Voir</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!enCours && dossiers.length === 0 && !erreur && (
        <p className="rounded border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          Choisissez le client et la période, puis appuyez sur « Afficher ». Chaque lecture prend quelques secondes.
        </p>
      )}

      {/* Détail d'un dossier : fenêtre modale (règle 20), jamais une page allongée */}
      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85dvh] max-w-md overflow-y-auto" data-testid="detail-dossier">
          <DialogHeader>
            <DialogTitle>Dossier n° {detail?.numero}</DialogTitle>
            <DialogDescription>Lecture seule · client {client}</DialogDescription>
          </DialogHeader>
          {detail && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="font-semibold text-slate-600">Libellé</dt><dd>{detail.libelle || "—"}</dd>
              <dt className="font-semibold text-slate-600">Date de dépôt</dt><dd>{dateFr(detail.date)}{detail.heure ? ` ${detail.heure}` : ""}</dd>
              <dt className="font-semibold text-slate-600">Patient</dt><dd className="text-violet-800">{libellePatient(detail, noms)}</dd>
              <dt className="font-semibold text-slate-600">Montant</dt>
              <dd className={`tabular-nums ${detail.regle ? "text-emerald-700" : "text-red-700"}`}>
                <Banknote className="mr-1 inline h-4 w-4" aria-hidden="true" />{detail.montant === null ? "—" : detail.montant.toLocaleString("fr-FR")}
              </dd>
              <dt className="font-semibold text-slate-600">Réglé</dt>
              <dd className={detail.regle ? "text-emerald-700" : "text-red-700"}>
                {detail.regle ? <><CheckCircle2 className="mr-1 inline h-4 w-4" aria-hidden="true" />Oui</> : <><XCircle className="mr-1 inline h-4 w-4" aria-hidden="true" />Non</>}
              </dd>
              <dt className="font-semibold text-slate-600">Modifié par</dt><dd>{detail.modificateur || "—"}</dd>
            </dl>
          )}
          <button type="button" onClick={() => setDetail(null)} className="mt-2 inline-flex items-center gap-2 rounded border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700">
            <XCircle className="h-4 w-4" aria-hidden="true" />Fermer
          </button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
