import React, { useEffect, useState, useMemo } from "react";
import { apiClient } from "@/lib/api";
import { toast } from "sonner";
import QRCode from "qrcode";
import {
  Link2, Plus, Copy, X, Trash2, ToggleLeft, ToggleRight, QrCode, Share2,
  CheckCircle2, AlertCircle, Clock, Power, ExternalLink,
} from "lucide-react";

/*
  Sub-component used inside MyPayments → tab "Liens".
  Lets the user generate shareable payment URLs (/pay/{slug}).
*/

const MNOS_ALL = ["ORANGE", "MOOV", "TELECEL"];
const MNO_LABELS = {
  ORANGE: "Orange Money",
  MOOV: "Moov Money",
  TELECEL: "Telecel Cash",
};

const STATUS_BADGE = {
  active: { cls: "bg-emerald-100 text-emerald-800 ring-emerald-200", icon: CheckCircle2, label: "Actif" },
  disabled: { cls: "bg-slate-100 text-slate-700 ring-slate-200", icon: Power, label: "Désactivé" },
  expired: { cls: "bg-amber-100 text-amber-800 ring-amber-200", icon: Clock, label: "Expiré" },
  exhausted: { cls: "bg-rose-100 text-rose-800 ring-rose-200", icon: AlertCircle, label: "Épuisé" },
};

function publicPayUrl(slug) {
  const base = window.location.origin;
  return `${base}/pay/${slug}`;
}

export default function MyPaymentLinks({ features, mnos }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [qrModal, setQrModal] = useState(null); // {slug, dataUrl}

  const load = async () => {
    setLoading(true);
    try {
      const r = await apiClient.get("/me/payment-links");
      setItems(r.data || []);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const copy = async (txt) => {
    try {
      await navigator.clipboard.writeText(txt);
      toast.success("Lien copié dans le presse-papiers");
    } catch {
      toast.error("Impossible de copier");
    }
  };

  const showQR = async (slug) => {
    try {
      const url = publicPayUrl(slug);
      const dataUrl = await QRCode.toDataURL(url, { errorCorrectionLevel: "M", width: 320, margin: 1 });
      setQrModal({ slug, dataUrl, url });
    } catch {
      toast.error("Erreur génération QR");
    }
  };

  const shareWa = (link) => {
    const url = publicPayUrl(link.slug);
    const text = `Bonjour, voici votre lien de paiement sécurisé : ${link.label}${link.amount ? ` (${Number(link.amount).toLocaleString("fr-FR")} ${link.currency})` : ""}\n\n${url}`;
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
  };

  const toggle = async (link) => {
    try {
      await apiClient.patch(`/me/payment-links/${link.id}`, { disabled: !link.disabled });
      toast.success(link.disabled ? "Lien réactivé" : "Lien désactivé");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  const remove = async (link) => {
    if (!window.confirm(`Supprimer définitivement le lien « ${link.label} » ?`)) return;
    try {
      await apiClient.delete(`/me/payment-links/${link.id}`);
      toast.success("Lien supprimé");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    }
  };

  return (
    <div className="space-y-4" data-testid="payment-links-tab">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-sm text-slate-500">
          Créez des liens de paiement à partager (WhatsApp, SMS, email, QR code…). Vos clients règlent en mobile money sans avoir besoin de compte.
        </p>
        <button
          onClick={() => {
            if (!features?.payments) { toast.error("Paiements non activés"); return; }
            if (!mnos?.length) { toast.error("Aucun opérateur disponible"); return; }
            setShowModal(true);
          }}
          disabled={!features?.payments || !mnos?.length}
          className="inline-flex items-center gap-2 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 text-sm disabled:opacity-40"
          data-testid="links-new-btn"
        >
          <Plus className="h-4 w-4" /> Nouveau lien
        </button>
      </div>

      <div className="rounded-xl ring-1 ring-slate-200 bg-white overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 uppercase text-[10px]">
              <tr>
                <th className="text-left px-3 py-2">Libellé</th>
                <th className="text-left px-3 py-2">Montant</th>
                <th className="text-left px-3 py-2">Opérateurs</th>
                <th className="text-left px-3 py-2">Utilisations</th>
                <th className="text-left px-3 py-2">Statut</th>
                <th className="text-right px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-400 italic">Chargement…</td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-slate-400 italic">Aucun lien pour l'instant. Cliquez sur « Nouveau lien » pour démarrer.</td></tr>
              )}
              {items.map((l) => {
                const sb = STATUS_BADGE[l.status] || STATUS_BADGE.active;
                const Icon = sb.icon;
                return (
                  <tr key={l.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`link-row-${l.slug}`}>
                    <td className="px-3 py-2">
                      <div className="font-semibold text-slate-800">{l.label}</div>
                      <div className="text-[11px] text-slate-500 font-mono">/pay/{l.slug}</div>
                      {l.description && <div className="text-[10px] text-slate-400 italic mt-0.5 max-w-[280px] truncate">{l.description}</div>}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">
                      {l.amount != null ? `${Number(l.amount).toLocaleString("fr-FR")} ${l.currency || "XOF"}` : <span className="text-amber-700 italic">libre</span>}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {(l.allowed_mnos || []).map((m) => (
                          <span key={m} className="text-[9px] uppercase tracking-wider bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded ring-1 ring-slate-200">{m}</span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs font-mono">
                      {l.uses_count || 0}{l.max_uses ? <span className="text-slate-400"> / {l.max_uses}</span> : <span className="text-slate-400"> / ∞</span>}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ring-1 ${sb.cls}`}>
                        <Icon className="h-3 w-3" /> {sb.label}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1">
                        <IconBtn label="Copier le lien" onClick={() => copy(publicPayUrl(l.slug))} testid={`link-copy-${l.slug}`}><Copy className="h-3.5 w-3.5" /></IconBtn>
                        <IconBtn label="QR Code" onClick={() => showQR(l.slug)} testid={`link-qr-${l.slug}`}><QrCode className="h-3.5 w-3.5" /></IconBtn>
                        <IconBtn label="Partager via WhatsApp" onClick={() => shareWa(l)} testid={`link-wa-${l.slug}`}><Share2 className="h-3.5 w-3.5" /></IconBtn>
                        <IconBtn label="Ouvrir" onClick={() => window.open(publicPayUrl(l.slug), "_blank")} testid={`link-open-${l.slug}`}><ExternalLink className="h-3.5 w-3.5" /></IconBtn>
                        <IconBtn label={l.disabled ? "Réactiver" : "Désactiver"} onClick={() => toggle(l)} testid={`link-toggle-${l.slug}`}>
                          {l.disabled ? <ToggleLeft className="h-3.5 w-3.5 text-slate-500" /> : <ToggleRight className="h-3.5 w-3.5 text-emerald-600" />}
                        </IconBtn>
                        <IconBtn label="Supprimer" onClick={() => remove(l)} testid={`link-delete-${l.slug}`}><Trash2 className="h-3.5 w-3.5 text-rose-600" /></IconBtn>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {showModal && (
        <NewLinkModal
          mnos={mnos}
          onClose={() => setShowModal(false)}
          onCreated={(created) => {
            setShowModal(false);
            load();
            if (created?.slug) showQR(created.slug);
          }}
        />
      )}
      {qrModal && <QrModal qr={qrModal} onClose={() => setQrModal(null)} onCopy={copy} />}
    </div>
  );
}

function IconBtn({ label, onClick, testid, children }) {
  return (
    <button
      title={label}
      onClick={onClick}
      className="inline-flex items-center justify-center h-7 w-7 rounded ring-1 ring-slate-200 hover:bg-slate-100"
      data-testid={testid}
    >
      {children}
    </button>
  );
}

function NewLinkModal({ mnos, onClose, onCreated }) {
  const [label, setLabel] = useState("");
  const [openAmount, setOpenAmount] = useState(false);
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [allowedMnos, setAllowedMnos] = useState(mnos || []);
  const [expiresAt, setExpiresAt] = useState("");
  const [maxUses, setMaxUses] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const toggleMno = (m) => {
    setAllowedMnos((cur) => cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]);
  };

  const submit = async () => {
    if (!label.trim()) { toast.error("Le libellé est requis"); return; }
    if (!openAmount) {
      const a = parseFloat(amount);
      if (!a || a <= 0) { toast.error("Montant invalide"); return; }
    }
    if (allowedMnos.length === 0) { toast.error("Sélectionnez au moins 1 opérateur"); return; }
    setSubmitting(true);
    try {
      const body = {
        label: label.trim(),
        amount: openAmount ? null : parseFloat(amount),
        description: description || undefined,
        allowed_mnos: allowedMnos,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
        max_uses: maxUses ? parseInt(maxUses, 10) : undefined,
      };
      const r = await apiClient.post("/me/payment-links", body);
      toast.success("Lien créé");
      onCreated && onCreated(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="link-new-modal">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b bg-amber-50">
          <h2 className="text-lg font-display font-bold inline-flex items-center gap-2">
            <Link2 className="h-5 w-5 text-amber-600" /> Nouveau lien de paiement
          </h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-900"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-3 overflow-y-auto">
          <div>
            <label className="text-xs font-semibold block mb-1">Libellé / référence *</label>
            <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} placeholder="Facture #2025-001 — Maintenance Q2"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="link-label" />
          </div>
          <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
            <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
              <input type="checkbox" checked={openAmount} onChange={(e) => setOpenAmount(e.target.checked)} data-testid="link-open-amount" />
              Montant libre (le payeur saisit le montant lui-même)
            </label>
            {!openAmount && (
              <div className="mt-2">
                <label className="text-[10px] uppercase tracking-wider text-slate-500 block">Montant fixe (XOF)</label>
                <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000"
                  className="w-full mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="link-amount" />
              </div>
            )}
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Opérateurs autorisés</label>
            <div className="grid grid-cols-3 gap-2">
              {(mnos || MNOS_ALL).map((m) => {
                const active = allowedMnos.includes(m);
                return (
                  <button key={m} type="button" onClick={() => toggleMno(m)}
                    className={`rounded-lg px-2 py-2 text-xs font-semibold ring-1 ${active ? "ring-2 bg-amber-50 ring-amber-400 text-amber-900" : "ring-slate-200 text-slate-500 bg-white"}`}
                    data-testid={`link-mno-${m}`}>
                    {MNO_LABELS[m] || m}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold block mb-1">Date d'expiration (optionnel)</label>
              <input type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="link-expires-at" />
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1">Nombre max d'utilisations</label>
              <input type="number" value={maxUses} onChange={(e) => setMaxUses(e.target.value)} placeholder="∞ illimité"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono" data-testid="link-max-uses" />
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1">Description (optionnel)</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} rows={2}
              placeholder="Maintenance trimestrielle Q2 2025…"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" data-testid="link-description" />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t bg-slate-50">
          <button onClick={onClose} className="text-sm rounded-lg bg-white ring-1 ring-slate-300 hover:bg-slate-100 px-4 py-2">Annuler</button>
          <button onClick={submit} disabled={submitting}
            className="inline-flex items-center gap-1.5 text-sm rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 disabled:opacity-50"
            data-testid="link-submit-btn">
            <Link2 className="h-4 w-4" /> {submitting ? "Création…" : "Créer le lien"}
          </button>
        </div>
      </div>
    </div>
  );
}

function QrModal({ qr, onClose, onCopy }) {
  const download = () => {
    const a = document.createElement("a");
    a.href = qr.dataUrl;
    a.download = `pay-${qr.slug}.png`;
    document.body.appendChild(a); a.click(); a.remove();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={(e) => e.target === e.currentTarget && onClose()} data-testid="link-qr-modal">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-display font-bold inline-flex items-center gap-2"><QrCode className="h-4 w-4" /> QR Code de paiement</h3>
          <button onClick={onClose} className="text-slate-500"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 flex flex-col items-center gap-3">
          <img src={qr.dataUrl} alt="QR" className="w-64 h-64 ring-1 ring-slate-200 rounded" />
          <code className="text-[10px] text-slate-500 break-all text-center">{qr.url}</code>
          <div className="flex gap-2 w-full">
            <button onClick={() => onCopy(qr.url)} className="flex-1 inline-flex items-center justify-center gap-1 rounded-lg ring-1 ring-slate-300 px-3 py-2 text-sm hover:bg-slate-50">
              <Copy className="h-4 w-4" /> Copier
            </button>
            <button onClick={download} className="flex-1 inline-flex items-center justify-center gap-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white px-3 py-2 text-sm">
              Télécharger PNG
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
