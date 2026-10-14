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
  Lot 111 — chaque carte a une « description détaillée » et un mode de bouton : « Page de présentation » (page
  publique de tout le carrousel, positionnée sur la carte) ou « Lien personnalisé ». L'administration peut
  rattacher un carrousel à une campagne de la RÉGIE PUBLICITAIRE (carrousel sponsorisé, clics facturés).
  Chaque envoi montre par carte : clics, vues de la présentation et « Je suis intéressé ».
  Lot 114 — « Envoyer maintenant » ou « Programmer le JJ/MM/AAAA à HH:MM » (heure de Ouagadougou), dans les plages
  horaires d'envoi fixées par l'Admin (Paramètres) : hors plage, l'envoi attend et reprend tout seul. Chaque envoi
  affiche son statut (Programmée, En attente, En cours, Terminée, Annulée) et peut être annulé tant qu'il n'est pas fini.
*/
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRight, CheckCircle2, ChevronDown, ChevronRight, Copy, ExternalLink, FolderOpen, GalleryHorizontalEnd, ImagePlus, Loader2, Megaphone,
  Package, Plus, MessageSquareReply, RefreshCw, Save, Send, Settings, Share2, Sparkles, Trash2, Users, XCircle,
} from "lucide-react";
import QRCode from "qrcode";                                  // lot 79 : QR code du lien d'accord
import { useAuth } from "@/contexts/AuthContext";             // lot 79 : rôle (partage réservé admin / superviseur)
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { pageVisible } from "@/lib/visibilite";   // lot 79.6 : relectures en pause onglet masqué
import EnvoiProgrammation from "@/components/EnvoiProgrammation";   // lot 114 : maintenant / programmer + plages horaires

const erreur = (e, defaut) => {
  const d = e?.response?.data?.detail;
  if (Array.isArray(d)) return d.map((x) => x.msg).join(" ; ");
  if (d && typeof d === "object") return d.message || defaut;     // lot 117.1 : détail structuré
  return d || defaut;
};
const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
// Lot 111 — bouton "" = automatique (lien s'il y en a un, sinon page de présentation) ; description détaillée vide
const carteVide = () => ({ source: "libre", image_url: "", titre: "", texte: "", lien: "", bouton: "", description_detaillee: "" });
const DESCRIPTION_MAX = 4000;   // lot 111 : longueur maximale de la description détaillée
// Cartes telles que le serveur les attend (une carte produit ne garde que son produit et ses textes)
// Lot 111 — + description détaillée et mode du bouton ; une carte produit en mode « lien » garde son lien
const cartesPourServeur = (cartes) => cartes.map((c) => {
  const commun = { description_detaillee: c.description_detaillee || "", bouton: c.bouton || null };
  return c.source === "produit"
    ? { source: "produit", produit_id: c.produit_id || null, titre: c.titre || null, texte: c.texte || null,
        lien: c.bouton === "lien" ? (c.lien || "") : "", ...commun }
    : { source: "libre", image_url: c.image_url || "", titre: c.titre || "", texte: c.texte || "", lien: c.lien || "", ...commun };
});
// Lot 111 — mode effectif du bouton, comme le calcule le serveur à l'envoi
const modeBouton = (c, lienDefaut) => c.bouton
  || ((c.lien || (c.source === "libre" && lienDefaut)) ? "lien" : "presentation");
// Lot 114 — pastille de statut d'une campagne : [classes de couleur, libellé par défaut]
const PASTILLES_STATUT = {
  PROGRAMMEE: ["bg-sky-100 text-sky-800 ring-sky-300", "Programmée"],
  EN_ATTENTE: ["bg-amber-100 text-amber-800 ring-amber-300", "En attente"],
  EN_COURS: ["bg-blue-100 text-blue-800 ring-blue-300", "En cours"],
  TERMINEE: ["bg-emerald-100 text-emerald-800 ring-emerald-300", "Terminée"],
  ANNULEE: ["bg-slate-200 text-slate-700 ring-slate-300", "Annulée"],
};
function PastilleStatut({ statut, libelle }) {
  const [classes, defaut] = PASTILLES_STATUT[statut] || ["bg-slate-100 text-slate-700 ring-slate-300", statut || "?"];
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${classes}`}
          data-testid={`statut-campagne-${statut}`}>
      {libelle || defaut}
    </span>
  );
}
// Lot 114 — statuts d'une campagne qui n'est pas encore finie (annulable)
const STATUTS_ACTIFS = ["PROGRAMMEE", "EN_ATTENTE", "EN_COURS"];
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

// Lot 139 — prépare une image choisie sur le téléphone ou le disque : WhatsApp n'accepte que JPEG et PNG de 5 Mo au plus.
// Les photos de téléphone (HEIC, WebP) ou trop lourdes sont converties en JPEG dans le navigateur (côté le plus long
// ramené à 1600 px), sans rien envoyer d'inutile. Renvoie un File prêt à envoyer, ou lève une erreur lisible.
const MAX_OCTETS_IMAGE = 5 * 1024 * 1024;
async function preparerImage(fichier) {
  const okType = fichier.type === "image/jpeg" || fichier.type === "image/png";
  if (okType && fichier.size <= MAX_OCTETS_IMAGE) return fichier;
  let bitmap;
  try {
    bitmap = await createImageBitmap(fichier);
  } catch {
    throw new Error(`« ${fichier.name} » : format non lisible par le navigateur (HEIC ?) — enregistrez-la en JPEG ou PNG.`);
  }
  const echelle = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * echelle);
  canvas.height = Math.round(bitmap.height * echelle);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";                            // fond blanc : le JPEG n'a pas de transparence
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  for (const qualite of [0.88, 0.75, 0.6]) {
    const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", qualite));
    if (blob && blob.size <= MAX_OCTETS_IMAGE) return new File([blob], fichier.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  }
  throw new Error(`« ${fichier.name} » reste trop lourde (plus de 5 Mo) même réduite.`);
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

  // Lot 139 — envoi d'UNE ou PLUSIEURS images (stockage du téléphone, fichiers ou dossier du disque, glisser-déposer) :
  // chacune est convertie si besoin (JPEG/PNG ≤ 5 Mo), la première remplit la carte, toutes rejoignent la galerie.
  const [survol, setSurvol] = useState(false);
  const envoyer = async (liste) => {
    const fichiers = Array.from(liste || []).filter((f) => (f.type || "").startsWith("image/") || /\.(heic|heif|webp|jpe?g|png)$/i.test(f.name));
    if (fichiers.length === 0) { toast.error("Aucune image dans la sélection."); return; }
    setEnvoi(true);
    let envoyees = 0;
    try {
      for (const brut of fichiers.slice(0, 50)) {
        try {
          const fichier = await preparerImage(brut);
          const fd = new FormData();
          fd.append("fichier", fichier);
          const { data } = await apiClient.post(`${base}/images`, fd);
          if (envoyees === 0) onChange(data.url);          // la première image remplit la carte
          envoyees += 1;
        } catch (e) {
          toast.error(e?.response ? erreur(e, "Image refusée") : (e?.message || "Image refusée"));
        }
      }
      if (envoyees > 0) {
        onEnvoyee();                                       // la galerie se met à jour
        if (envoyees > 1) { setOuvert(true); toast.success(`${envoyees} images ajoutées à la galerie — la première est dans la carte.`); }
      }
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
        <label className="inline-flex cursor-pointer items-center rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
               title="Photos du téléphone ou fichiers du disque (plusieurs possibles)">
          {envoi ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <ImagePlus className="mr-1 h-4 w-4" />}
          Envoyer des images
          <input type="file" accept="image/*" multiple className="hidden"
                 onChange={(e) => { envoyer(e.target.files); e.target.value = ""; }} />
        </label>
        {/* Dossier du disque (ordinateur) : toutes les images du dossier */}
        <label className="hidden cursor-pointer items-center rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 sm:inline-flex"
               title="Toutes les images d'un dossier du disque">
          <GalleryHorizontalEnd className="mr-1 h-4 w-4" /> Dossier…
          <input type="file" className="hidden" multiple webkitdirectory="" directory=""
                 onChange={(e) => { envoyer(e.target.files); e.target.value = ""; }} />
        </label>
      </div>
      {/* Glisser-déposer d'images (ordinateur) */}
      <div onDragOver={(e) => { e.preventDefault(); setSurvol(true); }} onDragLeave={() => setSurvol(false)}
           onDrop={(e) => { e.preventDefault(); setSurvol(false); envoyer(e.dataTransfer.files); }}
           className={`rounded-md border border-dashed px-3 py-2 text-center text-xs ${survol ? "border-emerald-500 bg-emerald-50 text-emerald-800" : "border-slate-300 text-slate-500"}`}>
        Glissez des images ici (JPEG, PNG, WebP, HEIC : converties en JPEG de 5 Mo au plus si besoin)
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
  // Lot 78.2 — statut ACTUEL de chaque modèle chez Meta (le résultat du dépôt n'est qu'une photo à l'instant du dépôt)
  const [actuels, setActuels] = useState({});
  const [motifs, setMotifs] = useState({});   // Lot 115.1 — motif du refus donné par Meta, par nombre de cartes
  const [urlReelle, setUrlReelle] = useState(null);   // Lot 117.1 — adresse du bouton dans la série DÉPOSÉE chez Meta
  const [actualisation, setActualisation] = useState(false);
  const actualiser = useCallback(async (silencieux = false) => {
    setActualisation(true);
    try {
      const { data } = await apiClient.get("/admin/whatsapp/carrousel/statuts-meta", { params: { rafraichir: true } });
      setActuels(data.statuts || {});
      setMotifs(data.motifs || {});
      setUrlReelle(data.url_bouton_reelle || null);
      if (!silencieux) toast.success(data.erreur ? `Statuts Meta : ${data.erreur}` : "Statuts relus chez Meta");
    } catch (e) {
      if (!silencieux) toast.error(erreur(e, "Statuts Meta indisponibles"));
    } finally {
      setActualisation(false);
    }
  }, []);
  // Lot 117.1 — à l'ouverture : statuts et adresse RÉELLE du bouton de la série déposée chez Meta (sans message)
  useEffect(() => { actualiser(true); }, [actualiser]);
  // Tant qu'un modèle déposé est en attente, relecture automatique toutes les 60 s (30 min au plus)
  useEffect(() => {
    if (!resultats) return undefined;
    let n = 0;
    const t = setInterval(() => {
      n += 1;
      const enAttente = resultats.some((r) => {
        const k = Number(String(r.nom).split("_").pop());
        return (actuels[k] || actuels[String(k)] || "PENDING") === "PENDING";
      });
      if (!enAttente || n > 30) { clearInterval(t); return; }
      actualiser(true);
    }, 60000);
    return () => clearInterval(t);
  }, [resultats, actuels, actualiser]);
  const creerChezMeta = async (forcer = false) => {
    if (!modele) { toast.error("Saisissez d'abord le nom (préfixe) des modèles, ex. sawali_carrousel."); return; }
    if (!forcer && !window.confirm(`Déposer chez Meta les 9 modèles ${modele}_2 à ${modele}_10 (catégorie Marketing) ?`)) return;
    setCreation(true);
    setResultats(null);
    try {
      const { data } = await apiClient.post("/admin/whatsapp/carrousel/modeles-meta",
        { modele, langue, tenant_id: tenantId || null, forcer }, { timeout: 180000 });
      setResultats(data.resultats);
      setActuels({});
      const ok = data.resultats.filter((r) => r.statut !== "erreur").length;
      if (ok) { toast.success(`${ok} modèle(s) soumis à Meta. L'approbation prend de quelques minutes à 24 h.`); onEnregistre(); }
      else toast.error("Aucun modèle n'a été accepté : voir le détail ci-dessous.");
    } catch (e) {
      // Lot 117.1 — une série APPROUVÉE existe déjà : la réutiliser (recommandé) plutôt que d'en déposer une copie
      const d = e?.response?.data?.detail;
      if (e?.response?.status === 409 && d?.serie_approuvee) {
        setCreation(false);
        if (window.confirm(`${d.message}\n\nOK = réutiliser « ${d.serie_approuvee} » (recommandé)\nAnnuler = autres choix`)) {
          try {
            await apiClient.put("/admin/whatsapp/carrousel/reglages", { modele: d.serie_approuvee, langue, tenant_id: tenantId || null });
            setModele(d.serie_approuvee);
            toast.success(`Série « ${d.serie_approuvee} » réutilisée : vos carrousels partent avec elle.`);
            onEnregistre();
            actualiser(true);
          } catch (e2) { toast.error(erreur(e2, "Réglages refusés")); }
        } else if (window.confirm("Déposer QUAND MÊME une nouvelle série ? Meta la refusera si ses textes recopient ceux de la série approuvée.")) {
          creerChezMeta(true);
        }
        return;
      }
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
        <code> {"{{2}}"}</code> (texte), un bouton URL dynamique : <code className="break-all">{urlReelle || etat.url_bouton_modele}</code>
        {/* Lot 117.1 — adresse RÉELLE de la série déposée chez Meta (sinon celle d'une nouvelle série) */}
        {urlReelle ? " (adresse de la série déposée chez Meta)." : " (adresse d'une nouvelle série)."}
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
        <Button size="sm" variant="outline" onClick={() => creerChezMeta(false)} disabled={!modele || creation}>
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
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <Button type="button" size="sm" variant="outline" disabled={actualisation} onClick={() => actualiser(false)}>
            {actualisation ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />}
            Actualiser les statuts Meta
          </Button>
          Relu automatiquement chaque minute tant qu'un modèle est en attente.
        </div>
      )}
      {resultats && (
        <table className="w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="py-1">Modèle</th><th>Dépôt</th><th>Détail du dépôt</th><th>Statut actuel chez Meta</th></tr></thead>
          <tbody>
            {resultats.map((r) => (
              <tr key={r.nom} className="border-t border-slate-100">
                <td className="py-1 font-mono">{r.nom}</td>
                <td>
                  {r.statut === "erreur"
                    ? <span className="inline-flex items-center gap-1 text-red-600"><XCircle className="h-3.5 w-3.5" /> erreur</span>
                    : <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> {r.statut}</span>}
                </td>
                <td className="text-slate-600">{STATUT_COURT[r.detail] ? `${STATUT_COURT[r.detail]} (au dépôt)` : r.detail}</td>
                <td>
                  {(() => {
                    const k = Number(String(r.nom).split("_").pop());
                    const st = actuels[k] || actuels[String(k)];
                    const motif = motifs[k] || motifs[String(k)];   // Lot 115.1 — raison du refus
                    return st ? <span className="inline-flex flex-wrap items-center gap-1"><PastilleMeta statut={st} modele={r.nom} /> {STATUT_COURT[st] || st}
                      {motif && <span className="text-red-700">— motif : {motif.libelle} ({motif.code})</span>}</span>
                      : <span className="text-slate-400">—</span>;
                  })()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// Lot 79 — lien et QR code d'accord : la personne envoie elle-même « OUI NOUVEAUTES » (STOP pour arrêter)
function LienAccord({ base }) {
  const [info, setInfo] = useState(null);
  const [qr, setQr] = useState("");
  useEffect(() => {
    apiClient.get(`${base}/lien-accord`).then(async ({ data }) => {
      setInfo(data);
      if (data.lien) setQr(await QRCode.toDataURL(data.lien, { errorCorrectionLevel: "M", width: 240, margin: 1 }));
    }).catch(() => setInfo({ lien: "", erreur: "Lien d'accord indisponible" }));
  }, [base]);
  if (!info) return null;
  const copier = async () => {
    try { await navigator.clipboard.writeText(info.lien); toast.success("Lien copié"); } catch { toast.error("Copie impossible"); }
  };
  return (
    <details className="rounded-md border border-emerald-200 bg-emerald-50/50 p-3 text-xs text-slate-700">
      <summary className="cursor-pointer font-medium text-emerald-800">Lien et QR code d'accord (pour ceux qui ne vous ont pas écrit récemment)</summary>
      {info.lien ? (
        <div className="mt-2 flex flex-wrap items-start gap-4">
          {qr && <img src={qr} alt="QR code d'accord WhatsApp" className="h-32 w-32 rounded bg-white p-1" />}
          <div className="min-w-0 flex-1 space-y-2">
            <p>À afficher au comptoir, sur une affiche ou sur vos réseaux. La personne scanne ou touche le lien : WhatsApp s'ouvre
              avec <b>« {info.mot_cle} »</b> déjà écrit vers le {info.numero}. Dès qu'elle l'envoie, son accord est noté
              automatiquement (avec la date). « STOP » le retire à tout moment.</p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="break-all rounded bg-white px-2 py-1">{info.lien}</code>
              <Button type="button" size="sm" variant="outline" onClick={copier}><Copy className="mr-1 h-4 w-4" /> Copier le lien</Button>
              {qr && <a href={qr} download="qr-accord-whatsapp.png" className="text-emerald-700 underline">Télécharger le QR code</a>}
            </div>
          </div>
        </div>
      ) : <p className="mt-2 text-amber-700">{info.erreur || "Lien d'accord indisponible"}</p>}
    </details>
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
// Lot 78.2 — statut Meta en mots simples (au lieu de APPROVED / PENDING)
const STATUT_COURT = { APPROVED: "approuvé", PENDING: "en attente", IN_APPEAL: "en appel", REJECTED: "refusé",
  PAUSED: "en pause", DISABLED: "désactivé", ABSENT: "non créé" };
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
function MesCarrousels({ base, courant, onOuvrir, onEnregistre, rafraichir, onComposer, peutPartager }) {
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
  // Lot 78.2 — tant qu'un modèle est « en attente » chez Meta, relecture automatique chaque minute (30 min au plus)
  const enAttente = Object.values(meta.statuts || {}).some((x) => x === "PENDING" || x === "IN_APPEAL");
  useEffect(() => {
    if (!enAttente) return undefined;
    let n = 0;
    const t = setInterval(() => { n += 1; if (n > 30) clearInterval(t); else if (pageVisible()) charger(true); }, 60000);   // lot 79.6 : pas de relecture onglet masqué
    return () => clearInterval(t);
  }, [enAttente, charger]);

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
  // Lot 79 — partage : adresses e-mail des comptes (admin, superviseur, client) qui verront ce carrousel
  const partager = async (b) => {
    const actuels = (b.partages || []).map((x) => x.email).join(", ");
    const saisie = window.prompt(`Partager « ${b.nom} » avec (adresses e-mail séparées par des virgules ; vide = ne plus partager) :`, actuels);
    if (saisie === null) return;
    try {
      const emails = saisie.split(/[,;\s]+/).map((x) => x.trim()).filter(Boolean);
      const { data } = await apiClient.put(`${base}/brouillons/${b.id}/partages`, { emails });
      toast.success(data.partages.length ? `Partagé avec ${data.partages.map((x) => x.nom).join(", ")}` : "Ce carrousel n'est plus partagé");
      charger();
    } catch (e) {
      toast.error(erreur(e, "Partage impossible"));
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
          <RefreshCw className="mr-1 h-4 w-4" /> Actualiser les statuts Meta
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
                <span className="text-slate-500">· {STATUT_COURT[meta.statuts?.[n] || meta.statuts?.[String(n)] || "ABSENT"] || ""}</span>
              </button>
            ))}
          </div>
          {/* Lot 115.1 — modèles refusés : motif donné par Meta, en clair */}
          {Object.keys(meta.motifs || {}).length > 0 && (
            <div className="mt-2 rounded-lg bg-red-50 p-2 text-xs text-red-800 ring-1 ring-red-200">
              <p className="font-semibold">Modèles refusés par Meta :</p>
              <ul className="ml-4 list-disc">
                {Object.entries(meta.motifs).map(([n, m]) => (
                  <li key={n}>{meta.prefixe}_{n} ({n} cartes) : {m.libelle} <span className="text-red-600">({m.code})</span></li>
                ))}
              </ul>
            </div>
          )}
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
                  <td className="font-medium">
                    {b.nom}
                    {b.partage && <span className="ml-2 rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-normal text-sky-800">partagé par {b.partage_par}</span>}
                    {!b.partage && (b.partages || []).length > 0 && (
                      <span className="ml-2 text-[10px] font-normal text-slate-500" title={(b.partages || []).map((x) => x.email).join(", ")}>
                        partagé avec {(b.partages || []).length}
                      </span>
                    )}
                  </td>
                  <td className="tabular-nums">{b.nb_cartes}</td>
                  <td className="font-mono text-xs">{b.modele || "—"}</td>
                  <td className="text-xs">{dateFr(b.modifie_le)}</td>
                  <td className="whitespace-nowrap text-right">
                    <Button type="button" size="sm" variant="outline" className="mr-1" title="Afficher ce carrousel dans l'éditeur"
                            onClick={() => (b.partage
                              ? (onOuvrir({ ...b, id: null, nom: "" }), toast.info("Carrousel partagé : enregistrez-le sous un nom pour le garder dans votre espace"))
                              : onOuvrir(b))}>
                      <FolderOpen className="h-4 w-4" />
                    </Button>
                    <Button type="button" size="sm" variant="outline" className="mr-1" onClick={() => dupliquer(b)} title="Dupliquer pour en créer un nouveau">
                      <Copy className="h-4 w-4" />
                    </Button>
                    {peutPartager && !b.partage && (
                      <Button type="button" size="sm" variant="outline" className="mr-1" onClick={() => partager(b)} title="Partager avec d'autres comptes (e-mail)">
                        <Share2 className="h-4 w-4" />
                      </Button>
                    )}
                    {!b.partage && (
                      <Button type="button" size="sm" variant="outline" onClick={() => supprimer(b)} title="Supprimer">
                        <Trash2 className="h-4 w-4 text-red-600" />
                      </Button>
                    )}
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
  const { user } = useAuth();
  const peutPartager = admin || ["admin", "superviseur"].includes(user?.role);   // lot 79
  const [etat, setEtat] = useState(null);
  const [refus, setRefus] = useState("");
  const [produits, setProduits] = useState([]);
  const [images, setImages] = useState([]);
  const [annuaire, setAnnuaire] = useState({ contacts: [], groupes: [] });
  const [campagnes, setCampagnes] = useState([]);
  // Lot 156 : « Envois précédents » repliés par défaut (une ligne par envoi : date et heure) ; un clic déplie les autres informations.
  const [details, setDetails] = useState({});            // détail des destinataires par campagne (chargé au dépliage)
  const [deplies, setDeplies] = useState(() => new Set()); // campagnes dépliées
  // Lot 160 : seuls les 20 derniers envois sont affichés ; « Voir plus » en ajoute 20 à chaque clic
  const [nbAffiches, setNbAffiches] = useState(20);
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
  const [lienDefautServeur, setLienDefautServeur] = useState("");   // lot 78.3 : valeur enregistrée, utilisée à l'envoi
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
  // Lot 111 — carrousel sponsorisé (administration) : campagnes de la régie et campagne choisie pour l'envoi
  const [regies, setRegies] = useState([]);
  const [regieId, setRegieId] = useState("");

  const charger = useCallback(async () => {
    try {
      const [e, p, i, d, c] = await Promise.all([
        apiClient.get(base), apiClient.get(`${base}/produits`), apiClient.get(`${base}/images`),
        apiClient.get(`${base}/destinataires`), apiClient.get(`${base}/campagnes`),
      ]);
      setEtat(e.data); setProduits(p.data.produits); setImages(i.data.images);
      setAnnuaire(d.data); setCampagnes(c.data.campagnes);
      if (admin) {
        // Lot 111 — campagnes de régie « Carrousel WhatsApp » (facultatif : l'écran reste utilisable sans)
        apiClient.get(`${base}/regies`).then((r) => setRegies(r.data.regies || [])).catch(() => setRegies([]));
      }
    } catch (e) {
      setRefus(erreur(e, "Carrousel indisponible"));
    }
  }, [base, admin]);
  useEffect(() => { charger(); }, [charger]);

  // Lot 78 — au chargement : lien par défaut, puis restauration du brouillon automatique
  useEffect(() => {
    let fini = false;
    (async () => {
      try {
        const [pref, auto] = await Promise.all([apiClient.get(`${base}/preferences`), apiClient.get(`${base}/brouillon-auto`)]);
        if (fini) return;
        setLienDefaut(pref.data.lien_defaut || "");
        setLienDefautServeur(pref.data.lien_defaut || "");
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
      setLienDefautServeur(data.lien_defaut);
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
    // Lot 79 — l'accord noté à la main doit avoir été réellement donné (oral, écrit) : confirmation explicite
    if (accepte && !window.confirm("Cette personne vous a-t-elle réellement donné son accord (de vive voix ou par écrit) ?\n"
      + "Ne notez jamais un accord qui n'a pas été donné : utilisez plutôt « Demander l'accord » ou le lien d'accord.")) return;
    try {
      await apiClient.put(`${base}/consentements`, { ids, accepte });
      toast.success(accepte ? "Consentement noté" : "Consentement retiré");
      const { data } = await apiClient.get(`${base}/destinataires`);
      setAnnuaire(data);
    } catch (e) {
      toast.error(erreur(e, "Modification refusée"));
    }
  };
  // Lot 79 — demande d'accord : message WhatsApp à 2 boutons ; l'accord est noté dès que la personne touche « Oui »
  const [demande, setDemande] = useState(false);
  const demanderAccord = async () => {
    const ids = new Set(choisis);
    annuaire.groupes.filter((g) => groupes.has(g.id)).forEach((g) => g.contact_ids.forEach((x) => ids.add(x)));
    const cibles = annuaire.contacts.filter((c) => ids.has(c.id) && !c.accepte && c.telephone);
    if (!cibles.length) { toast.info("Cochez d'abord des personnes qui n'ont pas encore donné leur accord."); return; }
    if (!window.confirm(`Envoyer la demande d'accord (boutons « Oui, j'accepte » / « Non merci ») à ${cibles.length} personne(s) ?`)) return;
    setDemande(true);
    try {
      const { data } = await apiClient.post(`${base}/demande-accord`, { ids: cibles.map((c) => c.id) });
      if (data.envoyees) toast.success(`${data.envoyees} demande(s) envoyée(s) : l'accord sera noté dès que la personne touchera « Oui ».`);
      if (data.fenetre_fermee.length) toast.warning(`${data.fenetre_fermee.length} personne(s) ne vous ont pas écrit depuis 24 h : WhatsApp interdit de leur écrire en premier. Donnez-leur le lien ou le QR code d'accord : ${data.fenetre_fermee.slice(0, 5).join(", ")}${data.fenetre_fermee.length > 5 ? "…" : ""}`, { duration: 12000 });
      if (data.erreurs.length) toast.error(data.erreurs.slice(0, 3).join(" · "));
    } catch (e) {
      toast.error(erreur(e, "Demande d'accord impossible"));
    } finally {
      setDemande(false);
    }
  };
  // Destinataires réels : contacts cochés + membres des groupes, qui ont accepté
  const retenus = useMemo(() => {
    const ids = new Set(choisis);
    annuaire.groupes.filter((g) => groupes.has(g.id)).forEach((g) => g.contact_ids.forEach((x) => ids.add(x)));
    return annuaire.contacts.filter((c) => ids.has(c.id) && c.accepte && c.telephone);
  }, [choisis, groupes, annuaire]);
  // Lot 155 : parmi eux, ceux qui n'ont jamais écrit à la plateforme
  const silencieux = useMemo(() => retenus.filter((c) => !c.a_repondu), [retenus]);

  const [envoiErreur, setEnvoiErreur] = useState("");   // lot 79.1 : motif d'un refus, affiché sous le bouton
  // Lot 114 — date et heure d'envoi programmées (« AAAA-MM-JJTHH:MM », heure de Ouagadougou) ; vide = maintenant
  const [programmeLe, setProgrammeLe] = useState("");
  const envoyer = async () => {
    const quand = programmeLe ? ` le ${dateFr(programmeLe)}` : "";
    if (!window.confirm(`${programmeLe ? "Programmer" : "Envoyer"} ce carrousel de ${cartes.length} cartes à ${retenus.length} destinataire(s)${quand} ?`)) return;
    setEnvoi(true);
    setEnvoiErreur("");
    // Lot 114 — toast « Patientez… » pendant la préparation de la campagne (contrôles, liens, régie)
    const attente = toast.loading("Patientez… préparation de l'envoi");
    try {
      const corps = {
        message,
        cartes: cartesPourServeur(cartes),
        ids: [...choisis], groupes: [...groupes],
        regie_id: admin && regieId ? regieId : null,   // lot 111 : carrousel sponsorisé
        programme_le: programmeLe || null,              // lot 114 : envoi programmé (vide = maintenant)
      };
      const { data } = await apiClient.post(`${base}/envoyer`, corps);
      // Lot 114 — message selon le statut de départ : programmé, en attente d'une plage horaire ou lancé
      if (data.statut === "PROGRAMMEE") {
        toast.success(`Envoi programmé le ${dateFr(data.programme_le)} vers ${data.destinataires} destinataire(s)`, { id: attente });
      } else if (data.statut === "EN_ATTENTE") {
        toast.info(`Hors des plages horaires d'envoi : le carrousel partira le ${dateFr(data.reprise_le)} (${data.destinataires} destinataire(s))`, { id: attente, duration: 8000 });
      } else {
        toast.success(`Envoi lancé vers ${data.destinataires} destinataire(s) (modèle ${data.modele})`, { id: attente });
      }
      setProgrammeLe("");
      setTimeout(charger, data.statut === "EN_COURS" ? 3000 : 300);
    } catch (e) {
      const motif = erreur(e, "Envoi refusé");
      toast.error(motif, { id: attente, duration: 10000 });
      setEnvoiErreur(motif);   // reste affiché sous le bouton tant qu'on ne relance pas l'envoi
    } finally {
      setEnvoi(false);
    }
  };

  // Lot 111 — rattacher un envoi déjà fait à une campagne de régie (ses prochains clics seront facturés)
  const [liaison, setLiaison] = useState("");
  const lierRegie = async (c, rid) => {
    setLiaison(c.id);
    const attente = toast.loading("Patientez… rattachement à la régie");
    try {
      await apiClient.put(`${base}/campagnes/${c.id}/regie`, { regie_id: rid || null });
      toast.success(rid ? "Envoi rattaché à la campagne de régie : ses clics seront facturés" : "Envoi détaché de la régie", { id: attente });
      await charger();
    } catch (e) {
      toast.error(erreur(e, "Rattachement impossible"), { id: attente });
    } finally {
      setLiaison("");
    }
  };

  // Lot 114 — annuler un envoi programmé, en attente ou en cours (les destinataires déjà servis le restent)
  const [annulation, setAnnulation] = useState("");
  const annuler = async (c) => {
    if (!window.confirm(`Annuler cet envoi (${PASTILLES_STATUT[c.statut]?.[1] || c.statut}) ? Les messages déjà partis ne sont pas rappelés.`)) return;
    setAnnulation(c.id);
    const attente = toast.loading("Patientez… annulation de l'envoi");
    try {
      await apiClient.post(`${base}/campagnes/${c.id}/annuler`);
      toast.success("Envoi annulé", { id: attente });
      await charger();
    } catch (e) {
      toast.error(erreur(e, "Annulation impossible"), { id: attente });
    } finally {
      setAnnulation("");
    }
  };
  // Lot 114 — envois programmés, en attente d'une plage horaire ou en cours (liste dédiée en tête de la section 3)
  const envoisActifs = useMemo(() => campagnes.filter((c) => STATUTS_ACTIFS.includes(c.statut)), [campagnes]);
  // Lot 114 — relecture toutes les 30 s tant qu'un envoi est en cours (onglet visible seulement)
  useEffect(() => {
    if (!campagnes.some((c) => c.statut === "EN_COURS")) return undefined;
    const t = setInterval(() => { if (pageVisible()) charger(); }, 30000);
    return () => clearInterval(t);
  }, [campagnes, charger]);

  const ouvrirDetail = async (id) => {
    const { data } = await apiClient.get(`${base}/campagnes/${id}`);
    setDetails((p) => ({ ...p, [id]: data }));
  };
  // Plie / déplie un envoi précédent ; le détail des destinataires (remise réelle) est lu au dépliage
  const basculerEnvoi = (id) => {
    const ouvert = deplies.has(id);
    setDeplies((p) => { const n = new Set(p); if (ouvert) n.delete(id); else n.add(id); return n; });
    if (!ouvert) ouvrirDetail(id).catch(() => {});
  };

  if (refus) return <div className="m-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">{refus}</div>;
  if (!etat) return <div className="flex justify-center p-10"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>;

  // Lot 94 — le lien n'est plus obligatoire : une carte sans lien (ni lien par défaut) mène à sa page de
  // présentation sur le site (photo, titre, texte, prix du produit)
  const cartesPretes = cartes.every((c) => (c.source === "produit" ? c.produit_id : c.image_url && c.titre));
  // Lot 78.3 — ce qui manque pour pouvoir envoyer (affiché à côté du bouton grisé)
  const manques = [];
  if (etat && !etat.pret) manques.push("WhatsApp ou les modèles du carrousel ne sont pas configurés");
  if (!message.trim()) manques.push("le texte au-dessus des cartes (rubrique 1)");
  cartes.forEach((c, i) => {
    if (c.source === "produit") { if (!c.produit_id) manques.push(`carte ${i + 1} : choisir un produit`); return; }
    const m = [!c.image_url && "image", !c.titre && "titre"].filter(Boolean);
    if (m.length) manques.push(`carte ${i + 1} : ${m.join(", ")}`);
  });
  if (retenus.length === 0) manques.push(choisis.size + groupes.size > 0
    ? "aucun destinataire coché n'a « accepté » les messages WhatsApp (notez son accord dans la liste)"
    : "cocher au moins un destinataire");

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
      <MesCarrousels base={base} courant={courant} onOuvrir={ouvrirCarrousel} rafraichir={rafraichirListe} onComposer={composer} peutPartager={peutPartager}
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
                    {!c.lien && c.bouton !== "presentation" && (
                      <p className="text-[11px] text-slate-500">
                        {lienDefautServeur ? `Sans lien : le bouton ouvrira ${lienDefautServeur}` : "Sans lien : le bouton ouvrira la page de présentation de cette carte sur le site."}
                      </p>
                    )}
                  </div>
                </div>
              )}
              {/* Lot 111 — où mène le bouton de la carte, et description détaillée de la page de présentation */}
              <div className="mt-3 space-y-2 rounded-md bg-slate-50 p-3">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                  <span className="text-xs font-medium text-slate-600">Bouton de la carte :</span>
                  {[["presentation", "Page de présentation (recommandé)"], ["lien", "Lien personnalisé"]].map(([v, libelle]) => (
                    <label key={v} className="inline-flex items-center gap-1.5">
                      <input type="radio" name={`bouton-${i}`} checked={modeBouton(c, lienDefautServeur) === v}
                             onChange={() => majCarte(i, { bouton: v })} />
                      {libelle}
                    </label>
                  ))}
                </div>
                {c.source === "produit" && c.bouton === "lien" && (
                  <input className={champ} placeholder="Lien du bouton https://…" value={c.lien || ""} onChange={(e) => majCarte(i, { lien: e.target.value })} />
                )}
                <p className="text-[11px] text-slate-500">
                  {modeBouton(c, lienDefautServeur) === "presentation"
                    ? `Le bouton ouvre la page de présentation de tout le carrousel, directement sur cette carte (carte ${i + 1}), avec « Je suis intéressé » (WhatsApp).`
                    : "Le bouton ouvre le lien saisi (ou le lien par défaut). Choisissez « Page de présentation » pour présenter la carte sur le site."}
                </p>
                <textarea className={champ} rows={4} maxLength={DESCRIPTION_MAX}
                          placeholder={"Description détaillée affichée sur la page de présentation (facultatif).\nMarkdown simple : **gras**, *italique*, - liste, [texte](https://…)"}
                          value={c.description_detaillee || ""} onChange={(e) => majCarte(i, { description_detaillee: e.target.value })} />
                <p className="text-right text-[11px] text-slate-400">{(c.description_detaillee || "").length} / {DESCRIPTION_MAX}</p>
              </div>
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
          WhatsApp et loi sur les données personnelles). Pour obtenir l'accord : cochez les personnes puis
          « Demander l'accord » (boutons Oui / Non, noté automatiquement), ou donnez-leur le lien / QR code ci-dessous.
        </p>
        <LienAccord base={base} />
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
          <Button type="button" size="sm" variant="outline" disabled={demande} onClick={demanderAccord}
                  title="Envoie « Souhaitez-vous recevoir nos nouveautés ? » avec les boutons Oui / Non aux personnes cochées sans accord">
            {demande ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <MessageSquareReply className="mr-1 h-4 w-4" />}
            Demander l'accord (boutons Oui / Non)
          </Button>
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
                    <input type="checkbox" disabled={!c.telephone} checked={choisis.has(c.id)}
                           onChange={() => basculer(choisis, setChoisis, c.id)} />
                  </td>
                  <td className="p-2">{c.nom}<span className="text-xs text-slate-500"> {c.societe}</span>
                    {c.telephone && !c.a_repondu && (
                      <span className="ml-1 rounded bg-amber-100 px-1.5 text-[10px] text-amber-800" data-testid="carrousel-jamais-repondu"
                            title="N'a jamais écrit à votre ligne WhatsApp : WhatsApp peut refuser de lui remettre un message marketing (code 131049)">jamais répondu</span>
                    )}
                  </td>
                  <td className="p-2 text-slate-600">{c.telephone || <span className="text-red-600">aucun numéro</span>}</td>
                  <td className="p-2">
                    {c.accepte ? (
                      <button type="button" className="text-xs text-emerald-700" title="Retirer l'accord" onClick={() => consentement([c.id], false)}>
                        <CheckCircle2 className="mr-1 inline h-4 w-4" />accepté {c.accepte_le ? `le ${dateFr(c.accepte_le)}` : ""}
                        {c.moyen && <span className="ml-1 text-slate-500">({c.moyen})</span>}
                      </button>
                    ) : (
                      <button type="button" className="text-xs text-slate-600 underline" onClick={() => consentement([c.id], true)}>
                        Noter son accord (donné de vive voix ou par écrit)
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Lot 111 — carrousel sponsorisé : campagne de la régie publicitaire qui paie les clics (administration) */}
        {admin && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-fuchsia-200 bg-fuchsia-50/60 p-3 text-sm">
            <Megaphone className="h-4 w-4 text-fuchsia-700" />
            <label htmlFor="carrousel-regie" className="text-xs font-medium text-slate-700">Carrousel sponsorisé (régie publicitaire) :</label>
            <select id="carrousel-regie" className="rounded border border-slate-300 px-2 py-1 text-sm" value={regieId}
                    onChange={(e) => setRegieId(e.target.value)}>
              <option value="">— Aucune (carrousel ordinaire) —</option>
              {regies.map((r) => (
                <option key={r.id} value={r.id} disabled={!!r.motif}>
                  {r.nom}{r.annonceur ? ` · ${r.annonceur}` : ""} — {r.cout_par_clic} {r.devise}/clic
                  {r.reste != null ? ` · reste ${Math.round(r.reste)} ${r.devise}` : ""}{r.motif ? ` (${r.motif})` : ""}
                </option>
              ))}
            </select>
            <span className="w-full text-[11px] text-slate-500">
              Chaque clic sur un bouton est facturé à l'annonceur (une fois par appareil et par carte sur 24 h, dans la limite
              du budget). Les campagnes se créent dans « Régie publicitaire » (type « Carrousel WhatsApp »).
            </span>
          </div>
        )}
        {/* Lot 114 — Maintenant / Programmer le … ; rappel des plages horaires d'envoi fixées par l'Admin */}
        <EnvoiProgrammation value={programmeLe} onChange={setProgrammeLe} />
        {/* Lot 155 : alerte avant l'envoi — destinataires qui n'ont jamais écrit à la ligne (risque de non-remise, code 131049) */}
        {silencieux.length > 0 && (
          <div role="status" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="carrousel-alerte-silencieux">
            <b>{silencieux.length} destinataire(s) sur {retenus.length} n'ont jamais écrit à votre ligne WhatsApp</b> :
            {" "}{silencieux.slice(0, 6).map((c) => c.nom).join(", ")}{silencieux.length > 6 ? `, … (+${silencieux.length - 6})` : ""}.
            WhatsApp peut refuser de leur remettre un message marketing (code 131049, « healthy ecosystem engagement ») même si l'envoi est
            accepté. Demandez-leur d'écrire d'abord un mot à votre ligne, puis vérifiez la remise dans « Envois précédents ».
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-700"><b>{retenus.length}</b> destinataire(s) (max. {etat.destinataires_max})</span>
          <Button onClick={envoyer} disabled={!etat.pret || envoi || !message.trim() || !cartesPretes || retenus.length === 0
                                               || retenus.length > etat.destinataires_max}>
            {envoi ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Send className="mr-1 h-4 w-4" />}
            {programmeLe ? "Programmer l'envoi" : "Envoyer le carrousel"}
          </Button>
          {!envoi && manques.length > 0 && (
            <span className="w-full text-xs text-amber-700">Pour envoyer, il manque : {manques.join(" · ")}.</span>
          )}
          {!envoi && envoiErreur && (
            <div role="alert" className="w-full rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              <XCircle className="mr-1 inline h-4 w-4" /> Envoi refusé : {envoiErreur}
            </div>
          )}
        </div>
      </section>

      {/* 3. Campagnes */}
      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800"><Package className="h-4 w-4" /> 3. Envois précédents</h2>
        {campagnes.length === 0 && <p className="text-sm text-slate-500">Aucun envoi pour le moment.</p>}
        {/* Lot 114 — envois programmés / en attente / en cours, avec annulation */}
        {envoisActifs.length > 0 && (
          <div className="rounded-md border border-sky-200 bg-sky-50/60 p-3 text-sm" data-testid="carrousel-envois-programmes">
            <p className="mb-2 font-semibold text-slate-800">Envois programmés et en attente ({envoisActifs.length})</p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-xs">
                <thead className="text-left text-slate-500">
                  <tr><th className="py-1 pr-2">Statut</th><th className="py-1 pr-2">Départ prévu / reprise</th>
                    <th className="py-1 pr-2">Message</th><th className="py-1 pr-2 text-right">Envoyés</th><th className="py-1" /></tr>
                </thead>
                <tbody>
                  {envoisActifs.map((c) => (
                    <tr key={c.id} className="border-t border-sky-100">
                      <td className="py-1 pr-2"><PastilleStatut statut={c.statut} libelle={c.statut_libelle} /></td>
                      <td className="py-1 pr-2">
                        {c.statut === "PROGRAMMEE" && <>le {dateFr(c.programme_le)}</>}
                        {c.statut === "EN_ATTENTE" && <>reprendra le {dateFr(c.reprise_le)}</>}
                        {c.statut === "EN_COURS" && <>en cours d'envoi…</>}
                      </td>
                      <td className="max-w-[240px] truncate py-1 pr-2">{c.message}</td>
                      <td className="py-1 pr-2 text-right tabular-nums">{c.compte.envoyes} / {c.compte.total}</td>
                      <td className="py-1 text-right">
                        <Button size="sm" variant="outline" disabled={annulation === c.id} onClick={() => annuler(c)}
                                data-testid={`annuler-campagne-${c.id}`}>
                          <XCircle className="mr-1 h-3.5 w-3.5" /> Annuler
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {campagnes.slice(0, nbAffiches).map((c) => (
          <div key={c.id} className="rounded-md border border-slate-200 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => basculerEnvoi(c.id)} aria-expanded={deplies.has(c.id)} data-testid={`carrousel-envoi-${c.id}`}
                      className="inline-flex items-center gap-1 font-medium hover:text-sawali-blue" title="Déplier / replier cet envoi">
                {deplies.has(c.id) ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}{dateFr(c.cree_le)}
              </button>
              <span className="text-slate-600">{c.cartes.length} cartes · {c.modele}</span>
              <span className="text-emerald-700">{c.compte.envoyes} envoyé(s)</span>
              {c.compte.echecs > 0 && <span className="text-red-700">{c.compte.echecs} échec(s)</span>}
              {/* Lot 114 — statut en pastille, date programmée, reprise prévue, motif d'arrêt */}
              <PastilleStatut statut={c.statut} libelle={c.statut_libelle} />
              {c.programme_le && <span className="text-xs text-sky-700">programmé le {dateFr(c.programme_le)}</span>}
              {c.statut === "EN_ATTENTE" && c.reprise_le && <span className="text-xs text-amber-700">reprendra le {dateFr(c.reprise_le)}</span>}
              {c.statut === "ANNULEE" && (
                <span className="text-xs text-slate-500">
                  {c.annule_le ? `annulé le ${dateFr(c.annule_le)}` : ""}{c.annule_par ? ` par ${c.annule_par}` : ""}
                  {c.motif_arret ? ` — ${c.motif_arret}` : ""}
                </span>
              )}
              {c.annulable && (
                <Button size="sm" variant="ghost" className="text-red-700" disabled={annulation === c.id} onClick={() => annuler(c)}>
                  <XCircle className="mr-1 h-3.5 w-3.5" /> Annuler
                </Button>
              )}
              {/* Lot 78 — recharge les cartes et le message de cet envoi dans l'éditeur (nouveau carrousel) */}
              <Button size="sm" variant="outline" className="ml-auto" title="Reprendre ce carrousel dans l'éditeur pour le modifier ou le renvoyer"
                onClick={() => { ouvrirCarrousel({ nom: "", message: c.message, cartes: c.cartes.map(({ source, produit_id, image_url, titre, texte, lien, bouton, description_detaillee }) => ({ source, produit_id, image_url, titre, texte, lien, bouton, description_detaillee })) }); if (admin && c.regie_id) setRegieId(c.regie_id); toast.success("Carrousel rechargé dans l'éditeur — pensez à l'enregistrer sous un nom"); }}>
                Recharger dans l'éditeur
              </Button>
              <Button size="sm" variant="ghost" onClick={() => basculerEnvoi(c.id)}>
                {deplies.has(c.id) ? "Masquer" : "Détail"}
              </Button>
            </div>
            {deplies.has(c.id) && (<>
            <div className="mt-1 truncate text-slate-600">{c.message}</div>
            {/* Lot 111 — par carte : clics, vues de la page de présentation, « Je suis intéressé » (et clics facturés) */}
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[420px] text-xs">
                <thead className="text-left text-slate-500">
                  <tr><th className="py-1 pr-2">Carte</th><th className="py-1 pr-2 text-right">Clics</th>
                    {c.regie_id && <th className="py-1 pr-2 text-right">Facturés</th>}
                    <th className="py-1 pr-2 text-right">Vues présentation</th><th className="py-1 text-right">« Je suis intéressé »</th></tr>
                </thead>
                <tbody>
                  {c.cartes.map((k, i) => (
                    <tr key={i} className="border-t border-slate-100">
                      <td className="py-1 pr-2">{i + 1}. {k.titre}</td>
                      <td className="py-1 pr-2 text-right tabular-nums">{k.clics}</td>
                      {c.regie_id && <td className="py-1 pr-2 text-right tabular-nums">{k.clics_factures || 0}</td>}
                      <td className="py-1 pr-2 text-right tabular-nums">{k.vues || 0}</td>
                      <td className="py-1 text-right tabular-nums">{k.interesses || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              {c.url_presentation && (
                <a href={c.url_presentation} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-emerald-700 underline">
                  <ExternalLink className="h-3.5 w-3.5" /> Page de présentation
                </a>
              )}
              {c.regie_id && <span className="rounded-full bg-fuchsia-100 px-2 py-0.5 text-fuchsia-800">Sponsorisé : {c.regie_nom || "régie"}</span>}
              {admin && (
                <select className="ml-auto rounded border border-slate-300 px-2 py-1" value={c.regie_id || ""} disabled={liaison === c.id}
                        onChange={(e) => lierRegie(c, e.target.value)} title="Rattacher cet envoi à une campagne de la régie publicitaire">
                  <option value="">Non sponsorisé</option>
                  {regies.map((r) => <option key={r.id} value={r.id}>Régie : {r.nom}</option>)}
                </select>
              )}
            </div>
            {details[c.id] && (
              <ul className="mt-2 space-y-1 border-t border-slate-100 pt-2">
                {details[c.id].destinataires.map((d) => (
                  <li key={d.id} className="flex items-center gap-2">
                    {d.statut === "ENVOYE" ? <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      : d.statut === "ECHEC" ? <XCircle className="h-4 w-4 text-red-600" />
                        : <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
                    <span>{d.nom}</span><span className="text-slate-500">{d.telephone}</span>
                    {d.erreur && <span className="text-xs text-red-700">{d.erreur}</span>}
                    {/* Lot 152 : « Envoyé » = accepté par WhatsApp ; la remise réelle vient des accusés de WhatsApp */}
                    {d.statut === "ENVOYE" && (d.livraison === "failed"
                      ? <span className="rounded bg-red-100 px-1.5 text-xs text-red-800" data-testid="carrousel-non-remis">Non remis{d.livraison_erreur ? ` : ${d.livraison_erreur}` : ""}</span>
                      : d.livraison === "read" ? <span className="rounded bg-emerald-100 px-1.5 text-xs text-emerald-800">Lu</span>
                        : d.livraison === "delivered" ? <span className="rounded bg-emerald-50 px-1.5 text-xs text-emerald-700">Remis</span>
                          : <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-800" title="Accepté par WhatsApp, pas d'accusé de remise reçu (téléphone éteint, limite de WhatsApp sur les messages marketing…)">Pas d'accusé de remise</span>)}
                  </li>
                ))}
              </ul>
            )}
            </>)}
          </div>
        ))}
        {/* Lot 160 : liste limitée aux 20 derniers envois ; « Voir plus » en affiche 20 de plus */}
        {campagnes.length > nbAffiches && (
          <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="carrousel-voir-plus">
            <span className="text-slate-500">{nbAffiches} envois affichés sur {campagnes.length}</span>
            <Button size="sm" variant="outline" onClick={() => setNbAffiches((n) => n + 20)}>Voir plus (20 de plus)</Button>
            <Button size="sm" variant="ghost" onClick={() => setNbAffiches(campagnes.length)}>Tout afficher</Button>
          </div>
        )}
      </section>
    </div>
  );
}
