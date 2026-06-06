// Iter40 (2026-02) — Section Admin : Filtre no-toast WA.
// Quand activé, les messages WhatsApp provenant des numéros listés
// n'apparaissent pas comme toast dans le portail (mais sont quand même
// stockés en DB). Utile pour des numéros « techniques » qui spamment.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, BellOff, Save } from "lucide-react";

export default function WaSilentPhonesSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [text, setText] = useState("");

  const load = async () => {
    try {
      setLoading(true);
      const r = await apiClient.get("/admin/settings");
      setEnabled(!!r.data?.wa_silent_phones_enabled);
      const list = r.data?.wa_silent_phones || [];
      setText(list.join("\n"));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    try {
      setSaving(true);
      const phones = text
        .split(/[\s,;]+/)
        .map((p) => p.replace(/\D+/g, ""))
        .filter((p) => p.length >= 6);
      await apiClient.put("/admin/settings", {
        wa_silent_phones_enabled: enabled,
        wa_silent_phones: phones,
      });
      toast.success("Filtre no-toast WA enregistré");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur enregistrement");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
      <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
    </div>
  );

  const count = text.split(/[\s,;]+/).filter((p) => p.replace(/\D+/g, "").length >= 6).length;

  return (
    <div className="space-y-3" data-testid="wa-silent-phones-section">
      <p className="text-xs text-slate-600">
        Quand activé, les messages WhatsApp provenant des numéros listés ci-dessous
        ne déclenchent <strong>aucun toast</strong> dans le portail. Ils restent
        enregistrés normalement en base et sont visibles dans Inbox.
      </p>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          className="h-4 w-4 rounded text-fuchsia-600 focus:ring-fuchsia-500"
          data-testid="wa-silent-enabled-toggle"
        />
        <span className="inline-flex items-center gap-1.5">
          <BellOff className="h-4 w-4 text-fuchsia-600" />
          Activer le filtre no-toast WhatsApp
        </span>
        <span className="ml-auto text-[10px] text-slate-500">
          {count} numéro{count > 1 ? "s" : ""}
        </span>
      </label>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="+226 07 33 23 13&#10;+228 90 12 34 56"
        rows={5}
        disabled={!enabled}
        className="w-full text-xs font-mono px-2 py-1.5 rounded ring-1 ring-slate-300 disabled:bg-slate-50 disabled:text-slate-400"
        data-testid="wa-silent-phones-textarea"
      />
      <div className="flex justify-end">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-700 text-white disabled:opacity-60"
          data-testid="wa-silent-save"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Enregistrer
        </button>
      </div>
    </div>
  );
}
