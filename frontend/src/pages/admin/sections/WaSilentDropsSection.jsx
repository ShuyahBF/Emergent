// Iter43-fix24az-w (2026-07-22) — Admin section : WhatsApp Silent Drops.
// Monitor Meta "silent drops" (HTTP 2xx without message_id — payload silently
// rejected). Configure threshold-based alerts sent by email + WhatsApp when
// the count in the window exceeds the configured threshold.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Loader2, Save, AlertTriangle, Bell, RefreshCw, Trash2, Send, ShieldAlert,
} from "lucide-react";

export default function WaSilentDropsSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [stats, setStats] = useState(null);
  const [drops, setDrops] = useState([]);
  const [cfg, setCfg] = useState({
    enabled: false,
    threshold: 5,
    window_minutes: 15,
    cooldown_minutes: 60,
    emails: [],
    wa_phones: [],
  });
  const [emailsText, setEmailsText] = useState("");
  const [phonesText, setPhonesText] = useState("");

  const load = async () => {
    try {
      setLoading(true);
      const [rStats, rList] = await Promise.all([
        apiClient.get("/admin/wa-silent-drops/stats"),
        apiClient.get("/admin/wa-silent-drops?limit=20"),
      ]);
      setStats(rStats.data);
      setDrops(rList.data?.drops || []);
      const c = rStats.data?.config || {};
      setCfg({
        enabled: !!c.enabled,
        threshold: c.threshold ?? 5,
        window_minutes: c.window_minutes ?? 15,
        cooldown_minutes: c.cooldown_minutes ?? 60,
        emails: c.emails || [],
        wa_phones: c.wa_phones || [],
      });
      setEmailsText((c.emails || []).join("\n"));
      setPhonesText((c.wa_phones || []).join("\n"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const [rStats, rList] = await Promise.all([
        apiClient.get("/admin/wa-silent-drops/stats"),
        apiClient.get("/admin/wa-silent-drops?limit=20"),
      ]);
      setStats(rStats.data);
      setDrops(rList.data?.drops || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally {
      setRefreshing(false);
    }
  };

  const save = async () => {
    try {
      setSaving(true);
      const emails = emailsText.split(/[\s,;]+/).map((s) => s.trim().toLowerCase())
        .filter((e) => e.includes("@") && e.split("@")[1]?.includes("."));
      const phones = phonesText.split(/[\s,;]+/).map((p) => p.replace(/\D+/g, ""))
        .filter((p) => p.length >= 6);
      const r = await apiClient.put("/admin/wa-silent-drops/config", {
        enabled: cfg.enabled,
        threshold: Number(cfg.threshold),
        window_minutes: Number(cfg.window_minutes),
        cooldown_minutes: Number(cfg.cooldown_minutes),
        emails,
        wa_phones: phones,
      });
      toast.success("Configuration alertes enregistrée");
      setCfg({
        enabled: !!r.data.enabled,
        threshold: r.data.threshold,
        window_minutes: r.data.window_minutes,
        cooldown_minutes: r.data.cooldown_minutes,
        emails: r.data.emails,
        wa_phones: r.data.wa_phones,
      });
      setEmailsText((r.data.emails || []).join("\n"));
      setPhonesText((r.data.wa_phones || []).join("\n"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur enregistrement");
    } finally {
      setSaving(false);
    }
  };

  const testAlert = async () => {
    try {
      setTesting(true);
      const r = await apiClient.post("/admin/wa-silent-drops/test-alert");
      const emailsOk = (r.data?.email_results || []).filter((e) => e.ok).length;
      const emailsFail = (r.data?.email_results || []).filter((e) => !e.ok).length;
      const waOk = (r.data?.wa_results || []).filter((w) => w.ok).length;
      const waFail = (r.data?.wa_results || []).filter((w) => !w.ok).length;
      if (emailsOk + waOk === 0 && emailsFail + waFail === 0) {
        toast.warning("Aucun destinataire configuré — ajoute au moins 1 email ou 1 numéro WA");
      } else {
        toast.success(`Alerte test envoyée — Emails ${emailsOk}✓/${emailsFail}✗ · WhatsApp ${waOk}✓/${waFail}✗`);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur test alerte");
    } finally {
      setTesting(false);
    }
  };

  const clearAll = async () => {
    if (!window.confirm("Supprimer TOUS les enregistrements de silent drops ?")) return;
    try {
      setClearing(true);
      const r = await apiClient.delete("/admin/wa-silent-drops");
      toast.success(`${r.data?.deleted ?? 0} drops supprimés`);
      await refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally {
      setClearing(false);
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
      <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
    </div>
  );

  const s = stats || {};
  const alertLive = s.threshold_reached;

  return (
    <div className="space-y-5" data-testid="wa-silent-drops-section">
      <p className="text-xs text-slate-600">
        Meta rejette parfois des messages WhatsApp sans erreur (HTTP 2xx mais{" "}
        <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">message_id: null</code>) —
        ex. token expiré, template non approuvé, quota dépassé, payload trop long.
        Cette section enregistre ces événements et déclenche une alerte
        (email + WhatsApp) quand leur nombre dépasse le seuil dans la fenêtre.
      </p>

      {/* ---------------- LIVE STATS ---------------- */}
      <div className="grid grid-cols-3 gap-3">
        <StatCard
          label="Dernières 15 min"
          value={s.last_15m ?? 0}
          highlight={s.last_15m >= (cfg.threshold || 5)}
          testid="wa-drops-stat-15m"
        />
        <StatCard
          label="Dernière heure"
          value={s.last_1h ?? 0}
          testid="wa-drops-stat-1h"
        />
        <StatCard
          label="Dernières 24 h"
          value={s.last_24h ?? 0}
          testid="wa-drops-stat-24h"
        />
      </div>

      {alertLive && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-red-50 ring-1 ring-red-200 text-red-800 text-sm" data-testid="wa-drops-alert-active">
          <ShieldAlert className="h-5 w-5 shrink-0" />
          <div>
            <div className="font-semibold">Seuil atteint dans la fenêtre courante</div>
            <div className="text-xs mt-0.5">
              {s.current_window_count} drop(s) enregistrés dans les {cfg.window_minutes} dernières minutes
              (seuil = {cfg.threshold}). Une alerte a probablement été envoyée aux destinataires configurés
              (respecte le cooldown de {cfg.cooldown_minutes} min).
            </div>
          </div>
        </div>
      )}

      {/* ---------------- CONFIG ---------------- */}
      <div className="rounded-lg ring-1 ring-slate-200 p-4 space-y-4">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input
            type="checkbox"
            checked={cfg.enabled}
            onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
            className="h-4 w-4 rounded text-fuchsia-600 focus:ring-fuchsia-500"
            data-testid="wa-drops-alert-toggle"
          />
          <Bell className="h-4 w-4 text-fuchsia-600" />
          Activer les alertes automatiques (email + WhatsApp)
        </label>

        <div className="grid grid-cols-3 gap-3">
          <NumField
            label="Seuil (drops)"
            value={cfg.threshold}
            onChange={(v) => setCfg({ ...cfg, threshold: v })}
            min={1} max={1000}
            testid="wa-drops-threshold"
          />
          <NumField
            label="Fenêtre (min)"
            value={cfg.window_minutes}
            onChange={(v) => setCfg({ ...cfg, window_minutes: v })}
            min={1} max={1440}
            testid="wa-drops-window"
          />
          <NumField
            label="Cooldown (min)"
            value={cfg.cooldown_minutes}
            onChange={(v) => setCfg({ ...cfg, cooldown_minutes: v })}
            min={1} max={1440}
            testid="wa-drops-cooldown"
          />
        </div>

        <div className="grid md:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-600 mb-1">
              Emails destinataires (un par ligne)
            </label>
            <textarea
              value={emailsText}
              onChange={(e) => setEmailsText(e.target.value)}
              placeholder="admin@sawalismartsystems.com&#10;ops@example.com"
              rows={3}
              className="w-full text-xs font-mono px-2 py-1.5 rounded ring-1 ring-slate-300"
              data-testid="wa-drops-emails-textarea"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-600 mb-1">
              Numéros WhatsApp destinataires (un par ligne, format E.164)
            </label>
            <textarea
              value={phonesText}
              onChange={(e) => setPhonesText(e.target.value)}
              placeholder="+226 70 00 11 22&#10;+228 90 12 34 56"
              rows={3}
              className="w-full text-xs font-mono px-2 py-1.5 rounded ring-1 ring-slate-300"
              data-testid="wa-drops-phones-textarea"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-100">
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white disabled:opacity-60"
            data-testid="wa-drops-save"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Enregistrer
          </button>
          <button
            type="button"
            onClick={testAlert}
            disabled={testing || !cfg.enabled}
            title={!cfg.enabled ? "Active d'abord les alertes" : "Envoie un message de test aux destinataires"}
            className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-40"
            data-testid="wa-drops-test-alert"
          >
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Envoyer alerte de test
          </button>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              onClick={refresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg ring-1 ring-slate-300 hover:bg-slate-50"
              data-testid="wa-drops-refresh"
            >
              {refreshing ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              Rafraîchir
            </button>
            <button
              type="button"
              onClick={clearAll}
              disabled={clearing || drops.length === 0}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg ring-1 ring-red-300 text-red-700 hover:bg-red-50 disabled:opacity-40"
              data-testid="wa-drops-clear"
            >
              {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              Purger
            </button>
          </div>
        </div>

        {s.config?.last_sent_at && (
          <div className="text-[11px] text-slate-500 pt-1 border-t border-slate-100">
            Dernière alerte envoyée : {new Date(s.config.last_sent_at).toLocaleString("fr-FR")}
          </div>
        )}
      </div>

      {/* ---------------- RECENT DROPS ---------------- */}
      <div>
        <h4 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          20 derniers silent drops
        </h4>
        {drops.length === 0 ? (
          <div className="text-xs text-slate-500 italic py-3 text-center rounded bg-slate-50">
            Aucun silent drop enregistré (bonne nouvelle 🎉)
          </div>
        ) : (
          <div className="overflow-x-auto rounded ring-1 ring-slate-200">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-50">
                <tr className="text-left text-slate-600">
                  <th className="px-2 py-1.5 font-medium">Quand</th>
                  <th className="px-2 py-1.5 font-medium">Destinataire</th>
                  <th className="px-2 py-1.5 font-medium">Chunk</th>
                  <th className="px-2 py-1.5 font-medium">Taille</th>
                  <th className="px-2 py-1.5 font-medium">HTTP</th>
                  <th className="px-2 py-1.5 font-medium">Aperçu</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {drops.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50" data-testid={`wa-drop-row-${d.id}`}>
                    <td className="px-2 py-1.5 whitespace-nowrap text-slate-600">
                      {new Date(d.created_at).toLocaleString("fr-FR")}
                    </td>
                    <td className="px-2 py-1.5 font-mono">+{d.to}</td>
                    <td className="px-2 py-1.5 text-slate-500">
                      {d.chunk_index}/{d.chunk_total}
                    </td>
                    <td className="px-2 py-1.5">{d.chunk_length} car.</td>
                    <td className="px-2 py-1.5">{d.http_status || "—"}</td>
                    <td className="px-2 py-1.5 max-w-[240px] truncate text-slate-500" title={d.chunk_preview}>
                      {d.chunk_preview || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, highlight, testid }) {
  return (
    <div
      className={`rounded-lg ring-1 p-3 ${highlight ? "ring-red-300 bg-red-50" : "ring-slate-200 bg-white"}`}
      data-testid={testid}
    >
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold mt-0.5 ${highlight ? "text-red-700" : "text-slate-800"}`}>
        {value}
      </div>
    </div>
  );
}

function NumField({ label, value, onChange, min, max, testid }) {
  return (
    <div>
      <label className="block text-xs text-slate-600 mb-1">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        min={min}
        max={max}
        className="w-full text-sm px-2 py-1.5 rounded ring-1 ring-slate-300"
        data-testid={testid}
      />
    </div>
  );
}
