// ============================================================================
// AppareilsAndroidSection.jsx — Lot 468 : Paramètres → « 📱 Appareils Android — Loois mobile ».
// Registre des téléphones / tablettes qui utilisent l'APK « Loois mobile » : identifiant de l'appareil, nom de l'utilisateur, adresse IP vue par le serveur à la dernière
// connexion, ÉTAT de l'accès (Autorisé / Interdit), zone de lancement et nom de la base de données (myAizenta-CMC, myAurora, myAizenta-PMT…).
// Un appareil qui s'enregistre arrive « Interdit » (badge « Nouveau ») : l'administrateur le renseigne puis l'autorise. Modification dans une FENÊTRE MODALE (règle 20) ;
// listes finies = listes déroulantes avec « Autre… » en fin de liste (règle 10) ; colonnes triables (règle 19) ; « Actualiser » avec toasts (règle 17).
// Backend : GET /api/admin/android-appareils, PUT …/{id}, POST …/{id}/reinitialiser, DELETE …/{id} (administrateur seul). L'APK utilise /api/android/appareil/*.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, KeyRound, Pencil, RefreshCw, Save, Smartphone, Trash2, XCircle, ShieldCheck, ShieldOff } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import ConnexionsRapidesBloc from "./ConnexionsRapidesBloc";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const AUTRE = "__autre__";

// Badge d'état : couleur ET pictogramme ET texte (jamais la couleur seule)
const Etat = ({ etat }) => etat === "autorise"
  ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800"><ShieldCheck className="h-3.5 w-3.5" /> Autorisé</span>
  : <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-800"><ShieldOff className="h-3.5 w-3.5" /> Interdit</span>;

export default function AppareilsAndroidSection() {
  const [liste, setListe] = useState(null);            // null = chargement
  const [zones, setZones] = useState([]);
  const [edition, setEdition] = useState(null);        // fiche en cours de modification (copie)
  const [enCours, setEnCours] = useState(false);
  const [autreZone, setAutreZone] = useState(false);   // « Autre… » choisi pour la zone

  const charger = useCallback(async (avecToast) => {
    if (avecToast) toast("Lecture des appareils en cours…");
    try {
      const r = await apiClient.get("/admin/android-appareils");
      setListe(r.data.appareils || []); setZones(r.data.zones || []);
      if (avecToast) toast.success(`${(r.data.appareils || []).length} appareil(s) lu(s).`);
    } catch (e) { setListe([]); if (avecToast) toast.error(e?.response?.data?.detail || "Lecture impossible"); }
  }, []);
  useEffect(() => { charger(false); }, [charger]);

  const { lignes, tri, basculer } = useTri(liste || [], {
    nom: (a) => a.nom_utilisateur, modele: (a) => a.modele, etat: (a) => a.etat, zone: (a) => a.zone, base: (a) => a.base, ip: (a) => a.ip_derniere, derniere: (a) => a.derniere_connexion || "",
  });

  const ouvrir = (a) => { setEdition({ ...a }); setAutreZone(!!a.zone && !zones.some((z) => z.cle === a.zone)); };
  // Choisir une zone connue propose sa base (modifiable) ; « Autre… » ouvre la saisie libre
  const choisirZone = (v) => {
    if (v === AUTRE) { setAutreZone(true); return; }
    setAutreZone(false);
    const z = zones.find((x) => x.cle === v);
    setEdition((e) => ({ ...e, zone: v, base: z ? z.base : e.base }));
  };

  const enregistrer = async () => {
    setEnCours(true); toast("Enregistrement en cours…");
    try {
      const { nom_utilisateur, zone, base, client_code, etat, notes, profil } = edition;
      await apiClient.put(`/admin/android-appareils/${edition.id}`, { nom_utilisateur, zone, base, client_code, etat, notes, profil: profil || "agent" });
      toast.success("Appareil enregistré."); setEdition(null); await charger(false);
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setEnCours(false); }
  };
  const reinitialiser = async () => {
    if (!window.confirm("Réinitialiser le jeton de cet appareil ?\n\nL'appareil ne pourra plus se connecter tant qu'il ne se sera pas ré-enregistré (utile après une réinstallation de l'application ou une réinitialisation du téléphone).")) return;
    try { await apiClient.post(`/admin/android-appareils/${edition.id}/reinitialiser`); toast.success("Jeton réinitialisé : l'appareil devra se ré-enregistrer."); setEdition(null); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Réinitialisation impossible"); }
  };
  const supprimer = async () => {
    if (!window.confirm("Supprimer définitivement la fiche de cet appareil ?")) return;
    try { await apiClient.delete(`/admin/android-appareils/${edition.id}`); toast.success("Appareil supprimé."); setEdition(null); await charger(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Suppression impossible"); }
  };
  const basculerEtat = (e, a) => { e.stopPropagation(); apiClient.put(`/admin/android-appareils/${a.id}`, { etat: a.etat === "autorise" ? "interdit" : "autorise" })
    .then(() => { toast.success(a.etat === "autorise" ? "Appareil interdit." : "Appareil autorisé."); charger(false); }).catch((x) => toast.error(x?.response?.data?.detail || "Modification impossible")); };

  // Journal d'audit des actions faites depuis les appareils (connexion, historique, détail d'un reçu, corrections) : lecture seule
  const [journal, setJournal] = useState(null);
  const chargerJournal = useCallback(async (avecToast) => {
    if (avecToast) toast("Lecture du journal en cours…");
    try { const r = await apiClient.get("/admin/android-journal", { params: { limite: 200 } }); setJournal(r.data.lignes || []); if (avecToast) toast.success(`${(r.data.lignes || []).length} ligne(s) du journal lue(s).`); }
    catch (e) { setJournal([]); if (avecToast) toast.error(e?.response?.data?.detail || "Lecture du journal impossible"); }
  }, []);
  const { lignes: journalTrie, tri: triJ, basculer: basculerJ } = useTri(journal || [], { quand: (j) => j.quand, login: (j) => j.login, action: (j) => j.action, detail: (j) => j.detail, resultat: (j) => j.resultat, ip: (j) => j.ip });

  // Serveurs locaux remontés par Loois (lot 480) : adresses des passerelles que les téléphones utilisent SANS Internet
  const [locaux, setLocaux] = useState(null);
  const chargerLocaux = useCallback(async (avecToast) => {
    if (avecToast) toast("Lecture des serveurs locaux en cours…");
    try { const r = await apiClient.get("/admin/serveurs-locaux"); setLocaux(r.data.clients || []); if (avecToast) toast.success(`${(r.data.clients || []).length} client(s) avec un serveur local.`); }
    catch (e) { setLocaux([]); if (avecToast) toast.error(e?.response?.data?.detail || "Lecture des serveurs locaux impossible"); }
  }, []);
  const regenererSecret = async (code) => {
    if (!window.confirm(`Créer un nouveau secret pour le client ${code} ?\n\nLes tickets et sessions des téléphones deviennent invalides : ils se reconnecteront (Internet requis une fois) ; les services Windows récupèrent le nouveau secret à leur prochain signalement.`)) return;
    try { await apiClient.post(`/admin/serveurs-locaux/${code}/regenerer`); toast.success("Nouveau secret créé."); chargerLocaux(false); }
    catch (e) { toast.error(e?.response?.data?.detail || "Régénération impossible"); }
  };
  // Nettoyage : supprime les appareils « Nouveau » (interdits, jamais renseignés) — jamais un appareil autorisé ou déjà renseigné. Aperçu et confirmation d'abord.
  const nettoyerNouveaux = async () => {
    try {
      const a = await apiClient.post("/admin/android-appareils/nettoyer", { apercu: true });
      if (!a.data.nombre) { toast("Aucun appareil « Nouveau » à nettoyer."); return; }
      if (!window.confirm(`Supprimer ${a.data.nombre} appareil(s) « Nouveau » (interdits, jamais renseignés) ?\n\nModèles : ${a.data.modeles.join(", ")}\n\nUn vrai appareil supprimé se ré-enregistrera tout seul à son prochain lancement. Les appareils autorisés ou renseignés ne sont jamais touchés.`)) return;
      toast("Nettoyage en cours…");
      const r = await apiClient.post("/admin/android-appareils/nettoyer", {});
      toast.success(`${r.data.supprimes} appareil(s) supprimé(s).`); charger(false);
    } catch (e) { toast.error(e?.response?.data?.detail || "Nettoyage impossible"); }
  };

  const nouveaux = useMemo(() => (liste || []).filter((a) => a.nouveau).length, [liste]);

  return (
    <div className="space-y-3" data-testid="appareils-android">
      <p className="text-sm text-slate-600">
        Téléphones et tablettes qui utilisent l'application « Loois mobile ». Un appareil qui s'enregistre arrive <b>Interdit</b> : renseignez-le (utilisateur, zone, base) puis autorisez-le.
        L'adresse IP est celle que <b>le serveur</b> voit à la dernière connexion.
      </p>
      <div className="flex flex-wrap items-center gap-2 boutons-distincts">
        <button type="button" onClick={() => charger(true)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold" data-testid="appareils-actualiser"><RefreshCw className="h-4 w-4" /> Actualiser</button>
        {nouveaux > 0 && <button type="button" onClick={nettoyerNouveaux} className="inline-flex items-center gap-1 rounded-full border border-red-300 px-3 py-1.5 text-sm font-semibold text-red-800" data-testid="appareils-nettoyer"><Trash2 className="h-4 w-4" /> Nettoyer les nouveaux</button>}
        {nouveaux > 0 && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900" data-testid="appareils-nouveaux">{nouveaux} nouvel(le)(s) appareil(s) à renseigner</span>}
      </div>

      <div className="max-h-[30rem] overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm" data-testid="appareils-table">
          <thead className="sticky top-0 bg-slate-50"><tr className="text-left text-slate-600">
            <ThTri cle="nom" tri={tri} onTri={basculer}>Utilisateur</ThTri>
            <ThTri cle="modele" tri={tri} onTri={basculer}>Appareil</ThTri>
            <ThTri cle="etat" tri={tri} onTri={basculer}>État</ThTri>
            <ThTri cle="zone" tri={tri} onTri={basculer}>Zone</ThTri>
            <ThTri cle="base" tri={tri} onTri={basculer}>Base de données</ThTri>
            <ThTri cle="ip" tri={tri} onTri={basculer}>IP (vue par le serveur)</ThTri>
            <ThTri cle="derniere" tri={tri} onTri={basculer}>Dernière connexion</ThTri>
            <th className="p-2">Actions</th>
          </tr></thead>
          <tbody>
            {lignes.map((a) => (
              <tr key={a.id} className="cursor-pointer border-t align-top" onClick={() => ouvrir(a)} data-testid={`appareil-${a.id}`}>
                <td className="p-2 font-semibold text-sky-800">{a.nom_utilisateur || <span className="italic text-slate-400">à renseigner</span>}{a.nouveau && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-bold text-amber-900">NOUVEAU</span>}</td>
                <td className="p-2"><span className="flex items-center gap-1"><Smartphone className="h-4 w-4 text-slate-500" />{a.modele || "—"}</span><span className="text-[11px] text-slate-500">v{a.version_app || "?"} · {a.id}{a.profil === "client" && <span className="ml-1 rounded bg-sky-100 px-1 font-bold text-sky-800">CLIENT</span>}</span></td>
                <td className="p-2"><Etat etat={a.etat} /></td>
                <td className="p-2">{a.zone ? <code>/{a.zone}</code> : "—"}</td>
                <td className="p-2 font-medium text-indigo-800">{a.base || "—"}</td>
                <td className="whitespace-nowrap p-2 tabular-nums">{a.ip_derniere || "—"}</td>
                <td className="whitespace-nowrap p-2 tabular-nums">{quand(a.derniere_connexion)}</td>
                <td className="p-2">
                  <div className="flex items-center gap-1">
                    <button type="button" onClick={(e) => basculerEtat(e, a)} title={a.etat === "autorise" ? "Interdire cet appareil" : "Autoriser cet appareil"} aria-label={a.etat === "autorise" ? "Interdire" : "Autoriser"}
                      className={`inline-flex h-8 items-center gap-1 rounded-full border px-2 text-xs font-semibold ${a.etat === "autorise" ? "border-red-300 text-red-800" : "border-emerald-300 text-emerald-800"}`}>
                      {a.etat === "autorise" ? <><XCircle className="h-4 w-4" /> Interdire</> : <><CheckCircle2 className="h-4 w-4" /> Autoriser</>}</button>
                    <button type="button" title="Modifier" aria-label="Modifier" className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-sky-300 text-sky-800"><Pencil className="h-4 w-4" /></button>
                  </div>
                </td>
              </tr>))}
            {liste !== null && lignes.length === 0 && <tr><td colSpan={8} className="p-3 text-slate-500">Aucun appareil enregistré pour l'instant. Ils apparaîtront ici dès le premier lancement de l'application.</td></tr>}
            {liste === null && <tr><td colSpan={8} className="p-3 text-slate-500">Lecture en cours…</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Lot 484 : connexions rapides (biométrie, Google, clé d'accès) */}
      <ConnexionsRapidesBloc />

      {/* Serveurs locaux remontés par Loois : le téléphone les reçoit tout seul dans son statut (rien à saisir) */}
      <details className="rounded-lg border border-slate-200 p-3" onToggle={(e) => { if (e.currentTarget.open && locaux === null) chargerLocaux(false); }} data-testid="serveurs-locaux">
        <summary className="cursor-pointer font-semibold text-slate-800">Serveurs locaux remontés par Loois (accès sans Internet)</summary>
        <div className="mt-2 space-y-2">
          <p className="text-xs text-slate-600">Chaque service Windows Loois signale l'adresse de sa passerelle (réseau local), son serveur HFSQL, sa zone et sa base — jamais de mot de passe. Les téléphones autorisés reçoivent ces adresses avec un ticket valable 72 h.</p>
          <button type="button" onClick={() => chargerLocaux(true)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold"><RefreshCw className="h-4 w-4" /> Actualiser les serveurs locaux</button>
          {locaux !== null && locaux.length === 0 && <p className="text-sm text-slate-500">Aucun service Loois ne s'est encore signalé (la passerelle arrive avec la prochaine mise à jour de Loois).</p>}
          {(locaux || []).map((c) => (
            <div key={c.client} className="rounded-lg border border-slate-200">
              <div className="flex items-center justify-between bg-slate-50 px-3 py-2"><span className="font-bold text-sky-800">Client {c.client}</span>
                <button type="button" onClick={() => regenererSecret(c.client)} className="inline-flex items-center gap-1 rounded-full border border-amber-300 px-3 py-1 text-xs font-semibold text-amber-900"><KeyRound className="h-3.5 w-3.5" /> Régénérer le secret</button></div>
              <table className="min-w-full text-sm"><thead><tr className="text-left text-slate-600"><th className="p-2">Machine</th><th className="p-2">Adresse de la passerelle</th><th className="p-2">Serveur HFSQL</th><th className="p-2">Zone · base</th><th className="p-2">Vu le</th></tr></thead>
                <tbody>{c.machines.map((m) => (<tr key={m.poste} className="border-t"><td className="p-2 font-semibold">{m.poste}</td><td className="p-2 tabular-nums text-indigo-800">{(m.ips || []).map((ip) => `${ip}:${m.port}`).join(" · ")}</td><td className="p-2">{m.serveur_hfsql || "—"}</td>
                  <td className="p-2">{m.zone ? `/${m.zone}` : "—"} · {m.base || "—"}</td><td className="whitespace-nowrap p-2 tabular-nums">{quand(m.vu_le)}</td></tr>))}</tbody></table>
            </div>))}
        </div>
      </details>

      {/* Journal d'activité (audit) : qui a fait quoi depuis quel appareil — jamais de mot de passe */}
      <details className="rounded-lg border border-slate-200 p-3" onToggle={(e) => { if (e.currentTarget.open && journal === null) chargerJournal(false); }} data-testid="appareils-journal">
        <summary className="cursor-pointer font-semibold text-slate-800">Journal d'activité des appareils</summary>
        <div className="mt-2 space-y-2">
          <button type="button" onClick={() => chargerJournal(true)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-3 py-1.5 text-sm font-semibold"><RefreshCw className="h-4 w-4" /> Actualiser le journal</button>
          <div className="max-h-80 overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-full text-sm"><thead className="sticky top-0 bg-slate-50"><tr className="text-left text-slate-600">
              <ThTri cle="quand" tri={triJ} onTri={basculerJ}>Date et heure</ThTri><ThTri cle="login" tri={triJ} onTri={basculerJ}>Utilisateur</ThTri><ThTri cle="action" tri={triJ} onTri={basculerJ}>Action</ThTri>
              <ThTri cle="detail" tri={triJ} onTri={basculerJ}>Détail</ThTri><ThTri cle="resultat" tri={triJ} onTri={basculerJ}>Résultat</ThTri><ThTri cle="ip" tri={triJ} onTri={basculerJ}>IP</ThTri></tr></thead>
              <tbody>{journalTrie.map((j, i) => (
                <tr key={i} className="border-t"><td className="whitespace-nowrap p-2 tabular-nums">{quand(j.quand)}</td><td className="p-2 font-semibold text-sky-800">{j.login || "—"}</td><td className="p-2">{j.action}</td><td className="p-2">{j.detail}</td>
                  <td className="p-2"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${j.resultat === "ok" ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>{j.resultat === "ok" ? "✔ ok" : `✖ ${j.resultat}`}</span></td><td className="whitespace-nowrap p-2 tabular-nums">{j.ip || "—"}</td></tr>))}
                {journal !== null && journalTrie.length === 0 && <tr><td colSpan={6} className="p-3 text-slate-500">Aucune activité enregistrée.</td></tr>}</tbody></table>
          </div>
        </div>
      </details>

      {/* Fenêtre modale d'édition (règle 20) */}
      <Dialog open={!!edition} onOpenChange={(ouvert) => { if (!ouvert) setEdition(null); }}>
        <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="appareil-edition">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><Smartphone className="h-5 w-5 text-sky-700" /> Appareil {edition?.modele || ""}</DialogTitle></DialogHeader>
          {edition && (
            <div className="space-y-3 text-sm">
              <p className="text-xs text-slate-500">Identifiant {edition.id} · enregistré le {quand(edition.cree_le)} · IP au premier lancement {edition.ip_premiere || "—"} · version {edition.version_app || "?"}</p>
              <label className="block font-semibold text-slate-700">Nom de l'utilisateur
                <input value={edition.nom_utilisateur || ""} onChange={(e) => setEdition({ ...edition, nom_utilisateur: e.target.value })} placeholder="BADINI Awa" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" data-testid="appareil-nom" /></label>
              <label className="block font-semibold text-slate-700">État de l'accès
                <select value={edition.etat} onChange={(e) => setEdition({ ...edition, etat: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal" data-testid="appareil-etat">
                  <option value="interdit">Interdit</option><option value="autorise">Autorisé</option></select></label>
              <label className="block font-semibold text-slate-700">Profil de l'appareil
                <select value={edition.profil || "agent"} onChange={(e) => setEdition({ ...edition, profil: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal" data-testid="appareil-profil">
                  <option value="agent">Agent — caisse et corrections selon les droits Loois</option><option value="client">Client — tableau de bord de suivi (responsable d'établissement)</option></select></label>
              <label className="block font-semibold text-slate-700">Zone de lancement
                <select value={autreZone ? AUTRE : (edition.zone || "")} onChange={(e) => choisirZone(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 font-normal" data-testid="appareil-zone">
                  <option value="">— Aucune —</option>
                  {zones.map((z) => <option key={z.cle} value={z.cle}>{z.libelle} (/{z.cle})</option>)}
                  <option value={AUTRE}>Autre…</option></select></label>
              {autreZone && <input value={edition.zone || ""} onChange={(e) => setEdition({ ...edition, zone: e.target.value })} placeholder="docx=IPM" className="w-full rounded-lg border border-slate-300 px-3 py-2" data-testid="appareil-zone-libre" />}
              <label className="block font-semibold text-slate-700">Base de données
                <input value={edition.base || ""} onChange={(e) => setEdition({ ...edition, base: e.target.value })} placeholder="myAizenta-CMC" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" data-testid="appareil-base" /></label>
              <label className="block font-semibold text-slate-700">Code client (SQL à distance)
                <input value={edition.client_code || ""} onChange={(e) => setEdition({ ...edition, client_code: e.target.value.toUpperCase() })} placeholder="CMC" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" data-testid="appareil-client" /></label>
              <label className="block font-semibold text-slate-700">Notes
                <textarea value={edition.notes || ""} onChange={(e) => setEdition({ ...edition, notes: e.target.value })} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-normal" /></label>
              {(edition.journal || []).length > 0 && (
                <details className="rounded-lg border border-slate-200 p-2"><summary className="cursor-pointer font-semibold text-slate-700">Dernières connexions ({edition.journal.length})</summary>
                  <ul className="mt-1 space-y-0.5 text-xs text-slate-600">{[...edition.journal].reverse().map((j, i) => <li key={i} className="tabular-nums">{quand(j.quand)} · {j.ip || "—"} · {j.resultat}</li>)}</ul></details>)}
              <div className="flex flex-wrap items-center justify-between gap-2 boutons-distincts">
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={enregistrer} disabled={enCours} data-testid="appareil-enregistrer" className="inline-flex items-center gap-1 rounded-full bg-sky-700 px-4 py-2 font-semibold text-white disabled:opacity-50"><Save className="h-4 w-4" /> Enregistrer</button>
                  <button type="button" onClick={() => setEdition(null)} className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 font-semibold"><XCircle className="h-4 w-4" /> Fermer</button>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={reinitialiser} className="inline-flex items-center gap-1 rounded-full border border-amber-300 px-3 py-2 font-semibold text-amber-900" title="Efface le jeton : l'appareil devra se ré-enregistrer"><KeyRound className="h-4 w-4" /> Réinitialiser le jeton</button>
                  <button type="button" onClick={supprimer} className="inline-flex items-center gap-1 rounded-full border border-red-300 px-3 py-2 font-semibold text-red-800"><Trash2 className="h-4 w-4" /> Supprimer</button>
                </div>
              </div>
            </div>)}
        </DialogContent>
      </Dialog>
    </div>
  );
}
