// Iter42b (2026-02) — Section AdminSettings : Templates OTP (WhatsApp)
//
// Centralise les paramètres des templates WhatsApp utilisés pour l'envoi
// des codes OTP. Deux templates sont gérés :
//   • Login WhatsApp général (`wa_otp_template`) — existant
//   • Login Officines self-service (`officine_otp_template`) — nouveau Iter42b
//
// Chaque template peut être testé avec un numéro de destination pour vérifier
// l'approbation Meta et la catégorie (Authentication vs Utility).
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { Loader2, Save, Send, MessageCircle, Smartphone, CheckCircle2, AlertTriangle } from "lucide-react";

export default function TemplatesOtpSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({});

  // Test states (séparés par template)
  const [testMsisdn, setTestMsisdn] = useState({ wa_otp: "", officine_otp: "" });
  const [testBusy, setTestBusy] = useState({ wa_otp: false, officine_otp: false });
  const [testResult, setTestResult] = useState({ wa_otp: null, officine_otp: null });

  useEffect(() => {
    (async () => {
      try {
        const r = await apiClient.get("/admin/settings");
        setForm(r.data || {});
      } catch {
        toast.error("Erreur chargement");
      } finally { setLoading(false); }
    })();
  }, []);

  const upd = (k, v) => setForm((s) => ({ ...s, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const out = {
        // Template login WA général
        wa_otp_template: form.wa_otp_template || "",
        wa_otp_template_lang: form.wa_otp_template_lang || "fr",
        // Template login Officines self-service
        officine_otp_template: form.officine_otp_template || "",
        officine_otp_template_lang: form.officine_otp_template_lang || "fr",
      };
      await apiClient.put("/admin/settings", out);
      toast.success("Templates OTP enregistrés");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const testTemplate = async (kind) => {
    const msisdn = (testMsisdn[kind] || "").replace(/\D/g, "");
    if (msisdn.length < 8) {
      toast.error("Numéro invalide (E.164 sans le +)");
      return;
    }
    setTestBusy((s) => ({ ...s, [kind]: true }));
    setTestResult((s) => ({ ...s, [kind]: null }));
    try {
      const endpoint = kind === "wa_otp"
        ? "/admin/wa-otp/test"
        : "/admin/officine-otp/test";
      const r = await apiClient.post(endpoint, { msisdn });
      setTestResult((s) => ({ ...s, [kind]: r.data }));
      if (r.data?.ok) toast.success(`Envoyé via ${r.data.sent_via}`);
      else toast.error("Échec — voir le détail");
    } catch (e) {
      setTestResult((s) => ({ ...s, [kind]: { ok: false, error: e?.response?.data?.detail || String(e).slice(0, 200) } }));
      toast.error(e?.response?.data?.detail || "Erreur réseau");
    } finally {
      setTestBusy((s) => ({ ...s, [kind]: false }));
    }
  };

  if (loading) return (
    <div className="flex items-center gap-2 text-sm text-slate-600 py-4">
      <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
    </div>
  );

  return (
    <div className="space-y-5" data-testid="templates-otp-section">
      <div className="bg-amber-50 ring-1 ring-amber-200 rounded-lg p-3 text-xs text-amber-900">
        <p className="font-medium inline-flex items-center gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5" /> Pré-requis
        </p>
        <ul className="mt-1 list-disc list-inside space-y-0.5">
          <li>Les templates doivent être <strong>approuvés par Meta</strong> dans WhatsApp Business Manager.</li>
          <li>Catégorie recommandée : <strong>Authentication</strong> (avec bouton COPY_CODE). À défaut, Utility avec un paramètre body texte.</li>
          <li>Le langage doit utiliser un code BCP-47 (ex: <code>fr</code>, <code>fr_FR</code>, <code>en</code>, <code>en_US</code>).</li>
        </ul>
      </div>

      {/* === Template Login WA général === */}
      <TemplateCard
        title="Login WhatsApp général"
        subtitle="Utilisé pour le login OTP via le portail principal (clients, admins, etc.)"
        nameKey="wa_otp_template"
        langKey="wa_otp_template_lang"
        categoryKey="wa_otp_template_category"
        kind="wa_otp"
        form={form}
        upd={upd}
        testMsisdn={testMsisdn.wa_otp}
        setTestMsisdn={(v) => setTestMsisdn((s) => ({ ...s, wa_otp: v }))}
        testBusy={testBusy.wa_otp}
        testResult={testResult.wa_otp}
        onTest={() => testTemplate("wa_otp")}
        color="sky"
      />

      {/* === Template Login Officines === */}
      <TemplateCard
        title="Login Officines (self-service)"
        subtitle="Utilisé pour le login OTP des pharmacies inscrites au portail /officines"
        nameKey="officine_otp_template"
        langKey="officine_otp_template_lang"
        categoryKey="officine_otp_template_category"
        kind="officine_otp"
        form={form}
        upd={upd}
        testMsisdn={testMsisdn.officine_otp}
        setTestMsisdn={(v) => setTestMsisdn((s) => ({ ...s, officine_otp: v }))}
        testBusy={testBusy.officine_otp}
        testResult={testResult.officine_otp}
        onTest={() => testTemplate("officine_otp")}
        color="emerald"
      />

      <div className="sticky bottom-0 bg-white border-t border-slate-200 -mx-4 -mb-4 px-4 py-3 flex justify-end">
        <button onClick={save} disabled={saving}
                className="text-sm px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white inline-flex items-center gap-2 disabled:opacity-60"
                data-testid="templates-otp-save-btn">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Enregistrer les templates
        </button>
      </div>
    </div>
  );
}

function TemplateCard({
  title, subtitle, nameKey, langKey, categoryKey, kind, color,
  form, upd, testMsisdn, setTestMsisdn, testBusy, testResult, onTest,
}) {
  const tone = {
    sky: "bg-sky-100 text-sky-700",
    emerald: "bg-emerald-100 text-emerald-700",
  }[color];
  const Icon = kind === "wa_otp" ? Smartphone : MessageCircle;
  return (
    <div className="ring-1 ring-slate-200 rounded-lg p-4 bg-white space-y-3" data-testid={`template-${kind}-card`}>
      <div className="flex items-start gap-3">
        <div className={`h-10 w-10 rounded-xl flex items-center justify-center ${tone}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <h3 className="font-semibold text-slate-900">{title}</h3>
          <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>
        </div>
        {form[categoryKey] && (
          <span className="text-[10px] uppercase tracking-wider font-medium px-2 py-1 rounded bg-slate-100 text-slate-600 ring-1 ring-slate-200 self-start">
            Catégorie : {form[categoryKey]}
          </span>
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Nom du template Meta</span>
          <input value={form[nameKey] || ""} onChange={(e) => upd(nameKey, e.target.value)}
                 placeholder="ex: officine_login_otp" className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                 data-testid={`template-${kind}-name`} />
        </label>
        <label className="block text-xs">
          <span className="block text-slate-600 mb-1">Langue (BCP-47)</span>
          <input value={form[langKey] || ""} onChange={(e) => upd(langKey, e.target.value)}
                 placeholder="fr" className="w-full text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                 data-testid={`template-${kind}-lang`} />
        </label>
      </div>
      <div className="border-t pt-3 space-y-2">
        <p className="text-xs font-medium text-slate-700">Tester l&apos;envoi</p>
        <div className="flex items-center gap-2">
          <input value={testMsisdn} onChange={(e) => setTestMsisdn(e.target.value)}
                 placeholder="22501234567 (sans +)" className="flex-1 text-xs px-2 py-1.5 rounded ring-1 ring-slate-300 font-mono"
                 data-testid={`template-${kind}-test-msisdn`} />
          <button onClick={onTest} disabled={testBusy}
                  className={`text-xs px-3 py-1.5 rounded ring-1 inline-flex items-center gap-1 disabled:opacity-60 ${
                    color === "sky"
                      ? "ring-sky-300 text-sky-700 hover:bg-sky-50"
                      : "ring-emerald-300 text-emerald-700 hover:bg-emerald-50"
                  }`}
                  data-testid={`template-${kind}-test-btn`}>
            {testBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />} Envoyer un OTP test
          </button>
        </div>
        {testResult && (
          <div className={`text-xs rounded p-2 ${testResult.ok ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200" : "bg-rose-50 text-rose-800 ring-1 ring-rose-200"}`} data-testid={`template-${kind}-test-result`}>
            {testResult.ok ? (
              <div className="flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Envoyé via <strong>{testResult.sent_via}</strong></span>
                {testResult.test_code && <span className="ml-2 font-mono text-[10px] text-slate-500">(code de test affiché côté serveur)</span>}
              </div>
            ) : (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  <span>Échec</span>
                </div>
                {testResult.error && <p className="ml-5 text-[11px]">{testResult.error}</p>}
                {testResult.hint && <p className="ml-5 text-[11px] italic">{testResult.hint}</p>}
                {testResult.attempts && testResult.attempts.length > 0 && (
                  <details className="ml-5">
                    <summary className="text-[11px] cursor-pointer hover:underline">Détail des tentatives</summary>
                    <pre className="mt-1 bg-white ring-1 ring-rose-200 rounded p-2 text-[10px] overflow-x-auto">{JSON.stringify(testResult.attempts, null, 2)}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
