import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  BarChart3, ChevronDown, ChevronRight, Download, FileJson, FileText, Loader2, RefreshCw, ScanText, Trash2, Upload,
} from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
// Module commun ocr-core (copie identique, source unique : dépôt ShuyahBF/Claude).
import OcrRunsPanel from "@/components/ocr-core/OcrRunsPanel";
import OcrDashboard from "@/components/ocr-core/OcrDashboard";
import StarRating from "@/components/ocr-core/StarRating";
import { displayValue, errorMessage, formatXof, shortModel } from "@/components/ocr-core/format";
import { estPhoto, reduirePhoto, triNaturel } from "@/lib/photos";

/*
  Portail / Admin → « OCR sur Pièces » (lot 2026-09).
  Dépôt de pièces (factures fournisseurs, bons de livraison, reçus…) et
  analyse IA. Deux publics, une seule page :
    - pharmacies (rôle pharmacien, ou Pharmacien suivi) : déposent leurs
      pièces, voient la synthèse et les champs extraits, téléchargent ;
      jamais le modèle, le coût ni les évaluations (le serveur ne les envoie pas) ;
    - administration (admin/superviseur) : choisit la pharmacie et le modèle
      d'IA, voit le coût réel en FCFA, évalue chaque analyse (1-5 étoiles +
      corrections), relance avec un autre modèle, consulte le tableau de bord.
  API : /ocr-pieces (backend/routes/ocr_pieces.py, contrat commun ocr-core).

  Type « Liste de pointage » (lot 2026-09-29) : on dépose le scan de la liste
  de pointage remplie à la main + le JSON de l'inventaire exporté par WinDev ;
  l'analyse (backend/ocr_pointage) complète le JSON (IMagasin, ISalle,
  Peremption1), téléchargeable via le bouton « JSON complété ».
  Sans scanner (lot 32) : on peut choisir d'un coup TOUTES les photos des pages
  prises au téléphone ; elles sont réduites dans le navigateur puis envoyées
  ensemble (champ « photos ») et le serveur les assemble en un seul PDF.
*/

const API_BASE = "/ocr-pieces";
const ALL_TENANTS = "__all__";   // valeur sentinelle : le Select shadcn refuse ""

// Types de pièce (mêmes codes que PIECE_KINDS côté serveur).
const KINDS = [
  { value: "facture", label: "Facture" },
  { value: "bon_livraison", label: "Bon de livraison" },
  { value: "avoir", label: "Avoir" },
  { value: "recu", label: "Reçu" },
  { value: "releve", label: "Relevé" },
  { value: "liste_pointage", label: "Liste de pointage" },
  { value: "autre", label: "Autre" },
];
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label]));

// Statut d'une pièce → libellé + couleurs du badge.
const STATUS = {
  en_analyse: { label: "Analyse en cours", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  analyse: { label: "Analysée", cls: "bg-teal-50 text-teal-700 border-teal-200" },
  erreur_analyse: { label: "Erreur d'analyse", cls: "bg-red-50 text-red-700 border-red-200" },
};

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.txt,.csv";
const POINTAGE = "liste_pointage";
// Scan de la liste : un PDF, ou les photos des pages. « image/* » laisse l'iPhone
// convertir lui-même ses photos HEIC en JPEG au moment du choix.
const ACCEPT_POINTAGE = ".pdf,.jpg,.jpeg,.png,.webp,image/*";
// Nom du JSON complété téléchargé (même règle que le serveur) :
// « InventaireSélectionné_PPH_INV067.json » → « …_INV067_complete.json ».
function jsonCompleteName(piece) {
  const base = (piece.inventaire_json_filename || "inventaire.json").replace(/\.json$/i, "");
  return `${base}_complete.json`;
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function StatusBadge({ status }) {
  const s = STATUS[status] || { label: status || "—", cls: "bg-slate-50 text-slate-600 border-slate-200" };
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${s.cls}`}>
      {status === "en_analyse" && <Loader2 className="w-3 h-3 animate-spin" />}
      {s.label}
    </span>
  );
}

// Vue pharmacie d'une pièce analysée : synthèse + champs extraits + alertes.
function PharmacySynthesis({ piece }) {
  if (piece.status === "en_analyse") {
    return <p className="text-sm text-slate-500">L'analyse de cette pièce est en cours…</p>;
  }
  const fields = Object.entries(piece.extracted_fields || {});
  return (
    <div className="space-y-3" data-testid={`ocr-synthesis-${piece.id}`}>
      {piece.document_type_guess && (
        <p className="text-sm"><span className="text-slate-500">Type reconnu : </span>{piece.document_type_guess}</p>
      )}
      <p className="text-sm text-slate-700 whitespace-pre-line">{piece.summary || "Aucune synthèse disponible."}</p>
      {fields.length > 0 && (
        <table className="w-full text-sm border border-slate-200 rounded">
          <tbody>
            {fields.map(([k, v]) => (
              <tr key={k} className="border-t border-slate-100 align-top">
                <td className="px-2 py-1 text-slate-500 w-1/3">{k}</td>
                <td className="px-2 py-1 whitespace-pre-wrap break-words">{displayValue(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(piece.flags || []).length > 0 && (
        <ul className="text-sm text-amber-700 list-disc pl-5">
          {piece.flags.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
      )}
    </div>
  );
}

// Sélecteur de fichier aux libellés TOUJOURS en français : le champ natif <input type="file">
// affiche « Choose File / No file chosen » selon la langue du navigateur ; il est masqué et
// déclenché par un bouton du site.
// Avec `multiple` (liste de pointage), plusieurs fichiers peuvent être choisis d'un coup :
// onChange reçoit alors le tableau des fichiers, et `libelle` remplace le nom affiché.
function ChoixFichier({ inputRef, accept, file, onChange, testId, multiple = false, libelle = "",
  className = "bg-slate-100 text-slate-700" }) {
  const affiche = libelle || (file ? file.name : "Aucun fichier choisi");
  return (
    <div className="flex items-center gap-3 text-sm">
      <input ref={inputRef} type="file" accept={accept} data-testid={testId} className="hidden" multiple={multiple}
        onChange={(e) => onChange(multiple ? Array.from(e.target.files || []) : (e.target.files?.[0] || null))} />
      <button type="button" onClick={() => inputRef.current?.click()} data-testid={`${testId}-bouton`}
        className={`px-3 py-1.5 rounded ${className} hover:brightness-95`}>
        {multiple ? "Choisir le PDF ou les photos" : "Choisir un fichier"}
      </button>
      <span className="text-slate-700 max-w-[260px] truncate" title={affiche} data-testid={`${testId}-nom`}>
        {affiche}
      </span>
    </div>
  );
}

// Liste de pointage : compte rendu détaillé (rédigé par le serveur, retours à la ligne
// conservés) + téléchargement du JSON complété à réimporter dans Aizenta.
function PointageReport({ piece, onDownloadJson }) {
  if (piece.status === "en_analyse") {
    return <p className="text-sm text-slate-500">Lecture de la liste de pointage en cours…</p>;
  }
  return (
    <div className="space-y-3" data-testid={`ocr-pointage-report-${piece.id}`}>
      <div className="text-sm text-slate-700 whitespace-pre-line bg-white border border-slate-200 rounded p-3">
        {piece.compte_rendu || piece.summary || "Aucun compte rendu disponible."}
      </div>
      {piece.json_complete_disponible && (
        <Button size="sm" onClick={() => onDownloadJson(piece)} className="bg-teal-600 hover:bg-teal-700"
          data-testid={`ocr-pointage-download-${piece.id}`}>
          <FileJson className="w-4 h-4 mr-1" /> Télécharger le JSON complété
        </Button>
      )}
    </div>
  );
}

// Résumé des analyses d'une pièce (admin) : « Sonnet 5 · 2,40 FCFA · ★4 ».
function RunsSummary({ runs }) {
  if (!runs?.length) return <span className="text-slate-400">—</span>;
  return (
    <div className="flex flex-col gap-0.5">
      {runs.map((r) => (
        <span key={r.id} className="inline-flex items-center gap-1 text-xs text-slate-600">
          {shortModel(r.model)} · {formatXof(r.cost_xof)}
          {r.rating ? <StarRating value={r.rating} size={12} /> : <span className="text-slate-400">· non évaluée</span>}
        </span>
      ))}
    </div>
  );
}

export default function OcrPieces() {
  const { user } = useAuth();
  const isStaff = user?.role === "admin" || user?.role === "superviseur";

  const [view, setView] = useState("pieces");          // "pieces" | "dashboard" (admin)
  const [pieces, setPieces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);       // id de la pièce dépliée

  // Référentiels admin : pharmacies et modèles d'IA.
  const [tenants, setTenants] = useState([]);
  const [catalog, setCatalog] = useState({ models: [], default_model: "" });
  const [tenantFilter, setTenantFilter] = useState(ALL_TENANTS);

  // Formulaire de dépôt.
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  // Liste de pointage sans scanner : photos des pages (au moins 2), triées par nom.
  const [photos, setPhotos] = useState([]);
  const [kind, setKind] = useState("facture");
  const [uploadTenant, setUploadTenant] = useState("");
  const [uploadModel, setUploadModel] = useState("");
  const [uploading, setUploading] = useState(false);
  // Liste de pointage : JSON de l'inventaire (export WinDev) joint au scan.
  const jsonRef = useRef(null);
  const [jsonFile, setJsonFile] = useState(null);
  const isPointage = kind === POINTAGE;

  // Changement de type : les photos multiples ne valent que pour une liste de pointage.
  useEffect(() => {
    if (!isPointage && photos.length) {
      setPhotos([]);
      if (fileRef.current) fileRef.current.value = "";
    }
  }, [isPointage, photos.length]);

  // Choix pour une liste de pointage : un seul fichier (PDF ou photo) → envoi classique ;
  // plusieurs → uniquement des photos, assemblées en PDF par le serveur.
  const choisirPointage = (fichiers) => {
    if (fichiers.length <= 1) {
      setPhotos([]);
      setFile(fichiers[0] || null);
      return;
    }
    const nonPhotos = fichiers.filter((f) => !estPhoto(f));
    if (nonPhotos.length) {
      toast.error("Plusieurs fichiers : uniquement des photos (JPG, PNG, WEBP). Pour un PDF, choisissez-le seul.");
      if (fileRef.current) fileRef.current.value = "";
      return;
    }
    setFile(null);
    setPhotos([...fichiers].sort(triNaturel));
  };
  const libellePhotos = photos.length
    ? `${photos.length} photos (${photos[0].name} → ${photos[photos.length - 1].name})`
    : "";

  // Liste des pièces (admin : filtrable par pharmacie ; pharmacie : les siennes, filtrées par le serveur).
  const loadPieces = useCallback(async () => {
    try {
      const params = isStaff && tenantFilter !== ALL_TENANTS ? { tenant_id: tenantFilter } : {};
      const { data } = await apiClient.get(API_BASE, { params });
      setPieces(data || []);
    } catch (err) {
      toast.error(errorMessage(err, "Impossible de charger les pièces"));
    } finally {
      setLoading(false);
    }
  }, [isStaff, tenantFilter]);

  useEffect(() => { loadPieces(); }, [loadPieces]);

  // Référentiels admin chargés une fois.
  useEffect(() => {
    if (!isStaff) return;
    apiClient.get(`${API_BASE}/tenants`).then((r) => setTenants(r.data || [])).catch(() => setTenants([]));
    apiClient.get(`${API_BASE}/ocr-models`).then((r) => {
      setCatalog(r.data || { models: [] });
      setUploadModel(r.data?.default_model || "");
    }).catch(() => {});
  }, [isStaff]);

  // Tant qu'une analyse tourne, la liste se rafraîchit toutes les 4 secondes.
  const analysing = useMemo(() => pieces.some((p) => p.status === "en_analyse"), [pieces]);
  useEffect(() => {
    if (!analysing) return undefined;
    const t = setInterval(loadPieces, 4000);
    return () => clearInterval(t);
  }, [analysing, loadPieces]);

  const tenantName = (t) => [t.company || t.full_name, t.client_code].filter(Boolean).join(" · ");

  // Dépôt d'une pièce : l'analyse démarre aussitôt côté serveur.
  const upload = async () => {
    if (!file && !photos.length) return;
    if (isStaff && !uploadTenant) {
      toast.error("Choisissez la pharmacie concernée");
      return;
    }
    if (isPointage && !jsonFile) {
      toast.error("Joignez le fichier JSON de l'inventaire");
      return;
    }
    setUploading(true);
    const form = new FormData();
    if (photos.length) {
      // Pages photographiées : réduites ici (envoi plus rapide sur mobile), dans l'ordre.
      const reduites = await Promise.all(photos.map(reduirePhoto));
      reduites.forEach((p) => form.append("photos", p));
    } else {
      form.append("file", file);
    }
    form.append("kind", kind);
    if (isPointage) form.append("inventaire_json", jsonFile);
    if (isStaff) {
      form.append("tenant_id", uploadTenant);
      if (uploadModel) form.append("model", uploadModel);
    }
    try {
      await apiClient.post(API_BASE, form);
      toast.success("Pièce déposée — analyse en cours…");
      setFile(null);
      setPhotos([]);
      if (fileRef.current) fileRef.current.value = "";
      setJsonFile(null);
      if (jsonRef.current) jsonRef.current.value = "";
      loadPieces();
    } catch (err) {
      toast.error(errorMessage(err, "Dépôt impossible"));
    } finally {
      setUploading(false);
    }
  };

  // Téléchargement authentifié (le jeton est ajouté par apiClient).
  const download = async (piece) => {
    try {
      const res = await apiClient.get(`${API_BASE}/${piece.id}/download`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = piece.original_filename || "piece";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (err) {
      toast.error(errorMessage(err, "Téléchargement impossible"));
    }
  };

  // Liste de pointage : JSON de l'inventaire complété par la dernière analyse.
  const downloadJson = async (piece) => {
    try {
      const res = await apiClient.get(`${API_BASE}/${piece.id}/json-complete`, { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = jsonCompleteName(piece);
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (err) {
      toast.error(errorMessage(err, "Téléchargement du JSON impossible"));
    }
  };

  const remove = async (piece) => {
    if (!window.confirm(`Supprimer la pièce « ${piece.original_filename} » et ses analyses ?`)) return;
    try {
      await apiClient.delete(`${API_BASE}/${piece.id}`);
      if (expanded === piece.id) setExpanded(null);
      loadPieces();
    } catch (err) {
      toast.error(errorMessage(err, "Suppression impossible"));
    }
  };

  const colCount = isStaff ? 7 : 6;

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-6" data-testid="ocr-pieces-page">
      {/* En-tête + bascule admin Pièces / Tableau de bord */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-display font-bold text-slate-800 flex items-center gap-2">
          <ScanText className="w-6 h-6 text-teal-600" /> OCR sur Pièces
        </h1>
        {isStaff && (
          <div className="inline-flex rounded-md border border-slate-200 overflow-hidden">
            <button type="button" onClick={() => setView("pieces")} data-testid="ocr-view-pieces"
              className={`px-3 py-1.5 text-sm flex items-center gap-1 ${view === "pieces" ? "bg-teal-600 text-white" : "bg-white text-slate-600"}`}>
              <FileText className="w-4 h-4" /> Pièces
            </button>
            <button type="button" onClick={() => setView("dashboard")} data-testid="ocr-view-dashboard"
              className={`px-3 py-1.5 text-sm flex items-center gap-1 ${view === "dashboard" ? "bg-teal-600 text-white" : "bg-white text-slate-600"}`}>
              <BarChart3 className="w-4 h-4" /> Tableau de bord OCR
            </button>
          </div>
        )}
      </div>

      {view === "dashboard" && isStaff ? <OcrDashboard apiBase={API_BASE} /> : (
        <>
          {/* Dépôt d'une pièce */}
          <div className="bg-white border border-slate-200 rounded-lg p-4 space-y-3">
            <p className="text-sm text-slate-600">
              Déposez une facture, un bon de livraison ou un reçu (PDF, photo JPG/PNG/WEBP, texte — 20 Mo max).
              L'IA en extrait automatiquement les informations principales.
            </p>
            {isPointage && (
              <p className="text-sm text-teal-800 bg-teal-50 border border-teal-200 rounded px-3 py-2"
                data-testid="ocr-pointage-help">
                <b>Liste de pointage :</b> déposez le scan de la liste remplie à la main (PDF) ou, sans
                scanner, choisissez d'un coup toutes les photos des pages prises au téléphone (triées par
                leur nom, dans l'ordre des prises), et joignez le fichier JSON de l'inventaire exporté par WinDev. Les colonnes INV Mag, INV SV
                et Pérempt° sont lues et reportées dans le JSON (produits retrouvés par leur intitulé), à
                télécharger ensuite avec le bouton <FileJson className="w-3.5 h-3.5 inline" />.
              </p>
            )}
            <div className="flex flex-wrap items-end gap-3">
              <ChoixFichier inputRef={fileRef} accept={isPointage ? ACCEPT_POINTAGE : ACCEPT} file={file}
                onChange={isPointage ? choisirPointage : setFile} multiple={isPointage}
                libelle={isPointage ? libellePhotos : ""} testId="ocr-file-input" />
              {isPointage && (
                <div className="flex flex-col text-xs text-slate-500 gap-1">
                  JSON de l'inventaire
                  <ChoixFichier inputRef={jsonRef} accept=".json,application/json" file={jsonFile}
                    onChange={setJsonFile} testId="ocr-json-input" className="bg-teal-50 text-teal-700" />
                </div>
              )}
              <div className="w-44">
                <Select value={kind} onValueChange={setKind}>
                  <SelectTrigger data-testid="ocr-kind-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {KINDS.map((k) => <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              {isStaff && (
                <>
                  <div className="w-56">
                    <Select value={uploadTenant} onValueChange={setUploadTenant}>
                      <SelectTrigger data-testid="ocr-tenant-select"><SelectValue placeholder="Pharmacie…" /></SelectTrigger>
                      <SelectContent>
                        {tenants.map((t) => <SelectItem key={t.id} value={t.id}>{tenantName(t)}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="w-52">
                    <Select value={uploadModel} onValueChange={setUploadModel}>
                      <SelectTrigger data-testid="ocr-model-select"><SelectValue placeholder="Modèle d'IA" /></SelectTrigger>
                      <SelectContent>
                        {(catalog.models || []).map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.label || shortModel(m.id)}{m.id === catalog.default_model ? " (défaut)" : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}
              <Button onClick={upload} disabled={(!file && !photos.length) || uploading || (isPointage && !jsonFile)} data-testid="ocr-upload-btn"
                className="bg-teal-600 hover:bg-teal-700">
                {uploading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Upload className="w-4 h-4 mr-1" />}
                Déposer et analyser
              </Button>
            </div>
          </div>

          {/* Liste des pièces */}
          <div className="bg-white border border-slate-200 rounded-lg">
            <div className="flex flex-wrap items-center justify-between gap-3 p-3 border-b border-slate-100">
              <span className="text-sm font-medium text-slate-700">{pieces.length} pièce(s)</span>
              <div className="flex items-center gap-2">
                {isStaff && (
                  <div className="w-56">
                    <Select value={tenantFilter} onValueChange={setTenantFilter}>
                      <SelectTrigger data-testid="ocr-tenant-filter"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value={ALL_TENANTS}>Toutes les pharmacies</SelectItem>
                        {tenants.map((t) => <SelectItem key={t.id} value={t.id}>{tenantName(t)}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <Button variant="outline" size="sm" onClick={loadPieces} data-testid="ocr-refresh-btn">
                  <RefreshCw className="w-4 h-4" />
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-slate-500 text-left">
                  <tr>
                    <th className="px-3 py-2 w-6" />
                    <th className="px-3 py-2">Date</th>
                    <th className="px-3 py-2">Pièce</th>
                    {isStaff && <th className="px-3 py-2">Pharmacie</th>}
                    <th className="px-3 py-2">Statut</th>
                    <th className="px-3 py-2">{isStaff ? "Analyses" : "Synthèse"}</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && (
                    <tr><td colSpan={colCount} className="px-3 py-6 text-center text-slate-400">
                      <Loader2 className="w-4 h-4 inline animate-spin mr-1" /> Chargement…
                    </td></tr>
                  )}
                  {!loading && pieces.length === 0 && (
                    <tr><td colSpan={colCount} className="px-3 py-6 text-center text-slate-400">Aucune pièce déposée.</td></tr>
                  )}
                  {pieces.map((p) => (
                    <React.Fragment key={p.id}>
                      <tr className="border-t border-slate-100 align-top hover:bg-slate-50/60" data-testid={`ocr-piece-row-${p.id}`}>
                        <td className="px-3 py-2">
                          <button type="button" onClick={() => setExpanded(expanded === p.id ? null : p.id)}
                            aria-label="Détail" data-testid={`ocr-expand-${p.id}`} className="text-slate-500">
                            {expanded === p.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          </button>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">{formatDate(p.created_at)}</td>
                        <td className="px-3 py-2">
                          <div className="font-medium text-slate-700 break-all">{p.original_filename}</div>
                          <div className="text-xs text-slate-500">{KIND_LABEL[p.kind] || p.kind}</div>
                        </td>
                        {isStaff && (
                          <td className="px-3 py-2">{[p.tenant_label, p.client_code].filter(Boolean).join(" · ") || "—"}</td>
                        )}
                        <td className="px-3 py-2"><StatusBadge status={p.status} /></td>
                        <td className="px-3 py-2 max-w-xs">
                          {isStaff ? <RunsSummary runs={p.ocr_runs} /> : (
                            <span className="text-slate-600 line-clamp-2">{p.summary || "—"}</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          {p.kind === POINTAGE && p.json_complete_disponible && (
                            <Button variant="ghost" size="sm" onClick={() => downloadJson(p)}
                              title="Télécharger le JSON complété" data-testid={`ocr-json-complete-${p.id}`}>
                              <FileJson className="w-4 h-4 text-teal-600" />
                            </Button>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => download(p)} title="Télécharger"
                            data-testid={`ocr-download-${p.id}`}>
                            <Download className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => remove(p)} title="Supprimer"
                            data-testid={`ocr-delete-${p.id}`}>
                            <Trash2 className="w-4 h-4 text-red-500" />
                          </Button>
                        </td>
                      </tr>
                      {expanded === p.id && (
                        <tr className="bg-slate-50/60">
                          <td colSpan={colCount} className="px-4 py-3">
                            {p.kind === POINTAGE && (
                              <div className={isStaff ? "mb-4" : ""}>
                                <PointageReport piece={p} onDownloadJson={downloadJson} />
                              </div>
                            )}
                            {isStaff ? (
                              <OcrRunsPanel apiBase={API_BASE} doc={p} models={catalog.models}
                                defaultModel={catalog.default_model} onChanged={loadPieces} />
                            ) : (
                              p.kind !== POINTAGE && <PharmacySynthesis piece={p} />
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
