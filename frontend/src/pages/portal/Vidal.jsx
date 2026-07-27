// Iter41 (2026-02) — Portail VIDAL France
// Page unifiée : recherche médicament + fiche médicament + analyse de prescription
// Trois onglets : Recherche, Catalogue, Analyse de prescription.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Stethoscope, Search, Loader2, AlertTriangle, FileText, Pill, ListChecks, Plus, X, Zap, Star, Copy, Trash2
} from "lucide-react";
// Iter43-fix24az-ac (2026-07-22) — Le formulaire d'analyse a été extrait vers
// pages/portal/PrescriptionAnalysis.jsx pour permettre une page dédiée (menu
// sidebar du médecin) tout en le gardant utilisable ici comme onglet.
import { PrescriptionAnalysisForm } from "@/pages/portal/PrescriptionAnalysis";

const TABS = [
  { key: "actions", label: "Actions", icon: Zap },
  { key: "search", label: "Recherche", icon: Search },
  { key: "catalog", label: "Catalogue", icon: ListChecks },
  { key: "favorites", label: "Favoris", icon: Star },
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

// Iter43-fix24at (2026-02-26) — Favoris VIDAL : context partagé entre les
// onglets pour qu'un ajout/retrait depuis la liste de recherche se reflète
// instantanément sur l'onglet Favoris (et inversement).
const FavoritesContext = React.createContext({
  ids: new Set(),
  loading: false,
  add: async () => {},
  remove: async () => {},
  refresh: async () => {},
  isFavorite: () => false,
});

function useFavorites() {
  return React.useContext(FavoritesContext);
}

function FavoritesProvider({ children }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/vidal/favorites");
      setItems(r.data?.items || []);
    } catch (e) {
      // Silent — endpoint may be unreachable briefly during boot
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const ids = React.useMemo(() => new Set(items.map((i) => String(i.vidal_id))), [items]);
  const isFavorite = React.useCallback((vid) => ids.has(String(vid || "")), [ids]);

  const add = React.useCallback(async (favPayload) => {
    if (!favPayload?.vidal_id) {
      toast.warning("Code VIDAL manquant pour ce produit");
      return false;
    }
    try {
      await apiClient.post("/vidal/favorites", favPayload);
      toast.success("⭐ Ajouté aux favoris");
      await refresh();
      return true;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur ajout favori");
      return false;
    }
  }, [refresh]);

  const remove = React.useCallback(async (vid) => {
    if (!vid) return false;
    try {
      await apiClient.delete(`/vidal/favorites/${encodeURIComponent(vid)}`);
      toast.success("Retiré des favoris");
      await refresh();
      return true;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur retrait favori");
      return false;
    }
  }, [refresh]);

  const value = { items, ids, loading, isFavorite, add, remove, refresh };
  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>;
}

// Copy any string to clipboard with a friendly toast.
function _copyCode(code) {
  if (!code) {
    toast.warning("Aucun code à copier");
    return;
  }
  try {
    navigator.clipboard.writeText(String(code));
    toast.success(`📋 Code copié : ${code}`);
  } catch {
    toast.error("Copie impossible");
  }
}

// Small inline button shared by the result tables ("📋 Copier le code").
function CopyCodeButton({ code, testId }) {
  if (!code) return null;
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); _copyCode(code); }}
      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 hover:bg-fuchsia-100 text-slate-600 hover:text-fuchsia-700 ring-1 ring-slate-200 inline-flex items-center gap-1 transition-colors"
      title={`Copier le code VIDAL : ${code}`}
      data-testid={testId}
    >
      <Copy className="h-3 w-3" /> Copier le code
    </button>
  );
}

// Small inline star toggle shared by the result tables.
function FavoriteToggle({ vidalId, title, type, summary, testId }) {
  const { isFavorite, add, remove } = useFavorites();
  if (!vidalId) return null;
  const on = isFavorite(vidalId);
  const onClick = async (e) => {
    e.stopPropagation();
    if (on) await remove(vidalId);
    else await add({ vidal_id: String(vidalId), title: title || "", type: type || "", summary: summary || "" });
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-[10px] px-1.5 py-0.5 rounded ring-1 inline-flex items-center gap-1 transition-colors ${on ? "bg-amber-100 ring-amber-300 text-amber-700 hover:bg-amber-200" : "bg-slate-100 ring-slate-200 text-slate-500 hover:bg-amber-50 hover:text-amber-600"}`}
      title={on ? "Retirer des favoris" : "Ajouter aux favoris"}
      data-testid={testId}
    >
      <Star className={`h-3 w-3 ${on ? "fill-current" : ""}`} />
      {on ? "Favori" : "★ Favori"}
    </button>
  );
}

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
      // Iter43-fix24am+24aq (2026-06-17) — Extract VIDAL product code robustly.
      // Strategy stack (first hit wins) :
      //   1) `<vidal:id>NNNN</vidal:id>` via getElementsByTagName (handles
      //       XML where the prefix is preserved on the qualified name).
      //   2) Any *direct child* whose `localName === "id"` AND content is digits.
      //       Handles both prefixed namespaces and default-namespaced cases.
      //   3) `<id>` URN form `vidal://product/5485` → extract trailing digits.
      //   4) Regex fallback on the raw outerHTML for `<*:id>NNNN</*:id>`
      //       (catches edge cases where the DOM normalization drops prefixes).
      let vidalId = "";
      // 1) Prefixed tagname
      const vidalIdNode = node.getElementsByTagName("vidal:id")[0];
      if (vidalIdNode) {
        const t = (vidalIdNode.textContent || "").trim();
        if (t) vidalId = t;
      }
      // 2) Scan direct children for localName "id" + digit content
      if (!vidalId) {
        for (const child of Array.from(node.children || [])) {
          if ((child.localName || child.nodeName || "").toLowerCase() === "id") {
            const tt = (child.textContent || "").trim();
            if (/^\d+$/.test(tt)) {
              vidalId = tt;
              break;
            }
          }
        }
      }
      // 3) Atom `<id>` URN fallback
      const atomId = get("id");
      if (!vidalId && atomId) {
        const m = atomId.match(/(\d+)\s*$/);
        if (m) vidalId = m[1];
      }
      // 4) Regex on raw outerHTML for `<*:id>NNNN</*:id>` (last resort)
      if (!vidalId) {
        try {
          const html = node.outerHTML || "";
          const m = html.match(/<[a-z][a-z0-9]*:id>\s*(\d+)\s*<\/[a-z][a-z0-9]*:id>/i);
          if (m) vidalId = m[1];
        } catch { /* noop */ }
      }
      // Final fallback: use atomId as-is (last resort, may be a URN string)
      const id = vidalId || atomId;
      return {
        title: get("title") || get("name") || "(sans nom)",
        id,
        vidal_id: vidalId,  // ONLY populated when we found a real numeric code
        type: get("type") || get("objectType") || "-",
        summary: get("summary") || get("description") || "",
        updated: get("updated") || "",
      };
    });
  } catch {
    return null;
  }
}

function _buildCurlCommand(meta) {
  if (!meta) return "";
  const m = String(meta.method || "GET").toUpperCase();
  // Build full URL with query string
  let url = meta.url || "";
  const params = meta.params || {};
  const qs = Object.entries(params)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v ?? ""))}`)
    .join("&");
  if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  // Iter43-fix24z (2026-06-16) — VIDAL répond en XML Atom : on accepte les
  // deux formats pour matcher exactement ce que le backend envoie.
  const accept = "application/atom+xml, application/xml, application/json;q=0.5";
  const lines = [`curl -X ${m} '${url}'`, `  -H 'Accept: ${accept}'`];
  if (m !== "GET" && m !== "HEAD" && meta.body) {
    // POST /alerts/full : body XML + text/xml selon la spec VIDAL
    const bodyIsString = typeof meta.body === "string";
    const ctype = bodyIsString ? "text/xml; charset=utf-8" : "application/json";
    lines.push(`  -H 'Content-Type: ${ctype}'`);
    const payload = bodyIsString ? meta.body : JSON.stringify(meta.body);
    lines.push(`  -d ${JSON.stringify(payload)}`);
  }
  return lines.join(" \\\n");
}

function RequestDebugPanel({ meta }) {
  if (!meta) return null;
  const curl = _buildCurlCommand(meta);
  const fullUrl = (() => {
    let u = meta.url || "";
    const qs = Object.entries(meta.params || {})
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v ?? ""))}`)
      .join("&");
    return u + (qs ? (u.includes("?") ? "&" : "?") + qs : "");
  })();
  const copyText = (text) => {
    try {
      navigator.clipboard.writeText(text || "");
      toast.success("Copié dans le presse-papier");
    } catch {
      toast.error("Copie impossible");
    }
  };
  return (
    <div className="rounded-lg ring-1 ring-blue-200 bg-blue-50 p-3 space-y-2" data-testid="vidal-request-debug">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-blue-900">🔬 Requête envoyée à VIDAL</p>
        <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-bold">
          mode: {meta.mode || "?"}
        </span>
      </div>
      <div className="grid grid-cols-[80px_1fr] gap-x-2 gap-y-1 text-[11px]">
        <span className="text-blue-700 font-semibold">Méthode</span>
        <code className="text-slate-800 break-all">{(meta.method || "GET").toUpperCase()}</code>
        <span className="text-blue-700 font-semibold">URL</span>
        <code className="text-slate-800 break-all bg-white px-1.5 py-0.5 rounded ring-1 ring-blue-100" data-testid="vidal-debug-url">{fullUrl}</code>
        {meta.body && (
          <>
            <span className="text-blue-700 font-semibold">Body</span>
            <pre className="text-[10px] bg-white p-1.5 rounded ring-1 ring-blue-100 overflow-auto max-h-24 font-mono" data-testid="vidal-debug-body">
              {typeof meta.body === "string" ? meta.body : JSON.stringify(meta.body, null, 2)}
            </pre>
          </>
        )}
        <span className="text-blue-700 font-semibold">Timeout</span>
        <span className="text-slate-600">{meta.timeout_seconds || "?"} s</span>
      </div>
      <details className="text-[11px]">
        <summary className="cursor-pointer text-blue-700 hover:text-blue-900 select-none font-semibold">
          ▼ Commande curl reproductible (clé app_key masquée)
        </summary>
        <div className="mt-1.5 space-y-1.5">
          <pre className="text-[10px] bg-slate-900 text-emerald-200 p-2 rounded overflow-auto font-mono" data-testid="vidal-debug-curl">{curl}</pre>
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => copyText(curl)}
              className="text-[10px] px-2 py-1 rounded bg-blue-600 hover:bg-blue-700 text-white"
              data-testid="vidal-debug-copy-curl"
            >
              📋 Copier curl
            </button>
            <button
              type="button"
              onClick={() => copyText(fullUrl)}
              className="text-[10px] px-2 py-1 rounded bg-slate-200 hover:bg-slate-300 text-slate-700"
              data-testid="vidal-debug-copy-url"
            >
              Copier URL seule
            </button>
            {meta.body && (
              <button
                type="button"
                onClick={() => copyText(typeof meta.body === "string" ? meta.body : JSON.stringify(meta.body, null, 2))}
                className="text-[10px] px-2 py-1 rounded bg-slate-200 hover:bg-slate-300 text-slate-700"
                data-testid="vidal-debug-copy-body"
              >
                Copier Body
              </button>
            )}
          </div>
          <p className="text-[10px] text-blue-700 italic">
            ⚠️ Remplacez <code className="bg-blue-100 px-1">app_key=***</code> par votre clé réelle avant exécution dans Postman / curl.
          </p>
        </div>
      </details>
    </div>
  );
}

function RawResponseViewer({ raw, contentLength = 0, requestMeta = null }) {
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
          <div className="space-y-2">
            {requestMeta && <RequestDebugPanel meta={requestMeta} />}
            <div>
              <div className="text-[11px] text-slate-500 mb-1">📄 Source HTML brute reçue de VIDAL :</div>
              <pre className="text-[10px] bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-80 font-mono whitespace-pre-wrap" data-testid="vidal-raw-source">
                {raw.slice(0, 20000)}
                {raw.length > 20000 && "\n\n… (tronqué — utilisez Copier pour récupérer le contenu complet)"}
              </pre>
            </div>
          </div>
        )}
      </div>
    );
  }

  if (kind === "xml" && atomEntries && atomEntries.length > 0) {
    return <AtomFeedViewer entries={atomEntries} raw={raw} requestMeta={requestMeta} />;
  }

  // JSON kind → tree view (collapsible)
  if (kind === "json") {
    let parsed = null;
    try { parsed = JSON.parse(raw); } catch { parsed = null; }
    if (parsed !== null) {
      return <JsonTreeViewer data={parsed} raw={raw} requestMeta={requestMeta} />;
    }
  }

  // Fallback : texte brut / inconnu
  return (
    <div className="space-y-2">
      {requestMeta && <RequestDebugPanel meta={requestMeta} />}
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-slate-500">
          📄 Réponse texte ({Math.round((raw || "").length / 1024)} Ko)
          {kind && <span className="ml-2 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px] uppercase tracking-wider font-mono">format : {kind}</span>}
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

// ---------------------------------------------------------------------------
// Iter43-fix24z (2026-06-16) — Format-specific viewers
// ---------------------------------------------------------------------------

function _entryDisplayInfo(entry) {
  // Pull a friendly subtitle from the Atom entry. VIDAL embeds the resource
  // type in `category[term]` and useful metadata in `content`. We surface
  // the prettiest available.
  const cat = (entry.type || "").split(":").pop();
  const dose = entry.summary || "";
  return { category: cat, summary: dose };
}

function AtomFeedViewer({ entries, raw, requestMeta }) {
  const [view, setView] = React.useState("table"); // table | source
  const [filterTerm, setFilterTerm] = React.useState("");
  const [filterType, setFilterType] = React.useState("__all__");

  const types = React.useMemo(() => {
    const s = new Set();
    entries.forEach((e) => {
      const t = (e.type || "").split(":").pop();
      if (t) s.add(t);
    });
    return ["__all__", ...Array.from(s).sort()];
  }, [entries]);

  const filtered = React.useMemo(() => {
    const q = filterTerm.trim().toLowerCase();
    return entries.filter((e) => {
      const t = (e.type || "").split(":").pop();
      if (filterType !== "__all__" && t !== filterType) return false;
      if (!q) return true;
      return [e.title, e.id, e.summary].some((v) => (v || "").toLowerCase().includes(q));
    });
  }, [entries, filterTerm, filterType]);

  const copyText = (txt) => {
    try { navigator.clipboard.writeText(txt || ""); toast.success("Copié"); }
    catch { toast.error("Copie impossible"); }
  };

  const downloadXml = () => {
    try {
      const blob = new Blob([raw], { type: "application/atom+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "vidal-response.xml";
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch { toast.error("Téléchargement impossible"); }
  };

  return (
    <div className="space-y-2" data-testid="vidal-atom-viewer">
      {requestMeta && <RequestDebugPanel meta={requestMeta} />}
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-2 text-[11px] text-emerald-700">
          <span className="font-semibold">📑 Réponse Atom/XML</span>
          <span className="px-1.5 py-0.5 rounded bg-emerald-50 ring-1 ring-emerald-200 text-emerald-700">
            {filtered.length}/{entries.length} entrée{entries.length > 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setView(view === "table" ? "source" : "table")}
            className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
            data-testid="vidal-atom-toggle-view"
          >
            {view === "table" ? "Voir source XML" : "Voir tableau"}
          </button>
          <button
            type="button"
            onClick={() => copyText(raw)}
            className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
            data-testid="vidal-atom-copy-xml"
          >
            Copier XML
          </button>
          <button
            type="button"
            onClick={downloadXml}
            className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
            data-testid="vidal-atom-download"
          >
            ⬇ Télécharger
          </button>
        </div>
      </div>

      {view === "table" ? (
        <>
          <div className="flex flex-wrap items-center gap-1.5 px-1">
            <input
              type="text"
              placeholder="🔍 Filtrer titre / ID / résumé…"
              value={filterTerm}
              onChange={(e) => setFilterTerm(e.target.value)}
              className="flex-1 min-w-[180px] text-[11px] px-2 py-1 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-emerald-400 outline-none"
              data-testid="vidal-atom-filter-term"
            />
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="text-[11px] px-2 py-1 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-emerald-400 outline-none"
              data-testid="vidal-atom-filter-type"
            >
              {types.map((t) => (
                <option key={t} value={t}>{t === "__all__" ? "Tous types" : t}</option>
              ))}
            </select>
          </div>
          <div className="overflow-x-auto rounded ring-1 ring-slate-200">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-600 sticky top-0">
                <tr>
                  <th className="text-left px-2 py-1.5">Titre</th>
                  <th className="text-left px-2 py-1.5">ID VIDAL</th>
                  <th className="text-left px-2 py-1.5">Type</th>
                  <th className="text-left px-2 py-1.5">Résumé</th>
                  <th className="text-right px-2 py-1.5">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, 200).map((e, i) => {
                  const info = _entryDisplayInfo(e);
                  // Iter43-fix24am+24aq (2026-06-17) — Affiche le code entre
                  // parens UNIQUEMENT s'il s'agit d'un nombre (vrai vidal:id).
                  const rawId = e.vidal_id || e.id || "";
                  const numericId = /^\d+$/.test(String(rawId)) ? rawId : "";
                  return (
                    <tr key={i} className="border-t border-slate-100 hover:bg-emerald-50/40 transition-colors">
                      <td className="px-2 py-1.5 font-semibold" data-testid={`vidal-atom-row-${i}-title`}>
                        {e.title || "—"}
                        {numericId && (
                          <span className="ml-1 font-mono text-slate-500 font-normal" data-testid={`vidal-atom-row-${i}-id-paren`}>
                            ({numericId})
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 font-mono text-[10px] text-slate-500">{numericId || rawId || "?"}</td>
                      <td className="px-2 py-1.5 text-slate-500">
                        <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{info.category || "—"}</span>
                      </td>
                      <td className="px-2 py-1.5 text-slate-600 max-w-[400px] truncate" title={info.summary}>{info.summary || "—"}</td>
                      <td className="px-2 py-1.5 text-right whitespace-nowrap">
                        <div className="inline-flex gap-1 justify-end">
                          <CopyCodeButton code={numericId || rawId} testId={`vidal-atom-copy-${i}`} />
                          <FavoriteToggle
                            vidalId={numericId || rawId}
                            title={e.title || ""}
                            type={info.category || ""}
                            summary={info.summary || ""}
                            testId={`vidal-atom-fav-${i}`}
                          />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {filtered.length > 200 && (
            <p className="text-[10px] text-slate-500 italic px-1">… {filtered.length - 200} entrées non affichées (limite UI 200).</p>
          )}
          {filtered.length === 0 && (
            <p className="text-[11px] text-slate-500 italic px-1 py-3 text-center">Aucune entrée ne correspond aux filtres.</p>
          )}
        </>
      ) : (
        <pre className="text-[10px] bg-slate-900 text-slate-100 p-3 rounded overflow-auto max-h-96 font-mono whitespace-pre-wrap" data-testid="vidal-atom-source">
          {(raw || "").slice(0, 30000)}
          {raw && raw.length > 30000 && "\n\n… (tronqué — utilisez Télécharger pour le contenu complet)"}
        </pre>
      )}
    </div>
  );
}

function JsonTreeViewer({ data, raw, requestMeta }) {
  const [view, setView] = React.useState("tree"); // tree | source
  const pretty = React.useMemo(() => {
    try { return JSON.stringify(data, null, 2); } catch { return String(data); }
  }, [data]);
  const copyText = (txt) => {
    try { navigator.clipboard.writeText(txt); toast.success("Copié"); }
    catch { toast.error("Copie impossible"); }
  };
  return (
    <div className="space-y-2" data-testid="vidal-json-viewer">
      {requestMeta && <RequestDebugPanel meta={requestMeta} />}
      <div className="flex items-center justify-between gap-2 px-1">
        <div className="text-[11px] text-violet-700 font-semibold">
          <span className="font-mono">&#123;&#125;</span> Réponse JSON
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setView(view === "tree" ? "source" : "tree")}
            className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
            data-testid="vidal-json-toggle-view"
          >
            {view === "tree" ? "Voir brut compact" : "Voir formaté"}
          </button>
          <button
            type="button"
            onClick={() => copyText(raw)}
            className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300"
            data-testid="vidal-json-copy"
          >
            Copier
          </button>
        </div>
      </div>
      <pre
        className={
          view === "tree"
            ? "text-[11px] bg-white p-3 rounded ring-1 ring-slate-200 overflow-auto max-h-96 font-mono whitespace-pre"
            : "text-[10px] bg-slate-900 text-emerald-200 p-3 rounded overflow-auto max-h-96 font-mono whitespace-pre-wrap"
        }
        data-testid={view === "tree" ? "vidal-json-tree" : "vidal-json-source"}
      >
        {view === "tree" ? pretty.slice(0, 30000) : (raw || "").slice(0, 30000)}
      </pre>
    </div>
  );
}

function ErrorBanner({ error }) {
  if (!error) return null;
  const status = error.status || 0;
  const isNetwork = status === 0;
  return (
    <div
      className={`rounded-lg p-3 ring-1 ${isNetwork ? "bg-amber-50 ring-amber-300 text-amber-900" : "bg-rose-50 ring-rose-300 text-rose-900"}`}
      data-testid="vidal-error-banner"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="text-base">{isNetwork ? "⚠️" : "🚫"}</span>
        <span className="text-sm font-semibold">
          {isNetwork ? "VIDAL injoignable (erreur réseau)" : `VIDAL a renvoyé HTTP ${status}`}
        </span>
        {!isNetwork && (
          <span className="ml-auto px-2 py-0.5 rounded bg-rose-100 text-rose-700 text-[10px] font-mono uppercase tracking-wider">
            {status >= 500 ? "Serveur VIDAL" : status === 404 ? "Endpoint inconnu" : status === 401 || status === 403 ? "Auth invalide" : "Client"}
          </span>
        )}
      </div>
      <p className="text-xs leading-relaxed">{error.message || "—"}</p>
      {error.url && (
        <p className="text-[10px] mt-1 text-slate-600 break-all">
          <span className="font-semibold">URL appelée :</span> <code>{error.url}</code>
        </p>
      )}
      <p className="text-[11px] mt-1.5 italic">
        ↓ La requête + la réponse complète de VIDAL sont affichées ci-dessous pour diagnostic.
      </p>
    </div>
  );
}

function ResultTable({ data, onPick }) {
  // VIDAL responses can be Atom-style. We try to detect entries[] or items[].
  const entries = data?.entries || data?.items || data?.feed?.entries || [];
  const errorInfo = data?._error || null;
  const hasNoStructuredEntries = !Array.isArray(entries) || entries.length === 0;
  if (hasNoStructuredEntries) {
    // Iter43-fix24p — Rendu enrichi pour les réponses non structurées
    // (HTML → iframe sandboxée, XML/Atom → table parsée, sinon JSON pretty).
    // Iter43-fix24aa (2026-06-16) — Si data._error existe, on affiche une
    // bannière d'erreur au-dessus du viewer mais on rend QUAND MÊME la
    // requête + le body, indispensable pour diagnostiquer.
    const raw = typeof data?.raw === "string" ? data.raw : null;
    if (raw) {
      return (
        <div className="space-y-2">
          {errorInfo && <ErrorBanner error={errorInfo} />}
          <RawResponseViewer raw={raw} contentLength={raw.length} requestMeta={data?._request || null} />
        </div>
      );
    }
    return (
      <div className="space-y-2">
        {errorInfo && <ErrorBanner error={errorInfo} />}
        {data?._request && <RequestDebugPanel meta={data._request} />}
        <div className="text-xs text-slate-500 italic p-3 ring-1 ring-slate-200 rounded bg-slate-50">
          Aucun résultat structuré renvoyé. Réponse JSON :
          <pre className="mt-2 text-[10px] overflow-auto max-h-60 bg-white p-2 rounded ring-1 ring-slate-100">
            {JSON.stringify(data, null, 2).slice(0, 4000)}
          </pre>
        </div>
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
          <th className="text-right px-2 py-1.5">Actions</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e, i) => {
          // Iter43-fix24am+24aq (2026-06-17) — Affiche le code entre parens
          // UNIQUEMENT si `vidal_id` est numérique (vrai code produit).
          // Évite d'afficher des URN longs ou le titre.
          const id = e?.vidal_id || e?.id || e?.product_id || e?.idVidal;
          const numericId = /^\d+$/.test(String(e?.vidal_id || ""))
            ? e.vidal_id
            : (/^\d+$/.test(String(id || "")) ? id : "");
          const title = e?.title || e?.name || e?.label || "(sans nom)";
          const type = e?.type || e?.objectType || "-";
          const codeForCopy = numericId || (id || "");
          return (
            <tr key={i} className="border-t border-slate-100 hover:bg-fuchsia-50">
              <td className="px-2 py-1.5 font-semibold" data-testid={`vidal-row-${i}-name`}>
                {title}
                {numericId && (
                  <span className="ml-1 font-mono text-slate-500 font-normal" data-testid={`vidal-row-${i}-id-paren`}>
                    ({numericId})
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5 font-mono text-slate-500">{numericId || id || "?"}</td>
              <td className="px-2 py-1.5 text-slate-500">{type}</td>
              <td className="px-2 py-1.5 text-right whitespace-nowrap">
                <div className="inline-flex gap-1 justify-end items-center flex-wrap">
                  <CopyCodeButton code={codeForCopy} testId={`vidal-row-copy-${i}`} />
                  <FavoriteToggle
                    vidalId={codeForCopy}
                    title={title}
                    type={type}
                    summary={e?.summary || e?.description || ""}
                    testId={`vidal-row-fav-${i}`}
                  />
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
                </div>
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

// ---------------------------------------------------------------------------
// Iter43-fix24ac (2026-06-16) — Tab "Actions" : boutons dynamiques générés
// depuis la configuration admin (Admin → Settings → S058b VIDAL Actions).
// Chaque action visible (`portal_button_visible=true`) devient une carte
// avec : champ de saisie + bouton "Exécuter" + viewer adapté.
// ---------------------------------------------------------------------------
function ActionsTab() {
  const [actions, setActions] = useState([]);
  const [loading, setLoading] = useState(true);
  // Map { [action_id]: { input, running, result } }
  const [state, setState] = useState({});

  useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get("/vidal/actions/portal");
        setActions(r.data?.actions || []);
      } catch (e) {
        toast.error(e?.response?.data?.detail || "Chargement actions VIDAL impossible");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const setInput = (id, val) => setState((s) => ({ ...s, [id]: { ...(s[id] || {}), input: val } }));

  const run = async (action) => {
    const id = action.id;
    const userInput = (state[id]?.input || "").trim();
    if (!userInput) {
      toast.warning("Saisir une valeur d'abord");
      return;
    }
    setState((s) => ({ ...s, [id]: { ...(s[id] || {}), running: true } }));
    try {
      // Special case 'interactions' splits into id1/id2
      let payload;
      if (action.id === "interactions") {
        const parts = userInput.split(/\s+/);
        payload = { id1: parts[0] || "", id2: parts[1] || "" };
      } else {
        const key = action.input_param || "q";
        payload = { [key]: userInput };
      }
      const r = await apiClient.post(`/vidal/execute/${encodeURIComponent(action.id)}`, payload);
      setState((s) => ({ ...s, [id]: { ...(s[id] || {}), result: r.data, running: false } }));
    } catch (e) {
      setState((s) => ({ ...s, [id]: { ...(s[id] || {}), result: { data: { _error: { status: e?.response?.status || 0, message: e?.response?.data?.detail || String(e) } } }, running: false } }));
    }
  };

  if (loading) return <p className="text-sm text-slate-500 italic">Chargement des actions…</p>;

  if (actions.length === 0) {
    return (
      <div className="text-sm text-slate-600 italic p-4 bg-slate-50 rounded ring-1 ring-slate-200">
        Aucune action VIDAL visible.{" "}
        <a href="/admin/settings#s-s058b-vidal-actions" className="text-fuchsia-600 hover:underline">
          Configurer dans Admin → Settings → VIDAL Actions →
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="vidal-actions-tab">
      <p className="text-[11px] text-slate-500">
        Boutons configurés via <strong>Admin → Settings → S058b VIDAL Actions</strong>. {actions.length} action{actions.length > 1 ? "s" : ""} disponible{actions.length > 1 ? "s" : ""}.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {actions.map((a) => {
          const st = state[a.id] || {};
          return (
            <div key={a.id} className="ring-1 ring-slate-200 rounded-lg bg-white p-3 space-y-2" data-testid={`vidal-action-card-${a.id}`}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold flex-1">{a.portal_button_label || a.label}</span>
                <span className="font-mono text-[9px] uppercase px-1 py-0.5 rounded bg-slate-100 text-slate-500">{a.method}</span>
                {!a.is_public && <span className="text-[9px] px-1 py-0.5 rounded bg-amber-100 text-amber-700">🔒</span>}
              </div>
              <p className="text-[10px] text-slate-500 font-mono break-all">{a.path}</p>
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={st.input || ""}
                  onChange={(e) => setInput(a.id, e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && run(a)}
                  placeholder={a.input_label || "Saisir une valeur…"}
                  className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 focus:ring-2 focus:ring-fuchsia-400 outline-none"
                  data-testid={`vidal-action-input-${a.id}`}
                />
                <button
                  type="button"
                  onClick={() => run(a)}
                  disabled={!!st.running}
                  className="text-xs px-3 py-1.5 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white disabled:opacity-50 inline-flex items-center gap-1"
                  data-testid={`vidal-action-run-${a.id}`}
                >
                  {st.running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Zap className="h-3 w-3" />}
                  Exécuter
                </button>
              </div>
              {st.result && (
                <div className="pt-2 border-t border-slate-100">
                  <ResultTable data={st.result.data} onPick={() => {}} />
                </div>
              )}
            </div>
          );
        })}
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

function AnalyzeTab_DEPRECATED_UNUSED() {
  // Iter43-fix24az-ac — Real implementation lives in `PrescriptionAnalysis.jsx`.
  // This shim is safe to remove after one release cycle.
  return null;
}

export default function Vidal() {
  return (
    <FavoritesProvider>
      <VidalInner />
    </FavoritesProvider>
  );
}

function FavoritesTab({ onPick }) {
  const { items, loading, remove, refresh } = useFavorites();

  if (loading) {
    return (
      <p className="text-sm text-slate-500 italic inline-flex items-center gap-2" data-testid="vidal-favorites-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> Chargement des favoris…
      </p>
    );
  }

  if (!items.length) {
    return (
      <div className="text-sm text-slate-600 italic p-4 bg-amber-50 rounded ring-1 ring-amber-200" data-testid="vidal-favorites-empty">
        <p className="font-semibold text-amber-800 mb-1">⭐ Aucun favori pour l&apos;instant</p>
        <p className="text-xs text-amber-700">
          Cliquez sur l&apos;étoile <Star className="inline h-3 w-3 mb-0.5" /> à côté d&apos;un produit dans <strong>Recherche</strong>, <strong>Catalogue</strong> ou <strong>Actions</strong> pour le retrouver ici.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="vidal-favorites-tab">
      <div className="flex items-center justify-between gap-2 px-1">
        <p className="text-[11px] text-slate-500">
          {items.length} produit{items.length > 1 ? "s" : ""} VIDAL favori{items.length > 1 ? "s" : ""}
        </p>
        <button
          type="button"
          onClick={refresh}
          className="text-[11px] px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-300 inline-flex items-center gap-1"
          data-testid="vidal-favorites-refresh"
        >
          <Loader2 className="h-3 w-3" /> Rafraîchir
        </button>
      </div>
      <div className="overflow-x-auto rounded ring-1 ring-slate-200">
        <table className="w-full text-xs">
          <thead className="bg-amber-50/60 text-slate-600">
            <tr>
              <th className="text-left px-2 py-1.5">Titre</th>
              <th className="text-left px-2 py-1.5">ID VIDAL</th>
              <th className="text-left px-2 py-1.5">Type</th>
              <th className="text-left px-2 py-1.5">Ajouté le</th>
              <th className="text-right px-2 py-1.5">Actions</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f, i) => {
              const numericId = /^\d+$/.test(String(f.vidal_id || "")) ? f.vidal_id : "";
              return (
                <tr key={f.vidal_id || i} className="border-t border-slate-100 hover:bg-amber-50/40">
                  <td className="px-2 py-1.5 font-semibold" data-testid={`vidal-fav-row-${i}-title`}>
                    {f.title || "(sans nom)"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[10px] text-slate-500" data-testid={`vidal-fav-row-${i}-id`}>
                    {f.vidal_id || "?"}
                  </td>
                  <td className="px-2 py-1.5 text-slate-500">
                    <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px]">{f.type || "—"}</span>
                  </td>
                  <td className="px-2 py-1.5 text-[10px] text-slate-400" title={f.created_at}>
                    {f.created_at ? new Date(f.created_at).toLocaleDateString("fr-FR") : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right whitespace-nowrap">
                    <div className="inline-flex gap-1 justify-end items-center">
                      <CopyCodeButton code={f.vidal_id} testId={`vidal-fav-copy-${i}`} />
                      {numericId && (
                        <button
                          type="button"
                          onClick={() => onPick(parseInt(numericId))}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-fuchsia-100 hover:bg-fuchsia-200 text-fuchsia-700 ring-1 ring-fuchsia-200 inline-flex items-center gap-1"
                          data-testid={`vidal-fav-open-${i}`}
                        >
                          📄 Fiche
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => remove(f.vidal_id)}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-rose-100 hover:bg-rose-200 text-rose-700 ring-1 ring-rose-200 inline-flex items-center gap-1"
                        title="Retirer des favoris"
                        data-testid={`vidal-fav-remove-${i}`}
                      >
                        <Trash2 className="h-3 w-3" /> Retirer
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function VidalInner() {
  const [tab, setTab] = useState("actions");
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
        {tab === "actions" && <ActionsTab />}
        {tab === "search" && <SearchTab onPick={setPickedId} />}
        {tab === "catalog" && <CatalogTab onPick={setPickedId} />}
        {tab === "favorites" && <FavoritesTab onPick={setPickedId} />}
        {tab === "analyze" && <PrescriptionAnalysisForm />}
      </div>

      {pickedId && <ProductDetail id={pickedId} onClose={() => setPickedId(null)} />}
    </div>
  );
}
