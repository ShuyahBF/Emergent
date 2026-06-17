// Iter41 (2026-02) — Portail VIDAL France
// Page unifiée : recherche médicament + fiche médicament + analyse de prescription
// Trois onglets : Recherche, Catalogue, Analyse de prescription.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Stethoscope, Search, Loader2, AlertTriangle, FileText, Pill, ListChecks, Plus, X
} from "lucide-react";

const TABS = [
  { key: "search", label: "Recherche", icon: Search },
  { key: "catalog", label: "Catalogue", icon: ListChecks },
  { key: "analyze", label: "Analyse prescription", icon: AlertTriangle },
];

const FILTER_OPTIONS = [
  { value: "product", label: "Médicament (produit)" },
  { value: "package", label: "Présentation (boîte)" },
  { value: "ucd", label: "UCD (hospitalier)" },
  { value: "vmp", label: "VMP (virtuel)" },
];

const CATALOG_STATUSES = [
  { value: "NEW", label: "Nouveautés" },
  { value: "AVAILABLE", label: "Disponibles" },
  { value: "DELETED", label: "Retirés" },
  { value: "PHARMACO", label: "Vigilance" },
];

// Iter43-fix24p (2026-06) — Rendu enrichi des réponses VIDAL non-JSON
// VIDAL peut renvoyer du HTML (portail API explorer si endpoint invalide ou auth manquée)
// ou du XML/Atom (catalogue, pharmacovigilance). Cette fonction utilitaire détecte
// le format et propose un rendu adapté plutôt qu'un blob de texte brut.
function _detectResponseKind(raw) {
  if (typeof raw !== "string") return "unknown";
  const head = raw.trim().slice(0, 200).toLowerCase();
  if (head.startsWith("<!doctype html") || head.startsWith("<html")) return "html";
  if (head.startsWith("<?xml") || /<(feed|entry|atom|rss)\b/.test(head)) return "xml";
  return "text";
}

function _parseAtomEntries(xmlText) {
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlText, "application/xml");
    const errorNode = doc.querySelector("parsererror");
    if (errorNode) return null;
    const entryNodes = doc.querySelectorAll("entry");
    if (!entryNodes.length) return null;
    return Array.from(entryNodes).map((node) => {
      const get = (tag) => {
        const el = node.querySelector(tag);
        return el ? (el.textContent || "").trim() : "";
      };
      return {
        title: get("title") || get("name") || "(sans nom)",
        id: get("id") || get("vidalId"),
        type: get("type") || get("objectType") || "-",
        summary: get("summary") || get("description") || "",
        updated: get("updated") || "",
      };
    });
  } catch {
    return null;
  }
}

function RawResponseViewer({ raw, contentLength = 0 }) {
  const [view, setView] = React.useState("rendered"); // rendered | source
  const kind = _detectResponseKind(raw);

  // Iter43-fix24s (2026-06-16) — Détection enrichie des pages HTML VIDAL :
  //   1. Page d'accueil de l'API explorer (Angular SPA) → URL contient `#!/`
  //   2. Page d'erreur générique « Oops! Something went wrong »
  const looksLikeApiExplorer = kind === "html"
    && (raw.includes("data-ng-app=\"app\"") || raw.includes("data-ng-controller=\"MainCtrl\""));
  const looksLikeErrorPage = kind === "html"
    && /Oops!?\s*Something went wrong/i.test(raw);

  // XML/Atom → tente de parser
  const atomEntries = kind === "xml" ? _parseAtomEntries(raw) : null;

  const copyToClipboard = () => {
    try { navigator.clipboard.writeText(raw || ""); toast.success("Réponse copiée"); }
    catch { toast.error("Copie impossible"); }
  };

  if (kind === "html") {
    return (
      <div className="space-y-2" data-testid="vidal-raw-html-viewer">
        {looksLikeApiExplorer && (
          <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-xs text-amber-900 leading-relaxed" data-testid="vidal-explorer-warning">
            <p className="font-semibold mb-1">⚠️ VIDAL a renvoyé la page d&apos;accueil de l&apos;API explorer</p>
            <p>Cela arrive quand :</p>
            <ul className="list-disc pl-5 mt-1 space-y-0.5">
              <li>Le <code>base_url</code> dans <strong>Admin → Paramètres → VIDAL</strong> pointe sur le portail explorer (URL contenant <code>#!/</code>)</li>
              <li>L&apos;<code>app_id</code> ou l&apos;<code>app_key</code> est invalide pour ce mode (test/prod)</li>
              <li>L&apos;endpoint demandé n&apos;existe pas (chemin incorrect)</li>
            </ul>
            <p className="mt-2 italic">La page complète VIDAL est affichée ci-dessous pour info.</p>
          </div>
        )}
        {looksLikeErrorPage && !looksLikeApiExplorer && (
          <div className="rounded-lg bg-rose-50 ring-1 ring-rose-200 p-3 text-xs text-rose-900 leading-relaxed" data-testid="vidal-error-page-warning">
            <p className="font-semibold mb-1">🚫 VIDAL a renvoyé une page d&apos;erreur générique</p>
            <p>Le serveur a accepté la requête mais ne peut pas répondre. Causes probables :</p>
            <ul className="list-disc pl-5 mt-1 space-y-0.5">
              <li>Endpoint inexistant sur cet environnement (vérifier <code>test</code> vs <code>production</code>)</li>
              <li>Credentials VIDAL invalides ou expirés</li>
              <li>Le <code>base_url</code> n&apos;est pas correct (doit inclure le bon préfixe REST)</li>
            </ul>
          </div>
        )}
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] text-slate-500">
            🌐 Réponse HTML reçue ({Math.round((contentLength || raw.length) / 1024)} Ko)
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setView(view === "rendered" ? "source" : "rendered")}
              className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
              data-testid="vidal-raw-toggle-view"
            >
              {view === "rendered" ? "Voir source HTML" : "Voir rendu"}
            </button>
            <button
              type="button"
              onClick={copyToClipboard}
              className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
              data-testid="vidal-raw-copy"
            >
              Copier
            </button>
          </div>
        </div>
        {view === "rendered" ? (
          <div className="rounded-lg ring-1 ring-slate-200 bg-white overflow-hidden">
            <iframe
              title="VIDAL response"
              srcDoc={raw}
              // Iter43-fix24u (2026-06-16) — `allow-scripts` + `allow-same-origin`
              // sont nécessaires pour : (1) que les scripts AngularJS s'exécutent,
              // (2) que les XHR vers `/api/vidal/proxy/...` partagent l'origine
              // du frontal (sinon CORS bloque). Le backend transmet à VIDAL
              // côté serveur avec les credentials, donc aucune fuite client-side.
              sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              referrerPolicy="no-referrer"
              className="w-full"
              style={{ height: "60vh", border: "none", background: "white" }}
              data-testid="vidal-raw-iframe"
            />
          </div>
        ) : (
          <pre className="text-[10px] bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-80 font-mono whitespace-pre-wrap" data-testid="vidal-raw-source">
            {raw.slice(0, 20000)}
            {raw.length > 20000 && "\n\n… (tronqué — utilisez Copier pour récupérer le contenu complet)"}
          </pre>
        )}
      </div>
    );
  }

  if (kind === "xml" && atomEntries && atomEntries.length > 0) {
    return (
      <div className="space-y-2" data-testid="vidal-raw-atom-viewer">
        <div className="text-[11px] text-emerald-700">
          📑 Réponse Atom/XML parsée — {atomEntries.length} entrée{atomEntries.length > 1 ? "s" : ""}
        </div>
        <table className="w-full text-xs ring-1 ring-slate-200 rounded">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="text-left px-2 py-1.5">Titre</th>
              <th className="text-left px-2 py-1.5">ID</th>
              <th className="text-left px-2 py-1.5">Type</th>
              <th className="text-left px-2 py-1.5">Résumé</th>
            </tr>
          </thead>
          <tbody>
            {atomEntries.slice(0, 50).map((e, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-2 py-1.5 font-semibold">{e.title}</td>
                <td className="px-2 py-1.5 font-mono text-[10px] text-slate-500">{e.id || "?"}</td>
                <td className="px-2 py-1.5 text-slate-500">{e.type}</td>
                <td className="px-2 py-1.5 text-slate-600 max-w-[400px] truncate" title={e.summary}>{e.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {atomEntries.length > 50 && (
          <p className="text-[10px] text-slate-500 italic">… {atomEntries.length - 50} entrées non affichées (limite UI 50).</p>
        )}
      </div>
    );
  }

  // Fallback : texte brut / JSON
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-slate-500">
          📄 Réponse texte ({Math.round((raw || "").length / 1024)} Ko)
        </div>
        <button
          type="button"
          onClick={copyToClipboard}
          className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
          data-testid="vidal-raw-copy-text"
        >
          Copier
        </button>
      </div>
      <pre className="text-[10px] bg-white p-3 rounded ring-1 ring-slate-200 overflow-auto max-h-80 font-mono whitespace-pre-wrap" data-testid="vidal-raw-text">
        {(raw || "").slice(0, 20000)}
      </pre>
    </div>
  );
}

function ResultTable({ data, onPick }) {
  // VIDAL responses can be Atom-style. We try to detect entries[] or items[].
  const entries = data?.entries || data?.items || data?.feed?.entries || [];
  if (!Array.isArray(entries) || entries.length === 0) {
    // Iter43-fix24p — Rendu enrichi pour les réponses non structurées
    // (HTML → iframe sandboxée, XML/Atom → table parsée, sinon JSON pretty).
    const raw = typeof data?.raw === "string" ? data.raw : null;
    if (raw) {
      return <RawResponseViewer raw={raw} contentLength={raw.length} />;
    }
    return (
      <div className="text-xs text-slate-500 italic p-3 ring-1 ring-slate-200 rounded bg-slate-50">
        Aucun résultat structuré renvoyé. Réponse JSON :
        <pre className="mt-2 text-[10px] overflow-auto max-h-60 bg-white p-2 rounded ring-1 ring-slate-100">
          {JSON.stringify(data, null, 2).slice(0, 4000)}
        </pre>
      </div>
    );
  }
  return (
    <table className="w-full text-xs ring-1 ring-slate-200 rounded">
      <thead className="bg-slate-50 text-slate-600">
        <tr>
          <th className="text-left px-2 py-1.5">Nom</th>
          <th className="text-left px-2 py-1.5">ID VIDAL</th>
          <th className="text-left px-2 py-1.5">Type</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e, i) => {
          const id = e?.id || e?.vidal_id || e?.product_id || e?.idVidal;
          const title = e?.title || e?.name || e?.label || "(sans nom)";
          const type = e?.type || e?.objectType || "-";
          return (
            <tr key={i} className="border-t border-slate-100 hover:bg-fuchsia-50">
              <td className="px-2 py-1.5 font-semibold">{title}</td>
              <td className="px-2 py-1.5 font-mono text-slate-500">{id || "?"}</td>
              <td className="px-2 py-1.5 text-slate-500">{type}</td>
              <td className="px-2 py-1.5 text-right">
                {id && (
                  <button
                    type="button"
                    onClick={() => onPick(parseInt(id) || id)}
                    className="text-fuchsia-600 hover:text-fuchsia-700 text-[10px] underline"
                    data-testid={`vidal-pick-${i}`}
                  >
                    Voir la fiche →
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ProductDetail({ id, onClose }) {
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null);
  const [rcp, setRcp] = useState(null);
  const [officines, setOfficines] = useState(null);
  const [loadingOff, setLoadingOff] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [a, b] = await Promise.all([
          apiClient.get(`/vidal/product/${id}`),
          apiClient.get(`/vidal/product/${id}/documents?type=RCP`),
        ]);
        if (!cancelled) {
          setDetail(a.data?.data);
          setRcp(b.data?.data);
        }
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Erreur fiche VIDAL");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [id]);

  const loadOfficines = async () => {
    setLoadingOff(true);
    try {
      const name = (detail?.product?.name) || (detail?.name) || `VIDAL ${id}`;
      const r = await apiClient.post("/officines/lookup", { product_name: name, requester_role: "vidal_button" });
      setOfficines(r.data?.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur officines");
    }
    setTimeout(() => setLoadingOff(false), 0);
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" data-testid="vidal-product-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-100 px-4 py-3 flex items-center justify-between">
          <h2 className="font-semibold text-slate-800 inline-flex items-center gap-2">
            <Pill className="h-4 w-4 text-fuchsia-600" />
            Fiche médicament — ID {id}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="vidal-product-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        {loading ? (
          <div className="p-6 text-sm text-slate-500 flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        ) : (
          <div className="p-4 space-y-4">
            <section data-testid="vidal-product-detail">
              <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">Informations produit</h3>
              <pre className="text-[11px] bg-slate-50 ring-1 ring-slate-200 rounded p-3 overflow-auto max-h-72">
                {JSON.stringify(detail, null, 2).slice(0, 6000)}
              </pre>
            </section>
            <section data-testid="vidal-product-rcp">
              <h3 className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                <FileText className="inline h-3 w-3 mr-1" />
                Monographie (RCP)
              </h3>
              <pre className="text-[11px] bg-slate-50 ring-1 ring-slate-200 rounded p-3 overflow-auto max-h-72">
                {JSON.stringify(rcp, null, 2).slice(0, 6000)}
              </pre>
            </section>
            <section data-testid="vidal-product-officines">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs uppercase tracking-wider text-slate-500">
                  🏪 Officines (lookup distribué)
                </h3>
                <button onClick={loadOfficines} disabled={loadingOff}
                        className="text-xs px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white inline-flex items-center gap-1 disabled:opacity-60"
                        data-testid="vidal-load-officines-btn">
                  {loadingOff ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />} Voir les officines
                </button>
              </div>
              {officines ? (
                <pre className="text-[11px] bg-emerald-50 ring-1 ring-emerald-200 rounded p-3 overflow-auto max-h-72">
                  {JSON.stringify(officines, null, 2).slice(0, 6000)}
                </pre>
              ) : (
                <p className="text-[11px] text-slate-400 italic">Cliquez le bouton pour interroger l&apos;API officines configurée.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function SearchTab({ onPick }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("product");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    if (q.length < 2) {
      toast.warning("Saisir au moins 2 caractères");
      return;
    }
    setLoading(true);
    try {
      const r = await apiClient.get(`/vidal/search?q=${encodeURIComponent(q)}&filter=${filter}`);
      setResult(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-slate-600 mb-1">Recherche (nom, DCI, code)</label>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            placeholder="ex: amoxicilline, doliprane, 3400930…"
            className="w-full text-sm px-3 py-2 rounded ring-1 ring-slate-300 focus:ring-fuchsia-500"
            data-testid="vidal-search-input"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-600 mb-1">Filtre</label>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="text-sm px-3 py-2 rounded ring-1 ring-slate-300"
            data-testid="vidal-search-filter"
          >
            {FILTER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="text-sm px-4 py-2 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="vidal-search-submit"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Rechercher
        </button>
      </div>
      {result && (
        <>
          {result.cached && (
            <p className="text-[10px] text-emerald-600">⚡ Réponse depuis le cache</p>
          )}
          <ResultTable data={result.data} onPick={onPick} />
        </>
      )}
    </div>
  );
}

function CatalogTab({ onPick }) {
  const [status, setStatus] = useState("NEW");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get(`/vidal/products/status?status=${status}`);
      setResult(r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-xs text-slate-600 mb-1">Statut réglementaire</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="text-sm px-3 py-2 rounded ring-1 ring-slate-300"
            data-testid="vidal-catalog-status"
          >
            {CATALOG_STATUSES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <button
          onClick={run}
          disabled={loading}
          className="text-sm px-4 py-2 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
          data-testid="vidal-catalog-submit"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ListChecks className="h-4 w-4" />} Lister
        </button>
      </div>
      {result && <ResultTable data={result.data} onPick={onPick} />}
    </div>
  );
}

function AnalyzeTab() {
  const [patient, setPatient] = useState({ birth_date: "", sex: "F", weight_kg: "" });
  const [prescriptions, setPrescriptions] = useState([{ vidal_id: "", dose: "" }]);
  const [allergies, setAllergies] = useState("");
  const [pathologies, setPathologies] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  const addRow = () => setPrescriptions((p) => [...p, { vidal_id: "", dose: "" }]);
  const removeRow = (idx) => setPrescriptions((p) => p.filter((_, i) => i !== idx));
  const updateRow = (idx, k, v) => setPrescriptions((p) =>
    p.map((row, i) => (i === idx ? { ...row, [k]: v } : row))
  );

  const run = async () => {
    if (prescriptions.every((p) => !p.vidal_id)) {
      toast.warning("Saisir au moins un ID VIDAL");
      return;
    }
    setLoading(true);
    try {
      const r = await apiClient.post("/vidal/prescription/analyze", {
        patient: {
          birth_date: patient.birth_date || null,
          sex: patient.sex,
          weight_kg: patient.weight_kg ? parseFloat(patient.weight_kg) : null,
        },
        prescriptions: prescriptions.filter((p) => p.vidal_id),
        allergies: allergies.split(",").map((s) => s.trim()).filter(Boolean),
        pathologies: pathologies.split(",").map((s) => s.trim()).filter(Boolean),
      });
      setResult(r.data?.data || r.data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    }
    setTimeout(() => setLoading(false), 0);
  };

  return (
    <div className="space-y-4">
      {/* Patient */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-3 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Date de naissance</span>
          <input
            type="date"
            value={patient.birth_date}
            onChange={(e) => setPatient({ ...patient, birth_date: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-patient-birth"
          />
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Sexe</span>
          <select
            value={patient.sex}
            onChange={(e) => setPatient({ ...patient, sex: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-patient-sex"
          >
            <option value="F">F</option>
            <option value="M">M</option>
          </select>
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Poids (kg)</span>
          <input
            type="number"
            step="0.1"
            value={patient.weight_kg}
            onChange={(e) => setPatient({ ...patient, weight_kg: e.target.value })}
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-patient-weight"
          />
        </label>
      </div>

      {/* Prescriptions */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white">
        <h4 className="text-xs font-semibold text-slate-700 mb-2">Médicaments prescrits (ID VIDAL + posologie)</h4>
        {prescriptions.map((row, idx) => (
          <div key={idx} className="grid sm:grid-cols-[1fr_2fr_auto] gap-2 mb-2">
            <input
              type="number"
              placeholder="ID VIDAL"
              value={row.vidal_id}
              onChange={(e) => updateRow(idx, "vidal_id", parseInt(e.target.value) || "")}
              className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
              data-testid={`vidal-rx-id-${idx}`}
            />
            <input
              type="text"
              placeholder="Posologie (ex: 500 mg x 3/j pendant 7 jours)"
              value={row.dose}
              onChange={(e) => updateRow(idx, "dose", e.target.value)}
              className="text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
              data-testid={`vidal-rx-dose-${idx}`}
            />
            {prescriptions.length > 1 && (
              <button onClick={() => removeRow(idx)} className="text-rose-500 hover:text-rose-700 px-2" data-testid={`vidal-rx-remove-${idx}`}>
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}
        <button
          onClick={addRow}
          className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50 inline-flex items-center gap-1"
          data-testid="vidal-rx-add"
        >
          <Plus className="h-3 w-3" /> Ajouter un médicament
        </button>
      </div>

      {/* Context */}
      <div className="ring-1 ring-slate-200 rounded-lg p-3 bg-white grid sm:grid-cols-2 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Allergies connues (séparées par virgules)</span>
          <input
            type="text"
            value={allergies}
            onChange={(e) => setAllergies(e.target.value)}
            placeholder="pénicilline, arachide…"
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-allergies"
          />
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Pathologies (séparées par virgules)</span>
          <input
            type="text"
            value={pathologies}
            onChange={(e) => setPathologies(e.target.value)}
            placeholder="diabète, insuffisance rénale…"
            className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300"
            data-testid="vidal-pathologies"
          />
        </label>
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="text-sm px-4 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
        data-testid="vidal-analyze-submit"
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />} Analyser la prescription
      </button>

      {result && (
        <div className="ring-1 ring-rose-200 rounded-lg p-3 bg-rose-50/30" data-testid="vidal-analyze-result">
          <h4 className="text-xs font-semibold text-rose-800 mb-2">Alertes VIDAL</h4>
          <pre className="text-[11px] bg-white ring-1 ring-rose-100 rounded p-3 overflow-auto max-h-96">
            {JSON.stringify(result, null, 2).slice(0, 8000)}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function Vidal() {
  const [tab, setTab] = useState("search");
  const [pickedId, setPickedId] = useState(null);
  const [quota, setQuota] = useState(null);

  useEffect(() => {
    apiClient.get("/vidal/quota/me").then((r) => setQuota(r.data)).catch(() => setQuota(null));
  }, []);

  return (
    <div className="p-4 md:p-6 space-y-4" data-testid="portal-vidal">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-800 inline-flex items-center gap-2">
          <Stethoscope className="h-6 w-6 text-fuchsia-600" />
          VIDAL France
        </h1>
        {quota && (
          <div className="text-xs text-slate-600 ring-1 ring-slate-200 rounded px-3 py-1.5 bg-white" data-testid="vidal-quota-badge">
            Quota : <strong>{quota.used}</strong>
            {quota.limit > 0 ? ` / ${quota.limit}` : " (illimité)"} aujourd&apos;hui
            <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded ${quota.mode === "production" ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>
              {quota.mode === "production" ? "🚀 PROD" : "🧪 TEST"}
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1 ring-1 ring-slate-200 rounded-lg p-1 bg-white w-fit">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`text-xs px-3 py-1.5 rounded inline-flex items-center gap-1 ${tab === t.key ? "bg-fuchsia-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            data-testid={`vidal-tab-${t.key}`}
          >
            <t.icon className="h-3 w-3" /> {t.label}
          </button>
        ))}
      </div>

      <div className="ring-1 ring-slate-200 rounded-lg bg-white p-4">
        {tab === "search" && <SearchTab onPick={setPickedId} />}
        {tab === "catalog" && <CatalogTab onPick={setPickedId} />}
        {tab === "analyze" && <AnalyzeTab />}
      </div>

      {pickedId && <ProductDetail id={pickedId} onClose={() => setPickedId(null)} />}
    </div>
  );
}
