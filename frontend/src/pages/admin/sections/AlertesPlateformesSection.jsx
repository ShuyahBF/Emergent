// AlertesPlateformesSection.jsx — Lots 352 et 354 : alertes des plateformes (Meta/WhatsApp) et HISTORIQUE PAR LIGNE (ID du numéro de téléphone)
// imprimable en PDF.
// Réservé à l'administrateur (les autres comptes reçoivent 403 et voient un message).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

const bouton = "text-xs font-semibold px-3 py-1.5 rounded-md bg-blue-700 text-white hover:bg-blue-800 disabled:opacity-50";
const quand = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

export default function AlertesPlateformesSection() {
  const [alertes, setAlertes] = useState(null);
  const [histo, setHisto] = useState(null);
  const [jours, setJours] = useState(30);
  const [occupe, setOccupe] = useState(false);
  const [refuse, setRefuse] = useState(false);

  const charger = useCallback(async (nbJours) => {
    try {
      const [a, h] = await Promise.all([
        apiClient.get("/admin/alertes-plateformes"),
        apiClient.get("/admin/alertes-plateformes/historique", { params: { jours: nbJours } }),
      ]);
      setAlertes(a.data);
      setHisto(h.data);
    } catch (err) {
      if (err?.response?.status === 403) setRefuse(true);
      else toast.error("Alertes indisponibles");
    }
  }, []);
  useEffect(() => { charger(30); }, [charger]);

  if (refuse) return <p className="text-xs text-slate-600">Cette rubrique est réservée à l'administrateur.</p>;
  if (!alertes || !histo) return <p className="text-xs text-slate-500">Patientez…</p>;

  // Contrôle immédiat des échecs d'envoi récents
  const verifier = async () => {
    setOccupe(true);
    try { await apiClient.post("/admin/alertes-plateformes/verifier"); await charger(jours); toast.success("Contrôle effectué"); }
    catch { toast.error("Contrôle impossible"); } finally { setOccupe(false); }
  };
  const regler = async (cle) => {
    try { await apiClient.post(`/admin/alertes-plateformes/${encodeURIComponent(cle)}/regle`); await charger(jours); }
    catch { toast.error("Impossible de fermer l'alerte"); }
  };
  // PDF : ouvert dans un nouvel onglet (impression depuis le lecteur du navigateur)
  const pdf = async (ligne, type = "historique") => {   // type : « historique » (échecs, alertes) ou « envois » (envois réussis + coût estimé)
    try {
      const r = await apiClient.get(`/admin/alertes-plateformes/${type}.pdf`, { params: { jours, ligne: ligne || undefined }, responseType: "blob" });
      window.open(URL.createObjectURL(new Blob([r.data], { type: "application/pdf" })), "_blank");
    } catch { toast.error("PDF indisponible"); }
  };

  return (
    <div className="space-y-4" data-testid="alertes-plateformes">
      <p className="text-xs text-slate-600">
        SAWALI surveille les échecs d'envoi WhatsApp qui bloquent tout le compte (moyen de paiement Meta, compte restreint, jeton expiré…).
        L'administrateur reçoit un e-mail (WhatsApp est alors en panne), un bandeau rouge sur les pages d'administration, et l'alerte se ferme
        toute seule quand les envois reprennent.
      </p>

      <div>
        <h4 className="text-sm font-semibold mb-1">Alertes en cours ({alertes.ouvertes.length})</h4>
        {alertes.ouvertes.length === 0 && <p className="text-xs text-green-700">Aucune alerte : les envois fonctionnent.</p>}
        {alertes.ouvertes.map((a) => (
          <div key={a.cle} className="rounded-md border border-red-200 bg-red-50 p-2 text-xs mb-1">
            <div className="font-semibold">{a.titre} <span className="font-normal text-slate-600">· WABA {a.waba_id || "—"} · code {a.code} · {a.nombre} échec(s) · depuis {quand(a.depuis)}</span></div>
            <div>Que faire : {a.action}</div>
            {/* Lot 355 : lien direct vers Meta pour régler le problème, placé juste avant « fermer » (paiement : réglages de paiement du compte WABA) */}
            <a className="inline-block mt-1 mr-3 font-semibold text-blue-700 underline" target="_blank" rel="noopener noreferrer"
               href={String(a.code) === "131042"
                 ? `https://business.facebook.com/billing_hub/payment_settings?asset_id=${a.waba_id || ""}`
                 : `https://business.facebook.com/wa/manage/home/?waba_id=${a.waba_id || ""}`}>
              {String(a.code) === "131042" ? "Régler le paiement sur Meta ↗" : "Ouvrir WhatsApp Manager ↗"}
            </a>
            <button type="button" className="underline mt-1" onClick={() => regler(a.cle)}>C'est réglé (fermer)</button>
          </div>
        ))}
        <button type="button" className={bouton} onClick={verifier} disabled={occupe} data-testid="alertes-verifier">Vérifier maintenant</button>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="text-sm font-semibold">Historique par ligne (ID du numéro de téléphone)</h4>
          <label className="text-xs flex items-center gap-1">sur
            <input type="number" min={1} max={365} className="w-16 rounded-md border border-slate-300 px-2 py-1" value={jours} onChange={(e) => setJours(e.target.value)} />
            jours</label>
          <button type="button" className={bouton} onClick={() => charger(jours)}>Actualiser</button>
          <button type="button" className={bouton} onClick={() => pdf(null)} data-testid="alertes-pdf-tous">PDF des échecs de toutes les lignes</button>
        </div>
        {histo.waba_id && <p className="text-xs text-slate-600">Compte WhatsApp Business (WABA) : <strong className="font-mono">{histo.waba_id}</strong> — le moyen de paiement se règle pour tout le compte, donc une alerte de paiement touche toutes les lignes.</p>}
        {histo.lignes.map((w) => (
          <div key={w.cle} className="rounded-xl border border-slate-200 p-2 text-xs space-y-1" data-testid={`ligne-${w.cle}`}>
            <div className="flex flex-wrap items-center gap-2">
              <strong className="text-sm">{w.libelle}{w.principale ? " (principale)" : ""}</strong>
              <span className="text-slate-600">{w.telephone || ""} · ID du numéro : <span className="font-mono">{w.phone_number_id || "—"}</span></span>
              <span>· {w.envois} envois · {w.echecs} échec(s){w.envois ? <span title="Taux d'échec = échecs ÷ envois sur la période"> (taux d'échec {(100 * w.echecs / w.envois).toFixed(1)} %)</span> : ""}</span>
              <button type="button" className={bouton} onClick={() => pdf(w.cle)}>Imprimer Échecs en PDF</button>
              {/* Lot 355 : impression des seuls ENVOIS de cette ligne, avec le coût estimé (coût par message de la fiche du client lié) */}
              <button type="button" className={bouton} onClick={() => pdf(w.cle, "envois")}>Imprimer les envois</button>
            </div>
            {w.par_code.length > 0 && (
              <table className="w-full"><thead><tr className="text-left text-slate-500"><th>Code</th><th>Signification</th><th className="text-right">Nombre</th><th>Dernier</th></tr></thead>
                <tbody>{w.par_code.map((c) => (
                  <tr key={c.code} className={c.critique ? "text-red-700 font-semibold" : ""}><td>{c.code}</td><td>{c.libelle}{c.critique ? " — critique" : ""}</td><td className="text-right tabular-nums">{c.nombre}</td><td>{quand(c.derniere)}</td></tr>
                ))}</tbody></table>
            )}
            {w.alertes.length > 0 && (
              <ul className="list-disc pl-4">{w.alertes.map((a, i) => <li key={i}>{quand(a.depuis)} — {a.titre} {a.ouverte ? "(ouverte)" : `(fermée le ${(a.fermee_le || "").slice(0, 10)} : ${a.motif || ""})`}</li>)}</ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
