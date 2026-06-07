// Iter42 — Officine portal: Inventory CRUD (quantity + price + expiry + lot)
import React from "react";
import { toast } from "sonner";
import { officineApi } from "@/lib/officineApi";
import { Plus, Edit3, Trash2, Download, Search, X, Save, ScanLine, ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";
import BarcodeScannerModal from "@/components/BarcodeScannerModal";

const EMPTY = {
  cip: "", product_name: "", lot_number: "",
  expiry_date: "", quantity: 0, unit_price: "",
  currency: "XOF", available: true, notes: "",
};

export default function OfficineInventory() {
  const [items, setItems] = React.useState([]);
  const [q, setQ] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(null); // null | "new" | item

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await officineApi.get("/officines-portal/inventory", { params: q ? { q } : {} });
      setItems(r.data?.items || []);
    } finally { setLoading(false); }
  }, [q]);

  React.useEffect(() => { load(); }, [load]);

  const removeItem = async (id) => {
    if (!window.confirm("Supprimer cet item ?")) return;
    try {
      await officineApi.delete(`/officines-portal/inventory/${id}`);
      toast.success("Item supprimé");
      load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    }
  };

  const exportCsv = () => {
    const url = `${process.env.REACT_APP_BACKEND_URL}/api/officines-portal/inventory/export.csv`;
    const token = localStorage.getItem("sawali_officine_token");
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `inventaire-${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
      })
      .catch(() => toast.error("Échec téléchargement"));
  };

  return (
    <div className="space-y-4" data-testid="officine-inventory-page">
      <div className="flex flex-wrap items-center gap-2 justify-between">
        <h1 className="text-xl font-display font-bold text-slate-900">Inventaire</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={exportCsv}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 ring-1 ring-slate-200"
            data-testid="inventory-export-btn"
          >
            <Download className="h-3.5 w-3.5" /> Export CSV
          </button>
          <button
            onClick={() => setEditing({ ...EMPTY })}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue/90"
            data-testid="inventory-add-btn"
          >
            <Plus className="h-3.5 w-3.5" /> Ajouter
          </button>
        </div>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Rechercher par nom, CIP ou lot…"
          className="w-full pl-9 pr-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-sawali-blue"
          data-testid="inventory-search"
        />
      </div>

      <div className="bg-white rounded-xl shadow-sm ring-1 ring-slate-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Produit</th>
                <th className="px-3 py-2 font-medium">CIP</th>
                <th className="px-3 py-2 font-medium">Lot</th>
                <th className="px-3 py-2 font-medium">Péremption</th>
                <th className="px-3 py-2 font-medium text-right">Qté</th>
                <th className="px-3 py-2 font-medium text-right">Prix</th>
                <th className="px-3 py-2 font-medium">Dispo.</th>
                <th className="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody data-testid="inventory-table-body">
              {loading && (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400">Chargement…</td></tr>
              )}
              {!loading && items.length === 0 && (
                <tr><td colSpan={8} className="px-3 py-6 text-center text-slate-400">Aucun item en stock.</td></tr>
              )}
              {items.map((it) => {
                const expSoon = it.expiry_date && new Date(it.expiry_date) <= new Date(Date.now() + 30 * 86400000);
                return (
                  <tr key={it.id} className="border-t border-slate-100 hover:bg-slate-50" data-testid={`inventory-row-${it.id}`}>
                    <td className="px-3 py-2 font-medium text-slate-900">{it.product_name}</td>
                    <td className="px-3 py-2 text-slate-600">{it.cip || "—"}</td>
                    <td className="px-3 py-2 text-slate-600">{it.lot_number || "—"}</td>
                    <td className={`px-3 py-2 ${expSoon ? "text-amber-700 font-medium" : "text-slate-600"}`}>
                      {it.expiry_date || "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{it.quantity}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {it.unit_price != null ? `${it.unit_price} ${it.currency || ""}` : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ring-1 ${
                        it.available ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-rose-50 text-rose-700 ring-rose-200"
                      }`}>
                        {it.available ? "Oui" : "Non"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => setEditing(it)}
                          className="p-1.5 rounded hover:bg-slate-200 text-slate-600"
                          data-testid={`inventory-edit-${it.id}`}
                          title="Modifier"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => removeItem(it.id)}
                          className="p-1.5 rounded hover:bg-rose-100 text-rose-600"
                          data-testid={`inventory-delete-${it.id}`}
                          title="Supprimer"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <InventoryEditor
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

function InventoryEditor({ item, onClose, onSaved }) {
  const isNew = !item?.id;
  const [form, setForm] = React.useState({
    cip: item.cip || "",
    product_name: item.product_name || "",
    lot_number: item.lot_number || "",
    expiry_date: item.expiry_date || "",
    quantity: item.quantity ?? 0,
    unit_price: item.unit_price ?? "",
    currency: item.currency || "XOF",
    available: item.available !== false,
    notes: item.notes || "",
  });
  const [busy, setBusy] = React.useState(false);
  // Iter42c — Scanner code-barres pour CIP
  const [scanning, setScanning] = React.useState(false);
  // Iter42d — Lookup AMM par CIP + pays par défaut
  const [lookupBusy, setLookupBusy] = React.useState(false);
  const [lookupResult, setLookupResult] = React.useState(null);
  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm({ ...form, [k]: v });
  };

  const onScanDetected = ({ cip, raw }) => {
    setForm((s) => ({ ...s, cip: cip || raw }));
    setScanning(false);
    setLookupResult(null);
    toast.success(`Code détecté : ${cip || raw}`);
  };

  const lookupAmm = async () => {
    if (!form.cip || form.cip.length < 3) {
      toast.error("Saisissez d'abord un code CIP");
      return;
    }
    setLookupBusy(true);
    setLookupResult(null);
    try {
      const r = await officineApi.post("/officines-portal/inventory/lookup-amm", { cip: form.cip.trim() });
      setLookupResult(r.data);
      if (r.data.found) {
        // Pré-remplit le nom du produit si vide
        if (!form.product_name && r.data.product_name) {
          setForm((s) => ({ ...s, product_name: r.data.product_name }));
        }
        if (r.data.expired) toast.warning(`AMM trouvé mais expiré (${r.data.expires_at})`);
        else toast.success(`AMM valide : ${r.data.product_name}`);
      } else {
        toast.info("AMM non trouvé dans le catalogue — le code est enregistré tel quel");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur lookup");
    } finally {
      setLookupBusy(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = {
        ...form,
        quantity: Number(form.quantity) || 0,
        unit_price: form.unit_price === "" ? null : Number(form.unit_price),
      };
      if (isNew) {
        await officineApi.post("/officines-portal/inventory", payload);
        toast.success("Item ajouté");
      } else {
        await officineApi.put(`/officines-portal/inventory/${item.id}`, payload);
        toast.success("Item modifié");
      }
      onSaved();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Échec");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" data-testid="inventory-editor-modal">
      <form onSubmit={submit} className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-display font-semibold text-slate-900">
            {isNew ? "Nouvel item" : "Modifier l'item"}
          </h3>
          <button type="button" onClick={onClose} className="p-1 hover:bg-slate-100 rounded" data-testid="inventory-editor-close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-3">
          <Row label="Nom du produit *">
            <input required value={form.product_name} onChange={set("product_name")}
              className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-product-name" />
          </Row>
          <div className="grid grid-cols-2 gap-3">
            <Row label="Code CIP">
              <div className="flex items-center gap-1.5">
                <input value={form.cip} onChange={(e) => { set("cip")(e); setLookupResult(null); }}
                  className="flex-1 border rounded px-3 py-2 text-sm font-mono" data-testid="editor-cip"
                  placeholder="Ex: 3400930123456" />
                <button
                  type="button"
                  onClick={() => setScanning(true)}
                  title="Scanner le code-barres"
                  className="inline-flex items-center justify-center px-2 py-2 rounded ring-1 ring-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                  data-testid="editor-scan-cip"
                >
                  <ScanLine className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={lookupAmm}
                  disabled={lookupBusy || !form.cip}
                  title="Vérifier la validité de l'AMM pour le pays par défaut"
                  className="inline-flex items-center justify-center gap-1 px-2 py-2 rounded ring-1 ring-sky-300 bg-sky-50 text-sky-700 hover:bg-sky-100 disabled:opacity-50 whitespace-nowrap text-xs"
                  data-testid="editor-lookup-amm"
                >
                  {lookupBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                  Vérifier AMM
                </button>
              </div>
              <p className="text-[10px] text-slate-400 mt-1">📷 Scannez le code-barres (Data Matrix ou EAN-13) ou cliquez sur « Vérifier AMM » pour contrôler la validité dans le pays.</p>
              {lookupResult && (
                <div className={`mt-2 text-xs rounded p-2 ring-1 ${
                  !lookupResult.found
                    ? "bg-slate-50 text-slate-700 ring-slate-200"
                    : lookupResult.expired
                    ? "bg-rose-50 text-rose-800 ring-rose-200"
                    : "bg-emerald-50 text-emerald-800 ring-emerald-200"
                }`} data-testid="lookup-result">
                  {!lookupResult.found ? (
                    <p>ℹ️ {lookupResult.message}</p>
                  ) : (
                    <div className="space-y-0.5">
                      <p className="font-medium inline-flex items-center gap-1">
                        {lookupResult.expired ? <ShieldAlert className="h-3.5 w-3.5" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                        {lookupResult.expired ? "AMM trouvé mais expiré" : "AMM valide"}
                      </p>
                      <p>📦 <strong>{lookupResult.product_name}</strong></p>
                      {lookupResult.laboratory && <p>🏭 {lookupResult.laboratory}</p>}
                      {lookupResult.amm_number && <p>📋 N° AMM : <span className="font-mono">{lookupResult.amm_number}</span></p>}
                      <p>🌍 Pays : <span className="font-mono">{lookupResult.country || "—"}</span></p>
                      {lookupResult.expires_at && <p>📅 Expire le : {lookupResult.expires_at}</p>}
                    </div>
                  )}
                </div>
              )}
            </Row>
            <Row label="Numéro de lot">
              <input value={form.lot_number} onChange={set("lot_number")}
                className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-lot" />
            </Row>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Row label="Date de péremption">
              <input type="date" value={form.expiry_date} onChange={set("expiry_date")}
                className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-expiry" />
            </Row>
            <Row label="Quantité">
              <input type="number" min="0" value={form.quantity} onChange={set("quantity")}
                className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-quantity" />
            </Row>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <Row label="Prix unitaire">
              <input type="number" step="0.01" min="0" value={form.unit_price} onChange={set("unit_price")}
                className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-price" />
            </Row>
            <Row label="Devise">
              <select value={form.currency} onChange={set("currency")}
                className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-currency">
                <option value="XOF">XOF</option>
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="MAD">MAD</option>
              </select>
            </Row>
            <Row label="Disponible">
              <label className="flex items-center gap-2 mt-2">
                <input type="checkbox" checked={form.available} onChange={set("available")} data-testid="editor-available" />
                <span className="text-xs text-slate-600">{form.available ? "En stock" : "Rupture"}</span>
              </label>
            </Row>
          </div>
          <Row label="Notes">
            <textarea value={form.notes} onChange={set("notes")} rows={2}
              className="w-full border rounded px-3 py-2 text-sm" data-testid="editor-notes" />
          </Row>
        </div>
        <div className="px-5 py-3 border-t bg-slate-50 flex justify-end gap-2">
          <button type="button" onClick={onClose}
            className="px-3 py-2 rounded text-sm bg-slate-200 hover:bg-slate-300 text-slate-700"
            data-testid="editor-cancel">
            Annuler
          </button>
          <button type="submit" disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded text-sm bg-sawali-blue text-white hover:bg-sawali-blue/90 disabled:opacity-50"
            data-testid="editor-save">
            <Save className="h-3.5 w-3.5" /> {busy ? "Enregistrement…" : "Enregistrer"}
          </button>
        </div>
      </form>
      {scanning && (
        <BarcodeScannerModal
          onClose={() => setScanning(false)}
          onDetected={onScanDetected}
        />
      )}
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-700 mb-1">{label}</label>
      {children}
    </div>
  );
}
