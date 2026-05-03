import React, { useEffect, useRef, useState } from "react";
import { apiClient, API } from "@/lib/api";
import { toast } from "sonner";
import {
  Shield, FileText, Trash, Upload, ExternalLink, Copy, RefreshCw, AlertTriangle, CheckCircle2, FileCheck, Calendar, User,
} from "lucide-react";

/*
  Admin → Politiques publiques
  3 slots fixes (privacy, services, deletion). Chaque slot accepte un PDF (≤15 Mo)
  qui est servi via /api/public/policies/{slot} pour Google/Facebook/partenaires.
*/
const SLOT_META = {
  privacy: { icon: Shield, color: "from-emerald-500 to-emerald-600", iconBg: "bg-emerald-100 text-emerald-600", desc: "Conformité RGPD : collecte, stockage, droits des utilisateurs." },
  services: { icon: FileText, color: "from-sky-500 to-sky-600", iconBg: "bg-sky-100 text-sky-600", desc: "Conditions générales d'utilisation des services SAWALI." },
  deletion: { icon: Trash, color: "from-rose-500 to-rose-600", iconBg: "bg-rose-100 text-rose-600", desc: "Procédure de suppression des comptes et des données utilisateurs." },
};

function fmtSize(bytes) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} Mo`;
}

export default function AdminPolicies() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/policies");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const onUploaded = async () => { await load(); };

  return (
    <div className="max-w-6xl space-y-6" data-testid="admin-policies-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Conformité</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Shield className="h-5 w-5 text-emerald-600" /> Politiques publiques
          </h1>
          <p className="text-sm text-slate-500">
            Hébergez vos politiques RGPD, services et suppression. Les liens publics ci-dessous peuvent être partagés à Google, Facebook et autres tiers pour vérification.
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
          data-testid="policies-refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Rafraîchir
        </button>
      </div>

      {loading ? (
        <div className="text-center text-slate-500 py-10">Chargement…</div>
      ) : (
        <div className="grid md:grid-cols-3 gap-4">
          {items.map((it) => (
            <PolicyCard key={it.slot} item={it} onUploaded={onUploaded} />
          ))}
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
        <p className="font-semibold text-slate-700 mb-1">Comment vérifier la présence avec Google / Facebook ?</p>
        <ol className="list-decimal pl-5 space-y-0.5">
          <li>Cliquez sur <strong>Copier</strong> sur la politique concernée pour récupérer le lien public.</li>
          <li>Collez le lien dans Google Search Console / Facebook Business Manager / Meta App Review.</li>
          <li>Le PDF est servi en <code className="bg-white px-1 rounded">application/pdf</code> avec <code className="bg-white px-1 rounded">X-Robots-Tag: all</code> pour autoriser l'indexation.</li>
        </ol>
      </div>
    </div>
  );
}

function PolicyCard({ item, onUploaded }) {
  const meta = SLOT_META[item.slot] || SLOT_META.services;
  const Icon = meta.icon;
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.type !== "application/pdf" && !f.name.toLowerCase().endsWith(".pdf")) {
      toast.error("Format invalide : PDF requis");
      e.target.value = "";
      return;
    }
    if (f.size > 15 * 1024 * 1024) {
      toast.error("Fichier trop volumineux (max 15 Mo)");
      e.target.value = "";
      return;
    }
    const data = new FormData();
    data.append("file", f);
    setUploading(true);
    setProgress(0);
    try {
      await apiClient.post(`/admin/policies/${item.slot}/upload`, data, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (evt) => {
          if (evt.total) setProgress(Math.round((evt.loaded / evt.total) * 100));
        },
      });
      toast.success(item.present ? "Politique remplacée" : "Politique publiée");
      await onUploaded();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally {
      setUploading(false);
      setProgress(0);
      if (e.target) e.target.value = "";
    }
  };

  const remove = async () => {
    if (!window.confirm(`Retirer "${item.label}" du site public ?`)) return;
    try {
      await apiClient.delete(`/admin/policies/${item.slot}`);
      toast.success("Retirée");
      await onUploaded();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(item.public_url);
      toast.success("Lien copié");
    } catch {
      toast.error("Impossible de copier");
    }
  };

  return (
    <div
      className={`rounded-xl border-2 ${item.present ? "border-emerald-200" : "border-slate-200"} bg-white overflow-hidden`}
      data-testid={`policy-card-${item.slot}`}
    >
      <div className={`h-1.5 bg-gradient-to-r ${meta.color}`} />
      <div className="p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className={`h-10 w-10 rounded-lg ${meta.iconBg} flex items-center justify-center shrink-0`}>
            <Icon className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-display font-bold text-slate-900 leading-tight">{item.label}</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">{meta.desc}</p>
          </div>
          {item.present ? (
            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 shrink-0">
              <CheckCircle2 className="h-2.5 w-2.5" /> Publiée
            </span>
          ) : (
            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 shrink-0">
              <AlertTriangle className="h-2.5 w-2.5" /> Non publiée
            </span>
          )}
        </div>

        {item.present && (
          <div className="rounded-lg bg-slate-50 border border-slate-200 p-2.5 text-[11px] space-y-1">
            <div className="flex items-center gap-1.5 text-slate-700">
              <FileCheck className="h-3 w-3 text-emerald-600" />
              <span className="font-medium truncate flex-1">{item.filename}</span>
              <span className="text-slate-400 font-mono">{fmtSize(item.size)}</span>
            </div>
            <div className="flex items-center gap-1.5 text-slate-500">
              <Calendar className="h-3 w-3" />
              <span>{item.uploaded_at ? new Date(item.uploaded_at).toLocaleString("fr-FR") : "—"}</span>
            </div>
            {item.uploaded_by_label && (
              <div className="flex items-center gap-1.5 text-slate-500">
                <User className="h-3 w-3" />
                <span className="truncate">{item.uploaded_by_label}</span>
              </div>
            )}
          </div>
        )}

        {/* Public URL */}
        <div className="rounded-lg border border-slate-200 bg-white p-2 text-[11px]">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1 font-semibold">Lien public</p>
          <div className="flex items-center gap-1.5">
            <code className="flex-1 truncate font-mono text-[11px] text-slate-700 bg-slate-50 px-1.5 py-1 rounded">
              {item.public_url}
            </code>
            <button
              onClick={copyLink}
              className="rounded p-1 text-slate-500 hover:bg-slate-100"
              title="Copier le lien"
              data-testid={`policy-copy-${item.slot}`}
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
            <a
              href={item.public_url}
              target="_blank"
              rel="noopener noreferrer"
              className={`rounded p-1 ${item.present ? "text-slate-500 hover:bg-slate-100" : "text-slate-300 cursor-not-allowed"}`}
              onClick={(e) => { if (!item.present) e.preventDefault(); }}
              title={item.present ? "Ouvrir le PDF" : "Aucun PDF publié"}
              data-testid={`policy-open-${item.slot}`}
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>

        {/* Upload progress */}
        {uploading && (
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-2 text-[11px] text-emerald-800">
            <div className="flex justify-between mb-1">
              <span>Envoi en cours…</span>
              <span className="font-mono">{progress}%</span>
            </div>
            <div className="h-1.5 bg-emerald-100 rounded overflow-hidden">
              <div className="h-full bg-emerald-600 transition-all" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            onChange={onFile}
            className="hidden"
            data-testid={`policy-file-input-${item.slot}`}
          />
          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-sawali-blue text-white px-3 py-2 text-xs hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid={`policy-upload-${item.slot}`}
          >
            <Upload className="h-3.5 w-3.5" />
            {item.present ? "Remplacer le PDF" : "Charger le PDF"}
          </button>
          {item.present && (
            <button
              onClick={remove}
              disabled={uploading}
              className="inline-flex items-center justify-center gap-1 rounded-lg bg-rose-500 text-white px-3 py-2 text-xs hover:bg-rose-600 disabled:opacity-50"
              title="Retirer du site public"
              data-testid={`policy-delete-${item.slot}`}
            >
              <Trash className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <p className="text-[10px] text-slate-400">Format PDF · max 15 Mo</p>
      </div>
    </div>
  );
}
