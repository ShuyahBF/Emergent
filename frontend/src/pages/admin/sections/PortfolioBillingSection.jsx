/*
  PortfolioBillingSection — lot 27 : facturation du portefeuille
  « Formulaires & Sondages WhatsApp » d'un client, dans sa page SMART Communications.

  1. Tarifs (FCFA HT) : forfait mensuel, formulaire actif, sondage actif,
     message WhatsApp envoyé, réponse de sondage, réponse de formulaire,
     bilan avec analyse IA ; TVA ; échéance ; mention sur la facture.
  2. Prompt de l'analyse IA (vide = prompt par défaut, affiché).
  3. Bilans de période : « Mois dernier », « Ce mois-ci » ou dates au choix,
     avec ou sans analyse IA. Chaque bilan montre les chiffres, l'analyse et
     les lignes de facture ; boutons PDF, lien pour le client, Créer la facture
     (ou une proforma), Supprimer.
  Props : clientId, clientLabel
*/
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import InvoiceTvaDialog from "@/components/InvoiceTvaDialog";
import { Receipt, Save, Sparkles, FileText, Loader2, Link2, Trash2, RotateCcw, ChevronDown, ChevronUp } from "lucide-react";

const money = (v) => `${Math.round(v || 0).toLocaleString("fr-FR")} FCFA`;
const iso = (d) => d.toISOString().slice(0, 10);
// Périodes rapides : mois précédent et mois en cours
const lastMonth = () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth() - 1, 1, 12)), iso(new Date(n.getFullYear(), n.getMonth(), 0, 12))]; };
const thisMonth = () => { const n = new Date(); return [iso(new Date(n.getFullYear(), n.getMonth(), 1, 12)), iso(n)]; };

// Analyse IA : titres « ## », puces « - », gras « **…** » mis en forme
function Analysis({ text }) {
  const bold = (t) => t.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part));
  return (
    <div className="rounded-lg bg-fuchsia-50/50 ring-1 ring-fuchsia-100 p-3 text-slate-800 text-[13px] leading-relaxed space-y-1" data-testid="pb-analysis">
      {text.split("\n").map((raw, i) => {
        const t = raw.trim();
        if (!t) return null;
        if (t.startsWith("#")) return <p key={i} className="pt-1 font-semibold text-fuchsia-800">{bold(t.replace(/^#+\s*/, ""))}</p>;
        if (/^[-*•]\s/.test(t)) return <p key={i} className="pl-4 relative before:content-['•'] before:absolute before:left-1 before:text-fuchsia-500">{bold(t.slice(2))}</p>;
        return <p key={i}>{bold(t)}</p>;
      })}
    </div>
  );
}

export default function PortfolioBillingSection({ clientId, clientLabel }) {
  const [cfg, setCfg] = useState(null);
  const [tariffs, setTariffs] = useState([]);
  const [defaultPrompt, setDefaultPrompt] = useState("");
  const [saving, setSaving] = useState(false);
  const [reports, setReports] = useState([]);
  const [open, setOpen] = useState(null);           // bilan déplié (détail complet)
  const [[from, to], setPeriod] = useState(lastMonth());
  const [withAi, setWithAi] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [invoiceFor, setInvoiceFor] = useState(null);  // {report, kind} : choix de la TVA puis facture

  const load = async () => {
    try {
      const [b, r] = await Promise.all([
        apiClient.get(`/admin/clients/${clientId}/portfolio-billing`),
        apiClient.get(`/admin/clients/${clientId}/portfolio-reports`),
      ]);
      setCfg(b.data.settings); setTariffs(b.data.tariffs || []); setDefaultPrompt(b.data.default_prompt || "");
      setReports(r.data.items || []);
    } catch { setCfg(null); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [clientId]);

  const set = (patch) => setCfg((c) => ({ ...c, ...patch }));
  const save = async () => {
    setSaving(true);
    try {
      const r = await apiClient.put(`/admin/clients/${clientId}/portfolio-billing`, cfg);
      setCfg(r.data.settings); toast.success("Tarifs et prompt enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Erreur"); } finally { setSaving(false); }
  };

  const generate = async () => {
    setGenerating(true);
    try {
      const r = await apiClient.post(`/admin/clients/${clientId}/portfolio-reports`, { date_from: from, date_to: to, with_ai: withAi });
      if (r.data.ai_error) toast.warning(`Bilan créé sans analyse IA : ${r.data.ai_error}`);
      else toast.success("Bilan généré");
      setOpen(r.data); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Génération impossible"); } finally { setGenerating(false); }
  };

  const openReport = async (rep) => {
    if (open?.id === rep.id) { setOpen(null); return; }
    try { setOpen((await apiClient.get(`/admin/portfolio-reports/${rep.id}`)).data); } catch { toast.error("Bilan introuvable"); }
  };
  const pdf = async (rep) => {
    try {
      const r = await apiClient.get(`/admin/portfolio-reports/${rep.id}/pdf`, { responseType: "blob" });
      window.open(URL.createObjectURL(r.data), "_blank");
    } catch { toast.error("PDF indisponible"); }
  };
  const copyLink = async (rep) => {
    const url = `${rep.base_url || window.location.origin}/api/public/portfolio-report/${rep.token}`;
    try { await navigator.clipboard.writeText(url); toast.success("Lien du bilan copié : transmettez-le au client"); }
    catch { window.prompt("Lien du bilan à transmettre au client :", url); }
  };
  // Facture : fenêtre de choix de la TVA (appliquée ou non pour cette facture)
  const invoice = (rep, kind) => setInvoiceFor({ report: { ...rep, client_name: rep.client_name || clientLabel }, kind });
  const invoiced = (res) => {
    const rep = invoiceFor.report;
    setInvoiceFor(null); load();
    if (open?.id === rep.id && invoiceFor.kind === "invoice") setOpen((o) => ({ ...o, invoice_number: res.invoice.number }));
  };
  const remove = async (rep) => {
    if (!window.confirm("Supprimer ce bilan ? (la facture éventuelle reste dans la Caisse)")) return;
    await apiClient.delete(`/admin/portfolio-reports/${rep.id}`); if (open?.id === rep.id) setOpen(null); load();
  };

  if (!cfg) return null;
  const input = "mt-1 w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2 bg-white";
  return (
    <div className="rounded-2xl ring-1 ring-indigo-200 bg-indigo-50/40 p-5 space-y-4" data-testid="portfolio-billing-section">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-xl bg-indigo-100 flex items-center justify-center"><Receipt className="h-5 w-5 text-indigo-600" /></div>
        <div className="flex-1">
          <h3 className="font-display font-semibold text-slate-900">Facturation — Formulaires & Sondages WhatsApp</h3>
          <p className="text-xs text-slate-500 mt-1">
            Tarifs appliqués à ce client en fin de période, et prompt de l'analyse IA de son bilan. Formulaire actif = au moins une
            réponse dans la période ; sondage actif = au moins un envoi ou une réponse ; message = invitation ou relance envoyée.
          </p>
        </div>
        <label className="inline-flex items-center gap-2 text-xs text-slate-700">
          <input type="checkbox" checked={!!cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} data-testid="pb-enabled" /> Facturation active
        </label>
      </div>

      {/* Tarifs */}
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {tariffs.map((t) => (
          <label key={t.key} className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            {t.label.split(" — ")[0]} <span className="normal-case font-normal">(FCFA HT / {t.unit})</span>
            <input type="number" min="0" step="1" value={cfg[t.key] ?? 0} data-testid={`pb-${t.key}`}
              onChange={(e) => set({ [t.key]: e.target.value === "" ? 0 : Number(e.target.value) })} className={input} />
          </label>
        ))}
        <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500">TVA (%)
          <input type="number" min="0" max="100" value={cfg.tva_pct ?? 18} onChange={(e) => set({ tva_pct: Number(e.target.value) })} className={input} />
        </label>
        <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500">Échéance (jours)
          <input type="number" min="0" max="180" value={cfg.due_days ?? 15} onChange={(e) => set({ due_days: Number(e.target.value) })} className={input} />
        </label>
        <label className="block sm:col-span-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">Mention sur la facture (facultatif)
          <input value={cfg.invoice_notes || ""} onChange={(e) => set({ invoice_notes: e.target.value })} className={input} maxLength={1000} />
        </label>
      </div>

      {/* Prompt IA */}
      <div className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
        <button type="button" onClick={() => setShowPrompt(!showPrompt)} className="w-full flex items-center justify-between text-sm font-semibold text-slate-800">
          <span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-fuchsia-500" /> Prompt de l'analyse IA {cfg.ai_prompt ? "(personnalisé)" : "(par défaut)"}</span>
          {showPrompt ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {showPrompt && (
          <div className="mt-2 space-y-2">
            <textarea rows={6} value={cfg.ai_prompt ?? ""} placeholder={defaultPrompt} data-testid="pb-prompt"
              onChange={(e) => set({ ai_prompt: e.target.value })} className="w-full text-sm rounded-lg ring-1 ring-slate-300 px-3 py-2" maxLength={6000} />
            <div className="flex flex-wrap gap-3 text-xs">
              <button type="button" onClick={() => set({ ai_prompt: defaultPrompt })} className="text-indigo-700 hover:underline">Partir du prompt par défaut</button>
              <button type="button" onClick={() => set({ ai_prompt: "" })} className="inline-flex items-center gap-1 text-slate-600 hover:underline"><RotateCcw className="h-3 w-3" /> Revenir au prompt par défaut</button>
              <span className="text-slate-400">L'IA reçoit les chiffres de la période et les commentaires, jamais les numéros de téléphone.</span>
            </div>
          </div>
        )}
      </div>
      <button onClick={save} disabled={saving} data-testid="pb-save"
        className="inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60">
        <Save className="h-4 w-4" /> {saving ? "Enregistrement…" : "Enregistrer les tarifs et le prompt"}
      </button>

      {/* Bilans */}
      <div className="border-t border-indigo-100 pt-4 space-y-3">
        <p className="text-sm font-semibold text-slate-800">Bilans de période</p>
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <button onClick={() => setPeriod(lastMonth())} className="rounded-full ring-1 ring-slate-300 bg-white px-3 py-1 text-xs hover:ring-indigo-400">Mois dernier</button>
          <button onClick={() => setPeriod(thisMonth())} className="rounded-full ring-1 ring-slate-300 bg-white px-3 py-1 text-xs hover:ring-indigo-400">Ce mois-ci</button>
          <label className="text-xs text-slate-600">Du <input type="date" value={from} onChange={(e) => setPeriod([e.target.value, to])} className="ml-1 rounded-lg ring-1 ring-slate-300 px-2 py-1" data-testid="pb-from" /></label>
          <label className="text-xs text-slate-600">au <input type="date" value={to} onChange={(e) => setPeriod([from, e.target.value])} className="ml-1 rounded-lg ring-1 ring-slate-300 px-2 py-1" data-testid="pb-to" /></label>
          <label className="inline-flex items-center gap-1.5 text-xs text-slate-700"><input type="checkbox" checked={withAi} onChange={(e) => setWithAi(e.target.checked)} /> Analyse IA</label>
          <button onClick={generate} disabled={generating} data-testid="pb-generate"
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 text-white px-3 py-1.5 text-sm hover:bg-slate-800 disabled:opacity-50">
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Générer le bilan
          </button>
        </div>

        {reports.map((rep) => {
          const detail = open?.id === rep.id ? open : null;
          return (
            <div key={rep.id} className="rounded-xl bg-white ring-1 ring-slate-200" data-testid={`pb-report-${rep.id}`}>
              <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                <button onClick={() => openReport(rep)} className="flex-1 min-w-[12rem] text-left">
                  <p className="text-sm font-semibold text-slate-900">
                    Du {new Date(rep.date_from).toLocaleDateString("fr-FR")} au {new Date(rep.date_to).toLocaleDateString("fr-FR")}
                    {rep.with_ai && <Sparkles className="inline h-3.5 w-3.5 ml-1 text-fuchsia-500" />}
                  </p>
                  <p className="text-[11px] text-slate-500">
                    {rep.invoice_number
                      ? <>facturé {money(rep.invoiced_amount ?? rep.total_ttc)} {rep.invoiced_with_tva === false ? "(sans TVA)" : "(TVA incluse)"}</>
                      : <>{money(rep.total_ht)} HT · {money(rep.total_ttc)} avec TVA</>} · créé le {new Date(rep.created_at).toLocaleDateString("fr-FR")}
                    {rep.invoice_number && <> · <span className="text-emerald-700 font-medium">facture {rep.invoice_number}</span></>}</p>
                </button>
                <button onClick={() => pdf(rep)} className="inline-flex items-center gap-1 text-xs rounded ring-1 ring-slate-300 px-2 py-1 hover:bg-slate-50" data-testid="pb-pdf"><FileText className="h-3.5 w-3.5" /> PDF</button>
                <button onClick={() => copyLink(rep)} className="inline-flex items-center gap-1 text-xs rounded ring-1 ring-slate-300 px-2 py-1 hover:bg-slate-50"><Link2 className="h-3.5 w-3.5" /> Lien client</button>
                {!rep.invoice_number ? (
                  <button onClick={() => invoice(rep, "invoice")} disabled={!rep.total_ttc} data-testid="pb-invoice"
                    className="inline-flex items-center gap-1 text-xs rounded bg-emerald-600 text-white px-2 py-1 hover:bg-emerald-700 disabled:opacity-40"><Receipt className="h-3.5 w-3.5" /> Créer la facture</button>
                ) : (
                  <Link to="/portal/billing" className="text-xs text-emerald-700 hover:underline">Voir dans la Caisse</Link>
                )}
                <button onClick={() => invoice(rep, "proforma")} disabled={!rep.total_ttc} className="text-xs text-slate-600 hover:underline disabled:opacity-40">Proforma</button>
                <button onClick={() => remove(rep)} className="p-1 text-slate-400 hover:text-rose-600" title="Supprimer"><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
              {detail && (
                <div className="border-t border-slate-100 p-3 space-y-3 text-sm" data-testid="pb-report-detail">
                  <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center">
                    {[["Sondages actifs", detail.metrics.surveys.active], ["Messages", detail.metrics.surveys.messages_sent],
                      ["Réponses sondages", detail.metrics.surveys.responses],
                      ["Taux", detail.metrics.surveys.response_rate == null ? "—" : `${detail.metrics.surveys.response_rate} %`],
                      ["Formulaires actifs", detail.metrics.forms.active], ["Réponses formulaires", detail.metrics.forms.submissions]].map(([l, v]) => (
                      <div key={l} className="rounded-lg bg-slate-50 py-2"><p className="text-lg font-bold text-indigo-700 tabular-nums">{v}</p><p className="text-[10px] text-slate-500">{l}</p></div>
                    ))}
                  </div>
                  {detail.ai_error && <p className="text-xs text-amber-700">Analyse IA non disponible : {detail.ai_error}</p>}
                  {detail.analysis && <Analysis text={detail.analysis} />}
                  {detail.lines.length ? (
                    <table className="w-full text-xs">
                      <thead className="text-[10px] uppercase text-slate-500"><tr><th className="text-left">Désignation</th><th className="text-right">Qté</th><th className="text-right">PU HT</th><th className="text-right">Total HT</th></tr></thead>
                      <tbody>
                        {detail.lines.map((ln) => (
                          <tr key={ln.key} className="border-t border-slate-100"><td className="py-1">{ln.label}</td><td className="text-right">{ln.quantity}</td>
                            <td className="text-right">{money(ln.unit_price_ht)}</td><td className="text-right">{money(ln.total_ht)}</td></tr>
                        ))}
                        <tr className="border-t border-slate-200"><td colSpan={3} className="text-right py-1">Total HT</td><td className="text-right">{money(detail.total_ht)}</td></tr>
                        <tr><td colSpan={3} className="text-right">TVA {detail.tva_pct} %</td><td className="text-right">{money(detail.total_tva)}</td></tr>
                        <tr className="font-bold"><td colSpan={3} className="text-right">Total TTC</td><td className="text-right">{money(detail.total_ttc)}</td></tr>
                      </tbody>
                    </table>
                  ) : <p className="text-xs text-slate-500">Aucun tarif ne s'applique à cette période (réglez les tarifs ci-dessus puis régénérez).</p>}
                </div>
              )}
            </div>
          );
        })}
        {!reports.length && <p className="text-xs text-slate-500">Aucun bilan pour l'instant.</p>}
        {invoiceFor && <InvoiceTvaDialog report={invoiceFor.report} kind={invoiceFor.kind} onClose={() => setInvoiceFor(null)} onDone={invoiced} />}
      </div>
    </div>
  );
}
