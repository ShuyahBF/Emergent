// Téléchargement d'un fichier AVEC fenêtre d'enregistrement (lieu de stockage et nom au choix), au lieu de l'ouvrir dans le navigateur.
// Demande du propriétaire (06/11/2026) : le lien d'un document (PDF reçu par WhatsApp, document d'un formulaire…) ne doit plus ouvrir directement
// le PDF ; il ouvre la fenêtre « Enregistrer sous ».
//   1) Chrome / Edge (ordinateur) : fenêtre « Enregistrer sous » du système (dossier + nom), via showSaveFilePicker ;
//   2) autres navigateurs : téléchargement avec le nom proposé (le navigateur demande l'emplacement si son réglage
//      « Demander où enregistrer chaque fichier » est activé) ;
//   3) si le fichier ne peut pas être lu par le navigateur (blocage du serveur) : ouverture dans un nouvel onglet, en dernier recours.
import { toast } from "sonner";

// Type MIME courant selon l'extension (pour le filtre de la fenêtre « Enregistrer sous »)
const TYPES = {
  pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp", txt: "text/plain", csv: "text/csv",
  zip: "application/zip", doc: "application/msword", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xls: "application/vnd.ms-excel", xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

// Nom de fichier sûr : retire les caractères interdits sous Windows
const nomSur = (nom) => (nom || "document").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").slice(0, 150);

export async function telechargerFichier(url, nomSuggere) {
  const nom = nomSur(nomSuggere || decodeURIComponent((url.split("?")[0].split("/").pop() || "document")));
  const ext = (nom.split(".").pop() || "").toLowerCase();
  const t = toast.loading("Patientez… préparation du fichier");
  try {
    const rep = await fetch(url);
    if (!rep.ok) throw new Error(`HTTP ${rep.status}`);
    const blob = await rep.blob();
    toast.dismiss(t);
    // 1) Fenêtre « Enregistrer sous » du système (dossier + nom au choix)
    if (typeof window.showSaveFilePicker === "function") {
      try {
        const poignee = await window.showSaveFilePicker({
          suggestedName: nom,
          ...(TYPES[ext] ? { types: [{ description: ext.toUpperCase(), accept: { [TYPES[ext]]: [`.${ext}`] } }] } : {}),
        });
        const flux = await poignee.createWritable();
        await flux.write(blob);
        await flux.close();
        toast.success("Fichier enregistré.");
        return;
      } catch (e) {
        if (e?.name === "AbortError") return;   // l'utilisateur a fermé la fenêtre : rien à faire
        // autre erreur (ex. fenêtre refusée par le navigateur) : on passe au téléchargement classique
      }
    }
    // 2) Téléchargement classique avec le nom proposé
    const objet = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objet; a.download = nom; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(objet), 60000);
  } catch {
    // 3) Lecture impossible par le navigateur : ouverture dans un nouvel onglet
    toast.dismiss(t);
    toast.message("Téléchargement direct impossible : le fichier s'ouvre dans un nouvel onglet.");
    window.open(url, "_blank", "noopener");
  }
}
