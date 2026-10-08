// =====================================================================
// Migration vers Render — sauvegarde complète du site vers MongoDB Atlas
// (toutes les collections + index) et Cloudflare R2 (archives EJSON,
// fichiers du stockage Emergent et du disque, secrets chiffrés).
// Backend : backend/routes/migration_render.py (/api/admin/migration/*).
// Les identifiants saisis ici ne sont JAMAIS enregistrés en clair par le serveur ;
// ils peuvent être mémorisés dans un coffre CHIFFRÉ (restitués avec son mot de passe).
// Lot 47 : sauvegardes programmées (tous les N jours à heure fixe), rétention dans R2
// et rapport envoyé à l'admin par Liluvine (bloc « Sauvegardes programmées et rétention »).
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Database, Cloud, KeyRound, Play, RefreshCw, Download, CheckCircle2, XCircle, AlertTriangle, Square, RotateCcw, Lock, Unlock, Trash2, CalendarClock, Save } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";

// Libellés et couleurs des statuts d'une sauvegarde
const STATUTS = {
  EN_COURS: ["En cours…", "bg-amber-100 text-amber-800"],
  TERMINEE: ["Terminée", "bg-emerald-100 text-emerald-800"],
  TERMINEE_AVEC_ERREURS: ["Terminée avec anomalies", "bg-orange-100 text-orange-800"],
  ECHEC: ["Échec", "bg-red-100 text-red-700"],
  INTERROMPUE: ["Interrompue", "bg-slate-200 text-slate-700"],
};
// Sauvegardes qui peuvent être reprises (les collections déjà copiées sont sautées)
const REPRENABLES = ["INTERROMPUE", "ECHEC", "TERMINEE_AVEC_ERREURS"];

// Secondes écoulées depuis un horodatage ISO -> texte court (« 12 s », « 3 min »)
const depuis = (iso) => {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 90 ? `${s} s` : `${Math.round(s / 60)} min`;
};
const Statut = ({ valeur }) => {
  const [libelle, classe] = STATUTS[valeur] || [valeur, "bg-slate-100 text-slate-700"];
  return <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${classe}`}>{libelle}</span>;
};

// Octets -> texte lisible
const taille = (o) => (o > 1048576 ? `${(o / 1048576).toFixed(1)} Mo` : o > 1024 ? `${Math.round(o / 1024)} Ko` : `${o || 0} o`);
// Octets -> Mo avec une décimale (avancement du fichier en cours)
const enMo = (o) => ((o || 0) / 1048576).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// Fichier en cours (signe de vie périodique) : octets reçus / taille, puis octets envoyés à R2
const AvancementFichier = ({ cours }) => {
  if (!cours?.recus && !cours?.taille && !cours?.envoyes) return null;
  const sur = cours.taille ? `${enMo(cours.taille)} Mo` : "taille inconnue";
  return cours.phase === "envoi"
    ? <span className="text-slate-500">· envoi vers R2 : {enMo(cours.envoyes)} / {sur}</span>
    : <span className="text-slate-500">· reçu {enMo(cours.recus)} / {sur}</span>;
};

// Barre de progression simple
const Barre = ({ fait, total }) => {
  const pct = total ? Math.round((fait / total) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
      <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
};

// Date ISO -> « 30/09/2026 14:05 » (heure du navigateur)
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

// Réglage par défaut des sauvegardes programmées (le serveur renvoie le réglage enregistré)
const REGLAGE_DEFAUT = {
  actif: false, tous_les: 1, heure: "03:00", fuseau: "Africa/Ouagadougou",
  base: true, fichiers: true, medias: true,
  retention_jours: 14, garder_min: 3, purge_manuelles: true,
  rapport_si_ok: true, modele_wa: "", modele_wa_langue: "fr",
};

// =====================================================================
// Sauvegardes programmées et rétention (Admin) : réglage, identifiants
// conservés chiffrés par le serveur (jamais renvoyés), purge des anciennes
// sauvegardes dans R2 et rapport envoyé par Liluvine.
// Backend : backend/routes/migration_programmation.py
// =====================================================================
const ProgrammationSauvegardes = ({ form, enCours, charger, suivre, actualisation }) => {
  const [etat, setEtat] = useState(null); // réglage + état renvoyés par le serveur
  const [reglage, setReglage] = useState(REGLAGE_DEFAUT);
  const [occupe, setOccupe] = useState("");

  // État du serveur ; le réglage affiché n'est remplacé qu'au premier chargement,
  // pour ne pas effacer une saisie en cours quand l'historique se met à jour
  const chargerEtat = useCallback(async (avecReglage = false) => {
    try {
      const { data } = await apiClient.get("/admin/migration/programmation");
      setEtat(data);
      if (avecReglage) setReglage({ ...REGLAGE_DEFAUT, ...data.reglage });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Programmation indisponible");
    }
  }, []);
  useEffect(() => { chargerEtat(true); }, [chargerEtat]);
  // Rechargé aussi quand l'historique change (fin d'une sauvegarde, purge...)
  useEffect(() => { if (actualisation) chargerEtat(); }, [chargerEtat, actualisation]);

  const majR = (champ) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? Number(e.target.value) : e.target.value;
    setReglage((r) => ({ ...r, [champ]: v }));
  };

  // Action serveur avec indicateur d'attente et message d'erreur
  const agir = async (nom, appel, succes) => {
    setOccupe(nom);
    try {
      const reponse = await appel();
      if (succes) toast.success(typeof succes === "function" ? succes(reponse.data) : succes);
      return reponse.data;
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible");
      return null;
    } finally {
      setOccupe("");
    }
  };

  const enregistrer = async () => {
    const data = await agir("reglage", () => apiClient.put("/admin/migration/programmation", reglage), "Programmation enregistrée");
    if (data) { setEtat(data); setReglage({ ...REGLAGE_DEFAUT, ...data.reglage }); }
  };

  // Identifiants saisis plus haut (ou restaurés du coffre) -> gardés chiffrés par le serveur
  const utiliserIdentifiants = async () => {
    const { mongo_uri, mongo_db, r2_account_id, r2_access_key_id, r2_secret_access_key, r2_bucket } = form;
    if (!r2_account_id || !r2_access_key_id || !r2_secret_access_key || !r2_bucket) {
      toast.error("Saisissez ou restaurez (coffre) les identifiants R2 (et l'URI Atlas si la base est sauvegardée).");
      return;
    }
    const data = await agir("identifiants",
      () => apiClient.put("/admin/migration/programmation/identifiants", { mongo_uri, mongo_db, r2_account_id, r2_access_key_id, r2_secret_access_key, r2_bucket }),
      "Identifiants vérifiés et enregistrés (chiffrés) pour les sauvegardes programmées");
    if (data) setEtat(data);
  };

  const oublierIdentifiants = async () => {
    if (!window.confirm("Effacer les identifiants des sauvegardes programmées ? La programmation sera désactivée.")) return;
    const data = await agir("oubli", () => apiClient.delete("/admin/migration/programmation/identifiants"), "Identifiants effacés");
    if (data) { setEtat(data); setReglage({ ...REGLAGE_DEFAUT, ...data.reglage }); }
  };

  const lancerMaintenant = async () => {
    if (!window.confirm("Lancer maintenant une sauvegarde avec les réglages enregistrés (mode fusion) ? Rapport et purge suivront.")) return;
    const data = await agir("lancer", () => apiClient.post("/admin/migration/programmation/lancer"), (d) => `Sauvegarde lancée (${d.prefixe})`);
    if (data) { suivre(data.id); chargerEtat(); }
  };

  const purgerMaintenant = async () => {
    if (!window.confirm(`Supprimer de R2 les sauvegardes de plus de ${reglage.retention_jours} jour(s), en gardant toujours les ${reglage.garder_min} dernières réussies ? (réglage enregistré)`)) return;
    const data = await agir("purge", () => apiClient.post("/admin/migration/programmation/purger"),
      (d) => `${d.supprimees.length} sauvegarde(s) supprimée(s), ${taille(d.octets)} libéré(s)`);
    if (data) { chargerEtat(); charger(); }
  };

  const champ = "rounded-lg border border-slate-300 px-3 py-2 text-sm";
  const ids = etat?.identifiants || { existe: false };
  const derniere = etat?.derniere_execution;
  const purge = etat?.derniere_purge;

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 p-4" data-testid="migration-programmation">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-semibold"><CalendarClock className="h-4 w-4" /> Sauvegardes programmées et rétention</p>
        <span className="text-xs text-slate-500">
          Prochaine exécution : <b>{etat?.prochaine_execution ? dateHeure(etat.prochaine_execution) : "aucune"}</b>
          {etat?.attente && <> · en attente ({etat.attente})</>}
        </span>
      </div>

      {/* Identifiants des sauvegardes programmées : jamais renvoyés par le serveur */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-3 text-sm">
        <Lock className="h-4 w-4 text-slate-500" />
        {ids.existe ? (
          <span className="text-xs text-slate-600">
            Identifiants enregistrés le {dateHeure(ids.cree_le)} par {ids.par} · Atlas {ids.mongo_hote || "— (fichiers seulement)"} / {ids.mongo_db} · bucket <b>{ids.r2_bucket}</b>
            {!ids.lisibles && <b className="ml-1 text-red-700">— illisibles (clé du serveur changée) : enregistrez-les à nouveau</b>}
          </span>
        ) : (
          <span className="text-xs text-slate-600">Aucun identifiant enregistré pour les sauvegardes programmées.</span>
        )}
        <button type="button" onClick={utiliserIdentifiants} disabled={!!occupe}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-slate-100 disabled:opacity-50 sm:ml-auto">
          <KeyRound className="h-3 w-3" /> {occupe === "identifiants" ? "Vérification…" : "Utiliser ces identifiants pour les sauvegardes programmées"}
        </button>
        {ids.existe && (
          <button type="button" onClick={oublierIdentifiants} disabled={!!occupe} className="inline-flex items-center gap-1 px-2 py-1.5 text-xs text-red-700 hover:underline">
            <Trash2 className="h-3 w-3" /> Oublier
          </button>
        )}
        <p className="w-full text-xs text-slate-500">
          Prend l'URI Atlas et les clés R2 saisies plus haut, vérifie les connexions puis les garde chiffrés sur le serveur (AES-256, clé du serveur).
          Ils ne sont jamais réaffichés. {ids.source_cle && `Clé utilisée : ${ids.source_cle}.`}
        </p>
      </div>

      {/* Réglage */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2 text-sm">
          <label className="flex items-center gap-2 font-semibold"><input type="checkbox" checked={reglage.actif} onChange={majR("actif")} /> Activer les sauvegardes programmées</label>
          <div className="flex flex-wrap items-center gap-2">
            Tous les <input type="number" min={1} max={365} className={`${champ} w-20`} value={reglage.tous_les} onChange={majR("tous_les")} /> jour(s) à
            <input type="time" className={champ} value={reglage.heure} onChange={majR("heure")} />
            <span className="text-xs text-slate-500">({reglage.fuseau})</span>
          </div>
          <p className="text-xs text-slate-500">1 = tous les jours. Serveur arrêté à l'heure prévue : la sauvegarde est faite au redémarrage, une seule fois.</p>
          <div className="flex flex-wrap gap-x-5 gap-y-1">
            <label className="flex items-center gap-2"><input type="checkbox" checked={reglage.base} onChange={majR("base")} /> Base de données</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={reglage.fichiers} onChange={majR("fichiers")} /> Fichiers</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={reglage.medias} onChange={majR("medias")} disabled={!reglage.fichiers} /> Médias (vidéos et sons)</label>
            <label className="flex items-center gap-2 text-slate-400" title={etat?.explication_secrets}><input type="checkbox" checked={false} disabled /> Variables d'environnement</label>
          </div>
          <p className="text-xs text-slate-500">Toujours en mode fusion (jamais « Remplacer »). {etat?.explication_secrets}</p>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            Garder les sauvegardes <input type="number" min={1} max={3650} className={`${champ} w-20`} value={reglage.retention_jours} onChange={majR("retention_jours")} /> jour(s),
            et toujours les <input type="number" min={1} max={100} className={`${champ} w-16`} value={reglage.garder_min} onChange={majR("garder_min")} /> dernières réussies
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={reglage.purge_manuelles} onChange={majR("purge_manuelles")} /> Appliquer aussi la rétention aux sauvegardes manuelles</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={reglage.rapport_si_ok} onChange={majR("rapport_si_ok")} /> M'envoyer le rapport même quand tout va bien</label>
          <div className="flex flex-wrap items-center gap-2">
            <input className={`${champ} w-56`} placeholder="Modèle Meta (hors fenêtre 24 h)" value={reglage.modele_wa} onChange={majR("modele_wa")} />
            <input className={`${champ} w-20`} placeholder="fr" value={reglage.modele_wa_langue} onChange={majR("modele_wa_langue")} />
          </div>
          <p className="text-xs text-slate-500">
            Rapport signé Liluvine envoyé par WhatsApp aux numéros admin de Liluvine (Paramètres → Liluvine). Si l'admin n'a pas écrit à Liluvine depuis 24 h,
            le modèle Meta indiqué (une variable {"{{1}}"}) est utilisé ; sinon, ou en cas d'échec, le rapport part par e-mail. Un échec est toujours signalé.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={enregistrer} disabled={!!occupe}
          className="inline-flex items-center gap-1 rounded-lg bg-sky-600 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-50">
          <Save className="h-4 w-4" /> Enregistrer
        </button>
        <button type="button" onClick={lancerMaintenant} disabled={!!occupe || enCours || !ids.existe}
          className="inline-flex items-center gap-1 rounded-lg border border-sky-300 px-4 py-2 text-sm font-semibold text-sky-700 hover:bg-sky-50 disabled:opacity-50">
          <Play className="h-4 w-4" /> Lancer maintenant avec ces réglages
        </button>
        <button type="button" onClick={purgerMaintenant} disabled={!!occupe || !ids.existe}
          className="inline-flex items-center gap-1 rounded-lg border border-red-300 px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50">
          <Trash2 className="h-4 w-4" /> {occupe === "purge" ? "Purge…" : "Purger maintenant"}
        </button>
      </div>

      {/* Dernière exécution programmée et dernière purge */}
      <div className="grid gap-2 text-xs sm:grid-cols-2">
        <div className="rounded-lg border border-slate-100 p-2">
          <p className="font-semibold">Dernière exécution programmée</p>
          {derniere ? (
            <p className="mt-1 flex flex-wrap items-center gap-2">
              {dateHeure(derniere.debut)} <Statut valeur={derniere.statut} /> {derniere.prefixe && <span className="font-mono">{derniere.prefixe}</span>}
              {derniere.erreur && <span className="text-red-700">{derniere.erreur}</span>}
              {derniere.rapport && <span className="text-slate-500">· rapport {derniere.rapport.envoye ? "envoyé" : "non envoyé"}</span>}
            </p>
          ) : <p className="mt-1 text-slate-500">Aucune</p>}
        </div>
        <div className="rounded-lg border border-slate-100 p-2">
          <p className="font-semibold">Dernière purge</p>
          {purge && !purge.erreur ? (
            <p className="mt-1 text-slate-600">
              {dateHeure(purge.le)} · {purge.supprimees?.length || 0} sauvegarde(s) supprimée(s), {taille(purge.octets)} libéré(s) · {purge.gardees} gardée(s)
              {purge.erreurs > 0 && <b className="text-red-700"> · {purge.erreurs} objet(s) non supprimé(s)</b>}
            </p>
          ) : <p className="mt-1 text-slate-500">{purge?.erreur || "Aucune"}</p>}
        </div>
      </div>

      <p className="text-xs text-slate-500">Les sauvegardes supprimées de R2 par la rétention restent dans l'historique ci-dessous avec le badge « purgée ».</p>
    </div>
  );
};

const CHAMPS_VIDES = {
  mongo_uri: "", mongo_db: "sawali", remplacer: false,
  r2_account_id: "", r2_access_key_id: "", r2_secret_access_key: "", r2_bucket: "sawali-migration",
  copier_base: true, copier_fichiers: true, sauver_secrets: true, mot_de_passe_secrets: "",
  copier_medias: true, // décoché : vidéos et sons non copiés (choix conservé en reprise)
  reprendre: null, // identifiant de la sauvegarde à reprendre (null = nouvelle sauvegarde)
};

const MigrationRenderSection = () => {
  const [inventaire, setInventaire] = useState(null); // contenu actuel du site
  const [jobs, setJobs] = useState([]); // historique des sauvegardes
  const [job, setJob] = useState(null); // sauvegarde affichée en détail
  const [form, setForm] = useState(CHAMPS_VIDES);
  const [envoi, setEnvoi] = useState(false);
  const minuterie = useRef(null);
  const [coffre, setCoffre] = useState({ existe: false }); // état du coffre (jamais son contenu)
  const [mdpCoffre, setMdpCoffre] = useState(""); // mot de passe du coffre (jamais enregistré)

  // Chargement de l'inventaire et de l'historique
  const charger = useCallback(async () => {
    try {
      const [inv, hist] = await Promise.all([apiClient.get("/admin/migration/inventaire"), apiClient.get("/admin/migration/jobs")]);
      setInventaire(inv.data);
      setJobs(hist.data || []);
      const c = await apiClient.get("/admin/migration/coffre");
      setCoffre(c.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Inventaire indisponible");
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Suivi en direct d'une sauvegarde (toutes les 8 s tant qu'elle tourne)
  const suivre = useCallback(async (id) => {
    clearTimeout(minuterie.current);
    try {
      const { data } = await apiClient.get(`/admin/migration/jobs/${id}`);
      setJob(data);
      // Lot 79.6 — toutes les 8 s (au lieu de 3) : la réponse contient tout le journal de la sauvegarde
      if (data.statut === "EN_COURS") minuterie.current = setTimeout(() => suivre(id), 8000);
      else charger();
    } catch {
      minuterie.current = setTimeout(() => suivre(id), 10000);
    }
  }, [charger]);
  useEffect(() => () => clearTimeout(minuterie.current), []);

  const maj = (champ) => (e) => setForm({ ...form, [champ]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  // Lancement : vérification des connexions côté serveur, puis tâche en arrière-plan
  const lancer = async () => {
    const avertissement = form.reprendre
      ? "Reprendre la sauvegarde interrompue ? Les collections déjà copiées seront sautées."
      : form.remplacer
      ? "Mode REMPLACER : chaque collection de la base cible sera VIDÉE puis recopiée. Continuer ?"
      : "Sauvegarder maintenant ? Le site reste utilisable pendant la copie.";
    if (!window.confirm(avertissement)) return;
    setEnvoi(true);
    try {
      const { data } = await apiClient.post("/admin/migration/lancer", form);
      toast.success(`Sauvegarde lancée (${data.prefixe})`);
      setForm((f) => ({ ...f, mot_de_passe_secrets: "", reprendre: null }));
      suivre(data.id);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Lancement impossible");
    } finally {
      setEnvoi(false);
    }
  };

  // Arrêt d'une sauvegarde en cours (pris en compte au lot suivant ; reprise possible ensuite)
  const arreter = async (id) => {
    if (!window.confirm("Arrêter cette sauvegarde ? Vous pourrez la reprendre plus tard.")) return;
    try {
      await apiClient.post(`/admin/migration/jobs/${id}/arreter`);
      toast.success("Arrêt demandé");
      suivre(id);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Arrêt impossible");
    }
  };

  // ---------- Coffre des identifiants (chiffré côté serveur avec le mot de passe saisi) ----------
  // Mot de passe utilisé : celui du coffre s'il est saisi, sinon le mot de passe de chiffrement des secrets
  const motDePasseCoffre = () => mdpCoffre || form.mot_de_passe_secrets;

  const memoriser = async () => {
    const mdp = motDePasseCoffre();
    if ((mdp || "").length < 12) {
      toast.error("Saisissez un mot de passe de 12 caractères minimum (coffre ou chiffrement)");
      return;
    }
    try {
      const { mongo_uri, mongo_db, r2_account_id, r2_access_key_id, r2_secret_access_key, r2_bucket } = form;
      await apiClient.put("/admin/migration/coffre", { mot_de_passe: mdp, mongo_uri, mongo_db, r2_account_id, r2_access_key_id, r2_secret_access_key, r2_bucket });
      toast.success("Identifiants mémorisés (chiffrés)");
      setMdpCoffre("");
      charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Mémorisation impossible");
    }
  };

  const restaurer = async () => {
    const mdp = motDePasseCoffre();
    if (!mdp) {
      toast.error("Saisissez le mot de passe du coffre");
      return;
    }
    try {
      const { data } = await apiClient.post("/admin/migration/coffre/ouvrir", { mot_de_passe: mdp });
      // Seuls les champs présents dans le coffre remplacent ceux du formulaire
      setForm((f) => ({ ...f, ...Object.fromEntries(Object.entries(data).filter(([, v]) => v)) }));
      toast.success("Identifiants restaurés");
      setMdpCoffre("");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Restauration impossible");
    }
  };

  const oublier = async () => {
    if (!window.confirm("Effacer définitivement les identifiants mémorisés ?")) return;
    try {
      await apiClient.delete("/admin/migration/coffre");
      toast.success("Coffre effacé");
      charger();
    } catch {
      toast.error("Effacement impossible");
    }
  };

  // Préparation d'une reprise : les identifiants (jamais enregistrés) doivent être ressaisis
  const preparerReprise = (j) => {
    // Le choix « Copier les médias » de la sauvegarde reprise est conservé (le serveur l'impose aussi).
    // Une sauvegarde plus ancienne, sans ce choix enregistré, laisse la case modifiable.
    const choixMedias = typeof j.options?.medias === "boolean";
    setForm((f) => ({ ...f, reprendre: j.id, remplacer: false, mongo_db: j.cible?.mongo_db || f.mongo_db, r2_bucket: j.cible?.r2_bucket || f.r2_bucket,
      copier_medias: choixMedias ? j.options.medias : f.copier_medias, medias_verrouille: choixMedias }));
    toast.info("Ressaisissez l'URI Atlas, les clés R2 et le mot de passe, puis cliquez sur « Reprendre ».");
    document.querySelector('[data-testid="migration-render-section"]')?.scrollIntoView({ behavior: "smooth" });
  };

  // « Réessayer les échecs » : reprise de l'étape Fichiers seulement (ni base, ni secrets).
  // Les objets déjà présents dans R2 sont sautés. Seuls les identifiants R2 sont nécessaires.
  const reessayerEchecs = async (j) => {
    const { r2_account_id, r2_access_key_id, r2_secret_access_key } = form;
    if (!r2_account_id || !r2_access_key_id || !r2_secret_access_key) {
      toast.error("Saisissez ou restaurez (coffre) les identifiants R2, puis réessayez.");
      return;
    }
    if (!window.confirm("Réessayer les fichiers en échec ? Seuls les fichiers absents de R2 seront recopiés (la base n'est pas recopiée).")) return;
    setEnvoi(true);
    try {
      const { data } = await apiClient.post(`/admin/migration/jobs/${j.id}/reessayer-echecs`, { ...form, r2_bucket: j.cible?.r2_bucket || form.r2_bucket });
      toast.success(`Nouvelle tentative lancée (${data.prefixe})`);
      suivre(data.id);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Nouvelle tentative impossible");
    } finally {
      setEnvoi(false);
    }
  };

  // Export CSV des fichiers en échec (UTF-8 avec BOM, séparateur « ; », ouvrable dans Excel)
  const exporterEchecs = async (j) => {
    try {
      const { data } = await apiClient.get(`/admin/migration/jobs/${j.id}/echecs.csv`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url; a.download = `sawali-migration-echecs-${j.cible?.prefixe || j.id}.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Export impossible");
    }
  };

  // Téléchargement du fichier des secrets chiffré
  const telechargerSecrets = async (id) => {
    try {
      const { data } = await apiClient.get(`/admin/migration/jobs/${id}/secrets`, { responseType: "blob" });
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url; a.download = `sawali-secrets-${id}.enc.json`; a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Téléchargement impossible");
    }
  };

  const champ = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";
  const enCours = job?.statut === "EN_COURS" || jobs.some((j) => j.statut === "EN_COURS");

  return (
    <div className="space-y-5" data-testid="migration-render-section">
      <p className="text-sm text-slate-600">
        {/* Lot 57.11 — la migration est terminée : cette section sert désormais de sauvegarde complète */}
        Sauvegarde <b>complète</b> du site : toutes les collections MongoDB (avec leurs index) vers une
        <b> base Atlas de secours</b> (jamais la base en service : refusée automatiquement), une archive de chaque
        collection, les fichiers et les variables d'environnement <b>chiffrées</b> vers <b>Cloudflare R2</b>. Relançable à volonté.
      </p>

      {/* ---------- Inventaire ---------- */}
      {inventaire && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 p-3">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500"><Database className="h-4 w-4" /> Base</p>
            <p className="mt-1 text-lg font-bold">{inventaire.collections.length} collections</p>
            <p className="text-xs text-slate-500">{inventaire.total_documents.toLocaleString("fr-FR")} documents</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-3">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500"><Cloud className="h-4 w-4" /> Fichiers</p>
            <p className="mt-1 text-lg font-bold">{inventaire.fichiers.stored_objects + inventaire.fichiers.files_avec_storage_path} objets</p>
            <p className="text-xs text-slate-500">+ {inventaire.fichiers.uploads_local.fichiers} sur disque ({taille(inventaire.fichiers.uploads_local.octets)})</p>
          </div>
          <div className="rounded-xl border border-slate-200 p-3">
            <p className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-500"><KeyRound className="h-4 w-4" /> Variables</p>
            <p className="mt-1 text-lg font-bold">{inventaire.variables.filter((v) => v.definie).length} définies</p>
            <p className="text-xs text-slate-500">sur {inventaire.variables.length} connues</p>
          </div>
        </div>
      )}
      {inventaire && (
        <details className="rounded-lg border border-slate-200 p-3 text-sm">
          <summary className="cursor-pointer font-semibold">Détail des collections</summary>
          <div className="mt-2 grid max-h-64 grid-cols-2 gap-x-6 overflow-y-auto sm:grid-cols-3">
            {inventaire.collections.map((c) => (
              <div key={c.nom} className="flex justify-between border-b border-slate-100 py-0.5">
                <span className="truncate font-mono text-xs">{c.nom}</span><span className="text-xs text-slate-500">{c.documents}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* ---------- Coffre des identifiants ---------- */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
        <Lock className="h-4 w-4 text-slate-500" />
        <span className="font-semibold">Coffre des identifiants</span>
        <span className="text-xs text-slate-500">
          {coffre.existe
            ? `mémorisés le ${new Date(coffre.cree_le).toLocaleString("fr-FR")} (${(coffre.champs || []).length} champs)`
            : "vide"}
        </span>
        <div className="w-full sm:ml-auto sm:w-64">
          <PasswordInput className={champ} placeholder="Mot de passe du coffre" value={mdpCoffre} onChange={(e) => setMdpCoffre(e.target.value)} autoComplete="off" />
        </div>
        {coffre.existe && (
          <button type="button" onClick={restaurer} className="inline-flex items-center gap-1 rounded-lg bg-sky-600 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-700">
            <Unlock className="h-3 w-3" /> Restaurer
          </button>
        )}
        <button type="button" onClick={memoriser} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold hover:bg-white">
          <Lock className="h-3 w-3" /> Mémoriser les identifiants saisis
        </button>
        {coffre.existe && (
          <button type="button" onClick={oublier} className="inline-flex items-center gap-1 px-2 py-2 text-xs text-red-700 hover:underline">
            <Trash2 className="h-3 w-3" /> Oublier
          </button>
        )}
        <p className="w-full text-xs text-slate-500">
          Chiffrés sur le serveur (AES-256), jamais en clair. Mot de passe du coffre laissé vide = mot de passe de chiffrement des secrets (plus bas).
          5 essais faux bloquent le coffre 15 minutes.
        </p>
      </div>

      {/* ---------- Cible ---------- */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2 rounded-xl border border-slate-200 p-4">
          <p className="font-semibold">MongoDB Atlas (base de secours)</p>
          <PasswordInput className={champ} placeholder="mongodb+srv://utilisateur:motdepasse@cluster.xxxxx.mongodb.net" value={form.mongo_uri} onChange={maj("mongo_uri")} autoComplete="off" />
          <input className={champ} placeholder="Nom de la base (ex. sawali)" value={form.mongo_db} onChange={maj("mongo_db")} />
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={form.remplacer} onChange={maj("remplacer")} />
            <span><b>Remplacer</b> (vider chaque collection cible avant copie). Sinon, les données sont fusionnées dans la base de secours.</span>
          </label>
          <p className="text-xs text-slate-500">Dans Atlas : Network Access doit autoriser le serveur Render (0.0.0.0/0 ou ses adresses de sortie).</p>
        </div>
        <div className="space-y-2 rounded-xl border border-slate-200 p-4">
          <p className="font-semibold">Cloudflare R2 (archives et fichiers)</p>
          <input className={champ} placeholder="Account ID" value={form.r2_account_id} onChange={maj("r2_account_id")} autoComplete="off" />
          <input className={champ} placeholder="Access Key ID" value={form.r2_access_key_id} onChange={maj("r2_access_key_id")} autoComplete="off" />
          <PasswordInput className={champ} placeholder="Secret Access Key" value={form.r2_secret_access_key} onChange={maj("r2_secret_access_key")} autoComplete="off" />
          <input className={champ} placeholder="Bucket (privé), ex. sawali-sauvegardes" value={form.r2_bucket} onChange={maj("r2_bucket")} />
        </div>
      </div>

      {/* ---------- Options ---------- */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.copier_base} onChange={maj("copier_base")} /> Base de données</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.copier_fichiers} onChange={maj("copier_fichiers")} /> Fichiers</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.sauver_secrets} onChange={maj("sauver_secrets")} /> Variables d'environnement (chiffrées)</label>
        {/* Décoché : vidéos et sons (reconnus à l'extension ou au type annoncé) ne sont pas copiés ; en reprise, choix de la sauvegarde reprise */}
        <label className="flex items-center gap-2" title={form.reprendre && form.medias_verrouille ? "En reprise, le choix de la sauvegarde reprise est conservé" : ""}>
          <input type="checkbox" checked={form.copier_medias} onChange={maj("copier_medias")} disabled={!form.copier_fichiers || (!!form.reprendre && !!form.medias_verrouille)} /> Copier les médias (vidéos et sons)
        </label>
      </div>
      {form.sauver_secrets && (
        <div className="max-w-md">
          <PasswordInput className={champ} placeholder="Mot de passe de chiffrement (12 caractères min.)" value={form.mot_de_passe_secrets} onChange={maj("mot_de_passe_secrets")} autoComplete="new-password" />
          <p className="mt-1 text-xs text-slate-500">Conservez-le précieusement : il sera demandé pour relire les secrets sur Render. Il n'est jamais enregistré.</p>
        </div>
      )}

      {/* Reprise en préparation : rappel de la sauvegarde reprise + possibilité d'annuler */}
      {form.reprendre && (
        <p className="flex flex-wrap items-center gap-2 rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-900">
          <RotateCcw className="h-4 w-4" /> Reprise de la sauvegarde <b>{jobs.find((j) => j.id === form.reprendre)?.cible?.prefixe || form.reprendre}</b> :
          les collections déjà copiées seront sautées.
          <button type="button" onClick={() => setForm((f) => ({ ...f, reprendre: null }))} className="text-xs font-semibold underline">Annuler la reprise</button>
        </p>
      )}

      <button type="button" onClick={lancer} disabled={envoi || enCours}
        className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
        data-testid="migration-lancer">
        {form.reprendre ? <RotateCcw className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        {envoi ? "Vérification des connexions…" : enCours ? "Sauvegarde en cours…" : form.reprendre ? "Reprendre la sauvegarde" : "Sauvegarder maintenant"}
      </button>

      {/* ---------- Suivi de la sauvegarde sélectionnée ---------- */}
      {job && (
        <div className="space-y-3 rounded-xl border border-slate-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold">Sauvegarde {job.cible?.prefixe} <Statut valeur={job.statut} /></p>
            <span className="text-xs text-slate-500">{job.cible?.mongo_hote} / {job.cible?.mongo_db} · bucket {job.cible?.r2_bucket}</span>
          </div>
          {/* Avancement en direct : élément en cours + dernier signe de vie de la tâche */}
          {job.statut === "EN_COURS" && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">
              {job.en_cours?.saut && (
                <span>Relecture de <b className="font-mono">{job.en_cours.collection}</b> (déjà copiée)</span>
              )}
              {job.en_cours?.fichier && (
                <span>Fichier {job.en_cours.faits}/{job.en_cours.total} : <span className="font-mono">{job.en_cours.fichier}</span> <AvancementFichier cours={job.en_cours} /></span>
              )}
              {job.battement && <span className="text-slate-500">dernier signe de vie il y a {depuis(job.battement)}</span>}
              <button type="button" onClick={() => arreter(job.id)} className="ml-auto inline-flex items-center gap-1 font-semibold text-red-700 hover:underline">
                <Square className="h-3 w-3" /> Arrêter
              </button>
            </div>
          )}
          {REPRENABLES.includes(job.statut) && (
            <button type="button" onClick={() => preparerReprise(job)}
              className="inline-flex items-center gap-1 rounded-lg border border-sky-300 px-3 py-1.5 text-sm font-semibold text-sky-700 hover:bg-sky-50">
              <RotateCcw className="h-4 w-4" /> Reprendre cette sauvegarde
            </button>
          )}
          {job.options?.base && (() => {
            // Documents déjà traités = collections terminées (y compris sautées en reprise) + collection en cours
            const cours = job.statut === "EN_COURS" && job.en_cours?.collection && !job.en_cours.saut ? job.en_cours : null;
            const faitsDocs = (job.resultats_collections || []).reduce((s, r) => s + (r.source || 0), 0) + (cours?.copies || 0);
            const totalDocs = job.documents_total || 0;
            const pct = (f, t) => (t ? Math.min(100, Math.round((f / t) * 100)) : 0);
            return (
              <div className="space-y-2 text-sm">
                {/* Jauge 1 : collection en cours de copie */}
                {cours && (
                  <div className="space-y-1">
                    <p className="flex justify-between gap-2">
                      <span>Collection en cours : <b className="font-mono">{cours.collection}</b></span>
                      <span className="text-slate-500">{(cours.copies || 0).toLocaleString("fr-FR")} / {(cours.total || 0).toLocaleString("fr-FR")} documents · {pct(cours.copies, cours.total)} %</span>
                    </p>
                    <Barre fait={cours.copies || 0} total={cours.total || 0} />
                  </div>
                )}
                {/* Jauge 2 : progression totale de la base (en documents) */}
                <div className="space-y-1">
                  <p className="flex justify-between gap-2">
                    <span>Total base : {job.collections_faites}/{job.collections_total} collections</span>
                    <span className="text-slate-500">
                      {totalDocs ? `${faitsDocs.toLocaleString("fr-FR")} / ${totalDocs.toLocaleString("fr-FR")} documents · ${pct(faitsDocs, totalDocs)} %`
                        : `${job.documents_copies?.toLocaleString("fr-FR")} documents`}
                    </span>
                  </p>
                  {totalDocs ? <Barre fait={faitsDocs} total={totalDocs} /> : <Barre fait={job.collections_faites} total={job.collections_total} />}
                </div>
              </div>
            );
          })()}
          {/* Fichiers : copiés / absents à la source (ignorés, n'empêchent pas « Terminée ») / vraies erreurs */}
          {job.options?.fichiers && job.fichiers_total > 0 && (
            <div className="space-y-1 text-sm">
              <p>
                Fichiers ({job.fichiers_total}) : <b>{job.fichiers_copies || 0} copiés</b>
                {" · "}<span className="text-slate-500">{job.fichiers_absents || 0} absents à la source (ignorés)</span>
                {(job.options?.medias === false || job.fichiers_medias_ignores > 0) && (
                  <>{" · "}<span className="text-slate-500">{job.fichiers_medias_ignores || 0} médias ignorés (option)</span></>
                )}
                {" · "}<span className={job.fichiers_echecs ? "font-semibold text-red-700" : ""}>{job.fichiers_echecs || 0} vraies erreurs</span>
              </p>
              <Barre fait={(job.fichiers_copies || 0) + (job.fichiers_absents || 0) + (job.fichiers_medias_ignores || 0) + (job.fichiers_echecs || 0)} total={job.fichiers_total} />
            </div>
          )}
          {/* Échecs groupés par cause / code HTTP + actions */}
          {job.statut !== "EN_COURS" && (job.fichiers_echecs > 0 || job.fichiers_absents > 0 || job.echecs_fichiers?.length > 0) && (
            <div className="space-y-2 rounded-lg bg-orange-50 px-3 py-2 text-sm">
              {job.echecs_par_cause && Object.keys(job.echecs_par_cause).length > 0 && (
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  {Object.entries(job.echecs_par_cause).sort((a, b) => b[1] - a[1]).map(([cause, n]) => (
                    <li key={cause} className={cause.startsWith("absent") ? "text-slate-500" : "font-semibold text-orange-800"}>
                      {cause} : {n}{cause.startsWith("absent") ? " (ignorés)" : ""}
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => exporterEchecs(job)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-slate-50">
                  <Download className="h-3 w-3" /> Exporter CSV
                </button>
                {job.fichiers_echecs > 0 && REPRENABLES.includes(job.statut) && (
                  <button type="button" onClick={() => reessayerEchecs(job)} disabled={envoi || enCours}
                    className="inline-flex items-center gap-1 rounded-lg border border-sky-300 bg-white px-3 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-50 disabled:opacity-50">
                    <RotateCcw className="h-3 w-3" /> Réessayer les échecs
                  </button>
                )}
              </div>
            </div>
          )}
          {job.secrets && (
            <p className="flex items-center gap-2 text-sm">
              <KeyRound className="h-4 w-4" /> {job.secrets.nombre} variable(s) chiffrée(s)
              <button type="button" onClick={() => telechargerSecrets(job.id)} className="inline-flex items-center gap-1 text-sky-700 hover:underline">
                <Download className="h-4 w-4" /> Télécharger le fichier chiffré
              </button>
            </p>
          )}
          {/* Comparaison source / cible par collection */}
          {job.resultats_collections?.length > 0 && (
            <details className="text-sm" open={job.statut !== "EN_COURS"}>
              <summary className="cursor-pointer font-semibold">Contrôle par collection (source → cible)</summary>
              <table className="mt-2 w-full text-xs">
                <thead><tr className="text-left text-slate-500"><th>Collection</th><th>Source</th><th>Cible</th><th>Index</th><th>Archive</th><th /></tr></thead>
                <tbody>
                  {job.resultats_collections.map((r) => (
                    <tr key={r.nom} className="border-t border-slate-100">
                      <td className="font-mono">{r.nom}</td><td>{r.source}</td><td>{r.cible}</td><td>{r.index}</td><td>{taille(r.archive_octets)}</td>
                      <td>{r.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-red-600" />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {/* Détail : vraies erreurs d'abord, puis absents à la source (liste complète dans l'export CSV) */}
          {job.echecs_fichiers?.length > 0 && (
            <details className="text-sm">
              <summary className="flex cursor-pointer items-center gap-1 font-semibold text-orange-700"><AlertTriangle className="h-4 w-4" /> Vraies erreurs ({job.fichiers_echecs})</summary>
              <ul className="mt-1 max-h-40 overflow-y-auto font-mono text-xs">
                {job.echecs_fichiers.map((e, i) => (
                  <li key={`${e.source}-${i}`}>
                    {e.source} — {e.cause ? `${e.cause}${e.code ? ` (HTTP ${e.code})` : ""}` : e.erreur}
                    {e.origine && <span className="text-slate-500"> · {e.origine}</span>}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {job.absents_fichiers?.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer font-semibold text-slate-600">Absents à la source, ignorés ({job.fichiers_absents})</summary>
              <ul className="mt-1 max-h-40 overflow-y-auto font-mono text-xs text-slate-600">
                {job.absents_fichiers.map((e, i) => (
                  <li key={`${e.source}-${i}`}>{e.source}{e.origine && <span className="text-slate-400"> · {e.origine}</span>}</li>
                ))}
              </ul>
            </details>
          )}
          <details className="text-xs">
            <summary className="cursor-pointer font-semibold">Journal</summary>
            <pre className="mt-1 max-h-56 overflow-y-auto whitespace-pre-wrap rounded bg-slate-900 p-2 text-slate-100">{(job.journal || []).join("\n")}</pre>
          </details>
        </div>
      )}

      {/* ---------- Sauvegardes programmées et rétention ---------- */}
      <ProgrammationSauvegardes form={form} enCours={enCours} charger={charger} suivre={suivre} actualisation={jobs} />

      {/* ---------- Historique ---------- */}
      {jobs.length > 0 && (
        <div className="text-sm">
          <div className="mb-1 flex items-center justify-between">
            <p className="font-semibold">Historique</p>
            <button type="button" onClick={charger} className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900"><RefreshCw className="h-3 w-3" /> Actualiser</button>
          </div>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {jobs.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <span className="font-mono text-xs">{j.cible?.prefixe}</span>
                <Statut valeur={j.statut} />
                {j.programmee && <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-800">programmée</span>}
                {j.purgee && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-700" title={`Supprimée de R2 le ${dateHeure(j.purgee_le)}`}>purgée</span>}
                <span className="text-xs text-slate-500">{j.collections_faites}/{j.collections_total} coll. · {j.fichiers_copies}/{j.fichiers_total} fichiers · par {j.lance_par}</span>
                <button type="button" onClick={() => suivre(j.id)} className="ml-auto text-xs font-semibold text-sky-700 hover:underline">Détail</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default MigrationRenderSection;
