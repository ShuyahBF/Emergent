/*
  Lot 40 — « Carrousel WhatsApp » : 2 à 10 cartes (photo, titre, texte, bouton) dans un seul
  message WhatsApp, comme le carrousel d'adLyn.
  - Portail (admin=false) : le client envoie à SES contacts et groupes qui ont accepté de
    recevoir ses messages WhatsApp. Fonction activable « Carrousel WhatsApp »
    (SMART Communications, Admin) ; la fonction « WhatsApp » doit aussi être active.
  - Administration (admin=true) : SAWALI envoie à ses clients qui ont accepté, et règle le
    nom et la langue des modèles Meta.
  Chaque carte vient d'un produit de la caisse (photo, nom, prix, « Voir le produit ») ou est
  libre (image envoyée, générée ou de la médiathèque ; titre, texte, lien).
  API : /me/whatsapp/carrousel et /admin/whatsapp/carrousel (backend/routes/carrousel_whatsapp.py).
*/
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRight, CheckCircle2, Copy, FolderOpen, GalleryHorizontalEnd, ImagePlus, Loader2, Package, Plus,
  RefreshCw, Save, Send, Settings, Sparkles, Trash2, Users, XCircle,
} from "lucide-react";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";

const erreur = (e, defaut) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg).join(" ; ");
  return d || defaut;
};
const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
const carteVide = () => ({ source: "libre", image_url: "", titre: "", texte: "", lien: "" });
// Cartes telles que le serveur les attend (une carte produit ne garde que son produit et ses textes)
const cartesPourServeur = (cartes) => cartes.map((c) => (c.source === "produit"
  ? { source: "produit", produit_id: c.produit_id || null, titre: c.titre || null, texte: c.texte || null }
  : { source: "libre", image_url: c.image_url || "", titre: c.titre || "", texte: c.texte || "", lien: c.lien || "" }));
const champ = "w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500";

// Aperçu d'une carte, à la façon de WhatsApp
function ApercuCarte({ carte, produit }) {
  const image = carte.image_url || produit?.image_url;
  const titre = carte.titre || produit?.nom || "Titre";
  const texte = carte.texte || produit?.prix || "";
  return (
    <div className="w-44 shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      {image ? <img src={image} alt="" className="h-28 w-full object-cover" /> : <div className="h-28 bg-slate-100" />}
      <div className="p-2">
        <div className="truncate text-sm font-semibold text-slate-800">{titre}</div>
        <div className="truncate text-xs text-slate-600">{texte || "—"}</div>
      </div>
      <div className="border-t border-slate-100 py-1.5 text-center text-xs font-semibold text-sky-600">
        {carte.source === "produit" ? "Voir le produit" : "Ouvrir"}
      </div>
    </div>
  );
}

// Choix d'une image : galerie (générées, médiathèque, envoyées), envoi d'un fichier ou adresse
function ChoixImage({ base, images, onEnvoyee, valeur, onChange, titre = "", ia = false }) {
  const [ouvert, setOuvert] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  // Lot 75 — image générée par l'IA : 1) description → « Générer » (aperçu) ;
  // 2) si l'image convient → « Utiliser cette image » : enregistrée, son adresse va dans le champ.
  const [prompt, setPrompt] = useState("");
  const [apercu, setApercu] = useState(null);            // { apercu_id, apercu (data:image/png…) }
  const [generation, setGeneration] = useState(false);
  const [retenue, setRetenue] = useState(false);
  const [secondes, setSecondes] = useState(0);
  useEffect(() => {                                     // compteur du toast « Patientez… »
    if (!generation) { setSecondes(0); return undefined; }
    const t = setInterval(() => setSecondes((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [generation]);

  const generer = async () => {
    if (prompt.trim().length < 3) { toast.error("Décrivez l'image souhaitée (quelques mots au moins)."); return; }
    setGeneration(true);
    setApercu(null);
    try {
      const { data } = await apiClient.post(`${base}/images/ia`, { prompt: prompt.trim(), titre }, { timeout: 180000 });
      setApercu(data);
    } catch (e) {
      toast.error(erreur(e, "Génération impossible"));
    } finally {
      setGeneration(false);
    }
  };

  const retenir = async () => {
    if (!apercu) return;
    setRetenue(true);
    try {
      const { data } = await apiClient.post(`${base}/images/ia/${apercu.apercu_id}/retenir`);
      onChange(data.url);                               // l'adresse https://… remplit le champ de la carte
      onEnvoyee();                                      // la galerie se met à jour
      setApercu(null);
      toast.success("Image ajoutée à la carte");
    } catch (e) {
      toast.error(erreur(e, "Enregistrement de l'image impossible"));
    } finally {
      setRetenue(false);
    }
  };

  const envoyer = async (fichier) => {
    if (!fichier) return;
    setEnvoi(true);
    try {
      const fd = new FormData();
      fd.append("fichier", fichier);
      const { data } = await apiClient.post(`${base}/images`, fd);
      onChange(data.url);
      onEnvoyee();
    } catch (e) {
      toast.error(erreur(e, "Image refusée"));
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => setOuvert(!ouvert)}>
          <GalleryHorizontalEnd className="mr-1 h-4 w-4" /> Galerie ({images.length})
        </Button>
        <label className="inline-flex cursor-pointer items-center rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          {envoi ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <ImagePlus className="mr-1 h-4 w-4" />}
          Envoyer une image
          <input type="file" accept="image/jpeg,image/png" className="hidden" onChange={(e) => envoyer(e.target.files?.[0])} />
        </label>
      </div>
      <input className={champ} placeholder="ou adresse https://… d'une image JPEG ou PNG" value={valeur}
             onChange={(e) => onChange(e.target.value)} />
      {/* Lot 75 — générer l'image par l'IA à partir d'une description */}
      {ia && (
        <div className="space-y-2 rounded-md border border-violet-200 bg-violet-50/50 p-2">
          <div className="flex items-center gap-1 text-xs font-semibold text-violet-800"><Sparkles className="h-3.5 w-3.5" /> Générer l'image avec l'IA</div>
          <textarea className={champ} rows={2} maxLength={1000} value={prompt} onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Décrivez l'image (ex. une tablette affichant un formulaire en ligne, sur un bureau lumineux)" />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" variant="outline" disabled={generation || retenue} onClick={generer}>
              {generation ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Sparkles className="mr-1 h-4 w-4" />}
              {apercu ? "Générer une autre" : "Générer"}
            </Button>
            {apercu && (
              <Button type="button" size="sm" disabled={retenue} onClick={retenir}>
                {retenue ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-1 h-4 w-4" />}
                Utiliser cette image
              </Button>
            )}
          </div>
          {apercu && <img src={apercu.apercu} alt="Aperçu de l'image générée" className="h-40 w-40 rounded-md border border-slate-200 object-cover" />}
          <p className="text-[11px] text-slate-500">L'image ne contiendra pas de texte : le titre et le texte de la carte s'affichent dessous dans WhatsApp.</p>
        </div>
      )}
      {/* Toast « Patientez… » avec jauge circulaire pendant la génération (souvent 20 à 60 s) */}
      {generation && (
        <div role="status" aria-live="polite" className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900/80 px-4 py-3 text-sm text-white shadow-lg backdrop-blur">
          <div className="flex items-center gap-2">
            <span aria-hidden="true" className="h-5 w-5 animate-spin rounded-full border-[2.5px] border-transparent border-r-sky-400 border-t-sky-400" />
            <strong>Patientez…</strong><span className="ml-3 tabular-nums opacity-70">{secondes} s</span>
          </div>
          <div className="mt-1 text-xs opacity-80">L'IA dessine l'image, cela prend souvent 20 à 60 secondes.</div>
        </div>
      )}
      {ouvert && (
        <div className="grid max-h-60 grid-cols-4 gap-2 overflow-y-auto rounded-md border border-slate-200 p-2 sm:grid-cols-6">
          {images.length === 0 && <p className="col-span-full text-xs text-slate-500">Aucune image JPEG/PNG disponible : envoyez-en une.</p>}
          {images.map((im) => (
            <button key={im.url} type="button" title={`${im.origine} — ${im.titre}`}
                    onClick={() => { onChange(im.url); setOuvert(false); }}
                    className={`overflow-hidden rounded border-2 ${valeur === im.url ? "border-emerald-500" : "border-transparent"}`}>
              <img src={im.url} alt="" className="h-16 w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Réglages des modèles Meta (administration seulement)
function Reglages({ etat, onEnregistre }) {
  const [modele, setModele] = useState(etat.modele || "");
  const [langue, setLangue] = useState(etat.langue || "fr");
  const [tenantId, setTenantId] = useState("");
  // Lot 76 — bouton « Créer les modèles chez Meta » : les 9 modèles sont déposés par l'API de Meta
  const [creation, setCreation] = useState(false);
  const [resultats, setResultats] = useState(null);
  const creerChezMeta = async () => {
    if (!modele) { toast.error("Saisissez d'abord le nom (préfixe) des modèles, ex. sawali_carrousel."); return; }
    if (!window.confirm(`Déposer chez Meta les 9 modèles ${modele}_2 à ${modele}_10 (catégorie Marketing) ?`)) return;
    setCreation(true);
    setResultats(null);
    try {
      const { data } = await apiClient.post("/admin/whatsapp/carrousel/modeles-meta",
        { modele, langue, tenant_id: tenantId || null }, { timeout: 180000 });
      setResultats(data.resultats);
      const ok = data.resultats.filter((r) => r.statut !== "erreur").length;
      if (ok) { toast.success(`${ok} modèle(s) soumis à Meta. L'approbation prend de quelques minutes à 24 h.`); onEnregistre(); }
      else toast.error("Aucun modèle n'a été accepté : voir le détail ci-dessous.");
    } catch (e) {
      toast.error(erreur(e, "Création des modèles impossible"));
    } finally {
      setCreation(false);
    }
  };
  const enregistrer = async () => {
    try {
      await apiClient.put("/admin/whatsapp/carrousel/reglages", { modele, langue, tenant_id: tenantId || null });
      toast.success("Réglages enregistrés");
      onEnregistre();
    } catch (e) {
      toast.error(erreur(e, "Réglages refusés"));
    }
  };
  return (
    <div className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="flex items-center gap-2 font-semibold text-slate-800"><Settings className="h-4 w-4" /> Modèles Meta</h3>
      <p className="text-xs text-slate-600">
        Un modèle « Carrousel » (catégorie Marketing) par nombre de cartes, à créer dans le WhatsApp Manager ou
        d'un clic avec le bouton « Créer les modèles chez Meta » ci-dessous :
        <b> {modele || "<nom>"}_2</b> à <b>{modele || "<nom>"}_10</b>. Message : <code>{"{{1}}"}</code> (expéditeur) et
        <code> {"{{2}}"}</code> (texte). Chaque carte : en-tête <b>image</b>, corps <code>{"{{1}}"}</code> (titre) et
        <code> {"{{2}}"}</code> (texte), un bouton URL dynamique : <code className="break-all">{etat.url_bouton_modele}</code>.
      </p>
      <div className="grid gap-2 sm:grid-cols-3">
        <input className={champ} placeholder="nom (ex. sawali_carrousel)" value={modele} onChange={(e) => setModele(e.target.value.toLowerCase())} />
        <input className={champ} placeholder="langue (fr)" value={langue} onChange={(e) => setLangue(e.target.value)} />
        <input className={champ} placeholder="(facultatif) id d'un client qui a son propre numéro" value={tenantId}
               onChange={(e) => setTenantId(e.target.value.trim())} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={enregistrer} disabled={!modele || creation}>Enregistrer le nom et la langue des modèles</Button>
        {/* Lot 76 — l'interface Meta ne propose pas toujours « Carrousel » : SAWALI dépose les modèles par l'API */}
        <Button size="sm" variant="outline" onClick={creerChezMeta} disabled={!modele || creation}>
          {creation ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />}
          Créer les modèles chez Meta
        </Button>
      </div>
      <p className="text-[11px] text-slate-500">
        « Créer les modèles chez Meta » dépose les 9 modèles déjà conformes à SAWALI (image d'exemple, textes, bouton).
        L'App ID Meta est retrouvé automatiquement à partir du jeton WhatsApp (comme pour la page Templates WhatsApp).
        Suivez ensuite leur approbation dans « Templates WhatsApp » ou le WhatsApp Manager.
      </p>
      {creation && (
        <div role="status" aria-live="polite" className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-slate-900/80 px-4 py-3 text-sm text-white shadow-lg backdrop-blur">
          <div className="flex items-center gap-2">
            <span aria-hidden="true" className="h-5 w-5 animate-spin rounded-full border-[2.5px] border-transparent border-r-sky-400 border-t-sky-400" />
            <strong>Patientez…</strong>
          </div>
          <div className="mt-1 text-xs opacity-80">Dépôt des 9 modèles chez Meta.</div>
        </div>
      )}
      {resultats && (
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Modèle</th><th>Résultat</th><th>Détail</th></tr></thead>
          <tbody>
            {resultats.map((r) => (
              <tr key={r.nom} className="border-t border-slate-100">
                <td className="py-1 font-mono">{r.nom}</td>
                <td>
                  {r.statut === "erreur"
                    ? <span className="inline-flex items-center gap-1 text-red-600"><XCircle className="h-3.5 w-3.5" /> erreur</span>
                    : <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> {r.statut}</span>}
                </td>
                <td className="text-slate-600">{r.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// Lot 77 — pastille du statut chez Meta du modèle utilisé (selon le nombre de cartes)
const STATUTS_META = {
  APPROVED: ["bg-emerald-500", "Approuvé par Meta : prêt à envoyer"],
  PENDING: ["bg-amber-400", "En attente d'approbation chez Meta"],
  IN_APPEAL: ["bg-amber-400", "En appel chez Meta"],
  REJECTED: ["bg-red-500", "Refusé par Meta"],
  PAUSED: ["bg-red-500", "Mis en pause par Meta"],
  DISABLED: ["bg-red-500", "Désactivé par Meta"],
  ABSENT: ["bg-slate-300", "Modèle pas encore créé chez Meta (bouton « Créer les modèles chez Meta »)"],
  HORS_LIMITES: ["bg-slate-300", "Un carrousel compte de 2 à 10 cartes"],
};
function PastilleMeta({ statut, modele }) {
  const [couleur, libelle] = STATUTS_META[statut] || ["bg-slate-300", `Statut Meta : ${statut}`];
  return (
    <span className="inline-flex items-center gap-1.5" title={`${modele ? `${modele} — ` : ""}${libelle}`}>
      <span aria-hidden="true" className={`inline-block h-3 w-3 rounded-full ${couleur}`} />
      <span className="sr-only">{libelle}</span>
    </span>
  );
}

// Lot 77 — carrousels enregistrés sous un nom : liste, ouvrir, dupliquer, supprimer
function MesCarrousels({ base, courant, onOuvrir, onEnregistre, rafraichir, onComposer }) {
  const [liste, setListe] = useState({ carrousels: [], erreur_meta: null });
  const [meta, setMeta] = useState({ prefixe: "", statuts: {} });   // lot 78.1 : modèles déposés chez Meta
  const charger = useCallback(async (relireMeta = false) => {
    try {
      const sm = await apiClient.get(`${base}/statuts-meta`, { params: { rafraichir: relireMeta } });
      setMeta(sm.data);
      const { data } = await apiClient.get(`${base}/brouillons`);
      setListe(data);
    } catch (e) {
      toast.error(erreur(e, "Liste des carrousels indisponible"));
    }
  }, [base]);
  // Rechargée au chargement et après chaque enregistrement (compteur « rafraichir »)
  useEffect(() => { charger(); }, [charger, rafraichir]);

  const dupliquer = async (b) => {
    try {
      const { data } = await apiClient.post(`${base}/brouillons/${b.id}/dupliquer`);
      toast.success(`« ${data.nom} » créé : modifiez-le puis enregistrez`);
      onOuvrir(data);
      charger();
    } catch (e) {
      toast.error(erreur(e, "Duplication impossible"));
    }
  };
  const supprimer = async (b) => {
    if (!window.confirm(`Supprimer le carrousel « ${b.nom} » ?`)) return;
    try {
      await apiClient.delete(`${base}/brouillons/${b.id}`);
      if (courant?.id === b.id) onEnregistre(null);
      charger();
    } catch (e) {
      toast.error(erreur(e, "Suppression impossible"));
    }
  };

  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800"><FolderOpen className="h-4 w-4" /> Mes carrousels</h2>
        <Button type="button" size="sm" variant="outline" onClick={() => charger(true)} title="Relire les statuts chez Meta">
          <RefreshCw className="mr-1 h-4 w-4" /> Statuts Meta
        </Button>
      </div>
      {liste.erreur_meta && <p className="text-xs text-amber-700">Statuts Meta indisponibles : {liste.erreur_meta}</p>}
      {/* Lot 78.1 — modèles chez Meta : une structure vide par nombre de cartes (pas vos images ni vos textes) */}
      {meta.prefixe && (
        <div className="rounded-md bg-slate-50 p-2 text-xs text-slate-600">
          <div className="mb-1">
            Modèles chez Meta <span className="font-mono">{meta.prefixe}_2 … _10</span> : ce sont des <b>cadres vides</b> (un par
            nombre de cartes). Meta ne garde ni vos images ni vos textes : ils sont dans « Mes carrousels » (si enregistrés)
            ou dans « 3. Envois précédents ». Cliquez sur un modèle pour composer un carrousel de ce nombre de cartes.
          </div>
          <div className="flex flex-wrap gap-1.5">
            {[2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
              <button key={n} type="button" onClick={() => onComposer(n)}
                      className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 ring-1 ring-slate-300 hover:ring-emerald-500"
                      title={`Composer un nouveau carrousel de ${n} cartes`}>
                <PastilleMeta statut={meta.statuts?.[n] || meta.statuts?.[String(n)] || "ABSENT"} modele={`${meta.prefixe}_${n}`} /> {n} cartes
              </button>
            ))}
          </div>
        </div>
      )}
      {liste.carrousels.length === 0 ? (
        <p className="text-xs text-slate-500">Aucun carrousel enregistré. Composez-en un ci-dessous, nommez-le et cliquez « Enregistrer ce carrousel » (en bas, avant l'aperçu).</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500">
              <th className="py-1 pr-2">Meta</th><th>Nom</th><th>Cartes</th><th>Modèle</th><th>Modifié le</th><th className="text-right">Actions</th>
            </tr></thead>
            <tbody>
              {liste.carrousels.map((b) => (
                <tr key={b.id} aria-selected={courant?.id === b.id ? "true" : "false"}
                    className={`border-t border-slate-100 ${courant?.id === b.id ? "ligne-selectionnee" : ""}`}>
                  <td className="py-1.5 pr-2"><PastilleMeta statut={b.statut_meta} modele={b.modele} /></td>
                  <td className="font-medium">{b.nom}</td>
                  <td className="tabular-nums">{b.nb_cartes}</td>
                  <td className="font-mono text-xs">{b.modele || "—"}</td>
                  <td className="text-xs">{dateFr(b.modifie_le)}</td>
                  <td className="whitespace-nowrap text-right">
                    <Button type="button" size="sm" variant="outline" className="mr-1" onClick={() => onOuvrir(b)} title="Afficher ce carrousel dans l'éditeur">
                      <FolderOpen className="h-4 w-4" />
                    </Button>
                    <Button type="button" size="sm" variant="outline" className="mr-1" onClick={() => dupliquer(b)} title="Dupliquer pour en créer un nouveau">
                      <Copy className="h-4 w-4" />
                    </Button>
                    <Button type="button" size="sm" variant="outline" onClick={() => supprimer(b)} title="Supprimer">
                      <Trash2 className="h-4 w-4 text-red-600" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-[11px] text-slate-500">
        Pastille : <span className="text-emerald-700">verte</span> = modèle approuvé par Meta pour ce nombre de cartes,
        <span className="text-amber-700"> orange</span> = en attente, <span className="text-red-600">rouge</span> = refusé, grise = modèle non créé.
      </p>
    </section>
  );
}

export default function CarrouselWhatsApp({ admin = false }) {
  const base = admin ? "/admin/whatsapp/carrousel" : "/me/whatsapp/carrousel";
  const [etat, setEtat] = useState(null);
  const [refus, setRefus] = useState("");
  const [produits, setProduits] = useState([]);
  const [images, setImages] = useState([]);
  const [annuaire, setAnnuaire] = useState({ contacts: [], groupes: [] });
  const [campagnes, setCampagnes] = useState([]);
  const [detail, setDetail] = useState(null);
  const [message, setMessage] = useState("");
  const [cartes, setCartes] = useState([carteVide(), carteVide()]);
  const [courant, setCourant] = useState(null);           // lot 77 : carrousel nommé ouvert dans l'éditeur
  // Lot 78 — nom et enregistrement (barre en bas, avant l'aperçu), brouillon automatique, lien par défaut
  const [nom, setNom] = useState("");
  const [enregistrement, setEnregistrement] = useState(false);
  const [rafraichirListe, setRafraichirListe] = useState(0);
  const [autoLe, setAutoLe] = useState(null);             // heure du dernier enregistrement automatique
  const autoPret = useRef(false);                         // pas d'enregistrement auto avant la restauration
  const [lienDefaut, setLienDefaut] = useState("");
  const [autoErreur, setAutoErreur] = useState("");       // lot 78.1 : échec de l'enregistrement automatique affiché
  // Lot 78.1 — nouveau carrousel vide de n cartes (depuis un modèle Meta) ; demande confirmation si l'éditeur est rempli
  const composer = (n) => {
    const rempli = message.trim() || cartes.some((c) => c.titre || c.image_url || c.lien || c.produit_id);
    if (rempli && !window.confirm("Remplacer le carrousel affiché par un nouveau carrousel vide ? (enregistrez-le d'abord si besoin)")) return;
    setCourant(null); setNom(""); setMessage("");
    setCartes(Array.from({ length: n }, carteVide));
  };
  const ouvrirCarrousel = (b) => {
    // Un carrousel enregistré garde son id ; un envoi rechargé devient un nouveau carrousel (sans id)
    setCourant(b?.id ? { id: b.id, nom: b.nom } : null);
    setNom(b?.nom || "");
    if (!b) return;
    setMessage(b.message || "");
    const cs = (b.cartes || []).map((c) => ({ ...carteVide(), ...Object.fromEntries(Object.entries(c).map(([k, v]) => [k, v ?? ""])) }));
    setCartes(cs.length >= 2 ? cs : [...cs, ...Array.from({ length: 2 - cs.length }, carteVide)]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const [choisis, setChoisis] = useState(new Set());
  const [groupes, setGroupes] = useState(new Set());
  const [filtre, setFiltre] = useState("");
  const [envoi, setEnvoi] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [e, p, i, d, c] = await Promise.all([
        apiClient.get(base), apiClient.get(`${base}/produits`), apiClient.get(`${base}/images`),
        apiClient.get(`${base}/destinataires`), apiClient.get(`${base}/campagnes`),
      ]);
      setEtat(e.data); setProduits(p.data.produits); setImages(i.data.images);
      setAnnuaire(d.data); setCampagnes(c.data.campagnes);
    } catch (e) {
      setRefus(erreur(e, "Carrousel indisponible"));
    }
  }, [base]);
  useEffect(() => { charger(); }, [charger]);

  // Lot 78 — au chargement : lien par défaut, puis restauration du brouillon automatique
  useEffect(() => {
    let fini = false;
    (async () => {
      try {
        const [pref, auto] = await Promise.all([apiClient.get(`${base}/preferences`), apiClient.get(`${base}/brouillon-auto`)]);
        if (fini) return;
        setLienDefaut(pref.data.lien_defaut || "");
        const b = auto.data.brouillon;
        const rempli = b && ((b.message || "").trim() || (b.cartes || []).some((c) => c.titre || c.image_url || c.lien || c.produit_id));
        if (rempli) {
          ouvrirCarrousel({ ...b, id: b.carrousel_id || null, nom: "" });
          if (b.carrousel_id) {
            const { data } = await apiClient.get(`${base}/brouillons`);
            const nomme = (data.carrousels || []).find((x) => x.id === b.carrousel_id);
            if (nomme) { setCourant({ id: nomme.id, nom: nomme.nom }); setNom(nomme.nom); } else setCourant(null);
          } else {
            setCourant(null);
          }
          setAutoLe(b.modifie_le);
          toast.info(`Travail en cours restauré (enregistré automatiquement le ${dateFr(b.modifie_le)})`);
        }
      } catch (e) {
        /* sans brouillon automatique, l'éditeur reste vide */
      } finally {
        autoPret.current = true;
      }
    })();
    return () => { fini = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base]);

  // Lot 78 — enregistrement automatique 3 s après la dernière modification
  useEffect(() => {
    if (!autoPret.current) return undefined;
    const t = setTimeout(async () => {
      try {
        const { data } = await apiClient.put(`${base}/brouillon-auto`, { message, cartes: cartesPourServeur(cartes), carrousel_id: courant?.id || null });
        setAutoLe(data.enregistre_le);
        setAutoErreur("");
      } catch (e) {
        // Lot 78.1 — l'échec n'est plus silencieux : il s'affiche dans la barre d'enregistrement
        setAutoErreur(erreur(e, "serveur injoignable"));
      }
    }, 3000);
    return () => clearTimeout(t);
  }, [base, message, cartes, courant]);

  const enregistrerCarrousel = async (commeNouveau) => {
    if (!nom.trim()) { toast.error("Donnez un nom au carrousel."); return; }
    setEnregistrement(true);
    try {
      const corps = { nom: nom.trim(), message, cartes: cartesPourServeur(cartes) };
      const { data } = courant?.id && !commeNouveau
        ? await apiClient.put(`${base}/brouillons/${courant.id}`, corps)
        : await apiClient.post(`${base}/brouillons`, corps);
      toast.success(`Carrousel « ${data.nom} » enregistré`);
      setCourant({ id: data.id, nom: data.nom });
      setRafraichirListe((n) => n + 1);
    } catch (e) {
      toast.error(erreur(e, "Enregistrement impossible"));
    } finally {
      setEnregistrement(false);
    }
  };

  const enregistrerLienDefaut = async () => {
    try {
      const { data } = await apiClient.put(`${base}/preferences`, { lien_defaut: lienDefaut.trim() });
      setLienDefaut(data.lien_defaut);
      toast.success(data.lien_defaut ? "Lien par défaut enregistré" : "Lien par défaut retiré");
    } catch (e) {
      toast.error(erreur(e, "Lien par défaut refusé"));
    }
  };

  const rechargerImages = async () => {
    const { data } = await apiClient.get(`${base}/images`);
    setImages(data.images);
  };
  const produitsParId = useMemo(() => Object.fromEntries(produits.map((p) => [p.id, p])), [produits]);

  // --- Cartes ---
  const majCarte = (i, champs) => setCartes((cs) => cs.map((c, k) => (k === i ? { ...c, ...champs } : c)));
  const deplacer = (i, sens) => setCartes((cs) => {
    const j = i + sens;
    if (j < 0 || j >= cs.length) return cs;
    const copie = [...cs];
    [copie[i], copie[j]] = [copie[j], copie[i]];
    return copie;
  });

  // --- Destinataires ---
  const contactsFiltres = annuaire.contacts.filter((c) =>
    `${c.nom} ${c.societe} ${c.telephone}`.toLowerCase().includes(filtre.toLowerCase()));
  const basculer = (set, setter, id) => {
    const s = new Set(set);
    s.has(id) ? s.delete(id) : s.add(id);
    setter(s);
  };
  const consentement = async (ids, accepte) => {
    try {
      await apiClient.put(`${base}/consentements`, { ids, accepte });
      toast.success(accepte ? "Consentement noté" : "Consentement retiré");
      const { data } = await apiClient.get(`${base}/destinataires`);
      setAnnuaire(data);
    } catch (e) {
      toast.error(erreur(e, "Modification refusée"));
    }
  };
  // Destinataires réels : contacts cochés + membres des groupes, qui ont accepté
  const retenus = useMemo(() => {
    const ids = new Set(choisis);
    annuaire.groupes.filter((g) => groupes.has(g.id)).forEach((g) => g.contact_ids.forEach((x) => ids.add(x)));
    return annuaire.contacts.filter((c) => ids.has(c.id) && c.accepte && c.telephone);
  }, [choisis, groupes, annuaire]);

  const envoyer = async () => {
    if (!window.confirm(`Envoyer ce carrousel de ${cartes.length} cartes à ${retenus.length} destinataire(s) ?`)) return;
    setEnvoi(true);
    try {
      const corps = {
        message,
        cartes: cartesPourServeur(cartes),
        ids: [...choisis], groupes: [...groupes],
      };
      const { data } = await apiClient.post(`${base}/envoyer`, corps);
      toast.success(`Envoi lancé vers ${data.destinataires} destinataire(s) (modèle ${data.modele})`);
      setTimeout(charger, 3000);
    } catch (e) {
      toast.error(erreur(e, "Envoi refusé"));
    } finally {
      setEnvoi(false);
    }
  };

  const ouvrirDetail = async (id) => {
    const { data } = await apiClient.get(`${base}/campagnes/${id}`);
    setDetail(data);
  };

  if (refus) return <div className="m-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">{refus}</div>;
  if (!etat) return <div className="flex justify-center p-10"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>;

  const cartesPretes = cartes.every((c) => (c.source === "produit" ? c.produit_id : c.image_url && c.titre && c.lien));

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-800">
          <GalleryHorizontalEnd className="h-6 w-6 text-emerald-600" /> Carrousel WhatsApp
        </h1>
        <p className="text-sm text-slate-600">
          {admin ? "Envoyez à vos clients qui ont accepté" : "Envoyez à vos contacts qui ont accepté"} de 2 à 10 cartes
          (photo, titre, texte, bouton) dans un seul message. {etat.envoyes_ce_mois} message(s) envoyé(s) ce mois-ci.
        </p>
      </div>

      {!etat.pret && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          {!etat.whatsapp_configure ? "WhatsApp n'est pas configuré pour ce numéro. " : ""}
          {!etat.modele ? "Les modèles de carrousel ne sont pas encore renseignés par l'administration SAWALI." : ""}
        </div>
      )}
      {admin && <Reglages etat={etat} onEnregistre={charger} />}

      {/* Lot 77 — carrousels nommés : liste, statut Meta, ouvrir, dupliquer */}
      <MesCarrousels base={base} courant={courant} onOuvrir={ouvrirCarrousel} rafraichir={rafraichirListe} onComposer={composer}
                     onEnregistre={(b) => { setCourant(b ? { id: b.id, nom: b.nom } : null); if (!b) setNom(""); }} />

      {/* 1. Message et cartes */}
      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="font-semibold text-slate-800">1. Message et cartes</h2>
        <textarea className={champ} rows={2} maxLength={500} placeholder="Texte au-dessus des cartes (ex. Nos nouveautés de la semaine)"
                  value={message} onChange={(e) => setMessage(e.target.value)} />
        {/* Lot 78 — lien utilisé par les cartes libres laissées sans lien */}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="carrousel-lien-defaut" className="text-xs font-medium text-slate-600">Lien par défaut des cartes sans lien :</label>
          <input id="carrousel-lien-defaut" className={`${champ} max-w-md`} placeholder="https://sawalismartsystems.com"
                 value={lienDefaut} onChange={(e) => setLienDefaut(e.target.value)} />
          <Button type="button" size="sm" variant="outline" onClick={enregistrerLienDefaut}>Enregistrer le lien par défaut</Button>
        </div>
        <div className="space-y-3">
          {cartes.map((c, i) => (
            <div key={i} className="rounded-md border border-slate-200 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-700">Carte {i + 1}</span>
                <select className="rounded border border-slate-300 px-2 py-1 text-sm" value={c.source}
                        onChange={(e) => majCarte(i, { ...carteVide(), source: e.target.value })}>
                  <option value="libre">Carte libre</option>
                  <option value="produit">Produit de la caisse</option>
                </select>
                <div className="ml-auto flex gap-1">
                  <Button type="button" size="icon" variant="ghost" onClick={() => deplacer(i, -1)} title="Avancer"><ArrowLeft className="h-4 w-4" /></Button>
                  <Button type="button" size="icon" variant="ghost" onClick={() => deplacer(i, 1)} title="Reculer"><ArrowRight className="h-4 w-4" /></Button>
                  <Button type="button" size="icon" variant="ghost" disabled={cartes.length <= etat.cartes_min}
                          onClick={() => setCartes(cartes.filter((_, k) => k !== i))} title="Retirer"><Trash2 className="h-4 w-4 text-red-600" /></Button>
                </div>
              </div>
              {c.source === "produit" ? (
                <div className="grid gap-2 sm:grid-cols-3">
                  <select className={champ} value={c.produit_id || ""} onChange={(e) => majCarte(i, { produit_id: e.target.value })}>
                    <option value="">— Choisir un produit avec photo —</option>
                    {produits.map((p) => (
                      <option key={p.id} value={p.id} disabled={!p.image_ok}>
                        {p.nom} — {p.prix}{p.image_ok ? "" : " (photo non JPEG/PNG)"}{p.public ? "" : " · hors catalogue public"}
                      </option>
                    ))}
                  </select>
                  <input className={champ} maxLength={60} placeholder="Titre (par défaut : nom du produit)" value={c.titre || ""}
                         onChange={(e) => majCarte(i, { titre: e.target.value })} />
                  <input className={champ} maxLength={80} placeholder="Texte (par défaut : prix)" value={c.texte || ""}
                         onChange={(e) => majCarte(i, { texte: e.target.value })} />
                </div>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2">
                  <ChoixImage base={base} images={images} onEnvoyee={rechargerImages} valeur={c.image_url}
                              onChange={(url) => majCarte(i, { image_url: url })} titre={c.titre} ia={!!etat.ia_images} />
                  <div className="space-y-2">
                    <input className={champ} maxLength={60} placeholder="Titre" value={c.titre} onChange={(e) => majCarte(i, { titre: e.target.value })} />
                    <input className={champ} maxLength={80} placeholder="Texte court" value={c.texte} onChange={(e) => majCarte(i, { texte: e.target.value })} />
                    <input className={champ} placeholder="Lien du bouton https://…" value={c.lien} onChange={(e) => majCarte(i, { lien: e.target.value })} />
                    {!c.lien && (
                      <p className={`text-[11px] ${lienDefaut ? "text-slate-500" : "text-amber-700"}`}>
                        {lienDefaut ? `Sans lien : le bouton ouvrira ${lienDefaut}` : "Lien obligatoire (ou réglez un lien par défaut ci-dessus)."}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
        <Button type="button" variant="outline" size="sm" disabled={cartes.length >= etat.cartes_max}
                onClick={() => setCartes([...cartes, carteVide()])}>
          <Plus className="mr-1 h-4 w-4" /> Ajouter une carte ({cartes.length}/{etat.cartes_max})
        </Button>
        {/* Lot 78 — nom et enregistrement, en bas de l'éditeur, juste avant l'aperçu */}
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-slate-50 p-3">
          <input className={`${champ} max-w-sm`} maxLength={80} placeholder="Nom du carrousel (ex. Nouveautés octobre)"
                 value={nom} onChange={(e) => setNom(e.target.value)} />
          <Button type="button" size="sm" disabled={enregistrement} onClick={() => enregistrerCarrousel(false)}>
            {enregistrement ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
            {courant?.id ? "Enregistrer les modifications du carrousel" : "Enregistrer ce carrousel"}
          </Button>
          {courant?.id && (
            <Button type="button" size="sm" variant="outline" disabled={enregistrement} onClick={() => enregistrerCarrousel(true)}>
              <Copy className="mr-1 h-4 w-4" /> Enregistrer comme nouveau carrousel
            </Button>
          )}
          <span className="ml-auto text-[11px] text-slate-500">
            {autoLe ? `Enregistré automatiquement le ${dateFr(autoLe)}` : "Enregistrement automatique actif"}
          </span>
          {autoErreur && <span className="w-full text-[11px] text-red-700">Enregistrement automatique impossible : {autoErreur}</span>}
        </div>
        {/* Aperçu */}
        <div className="rounded-lg bg-[#e5ddd5] p-3">
          <div className="mb-2 max-w-md rounded-lg bg-white p-2 text-sm shadow-sm">{message || "Votre message…"}</div>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {cartes.map((c, i) => <ApercuCarte key={i} carte={c} produit={produitsParId[c.produit_id]} />)}
          </div>
        </div>
      </section>

      {/* 2. Destinataires */}
      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800"><Users className="h-4 w-4" /> 2. Destinataires</h2>
        <p className="text-xs text-slate-600">
          Seules les personnes qui ont <b>accepté</b> de recevoir vos messages WhatsApp reçoivent le carrousel (règle de
          WhatsApp). Notez l'accord quand la personne vous l'a donné ; retirez-le si elle ne veut plus rien recevoir.
        </p>
        {annuaire.groupes.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {annuaire.groupes.map((g) => (
              <button key={g.id} type="button" onClick={() => basculer(groupes, setGroupes, g.id)}
                      className={`rounded-full px-3 py-1 text-xs ring-1 ${groupes.has(g.id) ? "bg-emerald-600 text-white ring-emerald-600" : "bg-white text-slate-700 ring-slate-300"}`}>
                {g.nom} ({g.contact_ids.length})
              </button>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${champ} max-w-xs`} placeholder="Rechercher" value={filtre} onChange={(e) => setFiltre(e.target.value)} />
          <Button type="button" size="sm" variant="outline"
                  onClick={() => setChoisis(new Set(contactsFiltres.filter((c) => c.accepte).map((c) => c.id)))}>
            Cocher ceux qui ont accepté
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setChoisis(new Set())}>Tout décocher</Button>
        </div>
        <div className="max-h-80 overflow-y-auto rounded-md border border-slate-200">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="p-2" /><th className="p-2">Nom</th><th className="p-2">WhatsApp</th><th className="p-2">Accord</th></tr>
            </thead>
            <tbody>
              {contactsFiltres.map((c) => (
                <tr key={c.id} className="border-t border-slate-100">
                  <td className="p-2">
                    <input type="checkbox" disabled={!c.accepte || !c.telephone} checked={choisis.has(c.id)}
                           onChange={() => basculer(choisis, setChoisis, c.id)} />
                  </td>
                  <td className="p-2">{c.nom}<span className="text-xs text-slate-500"> {c.societe}</span></td>
                  <td className="p-2 text-slate-600">{c.telephone || <span className="text-red-600">aucun numéro</span>}</td>
                  <td className="p-2">
                    {c.accepte ? (
                      <button type="button" className="text-xs text-emerald-700" title="Retirer l'accord" onClick={() => consentement([c.id], false)}>
                        <CheckCircle2 className="mr-1 inline h-4 w-4" />accepté {c.accepte_le ? `le ${dateFr(c.accepte_le)}` : ""}
                      </button>
                    ) : (
                      <button type="button" className="text-xs text-slate-600 underline" onClick={() => consentement([c.id], true)}>
                        Noter son accord
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-700"><b>{retenus.length}</b> destinataire(s) (max. {etat.destinataires_max})</span>
          <Button onClick={envoyer} disabled={!etat.pret || envoi || !message.trim() || !cartesPretes || retenus.length === 0
                                               || retenus.length > etat.destinataires_max}>
            {envoi ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />} Envoyer le carrousel
          </Button>
        </div>
      </section>

      {/* 3. Campagnes */}
      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800"><Package className="h-4 w-4" /> 3. Envois précédents</h2>
        {campagnes.length === 0 && <p className="text-sm text-slate-500">Aucun envoi pour le moment.</p>}
        {campagnes.map((c) => (
          <div key={c.id} className="rounded-md border border-slate-200 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-medium">{dateFr(c.cree_le)}</span>
              <span className="text-slate-600">{c.cartes.length} cartes · {c.modele}</span>
              <span className="text-emerald-700">{c.compte.envoyes} envoyé(s)</span>
              {c.compte.echecs > 0 && <span className="text-red-700">{c.compte.echecs} échec(s)</span>}
              <span className="text-slate-500">{c.statut === "EN_COURS" ? "en cours…" : ""}</span>
              {/* Lot 78 — recharge les cartes et le message de cet envoi dans l'éditeur (nouveau carrousel) */}
              <Button size="sm" variant="outline" className="ml-auto" title="Reprendre ce carrousel dans l'éditeur pour le modifier ou le renvoyer"
                onClick={() => { ouvrirCarrousel({ nom: "", message: c.message, cartes: c.cartes.map(({ source, produit_id, image_url, titre, texte, lien }) => ({ source, produit_id, image_url, titre, texte, lien })) }); toast.success("Carrousel rechargé dans l'éditeur — pensez à l'enregistrer sous un nom"); }}>
                Recharger dans l'éditeur
              </Button>
              <Button size="sm" variant="ghost" onClick={() => (detail?.id === c.id ? setDetail(null) : ouvrirDetail(c.id))}>
                {detail?.id === c.id ? "Masquer" : "Détail"}
              </Button>
            </div>
            <div className="mt-1 truncate text-slate-600">{c.message}</div>
            <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
              {c.cartes.map((k, i) => <span key={i}>{k.titre} : {k.clics} clic(s)</span>)}
            </div>
            {detail?.id === c.id && (
              <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2">
                {detail.destinataires.map((d) => (
                  <li key={d.id} className="flex items-center gap-2">
                    {d.statut === "ENVOYE" ? <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      : d.statut === "ECHEC" ? <XCircle className="h-4 w-4 text-red-600" />
                        : <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
                    <span>{d.nom}</span><span className="text-slate-500">{d.telephone}</span>
                    {d.erreur && <span className="text-xs text-red-700">{d.erreur}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </section>
    </div>
  );
}
