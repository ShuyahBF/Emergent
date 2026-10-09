// FacebookAnimationSection.jsx — Lot 96 : rubrique « 📣 Page Facebook animée par Liluvine » des Paramètres.
// Demande du propriétaire (09/10/2026) : Liluvine publie sur la page Facebook quelques photos de membres de
// beAuthentik avec leur propre message — visage MASQUÉ, texte = bio du membre relue par l'IA.
//   - réglages : activation, plateforme, jours, heure, nombre de membres, validation manuelle, légende, lien ;
//   - « Préparer maintenant » : demande des candidats à la plateforme, l'IA relit leur bio ;
//   - file : chaque publication à valider (Publier / Refuser), légende modifiable ; refus de l'IA visibles.
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

const JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];   // 0 = lundi (comme le serveur)
const LIBELLES = { a_valider: "À valider", publie: "Publiée", refuse: "Refusée", refuse_ia: "Bio refusée par l'IA", echec: "Échec" };
const COULEURS = { a_valider: "bg-amber-50 text-amber-800", publie: "bg-emerald-50 text-emerald-700", refuse: "bg-slate-100 text-slate-600",
                   refuse_ia: "bg-rose-50 text-rose-700", echec: "bg-rose-50 text-rose-700" };

export default function FacebookAnimationSection() {
  const [etat, setEtat] = useState(null);       // {reglages, publications, page, plateformes}
  const [regl, setRegl] = useState(null);       // réglages en cours de modification
  const [occupe, setOccupe] = useState(null);   // action en cours (id de publication ou nom d'action)
  const [textes, setTextes] = useState({});     // légendes retouchées, par publication
  const [pages, setPages] = useState(null);     // lot 97 : pages du compte Facebook connecté (id, nom)

  // Lecture des réglages, de la Page connectée et de la file
  const charger = async () => {
    try {
      const r = await apiClient.get("/admin/facebook/animation");
      setEtat(r.data);
      setRegl(r.data.reglages);
    } catch { setEtat({ erreur: true }); }
  };
  useEffect(() => { charger(); }, []);

  // Lot 97 — page propre à l'animation (ex. page beAuthentik) : la page active de SAWALI reste celle de SAWALI
  const chargerPages = async () => {
    setOccupe("pages");
    try { setPages((await apiClient.get("/admin/facebook/animation/pages")).data.pages); }
    catch (err) { toast.error(err?.response?.data?.detail || "Lecture des pages impossible"); }
    finally { setOccupe(null); }
  };
  const choisirPage = async (pageId) => {
    setOccupe("pages");
    try {
      await apiClient.put("/admin/facebook/animation/page", { page_id: pageId });
      toast.success(pageId ? "Page de l'animation enregistrée" : "Retour à la page active de SAWALI");
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Choix impossible"); }
    finally { setOccupe(null); }
  };

  const enregistrer = async () => {
    setOccupe("reglages");
    try { await apiClient.put("/admin/facebook/animation/reglages", regl); toast.success("Réglages enregistrés"); await charger(); }
    catch (err) { toast.error(err?.response?.data?.detail || "Enregistrement impossible"); }
    finally { setOccupe(null); }
  };

  // Préparation immédiate (avec « Patientez… » : appel à la plateforme puis relecture par l'IA)
  const preparer = async () => {
    setOccupe("preparer");
    const attente = toast.loading("Patientez… Liluvine choisit des membres et l'IA relit leur bio");
    try {
      const r = await apiClient.post("/admin/facebook/animation/preparer");
      toast.success(`${r.data.crees} publication(s) préparée(s)`, { id: attente });
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Préparation impossible", { id: attente }); }
    finally { setOccupe(null); }
  };

  // Publier (après retouche éventuelle de la légende) ou refuser une publication de la file
  const agir = async (p, action) => {
    setOccupe(p.id);
    try {
      if (action === "valider" && textes[p.id] !== undefined && textes[p.id] !== p.texte) {
        await apiClient.put(`/admin/facebook/animation/publications/${p.id}`, { texte: textes[p.id] });
      }
      const r = await apiClient.post(`/admin/facebook/animation/publications/${p.id}/${action}`);
      if (action === "valider") {
        r.data.statut === "publie" ? toast.success("Publiée sur la page Facebook") : toast.error(`Échec : ${r.data.erreur}`);
      } else toast.success("Publication refusée");
      await charger();
    } catch (err) { toast.error(err?.response?.data?.detail || "Action impossible"); }
    finally { setOccupe(null); }
  };

  if (!etat) return <p className="text-sm text-slate-500">Patientez…</p>;
  if (etat.erreur) return <p className="text-sm text-red-700">Rubrique indisponible.</p>;
  const basculerJour = (j) => setRegl({ ...regl, jours: regl.jours.includes(j) ? regl.jours.filter((x) => x !== j) : [...regl.jours, j].sort() });

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="rubrique-facebook-animation">
      <p className="text-xs text-slate-600">
        Liluvine publie sur la page Facebook des membres <b>qui ont donné leur accord</b> sur beAuthentik : photo avec le
        <b> visage masqué</b>, prénom, âge, ville et bio <b>relue par l'IA</b> (une bio avec coordonnées, lien, propos
        déplacés… est refusée).
      </p>

      {/* Lot 97 — page Facebook de la plateforme, distincte de la page active de SAWALI */}
      <div className="rounded-lg bg-slate-50 p-3 text-sm">
        Page de publication :{" "}
        {etat.page.propre
          ? <b className="text-emerald-700">{etat.page.nom}</b>
          : etat.page.connectee
            ? <span className="text-amber-700">aucune page propre — la page active de SAWALI (<b>{etat.page.nom}</b>) serait utilisée</span>
            : <b className="text-rose-700">aucune — connectez le compte Facebook dans la rubrique Facebook</b>}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {pages === null ? (
            <button type="button" onClick={chargerPages} disabled={occupe === "pages"} className="rounded border border-slate-300 px-2.5 py-1 text-xs">
              Choisir la page de la plateforme…
            </button>
          ) : (
            <select defaultValue="" disabled={occupe === "pages"} onChange={(e) => e.target.value !== "" && choisirPage(e.target.value === "-" ? "" : e.target.value)}
                    className="rounded border border-slate-300 px-2 py-1 text-xs">
              <option value="">— Choisir une page —</option>
              {pages.map((p) => <option key={p.id} value={p.id}>{p.nom}</option>)}
              <option value="-">(utiliser la page active de SAWALI)</option>
            </select>
          )}
        </div>
      </div>

      {/* Réglages */}
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
            <button key={j} type="button" onClick={() => basculerJour(i)}
                    className={`mr-1 rounded px-2 py-0.5 text-xs ${regl.jours.includes(i) ? "bg-sawali-blue text-white" : "border border-slate-300"}`}>{j}</button>
          ))}
        </div>
        <label className="text-sm">Heure (Ouagadougou) :{" "}
          <input type="time" value={regl.heure} onChange={(e) => setRegl({ ...regl, heure: e.target.value })} className="rounded border border-slate-300 px-2 py-0.5" />
        </label>
        <label className="text-sm">Membres par préparation :{" "}
          <input type="number" min={1} max={5} value={regl.nombre} onChange={(e) => setRegl({ ...regl, nombre: Number(e.target.value) })} className="w-16 rounded border border-slate-300 px-2 py-0.5" />
        </label>
        <label className="text-sm">Plateforme :{" "}
          <select value={regl.plateforme} onChange={(e) => setRegl({ ...regl, plateforme: e.target.value })} className="rounded border border-slate-300 px-2 py-0.5">
            {[...new Set([regl.plateforme, ...etat.plateformes])].map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">Lien d'inscription :{" "}
          <input value={regl.lien} onChange={(e) => setRegl({ ...regl, lien: e.target.value })} className="w-full rounded border border-slate-300 px-2 py-1" />
        </label>
        <label className="text-sm sm:col-span-2">Modèle de légende ({"{prenom} {age_txt} {ville_txt} {bio} {lien}"}) :
          <textarea rows={4} value={regl.legende} onChange={(e) => setRegl({ ...regl, legende: e.target.value })} className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-xs" />
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={enregistrer} disabled={occupe === "reglages"} className="rounded-lg bg-sawali-blue px-3.5 py-2 text-xs font-semibold text-white disabled:opacity-50">
          Enregistrer les réglages
        </button>
        <button type="button" onClick={preparer} disabled={occupe === "preparer"} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-3.5 py-2 text-xs">
          {occupe === "preparer" && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Préparer maintenant
        </button>
      </div>

      {/* File des publications */}
      <h4 className="text-sm font-semibold">Publications</h4>
      {etat.publications.length === 0 ? (
        <p className="text-xs text-slate-500">Aucune publication. Cliquez sur « Préparer maintenant » pour en créer.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {etat.publications.map((p) => (
            <div key={p.id} className="overflow-hidden rounded-lg border border-slate-200">
              <img src={p.image_url} alt={p.prenom || "Membre"} className="aspect-square w-full object-cover" />
              <div className="space-y-2 p-2 text-xs">
                <span className={`inline-block rounded-full px-2 py-0.5 font-semibold ${COULEURS[p.statut]}`}>{LIBELLES[p.statut]}</span>
                {p.statut === "refuse_ia" && <p className="text-rose-700">Raison : {p.avis_ia?.raison}</p>}
                {p.erreur && <p className="text-rose-700">{p.erreur}</p>}
                {["a_valider", "echec"].includes(p.statut) ? (
                  <>
                    <textarea rows={6} value={textes[p.id] ?? p.texte} onChange={(e) => setTextes({ ...textes, [p.id]: e.target.value })}
                              className="w-full rounded border border-slate-300 px-2 py-1" />
                    <div className="flex gap-2">
                      <button type="button" disabled={occupe === p.id} onClick={() => agir(p, "valider")} className="flex-1 rounded bg-emerald-600 py-1.5 font-semibold text-white disabled:opacity-50">Publier</button>
                      <button type="button" disabled={occupe === p.id} onClick={() => agir(p, "refuser")} className="flex-1 rounded bg-slate-200 py-1.5 font-semibold disabled:opacity-50">Refuser</button>
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
