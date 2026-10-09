// AdminRequetes.jsx — Lot 86 : « Requêtes clients » côté SAWALI (administrateur).
//
// Deux onglets :
//   - Requêtes : celles de tous les clients (filtres état / client / lot) ; un clic ouvre le détail où l'on ajoute
//     une OBSERVATION (date et heure automatiques), change l'ÉTAT et range la requête dans un LOT ;
//   - Lots : création d'un lot de correction (numéro automatique) ; passer un lot à « Déployé » fait passer toutes
//     ses requêtes à « Déployée » et prévient chaque client (e-mail, WhatsApp) qu'il peut évaluer.
//   - Liens clients (lot 86.1) : lien personnel SANS mot de passe de chaque client, envoyé par WhatsApp (et e-mail)
//     en un clic — plus simple pour les utilisateurs que de se connecter au site ; renouvelable et révocable.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import AudioRequete from "@/components/AudioRequete";
import { ImagesRequete } from "@/components/RequeteOutils";

const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

// Détail d'une requête : contenu, historique, observation / état / lot
function Detail({ r, etats, lots, onMaj }) {
  const [observation, setObservation] = useState("");
  const [etat, setEtat] = useState(r.etat);
  const [lotId, setLotId] = useState(r.lot_id || "");
  const enregistrer = async () => {
    const attente = toast.loading("Patientez…");
    try {
      await apiClient.patch(`/admin/requetes/${r.id}`, { observation, etat, lot_id: lotId || null });
      toast.success("Requête mise à jour", { id: attente });
      setObservation("");
      onMaj();
    } catch (e) { toast.error(erreur(e, "Mise à jour impossible"), { id: attente }); }
  };
  return (
    <div className="space-y-2 bg-slate-50 p-3 text-xs" data-testid={`detail-${r.numero}`}>
      <p className="text-slate-500">Déposée le {dateHeure(r.cree_le)} par {r.auteur_nom} ({r.client_nom}){r.origine === "lien" ? " · via le lien personnel" : ""}</p>
      {r.texte && <p className="whitespace-pre-wrap text-sm">{r.texte}</p>}
      {r.a_audio && <AudioRequete id={r.id} />}
      <ImagesRequete images={r.images} charger={(img) => apiClient.get(`/requetes/${r.id}/images/${img.id}`, { responseType: "blob" }).then((x) => x.data)} />
      {r.transcription && <p className="italic text-slate-600">Transcription : {r.transcription}</p>}
      {(r.observations || []).length > 0 && (
        <ul className="list-disc pl-5">{r.observations.map((o, i) => <li key={i}>{dateHeure(o.le)} — {o.par} : {o.texte}</li>)}</ul>
      )}
      <p className="text-slate-500">Historique : {(r.historique || []).map((h) => `${etats[h.etat] || h.etat} (${dateHeure(h.le)})`).join(" → ")}</p>
      {r.evaluation && <p>Évaluation du client : {"★".repeat(r.evaluation.note)}{"☆".repeat(5 - r.evaluation.note)} {r.evaluation.commentaire}</p>}
      <textarea rows={2} value={observation} onChange={(e) => setObservation(e.target.value)} placeholder="Observation (datée automatiquement)"
        className="w-full rounded border border-slate-300 px-2 py-1" />
      <div className="flex flex-wrap items-center gap-2">
        <select value={etat} onChange={(e) => setEtat(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
          {Object.entries(etats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={lotId} onChange={(e) => setLotId(e.target.value)} className="rounded border border-slate-300 px-2 py-1">
          <option value="">— aucun lot —</option>
          {lots.filter((l) => l.etat !== "deploye" || l.id === r.lot_id).map((l) => <option key={l.id} value={l.id}>Lot {l.numero} — {l.titre}</option>)}
        </select>
        <button type="button" onClick={enregistrer} className="rounded bg-sky-700 px-3 py-1 font-semibold text-white">Enregistrer</button>
      </div>
    </div>
  );
}

// Lot 86.1 — liens personnels des clients : envoi par WhatsApp / e-mail, renouvellement, révocation
function LiensClients() {
  const [clients, setClients] = useState(null);
  const [filtre, setFiltre] = useState("");
  const [numeros, setNumeros] = useState({});   // numéro WhatsApp saisi pour un client sans numéro
  const charger = useCallback(() => {
    apiClient.get("/admin/requetes-liens").then((r) => setClients(r.data.clients)).catch(() => setClients([]));
  }, []);
  useEffect(() => { charger(); }, [charger]);
  const envoyer = async (c, renouveler = false) => {
    const attente = toast.loading("Patientez… envoi du lien");
    try {
      const r = await apiClient.post("/admin/requetes-liens", { tenant_id: c.id, renouveler, numero: numeros[c.id] || undefined });
      const e = r.data.envoye;
      toast.success(e.whatsapp || e.email ? `Lien envoyé${e.whatsapp ? " par WhatsApp" : ""}${e.email ? `${e.whatsapp ? " et" : ""} par e-mail` : ""}`
        : "Lien créé (aucun numéro WhatsApp ni e-mail : copiez-le)", { id: attente });
      charger();
    } catch (e) { toast.error(erreur(e, "Envoi impossible"), { id: attente }); }
  };
  const revoquer = async (c) => {
    if (!window.confirm(`Révoquer le lien de ${c.nom} ? L'ancien lien ne fonctionnera plus.`)) return;
    await apiClient.delete(`/admin/requetes-liens/${c.id}`);
    toast.success("Lien révoqué");
    charger();
  };
  const copier = async (url) => {
    try { await navigator.clipboard.writeText(url); toast.success("Lien copié"); } catch { toast.error("Copie impossible"); }
  };
  if (!clients) return <p className="text-sm text-slate-500">Patientez…</p>;
  const visibles = clients.filter((c) => !filtre || c.nom.toLowerCase().includes(filtre.toLowerCase()));
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-3" data-testid="liens-clients">
      <p className="text-xs text-slate-600">Chaque client reçoit un lien personnel <b>sans mot de passe</b> : ses agents l'ouvrent depuis WhatsApp pour déposer une requête (texte, vocal, photos, captures), la suivre et l'évaluer. Les messages de suivi rappellent ce lien.</p>
      <input value={filtre} onChange={(e) => setFiltre(e.target.value)} placeholder="Rechercher un client…" className="w-64 rounded border border-slate-300 px-2 py-1 text-sm" />
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Client</th><th>WhatsApp</th><th>Lien</th><th>Envoyé le</th><th></th></tr></thead>
        <tbody>
          {visibles.map((c) => (
            <tr key={c.id} className="border-t border-slate-100">
              <td className="py-1">{c.nom}</td>
              <td className="text-xs">{c.whatsapp || (
                <input value={numeros[c.id] || ""} onChange={(e) => setNumeros({ ...numeros, [c.id]: e.target.value })} placeholder="226…"
                  className="w-32 rounded border border-slate-300 px-1 py-0.5 text-xs" />)}</td>
              <td className="max-w-xs truncate text-xs">{c.url ? <button type="button" onClick={() => copier(c.url)} title="Copier" className="font-mono text-sky-800 underline">{c.url}</button> : "—"}</td>
              <td className="text-xs">{dateHeure(c.envoye_le) || "—"}</td>
              <td className="space-x-1 whitespace-nowrap text-right">
                <button type="button" onClick={() => envoyer(c)} className="rounded bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white">Envoyer par WhatsApp</button>
                {c.url && <button type="button" onClick={() => envoyer(c, true)} className="rounded border border-slate-300 px-2 py-0.5 text-xs">Renouveler</button>}
                {c.url && <button type="button" onClick={() => revoquer(c)} className="rounded border border-rose-300 px-2 py-0.5 text-xs text-rose-700">Révoquer</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminRequetes() {
  // Onglet initial : « ?onglet=liens » ouvre directement les liens clients (bouton de la rubrique des Paramètres)
  const [onglet, setOnglet] = useState(() => new URLSearchParams(window.location.search).get("onglet") || "requetes");
  const [donnees, setDonnees] = useState(null);
  const [lots, setLots] = useState([]);
  const [filtres, setFiltres] = useState({ etat: "", tenant_id: "", lot_id: "" });
  const [ouverte, setOuverte] = useState(null);
  const [nouveauLot, setNouveauLot] = useState({ titre: "", description: "" });

  const charger = useCallback(() => {
    apiClient.get("/admin/requetes", { params: filtres }).then((r) => setDonnees(r.data)).catch(() => setDonnees(null));
    apiClient.get("/admin/requetes-lots").then((r) => setLots(r.data.lots || [])).catch(() => {});
  }, [filtres]);
  useEffect(() => { charger(); }, [charger]);

  const creerLot = async () => {
    try {
      await apiClient.post("/admin/requetes-lots", nouveauLot);
      toast.success("Lot créé");
      setNouveauLot({ titre: "", description: "" });
      charger();
    } catch (e) { toast.error(erreur(e, "Lot non créé")); }
  };
  const etatLot = async (lot, etat) => {
    if (etat === "deploye" && !window.confirm(`Déployer le lot ${lot.numero} ? Ses ${lot.requetes} requête(s) passeront à « Déployée » et les clients seront invités à évaluer.`)) return;
    const attente = toast.loading("Patientez…");
    try {
      const r = await apiClient.patch(`/admin/requetes-lots/${lot.id}`, { etat });
      toast.success(etat === "deploye" ? `Lot déployé — ${r.data.clients_prevenus} client(s) prévenu(s)` : "Lot mis à jour", { id: attente });
      charger();
    } catch (e) { toast.error(erreur(e, "Mise à jour impossible"), { id: attente }); }
  };

  if (!donnees) return <p className="p-6 text-sm text-slate-500">Patientez…</p>;
  const res = donnees.resume || {};
  const choix = "rounded border border-slate-300 px-2 py-1 text-xs";
  return (
    <div className="space-y-4 p-4 md:p-6" data-testid="admin-requetes">
      <div>
        <h1 className="text-2xl font-display font-bold">Requêtes des clients</h1>
        <p className="text-sm text-slate-600">
          {res.total} requête(s) · {res.par_etat?.nouvelle || 0} nouvelle(s) · {res.par_etat?.en_cours || 0} en cours · {res.a_evaluer || 0} en attente d'évaluation
          {res.moyenne != null && ` · note moyenne ${res.moyenne}/5 (${res.evaluees} évaluation(s))`}
        </p>
      </div>
      <div className="flex gap-2">
        {[["requetes", "Requêtes"], ["lots", "Lots"], ["liens", "Liens clients (WhatsApp)"]].map(([k, v]) => (
          <button key={k} type="button" onClick={() => setOnglet(k)}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${onglet === k ? "bg-sky-700 text-white" : "border border-slate-300"}`}>{v}</button>
        ))}
      </div>

      {onglet === "requetes" ? (
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex flex-wrap gap-2">
            <select value={filtres.etat} onChange={(e) => setFiltres({ ...filtres, etat: e.target.value })} className={choix}>
              <option value="">Tous les états</option>
              {Object.entries(donnees.etats).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={filtres.tenant_id} onChange={(e) => setFiltres({ ...filtres, tenant_id: e.target.value })} className={choix}>
              <option value="">Tous les clients</option>
              {donnees.clients.map((c) => <option key={c.id} value={c.id}>{c.nom || c.id}</option>)}
            </select>
            <select value={filtres.lot_id} onChange={(e) => setFiltres({ ...filtres, lot_id: e.target.value })} className={choix}>
              <option value="">Tous les lots</option><option value="aucun">Sans lot</option>
              {lots.map((l) => <option key={l.id} value={l.id}>Lot {l.numero}</option>)}
            </select>
          </div>
          {donnees.requetes.length === 0 ? <p className="text-sm text-slate-500">Aucune requête.</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">N°</th><th>Client</th><th>Déposée le</th><th>Catégorie</th><th>Titre</th><th>Lot</th><th>État</th><th>Note</th></tr></thead>
              <tbody>
                {donnees.requetes.map((r) => (
                  <React.Fragment key={r.id}>
                    <tr className={`cursor-pointer border-t border-slate-100 ${ouverte === r.id ? "ligne-selectionnee" : ""}`} onClick={() => setOuverte(ouverte === r.id ? null : r.id)}>
                      <td className="py-1 font-mono text-xs">{r.numero}</td><td className="text-xs">{r.client_nom}</td>
                      <td className="text-xs">{dateHeure(r.cree_le)}</td>
                      <td className="text-xs">{r.libelle_categorie}{r.logiciel ? ` · ${r.logiciel}` : ""}{r.equipement ? ` · ${r.equipement}` : ""}</td>
                      <td>{r.titre}{r.a_audio ? " 🎤" : ""}{r.images?.length ? ` 🖼️${r.images.length}` : ""}{r.origine === "lien" ? " 🔗" : ""}</td><td className="text-xs">{r.lot_numero ? `Lot ${r.lot_numero}` : "—"}</td>
                      <td className="text-xs">{r.libelle_etat}</td><td className="text-xs">{r.evaluation ? `${r.evaluation.note}/5` : r.a_evaluer ? "attendue" : "—"}</td>
                    </tr>
                    {ouverte === r.id && <tr><td colSpan={8}><Detail r={r} etats={donnees.etats} lots={lots} onMaj={charger} /></td></tr>}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : onglet === "liens" ? <LiensClients /> : (
        <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-xs"><span className="font-semibold">Nouveau lot</span>
              <input value={nouveauLot.titre} onChange={(e) => setNouveauLot({ ...nouveauLot, titre: e.target.value })} placeholder="Titre du lot"
                className="mt-1 block w-64 rounded border border-slate-300 px-2 py-1 text-sm" /></label>
            <input value={nouveauLot.description} onChange={(e) => setNouveauLot({ ...nouveauLot, description: e.target.value })} placeholder="Description (facultatif)"
              className="w-72 rounded border border-slate-300 px-2 py-1 text-sm" />
            <button type="button" disabled={!nouveauLot.titre.trim()} onClick={creerLot} className="rounded bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">Créer le lot</button>
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">Lot</th><th>Titre</th><th>Requêtes</th><th>Créé le</th><th>État</th><th>Déployé le</th><th></th></tr></thead>
            <tbody>
              {lots.map((l) => (
                <tr key={l.id} className="border-t border-slate-100">
                  <td className="py-1 font-mono">{l.numero}</td><td>{l.titre}</td><td>{l.requetes}</td><td className="text-xs">{dateHeure(l.cree_le)}</td>
                  <td className="text-xs">{l.libelle_etat}</td><td className="text-xs">{dateHeure(l.deploye_le)}</td>
                  <td className="space-x-1 text-right">
                    {l.etat === "ouvert" && <button type="button" onClick={() => etatLot(l, "en_cours")} className="rounded border border-slate-300 px-2 py-0.5 text-xs">En cours</button>}
                    {l.etat !== "deploye" && <button type="button" onClick={() => etatLot(l, "deploye")} className="rounded bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white">Déployé</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
