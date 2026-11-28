// ============================================================================
// PointageInventaireSection.jsx — Lot 496 : Paramètres → « 📱 Pointage D'Inventaire Par Téléphone ».
// Le responsable crée un inventaire pour TOUT lieu de commerce (lot 497 : client Loois, officine, ou commerce déclaré ici avec sa
// clé de suivi « CS-… »), dépose la liste des produits (JSON d'Aizenta ou CSV d'Excel / d'un autre logiciel), déclare les lieux de
// stockage (rattachés à « INV SV » ou « INV Mag » pour Aizenta), affiche le QR code, suit le comptage en direct, puis exporte :
// JSON WinDev (réimportable dans Aizenta) ou CSV (Excel, pour tout commerce).
// Lot 498 : chaque commerce doit avoir sa CLÉ DE POINTAGE (CP-…) et son MOT DE PASSE (montré une seule fois) pour être autorisé ;
// ce même composant sert l'ESPACE POINTAGE du responsable (page /pointage-espace, prop `espace`) : routes /api/pointage-espace/…,
// structure imposée par la connexion, pas de gestion des clés.
// Backend : /api/admin/pointage-inventaires (routes/pointage_telephone.py), administrateur seul.
// ============================================================================
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { AlertTriangle, Ban, Check, Copy, Download, Eye, FileSpreadsheet, KeyRound, Lock, LockOpen, Plus, QrCode, RefreshCw, RotateCcw, Search, Store, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const nombre = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("fr-FR"));
const dateCourte = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const peremption = (p) => (p ? `${p.slice(4, 6)}/${p.slice(0, 4)}` : "");   // « 20270301 » → « 03/2027 »
const COLONNES = [{ v: "SV", l: "INV SV (salle de vente)" }, { v: "MG", l: "INV Mag (magasin)" }];
const SOURCES = { commerce: "Commerce", loois: "Client Loois", officine: "Officine" };

// Accès aux routes : administrateur (/admin/…, session SAWALI) ou Espace pointage (/pointage-espace/…, jeton du commerce en en-tête).
// Parallèle WinDev : une variable globale de connexion partagée par toutes les fenêtres filles.
const CtxPointage = createContext(null);
function apiPour(espace) {
  const h = espace ? { "X-Pointage-Jeton": espace.jeton } : {};
  const avec = (o = {}) => ({ ...o, headers: { ...(o.headers || {}), ...h } });
  const traiter401 = (e) => { if (espace && e.response?.status === 401) espace.onExpire?.(); throw e; };
  return {
    base: espace ? "/pointage-espace/inventaires" : "/admin/pointage-inventaires",
    espace,
    get: (u, o) => apiClient.get(u, avec(o)).catch(traiter401),
    post: (u, b, o) => apiClient.post(u, b, avec(o)).catch(traiter401),
  };
}

/** Bouton rond à pictogramme seul (règle du 27/11/2026) : info-bulle et libellé d'accessibilité. */
function Picto({ titre, Icone, onClick, couleur = "bg-sky-600 text-white", disabled = false, testid }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={titre} aria-label={titre} data-testid={testid}
            className={`inline-flex h-11 w-11 items-center justify-center rounded-full shadow-sm disabled:opacity-40 ${couleur}`}>
      <Icone className="h-5 w-5" aria-hidden="true" />
    </button>
  );
}

export default function PointageInventaireSection({ espace = null }) {
  const api = useMemo(() => apiPour(espace), [espace]);
  const [inventaires, setInventaires] = useState([]);
  const [motDePasse, setMotDePasse] = useState(null);   // {cle, mot_de_passe, libelle} : affiché UNE fois
  const [creation, setCreation] = useState(false);
  const [ouvert, setOuvert] = useState(null);       // id de l'inventaire affiché dans la fenêtre de suivi

  const charger = useCallback(async (avecToast = false) => {
    const t = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const { data } = await api.get(api.base);
      setInventaires(data.inventaires || []);
      if (t) toast.success(`${data.inventaires.length} inventaire(s) relu(s).`, { id: t });
    } catch (e) {
      if (t) toast.error(e.response?.data?.detail || "Lecture impossible.", { id: t });
    }
  }, [api]);
  useEffect(() => { charger(); }, [charger]);

  const { lignes, tri, basculer } = useTri(inventaires, {
    numero: (i) => i.numero, structure: (i) => i.structure?.libelle || i.structure?.code, code: (i) => i.code_inv,
    lignes: (i) => i.lignes_total, comptees: (i) => i.lignes_comptees, progression: (i) => i.progression,
    etat: (i) => i.etat, cree: (i) => i.cree_le,
  });

  return (
    <div className="space-y-3" data-testid="pointage-inventaire">
      <p className="text-sm text-slate-600">
        Pour tout lieu de commerce : les auxiliaires scannent le QR code avec leur téléphone, puis dictent « ligne, quantité,
        péremption, suivant ». Le résultat s'exporte en JSON pour Aizenta ou en CSV pour Excel.
      </p>
      <div className="flex items-center gap-2">
        <Picto titre="Nouvel inventaire" Icone={Plus} onClick={() => setCreation(true)} couleur="bg-emerald-600 text-white" testid="pointage-nouveau" />
        <Picto titre="Actualiser la liste" Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-slate-100 text-slate-700" />
      </div>
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <ThTri cle="numero" tri={tri} onTri={basculer}>N°</ThTri>
              <ThTri cle="structure" tri={tri} onTri={basculer}>Structure</ThTri>
              <ThTri cle="code" tri={tri} onTri={basculer}>Inventaire</ThTri>
              <ThTri cle="lignes" tri={tri} onTri={basculer} droite>Lignes</ThTri>
              <ThTri cle="comptees" tri={tri} onTri={basculer} droite>Comptées</ThTri>
              <ThTri cle="progression" tri={tri} onTri={basculer} droite>Avancement</ThTri>
              <ThTri cle="etat" tri={tri} onTri={basculer}>État</ThTri>
              <ThTri cle="cree" tri={tri} onTri={basculer}>Créé le</ThTri>
              <th className="p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((i) => (
              <tr key={i.id} className="border-t">
                <td className="p-2 font-semibold text-sky-700">{i.numero}</td>
                <td className="p-2">{i.structure?.libelle || i.structure?.code}
                  <span className="block text-xs text-slate-500">{i.structure?.type || SOURCES[i.structure?.source] || ""}{i.structure?.code ? ` · ${i.structure.code}` : ""}</span></td>
                <td className="p-2">{i.code_inv || (i.format === "csv" ? "Liste CSV" : "—")}{i.base ? <span className="text-slate-500"> · {i.base}</span> : null}</td>
                <td className="p-2 text-right tabular-nums">{nombre(i.lignes_total)}</td>
                <td className="p-2 text-right tabular-nums text-emerald-700">{nombre(i.lignes_comptees)}</td>
                <td className="p-2 text-right tabular-nums">{i.progression} %</td>
                <td className="p-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${i.etat === "ouvert" ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"}`}>
                    {i.etat === "ouvert" ? "● En cours" : "■ Clôturé"}
                  </span>
                </td>
                <td className="p-2 whitespace-nowrap">{dateCourte(i.cree_le)}</td>
                <td className="p-2">
                  <button type="button" onClick={() => setOuvert(i.id)} title="Suivre / QR code / exporter" aria-label="Suivre, QR code et export"
                          className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700"><Eye className="h-4 w-4" aria-hidden="true" /></button>
                </td>
              </tr>
            ))}
            {!lignes.length && <tr><td colSpan={9} className="p-4 text-center text-slate-500">Aucun inventaire : créez-en un avec le pictogramme +.</td></tr>}
          </tbody>
          {/* Règle 25 : totaux des colonnes de quantités sous le tableau */}
          <tfoot className="border-t-2 bg-slate-50 font-semibold">
            <tr>
              <td className="p-2" colSpan={3}>{lignes.length} inventaire(s)</td>
              <td className="p-2 text-right tabular-nums">{nombre(lignes.reduce((s, i) => s + (i.lignes_total || 0), 0))}</td>
              <td className="p-2 text-right tabular-nums">{nombre(lignes.reduce((s, i) => s + (i.lignes_comptees || 0), 0))}</td>
              <td colSpan={4} />
            </tr>
          </tfoot>
        </table>
      </div>
      {!espace && <CommercesAutorises onMotDePasse={setMotDePasse} />}
      <CtxPointage.Provider value={api}>
        {creation && <FenetreCreation onFermer={() => setCreation(false)} onMotDePasse={setMotDePasse}
                                      onCree={(inv) => { setCreation(false); charger(); setOuvert(inv.id); }} />}
        {ouvert && <FenetreSuivi ident={ouvert} onFermer={() => { setOuvert(null); charger(); }} />}
      </CtxPointage.Provider>
      {motDePasse && <FenetreMotDePasse info={motDePasse} onFermer={() => setMotDePasse(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Lot 498 : clé de pointage et mot de passe — montrés UNE seule fois (SAWALI ne garde que l'empreinte du mot de passe)
// ---------------------------------------------------------------------------------------------------------------------------
function FenetreMotDePasse({ info, onFermer }) {
  const espaceUrl = `${window.location.origin}/pointage-espace`;
  const texte = `Pointage d'inventaire — ${info.libelle}\nClé de pointage : ${info.cle}\nMot de passe : ${info.mot_de_passe}\nEspace pointage : ${espaceUrl}`;
  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-md overflow-y-auto" data-testid="pointage-mot-de-passe">
        <DialogHeader><DialogTitle>Accès au pointage : {info.libelle}</DialogTitle></DialogHeader>
        <div className="space-y-2 rounded-xl border-2 border-violet-300 bg-violet-50 p-3 text-center">
          <p className="text-sm text-slate-600">Clé de pointage</p>
          <p className="text-2xl font-bold tracking-wider text-sky-700">{info.cle}</p>
          <p className="text-sm text-slate-600">Mot de passe</p>
          <p className="font-mono text-3xl font-bold tracking-widest text-violet-800" data-testid="pointage-mdp-affiche">{info.mot_de_passe}</p>
        </div>
        <p className="flex gap-2 rounded-lg bg-amber-50 p-2 text-sm text-amber-900"><AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
          Notez-le et transmettez-le au responsable du commerce : il ne sera plus jamais affiché (un nouveau mot de passe reste possible).</p>
        <p className="text-xs text-slate-500">Le responsable se connecte sur <b>{espaceUrl}</b> ; les auxiliaires saisissent le même mot de passe après le QR code.</p>
        <div className="flex justify-end gap-2">
          <Picto titre="Copier la clé, le mot de passe et l'adresse" Icone={Copy} couleur="bg-sky-100 text-sky-700"
                 onClick={() => navigator.clipboard?.writeText(texte).then(() => toast.success("Accès copié."))} />
          <Picto titre="Fermer" Icone={X} onClick={onFermer} couleur="bg-slate-100 text-slate-700" />
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Lot 498 : commerces autorisés au pointage (administrateur) — nouveau mot de passe, révocation, réactivation
// ---------------------------------------------------------------------------------------------------------------------------
function CommercesAutorises({ onMotDePasse }) {
  const [acces, setAcces] = useState([]);
  const charger = useCallback(async (avecToast = false) => {
    const t = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const { data } = await apiClient.get("/admin/pointage-acces");
      setAcces(data.acces || []);
      if (t) toast.success(`${data.acces.length} commerce(s) autorisé(s).`, { id: t });
    } catch (e) { if (t) toast.error(e.response?.data?.detail || "Lecture impossible.", { id: t }); }
  }, []);
  useEffect(() => { charger(); }, [charger]);
  const { lignes, tri, basculer } = useTri(acces, {
    commerce: (a) => a.structure?.libelle, type: (a) => a.structure?.type, cle: (a) => a.cle, etat: (a) => (a.actif ? 1 : 0), derniere: (a) => a.derniere_connexion,
  });
  const action = async (a, chemin) => {
    const t = toast.loading("En cours…");
    try {
      const { data } = await apiClient.post(`/admin/pointage-acces/${a.id}/${chemin}`);
      if (chemin === "mot-de-passe") { toast.success("Nouveau mot de passe créé : l'ancien ne marche plus.", { id: t }); onMotDePasse({ cle: a.cle, mot_de_passe: data.mot_de_passe, libelle: a.structure?.libelle }); }
      else toast.success(chemin === "revoquer" ? "Clé révoquée : plus aucun pointage possible." : "Clé réactivée.", { id: t });
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || "Action impossible.", { id: t }); }
  };
  return (
    <div className="space-y-2 pt-3">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4 text-violet-600" aria-hidden="true" />Commerces autorisés au pointage</p>
        <Picto titre="Actualiser les commerces autorisés" Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-slate-100 text-slate-700" />
      </div>
      <p className="text-xs text-slate-500">Une clé se génère commerce par commerce depuis « Nouvel inventaire » (pictogramme clé à côté du commerce) ; un commerce déclaré reçoit la sienne aussitôt.</p>
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr>
            <ThTri cle="commerce" tri={tri} onTri={basculer}>Commerce</ThTri>
            <ThTri cle="type" tri={tri} onTri={basculer}>Type</ThTri>
            <ThTri cle="cle" tri={tri} onTri={basculer}>Clé de pointage</ThTri>
            <ThTri cle="etat" tri={tri} onTri={basculer}>État</ThTri>
            <ThTri cle="derniere" tri={tri} onTri={basculer}>Dernière connexion</ThTri>
            <th className="p-2">Actions</th>
          </tr></thead>
          <tbody>
            {lignes.map((a) => (
              <tr key={a.id} className="border-t">
                <td className="p-2 font-semibold">{a.structure?.libelle}</td>
                <td className="p-2">{a.structure?.type || SOURCES[a.structure?.source]}</td>
                <td className="p-2 font-mono font-semibold text-sky-700">{a.cle}</td>
                <td className="p-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${a.actif ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800"}`}>{a.actif ? "✓ Autorisé" : "✕ Révoqué"}</span></td>
                <td className="p-2 whitespace-nowrap">{dateCourte(a.derniere_connexion)}</td>
                <td className="p-2">
                  <div className="flex gap-1">
                    <button type="button" onClick={() => action(a, "mot-de-passe")} title="Nouveau mot de passe" aria-label="Nouveau mot de passe"
                            className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-violet-100 text-violet-700"><KeyRound className="h-4 w-4" aria-hidden="true" /></button>
                    {a.actif
                      ? <button type="button" onClick={() => window.confirm(`Révoquer la clé de ${a.structure?.libelle} ? Les téléphones et l'Espace pointage seront coupés.`) && action(a, "revoquer")}
                                title="Révoquer la clé" aria-label="Révoquer la clé" className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-rose-100 text-rose-700"><Ban className="h-4 w-4" aria-hidden="true" /></button>
                      : <button type="button" onClick={() => action(a, "reactiver")} title="Réactiver la clé" aria-label="Réactiver la clé"
                                className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"><RotateCcw className="h-4 w-4" aria-hidden="true" /></button>}
                  </div>
                </td>
              </tr>
            ))}
            {!lignes.length && <tr><td colSpan={6} className="p-3 text-center text-slate-500">Aucun commerce autorisé pour l'instant.</td></tr>}
          </tbody>
          <tfoot className="border-t-2 bg-slate-50 font-semibold"><tr><td className="p-2" colSpan={6}>{lignes.length} commerce(s) · {lignes.filter((a) => a.actif).length} autorisé(s)</td></tr></tfoot>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Création : structure (liste déroulante), fichier JSON d'Aizenta, lieux de stockage
// ---------------------------------------------------------------------------------------------------------------------------
function FenetreCreation({ onFermer, onCree, onMotDePasse }) {
  const api = useContext(CtxPointage);
  const fixe = api.espace?.commerce?.structure;          // Espace pointage : le commerce est celui de la connexion
  const [q, setQ] = useState("");
  const [resultats, setResultats] = useState([]);
  const [types, setTypes] = useState([]);
  const [structure, setStructure] = useState(fixe ? { ...fixe, acces: { cle: api.espace.commerce.cle, actif: true } } : null);   // {source, id, libelle, code, type, acces}
  const [nouveau, setNouveau] = useState(null);       // formulaire « déclarer un commerce » : {nom, type, autre, ville}
  const [fichier, setFichier] = useState(null);       // {nom, contenu, lignes, format}
  const [lieux, setLieux] = useState([{ nom: "Salle de vente", colonne: "SV" }, { nom: "Magasin", colonne: "MG" }]);
  const [envoi, setEnvoi] = useState(false);

  // Recherche de la structure (clients Loois, officines, commerces déclarés), relancée 300 ms après la dernière frappe
  useEffect(() => {
    if (fixe) return undefined;                          // pas de recherche dans l'Espace pointage
    const t = setTimeout(() => {
      apiClient.get("/admin/pointage-inventaires/structures", { params: { q } })
        .then(({ data }) => { setResultats(data.structures || []); setTypes(data.types_commerce || []); })
        .catch(() => toast.error("Recherche des structures impossible."));
    }, 300);
    return () => clearTimeout(t);
  }, [q, fixe]);

  // Lot 498 : génère la clé de pointage d'un commerce déjà connu (une à une), puis montre le mot de passe une seule fois
  const genererCle = async (r) => {
    const t = toast.loading(`Génération de la clé de ${r.libelle}…`);
    try {
      const { data } = await apiClient.post("/admin/pointage-acces", { source: r.source, id: r.id });
      toast.success(`Clé ${data.cle} créée.`, { id: t });
      setStructure({ ...r, acces: { cle: data.cle, actif: true } });
      onMotDePasse({ cle: data.cle, mot_de_passe: data.mot_de_passe, libelle: r.libelle });
    } catch (e) { toast.error(e.response?.data?.detail || "Génération impossible.", { id: t }); }
  };

  const declarer = async () => {
    const t = toast.loading("Déclaration du commerce en cours…");
    try {
      const type = nouveau.type === "__autre" ? nouveau.autre : nouveau.type;
      const { data } = await apiClient.post("/admin/pointage-structures", { nom: nouveau.nom, type, ville: nouveau.ville || null });
      toast.success(`${data.libelle} déclaré, clé de pointage ${data.acces.cle}.`, { id: t });
      setStructure(data); setNouveau(null);
      onMotDePasse({ cle: data.acces.cle, mot_de_passe: data.mot_de_passe, libelle: data.libelle });
    } catch (e) { toast.error(e.response?.data?.detail || "Déclaration impossible.", { id: t }); }
  };

  // Liste des produits : JSON d'Aizenta, ou CSV (Excel → « Enregistrer sous » → CSV) ; le serveur refait le contrôle complet
  const lireFichier = async (f) => {
    if (!f) return;
    try {
      const contenu = (await f.text()).replace(/^﻿/, "");
      if (contenu.trimStart().startsWith("{")) {
        const n = JSON.parse(contenu)?.["REQ_DétailInventaire"]?.length;
        if (!n) throw new Error("tableau REQ_DétailInventaire absent (export d'Aizenta attendu)");
        setFichier({ nom: f.name, contenu, lignes: n, format: "JSON Aizenta" });
      } else {
        const n = contenu.split(/\r?\n/).filter((l) => l.replace(/[;,\t\s]/g, "")).length - 1;
        if (n < 1) throw new Error("CSV vide : une ligne d'en-têtes (dont « Libellé » ou « Désignation ») puis une ligne par produit");
        setFichier({ nom: f.name, contenu, lignes: n, format: "CSV" });
      }
    } catch (e) { toast.error(`Fichier refusé : ${e.message}`); setFichier(null); }
  };

  const creer = async () => {
    setEnvoi(true);
    const t = toast.loading("Création de l'inventaire en cours…");
    try {
      const { data } = await api.post(api.base, {
        structure: fixe ? null : { source: structure.source, id: structure.id }, lieux, nom_fichier: fichier.nom, contenu: fichier.contenu });
      toast.success(`Inventaire ${data.numero} créé (${data.lignes_total} lignes).`, { id: t });
      onCree(data);
    } catch (e) { toast.error(e.response?.data?.detail || "Création impossible.", { id: t }); setEnvoi(false); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="pointage-creation">
        <DialogHeader><DialogTitle>Nouvel inventaire par téléphone</DialogTitle></DialogHeader>

        {/* 1. Structure : n'importe quel lieu de commerce */}
        <p className="text-sm font-semibold">Lieu de commerce</p>
        {structure ? (
          <div className="flex items-center gap-2 rounded-xl border-2 border-emerald-500 bg-emerald-50 p-2">
            <Store className="h-5 w-5 text-emerald-700" aria-hidden="true" />
            <span className="min-w-0 flex-1 text-sm"><b>{structure.libelle}</b> <span className="text-slate-600">· {structure.type || SOURCES[structure.source]}</span>
              {structure.acces?.actif
                ? <span className="block text-emerald-800">✓ Clé de pointage <b className="font-mono">{structure.acces.cle}</b></span>
                : <span className="block text-red-700">✕ {structure.acces ? "Clé de pointage révoquée" : "Pas encore de clé de pointage"} : pointage impossible</span>}</span>
            {!fixe && !structure.acces && <Picto titre="Générer la clé de pointage et le mot de passe" Icone={KeyRound} onClick={() => genererCle(structure)} couleur="bg-violet-600 text-white" testid="pointage-generer-cle" />}
            {!fixe && <button type="button" onClick={() => setStructure(null)} title="Changer de lieu de commerce" aria-label="Changer de lieu de commerce"
                    className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-700"><X className="h-4 w-4" aria-hidden="true" /></button>}
          </div>
        ) : nouveau ? (
          <div className="space-y-2 rounded-xl border p-3">
            <input value={nouveau.nom} onChange={(e) => setNouveau({ ...nouveau, nom: e.target.value })} placeholder="Boutique Wend Panga" maxLength={120}
                   className="w-full rounded-lg border px-3 py-2" aria-label="Nom du commerce" />
            <div className="flex gap-2">
              <select value={nouveau.type} onChange={(e) => setNouveau({ ...nouveau, type: e.target.value })} className="min-w-0 flex-1 rounded-lg border px-2 py-2" aria-label="Type de commerce">
                <option value="">— Type de commerce —</option>
                {types.map((t) => <option key={t} value={t}>{t}</option>)}
                <option value="__autre">Autre…</option>
              </select>
              <input value={nouveau.ville} onChange={(e) => setNouveau({ ...nouveau, ville: e.target.value })} placeholder="Ouagadougou" maxLength={80}
                     className="w-36 rounded-lg border px-3 py-2" aria-label="Ville" />
            </div>
            {nouveau.type === "__autre" && <input value={nouveau.autre} onChange={(e) => setNouveau({ ...nouveau, autre: e.target.value })} placeholder="Pressing" maxLength={60}
                                                  className="w-full rounded-lg border px-3 py-2" aria-label="Autre type de commerce" />}
            <div className="flex justify-end gap-2">
              <Picto titre="Annuler" Icone={X} onClick={() => setNouveau(null)} couleur="bg-slate-100 text-slate-700" />
              <Picto titre="Déclarer ce commerce (clé de suivi générée)" Icone={Check} onClick={declarer} couleur="bg-emerald-600 text-white"
                     disabled={nouveau.nom.trim().length < 2 || !nouveau.type || (nouveau.type === "__autre" && !nouveau.autre.trim())} />
            </div>
          </div>
        ) : (
          <div className="space-y-1">
            <div className="flex items-center gap-2 rounded-lg border px-3">
              <Search className="h-4 w-4 text-slate-400" aria-hidden="true" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, ville ou clé de suivi" className="min-w-0 flex-1 py-2 outline-none" aria-label="Rechercher le lieu de commerce" />
            </div>
            <ul className="max-h-44 divide-y overflow-y-auto rounded-lg border text-sm">
              {resultats.map((r) => (
                <li key={`${r.source}-${r.id}`}>
                  <button type="button" onClick={() => setStructure(r)} className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-sky-50">
                    <Store className="h-4 w-4 shrink-0 text-sky-600" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate"><b>{r.libelle}</b>{r.ville ? ` · ${r.ville}` : ""}</span>
                    <span className="shrink-0 text-xs text-slate-500">{r.type || SOURCES[r.source]}</span>
                    <span className={`shrink-0 rounded px-1.5 text-xs font-semibold ${r.acces?.actif ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-500"}`}
                          title={r.acces?.actif ? "Autorisé au pointage" : "Sans clé de pointage"}>{r.acces?.actif ? `✓ ${r.acces.cle}` : "sans clé"}</span>
                  </button>
                </li>
              ))}
              {!resultats.length && <li className="px-3 py-2 text-slate-500">Aucun lieu trouvé : déclarez-le ci-dessous.</li>}
            </ul>
            <button type="button" onClick={() => setNouveau({ nom: q, type: "", autre: "", ville: "" })} className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-700">
              <Plus className="h-4 w-4" aria-hidden="true" />Déclarer un nouveau commerce
            </button>
          </div>
        )}

        {/* 2. Liste des produits */}
        <label className="mt-2 flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed p-3 hover:bg-sky-50">
          <Upload className="h-6 w-6 text-sky-600" aria-hidden="true" />
          <span className="text-sm">{fichier ? <><b className="text-sky-700">{fichier.nom}</b> · {fichier.format} · {nombre(fichier.lignes)} produits</>
            : <>Liste des produits : <b>JSON d'Aizenta</b> ou <b>CSV</b> (Excel : colonnes « Libellé » ou « Désignation », et si possible « N° », « Code », « Stock »)</>}</span>
          <input type="file" accept=".json,.csv,.txt,application/json,text/csv" className="sr-only" onChange={(e) => lireFichier(e.target.files?.[0])} />
        </label>

        {/* 3. Lieux de stockage */}
        <p className="mt-2 text-sm font-semibold">Lieux de stockage</p>
        <p className="text-xs text-slate-500">Pour Aizenta, chaque lieu s'ajoute à l'une de ses deux colonnes (INV SV ou INV Mag). L'export CSV garde une colonne par lieu.</p>
        <div className="space-y-2">
          {lieux.map((l, i) => (
            <div key={i} className="flex items-center gap-2">
              <input value={l.nom} maxLength={40} placeholder="Réservés" onChange={(e) => setLieux(lieux.map((x, j) => (j === i ? { ...x, nom: e.target.value } : x)))}
                     className="min-w-0 flex-1 rounded-lg border px-3 py-2" aria-label={`Nom du lieu ${i + 1}`} />
              <select value={l.colonne} onChange={(e) => setLieux(lieux.map((x, j) => (j === i ? { ...x, colonne: e.target.value } : x)))}
                      className="rounded-lg border px-2 py-2" aria-label={`Colonne Aizenta du lieu ${i + 1}`}>
                {COLONNES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
              </select>
              <button type="button" onClick={() => setLieux(lieux.filter((_, j) => j !== i))} disabled={lieux.length <= 1}
                      title="Retirer ce lieu" aria-label="Retirer ce lieu" className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-rose-100 text-rose-700 disabled:opacity-40">
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          ))}
          {lieux.length < 8 && (
            <button type="button" onClick={() => setLieux([...lieux, { nom: "", colonne: "MG" }])} className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-700">
              <Plus className="h-4 w-4" aria-hidden="true" />Ajouter un lieu
            </button>
          )}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Picto titre="Fermer" Icone={X} onClick={onFermer} couleur="bg-slate-100 text-slate-700" />
          <Picto titre="Créer l'inventaire" Icone={Plus} onClick={creer} couleur="bg-emerald-600 text-white" testid="pointage-creer"
                 disabled={envoi || !structure?.acces?.actif || !fichier || lieux.some((l) => !l.nom.trim())} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Suivi : QR code, avancement par lieu et par auxiliaire, alertes, lignes ; export, clôture
// ---------------------------------------------------------------------------------------------------------------------------
function FenetreSuivi({ ident, onFermer }) {
  const api = useContext(CtxPointage);
  const [d, setD] = useState(null);
  const [qr, setQr] = useState("");
  const [onglet, setOnglet] = useState("suivi");
  const [filtre, setFiltre] = useState("non_comptees");
  const lien = d?.jeton ? `${window.location.origin}/pointage/${d.jeton}` : "";

  const charger = useCallback(async (avecToast = false) => {
    const t = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const { data } = await api.get(`${api.base}/${ident}`);
      setD(data);
      if (t) toast.success(`${data.lignes_comptees} ligne(s) comptée(s) sur ${data.lignes_total}, ${data.alertes.length} alerte(s).`, { id: t });
    } catch (e) { if (t) toast.error(e.response?.data?.detail || "Lecture impossible.", { id: t }); }
  }, [ident, api]);
  useEffect(() => { charger(); const x = setInterval(() => charger(), 15000); return () => clearInterval(x); }, [charger]);   // suivi en direct : relu toutes les 15 s
  useEffect(() => { if (lien) QRCode.toDataURL(lien, { errorCorrectionLevel: "M", width: 260, margin: 1 }).then(setQr); else setQr(""); }, [lien]);

  const action = async (chemin, message) => {
    const t = toast.loading("En cours…");
    try { await api.post(`${api.base}/${ident}/${chemin}`); toast.success(message, { id: t }); charger(); }
    catch (e) { toast.error(e.response?.data?.detail || "Action impossible.", { id: t }); }
  };
  const exporter = async (format) => {
    const t = toast.loading(format === "csv" ? "Préparation du fichier CSV…" : "Préparation du JSON complété…");
    try {
      const r = await api.get(`${api.base}/${ident}/export`, { params: { format }, responseType: "blob" });
      const nom = /filename="([^"]+)"/.exec(r.headers["content-disposition"] || "")?.[1] || `inventaire.pointe.${format}`;
      const a = document.createElement("a"); a.href = URL.createObjectURL(r.data); a.download = nom; a.click(); URL.revokeObjectURL(a.href);
      toast.success(format === "csv" ? `${nom} téléchargé : à ouvrir avec Excel.` : `${nom} téléchargé : à réimporter dans Aizenta.`, { id: t });
    } catch { toast.error("Export impossible.", { id: t }); }
  };

  const lignesFiltrees = useMemo(() => {
    const l = d?.lignes || [];
    if (filtre === "non_comptees") return l.filter((x) => x.compte === null);
    if (filtre === "comptees") return l.filter((x) => x.compte !== null);
    return l;
  }, [d, filtre]);
  const { lignes: triees, tri, basculer } = useTri(lignesFiltrees, {
    chrono: (x) => x.chrono, libelle: (x) => x.libelle, avant: (x) => x.avant, sv: (x) => x.sv, mg: (x) => x.mg,
    compte: (x) => x.compte, ecart: (x) => x.ecart, peremption: (x) => x.peremption, par: (x) => x.par.join(", "),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="pointage-suivi">
        <DialogHeader><DialogTitle>{d ? `${d.numero} · ${d.structure?.libelle || d.structure?.code}${d.code_inv ? ` · ${d.code_inv}` : ""}` : "Patientez…"}</DialogTitle></DialogHeader>
        {d && (
          <>
            {/* Avancement */}
            <div>
              <div className="flex justify-between text-sm"><span><b className="text-emerald-700">{nombre(d.lignes_comptees)}</b> / {nombre(d.lignes_total)} lignes comptées</span><b>{d.progression} %</b></div>
              <div className="mt-1 h-3 rounded-full bg-slate-200"><div className="h-3 rounded-full bg-emerald-500" style={{ width: `${d.progression}%` }} /></div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Picto titre="Actualiser" Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-slate-100 text-slate-700" />
              {d.format !== "csv" && <Picto titre="Exporter le JSON complété (à réimporter dans Aizenta)" Icone={Download} onClick={() => exporter("json")} couleur="bg-emerald-600 text-white" testid="pointage-export" />}
              <Picto titre="Exporter en CSV (Excel : une colonne par lieu, écart, péremption)" Icone={FileSpreadsheet} onClick={() => exporter("csv")} couleur="bg-teal-100 text-teal-800" testid="pointage-export-csv" />
              {d.etat === "ouvert" ? <>
                <Picto titre="Nouveau QR code (l'ancien ne marche plus)" Icone={QrCode} onClick={() => action("jeton", "Nouveau QR code créé.")} couleur="bg-violet-100 text-violet-700" />
                <Picto titre="Clôturer l'inventaire" Icone={Lock} onClick={() => window.confirm("Clôturer ? Les téléphones ne pourront plus saisir.") && action("cloturer", "Inventaire clôturé.")} couleur="bg-rose-100 text-rose-700" />
              </> : <Picto titre="Rouvrir l'inventaire" Icone={LockOpen} onClick={() => action("rouvrir", "Inventaire rouvert : nouveau QR code.")} couleur="bg-amber-100 text-amber-800" />}
            </div>
            {/* Onglets */}
            <div className="flex gap-1 border-b text-sm" role="tablist">
              {[["suivi", "Suivi"], ["alertes", `Alertes (${d.alertes.length})`], ["lignes", "Lignes"]].map(([k, l]) => (
                <button key={k} type="button" role="tab" aria-selected={onglet === k} onClick={() => setOnglet(k)}
                        className={`px-3 py-2 font-semibold ${onglet === k ? "border-b-2 border-orange-500 text-orange-700" : "text-slate-500"}`}>{l}</button>
              ))}
            </div>
            {onglet === "suivi" && (
              <div className="space-y-3">
                {d.etat === "ouvert" && qr ? (
                  <div className="flex flex-col items-center gap-2 rounded-xl border bg-white p-3">
                    <img src={qr} alt="QR code du pointage" className="h-56 w-56" />
                    <div className="flex w-full items-center gap-2">
                      <code className="min-w-0 flex-1 truncate rounded bg-slate-100 px-2 py-1 text-xs">{lien}</code>
                      <button type="button" title="Copier le lien" aria-label="Copier le lien" onClick={() => navigator.clipboard?.writeText(lien).then(() => toast.success("Lien copié."))}
                              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700"><Copy className="h-4 w-4" aria-hidden="true" /></button>
                    </div>
                    <p className="text-xs text-slate-500">Valable jusqu'au {dateCourte(d.jeton_expire)}. À montrer aux auxiliaires : un scan avec le téléphone ouvre le pointage.</p>
                  </div>
                ) : <p className="rounded-lg bg-slate-100 p-3 text-sm">Inventaire clôturé : le QR code ne fonctionne plus.</p>}
                <TableauSimple titre="Par lieu" colonnes={["Lieu", "Colonne", "Lignes", "Saisies", "Quantité"]}
                               lignes={d.par_lieu.map((l) => [l.lieu, l.colonne === "SV" ? "INV SV" : "INV Mag", l.lignes, l.saisies, l.quantite])} nombres={[2, 3, 4]} />
                <TableauSimple titre="Par auxiliaire (prénom déclaré, non vérifiable)" colonnes={["Prénom", "Saisies", "Dernière"]}
                               lignes={d.par_auxiliaire.map((a) => [a.prenom, a.saisies, dateCourte(a.derniere)])} nombres={[1]} />
              </div>
            )}
            {onglet === "alertes" && (
              <ul className="space-y-1 text-sm">
                {d.alertes.map((a, i) => (
                  <li key={i} className={`flex gap-2 rounded-lg p-2 ${{ perime: "bg-red-50 text-red-800", ecart: "bg-orange-50 text-orange-800", doublon: "bg-amber-50 text-amber-800", proche: "bg-yellow-50 text-yellow-800" }[a.type]}`}>
                    <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" /><span><b className="text-sky-700">{a.chrono}</b> · {a.libelle} — {a.message}</span>
                  </li>
                ))}
                {!d.alertes.length && <li className="text-slate-500">Aucune alerte.</li>}
              </ul>
            )}
            {onglet === "lignes" && (
              <>
                <select value={filtre} onChange={(e) => setFiltre(e.target.value)} className="rounded-lg border px-2 py-1 text-sm" aria-label="Lignes affichées">
                  <option value="non_comptees">Lignes non comptées</option>
                  <option value="comptees">Lignes comptées</option>
                  <option value="toutes">Toutes les lignes</option>
                </select>
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50"><tr>
                      <ThTri cle="chrono" tri={tri} onTri={basculer} droite>N°</ThTri>
                      <ThTri cle="libelle" tri={tri} onTri={basculer}>Produit</ThTri>
                      <ThTri cle="avant" tri={tri} onTri={basculer} droite>Avant</ThTri>
                      <ThTri cle="sv" tri={tri} onTri={basculer} droite>SV</ThTri>
                      <ThTri cle="mg" tri={tri} onTri={basculer} droite>Mag</ThTri>
                      <ThTri cle="ecart" tri={tri} onTri={basculer} droite>Écart</ThTri>
                      <ThTri cle="peremption" tri={tri} onTri={basculer}>Pérempt.</ThTri>
                      <ThTri cle="par" tri={tri} onTri={basculer}>Par</ThTri>
                    </tr></thead>
                    <tbody>
                      {triees.map((x) => (
                        <tr key={x.chrono} className="border-t">
                          <td className="p-1 text-right font-semibold text-sky-700 tabular-nums">{x.chrono}</td>
                          <td className="p-1">{x.libelle} <span className="text-slate-400">{x.mesure}</span></td>
                          <td className="p-1 text-right tabular-nums">{x.avant}</td>
                          <td className="p-1 text-right tabular-nums">{x.sv ?? ""}</td>
                          <td className="p-1 text-right tabular-nums">{x.mg ?? ""}</td>
                          <td className={`p-1 text-right tabular-nums font-semibold ${x.ecart > 0 ? "text-emerald-700" : x.ecart < 0 ? "text-red-700" : ""}`}>{x.ecart ?? ""}</td>
                          <td className="p-1 text-orange-700">{peremption(x.peremption)}</td>
                          <td className="p-1">{x.par.join(", ")}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="border-t-2 bg-slate-50 font-semibold"><tr>
                      <td className="p-1" colSpan={2}>{triees.length} ligne(s)</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + x.avant, 0))}</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + (x.sv || 0), 0))}</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + (x.mg || 0), 0))}</td>
                      <td className="p-1 text-right tabular-nums">{nombre(triees.reduce((s, x) => s + (x.ecart || 0), 0))}</td>
                      <td colSpan={2} />
                    </tr></tfoot>
                  </table>
                </div>
              </>
            )}
          </>
        )}
        <div className="flex justify-end"><Picto titre="Fermer" Icone={X} onClick={onFermer} couleur="bg-slate-100 text-slate-700" /></div>
      </DialogContent>
    </Dialog>
  );
}

/** Petit tableau à colonnes triables, avec ligne de totaux sous les colonnes de nombres (règles 19 et 25). */
function TableauSimple({ titre, colonnes, lignes, nombres = [] }) {
  const acces = Object.fromEntries(colonnes.map((_, i) => [`c${i}`, (l) => l[i]]));
  const { lignes: triees, tri, basculer } = useTri(lignes, acces);
  return (
    <div>
      <p className="mb-1 text-sm font-semibold">{titre}</p>
      <table className="w-full rounded-lg border text-sm">
        <thead className="bg-slate-50"><tr>{colonnes.map((c, i) => <ThTri key={c} cle={`c${i}`} tri={tri} onTri={basculer} droite={nombres.includes(i)}>{c}</ThTri>)}</tr></thead>
        <tbody>{triees.map((l, k) => <tr key={k} className="border-t">{l.map((v, i) => <td key={i} className={`p-2 ${nombres.includes(i) ? "text-right tabular-nums" : ""} ${i === 0 ? "font-semibold text-sky-700" : ""}`}>{typeof v === "number" ? nombre(v) : v}</td>)}</tr>)}</tbody>
        <tfoot className="border-t-2 bg-slate-50 font-semibold"><tr>{colonnes.map((_, i) => (
          <td key={i} className={`p-2 ${nombres.includes(i) ? "text-right tabular-nums" : ""}`}>
            {i === 0 ? `${triees.length}` : nombres.includes(i) ? nombre(triees.reduce((s, l) => s + (Number(l[i]) || 0), 0)) : ""}
          </td>))}</tr></tfoot>
      </table>
    </div>
  );
}
