import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  ArrowLeft,
  Volume2,
  Plus,
  Trash2,
  Save,
  Send,
  RadioTower,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Settings as SettingsIcon,
  KeySquare,
} from "lucide-react";

/*
  Iter38r-fix9r — Admin → Notifications vocales Home Assistant.

  Permet à un admin tenant de :
   - Configurer l'URL + Token Long-Lived de son serveur Home Assistant
   - Définir l'enceinte cible par défaut (entity_id Alexa)
   - Parcourir le catalogue d'évènements actionnables (built-in + custom)
   - Activer / personnaliser le texte TTS lu par Alexa pour chaque évènement
   - Ajouter ses propres évènements personnalisés (libellé, module, table)
   - Tester la passerelle via un message vocal de démonstration
*/

const CATEGORY_BADGES = {
  billing: { label: "Facturation", color: "bg-emerald-100 text-emerald-700 ring-emerald-200" },
  support: { label: "Support", color: "bg-rose-100 text-rose-700 ring-rose-200" },
  payments: { label: "Paiements", color: "bg-amber-100 text-amber-700 ring-amber-200" },
  hr: { label: "RH", color: "bg-violet-100 text-violet-700 ring-violet-200" },
  alerts: { label: "Alertes", color: "bg-red-100 text-red-700 ring-red-200" },
  crm: { label: "CRM", color: "bg-sky-100 text-sky-700 ring-sky-200" },
  sales: { label: "Ventes", color: "bg-fuchsia-100 text-fuchsia-700 ring-fuchsia-200" },
  calendar: { label: "Agenda", color: "bg-blue-100 text-blue-700 ring-blue-200" },
  communications: { label: "Comm", color: "bg-teal-100 text-teal-700 ring-teal-200" },
  custom: { label: "Custom", color: "bg-slate-200 text-slate-700 ring-slate-300" },
};

export default function AdminVoiceNotifications() {
  const [config, setConfig] = useState({ enabled: false, provider: "home_assistant", ha_url: "", ha_token_set: false, ha_token_masked: "", ha_speaker: "", notify_service: "alexa_media", voice_monkey_url_set: false, voice_monkey_url_masked: "" });
  const [haTokenInput, setHaTokenInput] = useState("");
  const [vmUrlInput, setVmUrlInput] = useState("");
  const [catalog, setCatalog] = useState({ builtin: [], custom: [] });
  const [rules, setRules] = useState({});  // map event_key -> rule
  const [selectedKey, setSelectedKey] = useState(null);
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [customDraft, setCustomDraft] = useState({ event_key: "", label: "", module: "", page: "", db_table: "", default_tts: "", variables: "" });
  const [testMessage, setTestMessage] = useState("Bonjour. Le système SAWALI fonctionne et la passerelle Home Assistant est opérationnelle.");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [lastTest, setLastTest] = useState(null);
  const [log, setLog] = useState([]);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [cfg, cat, rul, lg] = await Promise.all([
        apiClient.get("/admin/voice-notifications/config"),
        apiClient.get("/admin/voice-notifications/catalog"),
        apiClient.get("/admin/voice-notifications/rules"),
        apiClient.get("/admin/voice-notifications/log", { params: { limit: 20 } }),
      ]);
      setConfig(cfg.data);
      setCatalog(cat.data);
      const map = {};
      for (const r of (rul.data?.items || [])) map[r.event_key] = r;
      setRules(map);
      setLog(lg.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAll(); }, []);

  const allEvents = useMemo(
    () => [...(catalog.builtin || []), ...(catalog.custom || [])],
    [catalog],
  );

  const selectedEvent = useMemo(
    () => allEvents.find((e) => e.key === selectedKey) || null,
    [allEvents, selectedKey],
  );

  const selectedRule = selectedKey
    ? rules[selectedKey] || { enabled: false, tts_template: selectedEvent?.default_tts || "", speaker_override: "" }
    : null;

  const saveConfig = async () => {
    setSaving(true);
    try {
      const payload = {
        enabled: config.enabled,
        provider: config.provider || "home_assistant",
        ha_url: config.ha_url,
        ha_speaker: config.ha_speaker,
        notify_service: config.notify_service || "alexa_media",
      };
      if (haTokenInput.trim()) payload.ha_token = haTokenInput.trim();
      if (vmUrlInput.trim()) payload.voice_monkey_url = vmUrlInput.trim();
      await apiClient.put("/admin/voice-notifications/config", payload);
      toast.success("Configuration enregistrée");
      setHaTokenInput("");
      setVmUrlInput("");
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSaving(false);
    }
  };

  const saveRule = async (eventKey, patch) => {
    const currentRule = rules[eventKey] || { enabled: false, tts_template: "", speaker_override: "" };
    const next = { ...currentRule, ...patch };
    setRules((r) => ({ ...r, [eventKey]: next }));
    try {
      await apiClient.put(`/admin/voice-notifications/rules/${eventKey}`, {
        enabled: !!next.enabled,
        tts_template: next.tts_template || "",
        speaker_override: next.speaker_override || "",
      });
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const addCustom = async () => {
    try {
      const variables = customDraft.variables
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      await apiClient.post("/admin/voice-notifications/custom-events", {
        ...customDraft,
        variables,
      });
      toast.success("Évènement personnalisé ajouté");
      setCustomDraft({ event_key: "", label: "", module: "", page: "", db_table: "", default_tts: "", variables: "" });
      setShowCustomForm(false);
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const deleteCustom = async (key) => {
    if (!window.confirm(`Supprimer l'évènement personnalisé "${key}" ?`)) return;
    try {
      await apiClient.delete(`/admin/voice-notifications/custom-events/${key}`);
      toast.success("Évènement supprimé");
      if (selectedKey === key) setSelectedKey(null);
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const runTest = async () => {
    setTesting(true);
    setLastTest(null);
    try {
      const r = await apiClient.post("/admin/voice-notifications/test", { message: testMessage });
      setLastTest(r.data);
      if (r.data?.ok) toast.success("Annonce envoyée à Home Assistant");
      else toast.warning("Home Assistant a répondu avec un code non OK");
      await loadAll();
    } catch (err) {
      setLastTest({ ok: false, error: err?.response?.data?.detail || String(err) });
      toast.error(err?.response?.data?.detail || "Échec du test");
    } finally {
      setTesting(false);
    }
  };

  if (loading) return <p className="p-6 text-slate-500">Chargement…</p>;

  return (
    <div className="space-y-6 p-6 max-w-7xl" data-testid="admin-voice-notifications-page">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <Link to="/admin/settings" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-sawali-blue mb-1">
            <ArrowLeft className="h-3 w-3" /> Retour aux paramètres
          </Link>
          <h1 className="text-2xl font-display font-bold inline-flex items-center gap-2">
            <Volume2 className="h-6 w-6 text-sawali-blue" /> Notifications vocales — Home Assistant
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Diffusez vocalement les évènements clés du CRM sur vos enceintes Amazon Echo / Alexa. Deux fournisseurs supportés : <strong>Voice Monkey</strong> (plus simple, 1 URL webhook) ou <strong>Home Assistant</strong> (intégration <code className="bg-slate-100 px-1 rounded text-[11px]">alexa_media_player</code>, multi-enceintes).
          </p>
        </div>
      </div>

      {/* CONFIG */}
      <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 space-y-4" data-testid="voice-config-section">
        <div className="flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-sky-50 flex items-center justify-center">
            <SettingsIcon className="h-5 w-5 text-sky-600" />
          </div>
          <div className="flex-1">
            <h2 className="font-display font-semibold text-slate-900">Configuration de la passerelle vocale</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Choisissez le fournisseur qui diffusera les annonces sur vos enceintes Echo.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={config.enabled}
              onChange={(e) => setConfig((c) => ({ ...c, enabled: e.target.checked }))}
              className="h-4 w-4"
              data-testid="voice-config-enabled"
            />
            <span className="text-sm font-semibold text-slate-700">Passerelle activée</span>
          </label>
        </div>

        {/* Iter38r-fix9x — Provider switch */}
        <div className="rounded-xl ring-1 ring-slate-200 bg-slate-50 p-3 flex items-center gap-3 flex-wrap">
          <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Fournisseur :</span>
          <label className="inline-flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio" name="voice-provider" value="voice_monkey"
              checked={config.provider === "voice_monkey"}
              onChange={() => setConfig((c) => ({ ...c, provider: "voice_monkey" }))}
              data-testid="voice-provider-vm"
            />
            <span className="text-sm font-semibold text-slate-700">Voice Monkey</span>
            <span className="text-[10px] text-slate-500">(simple, 1 URL)</span>
          </label>
          <label className="inline-flex items-center gap-1.5 cursor-pointer ml-4">
            <input
              type="radio" name="voice-provider" value="home_assistant"
              checked={config.provider === "home_assistant"}
              onChange={() => setConfig((c) => ({ ...c, provider: "home_assistant" }))}
              data-testid="voice-provider-ha"
            />
            <span className="text-sm font-semibold text-slate-700">Home Assistant</span>
            <span className="text-[10px] text-slate-500">(multi-enceintes, avancé)</span>
          </label>
        </div>

        {/* Voice Monkey fields */}
        {config.provider === "voice_monkey" && (
          <div className="grid gap-3" data-testid="voice-vm-fields">
            <label className="block">
              <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1">
                <KeySquare className="h-3 w-3" /> URL webhook Voice Monkey
                {config.voice_monkey_url_set && (
                  <span className="text-[10px] text-emerald-600 ml-1">(actuelle : {config.voice_monkey_url_masked})</span>
                )}
              </span>
              <input
                type="password"
                value={vmUrlInput}
                onChange={(e) => setVmUrlInput(e.target.value)}
                placeholder={config.voice_monkey_url_set ? "Laisser vide pour conserver" : "https://api-v2.voicemonkey.io/announcement?token=…&device=…"}
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                data-testid="voice-config-vm-url"
              />
              <p className="text-[10px] text-slate-500 mt-1">
                Profil Voice Monkey → Devices → cliquez sur le bouton « Get Announcement URL ». L'URL contient déjà le token et le nom de l'enceinte cible.
              </p>
            </label>
          </div>
        )}

        {/* Home Assistant fields */}
        {config.provider === "home_assistant" && (
        <div className="grid sm:grid-cols-2 gap-3" data-testid="voice-ha-fields">
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">URL Home Assistant</span>
            <input
              type="text"
              value={config.ha_url || ""}
              onChange={(e) => setConfig((c) => ({ ...c, ha_url: e.target.value }))}
              placeholder="http://homeassistant.local:8123"
              className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
              data-testid="voice-config-ha-url"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1">
              <KeySquare className="h-3 w-3" /> Token Long-Lived
              {config.ha_token_set && (
                <span className="text-[10px] text-emerald-600 ml-1">(actuel : {config.ha_token_masked})</span>
              )}
            </span>
            <input
              type="password"
              value={haTokenInput}
              onChange={(e) => setHaTokenInput(e.target.value)}
              placeholder={config.ha_token_set ? "Laisser vide pour conserver" : "eyJhbGciOi..."}
              className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
              data-testid="voice-config-ha-token"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Enceinte par défaut (entity_id)</span>
            <input
              type="text"
              value={config.ha_speaker || ""}
              onChange={(e) => setConfig((c) => ({ ...c, ha_speaker: e.target.value }))}
              placeholder="media_player.echo_bureau"
              className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
              data-testid="voice-config-ha-speaker"
            />
          </label>
          <label className="block">
            <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Service de notification HA</span>
            <input
              type="text"
              value={config.notify_service || "alexa_media"}
              onChange={(e) => setConfig((c) => ({ ...c, notify_service: e.target.value }))}
              placeholder="alexa_media"
              className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
              data-testid="voice-config-notify-service"
            />
          </label>
        </div>
        )}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={saveConfig}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue text-white px-4 py-2 text-sm hover:bg-sawali-blue-light disabled:opacity-50"
            data-testid="voice-config-save"
          >
            <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer la configuration"}
          </button>
          <div className="flex items-center gap-2 ml-auto">
            <input
              type="text"
              value={testMessage}
              onChange={(e) => setTestMessage(e.target.value)}
              className="text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white w-80 max-w-full"
              placeholder="Message de test"
              data-testid="voice-test-message"
            />
            <button
              onClick={runTest}
              disabled={testing || (config.provider === "home_assistant" && !config.ha_token_set) || (config.provider === "voice_monkey" && !config.voice_monkey_url_set)}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm hover:bg-emerald-700 disabled:opacity-50"
              data-testid="voice-test-btn"
              title="Tester la passerelle"
            >
              <Send className="h-4 w-4" /> {testing ? "Envoi…" : "Tester"}
            </button>
          </div>
        </div>
        {lastTest && (
          <div
            className={`rounded-lg ring-1 px-3 py-2 text-xs ${lastTest.ok ? "ring-emerald-300 bg-emerald-50 text-emerald-800" : "ring-rose-300 bg-rose-50 text-rose-800"}`}
            data-testid="voice-test-result"
          >
            {lastTest.ok ? <CheckCircle2 className="inline h-3.5 w-3.5 mr-1" /> : <AlertTriangle className="inline h-3.5 w-3.5 mr-1" />}
            {lastTest.ok
              ? <>Réponse HA <strong>{lastTest.ha_status}</strong> · message : « {lastTest.message} »{lastTest.target ? <> sur <code>{lastTest.target}</code></> : null}</>
              : <>Échec : {lastTest.error || lastTest.ha_response || lastTest.ha_status}</>}
          </div>
        )}
      </section>

      {/* CATALOG + RULES */}
      <section className="grid lg:grid-cols-2 gap-5">
        <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 space-y-3" data-testid="voice-catalog-section">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-display font-semibold text-slate-900 inline-flex items-center gap-2">
              <RadioTower className="h-5 w-5 text-fuchsia-600" /> Catalogue des actions ({allEvents.length})
            </h2>
            <button
              onClick={() => setShowCustomForm((v) => !v)}
              className="inline-flex items-center gap-1.5 rounded-lg ring-1 ring-fuchsia-300 bg-fuchsia-50 hover:bg-fuchsia-100 text-fuchsia-700 px-3 py-1.5 text-xs"
              data-testid="voice-add-custom-btn"
            >
              <Plus className="h-3.5 w-3.5" /> Évènement perso
            </button>
          </div>
          {showCustomForm && (
            <div className="rounded-xl ring-1 ring-fuchsia-200 bg-fuchsia-50/40 p-3 space-y-2" data-testid="voice-add-custom-form">
              <div className="grid sm:grid-cols-2 gap-2">
                <input
                  type="text" value={customDraft.event_key}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, event_key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") }))}
                  placeholder="Clé : backup_finished (a-z, 0-9, _)"
                  className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                  data-testid="voice-custom-key"
                />
                <input
                  type="text" value={customDraft.label}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, label: e.target.value }))}
                  placeholder="Libellé : Backup MongoDB terminé"
                  className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                  data-testid="voice-custom-label"
                />
                <input
                  type="text" value={customDraft.module}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, module: e.target.value }))}
                  placeholder="Module : Système"
                  className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                  data-testid="voice-custom-module"
                />
                <input
                  type="text" value={customDraft.page}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, page: e.target.value }))}
                  placeholder="Page : /admin/backups"
                  className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                  data-testid="voice-custom-page"
                />
                <input
                  type="text" value={customDraft.db_table}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, db_table: e.target.value }))}
                  placeholder="Table BD : mongo_dumps"
                  className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                  data-testid="voice-custom-table"
                />
                <input
                  type="text" value={customDraft.variables}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, variables: e.target.value }))}
                  placeholder="Variables : time, size_mb"
                  className="text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                  data-testid="voice-custom-vars"
                />
              </div>
              <input
                type="text" value={customDraft.default_tts}
                onChange={(e) => setCustomDraft((d) => ({ ...d, default_tts: e.target.value }))}
                placeholder="Texte TTS par défaut : Sauvegarde terminée à {time}."
                className="w-full text-xs rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                data-testid="voice-custom-tts"
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => { setShowCustomForm(false); setCustomDraft({ event_key: "", label: "", module: "", page: "", db_table: "", default_tts: "", variables: "" }); }}
                  className="text-xs text-slate-500 hover:underline"
                >Annuler</button>
                <button
                  onClick={addCustom}
                  className="inline-flex items-center gap-1 rounded-lg bg-fuchsia-600 text-white px-3 py-1.5 text-xs hover:bg-fuchsia-700"
                  data-testid="voice-custom-save"
                >
                  <Plus className="h-3 w-3" /> Ajouter
                </button>
              </div>
            </div>
          )}
          <div className="max-h-[600px] overflow-y-auto -mx-1 px-1 space-y-1.5">
            {allEvents.map((ev) => {
              const rule = rules[ev.key];
              const enabled = !!rule?.enabled;
              const active = selectedKey === ev.key;
              const cat = CATEGORY_BADGES[ev.category] || CATEGORY_BADGES.custom;
              return (
                <button
                  key={ev.key}
                  onClick={() => setSelectedKey(ev.key)}
                  type="button"
                  className={`w-full text-left rounded-xl ring-1 transition px-3 py-2.5 ${
                    active
                      ? "ring-2 ring-sawali-blue bg-sky-50"
                      : "ring-slate-200 hover:ring-slate-300 bg-white"
                  }`}
                  data-testid={`voice-event-${ev.key}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-semibold text-slate-900 truncate">{ev.label}</p>
                        <span className={`text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded ring-1 ${cat.color}`}>
                          {cat.label}
                        </span>
                        {!ev.is_builtin && (
                          <span className="text-[9px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded ring-1 bg-fuchsia-100 text-fuchsia-700 ring-fuchsia-200">
                            Custom
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        <span className="font-semibold text-slate-600">{ev.module}</span>
                        {ev.page && <> · <code className="bg-slate-100 px-1 rounded">{ev.page}</code></>}
                        {ev.db_table && <> · table <code className="bg-slate-100 px-1 rounded">{ev.db_table}</code></>}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {enabled && (
                        <span className="text-[10px] font-bold text-emerald-700 bg-emerald-100 px-1.5 py-0.5 rounded">ON</span>
                      )}
                      {!ev.is_builtin && (
                        <button
                          onClick={(e) => { e.stopPropagation(); deleteCustom(ev.key); }}
                          className="text-rose-500 hover:text-rose-700"
                          title="Supprimer"
                          data-testid={`voice-delete-custom-${ev.key}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* RULE DETAIL */}
        <div className="rounded-2xl ring-1 ring-slate-200 bg-white p-5 space-y-3" data-testid="voice-rule-detail">
          {!selectedEvent ? (
            <p className="text-sm text-slate-500 italic">Sélectionnez un évènement à gauche pour définir le texte vocal lu par Home Assistant.</p>
          ) : (
            <>
              <div className="flex items-start gap-3">
                <div className="h-10 w-10 rounded-xl bg-fuchsia-50 flex items-center justify-center">
                  <Sparkles className="h-5 w-5 text-fuchsia-600" />
                </div>
                <div className="flex-1">
                  <h3 className="font-display font-semibold text-slate-900">{selectedEvent.label}</h3>
                  <p className="text-[11px] text-slate-500">
                    Clé : <code className="bg-slate-100 px-1 rounded">{selectedEvent.key}</code>
                    {" "}· module {selectedEvent.module}
                    {selectedEvent.db_table && <> · table BD <code className="bg-slate-100 px-1 rounded">{selectedEvent.db_table}</code></>}
                  </p>
                </div>
              </div>
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={!!selectedRule?.enabled}
                  onChange={(e) => saveRule(selectedEvent.key, { enabled: e.target.checked })}
                  className="h-4 w-4"
                  data-testid="voice-rule-enabled"
                />
                <span className="text-sm font-semibold text-slate-700">Activer l'annonce vocale pour cet évènement</span>
              </label>

              <label className="block">
                <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Texte lu par Alexa (variables entre accolades)</span>
                <textarea
                  rows={3}
                  value={selectedRule?.tts_template ?? selectedEvent.default_tts ?? ""}
                  onChange={(e) => setRules((r) => ({ ...r, [selectedEvent.key]: { ...(r[selectedEvent.key] || {}), tts_template: e.target.value } }))}
                  onBlur={(e) => saveRule(selectedEvent.key, { tts_template: e.target.value })}
                  className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-sans"
                  placeholder={selectedEvent.default_tts}
                  data-testid="voice-rule-template"
                />
              </label>
              {selectedEvent.variables?.length > 0 && (
                <div className="text-[11px] text-slate-500">
                  Variables disponibles :
                  {selectedEvent.variables.map((v) => (
                    <button
                      key={v}
                      type="button"
                      onClick={() => {
                        const cur = (selectedRule?.tts_template ?? selectedEvent.default_tts ?? "") + `{${v}}`;
                        setRules((r) => ({ ...r, [selectedEvent.key]: { ...(r[selectedEvent.key] || {}), tts_template: cur } }));
                      }}
                      className="ml-1 inline-flex items-center bg-slate-100 hover:bg-slate-200 px-1.5 py-0.5 rounded font-mono text-[10px]"
                    >
                      {"{"}{v}{"}"}
                    </button>
                  ))}
                </div>
              )}

              <label className="block">
                <span className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Enceinte spécifique (laisser vide pour utiliser celle par défaut)</span>
                <input
                  type="text"
                  value={selectedRule?.speaker_override || ""}
                  onChange={(e) => setRules((r) => ({ ...r, [selectedEvent.key]: { ...(r[selectedEvent.key] || {}), speaker_override: e.target.value } }))}
                  onBlur={(e) => saveRule(selectedEvent.key, { speaker_override: e.target.value })}
                  placeholder={config.ha_speaker || "media_player.echo_cuisine"}
                  className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                  data-testid="voice-rule-speaker"
                />
              </label>
              <p className="text-[10px] text-slate-400 italic">
                Modifications enregistrées automatiquement lorsque vous quittez le champ.
              </p>
            </>
          )}
        </div>
      </section>

      {/* LOG */}
      {log.length > 0 && (
        <section className="rounded-2xl ring-1 ring-slate-200 bg-white p-5" data-testid="voice-log-section">
          <h2 className="font-display font-semibold text-slate-900 mb-3">Journal des envois ({log.length})</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-[10px]">
                <tr>
                  <th className="text-left px-2 py-1.5">Date</th>
                  <th className="text-left px-2 py-1.5">Évènement</th>
                  <th className="text-left px-2 py-1.5">Message</th>
                  <th className="text-left px-2 py-1.5">Cible</th>
                  <th className="text-right px-2 py-1.5">Statut HA</th>
                </tr>
              </thead>
              <tbody>
                {log.map((l, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">{new Date(l.created_at).toLocaleString("fr-FR")}</td>
                    <td className="px-2 py-1.5 text-slate-700"><code className="bg-slate-100 px-1 rounded">{l.event_key}</code></td>
                    <td className="px-2 py-1.5 text-slate-800 max-w-[280px] truncate">{l.message}</td>
                    <td className="px-2 py-1.5 text-slate-500 font-mono">{l.speaker || "—"}</td>
                    <td className={`px-2 py-1.5 text-right font-mono ${l.ha_status >= 200 && l.ha_status < 300 ? "text-emerald-700" : "text-rose-700"}`}>
                      {l.ha_status || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="rounded-xl ring-1 ring-amber-200 bg-amber-50 p-4 text-xs text-amber-900" data-testid="voice-help">
        <p className="font-semibold mb-1">Comment ça marche ?</p>
        <ol className="list-decimal list-inside space-y-1">
          <li>Installez l'intégration <code>alexa_media_player</code> via HACS sur votre Home Assistant.</li>
          <li>Créez un Token Long-Lived dans HA (Profil → onglet Sécurité).</li>
          <li>Renseignez l'URL HA, le token, et l'identifiant de votre enceinte Echo (ex: <code>media_player.echo_bureau</code>).</li>
          <li>Activez les évènements souhaités et personnalisez le message vocal pour chaque action.</li>
          <li>Cliquez sur « Tester » pour vérifier que la passerelle fonctionne.</li>
        </ol>
      </div>
    </div>
  );
}
