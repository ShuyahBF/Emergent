// ContratsPlateformes.jsx — Lot 81 : CONTRAT de chaque plateforme cliente (ALBARKA…), dans « Plateformes en temps réel ».
//
// Pour chaque plateforme (émetteur de la transmission WhatsApp universelle) :
//   - client SAWALI rattaché (les paramètres du contrat vivent sur sa fiche client/tenant) ;
//   - n° de contrat, début (ex. 15/10/2026), échéance, prestations et services (libellé + montant), montant total ;
//   - payé, montant dû, état (à jour / échéance proche en orange / dépassée / renouvellement urgent en rouge) ;
//   - historique des paiements (ceux de la fiche client) et bouton « Enregistrer un paiement ».
// La plateforme lit elle-même cet état (requête signée) pour afficher le bandeau orange ou rouge à son DG.
// Lot 82 : bandeau seulement de J−5 (orange) à J+5 (rouge), plus rien ensuite ; cases « Services suspendus
// automatiquement » (WA, e-mails, comptes rendus…) : bloqués chez la plateforme dès que le contrat est échu.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";

// « 1 500 000 XOF »
const argent = (v, devise = "XOF") => `${Math.round(Number(v) || 0).toLocaleString("fr-FR")} ${devise}`;
// « 15/10/2026 »
const jour = (iso) => (iso ? String(iso).slice(0, 10).split("-").reverse().join("/") : "—");
// Lot 82.1 : « AAAA-MM-JJ » + n jours → « AAAA-MM-JJ » (calcul en UTC : pas de décalage de fuseau horaire)
const ajouterJours = (iso, n) => {
  if (!iso || !Number.isFinite(n)) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
// Lot 82.1 : nombre de jours entre deux dates « AAAA-MM-JJ » ("" si l'une manque)
const ecartJours = (debut, fin) => (debut && fin
  ? String(Math.round((Date.parse(`${fin.slice(0, 10)}T00:00:00Z`) - Date.parse(`${debut.slice(0, 10)}T00:00:00Z`)) / 86400000))
  : "");
// Durées proposées dans la liste (le propriétaire peut aussi taper un nombre de jours)
const DUREES = [30, 90, 180, 365, 730];

const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

// Pastille de l'état du contrat (orange avant l'échéance, rouge juste après, gris foncé une fois échu)
function Etat({ etat }) {
  if (!etat) return null;
  const cls = etat.couleur === "rouge" ? "bg-rose-100 text-rose-800" : etat.couleur === "orange" ? "bg-amber-100 text-amber-800"
    : etat.niveau === "ok" ? "bg-emerald-100 text-emerald-800" : etat.niveau === "echu" ? "bg-slate-700 text-white" : "bg-slate-100 text-slate-600";
  const jours = etat.jours_restants;
  const precision = jours == null ? "" : jours >= 0 ? ` · J−${jours}` : ` · J+${-jours}`;
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{etat.libelle}{precision}</span>;
}

// Formulaire du contrat d'une plateforme (rattachement client + paramètres + lignes)
function FormulaireContrat({ contrat, clients, catalogue, onEnregistre, onAnnuler }) {
  const [f, setF] = useState({
    client_id: contrat.client?.id || "", numero: contrat.numero || "", devise: contrat.devise || "XOF",
    debut: (contrat.debut || "2026-10-15").slice(0, 10), fin: (contrat.fin || "").slice(0, 10),
    montant: contrat.finances?.montant != null && contrat.finances?.montant !== contrat.finances?.somme_lignes ? contrat.finances.montant : "",
    alerte_avant_jours: contrat.alerte_avant_jours ?? 5, alerte_apres_jours: contrat.alerte_apres_jours ?? 5,
    services_suspendus: contrat.services_a_suspendre || [],   // lot 82 : cases cochées
    lignes: (contrat.lignes || []).length ? contrat.lignes : [{ type: "prestation", libelle: "Développement", montant: "" }],
  });
  const [enCours, setEnCours] = useState(false);
  // Lot 82.1 : durée en jours ↔ échéance (l'une calcule l'autre) ; lot 82.3 : le début ne déplace plus l'échéance
  const [duree, setDuree] = useState(ecartJours((contrat.debut || "2026-10-15").slice(0, 10), (contrat.fin || "").slice(0, 10)));
  const changerDuree = (valeur) => {
    setDuree(valeur);
    const n = parseInt(valeur, 10);
    if (Number.isFinite(n) && n > 0) setF((avant) => ({ ...avant, fin: ajouterJours(avant.debut, n) }));
  };
  // Lot 82.3 : changer le début ne déplace JAMAIS l'échéance (seule la saisie d'une durée la calcule) ;
  // la durée affichée est simplement recalculée
  const changerDebut = (valeur) => {
    setF((avant) => ({ ...avant, debut: valeur }));
    setDuree(ecartJours(valeur, f.fin));
  };
  const changerFin = (valeur) => { setF((avant) => ({ ...avant, fin: valeur })); setDuree(ecartJours(f.debut, valeur)); };
  const total = f.lignes.reduce((s, l) => s + (Number(l.montant) || 0), 0);
  // Lot 82 : coche / décoche un service suspendu automatiquement
  const basculer = (code) => setF({ ...f, services_suspendus: f.services_suspendus.includes(code)
    ? f.services_suspendus.filter((c) => c !== code) : [...f.services_suspendus, code] });
  const majLigne = (i, champ, valeur) => setF({ ...f, lignes: f.lignes.map((l, k) => (k === i ? { ...l, [champ]: valeur } : l)) });

  const enregistrer = async () => {
    setEnCours(true);
    const attente = toast.loading("Patientez…");
    try {
      const r = await apiClient.put(`/admin/plateformes/${contrat.code}/contrat`, { ...f, montant: f.montant === "" ? null : f.montant });
      toast.success("Contrat enregistré", { id: attente });
      onEnregistre(r.data);
    } catch (e) {
      toast.error(erreur(e, "Enregistrement impossible"), { id: attente });
    } finally { setEnCours(false); }
  };

  const champ = "mt-1 w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm";
  return (
    <div className="space-y-3 rounded-lg border border-sky-200 bg-sky-50/40 p-3" data-testid={`contrat-form-${contrat.code}`}>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="text-xs sm:col-span-3"><span className="font-semibold">Client SAWALI (fiche où vit le contrat)</span>
          <select value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })} className={champ}>
            <option value="">— choisir —</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.company || c.full_name || c.email}{c.client_code ? ` (${c.client_code})` : ""}</option>)}
          </select></label>
        <label className="text-xs"><span className="font-semibold">N° de contrat</span>
          <input value={f.numero} onChange={(e) => setF({ ...f, numero: e.target.value })} className={champ} placeholder="CTR-ALB-2026-01" /></label>
        <label className="text-xs"><span className="font-semibold">Début</span>
          <input type="date" value={f.debut} onChange={(e) => changerDebut(e.target.value)} className={champ} /></label>
        <label className="text-xs"><span className="font-semibold">Échéance</span>
          <input type="date" value={f.fin} onChange={(e) => changerFin(e.target.value)} className={champ} /></label>
        {/* Lot 82.1 : durée en jours — choisie dans la liste ou tapée ; l'échéance = début + durée */}
        <label className="text-xs sm:col-start-3"><span className="font-semibold">Durée (jours) → calcule l'échéance</span>
          <input type="number" min="1" list="durees-contrat" value={duree} onChange={(e) => changerDuree(e.target.value)}
            className={champ} placeholder="ex. 365" data-testid={`contrat-duree-${contrat.code}`} />
          <datalist id="durees-contrat">{DUREES.map((n) => <option key={n} value={n} />)}</datalist></label>
      </div>
      {/* Prestations et services */}
      <div>
        <p className="text-xs font-semibold">Prestations et services</p>
        {f.lignes.map((l, i) => (
          <div key={i} className="mt-1 flex flex-wrap items-center gap-2">
            <select value={l.type} onChange={(e) => majLigne(i, "type", e.target.value)} className="rounded border border-slate-300 px-1 py-1 text-xs">
              <option value="prestation">Prestation</option><option value="service">Service</option>
            </select>
            <input value={l.libelle} onChange={(e) => majLigne(i, "libelle", e.target.value)} placeholder="Développement, maintenance, hébergement, coûts Meta/WA…"
              className="min-w-[12rem] flex-1 rounded border border-slate-300 px-2 py-1 text-xs" />
            <input type="number" min="0" value={l.montant} onChange={(e) => majLigne(i, "montant", e.target.value)} placeholder="Montant"
              className="w-32 rounded border border-slate-300 px-2 py-1 text-right text-xs" />
            <button type="button" onClick={() => setF({ ...f, lignes: f.lignes.filter((_, k) => k !== i) })} className="text-xs text-rose-700">Retirer</button>
          </div>
        ))}
        <button type="button" onClick={() => setF({ ...f, lignes: [...f.lignes, { type: "service", libelle: "", montant: "" }] })}
          className="mt-1 text-xs text-sky-700 underline">+ Ajouter une ligne</button>
        <p className="mt-1 text-xs text-slate-600">Total des lignes : <b>{argent(total, f.devise)}</b></p>
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        <label className="text-xs"><span className="font-semibold">Montant du contrat</span>
          <input type="number" min="0" value={f.montant} onChange={(e) => setF({ ...f, montant: e.target.value })} className={champ} placeholder="vide = total des lignes" /></label>
        <label className="text-xs"><span className="font-semibold">Devise</span>
          <input value={f.devise} onChange={(e) => setF({ ...f, devise: e.target.value.toUpperCase() })} className={champ} /></label>
        <label className="text-xs"><span className="font-semibold">Orange : jours avant</span>
          <input type="number" min="0" max="90" value={f.alerte_avant_jours} onChange={(e) => setF({ ...f, alerte_avant_jours: e.target.value })} className={champ} /></label>
        <label className="text-xs"><span className="font-semibold">Rouge : jours après</span>
          <input type="number" min="0" max="90" value={f.alerte_apres_jours} onChange={(e) => setF({ ...f, alerte_apres_jours: e.target.value })} className={champ} /></label>
      </div>
      {/* Lot 82 : services suspendus automatiquement chez la plateforme une fois le contrat échu (après J+jours) */}
      <div data-testid={`contrat-services-${contrat.code}`}>
        <p className="text-xs font-semibold">Services suspendus automatiquement (contrat échu depuis plus de {f.alerte_apres_jours} jours)</p>
        <div className="mt-1 grid gap-1 sm:grid-cols-2">
          {catalogue.map((s) => (
            <label key={s.code} className="flex cursor-pointer items-start gap-2 text-xs" title={s.description}>
              <input type="checkbox" className="mt-0.5" checked={f.services_suspendus.includes(s.code)} onChange={() => basculer(s.code)} />
              <span><b>{s.libelle}</b> <span className="text-slate-500">— {s.description}</span></span>
            </label>
          ))}
        </div>
        <p className="mt-1 text-[11px] text-slate-500">Rien de coché = aucune suspension. Repousser l'échéance (renouvellement) rouvre aussitôt les services.</p>
      </div>
      <div className="flex gap-2">
        <button type="button" disabled={enCours} onClick={enregistrer} className="rounded-lg bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          {enCours ? "Patientez…" : "Enregistrer le contrat"}</button>
        <button type="button" onClick={onAnnuler} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm">Annuler</button>
      </div>
    </div>
  );
}

// Saisie d'un paiement reçu (même route que la fiche client : historique unique)
function NouveauPaiement({ contrat, onEnregistre }) {
  const [p, setP] = useState({ payment_date: new Date().toISOString().slice(0, 10), amount_paid: "", invoice_ref: "", notes: "" });
  const [enCours, setEnCours] = useState(false);
  const enregistrer = async () => {
    setEnCours(true);
    const attente = toast.loading("Patientez…");
    try {
      await apiClient.post(`/admin/clients/${contrat.client.id}/payments`, {
        ...p, amount_paid: Number(p.amount_paid), amount_due: contrat.finances?.du ?? null, send_confirmation: true,
      });
      toast.success("Paiement enregistré", { id: attente });
      setP({ ...p, amount_paid: "", invoice_ref: "", notes: "" });
      onEnregistre();
    } catch (e) {
      toast.error(erreur(e, "Paiement non enregistré"), { id: attente });
    } finally { setEnCours(false); }
  };
  return (
    <div className="flex flex-wrap items-end gap-2 text-xs">
      <label>Date<input type="date" value={p.payment_date} onChange={(e) => setP({ ...p, payment_date: e.target.value })} className="ml-1 rounded border border-slate-300 px-1 py-0.5" /></label>
      <label>Montant<input type="number" min="0" value={p.amount_paid} onChange={(e) => setP({ ...p, amount_paid: e.target.value })} className="ml-1 w-28 rounded border border-slate-300 px-1 py-0.5 text-right" /></label>
      <label>Réf.<input value={p.invoice_ref} onChange={(e) => setP({ ...p, invoice_ref: e.target.value })} className="ml-1 w-28 rounded border border-slate-300 px-1 py-0.5" placeholder="facture…" /></label>
      <button type="button" disabled={enCours || !(Number(p.amount_paid) > 0)} onClick={enregistrer}
        className="rounded bg-emerald-600 px-2 py-1 font-semibold text-white disabled:opacity-50">Enregistrer un paiement</button>
    </div>
  );
}

export default function ContratsPlateformes() {
  const [contrats, setContrats] = useState(null);
  const [catalogue, setCatalogue] = useState([]);    // lot 82 : services pouvant être suspendus
  const [clients, setClients] = useState([]);
  const [edition, setEdition] = useState(null);       // code de la plateforme en cours de modification
  const [selection, setSelection] = useState(null);   // ligne de paiement sélectionnée (règle 3)

  const charger = useCallback(() => {
    apiClient.get("/admin/plateformes/contrats").then((r) => { setContrats(r.data.contrats); setCatalogue(r.data.services_catalogue || []); }).catch(() => setContrats([]));
  }, []);
  useEffect(() => {
    charger();
    apiClient.get("/admin/clients", { params: { role: "client" } }).then((r) => setClients(Array.isArray(r.data) ? r.data : (r.data?.items || []))).catch(() => {});
  }, [charger]);

  if (!contrats) return <p className="text-sm text-slate-500">Patientez…</p>;
  return (
    <section className="space-y-3" data-testid="contrats-plateformes">
      <h2 className="text-xl font-display font-bold">📑 Contrats des plateformes</h2>
      {contrats.length === 0 && <p className="text-sm text-slate-500">Aucune plateforme déclarée.</p>}
      {contrats.map((c) => {
        const f = c.finances || {};
        return (
          <div key={c.code} className="space-y-2 rounded-xl border border-slate-200 bg-white p-4" data-testid={`contrat-${c.code}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="font-semibold">{c.nom} {c.numero && <span className="ml-1 font-mono text-sm text-teal-700">{c.numero}</span>}</p>
                <p className="text-xs text-slate-500">
                  {c.client ? <>Client SAWALI : <b>{c.client.nom}</b> · du {jour(c.debut)} au {jour(c.fin)}</> : "Aucun client SAWALI rattaché"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Etat etat={c.etat} />
                <button type="button" onClick={() => setEdition(edition === c.code ? null : c.code)} className="rounded-lg border border-slate-300 px-2 py-1 text-xs">
                  {c.client ? "Modifier le contrat" : "Définir le contrat"}</button>
              </div>
            </div>
            {edition === c.code && (
              <FormulaireContrat contrat={c} clients={clients} catalogue={catalogue} onAnnuler={() => setEdition(null)}
                onEnregistre={() => { setEdition(null); charger(); }} />
            )}
            {c.client && (
              <>
                {/* Montants : contrat, prestations / services, payé, dû */}
                <div className="grid gap-2 text-sm sm:grid-cols-4">
                  <div className="rounded-lg bg-slate-50 p-2"><p className="text-[11px] text-slate-500">Montant du contrat</p><p className="font-semibold">{argent(f.montant, c.devise)}</p>
                    <p className="text-[11px] text-slate-500">Prestations {argent(f.prestations, c.devise)} · Services {argent(f.services, c.devise)}</p></div>
                  <div className="rounded-lg bg-emerald-50 p-2"><p className="text-[11px] text-slate-500">Payé depuis le {jour(c.debut)}</p><p className="font-semibold text-emerald-800">{argent(f.paye, c.devise)}</p></div>
                  <div className={`rounded-lg p-2 ${f.du > 0 ? "bg-amber-50" : "bg-slate-50"}`}><p className="text-[11px] text-slate-500">Montant dû</p><p className={`font-semibold ${f.du > 0 ? "text-amber-800" : ""}`}>{argent(f.du, c.devise)}</p></div>
                  <div className="rounded-lg bg-slate-50 p-2"><p className="text-[11px] text-slate-500">Alertes chez le DG</p><p className="text-xs">orange J−{c.alerte_avant_jours} · rouge J+{c.alerte_apres_jours} · puis aucun bandeau</p></div>
                </div>
                {/* Lot 82 : services cochés, suspendus ou à suspendre */}
                {(c.services_a_suspendre || []).length > 0 && (
                  <p className={`rounded-lg p-2 text-xs ${(c.services_suspendus || []).length ? "bg-rose-50 text-rose-800" : "bg-slate-50 text-slate-700"}`}>
                    {/* Lot 82.2 : libellé selon l'état — déjà suspendus (échéance dépassée) ou suspension à venir */}
                    {(c.services_suspendus || []).length
                      ? <>⛔ Suspendus depuis le <b>{jour(c.suspension_le)}</b> (échéance du {jour(c.fin)} dépassée de plus de {c.alerte_apres_jours} jours) — repoussez l'échéance pour les rétablir :{" "}</>
                      : <>Suspendus automatiquement à partir du <b>{jour(c.suspension_le)}</b> si le contrat n'est pas renouvelé :{" "}</>}
                    {c.services_a_suspendre.map((code) => catalogue.find((s) => s.code === code)?.libelle || code).join(", ")}
                  </p>
                )}
                {(c.lignes || []).length > 0 && (
                  <ul className="text-xs text-slate-600">
                    {c.lignes.map((l, i) => <li key={i}>{l.type === "service" ? "Service" : "Prestation"} — {l.libelle} : {argent(l.montant, c.devise)}</li>)}
                  </ul>
                )}
                {/* Historique des paiements */}
                <div>
                  <p className="text-xs font-semibold text-slate-700">Historique des paiements</p>
                  {(c.paiements || []).length === 0 ? <p className="text-xs text-slate-500">Aucun paiement.</p> : (
                    <table className="mt-1 w-full text-xs">
                      <thead className="text-left text-slate-500"><tr><th className="py-1">Date</th><th>Montant</th><th>Réf.</th><th>Mode</th><th>Saisi par</th></tr></thead>
                      <tbody>
                        {c.paiements.map((p) => (
                          <tr key={p.id || `${p.payment_date}-${p.amount_paid}`} className={`border-t border-slate-100 ${selection === p.id ? "ligne-selectionnee" : ""}`} onClick={() => setSelection(p.id)}>
                            <td className="py-1">{jour(p.payment_date)}</td><td>{argent(p.amount_paid, c.devise)}</td><td>{p.invoice_ref || "—"}</td>
                            <td>{p.payment_method_label || "—"}</td><td>{p.created_by_email || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  <div className="mt-2"><NouveauPaiement contrat={c} onEnregistre={charger} /></div>
                </div>
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}
