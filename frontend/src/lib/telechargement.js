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

// ---------------------------------------------------------------------------------------------------------------------
// Nom proposé pour un document reçu ou envoyé dans une conversation : EXPÉDITEUR_AAAA-MM-JJ_HHhMM[_nom d'origine].extension
// Demande du propriétaire (06/11/2026) : les PDF reçus par WhatsApp s'appellent tous « wa-inbound.pdf » ; on y met l'expéditeur et la date.
//   - le nom d'origine n'est ajouté que s'il est parlant (pas « wa-inbound… », « document », « file »…) ;
//   - date et heure en heure locale du navigateur ; extension reprise du nom d'origine, sinon du type MIME, sinon « .pdf ».
const NOMS_GENERIQUES = /^(wa-inbound|wa_inbound|document|file|fichier|media|attachment)([-_ ()0-9]*)$/i;
const EXT_PAR_MIME = {
  "application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "text/plain": "txt", "text/csv": "csv",
  "application/zip": "zip", "application/msword": "doc", "application/vnd.ms-excel": "xls",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
};

export function nomDocumentConversation({ expediteur, dateIso, nomOrigine, mime }) {
  const pointe = (nomOrigine || "").lastIndexOf(".");
  const base = pointe > 0 ? nomOrigine.slice(0, pointe) : (nomOrigine || "");
  const extOrigine = pointe > 0 ? nomOrigine.slice(pointe + 1).toLowerCase() : "";
  const ext = /^[a-z0-9]{1,5}$/.test(extOrigine) ? extOrigine : (EXT_PAR_MIME[(mime || "").toLowerCase()] || "pdf");
  const exp = (expediteur || "").trim().replace(/\s+/g, "_");
  const d = dateIso ? new Date(dateIso) : null;
  const pad = (n) => String(n).padStart(2, "0");
  const date = d && !Number.isNaN(d.getTime()) ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}h${pad(d.getMinutes())}` : "";
  const parlant = base.trim() && !NOMS_GENERIQUES.test(base.trim()) ? base.trim().replace(/\s+/g, "_") : "";
  const parties = [exp, date, parlant].filter(Boolean);
  return `${parties.length ? parties.join("_") : "document"}.${ext}`;
}
