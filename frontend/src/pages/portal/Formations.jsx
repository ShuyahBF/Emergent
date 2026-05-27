import React, { useEffect, useRef, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { GraduationCap, Coins, Users, Layers, ArrowLeft, ChevronRight, Send, Loader2, Star, Lock } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

const STATE_BADGES = {
  inscription: "bg-slate-100 text-slate-700",
  commencée: "bg-blue-100 text-blue-700",
  en_cours: "bg-amber-100 text-amber-700",
  suspendue: "bg-orange-100 text-orange-700",
  annulée: "bg-rose-100 text-rose-700",
  terminée: "bg-emerald-100 text-emerald-700",
};
const stateLabel = (s) => (s || "—").replace("_", " ");

// =====================================================================
// LIST PAGE
// =====================================================================
export function FormationsList() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(null);
  const isTracked = !!user?.tracked_user_id || !!user?.tracked_role;

  const load = () => apiClient.get("/me/formations").then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);

  const enroll = async (fid) => {
    setBusy(fid);
    try { await apiClient.post(`/me/formations/${fid}/enroll`); toast.success("Inscription enregistrée"); await load(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
    finally { setBusy(null); }
  };

  // Iter38o — Stripe Checkout for paid formations
  const startCheckout = async (fid) => {
    setBusy(fid);
    try {
      const r = await apiClient.post(`/me/formations/${fid}/stripe/checkout`, {
        origin_url: window.location.origin,
      });
      if (r.data?.url) {
        window.location.href = r.data.url;  // Redirect to Stripe Checkout
      } else {
        toast.error("Lien de paiement non disponible");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur Stripe");
    } finally { setBusy(null); }
  };

  return (
    <div className="space-y-6" data-testid="formations-list-page">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2"><GraduationCap className="h-6 w-6 text-sawali-blue" /> Formations Spécialisées</h1>
        <p className="text-sm text-slate-500">Catalogue des formations disponibles pour votre profil. Cliquez sur une formation pour la commencer.</p>
      </div>

      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-slate-500">Aucune formation disponible pour le moment.</div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((f) => {
            const enr = f.enrollment;
            return (
              <article key={f.id} className="rounded-xl border border-slate-200 bg-white overflow-hidden flex flex-col hover:border-sawali-blue/40 transition" data-testid={`formation-card-${f.id}`}>
                {f.cover_image_url ? <img src={f.cover_image_url} alt="" className="h-32 w-full object-cover" /> : <div className="h-2 bg-gradient-to-r from-sawali-blue to-emerald-400" />}
                <div className="p-5 flex flex-col gap-2 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="font-display font-semibold flex-1">{f.name}</h3>
                    {!f.available && <span className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-rose-100 text-rose-700">indispo</span>}
                  </div>
                  {f.description && <p className="text-xs text-slate-600 line-clamp-2">{f.description}</p>}
                  <div className="flex items-center gap-3 flex-wrap text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1"><Layers className="h-3 w-3" /> {f.modules_total} modules</span>
                    <span className={`inline-flex items-center gap-1 ${f.access === "paid" ? "text-amber-600" : "text-emerald-600"}`}><Coins className="h-3 w-3" /> {f.access === "paid" ? `${f.price || 0} XOF` : "libre"}</span>
                  </div>
                  {enr && (
                    <div className="flex items-center justify-between flex-wrap gap-2 mt-1">
                      <span className={`text-[11px] px-2 py-0.5 rounded ${STATE_BADGES[enr.state] || "bg-slate-100"}`} data-testid={`state-${f.id}`}>{stateLabel(enr.state)}</span>
                      <span className="text-[11px] text-slate-500 tabular-nums">{enr.modules_seen_count}/{enr.modules_total} modules · {enr.credits_available || 0}/{enr.credits_purchased || 0} crédits</span>
                    </div>
                  )}
                  <div className="mt-auto pt-2">
                    {enr ? (
                      <Link to={`/portal/formations/${f.id}`} className="block w-full text-center rounded-lg bg-sawali-blue text-white px-3 py-2 text-sm hover:bg-sawali-blue-light" data-testid={`open-formation-${f.id}`}>Continuer</Link>
                    ) : isTracked ? (
                      f.access === "paid" && f.price > 0 ? (
                        // Iter38o — Paid formation: Stripe Checkout
                        <button
                          disabled={busy === f.id}
                          onClick={() => startCheckout(f.id)}
                          data-testid={`buy-formation-${f.id}`}
                          className="w-full rounded-lg bg-gradient-to-r from-amber-500 to-orange-600 text-white px-3 py-2 text-sm hover:opacity-90 disabled:opacity-50 inline-flex items-center justify-center gap-2"
                        >
                          {busy === f.id ? "..." : <><Coins className="h-3.5 w-3.5" /> Acheter ({Math.round(f.price)} XOF)</>}
                        </button>
                      ) : (
                        <button disabled={busy === f.id} onClick={() => enroll(f.id)} className="w-full rounded-lg border border-sawali-blue text-sawali-blue px-3 py-2 text-sm hover:bg-sawali-blue/10 disabled:opacity-50" data-testid={`enroll-${f.id}`}>
                          {busy === f.id ? "..." : "M'inscrire"}
                        </button>
                      )
                    ) : (
                      <span className="block text-xs text-slate-400 italic">Inscription réservée aux utilisateurs suivis</span>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

// =====================================================================
// DETAIL PAGE
// =====================================================================
export function FormationDetail() {
  const { fid } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [activeMid, setActiveMid] = useState(null);
  // Iter38o — Handle Stripe return (session_id in URL)
  const [paymentMsg, setPaymentMsg] = useState(null);

  const load = () => apiClient.get(`/me/formations/${fid}`).then((r) => {
    setData(r.data);
    if (!activeMid && r.data.modules?.length) setActiveMid(r.data.modules[0].id);
  });
  useEffect(() => { load().catch(() => navigate("/portal/formations")); /* eslint-disable-next-line */ }, [fid]);

  // Iter38o — Poll the Stripe payment status if we returned with session_id
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id");
    const canceled = params.get("canceled");
    if (canceled) {
      setPaymentMsg({ kind: "warn", text: "Paiement annulé. Vous pouvez réessayer quand vous voulez." });
      return;
    }
    if (!sessionId) return;
    setPaymentMsg({ kind: "info", text: "Vérification du paiement…" });
    let attempts = 0;
    const poll = async () => {
      attempts += 1;
      if (attempts > 6) {
        setPaymentMsg({ kind: "warn", text: "Délai dépassé. Si le paiement aboutit, l'inscription apparaîtra automatiquement." });
        return;
      }
      try {
        const r = await apiClient.get(`/payments/stripe/status/${sessionId}`);
        if (r.data?.payment_status === "paid") {
          setPaymentMsg({ kind: "success", text: "✓ Paiement confirmé — inscription activée." });
          await load();
          return;
        }
        if (r.data?.status === "expired") {
          setPaymentMsg({ kind: "warn", text: "Session expirée. Veuillez réessayer." });
          return;
        }
        setTimeout(poll, 2000);
      } catch { setTimeout(poll, 2000); }
    };
    poll();
  // eslint-disable-next-line
  }, [fid]);

  if (!data) return <div className="text-slate-500">Chargement…</div>;
  const { formation, modules, enrollment } = data;
  const activeModule = modules.find((m) => m.id === activeMid);
  const seen = new Set(enrollment?.modules_seen || []);

  return (
    <div className="space-y-4" data-testid="formation-detail-page">
      {paymentMsg && (
        <div className={`rounded-xl border p-3 text-sm ${paymentMsg.kind === "success" ? "bg-emerald-50 border-emerald-200 text-emerald-800" : paymentMsg.kind === "warn" ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-blue-50 border-blue-200 text-blue-800"}`} data-testid="formation-payment-banner">
          {paymentMsg.text}
        </div>
      )}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate("/portal/formations")} className="text-slate-500 hover:text-sawali-blue"><ArrowLeft className="h-5 w-5" /></button>
          <div>
            <h1 className="text-xl font-display font-bold flex items-center gap-2">{formation.name}</h1>
            {enrollment && (
              <div className="flex items-center gap-2 flex-wrap text-xs">
                <span className={`px-2 py-0.5 rounded ${STATE_BADGES[enrollment.state] || "bg-slate-100"}`}>{stateLabel(enrollment.state)}</span>
                <span className="text-slate-500">{enrollment.modules_seen_count}/{enrollment.modules_total} modules</span>
                <span className="text-amber-600">{enrollment.credits_available || 0}/{enrollment.credits_purchased || 0} crédits</span>
                <span className="text-slate-500">{((enrollment.total_time_ms || 0) / 60000).toFixed(1)} min</span>
              </div>
            )}
          </div>
        </div>
        {enrollment && <FormationRating fid={fid} initialStars={data.my_rating?.stars || 0} onChange={load} />}
      </div>

      <div className="grid lg:grid-cols-[280px,1fr] gap-4">
        <aside className="rounded-xl border border-slate-200 bg-white p-3 max-h-[80vh] overflow-auto">
          <ul className="space-y-1">
            {modules.map((m, i) => (
              <li key={m.id}>
                <button onClick={() => setActiveMid(m.id)} className={`w-full text-left rounded px-2.5 py-2 text-sm flex items-center justify-between gap-2 ${activeMid === m.id ? "bg-sawali-blue/10 text-sawali-blue" : "hover:bg-slate-50 text-slate-700"}`} data-testid={`module-tab-${m.id}`}>
                  <span className="flex items-center gap-2 min-w-0">
                    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${seen.has(m.id) ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{i + 1}</span>
                    <span className="truncate">{m.name}</span>
                  </span>
                  {seen.has(m.id) && <ChevronRight className="h-3 w-3 opacity-60" />}
                </button>
              </li>
            ))}
            {modules.length === 0 && <li className="text-sm text-slate-500 px-2 py-4">Aucun module disponible.</li>}
          </ul>
        </aside>

        <main className="space-y-4">
          {activeModule ? <ModuleViewer key={activeModule.id} fid={fid} module={activeModule} onClose={load} /> : <div className="rounded-xl border border-slate-200 bg-white p-10 text-center text-slate-500">Sélectionnez un module pour commencer.</div>}
        </main>
      </div>
    </div>
  );
}

// =====================================================================
// Module viewer with timer + Q/R
// =====================================================================
function ModuleViewer({ fid, module, onClose }) {
  const visitIdRef = useRef(null);
  const [opened, setOpened] = useState(false);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [response, setResponse] = useState(null);

  // Track open + close
  useEffect(() => {
    let cancelled = false;
    apiClient.post(`/me/formations/${fid}/modules/${module.id}/visit`).then((r) => {
      if (cancelled) return;
      visitIdRef.current = r.data?.visit_id;
      setOpened(true);
    }).catch(() => {});
    const closeVisit = () => {
      if (visitIdRef.current) {
        const url = `/api/me/formations/${fid}/modules/${module.id}/visit/${visitIdRef.current}/close`;
        try {
          // sendBeacon survives page unload
          const tok = localStorage.getItem("sawali_token");
          const blob = new Blob([JSON.stringify({})], { type: "application/json" });
          // sendBeacon doesn't allow custom headers; fallback to fetch keepalive
          const base = process.env.REACT_APP_BACKEND_URL || "";
          fetch(`${base}${url}`, { method: "POST", headers: { Authorization: `Bearer ${tok}` }, keepalive: true });
          // also fire via apiClient as backup
          apiClient.post(url.replace("/api", "")).catch(() => {});
        } catch (e) { /* ignore */ }
      }
    };
    window.addEventListener("beforeunload", closeVisit);
    return () => {
      cancelled = true;
      closeVisit();
      window.removeEventListener("beforeunload", closeVisit);
      if (onClose) onClose();
    };
    // eslint-disable-next-line
  }, [fid, module.id]);

  const ask = async (e) => {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true); setResponse(null);
    try {
      const r = await apiClient.post(`/me/formations/${fid}/modules/${module.id}/ask`, { question });
      setResponse(r.data);
      setQuestion("");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec de la requête API");
    } finally { setBusy(false); }
  };

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5 space-y-4" data-testid={`module-view-${module.id}`}>
      <header>
        <h2 className="text-lg font-display font-semibold">{module.name}</h2>
        {module.software_path && <div className="text-xs text-slate-500 font-mono mt-1">📂 {module.software_path}</div>}
      </header>

      {module.screenshot_url && (
        <a href={module.screenshot_url} target="_blank" rel="noreferrer" className="block">
          <img src={module.screenshot_url} alt="Capture d'écran" className="w-full max-h-72 object-contain rounded-lg border border-slate-200 bg-slate-50" />
        </a>
      )}

      {module.content_html && <div className="prose-sawali text-sm" dangerouslySetInnerHTML={{ __html: module.content_html }} />}

      {module.api_url && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50/40 p-3 space-y-2">
          <p className="text-xs font-semibold flex items-center gap-2 text-emerald-700"><Send className="h-3 w-3" /> Posez votre question</p>
          <form onSubmit={ask} className="flex gap-2">
            <input value={question} onChange={(e) => setQuestion(e.target.value)} className="flex-1 rounded-lg border border-emerald-200 px-3 py-2 text-sm focus:border-sawali-blue focus:outline-none" placeholder="Tapez votre question…" data-testid={`module-ask-input-${module.id}`} />
            <button type="submit" disabled={busy} className="rounded-lg bg-emerald-600 text-white px-3 py-2 text-sm hover:bg-emerald-700 disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Envoyer"}</button>
          </form>
          {response && (
            <div className="text-xs bg-white rounded-lg p-2 border border-slate-200" data-testid={`module-response-${module.id}`}>
              <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-1">Réponse · HTTP {response.status}</div>
              <pre className="whitespace-pre-wrap font-mono text-[12px]">{typeof response.response === "string" ? response.response : JSON.stringify(response.response, null, 2)}</pre>
            </div>
          )}
        </div>
      )}

      {!opened && <div className="text-xs text-slate-400">Initialisation du suivi…</div>}
    </article>
  );
}

function FormationRating({ fid, initialStars, onChange }) {
  const [stars, setStars] = useState(initialStars || 0);
  const set = async (s) => {
    setStars(s);
    try { await apiClient.post(`/me/ratings/formations/${fid}`, { stars: s }); toast.success(`Note ${s}/5 enregistrée`); onChange?.(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Erreur"); }
  };
  return (
    <div className="inline-flex items-center gap-1" data-testid="formation-rating">
      <span className="text-[10px] uppercase tracking-widest text-slate-500 mr-1">votre note</span>
      {[1, 2, 3, 4, 5].map((n) => (
        <button key={n} onClick={() => set(n)} className="p-0.5"><Star className={`h-4 w-4 ${n <= stars ? "fill-amber-400 text-amber-500" : "text-slate-300"}`} /></button>
      ))}
    </div>
  );
}
