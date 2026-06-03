// =====================================================================
// CrossTenantSearch (2026-02)
// Petit panneau dépliable qui permet à un utilisateur de chercher un
// numéro (téléphone ou WhatsApp) dans TOUS les tenants. Si trouvé, il
// peut importer la fiche dans son propre tenant. Les admins/superviseurs
// peuvent en plus copier l'historique des messages WhatsApp.
// =====================================================================
import React, { useState } from "react";
import { Search, Download, ChevronDown, ChevronUp, Loader2, Globe, ShieldCheck, AlertTriangle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

export default function CrossTenantSearch({ user, onImported }) {
  const [open, setOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [importing, setImporting] = useState(null); // phone digits being imported
  const isPrivileged = user?.role === "admin" || user?.role === "superviseur";

  const doSearch = async (e) => {
    e?.preventDefault?.();
    const digits = (phone || "").replace(/\D/g, "");
    if (digits.length < 4) { toast.error("Numéro trop court (min 4 chiffres)"); return; }
    setLoading(true);
    setResults(null);
    try {
      const r = await apiClient.get("/me/contacts/search-cross-tenant", { params: { phone } });
      setResults(r.data);
      if (r.data?.count === 0) {
        toast.info("Aucune fiche trouvée pour ce numéro.");
      } else {
        toast.success(`${r.data.count} fiche${r.data.count > 1 ? "s" : ""} trouvée${r.data.count > 1 ? "s" : ""}.`);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur de recherche");
    } finally {
      setLoading(false);
    }
  };

  const doImport = async (digits, includeMessages) => {
    setImporting(`${digits}-${includeMessages ? "msg" : "card"}`);
    try {
      const r = await apiClient.post("/me/contacts/import-cross-tenant", {
        phone: digits,
        include_messages: !!includeMessages,
      });
      const ct = r.data?.contact || {};
      const msgN = r.data?.messages_imported || 0;
      toast.success(
        `Import réussi : ${ct.name || ct.phone}` +
        (includeMessages ? ` (${msgN} message${msgN > 1 ? "s" : ""} copié${msgN > 1 ? "s" : ""})` : ""),
        { duration: 6000 }
      );
      if (onImported) onImported();
      // Refresh results so the "in_current_scope" badge updates
      doSearch();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Erreur d'import");
    } finally {
      setImporting(null);
    }
  };

  return (
    <div className="rounded-xl ring-1 ring-sky-200 bg-sky-50/40" data-testid="cross-tenant-search">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left"
        data-testid="cross-tenant-toggle"
      >
        <div className="flex items-center gap-2">
          <Globe className="h-4 w-4 text-sky-700" />
          <span className="text-sm font-semibold text-sky-900">
            Récupérer une fiche contact d'un autre tenant
          </span>
          <span className="text-[10px] text-sky-700 bg-sky-100 ring-1 ring-sky-200 px-1.5 py-0.5 rounded-full hidden sm:inline">
            recherche cross-tenant
          </span>
        </div>
        {open ? <ChevronUp className="h-4 w-4 text-slate-500" /> : <ChevronDown className="h-4 w-4 text-slate-500" />}
      </button>

      {open && (
        <div className="border-t border-sky-200/70 px-3 py-3 space-y-3">
          <p className="text-[11px] text-sky-900">
            Utile si un contact a disparu de votre liste ou s'est égaré dans un
            autre tenant. La fiche (nom, tél, email, société) est copiée dans
            VOTRE espace.
            {isPrivileged ? (
              <span> <strong>En tant qu'admin/superviseur</strong>, vous pouvez aussi importer l'historique WhatsApp.</span>
            ) : (
              <span> L'import des messages est réservé aux admins/superviseurs.</span>
            )}
          </p>

          <form onSubmit={doSearch} className="flex flex-wrap items-center gap-2">
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+225 07 12 34 56 78"
              className="flex-1 min-w-[220px] rounded-lg border border-sky-300 px-3 py-1.5 text-sm focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              data-testid="cross-tenant-phone-input"
            />
            <button
              type="submit"
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 hover:bg-sky-700 text-white px-3 py-1.5 text-sm disabled:opacity-60"
              data-testid="cross-tenant-search-btn"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Rechercher
            </button>
          </form>

          {results && results.count > 0 && (
            <div className="rounded-lg bg-white ring-1 ring-slate-200 divide-y" data-testid="cross-tenant-results">
              {results.items.map((c) => {
                const alreadyImported = c.in_current_scope;
                const cardKey = `${results.phone_digits}-card`;
                const msgKey = `${results.phone_digits}-msg`;
                return (
                  <div key={c.id} className="px-3 py-2 flex flex-wrap items-center gap-3 text-sm" data-testid={`cross-tenant-row-${c.id}`}>
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-slate-800 truncate">
                        {c.name || c.wa_profile_name || c.phone || "(sans nom)"}
                        {alreadyImported && (
                          <span className="ml-2 inline-flex items-center gap-1 text-[10px] text-emerald-700 bg-emerald-50 ring-1 ring-emerald-200 px-1.5 py-0.5 rounded-full">
                            <CheckCircle2 className="h-3 w-3" /> Déjà dans votre espace
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-500 truncate">
                        {c.company || "—"} · {c.phone || c.whatsapp || "—"}{c.email ? ` · ${c.email}` : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => doImport(results.phone_digits, false)}
                        disabled={alreadyImported || importing === cardKey}
                        className="inline-flex items-center gap-1 rounded ring-1 ring-sky-300 text-sky-700 hover:bg-sky-50 px-2 py-1 text-[11px] font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
                        title={alreadyImported ? "Cette fiche est déjà dans votre tenant" : "Importer uniquement la fiche contact"}
                        data-testid={`cross-tenant-import-card-${c.id}`}
                      >
                        {importing === cardKey ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                        Importer fiche
                      </button>
                      {isPrivileged && (
                        <button
                          type="button"
                          onClick={() => doImport(results.phone_digits, true)}
                          disabled={importing === msgKey}
                          className="inline-flex items-center gap-1 rounded bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
                          title="Importer la fiche + l'historique des messages WhatsApp (admin/superviseur)"
                          data-testid={`cross-tenant-import-with-msgs-${c.id}`}
                        >
                          {importing === msgKey ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldCheck className="h-3 w-3" />}
                          + Messages
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {results && results.count === 0 && (
            <div className="rounded-lg bg-amber-50 ring-1 ring-amber-200 px-3 py-2 text-[12px] text-amber-900 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5 shrink-0" />
              <span>
                Aucune fiche trouvée pour ce numéro dans la base de données.
                Vérifiez le format (les chiffres seuls suffisent : <code>22673494658</code>).
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
