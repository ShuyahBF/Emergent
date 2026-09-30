/*
  Lot 34 — « Outils+ » (nommé « SMART Communications » jusqu'au lot 41) : fonctions activables par client, par l'Admin
  ET le Superviseur (/portal/smart-communications et /admin/smart-communications).

  « Formulaires et Sondages » et « OCR sur Pièces » ne sont accessibles à un client,
  et à ses utilisateurs suivis, que si elles sont activées ici (désactivées par
  défaut). Le serveur refuse l'accès sinon ; le menu du client les affiche grisées.
  Les autres fonctions de SMART Communications restent réservées à l'Admin (fiche
  client → SMART Communications).
  API : GET /supervision/fonctions-clients, PUT /supervision/fonctions-clients/{id}.
  Lot 36 — section « Liluvine — !formulaire » : tarifs (client SAWALI / numéro inconnu,
  modifiables par l'Admin) et dernières commandes WhatsApp (GET /supervision/liluvine-formulaire).
  Lot 37 — journal complet (filtres, livré, erreurs, intervention humaine avec « Renvoyer les
  liens » / « Marquer traité », détail des étapes) et sondage de satisfaction (Admin et Superviseur).
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Bot, FileText, Loader2, Monitor, Pill, Save, ScanText, Search, ShieldCheck, Wrench } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

// Lot 36 — états d'une commande « !formulaire »
const STATUTS_LILUVINE = {
  mode_emploi: ["Mode d'emploi", "bg-slate-100 text-slate-600"],
  refuse: ["Refusé", "bg-rose-100 text-rose-700"],
  analyse: ["Analyse", "bg-sky-100 text-sky-700"],
  en_attente_paiement: ["Attente paiement", "bg-amber-100 text-amber-800"],
  publie: ["En ligne", "bg-emerald-100 text-emerald-700"],
  erreur: ["Erreur", "bg-rose-100 text-rose-700"],
  attente_otp: ["Attente du code", "bg-violet-100 text-violet-700"],     // lot 41
  bloque: ["Liste noire", "bg-slate-800 text-white"],                     // lot 41
};

// Lot 41 — copie de la pièce jointe reçue (image affichée, sinon lien)
function PieceJointe({ url, mime, nom }) {
  if (!url) return null;
  const src = `${process.env.REACT_APP_BACKEND_URL || ""}${url}`;
  return (mime || "").startsWith("image/") || /\.(jpe?g|png|webp)$/i.test(url)
    ? <a href={src} target="_blank" rel="noreferrer" title={nom || "Pièce jointe"}>
        <img src={src} alt={nom || "pièce jointe"} className="h-20 w-20 rounded object-cover ring-1 ring-slate-200" />
      </a>
    : <a href={src} target="_blank" rel="noreferrer" className="text-violet-700 underline">{nom || "Pièce jointe"}</a>;
}

// Lot 41 — numéros bloqués pour « !formulaire » (3 demandes non valables), avec les pièces en cause
function ListeNoire({ estAdmin }) {
  const [items, setItems] = useState(null);
  const charger = () => apiClient.get("/supervision/liluvine-formulaire/liste-noire")
    .then((r) => setItems(r.data || [])).catch(() => setItems([]));
  useEffect(() => { charger(); }, []);
  const debloquer = async (x) => {
    if (!window.confirm(`Débloquer ${x.telephone} ? Ses demandes non valables passées ne compteront plus.`)) return;
    try { await apiClient.delete(`/supervision/liluvine-formulaire/liste-noire/${x.chiffres}`); toast.success("Numéro débloqué"); charger(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Déblocage impossible"); }
  };
  if (!items || !items.length) return null;
  return (
    <div className="rounded-lg ring-1 ring-slate-300 bg-slate-50 p-3 space-y-2" data-testid="liluvine-liste-noire">
      <h3 className="text-sm font-semibold text-slate-800">⛔ Liste noire « !formulaire » ({items.length})</h3>
      {items.map((x) => (
        <div key={x.chiffres} className="rounded bg-white ring-1 ring-slate-200 p-2 text-xs space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{x.telephone}</span><span>{x.nom_contact || "—"}</span>
            <span className="text-slate-500">le {dateHeure(x.le)} — {x.motif}</span>
            {estAdmin && <button onClick={() => debloquer(x)} className="ml-auto rounded bg-slate-700 text-white px-2 py-0.5">Débloquer</button>}
          </div>
          <div className="flex flex-wrap gap-2">
            {(x.pieces || []).map((p, i) => (
              <div key={i} className="space-y-0.5 w-24"><PieceJointe url={p.url} mime={p.mime} nom={p.nom} />
                <p className="text-[10px] text-rose-700 line-clamp-2" title={p.motif}>{p.motif}</p></div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// Lot 37 — filtres du journal « !formulaire »
// Lot 41 — mode de mise en ligne : AUTO (paiement confirmé ou gratuit) ou FORCÉ (par l'Admin)
const MODES_REALISATION = {
  auto: ["auto", "bg-emerald-100 text-emerald-700 ring-emerald-200", "Mis en ligne automatiquement (paiement confirmé ou service gratuit)"],
  force: ["forcé", "bg-orange-100 text-orange-700 ring-orange-200", "Réalisation forcée par l'Admin, sans paiement : figure sur la facture du client"],
};
const FILTRES_JOURNAL = [["tous", "Tout"], ["intervention", "À traiter"], ["erreurs", "Erreurs / refus"], ["non_livres", "Non livrés"]];
const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");

// Tarifs, sondage de satisfaction et journal des commandes WhatsApp « !formulaire » (Liluvine)
function LiluvineFormulaire() {
  const { user } = useAuth();
  const estAdmin = user?.role === "admin";
  const [suivi, setSuivi] = useState(null);
  const [filtre, setFiltre] = useState("tous");
  const [prix, setPrix] = useState({ client: "", inconnu: "" });
  const [sondages, setSondages] = useState([]);
  const [reglage, setReglage] = useState({ sondage_id: "", relance_heures: 24, relances_max: 2 });
  const [ouvert, setOuvert] = useState("");                // commande dont le détail est affiché
  const [occupe, setOccupe] = useState("");

  const charger = async (f = filtre) => {
    try {
      const r = await apiClient.get("/supervision/liluvine-formulaire", { params: { filtre: f } });
      setSuivi(r.data);
      return r.data;
    } catch {
      setSuivi({ tarifs: {}, commandes: [], a_traiter: 0 });
      return null;
    }
  };

  useEffect(() => {
    charger("tous").then((d) => {
      if (!d) return;
      setPrix({ client: d.tarifs?.client ?? "", inconnu: d.tarifs?.inconnu ?? "" });
      setReglage({ sondage_id: d.sondage?.sondage_id || "", relance_heures: d.sondage?.relance_heures ?? 24,
        relances_max: d.sondage?.relances_max ?? 2 });
    });
    apiClient.get("/supervision/liluvine-formulaire/sondages").then((r) => setSondages(r.data || [])).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const changerFiltre = (f) => { setFiltre(f); charger(f); };

  const enregistrerPrix = async () => {
    try {
      const r = await apiClient.put("/supervision/liluvine-formulaire/tarifs", {
        prix_client_xof: parseInt(prix.client, 10) || 0, prix_inconnu_xof: parseInt(prix.inconnu, 10) || 0 });
      setSuivi((s) => ({ ...s, tarifs: r.data }));
      toast.success("Tarifs de « !formulaire » enregistrés");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  const enregistrerSondage = async () => {
    try {
      const r = await apiClient.put("/supervision/liluvine-formulaire/sondage", {
        sondage_id: reglage.sondage_id || null, relance_heures: parseInt(reglage.relance_heures, 10) || 24,
        relances_max: parseInt(reglage.relances_max, 10) || 0 });
      setSuivi((s) => ({ ...s, sondage: r.data }));
      toast.success(r.data.sondage_id ? `Sondage « ${r.data.sondage_titre} » envoyé après chaque livraison` : "Aucun sondage après livraison");
    } catch (e) { toast.error(e?.response?.data?.detail || "Enregistrement impossible"); }
  };

  const action = async (c, quoi) => {
    setOccupe(`${c.id}:${quoi}`);
    try {
      if (quoi === "renvoyer") {
        const r = await apiClient.post(`/supervision/liluvine-formulaire/${c.id}/renvoyer-liens`);
        r.data.ok ? toast.success("Liens renvoyés au contact") : toast.error(r.data.detail || "Liens non délivrés");
      } else if (quoi === "forcer") {
        // Lot 41 — réalisation forcée (Admin) : mise en ligne sans paiement, badge « forcé »
        const motif = window.prompt(
          `Forcer la réalisation du formulaire de ${c.nom_contact || c.telephone} ?\n`
          + "Il sera mis en ligne sans paiement, les liens partiront au contact, et la commande figurera "
          + "sur la facture du client avec le badge « forcé ».\n\nMotif (facultatif) :", "");
        if (motif === null) return;
        const r = await apiClient.post(`/supervision/liluvine-formulaire/${c.id}/forcer`, { motif });
        toast.success(r.data.etape === "analyse_et_mis_en_ligne"
          ? "Document ré-analysé et formulaire mis en ligne (forcé)" : "Formulaire mis en ligne (forcé)");
      } else {
        const note = window.prompt("Intervention faite — note (facultative) :", "");
        if (note === null) return;
        await apiClient.post(`/supervision/liluvine-formulaire/${c.id}/intervention`, { note });
        toast.success("Intervention marquée comme faite");
      }
      await charger();
    } catch (e) { toast.error(e?.response?.data?.detail || "Action impossible"); }
    finally { setOccupe(""); }
  };

  const etatSondage = (c) => {
    const s = c.sondage;
    if (!s) return "—";
    if (s.repondu) return "Répondu ✓";
    return `Envoyé${s.relances ? ` · ${s.relances} relance(s)` : ""}${s.canal ? ` (${s.canal})` : ""}`;
  };

  return (
    <section className="rounded-xl bg-white ring-1 ring-slate-200 p-4 space-y-4" data-testid="liluvine-formulaire">
      <div>
        <h2 className="font-display font-semibold flex items-center gap-2"><Bot className="h-4 w-4 text-violet-600" /> Liluvine — commande WhatsApp « !formulaire »</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Un contact envoie à Liluvine un questionnaire (Word, Excel, PDF ou photo) avec la légende <b>!formulaire</b> :
          Liluvine crée le formulaire (privé), annonce le tarif, et après paiement Mobile Money envoie le lien crypté de
          saisie et celui des réponses (valables 30 jours), puis le sondage de satisfaction. Tarif 0 = gratuit.
        </p>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        {/* Tarifs (Admin) */}
        <div className="rounded-lg ring-1 ring-slate-200 p-3 space-y-2">
          <p className="text-xs font-semibold text-slate-700">Tarifs</p>
          <div className="flex flex-wrap items-end gap-2">
            {[["client", "Client SAWALI enregistré"], ["inconnu", "Numéro inconnu"]].map(([k, l]) => (
              <label key={k} className="text-[11px] text-slate-600">
                {l} (FCFA)
                <input type="number" min={0} value={prix[k]} disabled={!estAdmin} data-testid={`liluvine-prix-${k}`}
                  onChange={(e) => setPrix((p) => ({ ...p, [k]: e.target.value }))}
                  className="mt-1 block w-36 rounded-lg border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-50" />
              </label>
            ))}
            {estAdmin ? (
              <button onClick={enregistrerPrix} data-testid="liluvine-prix-enregistrer"
                className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 text-white px-3 py-2 text-xs font-semibold hover:bg-violet-700">
                <Save className="h-3.5 w-3.5" /> Enregistrer
              </button>
            ) : <p className="text-[11px] text-slate-400">Modifiables par l'Admin.</p>}
          </div>
        </div>
        {/* Sondage de satisfaction (Admin et Superviseur) */}
        <div className="rounded-lg ring-1 ring-slate-200 p-3 space-y-2" data-testid="liluvine-sondage">
          <p className="text-xs font-semibold text-slate-700">Sondage de satisfaction après livraison</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-[11px] text-slate-600">
              Sondage
              <select value={reglage.sondage_id} onChange={(e) => setReglage((r) => ({ ...r, sondage_id: e.target.value }))}
                className="mt-1 block w-56 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="liluvine-sondage-choix">
                <option value="">— Aucun sondage —</option>
                {sondages.map((s) => <option key={s.id} value={s.id}>{s.title}{s.status === "draft" ? " (brouillon)" : ""}</option>)}
              </select>
            </label>
            <label className="text-[11px] text-slate-600">
              Relance après (h)
              <input type="number" min={1} value={reglage.relance_heures} onChange={(e) => setReglage((r) => ({ ...r, relance_heures: e.target.value }))}
                className="mt-1 block w-24 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="liluvine-sondage-delai" />
            </label>
            <label className="text-[11px] text-slate-600">
              Relances max
              <input type="number" min={0} max={10} value={reglage.relances_max} onChange={(e) => setReglage((r) => ({ ...r, relances_max: e.target.value }))}
                className="mt-1 block w-20 rounded-lg border border-slate-300 px-2 py-1.5 text-sm" data-testid="liluvine-sondage-relances" />
            </label>
            <button onClick={enregistrerSondage} data-testid="liluvine-sondage-enregistrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 text-white px-3 py-2 text-xs font-semibold hover:bg-violet-700">
              <Save className="h-3.5 w-3.5" /> Enregistrer
            </button>
          </div>
          <p className="text-[11px] text-slate-500">Relances par WhatsApp, ou par SMS si WhatsApp refuse, tant que le contact n'a pas répondu.</p>
        </div>
      </div>

      {/* Journal */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs font-semibold text-slate-700 mr-2">Journal</p>
          {FILTRES_JOURNAL.map(([k, l]) => (
            <button key={k} onClick={() => changerFiltre(k)} data-testid={`liluvine-filtre-${k}`}
              className={`text-xs px-2.5 py-1 rounded-full ring-1 ${filtre === k ? "bg-violet-600 text-white ring-violet-600" : "bg-white ring-slate-200 hover:ring-violet-300"}`}>
              {l}{k === "intervention" && suivi?.a_traiter ? ` (${suivi.a_traiter})` : ""}
            </button>
          ))}
        </div>
        <ListeNoire estAdmin={estAdmin} />
        <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
              <tr><th className="text-left px-2 py-1.5">Date / heure</th><th className="text-left px-2">Numéro</th><th className="text-left px-2">Nom</th>
                <th className="text-left px-2">Référence du formulaire</th><th className="text-left px-2">Livré</th><th className="text-left px-2">Erreurs</th>
                <th className="text-left px-2">Intervention</th><th className="text-left px-2">Sondage</th></tr>
            </thead>
            <tbody>
              {!suivi && <tr><td colSpan={8} className="py-3 text-center text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin inline" /></td></tr>}
              {suivi && suivi.commandes.length === 0 && <tr><td colSpan={8} className="py-3 text-center text-slate-400 italic">Aucune commande.</td></tr>}
              {(suivi?.commandes || []).map((c) => {
                const [lib, cls] = STATUTS_LILUVINE[c.statut] || [c.statut, "bg-slate-100 text-slate-600"];
                const aTraiter = c.intervention_requise && !c.intervention_faite_le;
                return (
                  <React.Fragment key={c.id}>
                    <tr className={`border-t border-slate-100 align-top ${aTraiter ? "bg-rose-50/50" : ""}`} data-testid={`liluvine-ligne-${c.id}`}>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        <button onClick={() => setOuvert(ouvert === c.id ? "" : c.id)} className="text-violet-700 hover:underline">{dateHeure(c.cree_le)}</button>
                      </td>
                      <td className="px-2 whitespace-nowrap font-mono">{c.telephone}</td>
                      <td className="px-2">{c.nom_contact || "—"}{c.type_client === "client" && <span className="block text-[10px] text-slate-500">{c.compte_libelle}</span>}</td>
                      <td className="px-2"><span className={`rounded-full px-2 py-0.5 mr-1 ${cls}`}>{lib}</span>
                        {/* Lot 41 — badge du mode de mise en ligne */}
                        {c.mode_realisation && MODES_REALISATION[c.mode_realisation] && (
                          <span className={`rounded px-1.5 py-0.5 mr-1 text-[9px] font-bold uppercase ring-1 ${MODES_REALISATION[c.mode_realisation][1]}`}
                            title={MODES_REALISATION[c.mode_realisation][2] + (c.force_par ? ` — par ${c.force_par}${c.force_motif ? ` : ${c.force_motif}` : ""}` : "")}
                            data-testid={`liluvine-mode-${c.id}`}>
                            {MODES_REALISATION[c.mode_realisation][0]}
                          </span>
                        )}
                        <span className="font-mono">{c.reference || c.fichier || ""}</span>
                        {c.prix_xof != null && <span className="block text-[10px] text-slate-500">{c.prix_xof.toLocaleString("fr-FR")} F</span>}
                        {estAdmin && c.forcable && (
                          <button onClick={() => action(c, "forcer")} disabled={!!occupe} data-testid={`liluvine-forcer-${c.id}`}
                            title="Mettre le formulaire en ligne sans paiement (badge « forcé », facturé au client)"
                            className="mt-1 block rounded bg-orange-600 text-white px-2 py-0.5 text-[11px] disabled:opacity-50">
                            {occupe === `${c.id}:forcer` ? "…" : "Forcer la réalisation"}
                          </button>
                        )}</td>
                      <td className="px-2 whitespace-nowrap">{c.livre ? <span className="text-emerald-700">Oui · {dateHeure(c.livre_le)}</span> : (c.statut === "publie" ? <span className="text-rose-700 font-semibold">Non</span> : "—")}</td>
                      <td className="px-2 text-rose-700 max-w-[14rem]">{c.erreur || "—"}</td>
                      <td className="px-2 max-w-[16rem]">
                        {c.intervention_requise ? (
                          <div className="space-y-1">
                            <p className={aTraiter ? "text-rose-700 font-semibold" : "text-slate-500 line-through"}>{c.intervention_motif}</p>
                            {aTraiter ? (
                              <div className="flex flex-wrap gap-1">
                                {c.statut === "publie" && !c.livre && (
                                  <button onClick={() => action(c, "renvoyer")} disabled={!!occupe} data-testid={`liluvine-renvoyer-${c.id}`}
                                    className="rounded bg-emerald-600 text-white px-2 py-0.5 text-[11px] disabled:opacity-50">Renvoyer les liens</button>
                                )}
                                <button onClick={() => action(c, "traite")} disabled={!!occupe} data-testid={`liluvine-traite-${c.id}`}
                                  className="rounded bg-slate-700 text-white px-2 py-0.5 text-[11px] disabled:opacity-50">Marquer traité</button>
                              </div>
                            ) : <p className="text-[10px] text-emerald-700">Traité le {dateHeure(c.intervention_faite_le)} par {c.intervention_par}{c.intervention_note ? ` — ${c.intervention_note}` : ""}</p>}
                          </div>
                        ) : "Non"}
                      </td>
                      <td className="px-2 whitespace-nowrap">{etatSondage(c)}</td>
                    </tr>
                    {ouvert === c.id && (
                      <tr className="bg-slate-50/70"><td colSpan={8} className="px-3 py-2">
                        {/* Lot 41 — copie de la pièce jointe reçue */}
                        {c.piece_url && <div className="mb-2"><PieceJointe url={c.piece_url} mime={c.piece_mime} nom={c.fichier} /></div>}
                        <ol className="space-y-0.5">
                          {(c.journal || []).map((e, i) => (
                            <li key={i} className={e.ok ? "text-slate-600" : "text-rose-700"}>
                              <span className="font-mono text-[10px] text-slate-400 mr-2">{dateHeure(e.le)}</span><b>{e.etape}</b>{e.detail ? ` — ${e.detail}` : ""}
                            </li>
                          ))}
                        </ol>
                      </td></tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

// Colonnes de la page (mêmes clés que le serveur)
const FONCTIONS = [
  { cle: "forms_surveys", label: "Formulaires et Sondages", icon: FileText, couleur: "bg-indigo-600" },
  { cle: "ocr_pieces", label: "OCR sur Pièces", icon: ScanText, couleur: "bg-teal-600" },
  { cle: "ordonnances_stock", label: "Ordonnances et stock", icon: Pill, couleur: "bg-emerald-600" },   // lot 39
  { cle: "maintenance_equipements", label: "Maintenance des équipements", icon: Wrench, couleur: "bg-orange-600" },   // lot 41
  { cle: "parc_informatique", label: "Parc informatique", icon: Monitor, couleur: "bg-sky-600" },   // lot 47
];

// Interrupteur accessible (bouton à bascule)
function Interrupteur({ actif, occupe, onChange, couleur, testId, libelle }) {
  return (
    <button type="button" role="switch" aria-checked={actif} aria-label={libelle} disabled={occupe}
      onClick={() => onChange(!actif)} data-testid={testId}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition disabled:opacity-50 ${actif ? couleur : "bg-slate-300"}`}>
      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${actif ? "translate-x-5" : "translate-x-0.5"}`} />
    </button>
  );
}

export default function FonctionsClients() {
  const [clients, setClients] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [recherche, setRecherche] = useState("");
  const [enCours, setEnCours] = useState("");          // "<client>:<clé>" en cours d'enregistrement

  useEffect(() => {
    apiClient.get("/supervision/fonctions-clients")
      .then((r) => setClients(r.data?.clients || []))
      .catch((e) => toast.error(e?.response?.data?.detail || "Impossible de charger les clients"))
      .finally(() => setChargement(false));
  }, []);

  // Recherche : nom, société, e-mail ou code client
  const affiches = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return clients.filter((c) => !q || [c.company, c.full_name, c.email, c.client_code]
      .some((v) => (v || "").toLowerCase().includes(q)));
  }, [clients, recherche]);

  // Totaux par fonction (bandeau du haut)
  const totaux = useMemo(() => Object.fromEntries(FONCTIONS.map((f) => [f.cle, clients.filter((c) => c[f.cle]).length])), [clients]);

  // Bascule d'une fonction pour un client : enregistrée aussitôt
  const basculer = async (client, cle, valeur) => {
    setEnCours(`${client.id}:${cle}`);
    try {
      const r = await apiClient.put(`/supervision/fonctions-clients/${client.id}`, { [cle]: valeur });
      setClients((liste) => liste.map((c) => (c.id === client.id ? { ...c, ...r.data } : c)));
      const f = FONCTIONS.find((x) => x.cle === cle);
      toast.success(`Fonction « ${f.label} » ${valeur ? "activée" : "désactivée"} pour ${client.company || client.full_name || client.email}`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Modification impossible");
    } finally {
      setEnCours("");
    }
  };

  return (
    <div className="max-w-5xl space-y-5" data-testid="fonctions-clients-page">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Outils+</p>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-fuchsia-600" /> Fonctions par client
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Activez pour chaque client les fonctions <b>Formulaires et Sondages</b>, <b>OCR sur Pièces</b>,
          <b> Ordonnances et stock</b>, <b>Maintenance des équipements</b> et <b>Parc informatique</b>.
          Elles sont désactivées par défaut ; leurs utilisateurs suivis en héritent. L'Admin et le Superviseur y ont
          toujours accès.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
          <p className="text-[11px] uppercase tracking-wider text-slate-500">Clients</p>
          <p className="text-2xl font-bold tabular-nums text-slate-800">{clients.length}</p>
        </div>
        {FONCTIONS.map((f) => (
          <div key={f.cle} className="rounded-xl bg-white ring-1 ring-slate-200 p-3">
            <p className="text-[11px] uppercase tracking-wider text-slate-500">{f.label}</p>
            <p className="text-2xl font-bold tabular-nums text-slate-800">{totaux[f.cle] || 0} <span className="text-sm font-normal text-slate-500">activé(s)</span></p>
          </div>
        ))}
      </div>

      <div className="relative max-w-sm">
        <Search className="h-4 w-4 text-slate-400 absolute left-3 top-2.5" />
        <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Rechercher un client (nom, e-mail, code)…"
          className="w-full rounded-lg border border-slate-300 pl-9 pr-3 py-2 text-sm" data-testid="fonctions-clients-recherche" />
      </div>

      <div className="rounded-xl bg-white ring-1 ring-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[11px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="text-left px-4 py-2">Client</th>
              {FONCTIONS.map((f) => (
                <th key={f.cle} className="px-4 py-2 text-center whitespace-nowrap">
                  <span className="inline-flex items-center gap-1"><f.icon className="h-3.5 w-3.5" /> {f.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {chargement && (
              <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-400"><Loader2 className="h-4 w-4 animate-spin inline" /> Chargement…</td></tr>
            )}
            {!chargement && affiches.length === 0 && (
              <tr><td colSpan={3} className="px-4 py-6 text-center text-slate-400 italic">Aucun client.</td></tr>
            )}
            {affiches.map((c) => (
              <tr key={c.id} className="border-t border-slate-100" data-testid={`fonctions-client-${c.id}`}>
                <td className="px-4 py-2">
                  <p className="font-medium text-slate-800">
                    {c.company || c.full_name || c.email}
                    {/* Lot 42 — compte Superviseur ou de la plateforme SAWALI : accès toujours ouvert pour
                        lui-même, le réglage vaut pour ses utilisateurs suivis */}
                    {c.plateforme && (
                      <span className="ml-2 align-middle text-[10px] rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5"
                        title="Ce compte a toujours accès ; l'activation vaut pour ses utilisateurs suivis">
                        {c.role === "superviseur" ? "Superviseur" : "Plateforme"}
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-slate-500">{[c.client_code, c.full_name !== c.company ? c.full_name : null, c.email].filter(Boolean).join(" · ")}</p>
                </td>
                {FONCTIONS.map((f) => (
                  <td key={f.cle} className="px-4 py-2 text-center">
                    <Interrupteur actif={!!c[f.cle]} occupe={enCours === `${c.id}:${f.cle}`} couleur={f.couleur}
                      libelle={`${f.label} — ${c.company || c.full_name || c.email}`}
                      testId={`fonction-${c.id}-${f.cle}`} onChange={(v) => basculer(c, f.cle, v)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <LiluvineFormulaire />
    </div>
  );
}
