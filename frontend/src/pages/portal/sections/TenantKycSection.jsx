/*
 * 2026-02 fork (P0) — KYC section dans /portal/my-account.
 * Permet à chaque tenant de documenter ses données KYC :
 *  - Données Fiscales : IFU, RCCM, adresse, raison sociale, téléphone, coordonnées bancaires
 *  - Uploads : photo d'identité, carte d'identité, papier entête
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import { FileText, Save, Upload, Loader2, ExternalLink, Building2 } from "lucide-react";

const DOC_TYPES = [
  { key: "id_photo", label: "Photo (portrait)", accept: "image/*" },
  { key: "id_card", label: "Pièce d'identité (recto/verso)", accept: "image/*,application/pdf" },
  { key: "letterhead", label: "Papier à en-tête (modèle)", accept: "image/*,application/pdf" },
];

export default function TenantKycSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingKey, setUploadingKey] = useState(null);
  const [form, setForm] = useState({
    business_name: "",
    ifu: "",
    rccm: "",
    address: "",
    phone: "",
    bank_details: "",
  });
  const [urls, setUrls] = useState({ id_photo_url: null, id_card_url: null, letterhead_url: null });
  const fileRefs = useRef({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/kyc");
      const d = r.data || {};
      setForm({
        business_name: d.business_name || "",
        ifu: d.ifu || "",
        rccm: d.rccm || "",
        address: d.address || "",
        phone: d.phone || "",
        bank_details: d.bank_details || "",
      });
      setUrls({
        id_photo_url: d.id_photo_url || null,
        id_card_url: d.id_card_url || null,
        letterhead_url: d.letterhead_url || null,
      });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur chargement KYC");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/me/kyc", form);
      toast.success("Fiche KYC enregistrée");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Erreur");
    } finally { setSaving(false); }
  };

  const onFileSelected = async (docType, e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 3 * 1024 * 1024) {
      toast.error(`Fichier trop volumineux (max 3 MB, actuel : ${(f.size / 1024 / 1024).toFixed(1)} MB)`);
      return;
    }
    setUploadingKey(docType);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await apiClient.post(`/me/kyc/upload/${docType}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUrls((u) => ({ ...u, [`${docType}_url`]: r.data?.url || null }));
      toast.success(`${docType} enregistré (${Math.round((r.data?.size || 0) / 1024)} KB)`);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur upload");
    } finally { setUploadingKey(null); }
  };

  return (
    <section
      className="rounded-xl ring-1 ring-indigo-200 bg-indigo-50/40 p-5 space-y-4"
      data-testid="tenant-kyc-section"
    >
      <h2 className="font-display font-semibold text-sm text-indigo-800 flex items-center gap-2">
        <Building2 className="h-4 w-4" /> Fiche KYC (Données fiscales & documents)
      </h2>

      {loading ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</div>
      ) : (
        <>
          {/* Text fields */}
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Raison sociale" value={form.business_name} onChange={(v) => setForm((f) => ({ ...f, business_name: v }))} testid="kyc-business-name" />
            <Field label="IFU (n° d'identifiant fiscal)" value={form.ifu} onChange={(v) => setForm((f) => ({ ...f, ifu: v }))} testid="kyc-ifu" />
            <Field label="RCCM" value={form.rccm} onChange={(v) => setForm((f) => ({ ...f, rccm: v }))} testid="kyc-rccm" />
            <Field label="Téléphone" value={form.phone} onChange={(v) => setForm((f) => ({ ...f, phone: v }))} testid="kyc-phone" />
            <Field label="Adresse géographique" value={form.address} onChange={(v) => setForm((f) => ({ ...f, address: v }))} testid="kyc-address" className="sm:col-span-2" />
            <Field label="Coordonnées bancaires" value={form.bank_details} onChange={(v) => setForm((f) => ({ ...f, bank_details: v }))} testid="kyc-bank" className="sm:col-span-2" multiline />
          </div>
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 text-sm disabled:opacity-50"
            data-testid="kyc-save-btn"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Enregistrer les données
          </button>

          {/* Uploads */}
          <div className="pt-3 border-t border-indigo-200 space-y-2">
            <div className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Documents (max 3 MB, PDF ou image)</div>
            {DOC_TYPES.map((dt) => {
              const url = urls[`${dt.key}_url`];
              const busy = uploadingKey === dt.key;
              return (
                <div key={dt.key} className="flex items-center gap-2 rounded-lg bg-white ring-1 ring-slate-200 p-2">
                  <FileText className="h-4 w-4 text-indigo-500 shrink-0" />
                  <span className="text-sm text-slate-700 flex-1 min-w-0 truncate">{dt.label}</span>
                  {url && (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-indigo-600 hover:underline flex items-center gap-0.5"
                      data-testid={`kyc-view-${dt.key}`}
                    >
                      Voir <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                  <input
                    ref={(el) => { fileRefs.current[dt.key] = el; }}
                    type="file"
                    accept={dt.accept}
                    onChange={(e) => onFileSelected(dt.key, e)}
                    className="hidden"
                    data-testid={`kyc-file-${dt.key}`}
                  />
                  <button
                    type="button"
                    onClick={() => fileRefs.current[dt.key]?.click()}
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded-lg bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-2 py-1 text-xs disabled:opacity-50"
                    data-testid={`kyc-upload-${dt.key}`}
                  >
                    {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                    {busy ? "Envoi…" : (url ? "Remplacer" : "Choisir")}
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}

function Field({ label, value, onChange, testid, className = "", multiline = false }) {
  const Cmp = multiline ? "textarea" : "input";
  return (
    <label className={`block ${className}`}>
      <span className="text-xs font-semibold text-slate-700">{label}</span>
      <Cmp
        type={multiline ? undefined : "text"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={multiline ? 2 : undefined}
        className="mt-1 w-full px-2 py-1.5 rounded-lg border border-slate-300 text-sm"
        data-testid={testid}
      />
    </label>
  );
}
