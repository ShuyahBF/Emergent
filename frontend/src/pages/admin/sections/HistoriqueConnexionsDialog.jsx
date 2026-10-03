import React, { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/api";
import { History, X, Ban, CheckCircle2, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { toast } from "sonner";

// Lot 55 — Historique des connexions d'un utilisateur suivi (page « Utilisateurs suivis »).
// Serveur : backend/routes/connexions_ip.py et backend/connexions_ip.py.
//   - 50 lignes par page, les plus récentes d'abord, filtre par IP ;
//   - « Bloquer » : l'IP ne peut plus se connecter à CE compte (sessions ouvertes depuis cette IP
//     fermées) ; case « pour tous les comptes » réservée au super-admin ;
//   - « Autoriser » : lève le blocage et marque l'IP « de confiance » pour ce compte.
// Une adresse IP correspond à un lieu ou à un réseau (Wi-Fi, box), pas à une personne : pour le
// super-admin, la case « pour tous les comptes » est cochée par défaut (bloquer un site) ; un
// « libellé du site » facultatif accompagne chaque blocage ou autorisation.

const FUSEAU = "Africa/Ouagadougou";

/** Date et heure au format fr-FR, fuseau Africa/Ouagadougou ; "" si absente. */
export function dateHeureOuaga(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { timeZone: FUSEAU, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Badge du statut d'une IP pour un compte : rouge « bloquée », vert « de confiance ».
 *  Le libellé du site (et la portée) s'affiche en bulle au survol. */
export function BadgeIp({ statut, libelle, portee }) {
  const bulle = [libelle, portee === "globale" ? "bloquée pour tous les comptes" : null].filter(Boolean).join(" — ") || undefined;
  if (statut === "bloquee") {
    return <span title={bulle} className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 border border-rose-300 cursor-help" data-testid="badge-ip-bloquee">bloquée</span>;
  }
  if (statut === "confiance") {
    return <span title={bulle} className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-300 cursor-help" data-testid="badge-ip-confiance">de confiance</span>;
  }
  return null;
}

const METHODES = { mot_de_passe: "Mot de passe", code_email: "Code e-mail", code_whatsapp: "Code WhatsApp", autre: "Autre" };

export default function HistoriqueConnexionsDialog({ suivi, onClose }) {
  const [donnees, setDonnees] = useState(null);
  const [page, setPage] = useState(1);
  const [filtreIp, setFiltreIp] = useState("");
  const [ipAppliquee, setIpAppliquee] = useState("");
  const [globale, setGlobale] = useState(false);
  const [libelle, setLibelle] = useState("");
  const caseInitialisee = useRef(false);
  const [occupe, setOccupe] = useState("");

  const charger = useCallback(() => {
    const params = { page };
    if (ipAppliquee) params.ip = ipAppliquee;
    return apiClient.get(`/admin/tracked-users/${suivi.id}/connexions`, { params })
      .then((r) => setDonnees(r.data))
      .catch((err) => toast.error(err?.response?.data?.detail || "Chargement impossible"));
  }, [suivi.id, page, ipAppliquee]);

  useEffect(() => { charger(); }, [charger]);
  // Super-admin : « pour tous les comptes » coché par défaut (cas principal : bloquer un site)
  useEffect(() => {
    if (donnees && !caseInitialisee.current) {
      caseInitialisee.current = true;
      setGlobale(!!donnees.peut_bloquer_global);
    }
  }, [donnees]);

  const bloquees = donnees?.bloquees || [];
  const confiance = donnees?.confiance || [];
  const regleDe = (ip) => {
    const b = bloquees.find((x) => x.ip === ip && x.portee === "globale") || bloquees.find((x) => x.ip === ip);
    if (b) return { statut: "bloquee", libelle: b.libelle, portee: b.portee };
    const c = confiance.find((x) => x.ip === ip);
    if (c) return { statut: "confiance", libelle: c.libelle, portee: "compte" };
    return { statut: null };
  };
  const statutDe = (ip) => regleDe(ip).statut;
  const estSaPropreIp = (ip) => !!donnees?.ip_courante && ip === donnees.ip_courante;
  const compteProtege = !!donnees?.compte?.super_admin;

  const agir = async (action, ip) => {
    const portee = action === "bloquer" && globale ? " pour TOUS les comptes de la plateforme" : "";
    const question = action === "bloquer"
      ? `Bloquer l'adresse ${ip}${portee || " pour ce compte"} ? Les sessions ouvertes depuis cette adresse seront fermées.`
      : `Autoriser l'adresse ${ip} pour ce compte ?`;
    if (!window.confirm(question)) return;
    setOccupe(`${action}-${ip}`);
    try {
      const r = await apiClient.post(`/admin/tracked-users/${suivi.id}/connexions/${action}`,
        { ip, globale: action === "bloquer" ? globale : false, libelle: libelle.trim() || null });
      if (action === "bloquer") {
        const n = r.data?.sessions_fermees || 0;
        toast.success(`Adresse ${ip} bloquée${r.data?.portee === "globale" ? " pour tous les comptes" : ""}${n ? ` · ${n} session(s) fermée(s)` : ""}`);
      } else {
        toast.success(`Adresse ${ip} autorisée (de confiance pour ce compte)`);
      }
      setLibelle("");
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible");
    } finally { setOccupe(""); }
  };

  const BoutonsIp = ({ ip }) => {
    if (!ip) return null;
    const statut = statutDe(ip);
    return (
      <span className="inline-flex gap-1.5">
        <button
          onClick={() => agir("bloquer", ip)}
          disabled={!!occupe || (statut === "bloquee" && !(globale && regleDe(ip).portee !== "globale")) || estSaPropreIp(ip) || compteProtege}
          title={estSaPropreIp(ip) ? "Adresse de votre propre session : blocage impossible" : compteProtege ? "Le super-administrateur ne peut pas être bloqué" : "Bloquer cette adresse pour ce compte"}
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50 disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid={`bloquer-ip-${ip}`}
        >
          <Ban className="h-3 w-3" /> Bloquer
        </button>
        <button
          onClick={() => agir("autoriser", ip)}
          disabled={!!occupe || statut === "confiance"}
          title="Lever le blocage et marquer l'adresse comme de confiance pour ce compte"
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-40 disabled:cursor-not-allowed"
          data-testid={`autoriser-ip-${ip}`}
        >
          <CheckCircle2 className="h-3 w-3" /> Autoriser
        </button>
      </span>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-5xl max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()} data-testid="historique-connexions-dialog">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h3 className="font-display font-semibold inline-flex items-center gap-2">
              <History className="h-4 w-4 text-sawali-blue" /> Historique des connexions — {suivi.name}
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              {donnees?.compte?.email || suivi.email || ""} · heures de Ouagadougou · conservé 180 jours
              {donnees?.ip_courante ? <> · votre adresse : <span className="font-mono">{donnees.ip_courante}</span></> : null}
            </p>
          </div>
          <button onClick={onClose} aria-label="Fermer"><X className="h-4 w-4" /></button>
        </div>

        <div className="p-4 space-y-4 overflow-y-auto">
          {donnees && !donnees.compte && (
            <p className="text-sm text-slate-500">Cet utilisateur n'a pas de compte de connexion au portail.</p>
          )}

          <p className="text-xs text-slate-600 rounded-lg bg-slate-50 ring-1 ring-slate-200 px-3 py-2" data-testid="aide-ip-lieu">
            Une adresse IP correspond à un lieu ou à un réseau (Wi-Fi, box), pas à une personne. Bloquer une adresse
            bloque toutes les connexions qui passent par ce réseau.
          </p>

          {donnees?.compte && (
            <>
              {/* IP bloquées (du compte et globales) avec « Autoriser » en face de chacune */}
              <div className="rounded-lg ring-1 ring-rose-200 bg-rose-50/40 p-3" data-testid="liste-ip-bloquees">
                <div className="text-xs font-semibold text-rose-800 mb-2">IP bloquées ({bloquees.length})</div>
                {bloquees.length === 0 ? <p className="text-xs text-slate-500">Aucune adresse bloquée pour ce compte.</p> : (
                  <ul className="space-y-1">
                    {bloquees.map((b) => (
                      <li key={`${b.ip}-${b.portee}`} className="flex items-center justify-between gap-2 text-xs">
                        <span>
                          <span className="font-mono">{b.ip}</span>
                          {b.libelle && <span className="ml-2 font-medium text-slate-700" data-testid="libelle-site">{b.libelle}</span>}
                          <span className="ml-2 text-slate-500">{b.portee === "globale" ? "tous les comptes" : "ce compte"} · {dateHeureOuaga(b.date)}{b.par ? ` · par ${b.par}` : ""}</span>
                        </span>
                        <button
                          onClick={() => agir("autoriser", b.ip)}
                          disabled={!!occupe || (b.portee === "globale" && !donnees.peut_bloquer_global)}
                          title={b.portee === "globale" && !donnees.peut_bloquer_global ? "Blocage global : réservé au super-administrateur" : "Autoriser"}
                          className="inline-flex items-center gap-1 rounded px-2 py-0.5 ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                          data-testid={`autoriser-bloquee-${b.ip}`}
                        >
                          <CheckCircle2 className="h-3 w-3" /> Autoriser
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {confiance.length > 0 && (
                  <div className="mt-2 text-xs text-slate-600 flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-emerald-800">De confiance :</span>
                    {confiance.map((c) => <span key={c.ip} className="font-mono inline-flex items-center gap-1">{c.ip}{c.libelle ? <span className="font-sans text-slate-500">({c.libelle})</span> : null} <BadgeIp statut="confiance" libelle={c.libelle} /></span>)}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-3 flex-wrap">
                <form
                  onSubmit={(e) => { e.preventDefault(); setPage(1); setIpAppliquee(filtreIp.trim()); }}
                  className="inline-flex items-center gap-2"
                >
                  <input
                    value={filtreIp}
                    onChange={(e) => setFiltreIp(e.target.value)}
                    placeholder="Filtrer par IP (début de l'adresse)"
                    className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-mono w-64"
                    data-testid="filtre-ip"
                  />
                  <button type="submit" className="inline-flex items-center gap-1 rounded-lg ring-1 ring-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"><Search className="h-3.5 w-3.5" /> Filtrer</button>
                  {ipAppliquee && <button type="button" onClick={() => { setFiltreIp(""); setIpAppliquee(""); setPage(1); }} className="text-xs text-slate-500 underline">Effacer</button>}
                </form>
                <input
                  value={libelle}
                  onChange={(e) => setLibelle(e.target.value)}
                  maxLength={120}
                  placeholder="Libellé du site (facultatif) — ex. Pharmacie X — Wi-Fi accueil"
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm w-80"
                  data-testid="libelle-site-input"
                />
                {donnees.peut_bloquer_global && (
                  <label className="inline-flex items-center gap-2 text-xs rounded-lg ring-1 ring-amber-300 bg-amber-50 px-3 py-1.5 cursor-pointer" data-testid="case-pour-tous-les-comptes">
                    <input type="checkbox" checked={globale} onChange={(e) => setGlobale(e.target.checked)} />
                    Bloquer pour tous les comptes (super-admin)
                  </label>
                )}
              </div>

              <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
                <table className="w-full text-sm min-w-[820px]">
                  <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                    <tr>
                      <th className="text-left px-3 py-2">Date</th>
                      <th className="text-left px-3 py-2">Adresse IP</th>
                      <th className="text-left px-3 py-2">Appareil</th>
                      <th className="text-left px-3 py-2">Méthode</th>
                      <th className="text-left px-3 py-2">Résultat</th>
                      <th className="text-left px-3 py-2">Session</th>
                      <th className="text-right px-3 py-2">Adresse</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(donnees.items || []).length === 0 && (
                      <tr><td colSpan={7} className="px-3 py-6 text-center text-slate-500">Aucune connexion enregistrée{ipAppliquee ? " pour ce filtre" : ""}.</td></tr>
                    )}
                    {(donnees.items || []).map((l) => (
                      <tr key={l.id} className="border-t border-slate-100" data-testid={`ligne-connexion-${l.id}`}>
                        <td className="px-3 py-2 whitespace-nowrap">{dateHeureOuaga(l.date)}</td>
                        <td className="px-3 py-2 whitespace-nowrap"><span className="font-mono text-xs mr-1.5">{l.ip || "—"}</span><BadgeIp {...regleDe(l.ip)} /></td>
                        <td className="px-3 py-2 whitespace-nowrap text-slate-600">{l.appareil || "—"}</td>
                        <td className="px-3 py-2 whitespace-nowrap">{METHODES[l.methode] || l.methode || "—"}</td>
                        <td className="px-3 py-2">
                          {l.resultat === "reussie"
                            ? <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">Réussie</span>
                            : <span className="text-xs px-1.5 py-0.5 rounded bg-rose-50 text-rose-700">Refusée{l.motif ? ` — ${l.motif}` : ""}</span>}
                        </td>
                        <td className="px-3 py-2 font-mono text-[10px] text-slate-400">{l.sid ? l.sid.slice(0, 8) : "—"}</td>
                        <td className="px-3 py-2 text-right whitespace-nowrap"><BoutonsIp ip={l.ip} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between text-xs text-slate-600">
                <span>{donnees.total || 0} connexion(s) · page {donnees.page || 1} / {donnees.pages || 1} · 50 par page</span>
                <span className="inline-flex gap-2">
                  <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={(donnees.page || 1) <= 1} className="inline-flex items-center gap-1 rounded ring-1 ring-slate-300 px-2 py-1 disabled:opacity-40" data-testid="page-precedente"><ChevronLeft className="h-3 w-3" /> Précédente</button>
                  <button onClick={() => setPage((p) => p + 1)} disabled={(donnees.page || 1) >= (donnees.pages || 1)} className="inline-flex items-center gap-1 rounded ring-1 ring-slate-300 px-2 py-1 disabled:opacity-40" data-testid="page-suivante">Suivante <ChevronRight className="h-3 w-3" /></button>
                </span>
              </div>

              {(donnees.actions || []).length > 0 && (
                <details className="text-xs text-slate-600">
                  <summary className="cursor-pointer font-semibold">Dernières actions sur les adresses ({donnees.actions.length})</summary>
                  <ul className="mt-2 space-y-0.5">
                    {donnees.actions.map((a, i) => (
                      <li key={i}>
                        {dateHeureOuaga(a.date)} · {a.action === "BLOQUER" ? "Blocage" : "Autorisation"} de <span className="font-mono">{a.ip}</span>
                        {a.libelle ? ` « ${a.libelle} »` : ""}
                        {" "}({a.portee === "globale" ? "tous les comptes" : a.user_email || "ce compte"}) par {a.par || "?"}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
          {!donnees && <p className="text-sm text-slate-500">Chargement…</p>}
        </div>
      </div>
    </div>
  );
}

// Lot 55 — « Sites bloqués (toute la plateforme) » : super-admin, ouvert depuis la page Utilisateurs
// suivis. Pour chaque site : IP, libellé, auteur, date du blocage, tentatives refusées depuis.
export function SitesBloquesDialog({ onClose }) {
  const [items, setItems] = useState(null);
  const [occupe, setOccupe] = useState("");
  const charger = useCallback(() => apiClient.get("/admin/connexions/sites-bloques")
    .then((r) => setItems(r.data?.items || []))
    .catch((err) => { setItems([]); toast.error(err?.response?.data?.detail || "Chargement impossible"); }), []);
  useEffect(() => { charger(); }, [charger]);

  const autoriser = async (s) => {
    if (!window.confirm(`Autoriser de nouveau l'adresse ${s.ip}${s.libelle ? ` (${s.libelle})` : ""} sur toute la plateforme ?`)) return;
    setOccupe(s.ip);
    try {
      await apiClient.post("/admin/connexions/sites-bloques/autoriser", { ip: s.ip });
      toast.success(`Adresse ${s.ip} autorisée`);
      await charger();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible");
    } finally { setOccupe(""); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-4xl max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()} data-testid="sites-bloques-dialog">
        <div className="flex items-center justify-between p-4 border-b">
          <div>
            <h3 className="font-display font-semibold inline-flex items-center gap-2"><Ban className="h-4 w-4 text-rose-600" /> Sites bloqués (toute la plateforme)</h3>
            <p className="text-xs text-slate-500 mt-0.5">Une adresse IP correspond à un lieu ou à un réseau (Wi-Fi, box), pas à une personne. Heures de Ouagadougou.</p>
          </div>
          <button onClick={onClose} aria-label="Fermer"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-4 overflow-y-auto">
          {items === null ? <p className="text-sm text-slate-500">Chargement…</p> : items.length === 0 ? (
            <p className="text-sm text-slate-500">Aucun site bloqué sur toute la plateforme.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
              <table className="w-full text-sm min-w-[720px]">
                <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                  <tr>
                    <th className="text-left px-3 py-2">Adresse IP</th>
                    <th className="text-left px-3 py-2">Libellé du site</th>
                    <th className="text-left px-3 py-2">Bloqué par</th>
                    <th className="text-left px-3 py-2">Le</th>
                    <th className="text-right px-3 py-2">Tentatives refusées</th>
                    <th className="text-right px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((s) => (
                    <tr key={s.ip} className="border-t border-slate-100" data-testid={`site-bloque-${s.ip}`}>
                      <td className="px-3 py-2 font-mono text-xs">{s.ip}</td>
                      <td className="px-3 py-2">{s.libelle || <span className="text-slate-400">—</span>}</td>
                      <td className="px-3 py-2 text-slate-600">{s.par || "—"}</td>
                      <td className="px-3 py-2 whitespace-nowrap">{dateHeureOuaga(s.date)}</td>
                      <td className="px-3 py-2 text-right">{s.tentatives_refusees ?? 0}</td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => autoriser(s)} disabled={!!occupe}
                          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ring-1 ring-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                          data-testid={`autoriser-site-${s.ip}`}>
                          <CheckCircle2 className="h-3 w-3" /> Autoriser
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
