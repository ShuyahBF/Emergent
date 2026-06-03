/*
 * #1 (2026-02 — suite S044) — Liluvine PRO Screenshots Insights
 *
 *  Two views in one component:
 *   • « Historique » : Liste des captures envoyées par les clients à
 *     Liluvine PRO (date, sender, image cliente, analyse Vision, matches
 *     Qdrant SAWALI).
 *   • « Top écrans » : Aggregate des écrans SAWALI les plus matchés par
 *     les captures clients (signal fort : si un écran apparaît souvent,
 *     c'est qu'il génère beaucoup de questions support → cible idéale
 *     pour de l'onboarding / documentation).
 */
import React, { useCallback, useEffect, useState } from "react";
import { Camera, BarChart3, RefreshCw, ExternalLink, FileText, Loader2, Sparkles, Copy as CopyIcon, X, AlertTriangle } from "lucide-react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";

const fmtAge = (iso) => {
  if (!iso) return "—";
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60_000);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} h`;
    const d = Math.floor(h / 24);
    return `${d} j`;
  } catch { return "—"; }
};

// =====================================================================
// #2 (2026-02) — Doc draft generator modal
// =====================================================================
function DocDraftModal({ screen, days, onClose }) {
  const [markdown, setMarkdown] = useState("");
  const [info, setInfo] = useState(null);  // { questions_used, model, tokens }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await apiClient.post("/admin/liluvine-pro/generate-doc-draft", {
          image_url: screen.image_url,
          title: screen.title,
          days,
        });
        if (cancelled) return;
        setMarkdown(r.data?.markdown || "");
        setInfo({
          questions_used: r.data?.questions_used,
          model: r.data?.model,
          tokens: r.data?.tokens,
          warn: r.data?.warn,
        });
        setLoading(false);
        if (r.data?.warn) toast.warning("⚠️ Vous approchez de votre quota IA mensuel (80%).");
      } catch (err) {
        if (cancelled) return;
        setError(err?.response?.data?.detail || "Erreur");
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [screen.image_url, screen.title, days]);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(markdown);
      toast.success("Markdown copié dans le presse-papier !");
    } catch {
      toast.error("Impossible de copier — sélectionnez le texte manuellement");
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" data-testid="doc-draft-modal">
      <div className="bg-white rounded-xl shadow-2xl max-w-3xl w-full max-h-[90vh] flex flex-col">
        <header className="flex items-center justify-between gap-3 p-4 border-b border-slate-200">
          <div className="flex items-center gap-2 min-w-0">
            <Sparkles size={18} className="text-fuchsia-600 shrink-0" />
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-slate-800 truncate">
                Brouillon de doc : {screen.title || "Écran"}
              </h3>
              <p className="text-[10px] text-slate-500">
                Généré par Claude à partir des vraies questions clients reçues ces {days} derniers jours.
              </p>
            </div>
          </div>
          <button onClick={onClose} data-testid="doc-draft-close" className="p-1 text-slate-400 hover:text-slate-700">
            <X size={18} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="text-center py-12 text-slate-500 text-sm">
              <Loader2 className="h-6 w-6 animate-spin mx-auto mb-2 text-fuchsia-600" />
              Claude rédige le brouillon… (analyse des questions clients + structuration)
            </div>
          )}
          {error && (
            <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50 text-rose-800 p-3 text-sm" data-testid="doc-draft-error">
              {error}
            </div>
          )}
          {!loading && !error && (
            <>
              <div className="mb-3 rounded-lg ring-1 ring-emerald-200 bg-emerald-50 text-emerald-800 p-2.5 text-[11px] flex items-center justify-between gap-2">
                <span>
                  ✓ Synthèse de <strong>{info?.questions_used}</strong> question(s) client(s) ·
                  Modèle : <code className="text-[10px]">{info?.model}</code> ·
                  ~{info?.tokens} tokens
                </span>
                <button
                  onClick={copyToClipboard}
                  data-testid="doc-draft-copy"
                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-[10px]"
                >
                  <CopyIcon size={12} /> Copier le Markdown
                </button>
              </div>
              <textarea
                value={markdown}
                onChange={(e) => setMarkdown(e.target.value)}
                data-testid="doc-draft-content"
                className="w-full h-[60vh] p-3 rounded-lg ring-1 ring-slate-300 font-mono text-xs leading-relaxed resize-none focus:ring-fuchsia-400 outline-none"
                spellCheck={false}
              />
            </>
          )}
        </div>
        <footer className="p-4 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded ring-1 ring-slate-300 text-slate-600 hover:bg-slate-50">
            Fermer
          </button>
          {!loading && !error && (
            <button onClick={copyToClipboard} className="px-3 py-1.5 text-sm rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white inline-flex items-center gap-1">
              <CopyIcon size={14} /> Copier
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

function HistoryTable({ items, loading }) {
  if (loading) return <p className="py-8 text-center text-slate-400 text-xs"><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Chargement…</p>;
  if (items.length === 0) return <p className="py-8 text-center text-slate-400 text-xs italic">Aucune capture envoyée — vos clients n'ont pas encore utilisé cette fonctionnalité.</p>;
  return (
    <div className="space-y-2">
      {items.map((m) => (
        <div key={m.id} className="bg-white ring-1 ring-slate-200 rounded-lg p-3 flex gap-3 items-start" data-testid={`liluvine-screenshot-${m.id}`}>
          <a href={m.user_image_url} target="_blank" rel="noopener noreferrer" className="shrink-0">
            <img src={m.user_image_url} alt="Capture client" className="h-16 w-16 object-cover rounded ring-1 ring-slate-300 hover:ring-fuchsia-400 transition" />
          </a>
          <div className="flex-1 min-w-0 space-y-1">
            <div className="flex items-center gap-2 flex-wrap text-[11px]">
              <span className="font-semibold text-slate-700">{m.sender_label}</span>
              <span className="text-slate-400">·</span>
              <span className="text-slate-500">{fmtAge(m.created_at)}</span>
              {m.session_channel && m.session_channel !== "web" && (
                <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 text-[9px] uppercase">
                  {m.session_channel}
                </span>
              )}
            </div>
            {m.content && m.content !== "📸 Capture d'écran envoyée" && (
              <p className="text-xs text-slate-700 italic">« {m.content.slice(0, 220)}{m.content.length > 220 ? "…" : ""} »</p>
            )}
            {m.image_analysis?.visual_summary && (
              <p className="text-[11px] text-violet-700 bg-violet-50 rounded px-2 py-1">
                <strong>Vision :</strong> {m.image_analysis.visual_summary.slice(0, 200)}{m.image_analysis.visual_summary.length > 200 ? "…" : ""}
              </p>
            )}
            {(m.matched_images || []).length > 0 && (
              <div className="flex gap-1.5 flex-wrap mt-1.5">
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold self-center">Matches :</span>
                {m.matched_images.slice(0, 3).map((mi, idx) => (
                  <a
                    key={mi.image_url + idx}
                    href={mi.image_url} target="_blank" rel="noopener noreferrer"
                    className="relative h-12 w-12 rounded overflow-hidden ring-1 ring-emerald-300 hover:ring-emerald-500"
                    title={`${mi.title || `Match ${idx + 1}`} (${Math.round((mi.score || 0) * 100)}%)`}
                  >
                    <img src={mi.image_url} alt="" className="h-full w-full object-cover" />
                    <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[8px] px-0.5 text-center">{Math.round((mi.score || 0) * 100)}%</span>
                  </a>
                ))}
              </div>
            )}
            {(m.matched_images || []).length === 0 && (
              <p className="text-[10px] text-amber-700 italic">Aucun match SAWALI trouvé pour cette capture</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TopScreensTable({ data, loading, onGenerateDoc }) {
  if (loading) return <p className="py-8 text-center text-slate-400 text-xs"><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Chargement…</p>;
  if (!data || data.items.length === 0) {
    return (
      <p className="py-8 text-center text-slate-400 text-xs italic">
        Aucun écran matché — vos clients n'ont pas encore envoyé de captures avec des correspondances dans Qdrant.
      </p>
    );
  }
  const max = Math.max(...data.items.map((it) => it.count), 1);
  return (
    <>
      <p className="text-xs text-slate-600 mb-3 bg-slate-50 rounded p-2">
        💡 Sur les <strong>{data.total_screenshots}</strong> captures reçues ces <strong>{data.days}</strong> derniers jours,
        voici les écrans SAWALI que Liluvine a le plus souvent reconnus. Un écran à fort trafic ici = candidat idéal pour
        améliorer l'onboarding ou enrichir la documentation. Cliquez sur <strong>✨ Générer doc</strong> pour qu'IA rédige
        un brouillon d'article à partir des vraies questions clients.
      </p>
      <div className="space-y-2">
        {data.items.map((it, idx) => (
          <div key={it.image_url + idx} className="bg-white ring-1 ring-slate-200 rounded-lg p-2.5 flex items-center gap-3" data-testid={`top-screen-${idx}`}>
            <a href={it.image_url} target="_blank" rel="noopener noreferrer" className="shrink-0">
              <img src={it.image_url} alt={it.title || "Écran"} className="h-12 w-12 object-cover rounded ring-1 ring-slate-300" />
            </a>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-800 truncate">{it.title || "(sans titre)"}</p>
              <p className="text-[10px] text-slate-500">
                Collection: <span className="font-mono">{it.collection}</span> · Score moyen: {(it.avg_score * 100).toFixed(0)}%
              </p>
              <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden mt-1">
                <div
                  className="h-full bg-gradient-to-r from-fuchsia-500 to-violet-600"
                  style={{ width: `${(it.count / max) * 100}%` }}
                />
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-lg font-display font-bold text-fuchsia-600 tabular-nums">{it.count}</div>
              <div className="text-[9px] text-slate-500">consultations</div>
            </div>
            <button
              onClick={() => onGenerateDoc(it)}
              data-testid={`top-screen-${idx}-gen-doc`}
              title="Générer un brouillon de documentation à partir des vraies questions clients sur cet écran"
              className="shrink-0 px-2.5 py-1.5 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white text-[10px] inline-flex items-center gap-1"
            >
              <Sparkles size={12} /> Générer doc
            </button>
          </div>
        ))}
      </div>
    </>
  );
}

// =====================================================================
// #2bis (2026-02) — Coverage gaps (questions sans match Qdrant)
// =====================================================================
function GapsTable({ data, loading }) {
  if (loading) return <p className="py-8 text-center text-slate-400 text-xs"><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Chargement…</p>;
  if (!data || data.items.length === 0) {
    return (
      <p className="py-8 text-center text-emerald-600 text-xs italic">
        🎉 Aucun trou dans la base de connaissances ! Toutes les questions clients ont trouvé un écran SAWALI correspondant.
      </p>
    );
  }
  const rate = Math.round((data.blindspot_rate || 0) * 100);
  return (
    <>
      <div className="rounded-lg ring-1 ring-amber-200 bg-amber-50 text-amber-900 p-3 text-xs mb-3">
        ⚠️ <strong>{data.gaps_count}</strong> question(s) client sur <strong>{data.total_screenshots}</strong> captures
        ({rate}% de blind-spot) ne trouvent pas d'écran SAWALI correspondant.
        Ces sujets <strong>manquent dans votre base Qdrant</strong> — les ajouter améliorera directement les réponses de Liluvine.
      </div>
      <div className="space-y-2">
        {data.items.map((g) => (
          <div key={g.id} className="bg-white ring-1 ring-amber-200 rounded-lg p-3 flex gap-3 items-start" data-testid={`gap-item-${g.id}`}>
            <a href={g.user_image_url} target="_blank" rel="noopener noreferrer" className="shrink-0">
              <img src={g.user_image_url} alt="Capture client" className="h-14 w-14 object-cover rounded ring-1 ring-amber-300" />
            </a>
            <div className="flex-1 min-w-0 space-y-1">
              <div className="flex items-center gap-2 flex-wrap text-[11px]">
                <span className={`px-1.5 py-0.5 rounded text-[9px] uppercase font-bold ${
                  g.gap_reason === "no_match" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-800"
                }`}>
                  {g.gap_reason === "no_match" ? "❌ Aucun match" : `⚠ Score ${Math.round((g.top_score || 0) * 100)}%`}
                </span>
                <span className="text-slate-500">{fmtAge(g.created_at)}</span>
              </div>
              {g.content && g.content !== "📸 Capture d'écran envoyée" && (
                <p className="text-xs text-slate-700 italic">« {g.content.slice(0, 220)}{g.content.length > 220 ? "…" : ""} »</p>
              )}
              {g.image_analysis?.visual_summary && (
                <p className="text-[11px] text-violet-700 bg-violet-50 rounded px-2 py-1">
                  <strong>Vision :</strong> {g.image_analysis.visual_summary.slice(0, 200)}
                </p>
              )}
              <p className="text-[10px] text-slate-500 mt-1">
                💡 Pour combler ce gap : copiez le contexte ci-dessus, allez sur <strong>Admin → Réglages → Qdrant RAG</strong>,
                cliquez sur « Image » et ajoutez la bonne capture SAWALI avec ce contexte en description.
              </p>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}


export default function LiluvineScreenshotsInsights() {
  const [tab, setTab] = useState("history");  // history | top | gaps
  const [days, setDays] = useState(30);
  const [history, setHistory] = useState({ items: [], loading: false });
  const [topScreens, setTopScreens] = useState({ data: null, loading: false });
  const [gaps, setGaps] = useState({ data: null, loading: false });
  // #2 — Doc draft generator
  const [docModalScreen, setDocModalScreen] = useState(null);

  const loadHistory = useCallback(async () => {
    setHistory((h) => ({ ...h, loading: true }));
    try {
      const r = await apiClient.get(`/admin/liluvine-pro/screenshots-history?days=${days}&limit=100`);
      setHistory({ items: r.data?.items || [], loading: false });
    } catch (err) {
      setHistory({ items: [], loading: false });
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  }, [days]);

  const loadTop = useCallback(async () => {
    setTopScreens((t) => ({ ...t, loading: true }));
    try {
      const r = await apiClient.get(`/admin/liluvine-pro/top-screens?days=${days}&limit=20`);
      setTopScreens({ data: r.data, loading: false });
    } catch (err) {
      setTopScreens({ data: null, loading: false });
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  }, [days]);

  const loadGaps = useCallback(async () => {
    setGaps((g) => ({ ...g, loading: true }));
    try {
      const r = await apiClient.get(`/admin/liluvine-pro/coverage-gaps?days=${days}&min_score=0.5&limit=50`);
      setGaps({ data: r.data, loading: false });
    } catch (err) {
      setGaps({ data: null, loading: false });
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  }, [days]);

  useEffect(() => {
    if (tab === "history") loadHistory();
    else if (tab === "top") loadTop();
    else if (tab === "gaps") loadGaps();
  }, [tab, loadHistory, loadTop, loadGaps]);

  return (
    <div className="space-y-4" data-testid="liluvine-screenshots-insights">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="inline-flex gap-1 rounded-lg ring-1 ring-slate-200 bg-white p-1">
          <button
            onClick={() => setTab("history")}
            data-testid="screenshots-tab-history"
            className={`px-3 py-1.5 text-xs rounded-md inline-flex items-center gap-1.5 ${tab === "history" ? "bg-fuchsia-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
          >
            <Camera size={14} /> Historique
          </button>
          <button
            onClick={() => setTab("top")}
            data-testid="screenshots-tab-top"
            className={`px-3 py-1.5 text-xs rounded-md inline-flex items-center gap-1.5 ${tab === "top" ? "bg-fuchsia-600 text-white" : "text-slate-600 hover:bg-slate-50"}`}
          >
            <BarChart3 size={14} /> Top écrans consultés
          </button>
          <button
            onClick={() => setTab("gaps")}
            data-testid="screenshots-tab-gaps"
            className={`px-3 py-1.5 text-xs rounded-md inline-flex items-center gap-1.5 ${tab === "gaps" ? "bg-amber-500 text-white" : "text-slate-600 hover:bg-slate-50"}`}
          >
            <AlertTriangle size={14} /> Sujets non couverts
          </button>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            data-testid="screenshots-days"
            className="text-xs rounded ring-1 ring-slate-200 px-2 py-1.5 bg-white"
          >
            <option value={7}>7 derniers jours</option>
            <option value={30}>30 derniers jours</option>
            <option value={90}>90 derniers jours</option>
            <option value={365}>1 an</option>
          </select>
          <button
            onClick={() => tab === "history" ? loadHistory() : tab === "top" ? loadTop() : loadGaps()}
            className="text-xs inline-flex items-center gap-1 rounded ring-1 ring-slate-300 px-2.5 py-1.5 hover:bg-slate-50"
            data-testid="screenshots-refresh"
          >
            <RefreshCw size={12} /> Actualiser
          </button>
        </div>
      </div>
      {tab === "history" ? (
        <HistoryTable items={history.items} loading={history.loading} />
      ) : tab === "top" ? (
        <TopScreensTable
          data={topScreens.data}
          loading={topScreens.loading}
          onGenerateDoc={(screen) => setDocModalScreen(screen)}
        />
      ) : (
        <GapsTable data={gaps.data} loading={gaps.loading} />
      )}
      {docModalScreen && (
        <DocDraftModal
          screen={docModalScreen}
          days={days}
          onClose={() => setDocModalScreen(null)}
        />
      )}
    </div>
  );
}
