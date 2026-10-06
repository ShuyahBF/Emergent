// LooisClesClients.jsx — Lot 68.1 : onglet « Clés clients » de la page Plateformes → Loois → Synchro (administrateur).
//
// Demande du propriétaire (06/10/2026) : « oui prépare ces clés différentes par client » (au lieu de la seule clé
// commune LOOIS_SUPPORT_CLE).
//
// Ce que fait l'onglet :
//   - LISTE des clés : client (code du site envoyé par Loois), libellé, applications autorisées, début de la clé
//     (« LK-a1B… », jamais la clé entière), état, dernière utilisation (date + poste) ;
//   - CRÉER une clé : la clé n'est affichée qu'UNE SEULE FOIS (bouton « Copier » + avertissement) — SAWALI n'en garde
//     que l'empreinte ; elle se saisit ensuite sur chaque poste (icône Loois → « Clé client Loois… ») ;
//   - RÉGÉNÉRER (l'ancienne clé est révoquée immédiatement), RÉVOQUER, RÉACTIVER, MODIFIER (libellé, applications) ;
//   - RÉGLAGE DE TRANSITION « Accepter encore la clé commune pour la synchro » (décoché par défaut).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { apiClient } from "@/lib/api";

const BASE = "/admin/loois-cles-clients";
const LIBELLES = { eKol: "e-Kol", Aizenta: "Aizenta", Biolog: "Biolog" };

// Jauge circulaire transparente (attente), comme sur le reste de SAWALI
const Jauge = () => (
  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-sky-300 border-t-transparent align-middle" />
);

// Date ISO → « JJ/MM/AAAA HH:MM » (heure de Ouagadougou = UTC)
const dateHeure = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "short", timeStyle: "short" });
};

// Formulaire vide (création)
const VIDE = { code: "", libelle: "", applications: [] };

export default function LooisClesClients() {
  const [donnees, setDonnees] = useState(null);   // {cles, reglages, sites_connus, poivre_configure, cle_commune_configuree}
  const [occupe, setOccupe] = useState(false);
  const [formulaire, setFormulaire] = useState(VIDE);
  const [edition, setEdition] = useState(null);   // fiche en cours de modification {id, libelle, applications}
  const [cleMontree, setCleMontree] = useState(null); // {code, cle} : clé affichée UNE fois après création / régénération
  const [ligne, setLigne] = useState(null);       // ligne sélectionnée (orange, règle des tableaux)

  // Lecture de la liste (avec « Patientez… » si demandé)
  const charger = useCallback(async (visible = false) => {
    const t = visible ? toast.loading("Patientez…") : null;
    setOccupe(true);
    try {
      const r = await apiClient.get(BASE);
      setDonnees(r.data);
      if (t) toast.dismiss(t);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Clés clients indisponibles", t ? { id: t } : undefined);
    } finally {
      setOccupe(false);
    }
  }, []);

  useEffect(() => { charger(true); }, [charger]);

  // Coche / décoche une application dans un formulaire
  const basculerApp = (liste, app) => (liste.includes(app) ? liste.filter((a) => a !== app) : [...liste, app]);

  // Création d'une clé : la réponse contient la clé en clair, montrée une seule fois
  const creer = async (e) => {
    e.preventDefault();
    if (!formulaire.code.trim()) return;
    const t = toast.loading("Patientez… création de la clé");
    try {
      const r = await apiClient.post(BASE, formulaire);
      setCleMontree({ code: r.data.fiche.code, cle: r.data.cle });
      setFormulaire(VIDE);
      toast.success(`Clé créée pour ${r.data.fiche.code}`, { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Création impossible", { id: t });
    }
  };

  // Actions sur une clé : régénérer (nouvelle clé montrée une fois), révoquer, réactiver
  const action = async (fiche, quoi) => {
    const messages = {
      regenerer: `Générer une NOUVELLE clé pour ${fiche.code} ? L'ancienne sera refusée immédiatement sur tous ses postes.`,
      revoquer: `Révoquer la clé de ${fiche.code} ? Ses postes ne pourront plus synchroniser ni écrire au support avec cette clé.`,
      reactiver: `Réactiver la clé de ${fiche.code} ?`,
    };
    if (!window.confirm(messages[quoi])) return;
    const t = toast.loading("Patientez…");
    try {
      const r = await apiClient.post(`${BASE}/${fiche.id}/${quoi}`);
      if (r.data.cle) setCleMontree({ code: fiche.code, cle: r.data.cle });
      toast.success("Fait", { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Action impossible", { id: t });
    }
  };

  // Enregistrement d'une modification (libellé, applications)
  const enregistrerEdition = async () => {
    const t = toast.loading("Patientez… enregistrement");
    try {
      await apiClient.put(`${BASE}/${edition.id}`, { libelle: edition.libelle, applications: edition.applications });
      setEdition(null);
      toast.success("Enregistré", { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Enregistrement impossible", { id: t });
    }
  };

  // Réglage de transition : accepter encore la clé commune pour la synchro
  const basculerTransition = async (valeur) => {
    if (valeur && !window.confirm("Accepter de nouveau la clé COMMUNE pour la synchro des tables ? (à réserver à la transition)")) return;
    const t = toast.loading("Patientez…");
    try {
      await apiClient.put(`${BASE}-reglages`, { accepter_cle_commune_synchro: valeur });
      toast.success("Réglage enregistré", { id: t });
      charger(false);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Réglage impossible", { id: t });
    }
  };

  // Copie de la clé dans le presse-papiers
  const copier = async () => {
    try {
      await navigator.clipboard.writeText(cleMontree.cle);
      toast.success("Clé copiée");
    } catch {
      toast.error("Copie impossible : sélectionnez la clé et faites Ctrl+C");
    }
  };

  const applications = donnees?.applications || ["eKol", "Aizenta", "Biolog"];
  const cles = donnees?.cles || [];

  return (
    <div className="space-y-4" data-testid="loois-cles-clients">
      {!donnees && <p className="text-sm text-slate-500"><Jauge /> Patientez…</p>}

      {/* Clé affichée UNE SEULE FOIS (création ou régénération) */}
      {cleMontree && (
        <section className="rounded-2xl border-2 border-amber-400 bg-amber-50 p-4" data-testid="cle-montree">
          <h2 className="text-lg font-semibold text-amber-900">🔑 Clé client Loois de {cleMontree.code}</h2>
          <p className="text-sm text-amber-900">
            ⚠ Notez-la maintenant : elle ne sera <strong>plus jamais affichée</strong> (SAWALI n'en garde que l'empreinte).
            À saisir sur chaque poste du client : icône Loois → « Clé client Loois… ».
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="select-all rounded bg-white px-3 py-1.5 font-mono text-sm ring-1 ring-amber-300">{cleMontree.cle}</code>
            <button type="button" onClick={copier} className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm text-white hover:bg-amber-700">📋 Copier</button>
            <button type="button" onClick={() => setCleMontree(null)} className="rounded-lg border border-amber-400 px-3 py-1.5 text-sm hover:bg-amber-100">
              J'ai noté la clé — masquer
            </button>
          </div>
        </section>
      )}

      {donnees && (
        <>
          {/* Réglages et état */}
          <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="space-y-1 text-sm">
                <h2 className="text-lg font-semibold">Clés clients Loois {occupe && <Jauge />}</h2>
                <p className="text-xs text-slate-500">
                  Une clé par client : elle identifie le client (code du site) pour la synchro des tables, le chat du support et le signal de présence.
                  Seule l'empreinte de la clé est enregistrée{donnees.poivre_configure ? " (avec le poivre LOOIS_CLES_PEPPER)" : " — variable LOOIS_CLES_PEPPER non définie (recommandée)"}.
                  Clé commune LOOIS_SUPPORT_CLE : {donnees.cle_commune_configuree ? "définie (toujours acceptée pour le support et la présence)" : "non définie"}.
                </p>
                <label className="inline-flex items-center gap-1.5">
                  <input type="checkbox" checked={!!donnees.reglages?.accepter_cle_commune_synchro}
                    onChange={(e) => basculerTransition(e.target.checked)} data-testid="transition-cle-commune" />
                  Accepter encore la clé commune pour la synchro (transition)
                </label>
              </div>
              <button type="button" onClick={() => charger(true)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm hover:bg-slate-50">
                <RefreshCw className={`h-4 w-4 ${occupe ? "animate-spin" : ""}`} /> Actualiser
              </button>
            </div>

            {/* Création */}
            <form onSubmit={creer} className="mt-3 flex flex-wrap items-end gap-2 text-sm">
              <label className="flex flex-col">
                <span className="text-xs text-slate-500">Code client (site envoyé par Loois)</span>
                <input list="sites-connus" value={formulaire.code} onChange={(e) => setFormulaire({ ...formulaire, code: e.target.value })}
                  placeholder="ex. LYCEE-PRIVE-X ou SCF" className="w-56 rounded border border-slate-300 px-2 py-1" data-testid="code-client" />
                <datalist id="sites-connus">
                  {(donnees.sites_connus || []).filter((s) => !s.a_une_cle).map((s) => (
                    <option key={`${s.code}|${s.application}`} value={s.code}>{LIBELLES[s.application] || s.application}</option>
                  ))}
                </datalist>
              </label>
              <label className="flex flex-col">
                <span className="text-xs text-slate-500">Nom du client</span>
                <input value={formulaire.libelle} onChange={(e) => setFormulaire({ ...formulaire, libelle: e.target.value })}
                  placeholder="ex. Lycée Privé X" className="w-56 rounded border border-slate-300 px-2 py-1" />
              </label>
              <div className="flex flex-col">
                <span className="text-xs text-slate-500">Applications (aucune = toutes)</span>
                <div className="flex gap-2 py-1">
                  {applications.map((a) => (
                    <label key={a} className="inline-flex items-center gap-1">
                      <input type="checkbox" checked={formulaire.applications.includes(a)}
                        onChange={() => setFormulaire({ ...formulaire, applications: basculerApp(formulaire.applications, a) })} /> {LIBELLES[a] || a}
                    </label>
                  ))}
                </div>
              </div>
              <button type="submit" disabled={!formulaire.code.trim()} className="rounded-lg bg-sky-600 px-3 py-1.5 text-white hover:bg-sky-700 disabled:opacity-50" data-testid="creer-cle">
                ➕ Créer la clé
              </button>
            </form>
          </section>

          {/* Liste des clés (ligne survolée bleu clair / sélectionnée orange : CSS global) */}
          <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
            {cles.length === 0 ? (
              <p className="text-sm text-slate-500">Aucune clé client pour l'instant.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs text-slate-500">
                    <tr>
                      <th className="p-2">Client</th><th className="p-2">Applications</th><th className="p-2">Clé</th><th className="p-2">État</th>
                      <th className="p-2">Dernière utilisation</th><th className="p-2">Créée le</th><th className="p-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cles.map((f) => {
                      const enEdition = edition?.id === f.id;
                      return (
                        <tr key={f.id} className={`border-t border-slate-100 ${ligne === f.id ? "ligne-selectionnee" : ""}`} onClick={() => setLigne(f.id)}>
                          <td className="p-2">
                            <strong>{f.code}</strong>
                            {enEdition ? (
                              <input value={edition.libelle} onClick={(e) => e.stopPropagation()} onChange={(e) => setEdition({ ...edition, libelle: e.target.value })}
                                className="mt-1 block w-48 rounded border border-slate-300 px-2 py-0.5 text-slate-800" />
                            ) : <div className="text-xs opacity-80">{f.libelle}</div>}
                          </td>
                          <td className="p-2">
                            {enEdition ? (
                              <div className="flex flex-col" onClick={(e) => e.stopPropagation()}>
                                {applications.map((a) => (
                                  <label key={a} className="inline-flex items-center gap-1 text-xs">
                                    <input type="checkbox" checked={edition.applications.includes(a)}
                                      onChange={() => setEdition({ ...edition, applications: basculerApp(edition.applications, a) })} /> {LIBELLES[a] || a}
                                  </label>
                                ))}
                              </div>
                            ) : (f.applications?.length ? f.applications.map((a) => LIBELLES[a] || a).join(", ") : "toutes")}
                          </td>
                          <td className="p-2 font-mono text-xs">{f.prefixe}…</td>
                          <td className="p-2">
                            {f.actif
                              ? <span className="rounded bg-emerald-100 px-1.5 text-xs font-semibold text-emerald-800">active</span>
                              : <span className="rounded bg-rose-100 px-1.5 text-xs font-semibold text-rose-800" title={`Révoquée le ${dateHeure(f.revoquee_le)}`}>révoquée</span>}
                          </td>
                          <td className="p-2 text-xs">{dateHeure(f.derniere_utilisation)}{f.derniere_machine ? ` · ${f.derniere_machine}` : ""}</td>
                          <td className="p-2 text-xs">{dateHeure(f.cree_le)}{f.cree_par ? ` · ${f.cree_par}` : ""}</td>
                          <td className="whitespace-nowrap p-2" onClick={(e) => e.stopPropagation()}>
                            {enEdition ? (
                              <>
                                <button type="button" onClick={enregistrerEdition} className="mr-1 rounded bg-sky-600 px-2 py-0.5 text-xs text-white hover:bg-sky-700">Enregistrer</button>
                                <button type="button" onClick={() => setEdition(null)} className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700">Annuler</button>
                              </>
                            ) : (
                              <>
                                <button type="button" onClick={() => setEdition({ id: f.id, libelle: f.libelle || "", applications: f.applications || [] })}
                                  className="mr-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50">Modifier</button>
                                <button type="button" onClick={() => action(f, "regenerer")}
                                  className="mr-1 rounded border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50">Régénérer</button>
                                {f.actif ? (
                                  <button type="button" onClick={() => action(f, "revoquer")}
                                    className="rounded border border-rose-300 bg-white px-2 py-0.5 text-xs text-rose-700 hover:bg-rose-50">Révoquer</button>
                                ) : (
                                  <button type="button" onClick={() => action(f, "reactiver")}
                                    className="rounded border border-emerald-300 bg-white px-2 py-0.5 text-xs text-emerald-700 hover:bg-emerald-50">Réactiver</button>
                                )}
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
