// ============================================================================
// PointageSouscription.jsx — Lot 500 : SOUSCRIPTION AU POINTAGE (formules semaine, mois, année, illimité).
//   - <SouscriptionEspace> : carte « Ma souscription » de l'Espace pointage (responsable du commerce) : état, choix de la formule et de
//     l'opérateur, séquence USSD avec le code marchand (lien « tel: » qui ouvre le clavier du téléphone, ou copie), référence de la transaction
//     → vérification automatique par le SMS de paiement reçu (Transactions SMS), sinon par l'administrateur ; historique des demandes.
//   - <SouscriptionsAdmin> : Paramètres → prix des formules, devise, codes marchands ; demandes à vérifier EN HAUT (valider / refuser / relancer
//     le rapprochement SMS) ; souscription enregistrée à la main (espèces, virement).
// Backend : /api/pointage-espace/souscription, /api/admin/pointage-tarifs, /api/admin/pointage-souscriptions (routes/pointage_telephone.py).
// Parallèle WinDev : un contrôle de licence (table Abonnement) avec sa fenêtre de renouvellement.
// ============================================================================
import React, { useCallback, useEffect, useState } from "react";
import { BadgeCheck, Ban, Check, Copy, CreditCard, Phone, RefreshCw, Save, Search, X } from "lucide-react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const dateCourte = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
const nombre = (n) => (n === null || n === undefined ? "—" : Number(n).toLocaleString("fr-FR"));
export const FORMULES = { semaine: "Semaine", mois: "Mois", annee: "Année", illimite: "Illimité" };
const STATUTS = { en_attente: ["En attente de vérification", "bg-amber-100 text-amber-800"], verifiee: ["Vérifiée", "bg-emerald-100 text-emerald-800"],
  refusee: ["Refusée", "bg-red-100 text-red-800"] };

/** Pastille d'état d'une souscription (texte + couleur, jamais la couleur seule). */
export function PastilleSouscription({ etat, t = (x) => x }) {
  if (!etat) return null;
  if (etat.valide) {
    return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">
      ✓ {etat.illimite ? t("Souscription illimitée") : t("Souscription valide jusqu'au {d}", { d: dateCourte(etat.fin) })}</span>;
  }
  return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-800">
    ✕ {t("Sans souscription valide")}{etat.en_attente ? ` · ${t("{n} demande(s) en attente", { n: etat.en_attente })}` : ""}</span>;
}

/** Bouton rond à pictogramme (règle du 27/11/2026). */
function Picto({ titre, Icone, onClick, couleur, disabled = false }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={titre} aria-label={titre}
            className={`inline-flex h-11 w-11 items-center justify-center rounded-full shadow-sm disabled:opacity-40 ${couleur}`}>
      <Icone className="h-5 w-5" aria-hidden="true" />
    </button>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Espace pointage : « Ma souscription »
// ---------------------------------------------------------------------------------------------------------------------------
export function SouscriptionEspace({ espace, t, onChange }) {
  const [d, setD] = useState(null);
  const [formule, setFormule] = useState("");
  const [operateur, setOperateur] = useState("");
  const [reference, setReference] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const entetes = { headers: { "X-Pointage-Jeton": espace.jeton } };

  const charger = useCallback(async (avecToast = false) => {
    const id = avecToast ? toast.loading(t("Actualisation en cours…")) : null;
    try {
      const { data } = await apiClient.get("/pointage-espace/souscription", entetes);
      setD(data); onChange?.(data.etat);
      if (id) toast.success(t("Souscription relue."), { id });
    } catch (e) {
      if (e.response?.status === 401) espace.onExpire?.();
      if (id) toast.error(e.response?.data?.detail || t("Lecture impossible."), { id });
    }
  }, [espace.jeton]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { charger(); }, [charger]);

  const op = d?.operateurs?.find((o) => o.id === operateur);
  const choix = op?.formules?.[formule];
  const formulesProposees = Object.keys(d?.tarifs || {}).filter((f) => d.tarifs[f]);

  const envoyer = async () => {
    setEnvoi(true);
    const id = toast.loading(t("Vérification du paiement en cours…"));
    try {
      const { data } = await apiClient.post("/pointage-espace/souscription", { formule, operateur, reference }, entetes);
      if (data.souscription.statut === "verifiee") toast.success(t("Paiement vérifié : souscription active."), { id });
      else toast.info(t("Demande enregistrée : elle sera vérifiée dès réception du SMS de paiement, ou par SAWALI."), { id });
      setReference(""); charger();
    } catch (e) { toast.error(e.response?.data?.detail || t("Envoi impossible."), { id }); }
    setEnvoi(false);
  };

  if (!d) return null;
  return (
    <section className={`rounded-2xl border-2 p-4 ${d.etat.valide ? "border-emerald-300 bg-emerald-50" : "border-red-300 bg-red-50"}`} data-testid="souscription-espace">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 font-bold text-slate-900"><BadgeCheck className="h-5 w-5 text-violet-600" aria-hidden="true" />{t("Ma souscription au pointage")}</p>
        <div className="flex items-center gap-2"><PastilleSouscription etat={d.etat} t={t} />
          <Picto titre={t("Actualiser")} Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-white text-slate-700" /></div>
      </div>
      {!d.etat.valide && <p className="mt-2 text-sm text-red-800">{t("Sans souscription vérifiée, ni l'Espace ni les téléphones ne peuvent pointer. Les saisies déjà comptées pendant une période payée peuvent encore être envoyées.")}</p>}

      {/* Renouveler / souscrire : formule, opérateur, séquence USSD, référence */}
      {formulesProposees.length > 0 && d.operateurs.length > 0 ? (
        <div className="mt-3 space-y-2 rounded-xl bg-white p-3">
          <p className="text-sm font-semibold">{d.etat.valide ? t("Prolonger la souscription") : t("Souscrire")}</p>
          <div className="flex flex-wrap gap-2">
            <select value={formule} onChange={(e) => setFormule(e.target.value)} className="rounded-lg border px-2 py-2" aria-label={t("Formule")}>
              <option value="">— {t("Formule")} —</option>
              {formulesProposees.map((f) => <option key={f} value={f}>{t(FORMULES[f])} · {nombre(d.tarifs[f])} {d.devise}</option>)}
            </select>
            <select value={operateur} onChange={(e) => setOperateur(e.target.value)} className="rounded-lg border px-2 py-2" aria-label={t("Opérateur")}>
              <option value="">— {t("Opérateur")} —</option>
              {d.operateurs.map((o) => <option key={o.id} value={o.id}>{o.nom}</option>)}
            </select>
          </div>
          {choix && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-violet-200 bg-violet-50 p-2">
              <code className="text-lg font-bold tracking-wider text-violet-800">{choix.sequence}</code>
              <a href={choix.lien} title={t("Composer sur ce téléphone")} aria-label={t("Composer sur ce téléphone")}
                 className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-emerald-600 text-white"><Phone className="h-5 w-5" aria-hidden="true" /></a>
              <Picto titre={t("Copier la séquence")} Icone={Copy} couleur="bg-sky-100 text-sky-700"
                     onClick={() => navigator.clipboard?.writeText(choix.sequence).then(() => toast.success(t("Séquence copiée.")))} />
              <span className="basis-full text-xs text-slate-600">{t("Payez avec cette séquence, puis saisissez la référence (ID) de la transaction reçue par SMS.")}</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="PP251128.1234.A00001" maxLength={60}
                   className="min-w-0 flex-1 rounded-lg border px-3 py-2 font-mono" aria-label={t("Référence de la transaction")} />
            <Picto titre={t("Envoyer la référence pour vérification")} Icone={Check} onClick={envoyer} couleur="bg-emerald-600 text-white"
                   disabled={envoi || !formule || !operateur || reference.trim().length < 4} />
          </div>
        </div>
      ) : <p className="mt-2 text-sm text-slate-600">{t("Les formules ne sont pas encore proposées : contactez SAWALI.")}</p>}

      {d.historique.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {d.historique.slice(0, 6).map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-2">
              <span className={`rounded px-1.5 text-xs font-semibold ${STATUTS[h.statut]?.[1]}`}>{t(STATUTS[h.statut]?.[0] || h.statut)}</span>
              <b>{t(FORMULES[h.formule])}</b> · {nombre(h.montant)} {h.devise} · <span className="font-mono text-xs">{h.reference}</span>
              <span className="text-xs text-slate-500">{dateCourte(h.demandee_le)}{h.fin ? ` → ${dateCourte(h.fin)}` : h.statut === "verifiee" ? ` → ${t("Illimité")}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------------------------------
// Administration : prix, codes marchands, demandes à vérifier, souscription manuelle
// ---------------------------------------------------------------------------------------------------------------------------
export function SouscriptionsAdmin() {
  const [tarifs, setTarifs] = useState({ tarifs: {}, codes: {}, devise: "FCFA" });
  const [operateurs, setOperateurs] = useState({});
  const [liste, setListe] = useState([]);
  const [modifie, setModifie] = useState(false);

  const charger = useCallback(async (avecToast = false) => {
    const id = avecToast ? toast.loading("Actualisation en cours…") : null;
    try {
      const [t, s] = await Promise.all([apiClient.get("/admin/pointage-tarifs"), apiClient.get("/admin/pointage-souscriptions")]);
      setTarifs({ tarifs: t.data.tarifs, codes: t.data.codes, devise: t.data.devise }); setOperateurs(t.data.operateurs || {});
      setListe(s.data.souscriptions || []); setModifie(false);
      if (id) toast.success(`${s.data.souscriptions.length} souscription(s) relue(s).`, { id });
    } catch (e) { if (id) toast.error(e.response?.data?.detail || "Lecture impossible.", { id }); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const enregistrer = async () => {
    const id = toast.loading("Enregistrement des prix en cours…");
    try { await apiClient.put("/admin/pointage-tarifs", tarifs); toast.success("Prix et codes marchands enregistrés.", { id }); setModifie(false); }
    catch (e) { toast.error(e.response?.data?.detail || "Enregistrement impossible.", { id }); }
  };
  const decider = async (s, action) => {
    const id = toast.loading("En cours…");
    try {
      const { data } = await apiClient.post(`/admin/pointage-souscriptions/${s.id}/${action}`);
      toast.success(action === "valider" ? "Souscription vérifiée : le commerce peut pointer." : action === "refuser" ? "Demande refusée."
        : data.statut === "verifiee" ? "SMS de paiement trouvé : souscription vérifiée." : "Aucun SMS de paiement correspondant pour l'instant.", { id });
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || "Action impossible.", { id }); }
  };
  const { lignes, tri, basculer } = useTri(liste, {
    statut: (s) => s.statut, commerce: (s) => s.commerce, formule: (s) => s.formule, montant: (s) => s.montant, reference: (s) => s.reference,
    demandee: (s) => s.demandee_le, fin: (s) => s.fin,
  });
  const champ = (cle, sous, v) => { setTarifs((t) => ({ ...t, [cle]: { ...t[cle], [sous]: v } })); setModifie(true); };

  return (
    <div className="space-y-3 pt-3" data-testid="souscriptions-admin">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-2 font-semibold"><CreditCard className="h-4 w-4 text-violet-600" aria-hidden="true" />Souscriptions au pointage (web et Loois Mobile)</p>
        <Picto titre="Actualiser les souscriptions" Icone={RefreshCw} onClick={() => charger(true)} couleur="bg-slate-100 text-slate-700" />
      </div>
      {/* Prix des formules et codes marchands */}
      <div className="grid gap-2 rounded-xl border p-3 sm:grid-cols-2">
        <div className="space-y-1">
          <p className="text-sm font-semibold">Prix par formule (vide = non proposée)</p>
          {Object.entries(FORMULES).map(([f, l]) => (
            <label key={f} className="flex items-center gap-2 text-sm"><span className="w-20">{l}</span>
              <input value={tarifs.tarifs[f] ?? ""} inputMode="numeric" placeholder="7500" onChange={(e) => champ("tarifs", f, e.target.value.replace(/\D/g, ""))}
                     className="w-28 rounded-lg border px-2 py-1 text-right tabular-nums" aria-label={`Prix ${l}`} />
              <span className="text-slate-500">{tarifs.devise}</span></label>
          ))}
        </div>
        <div className="space-y-1">
          <p className="text-sm font-semibold">Codes marchands (paiement USSD)</p>
          {Object.entries(operateurs).map(([op, nom]) => (
            <label key={op} className="flex items-center gap-2 text-sm"><span className="w-28">{nom}</span>
              <input value={tarifs.codes[op] ?? ""} inputMode="numeric" placeholder="123456" onChange={(e) => champ("codes", op, e.target.value.replace(/\D/g, ""))}
                     className="w-32 rounded-lg border px-2 py-1 font-mono" aria-label={`Code marchand ${nom}`} /></label>
          ))}
        </div>
        <div className="flex items-center justify-end gap-2 sm:col-span-2">
          {modifie && <span className="text-xs text-amber-700">modifié, non enregistré</span>}
          <Picto titre="Enregistrer les prix et codes marchands" Icone={Save} onClick={enregistrer} couleur="bg-emerald-600 text-white" disabled={!modifie} />
        </div>
      </div>
      {/* Demandes (à vérifier en haut) */}
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-slate-50"><tr>
            <ThTri cle="statut" tri={tri} onTri={basculer}>État</ThTri>
            <ThTri cle="commerce" tri={tri} onTri={basculer}>Commerce</ThTri>
            <ThTri cle="formule" tri={tri} onTri={basculer}>Formule</ThTri>
            <ThTri cle="montant" tri={tri} onTri={basculer} droite>Montant</ThTri>
            <ThTri cle="reference" tri={tri} onTri={basculer}>Référence</ThTri>
            <ThTri cle="demandee" tri={tri} onTri={basculer}>Demandée le</ThTri>
            <ThTri cle="fin" tri={tri} onTri={basculer}>Fin</ThTri>
            <th className="p-2">Actions</th>
          </tr></thead>
          <tbody>
            {lignes.map((s) => (
              <tr key={s.id} className="border-t">
                <td className="p-2"><span className={`rounded px-1.5 text-xs font-semibold ${STATUTS[s.statut]?.[1]}`}>{STATUTS[s.statut]?.[0]}</span></td>
                <td className="p-2 font-semibold">{s.commerce}<span className="block font-mono text-xs text-sky-700">{s.cle}</span></td>
                <td className="p-2">{FORMULES[s.formule]}</td>
                <td className="p-2 text-right tabular-nums text-emerald-700">{nombre(s.montant)} {s.devise}</td>
                <td className="p-2 font-mono text-xs">{s.reference}{s.verifiee_par ? <span className="block text-slate-500">{s.verifiee_par}</span> : null}</td>
                <td className="p-2 whitespace-nowrap">{dateCourte(s.demandee_le)}</td>
                <td className="p-2 whitespace-nowrap">{s.statut === "verifiee" ? (s.fin ? dateCourte(s.fin) : "Illimité") : "—"}</td>
                <td className="p-2">
                  {s.statut === "en_attente" && (
                    <div className="flex gap-1">
                      <button type="button" onClick={() => decider(s, "verifier")} title="Chercher le SMS de paiement" aria-label="Chercher le SMS de paiement"
                              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-sky-100 text-sky-700"><Search className="h-4 w-4" aria-hidden="true" /></button>
                      <button type="button" onClick={() => decider(s, "valider")} title="Valider (paiement constaté)" aria-label="Valider (paiement constaté)"
                              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"><Check className="h-4 w-4" aria-hidden="true" /></button>
                      <button type="button" onClick={() => window.confirm("Refuser cette demande ?") && decider(s, "refuser")} title="Refuser" aria-label="Refuser"
                              className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-rose-100 text-rose-700"><Ban className="h-4 w-4" aria-hidden="true" /></button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {!lignes.length && <tr><td colSpan={8} className="p-3 text-center text-slate-500">Aucune souscription pour l'instant.</td></tr>}
          </tbody>
          <tfoot className="border-t-2 bg-slate-50 font-semibold"><tr>
            <td className="p-2" colSpan={3}>{lignes.length} souscription(s) · {lignes.filter((s) => s.statut === "en_attente").length} en attente</td>
            <td className="p-2 text-right tabular-nums">{nombre(lignes.filter((s) => s.statut === "verifiee").reduce((t, s) => t + (s.montant || 0), 0))}</td>
            <td colSpan={4} />
          </tr></tfoot>
        </table>
      </div>
    </div>
  );
}

/** Fenêtre « Enregistrer une souscription » pour un commerce (paiement en espèces, virement…) : vérifiée aussitôt. */
export function FenetreSouscriptionManuelle({ commerce, onFermer, onFait }) {
  const [formule, setFormule] = useState("mois");
  const [note, setNote] = useState("");
  const enregistrer = async () => {
    const id = toast.loading("Enregistrement de la souscription…");
    try {
      const { data } = await apiClient.post("/admin/pointage-souscriptions", { acces_id: commerce.id, formule, note: note || null });
      toast.success(`Souscription ${FORMULES[formule]} active${data.fin ? ` jusqu'au ${dateCourte(data.fin)}` : " (illimitée)"}.`, { id });
      onFait();
    } catch (e) { toast.error(e.response?.data?.detail || "Enregistrement impossible.", { id }); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-md overflow-y-auto">
        <DialogHeader><DialogTitle>Souscription : {commerce.structure?.libelle}</DialogTitle></DialogHeader>
        <select value={formule} onChange={(e) => setFormule(e.target.value)} className="w-full rounded-lg border px-2 py-2" aria-label="Formule">
          {Object.entries(FORMULES).map(([f, l]) => <option key={f} value={f}>{l}</option>)}
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="Payé en espèces le 28/11" className="w-full rounded-lg border px-3 py-2" aria-label="Note" />
        <p className="text-xs text-slate-500">La période commence à la fin de la souscription en cours (aucun jour perdu).</p>
        <div className="flex justify-end gap-2">
          <Picto titre="Fermer" Icone={X} onClick={onFermer} couleur="bg-slate-100 text-slate-700" />
          <Picto titre="Enregistrer la souscription" Icone={Check} onClick={enregistrer} couleur="bg-emerald-600 text-white" />
        </div>
      </DialogContent>
    </Dialog>
  );
}
