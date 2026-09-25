import React, { useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import {
  Database, Folder, Upload, RefreshCw, ArrowLeft, Send, Loader2,
  ChevronRight, CheckCircle2, AlertCircle, HardDrive, Search, X, Tag, FolderPlus, Settings2, ScanText,
} from "lucide-react";
import R2StorageGauge from "@/components/R2StorageGauge";
// Lot 22 — lignes de fichiers avec tags (édition, suggestions IA) et pastilles de filtre.
import { R2FileRow, TagChip } from "@/components/R2FileTags";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip as RTooltip } from "recharts";

/*
  Portail → "Gestion de Stocks" (Pharmacien suivi).
  Schéma fourni par l'utilisateur : deux blocs empilés.
    1. Explorateur BD MongoDB Atlas — 3 boutons Analyseur + zone de prompt
       libre. Le backend (/gestion-stocks/analyse) calcule des agrégats
       Mongo scopés au client_code (jamais de requête générée par le LLM),
       puis demande à Claude (via LlmChat) une analyse en français à partir
       de ces seuls agrégats. Les collections restent alimentées par un
       outil externe à venir — tant qu'elles sont vides, l'IA le signale
       plutôt que d'inventer des chiffres.
    2. Explorateur Stockage R2 — navigation par dossiers (un jeu de
       sous-dossiers fixe par client : Inventaires, Rapports, Analyses,
       Contrôle qualité, Factures, Autres), double-clic sur un fichier pour
       l'ouvrir dans un nouvel onglet via une URL de lecture temporaire.
*/

const ANALYSER_BUTTONS = [
  { mode: "inventaires", label: "Analyseur Inventaires" },
  { mode: "stocks", label: "Analyseur Stocks" },
  { mode: "ruptures", label: "Analyseur Ruptures" },
];

// Un seul hue (teal, déjà la couleur d'accent de la page) : une seule série
// de barres n'a pas besoin d'une palette catégorielle.
const CHART_BAR_COLOR = "#0d9488";

// Extrait une liste [{name, value}] du premier agrégat "top_..." trouvé
// dans la réponse — sert uniquement à illustrer la zone résultats d'un
// mini-graphique, le texte de l'IA reste la réponse principale.
function extractChartItems(data) {
  if (data?.inventaires?.top_produits_par_stock?.length) {
    return data.inventaires.top_produits_par_stock.map((p) => ({ name: p.designation, value: p.stock_total }));
  }
  if (data?.stocks?.top_produits_par_ventes?.length) {
    return data.stocks.top_produits_par_ventes.map((p) => ({ name: p.designation, value: p.quantite_vendue }));
  }
  if (data?.ruptures?.produits_les_plus_souvent_en_rupture?.length) {
    return data.ruptures.produits_les_plus_souvent_en_rupture.map((p) => ({ name: p.designation, value: p.nb_ruptures }));
  }
  return [];
}

// Icône + couleur par sous-dossier — purement cosmétique, la liste réelle
// des dossiers vient de l'API (`/gestion-stocks/context`).
const FOLDER_ICON_COLOR = "text-amber-500";

export default function GestionStocks() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superviseur";
  // Lot 20 — droit de dépôt renvoyé par le serveur (/gestion-stocks/context) :
  // admin et superviseur toujours ; utilisateur suivi seulement si
  // l'administrateur l'a autorisé (avec sa propre taille max par fichier).
  const [canUpload, setCanUpload] = useState(false);
  const gaugeRef = useRef(null);

  const [loadingContext, setLoadingContext] = useState(true);
  const [folders, setFolders] = useState([]);
  const [clientCode, setClientCode] = useState(null);
  const [r2Configured, setR2Configured] = useState(true);
  // Lot 20 — nom du compartiment R2 (fil d'Ariane) et taille max d'un fichier.
  const [bucket, setBucket] = useState(null);
  const [maxUploadMb, setMaxUploadMb] = useState(25);

  // Admin uniquement : liste des clients pour choisir lequel parcourir.
  const [adminClients, setAdminClients] = useState([]);
  const [adminSelectedCode, setAdminSelectedCode] = useState("");

  const [selectedFolder, setSelectedFolder] = useState(null);
  // Lot 22 — dossier ouvert à l'instant T (lu par le rafraîchissement différé après un dépôt).
  const selectedFolderRef = useRef(null);
  useEffect(() => { selectedFolderRef.current = selectedFolder; }, [selectedFolder]);
  const [files, setFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [uploading, setUploading] = useState(false);
  // Lot 20 — dépôt depuis l'ordinateur : file d'envoi (un fichier à la fois,
  // avec progression) et survol de la zone de glisser-déposer.
  const [uploadQueue, setUploadQueue] = useState([]);
  // Lot 20 — contenu réel du compartiment pour le client affiché : sous-dossiers
  // présents en plus des 6 standard, et fichiers posés à la racine du code client.
  const [extraFolders, setExtraFolders] = useState([]);
  const [rootFiles, setRootFiles] = useState(0);
  const [dragOver, setDragOver] = useState(false);

  // Lot 22 — tags et recherche des documents R2.
  const [knownTags, setKnownTags] = useState([]);           // tags du client [{tag, count}]
  const [aiTagsEnabled, setAiTagsEnabled] = useState(false); // suggestions IA activées pour ce client
  const [uploadTags, setUploadTags] = useState("");          // tags appliqués aux fichiers du prochain dépôt
  const [uploadDescription, setUploadDescription] = useState("");
  const [searchQ, setSearchQ] = useState("");                // texte recherché (nom, tags, description)
  const [searchTags, setSearchTags] = useState([]);          // pastilles de tags sélectionnées
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  // Lot 23 — création de dossier et gestion des tags (administration).
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [tagAdminOpen, setTagAdminOpen] = useState(false);
  const [renameFrom, setRenameFrom] = useState("");
  const [renameTo, setRenameTo] = useState("");

  // Explorateur BD MongoDB Atlas
  const [promptText, setPromptText] = useState("");
  const [analysing, setAnalysing] = useState(false);
  const [analyseMode, setAnalyseMode] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [chartItems, setChartItems] = useState([]);

  const effectiveClientCode = isAdmin ? adminSelectedCode : clientCode;

  const runAnalyse = async (mode) => {
    if (!effectiveClientCode) return;
    const question = mode === "libre" ? promptText.trim() : undefined;
    if (mode === "libre" && !question) return;
    setAnalysing(true);
    setAnalyseMode(mode);
    setAnswer(null);
    setChartItems([]);
    try {
      const r = await apiClient.post(
        "/gestion-stocks/analyse",
        { mode, question },
        { params: isAdmin ? { client_code: effectiveClientCode } : {} },
      );
      setAnswer(r.data?.answer || "");
      setChartItems(extractChartItems(r.data?.data));
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de l'analyseur");
    } finally {
      setAnalysing(false);
    }
  };

  const handlePromptKeyDown = (e) => {
    if (e.key === "Enter" && !analysing) {
      e.preventDefault();
      runAnalyse("libre");
    }
  };

  // Chargement initial : contexte (client_code résolu, dossiers, R2 configuré).
  const loadContext = async () => {
    setLoadingContext(true);
    try {
      const r = await apiClient.get("/gestion-stocks/context");
      setFolders(r.data?.folders || []);
      setClientCode(r.data?.client_code || null);
      setR2Configured(!!r.data?.r2_configured);
      setBucket(r.data?.bucket || null);
      setCanUpload(!!r.data?.can_upload);
      if (r.data?.upload_max_mb) setMaxUploadMb(r.data.upload_max_mb);
      if (r.data?.is_admin) {
        const rc = await apiClient.get("/admin/gestion-stocks/clients");
        setAdminClients(rc.data || []);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement de l'espace Gestion de Stocks");
    } finally {
      setLoadingContext(false);
    }
  };
  useEffect(() => { loadContext(); /* eslint-disable-next-line */ }, []);

  const openFolder = async (folder) => {
    if (!effectiveClientCode) return;
    setSelectedFolder(folder);
    setLoadingFiles(true);
    try {
      const r = await apiClient.get(`/gestion-stocks/folders/${encodeURIComponent(folder)}/files`, {
        params: isAdmin ? { client_code: effectiveClientCode } : {},
      });
      setFiles(r.data?.files || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de lecture du dossier");
      setFiles([]);
    } finally {
      setLoadingFiles(false);
    }
  };

  // Pseudo-dossier « racine » (fichiers hors de tout sous-dossier) — voir backend ROOT_FOLDER.
  const ROOT_FOLDER = "_racine";
  const folderLabel = (f) => (f === ROOT_FOLDER ? "Racine (hors dossier)" : f);

  // Dossiers réellement présents dans R2 pour le client affiché
  // (Lot 23 : `foldersVersion` relance la lecture après la création d'un dossier).
  const [foldersVersion, setFoldersVersion] = useState(0);
  useEffect(() => {
    if (!effectiveClientCode || !r2Configured) { setExtraFolders([]); setRootFiles(0); return; }
    apiClient.get("/gestion-stocks/folders", { params: isAdmin ? { client_code: effectiveClientCode } : {} })
      .then((r) => {
        if (r.data?.folders?.length) setFolders(r.data.folders);
        setExtraFolders(r.data?.extra_folders || []);
        setRootFiles(r.data?.root_files || 0);
        setAiTagsEnabled(!!r.data?.ai_tags_enabled);
      })
      .catch(() => { setExtraFolders([]); setRootFiles(0); setAiTagsEnabled(false); });
  }, [effectiveClientCode, r2Configured, isAdmin, foldersVersion]);

  // Lot 22 — tags déjà utilisés par le client (suggestions de saisie + pastilles de filtre).
  const clientParams = isAdmin ? { client_code: effectiveClientCode } : {};
  const loadKnownTags = () => {
    if (!effectiveClientCode || !r2Configured) { setKnownTags([]); return; }
    apiClient.get("/gestion-stocks/tags", { params: clientParams })
      .then((r) => setKnownTags(r.data?.tags || []))
      .catch(() => setKnownTags([]));
  };
  useEffect(() => {
    loadKnownTags();
    setSearchQ(""); setSearchTags([]); setSearchResults([]);
    /* eslint-disable-next-line */
  }, [effectiveClientCode, r2Configured, isAdmin]);

  // Lot 22 — recherche dans tous les dossiers du client (400 ms après la dernière frappe).
  const searchActive = searchQ.trim().length > 0 || searchTags.length > 0;
  const runSearch = () => {
    if (!effectiveClientCode || !searchActive) { setSearchResults([]); return; }
    setSearching(true);
    apiClient.get("/gestion-stocks/search", { params: { ...clientParams, q: searchQ.trim(), tags: searchTags.join(",") } })
      .then((r) => setSearchResults(r.data?.results || []))
      .catch((err) => { toast.error(err?.response?.data?.detail || "Erreur de recherche"); setSearchResults([]); })
      .finally(() => setSearching(false));
  };
  useEffect(() => {
    const t = setTimeout(runSearch, 400);
    return () => clearTimeout(t);
    /* eslint-disable-next-line */
  }, [searchQ, searchTags, effectiveClientCode]);

  // Active/désactive une pastille de tag dans le filtre.
  const toggleSearchTag = (tag) => setSearchTags((cur) => (cur.includes(tag) ? cur.filter((t) => t !== tag) : [...cur, tag]));
  const clearSearch = () => { setSearchQ(""); setSearchTags([]); setSearchResults([]); };

  // Après modification des tags d'un fichier : mise à jour de la ligne
  // (dossier ouvert et résultats de recherche) et des tags connus.
  const handleFileChanged = (updated, opts = {}) => {
    const merge = (list) => list.map((f) => (f.key === updated.key ? { ...f, ...updated } : f));
    setFiles(merge);
    setSearchResults(merge);
    if (!opts.keepEditing) loadKnownTags();
  };

  // Lot 23 — fichier supprimé : retiré des listes, jauge et tags rafraîchis.
  const handleFileDeleted = (deleted) => {
    const drop = (list) => list.filter((f) => f.key !== deleted.key);
    setFiles(drop);
    setSearchResults(drop);
    gaugeRef.current?.reload();
    loadKnownTags();
    if (deleted.folder === ROOT_FOLDER || selectedFolder === ROOT_FOLDER) setFoldersVersion((v) => v + 1);
  };

  // Lot 23 — création d'un dossier (marqueur vide dans R2, comme Cloudflare).
  const createFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    try {
      const r = await apiClient.post("/gestion-stocks/folders", { name, ...clientParams });
      toast.success(`Dossier « ${r.data.folder} » créé`);
      setNewFolderName(""); setNewFolderOpen(false);
      setFoldersVersion((v) => v + 1);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Création du dossier impossible");
    }
  };

  // Lot 23 — renommer / fusionner / retirer un tag pour tous les fichiers du client.
  const renameTag = async () => {
    if (!renameFrom) return;
    const target = renameTo.trim();
    const msg = target
      ? `Renommer le tag « ${renameFrom} » en « ${target} » sur tous les fichiers de ce client ?`
      : `Retirer le tag « ${renameFrom} » de tous les fichiers de ce client ?`;
    if (!window.confirm(msg)) return;
    try {
      const r = await apiClient.put("/gestion-stocks/tags/rename", { from: renameFrom, to: target, ...clientParams });
      setKnownTags(r.data?.tags || []);
      toast.success(`${r.data?.files_changed || 0} fichier(s) mis à jour`);
      setRenameFrom(""); setRenameTo("");
      setSearchTags((cur) => cur.filter((t) => t !== renameFrom));
      if (selectedFolder) openFolder(selectedFolder);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Renommage impossible");
    }
  };

  // Lot 23 — indexation du texte des fichiers anciens (déposés avant ce lot ou via Cloudflare).
  const reindex = async () => {
    try {
      const r = await apiClient.post("/gestion-stocks/reindex", { ...clientParams });
      toast.success(`${r.data?.queued || 0} fichier(s) en cours d'indexation sur ${r.data?.files || 0} — la recherche dans leur contenu sera disponible dans quelques instants.`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Indexation impossible");
    }
  };

  const openFile = async (file) => {
    try {
      const r = await apiClient.get("/gestion-stocks/files/view-url", { params: { key: file.key } });
      window.open(r.data.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible d'ouvrir ce document");
    }
  };

  // Lot 20 — dépôt (admin) d'un ou plusieurs fichiers depuis l'ordinateur,
  // via le bouton « Déposer des fichiers » ou par glisser-déposer. Les fichiers
  // partent un par un sur la route existante (un fichier par requête), avec
  // la progression de chacun ; un fichier trop gros est refusé avant l'envoi.
  const uploadFiles = async (fileList) => {
    const list = Array.from(fileList || []);
    if (!list.length || !selectedFolder || !effectiveClientCode || uploading) return;
    const maxBytes = maxUploadMb * 1024 * 1024;
    const queue = list.map((f, idx) => ({
      id: `${Date.now()}-${idx}`, name: f.name, size: f.size, progress: 0,
      status: f.size > maxBytes ? "error" : "pending",
      error: f.size > maxBytes
        ? `Refusé : ${(f.size / 1048576).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} Mo, au-delà de la taille maximale autorisée (${Number(maxUploadMb).toLocaleString("fr-FR")} Mo par fichier)`
        : null,
    }));
    setUploadQueue(queue);
    setUploading(true);
    const update = (id, patch) => setUploadQueue((q) => q.map((it) => (it.id === id ? { ...it, ...patch } : it)));
    let sent = 0;
    let aiStarted = false;
    for (let idx = 0; idx < list.length; idx += 1) {
      const item = queue[idx];
      if (item.status === "error") continue;
      update(item.id, { status: "uploading" });
      const form = new FormData();
      form.append("file", list[idx]);
      // Lot 22 — tags et description saisis avant le dépôt (appliqués à chaque fichier du lot).
      if (uploadTags.trim()) form.append("tags", uploadTags);
      if (uploadDescription.trim()) form.append("description", uploadDescription);
      try {
        // Administration : route admin (client choisi) ; utilisateur suivi :
        // route portail (son tenant est résolu par le serveur, jamais transmis).
        const url = isAdmin
          ? `/admin/gestion-stocks/${encodeURIComponent(effectiveClientCode)}/${encodeURIComponent(selectedFolder)}/upload`
          : `/gestion-stocks/folders/${encodeURIComponent(selectedFolder)}/upload`;
        const res = await apiClient.post(
          url,
          form,
          {
            headers: { "Content-Type": "multipart/form-data" },
            onUploadProgress: (ev) => {
              if (ev.total) update(item.id, { progress: Math.round((ev.loaded * 100) / ev.total) });
            },
          },
        );
        update(item.id, { status: "done", progress: 100 });
        sent += 1;
        if (res?.data?.ai_tags_started) aiStarted = true;
      } catch (err) {
        update(item.id, { status: "error", error: err?.response?.data?.detail || "Échec de l'envoi" });
      }
    }
    setUploading(false);
    gaugeRef.current?.reload();
    if (sent) {
      toast.success(`${sent} document${sent > 1 ? "s" : ""} déposé${sent > 1 ? "s" : ""} dans ${selectedFolder}.`);
      openFolder(selectedFolder);
      loadKnownTags();
      setUploadTags(""); setUploadDescription("");
      // Lot 22 — l'IA propose des tags en arrière-plan : on relit le dossier un peu plus tard.
      if (aiStarted) {
        toast.info("L'IA prépare des suggestions de tags : elles apparaîtront dans quelques secondes.");
        const folderAtUpload = selectedFolder;
        // Seulement si l'utilisateur est toujours dans ce dossier (sinon on ne le ramène pas en arrière).
        setTimeout(() => { if (selectedFolderRef.current === folderAtUpload) openFolder(folderAtUpload); }, 8000);
      }
    }
  };

  const handleUpload = (e) => {
    const picked = e.target.files;
    uploadFiles(picked).finally(() => { e.target.value = ""; });
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (canUpload && selectedFolder !== ROOT_FOLDER) uploadFiles(e.dataTransfer?.files);
  };

  // Libellé du client affiché dans le fil d'Ariane (admin : code + nom).
  const clientLabel = (() => {
    if (!effectiveClientCode) return null;
    const c = adminClients.find((x) => x.client_code === effectiveClientCode);
    return c?.label ? `${effectiveClientCode} — ${c.label}` : effectiveClientCode;
  })();

  const backToFolders = () => { setSelectedFolder(null); setFiles([]); setUploadQueue([]); };

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6" data-testid="gestion-stocks-page">
      <h1 className="text-xl font-display font-bold text-slate-800 flex items-center gap-2">
        <Database className="w-5 h-5 text-teal-600" /> Gestion de Stocks
      </h1>

      {/* Bloc 1 — Explorateur BD MongoDB Atlas */}
      <section className="rounded-xl border-2 border-slate-200 bg-slate-50/60 p-4 space-y-3" data-testid="gestion-stocks-mongo-block">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <span className="text-sm font-semibold text-slate-600">Explorateur BD MongoDB Atlas</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {ANALYSER_BUTTONS.map(({ mode, label }) => (
            <button
              key={mode}
              type="button"
              disabled={!effectiveClientCode || analysing}
              onClick={() => runAnalyse(mode)}
              className="px-3 py-2 rounded-lg ring-1 ring-slate-300 bg-white text-sm text-slate-700 hover:bg-teal-50 hover:ring-teal-300 disabled:text-slate-400 disabled:cursor-not-allowed disabled:hover:bg-white flex items-center justify-center gap-2"
              data-testid={`gestion-stocks-analyseur-${mode}`}
            >
              {analysing && analyseMode === mode && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {label}
            </button>
          ))}
        </div>
        <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3 min-h-[64px] text-sm" data-testid="gestion-stocks-results">
          {!effectiveClientCode ? (
            <p className="text-xs italic text-slate-400">
              {isAdmin
                ? "Choisissez d'abord un client ci-dessous pour interroger ses données."
                : "Aucun code client configuré pour votre société — contactez votre administrateur SAWALI."}
            </p>
          ) : analysing ? (
            <p className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Analyse en cours…</p>
          ) : answer ? (
            <div className="space-y-3">
              <p className="text-slate-700 whitespace-pre-wrap">{answer}</p>
              {chartItems.length > 0 && (
                <div className="h-56" data-testid="gestion-stocks-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartItems} layout="vertical" margin={{ left: 8, right: 16 }}>
                      <XAxis type="number" hide />
                      <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 11 }} />
                      <RTooltip />
                      <Bar dataKey="value" fill={CHART_BAR_COLOR} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs italic text-slate-400">
              Zone résultats (texte, graphique, etc) — cliquez sur un analyseur ou posez une question ci-dessous.
            </p>
          )}
        </div>
        <div className="relative">
          <input
            type="text"
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
            onKeyDown={handlePromptKeyDown}
            disabled={!effectiveClientCode || analysing}
            placeholder="Posez une question sur vos stocks puis Entrée…"
            className="w-full px-3 py-2 pr-9 rounded-lg ring-1 ring-slate-300 text-sm disabled:bg-slate-100 disabled:text-slate-400"
            data-testid="gestion-stocks-prompt"
          />
          <button
            type="button"
            onClick={() => runAnalyse("libre")}
            disabled={!effectiveClientCode || analysing || !promptText.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-teal-600 disabled:text-slate-300"
            data-testid="gestion-stocks-prompt-send"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </section>

      {/* Bloc 2 — Explorateur Stockage R2 */}
      <section className="rounded-xl border-2 border-teal-200 bg-teal-50/30 p-4 space-y-3" data-testid="gestion-stocks-r2-block">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <span className="text-sm font-semibold text-teal-800">
            Explorateur Stockage R2 (PDFs, Excel, Word, Images, ...)
          </span>
          <button
            type="button"
            onClick={() => (selectedFolder ? openFolder(selectedFolder) : loadContext())}
            className="text-xs text-teal-700 inline-flex items-center gap-1 hover:underline"
            data-testid="gestion-stocks-refresh"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Actualiser
          </button>
        </div>

        {loadingContext ? (
          <p className="text-sm text-slate-500">Chargement…</p>
        ) : !r2Configured ? (
          <p className="text-sm text-rose-600">
            Stockage R2 non configuré pour ce module (variables R2_STOCKS_* manquantes côté serveur).
          </p>
        ) : isAdmin && adminClients.length === 0 ? (
          <p className="text-sm text-slate-500">Aucun client avec un code client (client_code) configuré.</p>
        ) : !isAdmin && !clientCode ? (
          <p className="text-sm text-rose-600">
            Aucun code client configuré pour votre société — contactez votre administrateur SAWALI.
          </p>
        ) : (
          <>
            {isAdmin && (
              <select
                value={adminSelectedCode}
                onChange={(e) => { setAdminSelectedCode(e.target.value); setSelectedFolder(null); setFiles([]); setUploadQueue([]); clearSearch(); }}
                className="w-full sm:w-72 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm bg-white"
                data-testid="gestion-stocks-admin-client-select"
              >
                <option value="">— Choisir un client —</option>
                {adminClients.map((c) => (
                  <option key={c.client_code} value={c.client_code}>{c.client_code} — {c.label}</option>
                ))}
              </select>
            )}

            {/* Lot 20 — fil d'Ariane : compartiment R2 › client › dossier ouvert */}
            {effectiveClientCode && (
              <nav className="flex items-center flex-wrap gap-1 text-sm bg-white rounded-lg ring-1 ring-teal-200 px-3 py-2"
                aria-label="Emplacement" data-testid="gestion-stocks-breadcrumb">
                <HardDrive className="w-4 h-4 text-teal-600 shrink-0" />
                <span className="text-slate-500">Compartiment</span>
                <button type="button" onClick={backToFolders} className="font-mono font-semibold text-teal-800 hover:underline"
                  data-testid="gestion-stocks-breadcrumb-bucket">
                  {bucket || "—"}
                </button>
                <ChevronRight className="w-4 h-4 text-slate-400" />
                <button type="button" onClick={backToFolders}
                  className={`hover:underline ${selectedFolder ? "text-teal-800" : "font-semibold text-slate-800"}`}
                  data-testid="gestion-stocks-breadcrumb-client">
                  {clientLabel}
                </button>
                {selectedFolder && (
                  <>
                    <ChevronRight className="w-4 h-4 text-slate-400" />
                    <span className="font-semibold text-slate-800" data-testid="gestion-stocks-breadcrumb-folder">{folderLabel(selectedFolder)}</span>
                  </>
                )}
              </nav>
            )}

            {/* Lot 20 — espace occupé par les fichiers du tenant / espace alloué */}
            {effectiveClientCode && (
              <R2StorageGauge key={effectiveClientCode} ref={gaugeRef} compact clientCode={isAdmin ? effectiveClientCode : null} />
            )}

            {/* Lot 22 — recherche par nom, tag ou description, dans tous les dossiers du client */}
            {effectiveClientCode && (
              <div className="space-y-2" data-testid="gestion-stocks-search">
                <div className="relative">
                  <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                  <input value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
                    placeholder="Rechercher un document (nom, tag, description ou texte du document) dans tous les dossiers…"
                    className="w-full pl-9 pr-9 py-2 rounded-lg ring-1 ring-slate-300 text-sm bg-white"
                    data-testid="gestion-stocks-search-input" />
                  {searchActive && (
                    <button type="button" onClick={clearSearch} title="Effacer la recherche"
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                      data-testid="gestion-stocks-search-clear">
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
                {/* Lot 23 — outils de l'administration : renommer/fusionner un tag, indexer le contenu */}
                {isAdmin && (
                  <div className="flex flex-wrap items-center gap-3 text-[11px]">
                    <button type="button" onClick={() => setTagAdminOpen((v) => !v)} className="inline-flex items-center gap-1 text-teal-700 hover:underline"
                      data-testid="gestion-stocks-tag-admin-toggle">
                      <Settings2 className="w-3.5 h-3.5" /> Gérer les tags
                    </button>
                    <button type="button" onClick={reindex} className="inline-flex items-center gap-1 text-teal-700 hover:underline"
                      title="Extraire le texte des fichiers déjà présents pour pouvoir chercher dans leur contenu"
                      data-testid="gestion-stocks-reindex">
                      <ScanText className="w-3.5 h-3.5" /> Indexer le contenu des fichiers existants
                    </button>
                  </div>
                )}
                {isAdmin && tagAdminOpen && (
                  <div className="rounded-lg ring-1 ring-teal-200 bg-white p-3 space-y-2" data-testid="gestion-stocks-tag-admin">
                    <p className="text-[11px] text-slate-600">
                      Renommer un tag sur <strong>tous les fichiers de ce client</strong>. Si le nouveau nom existe déjà, les deux
                      tags sont fusionnés. Laisser le nouveau nom vide retire le tag partout.
                    </p>
                    <div className="flex flex-wrap gap-2 items-center">
                      <select value={renameFrom} onChange={(e) => setRenameFrom(e.target.value)}
                        className="px-2 py-1.5 rounded ring-1 ring-slate-300 text-xs bg-white" data-testid="gestion-stocks-rename-from">
                        <option value="">— Tag à renommer —</option>
                        {knownTags.map((k) => <option key={k.tag} value={k.tag}>{k.tag} ({k.count})</option>)}
                      </select>
                      <span className="text-xs text-slate-400">→</span>
                      <input value={renameTo} onChange={(e) => setRenameTo(e.target.value)} list="gestion-stocks-known-tags-admin"
                        placeholder="Nouveau nom (vide = retirer)" className="px-2 py-1.5 rounded ring-1 ring-slate-300 text-xs"
                        data-testid="gestion-stocks-rename-to" />
                      <datalist id="gestion-stocks-known-tags-admin">{knownTags.map((k) => <option key={k.tag} value={k.tag} />)}</datalist>
                      <button type="button" onClick={renameTag} disabled={!renameFrom}
                        className="px-3 py-1.5 rounded text-xs font-medium text-white bg-teal-600 hover:bg-teal-700 disabled:opacity-50"
                        data-testid="gestion-stocks-rename-apply">
                        Appliquer
                      </button>
                    </div>
                  </div>
                )}
                {knownTags.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1" data-testid="gestion-stocks-tag-filter">
                    <span className="text-[11px] text-slate-500 inline-flex items-center gap-1 mr-1"><Tag className="w-3 h-3" /> Filtrer :</span>
                    {knownTags.slice(0, 20).map((k) => (
                      <TagChip key={k.tag} tag={`${k.tag} (${k.count})`} active={searchTags.includes(k.tag)}
                        onClick={() => toggleSearchTag(k.tag)} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {effectiveClientCode && searchActive && (
              <div className="space-y-2" data-testid="gestion-stocks-search-results">
                <p className="text-xs text-slate-600">
                  {searching ? "Recherche…" : `${searchResults.length} document${searchResults.length > 1 ? "s" : ""} trouvé${searchResults.length > 1 ? "s" : ""}`}
                  {searchTags.length > 0 && <> avec {searchTags.length > 1 ? "les tags" : "le tag"} <strong>{searchTags.join(", ")}</strong></>}
                </p>
                {!searching && searchResults.length > 0 && (
                  <ul className="divide-y divide-slate-200 bg-white rounded-lg ring-1 ring-slate-200">
                    {searchResults.map((file) => (
                      <R2FileRow key={file.key} file={file} onOpen={openFile} onChanged={handleFileChanged} onDeleted={handleFileDeleted}
                        knownTags={knownTags} aiEnabled={aiTagsEnabled} showFolder folderLabel={folderLabel} />
                    ))}
                  </ul>
                )}
              </div>
            )}

            {effectiveClientCode && !searchActive && !selectedFolder && canUpload && (
              <p className="text-xs text-slate-500">Ouvrez un dossier pour consulter ou déposer des documents.</p>
            )}

            {/* Lot 23 — création d'un dossier (administration, ou compte autorisé à déposer) */}
            {effectiveClientCode && !searchActive && !selectedFolder && canUpload && (
              <div className="flex flex-wrap items-center gap-2" data-testid="gestion-stocks-new-folder">
                {newFolderOpen ? (
                  <>
                    <input autoFocus value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)} maxLength={60}
                      onKeyDown={(e) => { if (e.key === "Enter") createFolder(); if (e.key === "Escape") setNewFolderOpen(false); }}
                      placeholder="Nom du nouveau dossier" className="px-3 py-1.5 rounded-lg ring-1 ring-slate-300 text-sm bg-white"
                      data-testid="gestion-stocks-new-folder-input" />
                    <button type="button" onClick={createFolder} className="px-3 py-1.5 rounded-lg text-sm font-medium text-white bg-teal-600 hover:bg-teal-700"
                      data-testid="gestion-stocks-new-folder-create">Créer</button>
                    <button type="button" onClick={() => setNewFolderOpen(false)} className="text-xs text-slate-500 hover:underline">Annuler</button>
                  </>
                ) : (
                  <button type="button" onClick={() => setNewFolderOpen(true)}
                    className="inline-flex items-center gap-1 text-xs text-teal-700 hover:underline" data-testid="gestion-stocks-new-folder-btn">
                    <FolderPlus className="w-4 h-4" /> Nouveau dossier
                  </button>
                )}
              </div>
            )}

            {effectiveClientCode && !searchActive && !selectedFolder && (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4" data-testid="gestion-stocks-folder-grid">
                {rootFiles > 0 && (
                  <button
                    type="button"
                    onClick={() => openFolder(ROOT_FOLDER)}
                    className="flex flex-col items-center gap-1 p-3 rounded-lg hover:bg-white/70 transition"
                    title="Fichiers posés directement à la racine du code client, hors de tout dossier"
                    data-testid="gestion-stocks-folder-racine"
                  >
                    <Folder className="w-12 h-12 text-slate-400 fill-slate-100" strokeWidth={1.5} />
                    <span className="text-xs font-medium text-slate-700 text-center">Racine (hors dossier)</span>
                    <span className="text-[10px] text-slate-400">{rootFiles} fichier{rootFiles > 1 ? "s" : ""}</span>
                  </button>
                )}
                {folders.map((f) => (
                  <button
                    key={f}
                    type="button"
                    onClick={() => openFolder(f)}
                    className="flex flex-col items-center gap-1 p-3 rounded-lg hover:bg-white/70 transition"
                    data-testid={`gestion-stocks-folder-${f.replace(/\s+/g, "-").toLowerCase()}`}
                  >
                    <Folder className={`w-12 h-12 ${extraFolders.includes(f) ? "text-sky-500 fill-sky-100" : `${FOLDER_ICON_COLOR} fill-amber-100`}`} strokeWidth={1.5} />
                    <span className="text-xs font-medium text-slate-700 text-center">{f}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Lot 20 — légende des couleurs de dossiers (grille des dossiers) */}
            {effectiveClientCode && !searchActive && !selectedFolder && (
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-teal-100 pt-2 text-[11px] text-slate-500"
                data-testid="gestion-stocks-folder-legend">
                <span className="font-semibold text-slate-600">Légende :</span>
                <span className="inline-flex items-center gap-1">
                  <Folder className={`w-4 h-4 ${FOLDER_ICON_COLOR} fill-amber-100`} strokeWidth={1.5} />
                  Dossier standard (créé automatiquement dans le compartiment pour chaque client)
                </span>
                <span className="inline-flex items-center gap-1">
                  <Folder className="w-4 h-4 text-sky-500 fill-sky-100" strokeWidth={1.5} />
                  Autre dossier présent dans le compartiment (créé avec « Nouveau dossier » ou depuis Cloudflare)
                </span>
                <span className="inline-flex items-center gap-1">
                  <Folder className="w-4 h-4 text-slate-400 fill-slate-100" strokeWidth={1.5} />
                  Racine : fichiers posés directement sous le code client, hors dossier (consultation seule)
                </span>
              </div>
            )}

            {effectiveClientCode && !searchActive && selectedFolder && (
              <div className="space-y-2" data-testid="gestion-stocks-file-list"
                onDragOver={(e) => { if (canUpload && selectedFolder !== ROOT_FOLDER) { e.preventDefault(); setDragOver(true); } }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}>
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <button
                    type="button"
                    onClick={backToFolders}
                    className="text-xs text-slate-600 inline-flex items-center gap-1 hover:underline"
                  >
                    <ArrowLeft className="w-3.5 h-3.5" /> Retour aux dossiers
                  </button>
                  {canUpload && selectedFolder !== ROOT_FOLDER && (
                    <label className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-white ${uploading ? "bg-teal-400 cursor-wait" : "bg-teal-600 hover:bg-teal-700 cursor-pointer"}`}
                      data-testid="gestion-stocks-upload-btn">
                      {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                      {uploading ? "Envoi en cours…" : "Déposer des fichiers"}
                      <input type="file" multiple className="hidden" disabled={uploading} onChange={handleUpload}
                        data-testid="gestion-stocks-upload-input" />
                    </label>
                  )}
                </div>

                {/* Lot 22 — tags et description appliqués aux fichiers du prochain dépôt */}
                {canUpload && selectedFolder !== ROOT_FOLDER && (
                  <div className="grid sm:grid-cols-2 gap-2" data-testid="gestion-stocks-upload-meta">
                    <input value={uploadTags} onChange={(e) => setUploadTags(e.target.value)} list="gestion-stocks-known-tags"
                      placeholder="Tags du dépôt, séparés par des virgules (facultatif)"
                      className="px-3 py-1.5 rounded-lg ring-1 ring-slate-300 text-xs bg-white" data-testid="gestion-stocks-upload-tags" />
                    <datalist id="gestion-stocks-known-tags">{knownTags.map((k) => <option key={k.tag} value={k.tag} />)}</datalist>
                    <input value={uploadDescription} onChange={(e) => setUploadDescription(e.target.value)} maxLength={500}
                      placeholder="Description (facultative)"
                      className="px-3 py-1.5 rounded-lg ring-1 ring-slate-300 text-xs bg-white" data-testid="gestion-stocks-upload-description" />
                  </div>
                )}

                {/* Zone de glisser-déposer (admin) : même envoi que le bouton */}
                {canUpload && selectedFolder !== ROOT_FOLDER && (
                  <div className={`rounded-lg border-2 border-dashed px-3 py-4 text-center text-xs transition ${dragOver ? "border-teal-500 bg-teal-50 text-teal-800" : "border-slate-300 text-slate-500"}`}
                    data-testid="gestion-stocks-dropzone">
                    Glissez-déposez ici des fichiers depuis votre ordinateur (plusieurs à la fois, {Number(maxUploadMb).toLocaleString("fr-FR")} Mo max par fichier)
                    — ils seront rangés dans <strong>{selectedFolder}</strong>.
                  </div>
                )}

                {/* Suivi de l'envoi, fichier par fichier */}
                {uploadQueue.length > 0 && (
                  <ul className="space-y-1" data-testid="gestion-stocks-upload-queue">
                    {uploadQueue.map((it) => (
                      <li key={it.id} className="flex items-center gap-2 text-xs bg-white rounded ring-1 ring-slate-200 px-2 py-1.5">
                        {it.status === "done" ? <CheckCircle2 className="w-4 h-4 text-teal-600 shrink-0" />
                          : it.status === "error" ? <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
                          : <Loader2 className={`w-4 h-4 text-slate-400 shrink-0 ${it.status === "uploading" ? "animate-spin" : ""}`} />}
                        <span className="truncate flex-1 text-slate-700">{it.name}</span>
                        {it.status === "error" ? (
                          <span className="text-rose-600">{it.error}</span>
                        ) : (
                          <span className="w-28 h-1.5 bg-slate-100 rounded overflow-hidden shrink-0">
                            <span className="block h-full bg-teal-500 transition-all" style={{ width: `${it.progress}%` }} />
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {loadingFiles ? (
                  <p className="text-sm text-slate-500">Chargement…</p>
                ) : files.length === 0 ? (
                  <p className="text-sm text-slate-500 italic">Aucun document dans ce dossier pour l'instant.</p>
                ) : (
                  <ul className="divide-y divide-slate-200 bg-white rounded-lg ring-1 ring-slate-200">
                    {/* Lot 22 — chaque ligne affiche ses tags et, si autorisé, un éditeur en ligne */}
                    {files.map((file) => (
                      <R2FileRow key={file.key} file={file} onOpen={openFile} onChanged={handleFileChanged} onDeleted={handleFileDeleted}
                        knownTags={knownTags} aiEnabled={aiTagsEnabled} />
                    ))}
                  </ul>
                )}
                <p className="text-[10px] text-slate-400 italic">(Double-cliquer pour afficher)</p>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
