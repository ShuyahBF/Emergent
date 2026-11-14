// pages/officines/Paiement.jsx — Lot 386 : la pharmacie enregistre son code marchand par opérateur et imprime le QR du comptoir.
// Le client scanne le QR, choisit l'opérateur et le montant, et obtient la séquence USSD à composer (page publique /officine/payer/<jeton>).
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Printer, QrCode } from "lucide-react";
import { officineApi } from "@/lib/officineApi";

import { Save as Ico15Save } from "lucide-react";
export default function OfficinePaiement() {
  const [etat, setEtat] = useState(null);          // { operateurs, catalogue, jeton, url_publique }
  const [codes, setCodes] = useState({});          // { "Orange": "123456", … }
  const [qr, setQr] = useState(null);              // URL locale (blob) de l'image du QR
  const [occupe, setOccupe] = useState(false);

  // Charge l'état et l'image du QR (si au moins un code est enregistré)
  const charger = async () => {
    const { data } = await officineApi.get("/officines-portal/me/paiement");
    setEtat(data);
    setCodes(Object.fromEntries((data.operateurs || []).map((o) => [o.operateur, o.code])));
    if (data.jeton && data.operateurs.length) {
      try { const r = await officineApi.get("/officines-portal/me/paiement/qr.png", { responseType: "blob" }); setQr(URL.createObjectURL(r.data)); } catch { setQr(null); }
    } else setQr(null);
  };
  useEffect(() => { charger().catch(() => toast.error("Chargement impossible")); }, []);

  const enregistrer = async () => {
    setOccupe(true);
    try {
      await officineApi.put("/officines-portal/me/paiement", { operateurs: etat.catalogue.map((o) => ({ operateur: o, code: codes[o] || "" })) });
      toast.success("Codes marchands enregistrés");
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); } finally { setOccupe(false); }
  };

  const copier = () => { navigator.clipboard.writeText(etat.url_publique); toast.success("Adresse copiée"); };

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <div className="max-w-3xl space-y-5" data-testid="officine-paiement-page">
      <div>
        <h1 className="font-display text-xl font-bold text-slate-900">Paiement mobile au comptoir</h1>
        <p className="mt-1 text-sm text-slate-600">
          Vos clients scannent un QR code posé au comptoir, choisissent l'opérateur, saisissent le montant et obtiennent la séquence à composer
          (Orange Money, Moov Money, Telecel Money). Aucun paiement ne passe par SAWALI : le client compose la séquence sur son téléphone.
        </p>
      </div>
      <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
        <p className="text-sm font-semibold text-slate-800">Votre code marchand par opérateur</p>
        {etat.catalogue.map((o) => (
          <label key={o} className="flex items-center gap-3 text-sm">
            <span className="w-32 text-slate-700">{o}</span>
            <input value={codes[o] || ""} onChange={(e) => setCodes({ ...codes, [o]: e.target.value })} inputMode="numeric" placeholder="Laisser vide si non utilisé"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2" data-testid={`code-${o}`} />
          </label>
        ))}
        <p className="text-xs text-slate-500">De 3 à 12 chiffres. Le code marchand est celui que l'opérateur vous a remis.</p>
        <button type="button" onClick={enregistrer} disabled={occupe} className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50" data-testid="paiement-enregistrer"><Ico15Save className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Enregistrer</button>
      </div>
      {qr && (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-center" data-testid="paiement-qr">
          <p className="flex items-center justify-center gap-2 text-sm font-semibold text-slate-800"><QrCode className="h-4 w-4" /> QR code du comptoir</p>
          <img src={qr} alt="QR code de paiement" className="mx-auto h-56 w-56" />
          <p className="break-all text-xs text-slate-500">{etat.url_publique}</p>
          <div className="flex justify-center gap-2 print:hidden">
            <button type="button" onClick={() => window.print()} className="inline-flex items-center gap-1 rounded-lg bg-sky-700 px-3 py-2 text-sm font-semibold text-white"><Printer className="h-4 w-4" /> Imprimer</button>
            <button type="button" onClick={copier} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"><Copy className="h-4 w-4" /> Copier l'adresse</button>
          </div>
        </div>
      )}
    </div>
  );
}
