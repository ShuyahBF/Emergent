import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import {
  Database, Folder, FileText, Upload, RefreshCw, ArrowLeft, Send, Loader2,
} from "lucide-react";
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
  if (data?.ruptures?.produits_a_risque_bientot?.length) {
    return data.ruptures.produits_a_risque_bientot.map((p) => ({ name: p.designation, value: p.jours_restants_estimes }));
  }
  return [];
}

// Icône + couleur par sous-dossier — purement cosmétique, la liste réelle
// des dossiers vient de l'API (`/gestion-stocks/context`).
const FOLDER_ICON_COLOR = "text-amber-500";

function formatSize(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

export default function GestionStocks() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superviseur";

  const [loadingContext, setLoadingContext] = useState(true);
  const [folders, setFolders] = useState([]);
  const [clientCode, setClientCode] = useState(null);
  const [r2Configured, setR2Configured] = useState(true);

  // Admin uniquement : liste des clients pour choisir lequel parcourir.
  const [adminClients, setAdminClients] = useState([]);
  const [adminSelectedCode, setAdminSelectedCode] = useState("");

  const [selectedFolder, setSelectedFolder] = useState(null);
  const [files, setFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [uploading, setUploading] = useState(false);

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

  const openFile = async (file) => {
    try {
      const r = await apiClient.get("/gestion-stocks/files/view-url", { params: { key: file.key } });
      window.open(r.data.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Impossible d'ouvrir ce document");
    }
  };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !selectedFolder || !effectiveClientCode) return;
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      await apiClient.post(
        `/admin/gestion-stocks/${encodeURIComponent(effectiveClientCode)}/${encodeURIComponent(selectedFolder)}/upload`,
        form,
        { headers: { "Content-Type": "multipart/form-data" } },
      );
      toast.success("Document envoyé.");
      openFolder(selectedFolder);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de l'envoi");
    } finally {
      setUploading(false);
    }
  };

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
                onChange={(e) => { setAdminSelectedCode(e.target.value); setSelectedFolder(null); setFiles([]); }}
                className="w-full sm:w-72 px-3 py-2 rounded-lg ring-1 ring-slate-300 text-sm bg-white"
                data-testid="gestion-stocks-admin-client-select"
              >
                <option value="">— Choisir un client —</option>
                {adminClients.map((c) => (
                  <option key={c.client_code} value={c.client_code}>{c.client_code} — {c.label}</option>
                ))}
              </select>
            )}

            {effectiveClientCode && !selectedFolder && (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4" data-testid="gestion-stocks-folder-grid">
                {folders.map((f) => (
                  <button
                    key={f}
                    type="button"
                    onClick={() => openFolder(f)}
                    className="flex flex-col items-center gap-1 p-3 rounded-lg hover:bg-white/70 transition"
                    data-testid={`gestion-stocks-folder-${f.replace(/\s+/g, "-").toLowerCase()}`}
                  >
                    <Folder className={`w-12 h-12 ${FOLDER_ICON_COLOR} fill-amber-100`} strokeWidth={1.5} />
                    <span className="text-xs font-medium text-slate-700 text-center">{f}</span>
                  </button>
                ))}
              </div>
            )}

            {effectiveClientCode && selectedFolder && (
              <div className="space-y-2" data-testid="gestion-stocks-file-list">
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => { setSelectedFolder(null); setFiles([]); }}
                    className="text-xs text-slate-600 inline-flex items-center gap-1 hover:underline"
                  >
                    <ArrowLeft className="w-3.5 h-3.5" /> Retour aux dossiers
                  </button>
                  <span className="text-xs font-semibold text-slate-500">{selectedFolder}</span>
                  {isAdmin && (
                    <label className="text-xs text-teal-700 inline-flex items-center gap-1 cursor-pointer hover:underline">
                      <Upload className="w-3.5 h-3.5" /> {uploading ? "Envoi…" : "Ajouter un document"}
                      <input type="file" className="hidden" disabled={uploading} onChange={handleUpload} />
                    </label>
                  )}
                </div>
                {loadingFiles ? (
                  <p className="text-sm text-slate-500">Chargement…</p>
                ) : files.length === 0 ? (
                  <p className="text-sm text-slate-500 italic">Aucun document dans ce dossier pour l'instant.</p>
                ) : (
                  <ul className="divide-y divide-slate-200 bg-white rounded-lg ring-1 ring-slate-200">
                    {files.map((file) => (
                      <li
                        key={file.key}
                        onDoubleClick={() => openFile(file)}
                        className="flex items-center justify-between gap-3 px-3 py-2 cursor-pointer hover:bg-slate-50"
                        title="Double-cliquer pour afficher"
                        data-testid="gestion-stocks-file-row"
                      >
                        <span className="flex items-center gap-2 text-sm text-slate-700 truncate">
                          <FileText className="w-4 h-4 text-slate-400 shrink-0" /> {file.name}
                        </span>
                        <span className="text-[11px] text-slate-400 shrink-0">
                          {formatSize(file.size)} · {formatDate(file.last_modified)}
                        </span>
                      </li>
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
