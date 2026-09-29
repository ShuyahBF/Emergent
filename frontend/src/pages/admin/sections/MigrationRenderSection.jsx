// =====================================================================
// Migration vers Render — sauvegarde complète du site vers MongoDB Atlas
// (toutes les collections + index) et Cloudflare R2 (archives EJSON,
// fichiers du stockage Emergent et du disque, secrets chiffrés).
// Backend : backend/routes/migration_render.py (/api/admin/migration/*).
// Les identifiants saisis ici ne sont JAMAIS enregistrés en clair par le serveur ;
// ils peuvent être mémorisés dans un coffre CHIFFRÉ (restitués avec son mot de passe).
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Database, Cloud, KeyRound, Play, RefreshCw, Download, CheckCircle2, XCircle, AlertTriangle, Square, RotateCcw, Lock, Unlock, Trash2 } from "lucide-react";
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

// Barre de progression simple
const Barre = ({ fait, total }) => {
  const pct = total ? Math.round((fait / total) * 100) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
      <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
};

const CHAMPS_VIDES = {
  mongo_uri: "", mongo_db: "sawali", remplacer: false,
  r2_account_id: "", r2_access_key_id: "", r2_secret_access_key: "", r2_bucket: "sawali-migration",
  copier_base: true, copier_fichiers: true, sauver_secrets: true, mot_de_passe_secrets: "",
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

  // Suivi en direct d'une sauvegarde (toutes les 3 s tant qu'elle tourne)
  const suivre = useCallback(async (id) => {
    clearTimeout(minuterie.current);
    try {
      const { data } = await apiClient.get(`/admin/migration/jobs/${id}`);
      setJob(data);
      if (data.statut === "EN_COURS") minuterie.current = setTimeout(() => suivre(id), 3000);
      else charger();
    } catch {
      minuterie.current = setTimeout(() => suivre(id), 5000);
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
      : "Lancer la sauvegarde de migration ? Le site reste utilisable pendant la copie.";
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
    setForm((f) => ({ ...f, reprendre: j.id, remplacer: false, mongo_db: j.cible?.mongo_db || f.mongo_db, r2_bucket: j.cible?.r2_bucket || f.r2_bucket }));
    toast.info("Ressaisissez l'URI Atlas, les clés R2 et le mot de passe, puis cliquez sur « Reprendre ».");
    document.querySelector('[data-testid="migration-render-section"]')?.scrollIntoView({ behavior: "smooth" });
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
        Copie <b>complète</b> du site vers la nouvelle infrastructure : toutes les collections MongoDB (avec leurs index) vers
        <b> MongoDB Atlas</b>, une archive de chaque collection, les fichiers (stockage Emergent + disque) et les variables
        d'environnement <b>chiffrées</b> vers <b>Cloudflare R2</b>. Relançable à volonté ; pour la bascule finale, cochez « Remplacer ».
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
          <p className="font-semibold">MongoDB Atlas (nouvelle base)</p>
          <PasswordInput className={champ} placeholder="mongodb+srv://utilisateur:motdepasse@cluster.xxxxx.mongodb.net" value={form.mongo_uri} onChange={maj("mongo_uri")} autoComplete="off" />
          <input className={champ} placeholder="Nom de la base (ex. sawali)" value={form.mongo_db} onChange={maj("mongo_db")} />
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={form.remplacer} onChange={maj("remplacer")} />
            <span><b>Remplacer</b> (vider chaque collection cible avant copie). À utiliser pour la bascule finale ; sinon les données sont fusionnées.</span>
          </label>
          <p className="text-xs text-slate-500">Dans Atlas : Network Access doit autoriser 0.0.0.0/0 pendant la migration (les adresses d'Emergent ne sont pas fixes).</p>
        </div>
        <div className="space-y-2 rounded-xl border border-slate-200 p-4">
          <p className="font-semibold">Cloudflare R2 (archives et fichiers)</p>
          <input className={champ} placeholder="Account ID" value={form.r2_account_id} onChange={maj("r2_account_id")} autoComplete="off" />
          <input className={champ} placeholder="Access Key ID" value={form.r2_access_key_id} onChange={maj("r2_access_key_id")} autoComplete="off" />
          <PasswordInput className={champ} placeholder="Secret Access Key" value={form.r2_secret_access_key} onChange={maj("r2_secret_access_key")} autoComplete="off" />
          <input className={champ} placeholder="Bucket (privé), ex. sawali-migration" value={form.r2_bucket} onChange={maj("r2_bucket")} />
        </div>
      </div>

      {/* ---------- Options ---------- */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.copier_base} onChange={maj("copier_base")} /> Base de données</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.copier_fichiers} onChange={maj("copier_fichiers")} /> Fichiers</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.sauver_secrets} onChange={maj("sauver_secrets")} /> Variables d'environnement (chiffrées)</label>
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
        {envoi ? "Vérification des connexions…" : enCours ? "Sauvegarde en cours…" : form.reprendre ? "Reprendre la sauvegarde" : "Lancer la sauvegarde de migration"}
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
              {job.en_cours?.fichier && <span>Fichier {job.en_cours.faits}/{job.en_cours.total} : <span className="font-mono">{job.en_cours.fichier}</span></span>}
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
          {job.options?.fichiers && job.fichiers_total > 0 && (
            <div className="space-y-1 text-sm">
              <p>Fichiers : {job.fichiers_copies}/{job.fichiers_total} copiés{job.fichiers_echecs ? ` · ${job.fichiers_echecs} échec(s)` : ""}</p>
              <Barre fait={job.fichiers_copies + job.fichiers_echecs} total={job.fichiers_total} />
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
          {job.echecs_fichiers?.length > 0 && (
            <details className="text-sm">
              <summary className="flex cursor-pointer items-center gap-1 font-semibold text-orange-700"><AlertTriangle className="h-4 w-4" /> Fichiers en échec ({job.fichiers_echecs})</summary>
              <ul className="mt-1 max-h-40 overflow-y-auto font-mono text-xs">
                {job.echecs_fichiers.map((e) => <li key={e.source}>{e.source} — {e.erreur}</li>)}
              </ul>
            </details>
          )}
          <details className="text-xs">
            <summary className="cursor-pointer font-semibold">Journal</summary>
            <pre className="mt-1 max-h-56 overflow-y-auto whitespace-pre-wrap rounded bg-slate-900 p-2 text-slate-100">{(job.journal || []).join("\n")}</pre>
          </details>
        </div>
      )}

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
