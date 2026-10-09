// RequeteOutils.jsx — Lots 86 / 86.1 : briques communes des requêtes clients, utilisées par le portail (« Mes requêtes »),
// la page publique du lien personnel (/requete/<jeton>) et l'écran SAWALI (« Requêtes des clients »).
//   - Enregistreur : message vocal enregistré dans le navigateur (MediaRecorder) ;
//   - SelecteurImages (86.1) : photo prise au téléphone, image chargée, ou capture d'écran COLLÉE (Ctrl+V) ;
//   - ImagesRequete (86.1) : vignettes des images d'une requête (clic = image en grand dans un nouvel onglet) ;
//   - Evaluation : note 1 à 5 étoiles + commentaire, envoyée par la fonction reçue (portail ou lien public).
import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Camera, ImagePlus, Mic, Square, Star, Trash2, X } from "lucide-react";

// « 09/10/2026 08:15 »
export const dateHeure = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
export const erreur = (e, defaut) => e?.response?.data?.detail || defaut;

// Couleur de la pastille d'état
export const COULEUR_ETAT = {
  nouvelle: "bg-sky-100 text-sky-800", en_cours: "bg-amber-100 text-amber-800",
  attente_client: "bg-purple-100 text-purple-800", terminee: "bg-emerald-100 text-emerald-800",
  deployee: "bg-emerald-600 text-white", rejetee: "bg-slate-200 text-slate-700",
};

export const MAX_IMAGES = 6;
const TAILLE_MAX_IMAGE = 8 * 1024 * 1024;   // 8 Mo, comme le serveur

// Enregistreur vocal (MediaRecorder) : démarre / arrête, renvoie le fichier audio au parent
export function Enregistreur({ audio, onAudio }) {
  const [enregistre, setEnregistre] = useState(false);
  const recorder = useRef(null);
  const morceaux = useRef([]);
  const demarrer = async () => {
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: true });
      const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg", "audio/mp4"];
      const mime = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
      const r = new MediaRecorder(flux, mime ? { mimeType: mime } : undefined);
      morceaux.current = [];
      r.ondataavailable = (e) => e.data.size && morceaux.current.push(e.data);
      r.onstop = () => {
        flux.getTracks().forEach((t) => t.stop());
        const type = r.mimeType || "audio/webm";
        const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
        onAudio(new File(morceaux.current, `requete.${ext}`, { type }));
      };
      r.start();
      recorder.current = r;
      setEnregistre(true);
    } catch {
      toast.error("Micro indisponible : autorisez le micro dans le navigateur");
    }
  };
  const arreter = () => { recorder.current?.stop(); setEnregistre(false); };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {!enregistre ? (
        <button type="button" onClick={demarrer} className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
          <Mic className="h-4 w-4 text-rose-600" /> {audio ? "Réenregistrer" : "Message vocal"}</button>
      ) : (
        <button type="button" onClick={arreter} className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white animate-pulse">
          <Square className="h-4 w-4" /> Arrêter l'enregistrement</button>
      )}
      {audio && !enregistre && (
        <>
          <audio controls src={URL.createObjectURL(audio)} className="h-8" />
          <button type="button" onClick={() => onAudio(null)} title="Supprimer le message vocal" className="text-rose-700"><Trash2 className="h-4 w-4" /></button>
        </>
      )}
    </div>
  );
}

// Lot 86.1 — images jointes : appareil photo (téléphone), fichiers, ou capture collée avec Ctrl+V n'importe où sur la page
export function SelecteurImages({ images, onImages }) {
  const photo = useRef(null);
  const fichiers = useRef(null);
  const courantes = useRef(images);
  courantes.current = images;

  // Ajoute des fichiers en contrôlant le type, la taille et le nombre
  const ajouter = (liste) => {
    const nouvelles = [];
    for (const f of Array.from(liste || [])) {
      if (!f.type.startsWith("image/")) { toast.error(`« ${f.name} » n'est pas une image`); continue; }
      if (f.size > TAILLE_MAX_IMAGE) { toast.error(`« ${f.name} » dépasse 8 Mo`); continue; }
      nouvelles.push(f);
    }
    const total = [...courantes.current, ...nouvelles];
    if (total.length > MAX_IMAGES) toast.error(`${MAX_IMAGES} images au plus par requête`);
    onImages(total.slice(0, MAX_IMAGES));
  };

  // Capture d'écran collée (Ctrl+V) : les images du presse-papiers sont ajoutées
  useEffect(() => {
    const coller = (e) => {
      const items = Array.from(e.clipboardData?.items || []).filter((i) => i.type.startsWith("image/"));
      if (!items.length) return;
      e.preventDefault();
      const horodatage = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      ajouter(items.map((i, n) => {
        const f = i.getAsFile();
        return new File([f], `capture-${horodatage}-${n + 1}.png`, { type: f.type || "image/png" });
      }));
      toast.success("Capture d'écran ajoutée");
    };
    window.addEventListener("paste", coller);
    return () => window.removeEventListener("paste", coller);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Aperçus (adresses locales du navigateur, libérées quand la liste change)
  const [apercus, setApercus] = useState([]);
  useEffect(() => {
    const urls = images.map((f) => URL.createObjectURL(f));
    setApercus(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [images]);

  const bouton = "inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50";
  return (
    <div className="space-y-2" data-testid="selecteur-images">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => photo.current?.click()} className={bouton}><Camera className="h-4 w-4 text-sky-700" /> Prendre une photo</button>
        <button type="button" onClick={() => fichiers.current?.click()} className={bouton}><ImagePlus className="h-4 w-4 text-sky-700" /> Charger des images</button>
        <span className="text-xs text-slate-500">ou collez une capture d'écran (Ctrl+V) · {images.length}/{MAX_IMAGES}</span>
        <input ref={photo} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => { ajouter(e.target.files); e.target.value = ""; }} />
        <input ref={fichiers} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { ajouter(e.target.files); e.target.value = ""; }} />
      </div>
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {apercus.map((u, i) => (
            <div key={u} className="relative">
              <img src={u} alt={images[i]?.name} className="h-20 w-20 rounded-lg border border-slate-200 object-cover" />
              <button type="button" title="Retirer" onClick={() => onImages(images.filter((_, j) => j !== i))}
                className="absolute -right-2 -top-2 rounded-full bg-rose-600 p-0.5 text-white"><X className="h-3 w-3" /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Lot 86.1 — vignettes des images d'une requête. « charger(img) » renvoie une promesse de Blob (route protégée ou publique).
export function ImagesRequete({ images, charger }) {
  const [urls, setUrls] = useState({});
  useEffect(() => {
    let actif = true;
    const crees = [];
    (images || []).forEach((img) => {
      charger(img).then((blob) => {
        const u = URL.createObjectURL(blob);
        crees.push(u);
        if (actif) setUrls((p) => ({ ...p, [img.id]: u }));
      }).catch(() => { if (actif) setUrls((p) => ({ ...p, [img.id]: "" })); });
    });
    return () => { actif = false; crees.forEach((u) => URL.revokeObjectURL(u)); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify((images || []).map((i) => i.id))]);
  if (!images?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {images.map((img) => (
        urls[img.id] === undefined ? <div key={img.id} className="h-20 w-20 animate-pulse rounded-lg bg-slate-200" title="Patientez…" />
          : urls[img.id] === "" ? <div key={img.id} className="flex h-20 w-20 items-center justify-center rounded-lg bg-slate-100 text-[10px] text-rose-700">indisponible</div>
          : <a key={img.id} href={urls[img.id]} target="_blank" rel="noreferrer" title={img.nom}>
              <img src={urls[img.id]} alt={img.nom} className="h-20 w-20 rounded-lg border border-slate-200 object-cover hover:opacity-80" /></a>
      ))}
    </div>
  );
}

// Évaluation par étoiles (1 à 5) + commentaire ; « envoyer({note, commentaire}) » fait l'appel au serveur
export function Evaluation({ requete, envoyer, onFait }) {
  const [note, setNote] = useState(0);
  const [commentaire, setCommentaire] = useState("");
  const valider = async () => {
    const attente = toast.loading("Patientez…");
    try {
      await envoyer({ note, commentaire });
      toast.success("Merci pour votre évaluation", { id: attente });
      onFait();
    } catch (e) { toast.error(erreur(e, "Évaluation non enregistrée"), { id: attente }); }
  };
  return (
    <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs" data-testid={`evaluer-${requete.numero}`}>
      <p className="font-semibold text-amber-900">Votre avis sur le traitement de cette requête :</p>
      <div className="my-1 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" onClick={() => setNote(n)} aria-label={`${n} sur 5`}>
            <Star className={`h-5 w-5 ${n <= note ? "fill-amber-400 text-amber-500" : "text-slate-300"}`} /></button>
        ))}
      </div>
      <input value={commentaire} onChange={(e) => setCommentaire(e.target.value)} placeholder="Commentaire (facultatif)"
        className="w-full rounded border border-slate-300 px-2 py-1" />
      <button type="button" disabled={!note} onClick={valider} className="mt-1 rounded bg-amber-600 px-3 py-1 font-semibold text-white disabled:opacity-40">Envoyer mon évaluation</button>
    </div>
  );
}
