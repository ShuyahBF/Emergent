// FacebookAnimationSection.jsx — Lot 96 : rubrique « 📣 Page Facebook animée par Liluvine » des Paramètres.
// Demande du propriétaire (09/10/2026) : Liluvine publie sur la page Facebook quelques photos de membres de
// beAuthentik avec leur propre message — visage MASQUÉ, texte = bio du membre relue par l'IA.
//   - réglages : activation, jours, heure, nombre, validation manuelle, légende, lien ;
//   - « Préparer maintenant » : demande des candidats à la plateforme, l'IA relit leur texte ;
//   - file : chaque publication à valider (Publier / Refuser), légende modifiable ; refus de l'IA visibles.
// Lot 132 — UNE CONFIGURATION PAR PLATEFORME (« Publication Facebook pour ZandGo, adLyn et bfmobility comme pour
// beAuthentik ») : un onglet par plateforme (page Facebook propre, réglages, kit de lancement, préparation) ;
// la file des publications se filtre par plateforme et par statut.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, Filter, Loader2, RefreshCw, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import KitFacebookBloc from "./KitFacebookBloc";

const JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];   // 0 = lundi (comme le serveur)
const LIBELLES = { a_valider: "À valider", publie: "Publiée", refuse: "Refusée", refuse_ia: "Refusée par l'IA", echec: "Échec" };
const COULEURS = { a_valider: "bg-amber-50 text-amber-800", publie: "bg-emerald-50 text-emerald-700", refuse: "bg-slate-100 text-slate-600",
                   refuse_ia: "bg-rose-50 text-rose-700", echec: "bg-rose-50 text-rose-700" };
// Lot 132 — ce que publie chaque type de plateforme, et les variables utilisables dans sa légende
const CONTENUS = {
  membre: { quoi: "des membres qui ont donné leur accord : photo au visage masqué, prénom, âge, ville et bio relue par l'IA",
            unite: "Membres", variables: "{prenom} {age_txt} {ville_txt} {bio} {lien}" },
  produit: { quoi: "des articles en vente : photo, nom, prix donné par la plateforme et lien vers l'article ; l'IA relit le texte (ni coordonnées, ni promesse trompeuse, jamais de prix inventé)",
             unite: "Articles", variables: "{nom} {description} {prix_txt} {lien_article} {boutique} {boutique_txt} {lien}" },
  vehicule: { quoi: "des véhicules disponibles : photo, nom, tarif donné par la plateforme et lien vers la page du véhicule ; l'IA relit le texte",
              unite: "Véhicules", variables: "{nom} {classe} {classe_txt} {description} {tarif_txt} {lien_article} {lien}" },
};

export default function FacebookAnimationSection() {
  const [etat, setEtat] = useState(null);         // {reglages, publications, page, plateformes, configurations}
  const [code, setCode] = useState(null);         // lot 132 : plateforme affichée (onglet)
  const [filtre, setFiltre] = useState("");       // lot 132 : filtre de la file par plateforme ("" = toutes)
  const [statut, setStatut] = useState("");       // filtre de la file par statut ("" = tous)
  const [regl, setRegl] = useState(null);         // réglages en cours de modification (plateforme affichée)
  const [occupe, setOccupe] = useState(null);     // action en cours (id de publication ou nom d'action)
  const [textes, setTextes] = useState({});       // légendes retouchées, par publication
  const [pages, setPages] = useState(null);       // lot 97 : pages du compte Facebook connecté (id, nom)
  const [erreurPages, setErreurPages] = useState("");   // lot 99 : message clair si Facebook refuse la lecture

  // Lecture des réglages de la plateforme affichée, de sa Page et de la file (filtrée)
  const charger = useCallback(async (plateforme = code) => {
    try {
      const params = {};
      if (plateforme) params.plateforme = plateforme;
      if (filtre) params.filtre = filtre;
      if (statut) params.statut = statut;
      const r = await apiClient.get("/admin/facebook/animation", { params });
      setEtat(r.data);
      setRegl(r.data.reglages);
      if (!plateforme) setCode(r.data.reglages.plateforme);
    } catch { setEtat({ erreur: true }); }
  }, [code, filtre, statut]);
  useEffect(() => { charger(); }, [filtre, statut]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Changement d'onglet : réglages et page de l'autre plateforme (la liste des pages reste à recharger)
  const changerPlateforme = (c) => { setCode(c); setPages(null); setErreurPages(""); setTextes({}); charger(c); };

  // Lot 97 — page propre de la plateforme : la page active de SAWALI reste celle de SAWALI
  const chargerPages = async () => {
    setOccupe("pages"); setErreurPages("");
    const attente = toast.loading("Patientez… lecture des pages du compte Facebook");
    try { setPages((await apiClient.get("/admin/facebook/animation/pages")).data.pages); toast.dismiss(attente); }
    catch (err) { toast.dismiss(attente); setErreurPages(err?.response?.data?.detail || "Lecture des pages impossible"); }
    finally { setOccupe(null); }
  };
  // Lot 99 — reconnexion du compte Facebook sans quitter la rubrique ; dans la fenêtre de Facebook, cocher AUSSI
  // la page de la plateforme (beAuthentik, ZandGo, adLyn, bfmobility…).
  const reconnecterFacebook = async () => {
    try {
      const r = await apiClient.get("/admin/facebook/oauth/authorize");
      const fenetre = window.open(r.data.authorization_url, "facebook-oauth", "width=600,height=720");
      if (!fenetre) window.location.href = r.data.authorization_url;
      setErreurPages(""); setPages(null);
    } catch (err) { toast.error(err?.response?.data?.detail || "Reconnexion impossible"); }
  };
  const choisirPage = async (pageId) => {
    setOccupe("pages");
    try {
      await apiClient.put("/admin/facebook/animation/page", { page_id: pageId, plateforme: code });
      toast.success(pageId ? `Page de ${regl.nom} enregistrée` : "Page retirée");
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Choix impossible"); }
    finally { setOccupe(null); }
  };

  const enregistrer = async () => {
    setOccupe("reglages");
    try {
      await apiClient.put("/admin/facebook/animation/reglages", { ...regl, plateforme: code });
      toast.success(`Réglages de ${regl.nom} enregistrés`); await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setOccupe(null); }
  };

  // Préparation immédiate (avec « Patientez… » : appel à la plateforme puis relecture par l'IA)
  const preparer = async () => {
    setOccupe("preparer");
    const attente = toast.loading(`Patientez… Liluvine interroge ${regl.nom} et l'IA relit les textes`);
    try {
      const r = await apiClient.post("/admin/facebook/animation/preparer", null, { params: { plateforme: code } });
      toast.success(`${r.data.crees} publication(s) préparée(s) pour ${regl.nom}`, { id: attente });
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Préparation impossible", { id: attente }); }
    finally { setOccupe(null); }
  };

  // Publier (après retouche éventuelle de la légende) ou refuser une publication de la file
  const agir = async (p, action) => {
    setOccupe(p.id);
    const attente = action === "valider" ? toast.loading("Patientez… publication sur Facebook") : undefined;
    try {
      if (action === "valider" && textes[p.id] !== undefined && textes[p.id] !== p.texte) {
        await apiClient.put(`/admin/facebook/animation/publications/${p.id}`, { texte: textes[p.id] });
      }
      const r = await apiClient.post(`/admin/facebook/animation/publications/${p.id}/${action}`);
      if (action === "valider") {
        r.data.statut === "publie" ? toast.success("Publiée sur la page Facebook", { id: attente }) : toast.error(`Échec : ${r.data.erreur}`, { id: attente });
      } else toast.success("Publication refusée");
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Action impossible", attente ? { id: attente } : undefined); }
    finally { setOccupe(null); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">Rubrique indisponible.</p>;
  const basculerJour = (j) => setRegl({ ...regl, jours: regl.jours.includes(j) ? regl.jours.filter((x) => x !== j) : [...regl.jours, j].sort() });
  const contenu = CONTENUS[regl.contenu] || CONTENUS.produit;
  const configurations = etat.configurations || [];
  const nomDe = (c) => (configurations.find((x) => x.code === c) || {}).nom || c;
  const emetteurAbsent = !etat.plateformes.includes(code);

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-facebook-animation">
      <p className="text-xs text-slate-600">
        Liluvine anime la page Facebook de <b>chaque plateforme</b> : une configuration par plateforme (page propre,
        jours et heure, validation, légende). Choisissez la plateforme ci-dessous.
      </p>

      {/* Lot 132 — un onglet par plateforme ; pastille verte = préparation automatique activée */}
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Plateforme">
        {configurations.map((c) => (
          <button key={c.code} type="button" role="tab" aria-selected={c.code === code} onClick={() => changerPlateforme(c.code)}
                  data-testid={`fb-onglet-${c.code}`}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${c.code === code ? "bg-sawali-blue text-white" : "border border-slate-300 text-slate-700"}`}>
            <span className={`h-2 w-2 rounded-full ${c.reglages.actif ? "bg-emerald-400" : "bg-slate-300"}`} aria-hidden="true" />
            {c.nom}
            {!c.page.propre && c.code !== etat.historique && <span className="font-normal opacity-75">· sans page</span>}
          </button>
        ))}
      </div>

      <p className="text-xs text-slate-600">
        <b>{regl.nom}</b> : Liluvine publie {contenu.quoi}.
        {emetteurAbsent && (
          <span className="mt-1 block rounded bg-amber-50 px-2 py-1 text-amber-800">
            Aucun émetteur Liluvine « {code} » : créez-le (Transmission universelle) avec l'URL de retour de la
            plateforme, sinon la préparation est impossible.
          </span>
        )}
      </p>

      {/* Lot 97 — page Facebook de la plateforme, distincte de la page active de SAWALI */}
      <div className="rounded-lg bg-slate-50 p-3 text-sm">
        Page de publication de {regl.nom} :{" "}
        {etat.page.propre
          ? <b className="text-emerald-700">{etat.page.nom}</b>
          : code === etat.historique && etat.page.connectee
            ? <span className="text-amber-700">aucune page propre — la page active de SAWALI (<b>{etat.page.nom}</b>) serait utilisée</span>
            : <b className="text-rose-700">aucune — choisissez la page de {regl.nom} (rien ne sera publié sans elle)</b>}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {pages === null ? (
            <button type="button" onClick={chargerPages} disabled={occupe === "pages"} className="rounded border border-slate-300 px-2.5 py-1 text-xs">
              Choisir la page de {regl.nom}…
            </button>
          ) : (
            <select defaultValue="" disabled={occupe === "pages"} onChange={(e) => e.target.value !== "" && choisirPage(e.target.value === "-" ? "" : e.target.value)}
                    className="rounded border border-slate-300 px-2 py-1 text-xs">
              <option value="">— Choisir une page —</option>
              {pages.map((p) => <option key={p.id} value={p.id}>{p.nom}</option>)}
              <option value="-">{code === etat.historique ? "(utiliser la page active de SAWALI)" : "(retirer la page)"}</option>
            </select>
          )}
          {/* Toujours proposé : utile si la connexion a expiré ou si la page voulue n'est pas dans la liste */}
          <button type="button" onClick={reconnecterFacebook} className="inline-flex items-center gap-1 rounded border border-blue-300 bg-blue-50 px-2.5 py-1 text-xs text-blue-800">
            <RefreshCw className="h-3 w-3" aria-hidden="true" /> Reconnecter Facebook
          </button>
        </div>
        {erreurPages && <p className="mt-2 text-xs text-rose-700" data-testid="fb-pages-erreur">{erreurPages}</p>}
        {pages !== null && (
          <p className="mt-2 text-xs text-slate-500">
            La page voulue n'est pas dans la liste ? Le compte Facebook connecté doit en être administrateur : cliquez
            « Reconnecter Facebook » et cochez-la dans la fenêtre de Facebook.
          </p>
        )}
      </div>

      {/* Lot 105 / 132 — kit de lancement de la Page de la plateforme (visuels, « À propos », annonces) */}
      <KitFacebookBloc key={code} plateforme={code} pagePropre={etat.page.propre} onCharge={() => charger()} />

      {/* Réglages de la plateforme affichée */}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={regl.actif} onChange={(e) => setRegl({ ...regl, actif: e.target.checked })} />
          Préparation automatique activée
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={regl.validation_manuelle} onChange={(e) => setRegl({ ...regl, validation_manuelle: e.target.checked })} />
          Validation avant publication (recommandé)
        </label>
        <div className="text-sm">
          Jours :{" "}
          {JOURS.map((j, i) => (
            <button key={j} type="button" onClick={() => basculerJour(i)} aria-pressed={regl.jours.includes(i)}
                    className={`mr-1 rounded px-2 py-0.5 text-xs ${regl.jours.includes(i) ? "bg-sawali-blue text-white" : "border border-slate-300"}`}>{j}</button>
          ))}
        </div>
        <label className="text-sm">Heure (Ouagadougou) :{" "}
          <input type="time" value={regl.heure} onChange={(e) => setRegl({ ...regl, heure: e.target.value })} className="rounded border border-slate-300 px-2 py-0.5" />
        </label>
        <label className="text-sm">{contenu.unite} par préparation :{" "}
          <input type="number" min={1} max={5} value={regl.nombre} onChange={(e) => setRegl({ ...regl, nombre: Number(e.target.value) })} className="w-16 rounded border border-slate-300 px-2 py-0.5" />
        </label>
        <label className="text-sm sm:col-span-2">Lien (site de {regl.nom}) :{" "}
          <input value={regl.lien} onChange={(e) => setRegl({ ...regl, lien: e.target.value })} placeholder="https://…" className="w-full rounded border border-slate-300 px-2 py-1" />
        </label>
        <label className="text-sm sm:col-span-2">Modèle de légende ({contenu.variables}) :
          <textarea rows={6} value={regl.legende} onChange={(e) => setRegl({ ...regl, legende: e.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs" />
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={enregistrer} disabled={occupe === "reglages"} className="rounded-lg bg-sawali-blue px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-50">
          Enregistrer les réglages de {regl.nom}
        </button>
        <button type="button" onClick={preparer} disabled={occupe === "preparer" || emetteurAbsent} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-xs disabled:opacity-50">
          {occupe === "preparer" && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Préparer maintenant
        </button>
      </div>

      {/* File des publications, filtrable par plateforme (lot 132) et par statut */}
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="mr-auto text-sm font-semibold">Publications</h4>
        <Filter className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
        <select value={filtre} onChange={(e) => setFiltre(e.target.value)} aria-label="Filtrer par plateforme" data-testid="fb-filtre-plateforme"
                className="rounded border border-slate-300 px-2 py-1 text-xs">
          <option value="">Toutes les plateformes</option>
          {configurations.map((c) => <option key={c.code} value={c.code}>{c.nom}</option>)}
        </select>
        <select value={statut} onChange={(e) => setStatut(e.target.value)} aria-label="Filtrer par statut" className="rounded border border-slate-300 px-2 py-1 text-xs">
          <option value="">Tous les statuts</option>
          {Object.entries(LIBELLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {etat.publications.length === 0 ? (
        <p className="text-xs text-slate-500">Aucune publication. Cliquez sur « Préparer maintenant » pour en créer.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {etat.publications.map((p) => (
            <div key={p.id} className="overflow-hidden rounded-lg border border-slate-200">
              <img src={p.image_url} alt={p.prenom || "Publication"} className={`${p.type === "kit" ? "aspect-[4/5]" : "aspect-square"} w-full object-cover`} />
              <div className="space-y-2 p-2 text-xs">
                <p className="font-semibold text-slate-800">
                  <span className="mr-1 rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-600">{nomDe(p.plateforme)}</span>
                  {p.type === "kit" ? `Lancement ${p.rang}/${p.total_kit || 8} · ${p.prenom}` : p.prenom}
                </p>
                <span className={`inline-block rounded-full px-2 py-0.5 font-semibold ${COULEURS[p.statut]}`}>{LIBELLES[p.statut]}</span>
                {p.statut === "refuse_ia" && <p className="text-rose-700">Raison : {p.avis_ia?.raison}</p>}
                {p.erreur && <p className="text-rose-700">{p.erreur}</p>}
                {["a_valider", "echec"].includes(p.statut) ? (
                  <>
                    <textarea rows={6} value={textes[p.id] ?? p.texte} onChange={(e) => setTextes({ ...textes, [p.id]: e.target.value })}
                              className="w-full rounded border border-slate-300 px-2 py-1" />
                    <div className="flex gap-2">
                      <button type="button" disabled={occupe === p.id} onClick={() => agir(p, "valider")} className="inline-flex flex-1 items-center justify-center gap-1 rounded bg-emerald-600 py-1.5 font-semibold text-white disabled:opacity-50">
                        <Check className="h-3.5 w-3.5" aria-hidden="true" /> Publier
                      </button>
                      <button type="button" disabled={occupe === p.id} onClick={() => agir(p, "refuser")} className="inline-flex flex-1 items-center justify-center gap-1 rounded bg-slate-200 py-1.5 font-semibold disabled:opacity-50">
                        <X className="h-3.5 w-3.5" aria-hidden="true" /> Refuser
                      </button>
                    </div>
                  </>
                ) : p.texte && <p className="whitespace-pre-line text-slate-600">{p.texte}</p>}
                <p className="text-slate-400">{new Date(p.publie_le || p.cree_le).toLocaleString("fr-FR")}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
