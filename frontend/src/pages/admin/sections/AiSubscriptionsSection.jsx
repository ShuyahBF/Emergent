// Iter38r-fix9u — AI Subscriptions Reminder section for Admin Settings.
// Editable table of external AI/SaaS subscriptions with auto-computed renewal
// date + daily WA + Email reminder dispatch.
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2, Send, Save, X, Wallet, Bell, CalendarClock } from "lucide-react";

const DEFAULT_DRAFT = {
  name: "",
  active: true,
  monthly_cost: 0,
  currency: "USD",
  subscription_date: new Date().toISOString().slice(0, 10),
  period_days: 30,
  reminder_days_before: 5,
  notify_email: "",
  notify_whatsapp: "",
  notes: "",
};

export default function AiSubscriptionsSection() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState(DEFAULT_DRAFT);
  const [editing, setEditing] = useState(null);  // id being edited
  const [showForm, setShowForm] = useState(false);
  const [sendingId, setSendingId] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/admin/ai-subscriptions");
      setItems(r.data?.items || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const startCreate = () => {
    setEditing(null);
    setDraft(DEFAULT_DRAFT);
    setShowForm(true);
  };

  const startEdit = (it) => {
    setEditing(it.id);
    setDraft({
      name: it.name || "",
      active: !!it.active,
      monthly_cost: it.monthly_cost ?? 0,
      currency: it.currency || "USD",
      subscription_date: it.subscription_date,
      period_days: it.period_days || 30,
      reminder_days_before: it.reminder_days_before || 5,
      notify_email: it.notify_email || "",
      notify_whatsapp: it.notify_whatsapp || "",
      notes: it.notes || "",
    });
    setShowForm(true);
  };

  const save = async () => {
    if (!draft.name?.trim() || !draft.subscription_date) {
      toast.error("Nom et date de souscription requis");
      return;
    }
    try {
      if (editing) {
        await apiClient.put(`/admin/ai-subscriptions/${editing}`, draft);
        toast.success("Abonnement mis à jour");
      } else {
        await apiClient.post("/admin/ai-subscriptions", draft);
        toast.success("Abonnement ajouté");
      }
      setShowForm(false);
      setEditing(null);
      setDraft(DEFAULT_DRAFT);
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (id, name) => {
    if (!window.confirm(`Supprimer l'abonnement « ${name} » ?`)) return;
    try {
      await apiClient.delete(`/admin/ai-subscriptions/${id}`);
      toast.success("Supprimé");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const sendNow = async (id, name) => {
    if (!window.confirm(`Envoyer immédiatement un rappel pour « ${name} » ?`)) return;
    setSendingId(id);
    try {
      const r = await apiClient.post(`/admin/ai-subscriptions/${id}/send-reminder`);
      const { email, whatsapp } = r.data?.sent || {};
      const parts = [];
      if (email) parts.push("Email");
      if (whatsapp) parts.push("WhatsApp");
      toast.success(parts.length ? `Envoyé : ${parts.join(" + ")}` : "Aucun canal disponible");
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally { setSendingId(null); }
  };

  const totalMonthly = items
    .filter((i) => i.active)
    .reduce((acc, i) => {
      acc[i.currency || "USD"] = (acc[i.currency || "USD"] || 0) + (i.monthly_cost || 0);
      return acc;
    }, {});

  return (
    <div className="space-y-4" data-testid="ai-subscriptions-section">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex-1">
          <p className="text-xs text-slate-500">
            Suivez vos abonnements externes (Emergent, Claude Haiku PRO, OpenAI, ElevenLabs, fal.ai…).
            Un rappel WhatsApp + Email est envoyé automatiquement chaque matin à 08:00 (Africa/Abidjan)
            quand le renouvellement approche. La date de renouvellement est recalculée chaque mois automatiquement.
          </p>
          {Object.keys(totalMonthly).length > 0 && (
            <p className="text-xs text-emerald-700 mt-2 inline-flex items-center gap-1.5">
              <Wallet className="h-3.5 w-3.5" /> Coût mensuel total (actifs) :
              {Object.entries(totalMonthly).map(([cur, amt]) => (
                <span key={cur} className="ml-2 font-mono font-semibold">
                  {amt.toLocaleString("fr-FR")} {cur}
                </span>
              ))}
            </p>
          )}
        </div>
        <button
          onClick={startCreate}
          className="inline-flex items-center gap-1.5 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-xs hover:bg-sawali-blue-light"
          data-testid="ai-sub-add-btn"
        >
          <Plus className="h-3.5 w-3.5" /> Nouvel abonnement
        </button>
      </div>

      {showForm && (
        <div className="rounded-xl ring-1 ring-fuchsia-300 bg-fuchsia-50/40 p-4 space-y-3" data-testid="ai-sub-form">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">
              {editing ? "Modifier l'abonnement" : "Nouvel abonnement IA"}
            </h3>
            <button onClick={() => { setShowForm(false); setEditing(null); }} className="text-slate-400 hover:text-slate-700">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">Nom de l'outil</span>
              <input
                type="text" value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="Claude Haiku 4.5 PRO"
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                data-testid="ai-sub-name"
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">Date de souscription</span>
              <input
                type="date" value={draft.subscription_date}
                onChange={(e) => setDraft({ ...draft, subscription_date: e.target.value })}
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                data-testid="ai-sub-date"
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">Coût mensuel</span>
              <div className="flex gap-2">
                <input
                  type="number" min="0" step="0.01" value={draft.monthly_cost}
                  onChange={(e) => setDraft({ ...draft, monthly_cost: parseFloat(e.target.value) || 0 })}
                  className="mt-1 flex-1 text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                  data-testid="ai-sub-cost"
                />
                <select
                  value={draft.currency}
                  onChange={(e) => setDraft({ ...draft, currency: e.target.value })}
                  className="mt-1 text-sm rounded-lg ring-1 ring-slate-300 px-2 bg-white"
                  data-testid="ai-sub-currency"
                >
                  <option>USD</option>
                  <option>EUR</option>
                  <option>XOF</option>
                </select>
              </div>
            </label>
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">Durée d'abonnement (jours)</span>
              <input
                type="number" min="1" value={draft.period_days}
                onChange={(e) => setDraft({ ...draft, period_days: parseInt(e.target.value) || 30 })}
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                data-testid="ai-sub-period"
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">Rappel — jours avant échéance</span>
              <input
                type="number" min="0" max="90" value={draft.reminder_days_before}
                onChange={(e) => setDraft({ ...draft, reminder_days_before: parseInt(e.target.value) || 5 })}
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                data-testid="ai-sub-reminder-days"
              />
            </label>
            <label className="inline-flex items-center gap-2 mt-6 cursor-pointer">
              <input
                type="checkbox" checked={draft.active}
                onChange={(e) => setDraft({ ...draft, active: e.target.checked })}
                className="h-4 w-4"
                data-testid="ai-sub-active"
              />
              <span className="text-sm font-semibold text-slate-700">Abonnement actif (surveillé)</span>
            </label>
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">Email pour rappels</span>
              <input
                type="email" value={draft.notify_email}
                onChange={(e) => setDraft({ ...draft, notify_email: e.target.value })}
                placeholder="admin@sawalismartsystems.com"
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
                data-testid="ai-sub-email"
              />
            </label>
            <label className="block">
              <span className="text-[11px] uppercase font-semibold text-slate-500">WhatsApp pour rappels (E.164)</span>
              <input
                type="text" value={draft.notify_whatsapp}
                onChange={(e) => setDraft({ ...draft, notify_whatsapp: e.target.value })}
                placeholder="+22670000000"
                className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white font-mono"
                data-testid="ai-sub-whatsapp"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-[11px] uppercase font-semibold text-slate-500">Notes (optionnel)</span>
            <textarea
              rows={2} value={draft.notes}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
              placeholder="Identifiant compte, URL renouvellement…"
              className="mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white"
              data-testid="ai-sub-notes"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => { setShowForm(false); setEditing(null); }}
              className="text-xs text-slate-600 hover:underline"
            >Annuler</button>
            <button
              onClick={save}
              className="inline-flex items-center gap-1 rounded-lg bg-sawali-blue text-white px-3 py-1.5 text-xs hover:bg-sawali-blue-light"
              data-testid="ai-sub-save"
            >
              <Save className="h-3.5 w-3.5" /> {editing ? "Enregistrer" : "Ajouter"}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-400 italic">Aucun abonnement enregistré. Cliquez sur « Nouvel abonnement » pour commencer.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl ring-1 ring-slate-200 bg-white">
          <table className="w-full text-xs" data-testid="ai-subscriptions-table">
            <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-[10px]">
              <tr>
                <th className="text-left px-3 py-2">Outil</th>
                <th className="text-center px-2 py-2">Actif</th>
                <th className="text-right px-2 py-2">Coût/mois</th>
                <th className="text-left px-2 py-2">Souscription</th>
                <th className="text-right px-2 py-2">Durée</th>
                <th className="text-left px-2 py-2">Prochain renouvellement</th>
                <th className="text-right px-2 py-2">Rappel</th>
                <th className="text-center px-2 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const days = it.days_until_renewal;
                const urgent = days !== null && days !== undefined && days <= (it.reminder_days_before || 5);
                return (
                  <tr
                    key={it.id}
                    className={`border-t border-slate-100 hover:bg-slate-50 ${!it.active ? "opacity-50" : ""}`}
                    data-testid={`ai-sub-row-${it.id}`}
                  >
                    <td className="px-3 py-2">
                      <button onClick={() => startEdit(it)} className="font-semibold text-slate-800 hover:text-sawali-blue text-left">
                        {it.name}
                      </button>
                      {it.notes && <p className="text-[10px] text-slate-400 mt-0.5 truncate max-w-[200px]">{it.notes}</p>}
                    </td>
                    <td className="text-center">
                      {it.active
                        ? <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" title="Actif" />
                        : <span className="inline-block h-2 w-2 rounded-full bg-slate-300" title="Inactif" />}
                    </td>
                    <td className="text-right font-mono tabular-nums">
                      {(it.monthly_cost || 0).toLocaleString("fr-FR")} <span className="text-[10px] text-slate-400">{it.currency}</span>
                    </td>
                    <td className="text-slate-600">{it.subscription_date}</td>
                    <td className="text-right text-slate-500">{it.period_days}j</td>
                    <td className={`px-2 py-2 ${urgent ? "text-rose-700 font-bold" : "text-slate-700"}`}>
                      {it.next_renewal_date || "—"}
                      {days !== null && days !== undefined && (
                        <span className={`ml-1 text-[10px] inline-flex items-center gap-0.5 ${urgent ? "text-rose-600" : "text-slate-400"}`}>
                          <CalendarClock className="h-3 w-3" /> {days} j
                        </span>
                      )}
                    </td>
                    <td className="text-right text-slate-500">{it.reminder_days_before}j avant</td>
                    <td className="px-2 py-2">
                      <div className="flex items-center justify-center gap-1">
                        <button
                          onClick={() => sendNow(it.id, it.name)}
                          disabled={sendingId === it.id || (!it.notify_email && !it.notify_whatsapp)}
                          title={(!it.notify_email && !it.notify_whatsapp) ? "Aucun canal configuré" : "Envoyer un rappel maintenant"}
                          className="rounded p-1 ring-1 ring-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-700 disabled:opacity-30 disabled:cursor-not-allowed"
                          data-testid={`ai-sub-send-${it.id}`}
                        >
                          <Bell className="h-3 w-3" />
                        </button>
                        <button
                          onClick={() => remove(it.id, it.name)}
                          title="Supprimer"
                          className="rounded p-1 ring-1 ring-rose-300 bg-rose-50 hover:bg-rose-100 text-rose-700"
                          data-testid={`ai-sub-delete-${it.id}`}
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
        </div>
      )}
    </div>
  );
}
