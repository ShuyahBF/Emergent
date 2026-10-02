// =====================================================================
// Lot 49 — Sauvegarde / transfert des données (Admin)
// - Export « Tous les éléments » : toutes les collections + index, fichier chiffré par une
//   phrase secrète, téléchargeable UNE fois, effacé du serveur au plus tard 1 h après ;
// - Import : « Base vide uniquement » ou « Remplacer » (REMPLACER + mot de passe), rapport ;
// - Sauvegarde automatique quotidienne vers Cloudflare R2 (03:00), liste des sauvegardes et
//   « Restaurer ».
// Backend : backend/routes/sauvegarde_complete.py (/api/admin/sauvegarde-complete/*).
// Les instantanés existants (« Sauvegarde de la base (Snapshot) ») ne changent pas.
// =====================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CloudUpload, Database, Download, HardDriveDownload, Loader2, Play, RefreshCw, RotateCcw, ShieldAlert, Upload, XCircle } from "lucide-react";
import { toast } from "sonner";
import { API, apiClient } from "@/lib/api";
import PasswordInput from "@/components/PasswordInput";

const STATUTS = {
  EN_COURS: ["En cours…", "bg-amber-100 text-amber-800"],
  TERMINE: ["Terminé", "bg-emerald-100 text-emerald-800"],
  TERMINE_AVEC_ANOMALIES: ["Terminé avec anomalies", "bg-orange-100 text-orange-800"],
  ECHEC: ["Échec", "bg-red-100 text-red-700"],
  INTERROMPUE: ["Interrompue", "bg-slate-200 text-slate-700"],
};
const TYPES = { export: "Export complet", import: "Import", auto: "Sauvegarde automatique", restauration: "Restauration initiale", restauration_r2: "Restauration depuis R2" };
const Statut = ({ valeur }) => {
  const [libelle, classe] = STATUTS[valeur] || [valeur, "bg-slate-100 text-slate-700"];
  return <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${classe}`}>{libelle}</span>;
};
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const taille = (o) => (o > 1073741824 ? `${(o / 1073741824).toFixed(2)} Go` : o > 1048576 ? `${(o / 1048576).toFixed(1)} Mo` : `${Math.round((o || 0) / 1024)} Ko`);
const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const champ = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm";

const Barre = ({ fait, total }) => {
  const pct = total ? Math.min(100, Math.round((fait / total) * 100)) : 0;
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
      <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
};

// Suivi d'une tâche (export, import, restauration) : progression, journal, rapport
const SuiviTache = ({ tache, onTelecharger }) => {
  if (!tache) return null;
  const p = tache.progression || {};
  const r = tache.rapport || {};
  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3 text-sm" data-testid="sauvegarde-suivi">
      <div className="flex flex-wrap items-center gap-2">
        <strong>{TYPES[tache.type] || tache.type}</strong> <Statut valeur={tache.statut} />
        <span className="text-xs text-slate-500">{tache.etape}</span>
      </div>
      {tache.statut === "EN_COURS" && p.documents_total > 0 && (
        <div className="space-y-1">
          <Barre fait={p.documents} total={p.documents_total} />
          <p className="text-xs text-slate-500">
            {p.collections_faites || 0} / {p.collections_total || 0} collections · {p.documents || 0} / {p.documents_total} documents
            {p.collection ? ` · ${p.collection}` : ""}
          </p>
        </div>
      )}
      {tache.erreur && <p className="rounded bg-red-50 p-2 text-xs text-red-700">{tache.erreur}</p>}
      {tache.type === "export" && tache.statut === "TERMINE" && (
        tache.efface_le || tache.telecharge_le ? (
          <p className="text-xs text-slate-500">Fichier {tache.telecharge_le ? "téléchargé" : "expiré"} puis effacé du serveur.</p>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => onTelecharger(tache)} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700" data-testid="sauvegarde-telecharger">
              <Download className="h-3.5 w-3.5" /> Télécharger ({taille(tache.taille)}) — une seule fois
            </button>
            <span className="text-xs text-slate-500">Effacé automatiquement à {dateHeure(tache.expire_le)}.</span>
          </div>
        )
      )}
      {Array.isArray(r.comparaisons) && (
        <details className="text-xs" open={(r.anomalies || []).length > 0}>
          <summary className="cursor-pointer font-semibold">
            Rapport : {r.collections} collections, {r.documents_en_base} / {r.documents_attendus} documents,
            {" "}{(r.anomalies || []).length} anomalie(s) · signature : {r.signature}
          </summary>
          <div className="mt-2 max-h-72 overflow-auto">
            <table className="w-full text-left">
              <thead><tr className="text-slate-500"><th>Collection</th><th>Attendus</th><th>En base</th><th>Index</th><th /></tr></thead>
              <tbody>
                {r.comparaisons.map((c) => (
                  <tr key={c.collection} className={c.ok ? "" : "bg-orange-50"}>
                    <td className="pr-2 font-mono">{c.collection}</td><td>{c.attendus}</td><td>{c.en_base}</td>
                    <td>{c.index_recrees}/{c.index_attendus}</td>
                    <td>{c.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <span title={(c.erreurs || []).join("\n")}><XCircle className="h-3.5 w-3.5 text-orange-600" /></span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-slate-500">Redémarrez le service backend après un import pour recharger les réglages.</p>
        </details>
      )}
      {(tache.journal || []).length > 0 && (
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer">Journal</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2">{tache.journal.slice(-30).join("\n")}</pre>
        </details>
      )}
    </div>
  );
};

// Alerte en tête des Paramètres : sauvegarde automatique désactivée ou trop ancienne
export const AlerteSauvegardeAuto = () => {
  const [alerte, setAlerte] = useState(null);
  useEffect(() => {
    apiClient.get("/admin/sauvegarde-complete/etat").then((r) => setAlerte(r.data?.auto?.alerte || null)).catch(() => {});
  }, []);
  if (!alerte) return null;
  return (
    <a href="#s-sauvegarde-transfert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800" data-testid="alerte-sauvegarde-auto">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
      <span><strong>Sauvegarde hors serveur :</strong> {alerte} <span className="underline">Voir « Sauvegarde / transfert des données »</span></span>
    </a>
  );
};

// Garde-fou du mode « Remplacer » : le mot REMPLACER et le mot de passe de l'administrateur
const ConfirmationRemplacer = ({ confirmation, setConfirmation, motDePasse, setMotDePasse, prefixe }) => (
  <div className="grid gap-3 sm:grid-cols-2">
    <label className="text-xs font-medium text-red-700">Tapez REMPLACER
      <input value={confirmation} onChange={(e) => setConfirmation(e.target.value)} className={champ} placeholder="REMPLACER" data-testid={`${prefixe}-confirmation`} />
    </label>
    <label className="text-xs font-medium text-red-700">Votre mot de passe
      <PasswordInput value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)} className={champ} testid={`${prefixe}-mot-de-passe`} />
    </label>
  </div>
);

export default function SauvegardeTransfertSection() {
  const [etat, setEtat] = useState(null);
  const [tache, setTache] = useState(null);
  const [phrase, setPhrase] = useState("");
  const [phrase2, setPhrase2] = useState("");
  const [compris, setCompris] = useState(false);
  const [fichier, setFichier] = useState(null);
  const [phraseImport, setPhraseImport] = useState("");
  const [mode, setMode] = useState("vide");
  const [confirmation, setConfirmation] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [r2, setR2] = useState(null);
  const [aRestaurer, setARestaurer] = useState(null); // élément R2 choisi
  const [phraseR2, setPhraseR2] = useState("");
  const [occupe, setOccupe] = useState(false);
  const minuterie = useRef(null);
  const fichierRef = useRef(null);

  const charger = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/sauvegarde-complete/etat");
      setEtat(r.data);
    } catch (e) {
      toast.error(erreurDe(e, "Lecture de l'état impossible"));
    }
  }, []);
  const chargerR2 = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/sauvegarde-complete/r2");
      setR2(r.data);
    } catch (e) {
      setR2({ configure: true, erreur: erreurDe(e, "Lecture de R2 impossible"), elements: [] });
    }
  }, []);
  useEffect(() => { charger(); chargerR2(); return () => clearTimeout(minuterie.current); }, [charger, chargerR2]);

  // Suivi d'une tâche jusqu'à sa fin (toutes les 2 s)
  const suivre = useCallback((id) => {
    clearTimeout(minuterie.current);
    const tour = async () => {
      try {
        const r = await apiClient.get(`/admin/sauvegarde-complete/taches/${id}`);
        setTache(r.data);
        if (r.data.statut === "EN_COURS") { minuterie.current = setTimeout(tour, 2000); return; }
        charger();
        if (r.data.statut === "TERMINE") toast.success(`${TYPES[r.data.type] || "Tâche"} terminé`);
        else toast.error(r.data.erreur || "La tâche ne s'est pas terminée correctement");
      } catch (e) {
        if (e?.response?.status === 401) {
          setTache((t) => ({ ...(t || {}), statut: "TERMINE", etape: "Session terminée : la base a été remplacée, reconnectez-vous avec un compte de la sauvegarde." }));
          return;
        }
        minuterie.current = setTimeout(tour, 4000);
      }
    };
    tour();
  }, [charger]);

  const lancerExport = async () => {
    if (phrase.length < (etat?.phrase_min || 12)) return toast.error(`Phrase secrète : ${etat?.phrase_min || 12} caractères au minimum`);
    if (phrase !== phrase2) return toast.error("Les deux phrases ne sont pas identiques");
    if (!compris) return toast.error("Cochez la case d'avertissement");
    setOccupe(true);
    try {
      const r = await apiClient.post("/admin/sauvegarde-complete/export", { phrase });
      setTache(r.data);
      setPhrase(""); setPhrase2("");
      suivre(r.data.id);
    } catch (e) {
      toast.error(erreurDe(e, "Export impossible"));
    } finally {
      setOccupe(false);
    }
  };

  const telecharger = async (t) => {
    try {
      const r = await apiClient.post(`/admin/sauvegarde-complete/taches/${t.id}/lien`);
      // Le navigateur télécharge directement (lien à usage unique, sans jeton de session)
      window.location.href = `${API}${r.data.url.replace(/^\/api/, "")}`;
      setTimeout(() => suivre(t.id), 4000);
    } catch (e) {
      toast.error(erreurDe(e, "Téléchargement impossible"));
    }
  };

  const lancerImport = async () => {
    if (!fichier) return toast.error("Choisissez un fichier .sawali");
    if (!phraseImport) return toast.error("Saisissez la phrase secrète du fichier");
    if (mode === "remplacer" && confirmation !== "REMPLACER") return toast.error("Tapez REMPLACER pour confirmer");
    if (mode === "remplacer" && !motDePasse) return toast.error("Saisissez votre mot de passe");
    setOccupe(true);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      fd.append("phrase", phraseImport);
      fd.append("mode", mode);
      fd.append("confirmation", confirmation);
      fd.append("mot_de_passe", motDePasse);
      const r = await apiClient.post("/admin/sauvegarde-complete/import", fd, { headers: { "Content-Type": "multipart/form-data" }, timeout: 0 });
      setTache(r.data);
      setPhraseImport(""); setMotDePasse(""); setConfirmation(""); setFichier(null);
      if (fichierRef.current) fichierRef.current.value = "";
      suivre(r.data.id);
    } catch (e) {
      toast.error(erreurDe(e, "Import impossible"));
    } finally {
      setOccupe(false);
    }
  };

  const lancerAuto = async () => {
    try {
      await apiClient.post("/admin/sauvegarde-complete/r2/lancer");
      toast.success("Sauvegarde lancée : elle apparaîtra dans la liste à la fin");
      setTimeout(() => { charger(); }, 3000);
    } catch (e) {
      toast.error(erreurDe(e, "Lancement impossible"));
    }
  };

  const restaurerR2 = async () => {
    if (confirmation !== "REMPLACER") return toast.error("Tapez REMPLACER pour confirmer");
    if (!motDePasse) return toast.error("Saisissez votre mot de passe");
    setOccupe(true);
    try {
      const r = await apiClient.post("/admin/sauvegarde-complete/r2/restaurer", {
        cle: aRestaurer.cle, phrase: phraseR2, confirmation, mot_de_passe: motDePasse,
      });
      setTache(r.data);
      setARestaurer(null); setConfirmation(""); setMotDePasse(""); setPhraseR2("");
      suivre(r.data.id);
    } catch (e) {
      toast.error(erreurDe(e, "Restauration impossible"));
    } finally {
      setOccupe(false);
    }
  };

  const auto = etat?.auto;
  const enCours = tache?.statut === "EN_COURS";
  return (
    <div className="space-y-5 rounded-xl border-2 border-indigo-200 bg-indigo-50/30 p-6" data-testid="sauvegarde-transfert-section">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 font-display font-semibold"><Database className="h-5 w-5 text-indigo-600" /> Sauvegarde / transfert des données</h2>
          <p className="mt-1 text-xs text-slate-600">
            Sauvegarde de <strong>toute la base</strong> (toutes les collections et leurs index), pour la mettre à l'abri ou la
            transférer vers un autre serveur. Les instantanés ci-dessus restent disponibles tels quels.
          </p>
        </div>
        <button type="button" onClick={() => { charger(); chargerR2(); }} className="rounded-lg border border-slate-300 bg-white p-2 hover:bg-slate-50" title="Actualiser" data-testid="sauvegarde-actualiser">
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {/* État de la sauvegarde automatique */}
      {auto && (
        <div className={`rounded-lg border p-3 text-sm ${auto.alerte ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`} data-testid="sauvegarde-auto-etat">
          <p className="flex items-center gap-2 font-semibold">
            {auto.alerte ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
            Sauvegarde automatique quotidienne vers R2 : {auto.active ? `active, chaque jour à ${auto.heure}` : "désactivée"}
          </p>
          {auto.alerte && <p className="mt-1">{auto.alerte}</p>}
          <p className="mt-1 text-xs">
            Dernière réussite : {auto.derniere_reussite ? `${dateHeure(auto.derniere_reussite.le)} (${taille(auto.derniere_reussite.taille)})` : "aucune"}
            {auto.dernier_echec && <> · Dernier échec : {dateHeure(auto.dernier_echec.le)} — {auto.dernier_echec.erreur}</>}
          </p>
          <p className="mt-1 text-xs text-slate-600">
            Rétention : {auto.retention?.quotidiennes} quotidiennes, {auto.retention?.hebdomadaires} hebdomadaires, {auto.retention?.mensuelles} mensuelles.
            {auto.r2?.configure ? <> Bucket <code>{auto.r2.bucket}</code>, dossier <code>{auto.r2.prefixe}</code> (identifiants {auto.r2.source}).</> : " R2 non configuré."}
            {" "}Phrase de chiffrement : variable <code>SAUVEGARDE_AUTO_PHRASE</code> {auto.phrase_definie ? "définie" : "absente"} (jamais affichée ni enregistrée en base).
          </p>
        </div>
      )}

      {/* Export */}
      <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="flex items-center gap-2 font-semibold"><HardDriveDownload className="h-4 w-4" /> Exporter — Tous les éléments</h3>
        <div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <ShieldAlert className="h-4 w-4 shrink-0" />
          <p>
            Le fichier contient <strong>toutes les données et tous les secrets</strong> rangés en base (jetons WhatsApp, SMTP, clés d'API,
            empreintes des mots de passe…), <strong>non masqués</strong>, pour permettre une restauration complète. Il est chiffré
            (AES-256-GCM) par votre phrase secrète : sans elle il est illisible, et <strong>elle ne peut pas être retrouvée</strong>.
            Conservez-la à part (gestionnaire de mots de passe). Le fichier se télécharge <strong>une seule fois</strong> et est effacé du
            serveur au plus tard {etat?.duree_fichier_min || 60} minutes après sa création.
            {etat && !etat.signature_possible && " Ce serveur n'a pas de JWT_SECRET sûr : le fichier ne sera pas signé et ne pourra pas servir à une restauration initiale."}
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-slate-600">Phrase secrète ({etat?.phrase_min || 12} caractères minimum)
            <PasswordInput value={phrase} onChange={(e) => setPhrase(e.target.value)} className={champ} autoComplete="new-password" testid="export-phrase" />
          </label>
          <label className="text-xs font-medium text-slate-600">Confirmez la phrase
            <PasswordInput value={phrase2} onChange={(e) => setPhrase2(e.target.value)} className={champ} autoComplete="new-password" testid="export-phrase2" />
          </label>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={compris} onChange={(e) => setCompris(e.target.checked)} data-testid="export-compris" />
          J'ai compris : le fichier contient tous les secrets, je garde la phrase en lieu sûr.
        </label>
        <button type="button" disabled={occupe || enCours} onClick={lancerExport} className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50" data-testid="export-lancer">
          {occupe ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Lancer l'export complet
        </button>
      </div>

      <SuiviTache tache={tache} onTelecharger={telecharger} />

      {/* Import */}
      <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="flex items-center gap-2 font-semibold"><Upload className="h-4 w-4" /> Importer un export complet (.sawali)</h3>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-medium text-slate-600">Fichier
            <input ref={fichierRef} type="file" accept=".sawali" onChange={(e) => setFichier(e.target.files?.[0] || null)} className="mt-1 block w-full text-sm" data-testid="import-fichier" />
          </label>
          <label className="text-xs font-medium text-slate-600">Phrase secrète du fichier
            <PasswordInput value={phraseImport} onChange={(e) => setPhraseImport(e.target.value)} className={champ} autoComplete="off" testid="import-phrase" />
          </label>
        </div>
        <div className="space-y-1 text-sm">
          <label className="flex items-start gap-2">
            <input type="radio" name="mode-import" checked={mode === "vide"} onChange={() => setMode("vide")} data-testid="import-mode-vide" />
            <span><strong>Base vide uniquement</strong> — pour un nouveau serveur. Refusé si la base contient déjà des données (seuls sont
              tolérés les réglages créés au démarrage, les journaux techniques et votre compte d'administrateur initial, qui sera remplacé
              par les comptes de la sauvegarde).
              {etat && !etat.import_vide_possible && <span className="block text-xs text-orange-700">La base actuelle n'est pas vide : ce mode sera refusé.</span>}
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input type="radio" name="mode-import" checked={mode === "remplacer"} onChange={() => setMode("remplacer")} data-testid="import-mode-remplacer" />
            <span><strong>Remplacer</strong> — chaque collection présente dans le fichier est <strong>vidée puis rechargée</strong>. Les collections
              absentes du fichier sont conservées. Irréversible : faites d'abord un export de la base actuelle.</span>
          </label>
        </div>
        {mode === "remplacer" && <ConfirmationRemplacer confirmation={confirmation} setConfirmation={setConfirmation} motDePasse={motDePasse} setMotDePasse={setMotDePasse} prefixe="import" />}
        <button type="button" disabled={occupe || enCours} onClick={lancerImport} className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-50 ${mode === "remplacer" ? "bg-red-600 hover:bg-red-700" : "bg-indigo-600 hover:bg-indigo-700"}`} data-testid="import-lancer">
          {occupe ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} {mode === "remplacer" ? "Remplacer la base" : "Importer"}
        </button>
        <p className="text-xs text-slate-500">Le fichier est entièrement contrôlé (phrase, intégrité) avant toute écriture. Un rapport compare ensuite les nombres de documents et d'index.</p>
      </div>

      {/* Sauvegardes R2 */}
      <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 font-semibold"><CloudUpload className="h-4 w-4" /> Sauvegardes hors serveur (Cloudflare R2)</h3>
          <button type="button" disabled={!auto?.active} onClick={lancerAuto} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold hover:bg-slate-50 disabled:opacity-50" data-testid="r2-lancer">
            <Play className="h-3.5 w-3.5" /> Sauvegarder maintenant
          </button>
        </div>
        {r2 && !r2.configure && <p className="text-xs text-slate-500">R2 n'est pas configuré sur ce serveur (variables R2_SAUVEGARDES_* ou R2_STOCKS_*).</p>}
        {r2?.erreur && <p className="text-xs text-red-700">{r2.erreur}</p>}
        {r2?.configure && !r2.erreur && (
          (r2.elements || []).length === 0 ? <p className="text-xs text-slate-500">Aucune sauvegarde dans R2 pour l'instant.</p> : (
            <div className="max-h-80 overflow-auto">
              <table className="w-full text-left text-xs" data-testid="r2-liste">
                <thead><tr className="text-slate-500"><th className="py-1">Date</th><th>Taille</th><th>Conservée comme</th><th /></tr></thead>
                <tbody>
                  {r2.elements.map((e) => (
                    <tr key={e.cle} className="border-t border-slate-100">
                      <td className="py-1.5" title={e.cle}>{dateHeure(e.date)}</td>
                      <td>{e.taille_lisible}</td>
                      <td>{(e.conservee || []).join(", ") || "—"}</td>
                      <td className="text-right">
                        <button type="button" onClick={() => { setARestaurer(e); setConfirmation(""); setMotDePasse(""); }} className="inline-flex items-center gap-1 rounded border border-red-200 px-2 py-1 font-semibold text-red-700 hover:bg-red-50" data-testid="r2-restaurer">
                          <RotateCcw className="h-3 w-3" /> Restaurer
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
        {aRestaurer && (
          <div className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm" data-testid="r2-restaurer-formulaire">
            <p><strong>Restaurer la sauvegarde du {dateHeure(aRestaurer.date)}</strong> en mode <strong>Remplacer</strong> : chaque collection
              présente dans la sauvegarde est vidée puis rechargée.</p>
            <label className="block text-xs font-medium text-slate-600">Phrase secrète (laisser vide pour utiliser SAUVEGARDE_AUTO_PHRASE de ce serveur)
              <PasswordInput value={phraseR2} onChange={(e) => setPhraseR2(e.target.value)} className={champ} autoComplete="off" testid="r2-phrase" />
            </label>
            <ConfirmationRemplacer confirmation={confirmation} setConfirmation={setConfirmation} motDePasse={motDePasse} setMotDePasse={setMotDePasse} prefixe="r2" />
            <div className="flex gap-2">
              <button type="button" disabled={occupe || enCours} onClick={restaurerR2} className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50" data-testid="r2-restaurer-confirmer">Restaurer</button>
              <button type="button" onClick={() => setARestaurer(null)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs">Annuler</button>
            </div>
          </div>
        )}
      </div>

      {/* Historique */}
      {(etat?.taches || []).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold">Dernières opérations</summary>
          <table className="mt-2 w-full text-left">
            <tbody>
              {etat.taches.map((t) => (
                <tr key={t.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => (t.statut === "EN_COURS" ? suivre(t.id) : setTache(t))}>
                  <td className="py-1">{dateHeure(t.cree_le)}</td><td>{TYPES[t.type] || t.type}</td><td><Statut valeur={t.statut} /></td>
                  <td className="text-slate-500">{t.auteur}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
