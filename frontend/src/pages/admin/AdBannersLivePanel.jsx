// Iter38r-fix9z7 — Live admin dashboard panel for ad banners.
// Subscribes to /api/ws/ad-banners-live and displays a real-time list
// of active banners with their current impression / click counters that
// animate (flash) every time an event arrives.
import React, { useEffect, useRef, useState } from "react";
import { Eye, MousePointerClick, Wifi, WifiOff, Beaker, Image as ImageIcon } from "lucide-react";
import { resolveAssetUrl } from "@/lib/useAssetUrl";

const BACKEND = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
const WS_BASE = BACKEND.replace("https://", "wss://").replace("http://", "ws://");

export default function AdBannersLivePanel() {
  const [items, setItems] = useState([]);
  const [connected, setConnected] = useState(false);
  const [recentEvents, setRecentEvents] = useState([]); // last 5
  const flashTimers = useRef({});
  const wsRef = useRef(null);

  useEffect(() => {
    const token = localStorage.getItem("sawali_token") || "";
    if (!token) return;
    const url = `${WS_BASE}/api/ws/ad-banners-live?token=${encodeURIComponent(token)}`;
    let cancelled = false;
    let reconnectTimer = null;

    const open = () => {
      if (cancelled) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) reconnectTimer = setTimeout(open, 3000);
      };
      ws.onerror = () => {
        try { ws.close(); } catch { /* ignore */ }
      };
      ws.onmessage = (msg) => {
        let data;
        try { data = JSON.parse(msg.data); } catch { return; }
        if (data.event === "snapshot") {
          setItems(data.items || []);
        } else if (data.event === "impression" || data.event === "click") {
          // Update counters
          setItems((prev) => prev.map((it) =>
            it.id === data.banner_id ? { ...it, ...pickCounters(data) } : it
          ));
          // Flash row
          flashTimers.current[data.banner_id] = data.event;
          setTimeout(() => {
            flashTimers.current[data.banner_id] = null;
          }, 800);
          // Recent feed (last 5)
          setRecentEvents((prev) => [{
            event: data.event,
            banner_id: data.banner_id,
            name: data.name,
            advertiser_name: data.advertiser_name,
            variant: data.variant,
            ts: data.ts,
            key: `${data.banner_id}-${data.ts}-${Math.random()}`,
          }, ...prev].slice(0, 5));
        }
      };
    };
    open();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try { wsRef.current?.close(); } catch { /* ignore */ }
    };
  }, []);

  return (
    <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-4 sm:p-5 mb-6" data-testid="ad-banners-live-panel">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-lg bg-rose-50 flex items-center justify-center">
            <Eye className="h-5 w-5 text-rose-600" />
          </div>
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Régie publicitaire — Live</p>
            <h2 className="font-display font-bold text-slate-900">Bannières actives en temps réel</h2>
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-full ring-1 ${
            connected
              ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
              : "bg-rose-50 text-rose-700 ring-rose-200"
          }`}
          data-testid="ad-live-status"
        >
          {connected
            ? <><Wifi className="h-3 w-3" /> Connecté</>
            : <><WifiOff className="h-3 w-3" /> Hors-ligne — reconnexion…</>}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="text-xs text-slate-400 italic py-6 text-center">Aucune bannière active actuellement.</p>
      ) : (
        <div className="space-y-2">
          {items.map((it) => (
            <LiveRow key={it.id} item={it} flash={flashTimers.current[it.id]} />
          ))}
        </div>
      )}

      {recentEvents.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-200">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-semibold">Flux d'événements (5 derniers)</p>
          <div className="space-y-1">
            {recentEvents.map((e) => (
              <div key={e.key} className="text-xs flex items-center gap-2 text-slate-700" data-testid={`ad-live-event-${e.event}`}>
                <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                  e.event === "click" ? "bg-violet-100 text-violet-700" : "bg-sky-100 text-sky-700"
                }`}>{e.event === "click" ? "CLIC" : "VUE"}</span>
                <span className="font-semibold truncate flex-1">{e.name}</span>
                {e.advertiser_name && <span className="text-slate-400 truncate hidden sm:inline">{e.advertiser_name}</span>}
                <span className="text-[10px] uppercase font-mono text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded">var. {e.variant}</span>
                <time className="text-[10px] text-slate-400 tabular-nums hidden sm:inline">{new Date(e.ts).toLocaleTimeString("fr-FR")}</time>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function pickCounters(data) {
  return {
    total_impressions: data.total_impressions,
    total_clicks: data.total_clicks,
    total_impressions_a: data.total_impressions_a,
    total_impressions_b: data.total_impressions_b,
    total_clicks_a: data.total_clicks_a,
    total_clicks_b: data.total_clicks_b,
    amount_spent: data.amount_spent,
  };
}

function LiveRow({ item, flash }) {
  const ctr = item.total_impressions > 0
    ? ((item.total_clicks / item.total_impressions) * 100).toFixed(2)
    : "0";
  const bgFlash = flash === "click" ? "ring-violet-300 bg-violet-50/60"
    : flash === "impression" ? "ring-sky-300 bg-sky-50/60"
    : "ring-slate-200 bg-white";
  return (
    <div
      className={`rounded-lg ring-1 transition-all duration-700 flex items-center gap-3 p-2.5 ${bgFlash}`}
      data-testid={`ad-live-row-${item.id}`}
    >
      <div className="h-10 w-16 rounded ring-1 ring-slate-200 overflow-hidden bg-slate-100 flex-shrink-0">
        {item.image_url ? (
          item.media_kind === "video" ? (
            <video src={resolveAssetUrl(item.image_url)} className="w-full h-full object-cover" muted autoPlay loop playsInline />
          ) : (
            <img src={resolveAssetUrl(item.image_url)} alt="" className="w-full h-full object-cover" />
          )
        ) : (
          <div className="w-full h-full flex items-center justify-center"><ImageIcon className="h-4 w-4 text-slate-300" /></div>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className="font-semibold text-sm text-slate-900 truncate inline-flex items-center gap-1.5">
          {item.name}
          {item.ab_enabled && (
            <span className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider text-violet-700 bg-violet-100 px-1.5 py-0.5 rounded">
              <Beaker className="h-2.5 w-2.5" /> A/B
            </span>
          )}
        </p>
        <p className="text-[11px] text-slate-500 truncate">{item.advertiser_name || "—"} · {item.placement}</p>
      </div>
      <div className="text-right space-y-0.5">
        <div className="flex items-center gap-3 text-xs tabular-nums">
          <span className="inline-flex items-center gap-1 text-sky-700">
            <Eye className="h-3 w-3" /> <span className="font-bold">{item.total_impressions.toLocaleString("fr-FR")}</span>
          </span>
          <span className="inline-flex items-center gap-1 text-violet-700">
            <MousePointerClick className="h-3 w-3" /> <span className="font-bold">{item.total_clicks.toLocaleString("fr-FR")}</span>
          </span>
        </div>
        <p className="text-[10px] text-emerald-700 font-semibold tabular-nums">CTR {ctr}%</p>
      </div>
    </div>
  );
}
