// S038 — Qdrant RAG management UI for AdminSettings.
// Connection · Collections list/create/delete · Per-collection points
// browse / upsert text / PDF / URL / search · Migrate MongoDB KB.
import React, { useEffect, useState, useCallback } from "react";
import { apiClient } from "@/lib/api";
import {
  Database, RefreshCw, Loader2, Plus, Trash2, Search, FileText, Upload,
  Link as LinkIcon, ToggleLeft, ToggleRight, CheckCircle2, XCircle,
  AlertCircle, ArrowRightCircle, Eye, X, Image as ImageIcon,
} from "lucide-react";
import { toast } from "sonner";

const _BYTES_PER_VECTOR_DISPLAY = 384 * 4 * 1.30 + 512;

export default function QdrantRagSection() {
  const [status, setStatus] = useState(null);
  const [statusErr, setStatusErr] = useState(null);
  const [storage, setStorage] = useState(null);
  const [collections, setCollections] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeColl, setActiveColl] = useState(null);

  const testConn = useCallback(async () => {
    setStatus(null); setStatusErr(null);
    try {
      const r = await apiClient.post("/admin/qdrant/test-connection");
      setStatus(r.data); toast.success("Connexion Qdrant OK");
    } catch (e) {
      setStatusErr(e?.response?.data?.detail || "Erreur");
    }
  }, []);

  const loadStorage = useCallback(async () => {
    try {
      const r = await apiClient.get("/admin/qdrant/storage");
      setStorage(r.data);
    } catch { /* noop */ }
  }, []);

  const loadCollections = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/qdrant/collections");
      setCollections(r.data?.items || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement collections");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { testConn(); loadCollections(); loadStorage(); }, [testConn, loadCollections, loadStorage]);

  const createCollection = async () => {
    const name = window.prompt("Nom de la nouvelle collection ? (a-z, 0-9, _, -)");
    if (!name) return;
    try {
      await apiClient.post("/admin/qdrant/collections", { name, description: "" });
      toast.success(`Collection « ${name} » créée`);
      loadCollections();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Création échouée");
    }
  };

  const deleteCollection = async (name) => {
    if (!window.confirm(`Supprimer la collection « ${name} » et TOUS ses vecteurs ?`)) return;
    try {
      await apiClient.delete(`/admin/qdrant/collections/${encodeURIComponent(name)}`);
      toast.success(`Collection « ${name} » supprimée`);
      if (activeColl === name) setActiveColl(null);
      loadCollections();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Suppression échouée");
    }
  };

  const toggleEnabled = async (col) => {
    try {
      await apiClient.patch(`/admin/qdrant/collections/${encodeURIComponent(col.name)}`, {
        enabled_for_liluvine: !col.enabled_for_liluvine,
      });
      loadCollections();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Toggle échoué");
    }
  };

  const migrateMongo = async () => {
    if (!activeColl) { toast.info("Sélectionnez d'abord une collection cible"); return; }
    if (!window.confirm(`Importer toute la KB MongoDB existante dans « ${activeColl} » ?`)) return;
    try {
      const r = await apiClient.post("/admin/qdrant/migrate-mongo-kb", { collection: activeColl });
      toast.success(`Migration : ${r.data.inserted_chunks} chunks importés de la KB Mongo.`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Migration échouée");
    }
  };

  return (
    <div className="space-y-4">
      {/* Connection status */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="h-11 w-11 rounded-lg bg-indigo-50 flex items-center justify-center">
              <Database className="h-5 w-5 text-indigo-600" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Qdrant Cloud</p>
              <h3 className="font-display font-bold text-slate-900">Base de connaissance vectorielle (RAG sémantique)</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Connexion via les variables <code>QDRANT_URL</code> / <code>QDRANT_API_KEY</code> ou via les paramètres ci-dessous.
              </p>
            </div>
          </div>
          <button
            onClick={testConn}
            className="text-xs inline-flex items-center gap-1 px-3 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white"
            data-testid="qdrant-test-connection-btn"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Tester la connexion
          </button>
        </div>
        {status && (
          <div className="mt-3 text-xs px-3 py-2 rounded-lg bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 inline-flex items-center gap-2" data-testid="qdrant-status-ok">
            <CheckCircle2 className="h-4 w-4" /> Connecté · {status.collections} collection(s) côté serveur
          </div>
        )}
        {statusErr && (
          <div className="mt-3 text-xs px-3 py-2 rounded-lg bg-rose-50 text-rose-700 ring-1 ring-rose-200 inline-flex items-center gap-2" data-testid="qdrant-status-err">
            <XCircle className="h-4 w-4" /> {statusErr}
          </div>
        )}
        {storage && (
          <div className="mt-3" data-testid="qdrant-storage-panel">
            <div className="flex items-center justify-between text-[11px] text-slate-600 mb-1">
              <span className="font-semibold">Stockage Qdrant Cloud</span>
              <span className="tabular-nums">
                <strong className={storage.pct_used >= 80 ? "text-rose-600" : storage.pct_used >= 60 ? "text-amber-600" : "text-emerald-700"}>
                  {storage.estimated_size_mb.toFixed(2)} Mo
                </strong> / {storage.quota_mb} Mo ({storage.pct_used.toFixed(1)}%) · reste {storage.remaining_mb.toFixed(0)} Mo
              </span>
            </div>
            <div className="h-2 bg-slate-100 rounded-full overflow-hidden ring-1 ring-slate-200">
              <div
                className={`h-full transition-all ${storage.pct_used >= 80 ? "bg-rose-500" : storage.pct_used >= 60 ? "bg-amber-500" : "bg-emerald-500"}`}
                style={{ width: `${Math.min(100, storage.pct_used)}%` }}
              />
            </div>
            <p className="text-[10px] text-slate-400 mt-1">
              Estimation : {storage.total_points} vecteur(s) × {Math.round(_BYTES_PER_VECTOR_DISPLAY)} octets/vecteur (payload + index inclus).
              Free tier Qdrant Cloud = 1 Go.
            </p>
          </div>
        )}
      </div>

      {/* Collections list */}
      <div className="rounded-xl ring-1 ring-slate-200 bg-white p-4">
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <h4 className="font-semibold text-slate-800">Collections Qdrant ({collections.length})</h4>
          <div className="flex gap-2">
            <button onClick={loadCollections} disabled={loading}
              className="text-xs inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50">
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Rafraîchir
            </button>
            <button onClick={createCollection}
              className="text-xs inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white"
              data-testid="qdrant-create-collection-btn">
              <Plus className="h-3.5 w-3.5" /> Nouvelle
            </button>
          </div>
        </div>

        {collections.length === 0 && !loading && (
          <p className="text-xs text-slate-400 italic py-6 text-center">Aucune collection. Cliquez sur « Nouvelle » pour démarrer.</p>
        )}

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {collections.map((c) => (
            <div key={c.name} className={`rounded-lg ring-1 p-3 transition cursor-pointer ${activeColl === c.name ? "ring-indigo-500 bg-indigo-50/40" : "ring-slate-200 bg-white hover:ring-slate-300"}`} onClick={() => setActiveColl(c.name)} data-testid={`qdrant-collection-${c.name}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-mono font-semibold text-slate-900 truncate">{c.name}</p>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {c.vectors_count ?? "?"} vecteurs · {c.vector_size}d
                  </p>
                </div>
                <button onClick={(e) => { e.stopPropagation(); deleteCollection(c.name); }} className="text-rose-500 hover:text-rose-700 p-1" data-testid={`qdrant-delete-${c.name}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); toggleEnabled(c); }}
                className={`mt-2 w-full text-[11px] inline-flex items-center gap-1 px-2 py-1 rounded ${c.enabled_for_liluvine ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                data-testid={`qdrant-toggle-${c.name}`}
              >
                {c.enabled_for_liluvine ? <ToggleRight className="h-3.5 w-3.5" /> : <ToggleLeft className="h-3.5 w-3.5" />}
                {c.enabled_for_liluvine ? "Visible par Liluvine" : "Désactivée pour Liluvine"}
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Active collection panel */}
      {activeColl && (
        <CollectionWorkspace
          name={activeColl}
          onClose={() => setActiveColl(null)}
          onMigrate={migrateMongo}
        />
      )}
    </div>
  );
}

function CollectionWorkspace({ name, onClose, onMigrate }) {
  const [activeTab, setActiveTab] = useState("text");
  return (
    <div className="rounded-xl ring-2 ring-indigo-200 bg-white p-4" data-testid="qdrant-collection-workspace">
      <div className="flex items-center justify-between mb-3 gap-3">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-indigo-600" />
          <h4 className="font-display font-bold">Collection : <span className="font-mono">{name}</span></h4>
        </div>
        <div className="flex gap-2">
          <button onClick={onMigrate}
            className="text-xs inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg ring-1 ring-amber-300 text-amber-700 hover:bg-amber-50"
            data-testid="qdrant-migrate-btn"
            title="Importer la KB MongoDB existante dans cette collection">
            <ArrowRightCircle className="h-3.5 w-3.5" /> Migrer Mongo KB
          </button>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-slate-100" data-testid="qdrant-close-workspace">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="flex gap-1 mb-3 text-xs border-b border-slate-200" data-testid="qdrant-workspace-tabs">
        {[
          { k: "text", label: "Texte", icon: FileText },
          { k: "pdf", label: "PDF", icon: Upload },
          { k: "url", label: "URL", icon: LinkIcon },
          { k: "image", label: "Image", icon: ImageIcon },
          { k: "search", label: "Recherche", icon: Search },
          { k: "browse", label: "Parcourir", icon: Eye },
        ].map(({ k, label, icon: Icon }) => (
          <button
            key={k}
            onClick={() => setActiveTab(k)}
            className={`px-3 py-1.5 -mb-px inline-flex items-center gap-1.5 border-b-2 ${activeTab === k ? "border-indigo-600 text-indigo-700 font-semibold" : "border-transparent text-slate-500 hover:text-slate-700"}`}
            data-testid={`qdrant-tab-${k}`}
          >
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </div>
      {activeTab === "text" && <UpsertTextTab name={name} />}
      {activeTab === "pdf" && <UpsertPdfTab name={name} />}
      {activeTab === "url" && <UpsertUrlTab name={name} />}
      {activeTab === "image" && <UpsertImageTab name={name} />}
      {activeTab === "search" && <SearchTab name={name} />}
      {activeTab === "browse" && <BrowseTab name={name} />}
    </div>
  );
}

function UpsertImageTab({ name }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [autoDescribe, setAutoDescribe] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const submit = async () => {
    if (!file) { toast.error("Sélectionnez une image"); return; }
    setBusy(true); setResult(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", title);
    fd.append("caption", caption);
    fd.append("auto_describe", autoDescribe ? "on" : "off");
    try {
      const r = await apiClient.post(`/admin/qdrant/collections/${encodeURIComponent(name)}/points/image`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(r.data);
      toast.success("Image indexée et liée au point Qdrant.");
      setFile(null); setTitle(""); setCaption("");
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-3" data-testid="qdrant-upsert-image-tab">
      <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 p-3 text-[11px] text-amber-800">
        💡 Liluvine PRO pourra inclure cette image dans ses réponses chat pour illustrer le support
        (par exemple : « Voici la capture d'écran à laquelle vous faites référence ! »).
        Avec l'<strong>analyse Claude Vision</strong> activée, l'IA décrit automatiquement l'image
        (OCR + description visuelle) pour la rendre retrouvable même sans description manuelle.
      </div>
      <input
        type="file"
        accept="image/*"
        onChange={(e) => setFile(e.target.files?.[0] || null)}
        disabled={busy}
        className="block w-full text-sm"
        data-testid="qdrant-image-file"
      />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Titre court (ex: 'Écran de connexion')"
        maxLength={200}
        className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm"
        data-testid="qdrant-image-title"
      />
      <textarea
        value={caption}
        onChange={(e) => setCaption(e.target.value)}
        placeholder="Description manuelle (optionnel si Claude Vision activé)"
        rows={3}
        maxLength={2000}
        className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm"
        data-testid="qdrant-image-caption"
      />
      <label className="flex items-start gap-2 text-xs cursor-pointer rounded-lg ring-1 ring-indigo-200 bg-indigo-50 p-2">
        <input
          type="checkbox"
          checked={autoDescribe}
          onChange={(e) => setAutoDescribe(e.target.checked)}
          disabled={busy}
          className="mt-0.5 h-4 w-4 rounded text-indigo-600"
          data-testid="qdrant-image-auto-describe"
        />
        <span>
          <span className="font-semibold text-indigo-800">Analyser l'image avec Claude Vision</span>
          <span className="block text-[10px] text-indigo-700 mt-0.5">
            Extrait automatiquement le texte (OCR) + génère une description visuelle pour améliorer la recherche sémantique. Recommandé.
          </span>
        </span>
      </label>
      <p className="text-[10px] text-slate-400 tabular-nums">
        {file ? `${file.name} · ${Math.round(file.size / 1024)} Ko` : "Aucune image sélectionnée"}
      </p>
      <button
        onClick={submit}
        disabled={busy || !file}
        className="text-sm inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50"
        data-testid="qdrant-image-submit"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
        {busy && autoDescribe ? "Analyse Claude Vision…" : "Indexer l'image"}
      </button>
      {result && (
        <div className="rounded-lg ring-1 ring-emerald-200 bg-emerald-50 p-3 text-xs space-y-2" data-testid="qdrant-image-result">
          <p className="text-emerald-700 font-semibold">✓ Image indexée — Liluvine peut désormais la suggérer.</p>
          {result.image_url && (
            <img src={result.image_url} alt={result.title || "Image indexée"} className="max-h-40 rounded ring-1 ring-emerald-200" />
          )}
          {result.visual_summary && (
            <div className="rounded ring-1 ring-emerald-200 bg-white p-2">
              <p className="text-[10px] uppercase tracking-wider font-bold text-emerald-700 mb-0.5">Description Claude Vision</p>
              <p className="text-slate-700">{result.visual_summary}</p>
            </div>
          )}
          {result.ocr_text && (
            <details className="rounded ring-1 ring-emerald-200 bg-white p-2">
              <summary className="text-[10px] uppercase tracking-wider font-bold text-emerald-700 cursor-pointer">Texte OCR ({result.ocr_text.length} car.)</summary>
              <pre className="text-[11px] text-slate-700 whitespace-pre-wrap mt-1 max-h-40 overflow-y-auto">{result.ocr_text}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function UpsertTextTab({ name }) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!text.trim()) { toast.error("Texte requis"); return; }
    setBusy(true);
    try {
      const r = await apiClient.post(`/admin/qdrant/collections/${encodeURIComponent(name)}/points/text`, { title, text, source, tags: [] });
      toast.success(`${r.data.inserted_chunks} chunks indexés`);
      setTitle(""); setText(""); setSource("");
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Titre (optionnel)" className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm" data-testid="qdrant-text-title" />
      <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Texte à indexer (sera découpé en chunks de ~1200 caractères avec overlap)" rows={6} className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm" data-testid="qdrant-text-body" />
      <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="Source (ex: doc interne / FAQ #12)" className="w-full rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm" data-testid="qdrant-text-source" />
      <button onClick={submit} disabled={busy || !text.trim()} className="text-sm inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50" data-testid="qdrant-text-submit">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Indexer
      </button>
    </div>
  );
}

function UpsertPdfTab({ name }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const submit = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    setBusy(true); setResult(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await apiClient.post(`/admin/qdrant/collections/${encodeURIComponent(name)}/points/pdf`, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(r.data); toast.success(`PDF indexé : ${r.data.inserted_chunks} chunks`);
    } catch (err) { toast.error(err?.response?.data?.detail || "Lecture PDF échouée"); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <input type="file" accept="application/pdf" onChange={submit} disabled={busy} className="block w-full text-sm" data-testid="qdrant-pdf-input" />
      {busy && <p className="text-xs text-slate-500 inline-flex items-center gap-1"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Extraction + indexation…</p>}
      {result && <p className="text-xs text-emerald-600">✓ {result.inserted_chunks} chunks indexés.</p>}
    </div>
  );
}

function UpsertUrlTab({ name }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!url.trim()) return;
    setBusy(true);
    try {
      const r = await apiClient.post(`/admin/qdrant/collections/${encodeURIComponent(name)}/points/url`, { url });
      toast.success(`URL indexée : ${r.data.inserted_chunks} chunks`);
      setUrl("");
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://exemple.com/page" className="flex-1 rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm" data-testid="qdrant-url-input" />
        <button onClick={submit} disabled={busy || !url.trim()} className="text-sm inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white disabled:opacity-50" data-testid="qdrant-url-submit">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LinkIcon className="h-4 w-4" />} Récupérer
        </button>
      </div>
      <p className="text-[11px] text-slate-500">Le contenu HTML est scrapé (max 2 Mo), nettoyé puis chunké comme un texte standard.</p>
    </div>
  );
}

function SearchTab({ name }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!q.trim()) return;
    setBusy(true);
    try {
      const r = await apiClient.post(`/admin/qdrant/collections/${encodeURIComponent(name)}/search`, { query: q, top_k: 8 });
      setItems(r.data?.items || []);
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  };
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submit()} placeholder="Question ou mots-clés en français…" className="flex-1 rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm" data-testid="qdrant-search-input" />
        <button onClick={submit} disabled={busy || !q.trim()} className="text-sm inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white disabled:opacity-50" data-testid="qdrant-search-submit">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Rechercher
        </button>
      </div>
      {items.length > 0 && (
        <div className="space-y-2" data-testid="qdrant-search-results">
          {items.map((it) => (
            <div key={it.id} className="rounded-lg ring-1 ring-slate-200 p-3 bg-white">
              <div className="flex items-center justify-between mb-1">
                <p className="font-semibold text-sm text-slate-800">{it.title}</p>
                <span className="text-[11px] font-mono bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded">score {it.score.toFixed(3)}</span>
              </div>
              <p className="text-xs text-slate-600 whitespace-pre-wrap">{it.text}</p>
              {it.source && <p className="text-[10px] text-slate-400 mt-1">Source : {it.source}</p>}
            </div>
          ))}
        </div>
      )}
      {items.length === 0 && !busy && q && <p className="text-xs text-slate-400 italic">Aucun résultat — essayez d'autres mots.</p>}
    </div>
  );
}

function BrowseTab({ name }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await apiClient.get(`/admin/qdrant/collections/${encodeURIComponent(name)}/points?limit=50`);
      setItems(r.data?.items || []); setTotal(r.data?.total || 0);
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
    finally { setBusy(false); }
  }, [name]);
  useEffect(() => { load(); }, [load]);

  const remove = async (id) => {
    if (!window.confirm("Supprimer ce point ?")) return;
    try {
      await apiClient.delete(`/admin/qdrant/collections/${encodeURIComponent(name)}/points/${encodeURIComponent(id)}`);
      toast.success("Supprimé"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); }
  };

  if (busy) return <Loader2 className="h-4 w-4 animate-spin" />;
  if (items.length === 0) return <p className="text-xs text-slate-400 italic">Collection vide.</p>;
  return (
    <div className="space-y-2" data-testid="qdrant-browse-results">
      <p className="text-xs text-slate-500">{total} point(s) au total — affichage des 50 premiers.</p>
      {items.map((it) => (
        <div key={it.id} className="rounded-lg ring-1 ring-slate-200 p-3 bg-white flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-semibold text-sm text-slate-800">{it.title}</p>
            <p className="text-xs text-slate-600 mt-0.5">{it.text_preview}</p>
            {it.source && <p className="text-[10px] text-slate-400 mt-1">{it.source}</p>}
          </div>
          <button onClick={() => remove(it.id)} className="text-rose-500 hover:text-rose-700 p-1" data-testid={`qdrant-browse-delete-${it.id}`}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
