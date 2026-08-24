import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  Zap, Plus, Trash2, Edit, Power, Wand2, AlertTriangle, CheckCircle2, Clock, ArrowRight, MessageCircle,
} from "lucide-react";
import { Link } from "react-router-dom";

/*
  Admin → Automations
  Déclenche un template WhatsApp à la survenance d'un événement (RDV créé,
  intervention créée, client créé, rappel J-1).
*/
export default function AdminAutomations() {
  const [items, setItems] = useState([]);
  const [events, setEvents] = useState([]);
  const [templates, setTemplates] = useState({ configured: false, items: [] });
  const [tokens, setTokens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null | object (creating/editing)

  const loadAll = async () => {
    setLoading(true);
    try {
      const [a, e, t, tk] = await Promise.all([
        apiClient.get("/admin/automations"),
        apiClient.get("/admin/automations/events"),
        apiClient.get("/admin/whatsapp/templates"),
        apiClient.get("/admin/messaging/variable-tokens"),
      ]);
      setItems(a.data || []);
      setEvents(e.data?.events || []);
      setTemplates(t.data || { configured: false, items: [] });
      setTokens(tk.data?.tokens || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadAll(); /* eslint-disable-next-line */ }, []);

  const startCreate = () => {
    const firstEvent = events[0]?.value || "client.created";
    setEditing({
      title: "",
      event: firstEvent,
      template_name: "",
      language_code: "fr",
      variables: [],
      delay_minutes: 0,
      target: "event_target",
      enabled: true,
      notification_email: "",
      notification_phone: "",
    });
  };

  const remove = async (id) => {
    if (!window.confirm("Supprimer cette automation ?")) return;
    try {
      await apiClient.delete(`/admin/automations/${id}`);
      toast.success("Supprimée");
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const toggleEnabled = async (it) => {
    try {
      await apiClient.put(`/admin/automations/${it.id}`, { enabled: !it.enabled });
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="max-w-7xl space-y-6" data-testid="admin-automations-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">CRM</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Zap className="h-5 w-5 text-amber-500" /> Automations WhatsApp
          </h1>
          <p className="text-sm text-slate-500">
            Envoyez automatiquement un template Meta à un client lors d'un événement (RDV, intervention, nouveau client, rappel J-1).
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/admin/messaging"
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="automations-to-messaging"
          >
            <MessageCircle className="h-3.5 w-3.5" /> Messagerie WhatsApp
          </Link>
          <button
            onClick={startCreate}
            disabled={!templates.configured}
            title={!templates.configured ? "Configurez WhatsApp d'abord" : ""}
            className="inline-flex items-center gap-2 rounded-lg bg-amber-500 text-white px-3 py-1.5 text-sm hover:bg-amber-600 disabled:opacity-50"
            data-testid="automations-create-btn"
          >
            <Plus className="h-4 w-4" /> Nouvelle automation
          </button>
        </div>
      </div>

      {!templates.configured && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-sm text-amber-900">
            <strong>WhatsApp Business API non configurée.</strong> Configurez les
            credentials Meta dans <Link to="/admin/settings" className="underline font-semibold">Paramètres</Link> et
            faites approuver au moins un template avant de créer une automation.
          </div>
        </div>
      )}

      {/* List */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        {loading ? (
          <div className="text-center text-slate-500 py-10">Chargement…</div>
        ) : items.length === 0 ? (
          <div className="text-center text-slate-400 py-10 italic text-sm">
            Aucune automation. Cliquez sur "Nouvelle automation" pour démarrer.
          </div>
        ) : (
          <table className="min-w-full text-sm" data-testid="automations-table">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="text-left py-2 px-3">Titre</th>
                <th className="text-left py-2 px-3">Événement</th>
                <th className="text-left py-2 px-3">Template</th>
                <th className="text-left py-2 px-3">Délai</th>
                <th className="text-center py-2 px-3">Déclenchements</th>
                <th className="text-center py-2 px-3">Activée</th>
                <th className="text-right py-2 px-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const ev = events.find((e) => e.value === it.event);
                return (
                  <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`automation-row-${it.id}`}>
                    <td className="py-2 px-3 font-medium text-slate-900">{it.title}</td>
                    <td className="py-2 px-3">
                      <span className="text-[11px] font-mono bg-slate-100 px-1.5 py-0.5 rounded">
                        {ev?.label || it.event}
                      </span>
                    </td>
                    <td className="py-2 px-3 font-mono text-[11px] text-slate-700">{it.template_name}</td>
                    <td className="py-2 px-3 text-slate-600 text-xs">
                      {it.delay_minutes > 0 ? (
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" /> +{it.delay_minutes} min
                        </span>
                      ) : (
                        <span className="text-emerald-700">Immédiat</span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-center font-mono text-slate-700">{it.trigger_count || 0}</td>
                    <td className="py-2 px-3 text-center">
                      <button
                        onClick={() => toggleEnabled(it)}
                        className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] ${
                          it.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"
                        }`}
                        data-testid={`automation-toggle-${it.id}`}
                      >
                        <Power className="h-3 w-3" /> {it.enabled ? "ON" : "OFF"}
                      </button>
                    </td>
                    <td className="py-2 px-3 text-right">
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => setEditing({ ...it })}
                          className="inline-flex items-center gap-1 text-[11px] rounded bg-slate-700 text-white px-2 py-1 hover:bg-slate-800"
                          data-testid={`automation-edit-${it.id}`}
                        >
                          <Edit className="h-3 w-3" />
                        </button>
                        <button
                          onClick={() => remove(it.id)}
                          className="inline-flex items-center gap-1 text-[11px] rounded bg-rose-500 text-white px-2 py-1 hover:bg-rose-600"
                          data-testid={`automation-delete-${it.id}`}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {editing && (
        <AutomationModal
          editing={editing}
          setEditing={setEditing}
          events={events}
          templates={templates}
          tokens={tokens}
          onSaved={async () => { setEditing(null); await loadAll(); }}
        />
      )}
    </div>
  );
}

function AutomationModal({ editing, setEditing, events, templates, tokens, onSaved }) {
  const isEdit = !!editing.id;
  const [saving, setSaving] = useState(false);
  const approved = (templates.items || []).filter((t) => (t.status || "").toUpperCase() === "APPROVED");
  const tpl = approved.find((t) => t.name === editing.template_name);

  const { bodyText, varCount } = useMemo(() => {
    if (!tpl) return { bodyText: "", varCount: 0 };
    const body = (tpl.components || []).find((c) => (c.type || "").toUpperCase() === "BODY");
    const text = body?.text || "";
    const matches = [...text.matchAll(/\{\{\s*(\d+)\s*\}\}/g)].map((m) => parseInt(m[1], 10));
    return { bodyText: text, varCount: matches.length ? Math.max(...matches) : 0 };
  }, [tpl]);

  // Sync variables array length to varCount
  useEffect(() => {
    setEditing((s) => {
      const variables = [...(s.variables || [])];
      while (variables.length < varCount) variables.push("");
      variables.length = varCount;
      return { ...s, variables };
    });
    // eslint-disable-next-line
  }, [varCount]);

  const updateVar = (i, val) => {
    setEditing((s) => {
      const variables = [...(s.variables || [])];
      variables[i] = val;
      return { ...s, variables };
    });
  };

  const insertToken = (i, tok) => {
    setEditing((s) => {
      const variables = [...(s.variables || [])];
      variables[i] = (variables[i] || "") + tok;
      return { ...s, variables };
    });
  };

  const save = async () => {
    if (!editing.title.trim()) {
      toast.error("Titre requis");
      return;
    }
    if (!editing.template_name) {
      toast.error("Template requis");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        title: editing.title,
        event: editing.event,
        template_name: editing.template_name,
        language_code: editing.language_code || "fr",
        variables: (editing.variables || []).filter(() => true),
        delay_minutes: parseInt(editing.delay_minutes || 0, 10) || 0,
        target: "event_target",
        enabled: !!editing.enabled,
        notification_email: (editing.notification_email || "").trim() || null,
        notification_phone: (editing.notification_phone || "").trim() || null,
      };
      if (isEdit) {
        await apiClient.put(`/admin/automations/${editing.id}`, payload);
      } else {
        await apiClient.post("/admin/automations", payload);
      }
      toast.success(isEdit ? "Automation mise à jour" : "Automation créée");
      await onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-start md:items-center justify-center p-4 overflow-y-auto"
      data-testid="automation-modal"
    >
      <div className="bg-white rounded-xl w-full max-w-2xl my-6 shadow-2xl">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-lg font-display font-bold flex items-center gap-2">
            <Zap className="h-5 w-5 text-amber-500" />
            {isEdit ? "Modifier l'automation" : "Nouvelle automation"}
          </h2>
          <button onClick={() => setEditing(null)} className="text-slate-500 hover:text-slate-900" data-testid="automation-modal-close">✕</button>
        </div>
        <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Titre *</label>
            <input
              value={editing.title}
              onChange={(e) => setEditing({ ...editing, title: e.target.value })}
              placeholder="Ex: Bienvenue nouveau client"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="automation-title-input"
            />
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Événement déclencheur</label>
            <select
              value={editing.event}
              onChange={(e) => setEditing({ ...editing, event: e.target.value })}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="automation-event-select"
            >
              {events.map((e) => (
                <option key={e.value} value={e.value}>{e.label} — {e.value}</option>
              ))}
            </select>
            <p className="text-[11px] text-slate-500 mt-1">
              {events.find((e) => e.value === editing.event)?.description || ""}
            </p>
          </div>

          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Template Meta</label>
              <select
                value={editing.template_name}
                onChange={(e) => {
                  const next = e.target.value;
                  const t = approved.find((x) => x.name === next);
                  setEditing({
                    ...editing,
                    template_name: next,
                    language_code: (t?.language || editing.language_code || "fr").split("_")[0],
                  });
                }}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="automation-template-select"
              >
                <option value="">— Sélectionner —</option>
                {approved.map((t) => (
                  <option key={t.name} value={t.name}>{t.name} · {t.language}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Délai (minutes)</label>
              <input
                type="number"
                min={0}
                max={10080}
                value={editing.delay_minutes}
                onChange={(e) => setEditing({ ...editing, delay_minutes: e.target.value })}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="automation-delay-input"
              />
              <p className="text-[11px] text-slate-500 mt-1">0 = envoi immédiat. Sinon planifié X minutes après l'événement.</p>
            </div>
          </div>

          {tpl && bodyText && (
            <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] italic text-slate-600 whitespace-pre-line">
              <strong className="not-italic text-slate-700">Corps Meta :</strong>
              <br />{bodyText}
            </div>
          )}

          {varCount > 0 && (
            <div className="space-y-2 pt-2 border-t border-slate-100">
              <h4 className="text-xs font-semibold flex items-center gap-2">
                <Wand2 className="h-3.5 w-3.5 text-amber-600" /> Variables ({varCount})
              </h4>
              {Array.from({ length: varCount }).map((_, i) => (
                <div key={i} className="grid grid-cols-[60px_1fr_auto] gap-2 items-center">
                  <span className="text-[11px] font-mono text-slate-500">{`{{${i + 1}}}`}</span>
                  <input
                    value={editing.variables?.[i] || ""}
                    onChange={(e) => updateVar(i, e.target.value)}
                    placeholder="Texte ou tokens"
                    className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs font-mono"
                    data-testid={`automation-variable-input-${i + 1}`}
                  />
                  <select
                    onChange={(e) => {
                      const tk = e.target.value;
                      if (tk) { insertToken(i, tk); e.target.value = ""; }
                    }}
                    defaultValue=""
                    className="rounded-lg border border-slate-300 bg-white px-1.5 py-1.5 text-[11px]"
                    data-testid={`automation-variable-token-picker-${i + 1}`}
                  >
                    <option value="">+ Insérer…</option>
                    {tokens.map((t) => (
                      <option key={t.token} value={t.token}>{t.label}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          )}

          <label className="inline-flex items-center gap-2 text-sm pt-2 border-t border-slate-100" data-testid="automation-enabled-toggle">
            <input
              type="checkbox"
              checked={!!editing.enabled}
              onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })}
              className="accent-emerald-600"
            />
            <span className="text-slate-700">Automation activée</span>
          </label>

          {/* 2026-02 fork (bug fix) — Email de secours si WA échoue */}
          <div className="pt-2 border-t border-slate-100" data-testid="automation-notification-email-row">
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
              Email de secours (fallback WhatsApp)
            </label>
            <input
              type="email"
              value={editing.notification_email || ""}
              onChange={(e) => setEditing({ ...editing, notification_email: e.target.value })}
              placeholder="admin@sawalismartsystems.com"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="automation-notification-email-input"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Utilisé UNIQUEMENT quand l'envoi WhatsApp échoue (template refusé, numéro manquant, timeout Meta…). Vous pouvez définir un email différent par automation.
            </p>
          </div>

          {/* 2026-02 fork iter102 (bug fix prod) — Numéro WA de secours */}
          <div data-testid="automation-notification-phone-row">
            <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
              Numéro WhatsApp de secours (E.164, sans « + »)
            </label>
            <input
              type="tel"
              value={editing.notification_phone || ""}
              onChange={(e) => setEditing({ ...editing, notification_phone: e.target.value })}
              placeholder="22670000000"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
              data-testid="automation-notification-phone-input"
            />
            <p className="text-[11px] text-slate-500 mt-1">
              Numéro WhatsApp utilisé quand le destinataire résolu par l'événement <em>n'a pas de téléphone ni de whatsapp_number</em> (ex : compte super-admin). Le message WA est alors envoyé à ce numéro à la place. Vide = pas de fallback WA → l'email de secours prend le relais.
            </p>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-slate-200 flex justify-end gap-2">
          <button
            onClick={() => setEditing(null)}
            className="text-sm px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50"
            data-testid="automation-cancel-btn"
          >
            Annuler
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 text-sm rounded-lg bg-amber-500 text-white px-4 py-1.5 hover:bg-amber-600 disabled:opacity-50"
            data-testid="automation-save-btn"
          >
            {saving ? "…" : (
              <>
                <CheckCircle2 className="h-4 w-4" /> {isEdit ? "Enregistrer" : "Créer"}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
