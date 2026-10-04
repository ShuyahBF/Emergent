// =====================================================================
// Lot 57.8 — Section « Encaissement PI-SPI » (Paramètres, onglet Paiements & Caisse ;
// réservée au super-administrateur SAWALI). Réglages GLOBAUX de la plateforme.
// - Actif, banque (UBA, BSIC, IB Bank, Ecobank, Autre), titulaire, adresse de paiement PI-SPI.
// - QR fourni par la banque : texte décodé du QR (refait tel quel) OU image téléversée (≤ 1 Mo).
// - Consigne imprimée sous le QR.
// - Factures de la Caisse concernées : seulement celles de l'entité choisie (Caisse de SAWALI).
// - Saisie manuelle d'un encaissement PI-SPI (référence bancaire) et derniers encaissements.
// Aucune API bancaire n'est appelée : le connecteur actif est « manuel ».
// Backend : routes/pispi.py (/api/admin/pispi/...).
// =====================================================================
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, QrCode, Trash2, Upload } from "lucide-react";
import { apiClient } from "@/lib/api";

const champ = "w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";
const erreurDe = (e, d) => { const x = e?.response?.data?.detail; return Array.isArray(x) ? x.map((i) => i.msg).join(" ; ") : x || d; };
const STATUTS = { attendu: "Attendu", recu: "Reçu", rapproche: "Rapproché", rejete: "Rejeté" };

// Saisie initiale à partir de la vue renvoyée par le serveur
function saisieDepuis(v) {
  return {
    actif: !!v.actif, banque: v.banque || "uba", banque_autre: v.banque_autre || "", titulaire: v.titulaire || "",
    adresse_paiement: v.adresse_paiement || "", qr_contenu: v.qr_contenu || "", consigne: v.consigne || "",
    caisse_tenant_id: v.caisse_tenant_id || "", caisse_tenant_nom: v.caisse_tenant_nom || "",
  };
}

export default function PispiSection() {
  const [vue, setVue] = useState(null);           // réglages enregistrés (serveur)
  const [saisie, setSaisie] = useState(null);     // formulaire en cours
  const [refuse, setRefuse] = useState(false);    // pas super-admin
  const [occupe, setOccupe] = useState(false);
  const [entite, setEntite] = useState(null);     // entité de la Caisse de l'utilisateur connecté
  const [transactions, setTransactions] = useState([]);
  const [enc, setEnc] = useState({ reference: "", montant: "", reference_bancaire: "" });

  // Chargement des réglages, de l'entité Caisse et des derniers encaissements
  const charger = useCallback(async () => {
    try {
      const v = await apiClient.get("/admin/pispi/parametres");
      setVue(v.data);
      setSaisie(saisieDepuis(v.data));
      apiClient.get("/cashier/tenant-info").then((r) => setEntite(r.data)).catch(() => setEntite(null));
      apiClient.get("/admin/pispi/transactions?limite=20").then((r) => setTransactions(r.data || [])).catch(() => {});
    } catch (e) {
      if (e?.response?.status === 403) setRefuse(true);
      else toast.error(erreurDe(e, "Chargement impossible"));
    }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Enregistrement des réglages (toast « Patientez… » pendant l'attente)
  async function enregistrer() {
    setOccupe(true);
    const idToast = toast.loading("Patientez… enregistrement");
    try {
      const r = await apiClient.put("/admin/pispi/parametres", saisie);
      setVue(r.data);
      setSaisie(saisieDepuis(r.data));
      toast.success("Encaissement PI-SPI enregistré", { id: idToast });
    } catch (e) {
      toast.error(erreurDe(e, "Enregistrement impossible"), { id: idToast });
    } finally { setOccupe(false); }
  }

  // Téléversement de l'image du QR (contrôle local de la taille, puis contrôle serveur)
  async function televerser(fichier) {
    if (!fichier) return;
    if (fichier.size > (vue?.image_max_octets || 1048576)) { toast.error("Image trop lourde : 1 Mo maximum."); return; }
    setOccupe(true);
    const idToast = toast.loading("Patientez… envoi de l'image du QR");
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      const r = await apiClient.post("/admin/pispi/parametres/qr-image", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setVue(r.data);
      toast.success("Image du QR enregistrée", { id: idToast });
    } catch (e) {
      toast.error(erreurDe(e, "Envoi impossible"), { id: idToast });
    } finally { setOccupe(false); }
  }

  async function retirerImage() {
    if (!window.confirm("Retirer l'image du QR ?")) return;
    try {
      const r = await apiClient.delete("/admin/pispi/parametres/qr-image");
      setVue(r.data);
      toast.success("Image retirée");
    } catch (e) { toast.error(erreurDe(e, "Retrait impossible")); }
  }

  // Saisie manuelle d'un encaissement PI-SPI reçu sur le compte bancaire
  async function saisirEncaissement() {
    setOccupe(true);
    const idToast = toast.loading("Patientez… enregistrement de l'encaissement");
    try {
      const r = await apiClient.post("/admin/pispi/encaissements", {
        reference: enc.reference.trim(), montant: parseFloat(enc.montant) || 0, reference_bancaire: enc.reference_bancaire.trim(),
      });
      toast.success(r.data.message || "Encaissement enregistré", { id: idToast });
      setEnc({ reference: "", montant: "", reference_bancaire: "" });
      const t = await apiClient.get("/admin/pispi/transactions?limite=20");
      setTransactions(t.data || []);
    } catch (e) {
      toast.error(erreurDe(e, "Enregistrement impossible"), { id: idToast });
    } finally { setOccupe(false); }
  }

  if (refuse) return <Cadre><p className="text-sm text-slate-600">Réservé au super-administrateur SAWALI.</p></Cadre>;
  if (!vue || !saisie) {
    return <Cadre><p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p></Cadre>;
  }
  const maj = (k, v) => setSaisie({ ...saisie, [k]: v });
  const caisseLiee = !!saisie.caisse_tenant_id && entite && saisie.caisse_tenant_id === entite.tenant_id;

  return (
    <Cadre>
      <p className="rounded-lg border border-sky-200 bg-sky-50 p-2 text-xs text-sky-900">
        Le QR PI-SPI est fourni par votre banque (il contient votre adresse de paiement, jamais votre numéro).
        SAWALI l'imprime tel quel sur les factures non soldées, avec le montant restant dû et la référence (n° de facture).
        Aucune API bancaire n'est appelée : les encaissements sont saisis à la main.
      </p>

      {/* Activation et banque */}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex items-start gap-2 pt-1 text-xs text-slate-700">
          <input type="checkbox" className="mt-0.5" checked={saisie.actif} disabled={occupe} data-testid="pispi-actif"
            onChange={(e) => maj("actif", e.target.checked)} />
          <span><strong>Encaissement PI-SPI actif</strong> (bloc « Payer par PI-SPI » sur les factures)</span>
        </label>
        <label className="space-y-1 text-xs text-slate-600">
          <span className="font-semibold">Banque</span>
          <select className={champ} value={saisie.banque} disabled={occupe} data-testid="pispi-banque" onChange={(e) => maj("banque", e.target.value)}>
            {(vue.banques || []).map((b) => <option key={b.valeur} value={b.valeur}>{b.libelle}</option>)}
          </select>
        </label>
        {saisie.banque === "autre" && (
          <label className="space-y-1 text-xs text-slate-600">
            <span className="font-semibold">Nom de la banque</span>
            <input className={champ} value={saisie.banque_autre} disabled={occupe} data-testid="pispi-banque-autre" onChange={(e) => maj("banque_autre", e.target.value)} />
          </label>
        )}
        <label className="space-y-1 text-xs text-slate-600">
          <span className="font-semibold">Titulaire (nom affiché)</span>
          <input className={champ} value={saisie.titulaire} disabled={occupe} placeholder="SAWALI SMART SYSTEMS" data-testid="pispi-titulaire" onChange={(e) => maj("titulaire", e.target.value)} />
        </label>
        <label className="space-y-1 text-xs text-slate-600">
          <span className="font-semibold">Adresse de paiement PI-SPI (alias fourni par la banque)</span>
          <input className={champ} value={saisie.adresse_paiement} disabled={occupe} data-testid="pispi-adresse" onChange={(e) => maj("adresse_paiement", e.target.value)} />
        </label>
      </div>

      {/* QR de la banque : texte décodé OU image */}
      <div className="grid gap-3 md:grid-cols-[1fr_auto]">
        <div className="space-y-3">
          <label className="block space-y-1 text-xs text-slate-600">
            <span className="font-semibold">Texte décodé du QR de la banque (facultatif)</span>
            <textarea className={`${champ} font-mono`} rows={3} value={saisie.qr_contenu} disabled={occupe} data-testid="pispi-qr-texte"
              onChange={(e) => maj("qr_contenu", e.target.value)} />
            <span className="block text-[11px] text-slate-400">Collé tel quel : le QR imprimé est refait à partir de ce texte, sans aucune modification.</span>
          </label>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label className={`inline-flex cursor-pointer items-center gap-1 rounded-lg bg-slate-100 px-3 py-1.5 font-medium hover:bg-slate-200 ${occupe ? "pointer-events-none opacity-50" : ""}`}>
              <Upload className="h-3.5 w-3.5" /> Téléverser l'image du QR (PNG/JPG, 1 Mo max)
              <input type="file" accept="image/png,image/jpeg" className="hidden" data-testid="pispi-qr-image"
                onChange={(e) => { televerser(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
            {vue.qr_image_presente && (
              <button type="button" onClick={retirerImage} disabled={occupe} className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-red-700 hover:bg-red-50">
                <Trash2 className="h-3.5 w-3.5" /> Retirer l'image
              </button>
            )}
            <span className="text-slate-500">
              {vue.source_qr === "image" ? "QR imprimé : image téléversée." : vue.source_qr === "texte" ? "QR imprimé : refait depuis le texte." : "Aucun QR enregistré."}
            </span>
          </div>
        </div>
        <div className="flex flex-col items-center justify-center rounded-lg ring-1 ring-slate-200 p-2" data-testid="pispi-apercu">
          {vue.qr_apercu ? <img src={vue.qr_apercu} alt="QR PI-SPI" className="h-32 w-32" /> : <QrCode className="h-16 w-16 text-slate-300" />}
          <span className="mt-1 text-[10px] text-slate-400">Aperçu (enregistré)</span>
        </div>
      </div>

      <label className="block space-y-1 text-xs text-slate-600">
        <span className="font-semibold">Consigne imprimée sous le QR</span>
        <textarea className={champ} rows={2} value={saisie.consigne} disabled={occupe} data-testid="pispi-consigne" placeholder={vue.consigne_defaut}
          onChange={(e) => maj("consigne", e.target.value)} />
      </label>

      {/* Factures concernées */}
      <div className="rounded-lg bg-slate-50 p-3 text-xs text-slate-700 space-y-1">
        <p><strong>Factures concernées :</strong> factures d'interventions (toujours) et factures de la Caisse de l'entité choisie ci-dessous
          (jamais les factures que vos clients émettent avec leur propre Caisse). Les proformas et les reçus ne portent pas le bloc.</p>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-0.5" disabled={occupe || !entite} checked={caisseLiee} data-testid="pispi-caisse"
            onChange={(e) => setSaisie({ ...saisie, caisse_tenant_id: e.target.checked ? entite.tenant_id : "", caisse_tenant_nom: e.target.checked ? (entite.tenant_name || "") : "" })} />
          <span>Ajouter le bloc aux factures de la Caisse de <strong>{entite?.tenant_name || "mon entité"}</strong></span>
        </label>
        {saisie.caisse_tenant_id && !caisseLiee && (
          <p className="text-orange-700">Entité actuellement choisie : {saisie.caisse_tenant_nom || saisie.caisse_tenant_id}</p>
        )}
      </div>

      <div className="flex justify-end">
        <button type="button" onClick={enregistrer} disabled={occupe} data-testid="pispi-enregistrer"
          className="rounded-lg bg-sawali-blue px-4 py-2 text-sm font-medium text-white hover:bg-sawali-blue-light disabled:opacity-50">
          Enregistrer
        </button>
      </div>

      {/* Saisie manuelle d'un encaissement et derniers encaissements */}
      <details className="rounded-lg ring-1 ring-slate-200 p-3 text-xs">
        <summary className="cursor-pointer font-semibold text-slate-700">Encaissements PI-SPI (saisie manuelle et historique)</summary>
        <div className="mt-2 grid gap-2 sm:grid-cols-4">
          <input className={champ} placeholder="N° de facture (référence)" value={enc.reference} onChange={(e) => setEnc({ ...enc, reference: e.target.value })} data-testid="pispi-enc-reference" />
          <input className={champ} type="number" min="0" placeholder="Montant (FCFA)" value={enc.montant} onChange={(e) => setEnc({ ...enc, montant: e.target.value })} data-testid="pispi-enc-montant" />
          <input className={champ} placeholder="Référence bancaire" value={enc.reference_bancaire} onChange={(e) => setEnc({ ...enc, reference_bancaire: e.target.value })} data-testid="pispi-enc-ref-banque" />
          <button type="button" onClick={saisirEncaissement} disabled={occupe} className="rounded-lg bg-emerald-600 px-3 py-1.5 font-medium text-white hover:bg-emerald-700 disabled:opacity-50" data-testid="pispi-enc-valider">
            Enregistrer l'encaissement
          </button>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-slate-500"><tr><th className="px-2 py-1">Date</th><th className="px-2 py-1">Référence</th><th className="px-2 py-1 text-right">Montant</th><th className="px-2 py-1">Statut</th><th className="px-2 py-1">Réf. bancaire</th><th className="px-2 py-1">Source</th></tr></thead>
            <tbody>
              {transactions.length === 0 && <tr><td colSpan={6} className="px-2 py-2 text-slate-400">Aucun encaissement.</td></tr>}
              {transactions.map((t) => (
                <tr key={t.id} className="border-t border-slate-100">
                  <td className="px-2 py-1">{new Date(t.date).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                  <td className="px-2 py-1 font-mono">{t.reference}</td>
                  <td className="px-2 py-1 text-right font-mono">{Number(t.montant || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })}</td>
                  <td className="px-2 py-1">{STATUTS[t.statut] || t.statut}</td>
                  <td className="px-2 py-1 font-mono">{t.reference_bancaire || "—"}</td>
                  <td className="px-2 py-1">{t.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Cadre>
  );
}

function Cadre({ children }) {
  return (
    <section className="space-y-4 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200" data-testid="section-pispi">
      <h2 className="font-display text-lg font-bold text-slate-900">🏦 Encaissement PI-SPI (paiement instantané BCEAO)</h2>
      {children}
    </section>
  );
}
