import React, { useEffect, useMemo, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import {
  MessageCircle, Send, Users, UserCheck, Filter, Search, RefreshCw, CheckCircle2, XCircle, ClockIcon, AlertTriangle, Phone, Settings,
} from "lucide-react";
import { Link } from "react-router-dom";

/*
  Admin → Messagerie WhatsApp
  Sélection multi : clients + utilisateurs suivis → template Meta approuvé → envoi groupé.
  Historique des envois avec filtre (réussis / échoués / bulk / ad-hoc).
*/
export default function AdminMessaging() {
  const [audience, setAudience] = useState({ clients: [], tracked_users: [] });
  const [templates, setTemplates] = useState({ configured: false, items: [], error: null });
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  const [tab, setTab] = useState("clients");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState({}); // `${kind}:${id}` → true
  const [template, setTemplate] = useState("");
  const [language, setLanguage] = useState("fr");

  const loadAll = async () => {
    setLoading(true);
    try {
      const [aud, tpl, hist] = await Promise.all([
        apiClient.get("/admin/messaging/audience"),
        apiClient.get("/admin/whatsapp/templates"),
        apiClient.get("/admin/messaging/history", { params: { limit: 200 } }),
      ]);
      setAudience(aud.data || { clients: [], tracked_users: [] });
      setTemplates(tpl.data || { configured: false, items: [] });
      setHistory(hist.data || []);
      // Preselect first approved template
      const first = (tpl.data?.items || []).find((t) => (t.status || "").toUpperCase() === "APPROVED");
      if (first && !template) {
        setTemplate(first.name);
        setLanguage((first.language || "fr").split("_")[0]);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadAll(); /* eslint-disable-next-line */ }, []);

  const rows = tab === "clients" ? audience.clients : audience.tracked_users;
  const filtered = rows.filter((r) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (r.full_name || "").toLowerCase().includes(q) ||
      (r.email || "").toLowerCase().includes(q) ||
      (r.phone || "").toLowerCase().includes(q) ||
      (r.company || "").toLowerCase().includes(q) ||
      (r.client_label || "").toLowerCase().includes(q)
    );
  });

  const toggle = (kind, id) => {
    const key = `${kind}:${id}`;
    setSelected((s) => ({ ...s, [key]: !s[key] }));
  };

  const toggleAllVisible = () => {
    const withPhone = filtered.filter((r) => r.has_phone);
    const allOn = withPhone.every((r) => selected[`${r.kind}:${r.id}`]);
    const patch = {};
    withPhone.forEach((r) => { patch[`${r.kind}:${r.id}`] = !allOn; });
    setSelected((s) => ({ ...s, ...patch }));
  };

  const selectedList = useMemo(() => {
    const out = [];
    Object.entries(selected).forEach(([key, v]) => {
      if (!v) return;
      const [kind, id] = key.split(":");
      const row = [...audience.clients, ...audience.tracked_users].find(
        (r) => r.kind === kind && r.id === id
      );
      if (row && row.has_phone) out.push(row);
    });
    return out;
  }, [selected, audience]);

  const approved = (templates.items || []).filter((t) => (t.status || "").toUpperCase() === "APPROVED");

  const send = async () => {
    if (selectedList.length === 0) {
      toast.error("Sélectionnez au moins un destinataire");
      return;
    }
    if (!template) {
      toast.error("Choisissez un template Meta approuvé");
      return;
    }
    if (!window.confirm(`Envoyer le template "${template}" à ${selectedList.length} destinataire(s) ?`)) return;
    setSending(true);
    try {
      const r = await apiClient.post("/admin/messaging/bulk-send", {
        recipients: selectedList.map((x) => ({ kind: x.kind, id: x.id, phone: x.phone, label: x.full_name })),
        template_name: template,
        language_code: language || "fr",
      });
      const { sent_ok = 0, sent_ko = 0, skipped = [] } = r.data || {};
      if (sent_ok > 0 && sent_ko === 0) {
        toast.success(`${sent_ok} message(s) envoyé(s)`);
      } else if (sent_ok > 0) {
        toast.success(`${sent_ok} envoyé(s), ${sent_ko} en erreur`);
      } else {
        toast.error(`Aucun envoi — ${sent_ko} erreur(s). Vérifiez le template et les numéros.`);
      }
      if (skipped.length > 0) {
        toast.message(`${skipped.length} destinataire(s) ignoré(s) (pas de numéro).`);
      }
      setSelected({});
      await loadAll();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'envoi");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="max-w-7xl space-y-6" data-testid="admin-messaging-page">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Messagerie</p>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <MessageCircle className="h-5 w-5 text-sawali-blue" /> Messagerie WhatsApp
          </h1>
          <p className="text-sm text-slate-500">
            Envoi groupé de templates Meta approuvés aux clients et utilisateurs suivis.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            to="/admin/settings"
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="messaging-to-settings"
          >
            <Settings className="h-3.5 w-3.5" /> Paramètres WhatsApp
          </Link>
          <button
            onClick={loadAll}
            className="inline-flex items-center gap-1 text-xs rounded-lg border border-slate-300 px-3 py-1.5 hover:bg-slate-50"
            data-testid="messaging-refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Rafraîchir
          </button>
        </div>
      </div>

      {/* Config / template picker */}
      <div
        className={`rounded-xl border p-4 ${templates.configured ? "border-slate-200 bg-white" : "border-amber-300 bg-amber-50"}`}
        data-testid="messaging-config-card"
      >
        {!templates.configured ? (
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
            <div className="text-sm text-amber-900">
              <strong>WhatsApp Business API non configurée.</strong> Renseignez les identifiants Meta
              dans <Link to="/admin/settings" className="underline font-semibold">Paramètres → WhatsApp Business API</Link>
              &nbsp;(WABA ID, Phone Number ID, App ID, Token). Ensuite, créez et faites approuver vos templates dans Meta Business Suite.
            </div>
          </div>
        ) : (
          <div className="grid md:grid-cols-3 gap-3 items-end">
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
                Template Meta ({approved.length} approuvé{approved.length > 1 ? "s" : ""})
              </label>
              <select
                value={template}
                onChange={(e) => {
                  setTemplate(e.target.value);
                  const t = approved.find((x) => x.name === e.target.value);
                  if (t?.language) setLanguage((t.language || "fr").split("_")[0]);
                }}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                data-testid="messaging-template-select"
              >
                <option value="">— Sélectionner un template approuvé —</option>
                {approved.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name} · {t.language || "fr"} · {t.category || "UTILITY"}
                  </option>
                ))}
              </select>
              {approved.length === 0 && (
                <p className="text-[11px] text-amber-700 mt-1">
                  Aucun template approuvé trouvé côté Meta. Créez-en un dans Meta Business Suite.
                </p>
              )}
            </div>
            <div>
              <label className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Langue</label>
              <input
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                placeholder="fr, en, ar…"
                data-testid="messaging-language"
              />
            </div>
            <button
              onClick={send}
              disabled={sending || selectedList.length === 0 || !template}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-600 text-white px-4 py-2 text-sm hover:bg-emerald-700 disabled:opacity-50"
              data-testid="messaging-send-btn"
            >
              <Send className="h-4 w-4" />
              {sending ? "Envoi…" : `Envoyer à ${selectedList.length}`}
            </button>
          </div>
        )}
      </div>

      {/* Audience */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-200 flex-wrap">
          <div className="flex gap-1">
            <TabBtn active={tab === "clients"} onClick={() => setTab("clients")} testid="tab-clients">
              <Users className="h-3.5 w-3.5" /> Clients ({audience.clients.length})
            </TabBtn>
            <TabBtn active={tab === "tracked"} onClick={() => setTab("tracked")} testid="tab-tracked">
              <UserCheck className="h-3.5 w-3.5" /> Utilisateurs suivis ({audience.tracked_users.length})
            </TabBtn>
          </div>
          <div className="relative flex-1 max-w-xs">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher nom, email, téléphone…"
              className="w-full pl-8 pr-3 py-1.5 text-sm rounded-lg border border-slate-300 bg-white"
              data-testid="messaging-search"
            />
          </div>
          <button
            onClick={toggleAllVisible}
            className="text-xs rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-50"
            data-testid="messaging-toggle-all"
          >
            <Filter className="h-3 w-3 inline mr-1" /> Tout sélectionner (avec tél.)
          </button>
        </div>

        {loading ? (
          <div className="text-center text-slate-500 py-10">Chargement…</div>
        ) : filtered.length === 0 ? (
          <div className="text-center text-slate-400 py-10 italic text-sm">Aucun destinataire.</div>
        ) : (
          <div className="max-h-[480px] overflow-y-auto">
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left py-2 px-3 w-8"></th>
                  <th className="text-left py-2 px-3">{tab === "clients" ? "Client" : "Utilisateur"}</th>
                  <th className="text-left py-2 px-3">{tab === "clients" ? "Société" : "Rattaché à"}</th>
                  <th className="text-left py-2 px-3">Email</th>
                  <th className="text-left py-2 px-3">Téléphone</th>
                  <th className="text-left py-2 px-3">Statut</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const key = `${r.kind}:${r.id}`;
                  const on = !!selected[key];
                  return (
                    <tr
                      key={key}
                      className={`border-t border-slate-100 ${on ? "bg-sawali-blue/5" : "hover:bg-slate-50"}`}
                      data-testid={`messaging-row-${r.kind}-${r.id}`}
                    >
                      <td className="py-2 px-3">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggle(r.kind, r.id)}
                          disabled={!r.has_phone}
                          className="accent-sawali-blue disabled:opacity-30"
                          data-testid={`messaging-check-${r.kind}-${r.id}`}
                        />
                      </td>
                      <td className="py-2 px-3">
                        <div className="font-medium text-slate-900">{r.full_name}</div>
                        {r.client_code && <code className="text-[10px] font-mono bg-slate-100 px-1 py-0.5 rounded">{r.client_code}</code>}
                      </td>
                      <td className="py-2 px-3 text-slate-600">{r.company || r.client_label || "—"}</td>
                      <td className="py-2 px-3 text-slate-600">{r.email || "—"}</td>
                      <td className="py-2 px-3">
                        {r.phone ? (
                          <span className="inline-flex items-center gap-1 font-mono text-[11px]">
                            <Phone className="h-3 w-3 text-slate-400" /> {r.phone}
                          </span>
                        ) : (
                          <span className="text-[11px] text-rose-500">Pas de numéro</span>
                        )}
                      </td>
                      <td className="py-2 px-3 text-[11px]">
                        {r.account_status && (
                          <span className={`px-2 py-0.5 rounded ${r.account_status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                            {r.account_status}
                          </span>
                        )}
                        {r.role && (
                          <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 ml-1">{r.role}</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* History */}
      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h3 className="text-sm font-display font-bold">Historique des envois (200 derniers)</h3>
        </div>
        {history.length === 0 ? (
          <div className="text-center text-slate-400 py-10 italic text-sm">Aucun envoi enregistré.</div>
        ) : (
          <div className="max-h-[360px] overflow-y-auto">
            <table className="min-w-full text-xs" data-testid="messaging-history">
              <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="text-left py-2 px-3">Date</th>
                  <th className="text-left py-2 px-3">Destinataire</th>
                  <th className="text-left py-2 px-3">Template</th>
                  <th className="text-left py-2 px-3">Expéditeur</th>
                  <th className="text-left py-2 px-3">Statut</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-t border-slate-100" data-testid={`messaging-history-row-${h.id}`}>
                    <td className="py-1.5 px-3 text-slate-500">
                      {h.created_at ? new Date(h.created_at).toLocaleString("fr-FR") : "—"}
                    </td>
                    <td className="py-1.5 px-3">
                      <div className="text-slate-900">{h.recipient_label || h.to}</div>
                      <div className="text-[10px] font-mono text-slate-400">{h.to}</div>
                    </td>
                    <td className="py-1.5 px-3 font-mono text-[11px]">{h.template_name}</td>
                    <td className="py-1.5 px-3 text-slate-500">{h.sender_label || "—"}</td>
                    <td className="py-1.5 px-3">
                      {h.ok ? (
                        <span className="inline-flex items-center gap-1 text-emerald-700">
                          <CheckCircle2 className="h-3 w-3" /> OK
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-600" title={h.error || ""}>
                          <XCircle className="h-3 w-3" /> {h.status || "KO"}
                        </span>
                      )}
                      {h.bulk && (
                        <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 text-[10px]">
                          <ClockIcon className="h-2.5 w-2.5" /> groupé
                        </span>
                      )}
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

function TabBtn({ active, onClick, children, testid }) {
  return (
    <button
      onClick={onClick}
      data-testid={testid}
      className={`inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-md border transition ${
        active ? "bg-sawali-blue text-white border-sawali-blue" : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
      }`}
    >
      {children}
    </button>
  );
}
