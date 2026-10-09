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
import { Enregistreur, ImagesRequete, SelecteurImages } from "@/components/RequeteOutils";

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
      <p className="text-slate-500">Déposée le {dateHeure(r.cree_le)} par {r.auteur_nom} ({r.client_nom}){r.origine === "lien" ? " · via le lien personnel" : r.origine === "sawali" ? " · saisie par SAWALI" : ""}</p>
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

// Lot 86.3 — saisie d'une requête AU NOM d'un client (appel téléphonique, visite, message reçu ailleurs)
function NouvelleRequeteAdmin({ categories, onCree, onFermer }) {
  const [clients, setClients] = useState([]);
  const [f, setF] = useState({ tenant_id: "", categorie: "dysfonctionnement", titre: "", texte: "", logiciel: "", equipement: "" });
  const [audio, setAudio] = useState(null);
  const [images, setImages] = useState([]);
  const [envoi, setEnvoi] = useState(false);
  // Liste de tous les clients de SAWALI (même source que l'onglet « Liens clients »)
  useEffect(() => { apiClient.get("/admin/requetes-liens").then((r) => setClients(r.data.clients || [])).catch(() => {}); }, []);
  const enregistrer = async () => {
    setEnvoi(true);
    const attente = toast.loading("Patientez… enregistrement de la requête");
    try {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => fd.append(k, v));
      if (audio) fd.append("audio", audio);
      images.forEach((img) => fd.append("images", img, img.name));
      const r = await apiClient.post("/admin/requetes", fd);
      toast.success(`Requête ${r.data.numero} enregistrée pour ${r.data.client_nom}`, { id: attente });
      onCree();
    } catch (e) { toast.error(erreur(e, "Requête non enregistrée"), { id: attente }); }
    finally { setEnvoi(false); }
  };
  const champ = "mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm";
  return (
    <div className="mb-3 space-y-2 rounded-xl border border-sky-200 bg-sky-50/60 p-3" data-testid="nouvelle-requete-admin">
      <p className="text-sm font-semibold">Nouvelle requête au nom d'un client</p>
      <div className="grid gap-2 sm:grid-cols-3">
        <label className="text-xs"><span className="font-semibold">Client</span>
          <select value={f.tenant_id} onChange={(e) => setF({ ...f, tenant_id: e.target.value })} className={champ}>
            <option value="">— choisir —</option>
            {clients.map((c) => <option key={c.id} value={c.id}>{c.nom}</option>)}
          </select></label>
        <label className="text-xs"><span className="font-semibold">Catégorie</span>
          <select value={f.categorie} onChange={(e) => setF({ ...f, categorie: e.target.value })} className={champ}>
            {Object.entries(categories || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select></label>
        {f.categorie === "logiciel" && <label className="text-xs"><span className="font-semibold">Logiciel</span>
          <input value={f.logiciel} onChange={(e) => setF({ ...f, logiciel: e.target.value })} className={champ} /></label>}
        {f.categorie === "equipement" && <label className="text-xs"><span className="font-semibold">Équipement</span>
          <input value={f.equipement} onChange={(e) => setF({ ...f, equipement: e.target.value })} className={champ} /></label>}
        <label className="text-xs sm:col-span-3"><span className="font-semibold">Titre</span>
          <input value={f.titre} onChange={(e) => setF({ ...f, titre: e.target.value })} className={champ} /></label>
        <label className="text-xs sm:col-span-3"><span className="font-semibold">Description</span>
          <textarea rows={3} value={f.texte} onChange={(e) => setF({ ...f, texte: e.target.value })} className={champ} /></label>
      </div>
      <Enregistreur audio={audio} onAudio={setAudio} />
      <SelecteurImages images={images} onImages={setImages} />
      <div className="flex gap-2">
        <button type="button" disabled={!f.tenant_id || envoi} onClick={enregistrer} className="rounded bg-sky-700 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">Enregistrer la requête</button>
        <button type="button" onClick={onFermer} className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm">Annuler</button>
      </div>
    </div>
  );
}

// Lot 86.2 — modèles WhatsApp Meta du lien (envoi possible à tout moment, hors fenêtre de 24 h)
const LIBELLE_ETAT_MODELE = {
  APPROVED: ["Approuvé", "bg-emerald-100 text-emerald-800"], PENDING: ["En revue chez Meta", "bg-amber-100 text-amber-800"],
  REJECTED: ["Refusé", "bg-rose-100 text-rose-800"], ABSENT: ["Pas encore créé", "bg-slate-100 text-slate-700"],
  EXISTANT: ["Déjà créé", "bg-slate-100 text-slate-700"],
};
function ModelesMeta() {
  const [modeles, setModeles] = useState(null);
  const charger = useCallback(() => {
    apiClient.get("/admin/requetes-modeles-meta").then((r) => setModeles(r.data.modeles)).catch((e) => setModeles({ erreur: erreur(e, "État des modèles indisponible") }));
  }, []);
  useEffect(() => { charger(); }, [charger]);
  const creer = async () => {
    const attente = toast.loading("Patientez… envoi des modèles à Meta");
    try {
      const r = await apiClient.post("/admin/requetes-modeles-meta");
      const ko = r.data.resultats.filter((x) => !x.ok);
      if (ko.length) toast.error(ko.map((x) => `${x.nom} : ${x.erreur}`).join(" · "), { id: attente });
      else toast.success("Modèles soumis à Meta — approbation en général en quelques minutes", { id: attente });
      charger();
    } catch (e) { toast.error(erreur(e, "Création impossible"), { id: attente }); }
  };
  if (!modeles) return <p className="text-xs text-slate-500">Patientez… état des modèles Meta</p>;
  if (modeles.erreur) return <p className="text-xs text-rose-700">{modeles.erreur}</p>;
  const tousApprouves = modeles.every((m) => m.etat === "APPROVED");
  return (
    <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50/50 p-3 text-xs" data-testid="modeles-meta-requetes">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">Modèles WhatsApp Meta</span>
        <span className="text-slate-600">— permettent d'envoyer le lien à tout moment (sans attendre que le client ait écrit dans les 24 h), avec un bouton « Ouvrir mes requêtes ».</span>
        {!tousApprouves && <button type="button" onClick={creer} className="rounded bg-emerald-600 px-2 py-0.5 font-semibold text-white">Créer les modèles chez Meta</button>}
        <button type="button" onClick={charger} className="rounded border border-slate-300 bg-white px-2 py-0.5">Actualiser</button>
      </div>
      {modeles.map((m) => {
        const [libelle, couleur] = LIBELLE_ETAT_MODELE[m.etat] || [m.etat, "bg-slate-100 text-slate-700"];
        return (
          <div key={m.nom} className="rounded border border-slate-200 bg-white p-2">
            <p><span className="font-mono">{m.nom}</span> <span className={`ml-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${couleur}`}>{libelle}</span></p>
            <p className="mt-1 text-slate-600">{m.texte}</p>
          </div>
        );
      })}
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
      toast.success(e.whatsapp || e.email ? `Lien envoyé${e.whatsapp ? (e.mode === "modele" ? " par WhatsApp (modèle Meta)" : " par WhatsApp") : ""}${e.email ? `${e.whatsapp ? " et" : ""} par e-mail` : ""}`
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
      <ModelesMeta />
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
  const [saisie, setSaisie] = useState(false);   // lot 86.3 : formulaire « Nouvelle requête » ouvert

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
          {saisie && <NouvelleRequeteAdmin categories={donnees.categories} onFermer={() => setSaisie(false)} onCree={() => { setSaisie(false); charger(); }} />}
          <div className="mb-2 flex flex-wrap gap-2">
            {!saisie && <button type="button" onClick={() => setSaisie(true)} className="rounded bg-sky-700 px-3 py-1 text-xs font-semibold text-white">+ Nouvelle requête</button>}
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
          {donnees.requetes.length === 0 ? (
            <div className="space-y-1 text-sm text-slate-500">
              <p>Aucune requête{filtres.etat || filtres.tenant_id || filtres.lot_id ? " avec ces filtres" : ""}.</p>
              <p className="text-xs">Les clients déposent leurs requêtes depuis le <b>lien reçu sur WhatsApp</b> (onglet « Liens clients ») ou leur portail (« Mes requêtes »).
                Vous pouvez aussi en saisir une pour un client avec <b>« + Nouvelle requête »</b>. Les lots se créent dans l'onglet « Lots ».</p>
            </div>
          ) : (
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
