import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  BarChart3, ChevronDown, ChevronRight, Download, FileText, Loader2, RefreshCw, ScanText, Trash2, Upload,
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
  const [kind, setKind] = useState("facture");
  const [uploadTenant, setUploadTenant] = useState("");
  const [uploadModel, setUploadModel] = useState("");
  const [uploading, setUploading] = useState(false);

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
    if (!file) return;
    if (isStaff && !uploadTenant) {
      toast.error("Choisissez la pharmacie concernée");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    if (isStaff) {
      form.append("tenant_id", uploadTenant);
      if (uploadModel) form.append("model", uploadModel);
    }
    setUploading(true);
    try {
      await apiClient.post(API_BASE, form);
      toast.success("Pièce déposée — analyse en cours…");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
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
            <div className="flex flex-wrap items-end gap-3">
              <input ref={fileRef} type="file" accept={ACCEPT} data-testid="ocr-file-input"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="text-sm file:mr-3 file:px-3 file:py-1.5 file:rounded file:border-0 file:bg-slate-100 file:text-slate-700" />
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
              <Button onClick={upload} disabled={!file || uploading} data-testid="ocr-upload-btn"
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
                            {isStaff ? (
                              <OcrRunsPanel apiBase={API_BASE} doc={p} models={catalog.models}
                                defaultModel={catalog.default_model} onChanged={loadPieces} />
                            ) : (
                              <PharmacySynthesis piece={p} />
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
