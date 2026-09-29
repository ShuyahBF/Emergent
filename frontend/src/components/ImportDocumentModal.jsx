/*
  Lot 33 — « Créer depuis un document » (Formulaires et Sondages WhatsApp).

  On dépose un questionnaire existant : Word (.docx), Excel (.xlsx), PDF, ou les
  photos / images des pages imprimées (plusieurs d'un coup). Les photos sont réduites
  dans le navigateur et remises dans l'ordre des prises. Le serveur
  (POST /me/form-imports) en déduit la structure avec l'IA et crée un BROUILLON
  (formulaire : tableaux avec leurs colonnes, et leurs lignes si la case
  « Reprendre aussi les données des tableaux » est cochée) ;
  la fenêtre suit l'analyse (GET /me/form-imports/{id}), affiche le compte rendu
  (points à vérifier) puis ouvre le brouillon dans l'éditeur habituel.
*/
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { apiClient } from "@/lib/api";
import { estPhoto, reduirePhoto, triNaturel } from "@/lib/photos";

const ACCEPT = ".docx,.xlsx,.xlsm,.pdf,.jpg,.jpeg,.png,.webp,image/*";
const TEXTES = {
  formulaire: { titre: "Créer un formulaire depuis un document", objet: "le formulaire" },
  sondage: { titre: "Créer un sondage depuis un document", objet: "le sondage" },
};

// cible : "formulaire" | "sondage" ; lienEditeur(id) : page d'édition du brouillon créé.
export default function ImportDocumentModal({ cible, lienEditeur, onClose }) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [fichiers, setFichiers] = useState([]);
  const [avecDonnees, setAvecDonnees] = useState(false);   // formulaire : lignes des tableaux reprises ?
  const [etape, setEtape] = useState("choix");        // choix | analyse | termine | erreur
  const [job, setJob] = useState(null);
  const t = TEXTES[cible];

  // Suivi de l'analyse : toutes les 2 secondes jusqu'à « termine » ou « erreur ».
  useEffect(() => {
    if (etape !== "analyse" || !job?.id) return undefined;
    const minuterie = setInterval(async () => {
      try {
        const r = await apiClient.get(`/me/form-imports/${job.id}`);
        if (r.data.statut !== "en_cours") {
          setJob(r.data);
          setEtape(r.data.statut === "termine" ? "termine" : "erreur");
        }
      } catch { /* nouvelle tentative au prochain tour */ }
    }, 2000);
    return () => clearInterval(minuterie);
  }, [etape, job?.id]);

  // Choix des fichiers : photos triées par nom (ordre des prises), les autres gardent leur ordre.
  const choisir = (liste) => {
    const autres = liste.filter((f) => !estPhoto(f));
    setFichiers([...autres, ...liste.filter(estPhoto).sort(triNaturel)]);
  };

  const analyser = async () => {
    setEtape("analyse");
    try {
      const form = new FormData();
      form.append("cible", cible);
      if (cible === "formulaire") form.append("avec_donnees", avecDonnees ? "true" : "false");
      const prets = await Promise.all(fichiers.map((f) => (estPhoto(f) ? reduirePhoto(f) : f)));
      prets.forEach((f) => form.append("fichiers", f));
      const r = await apiClient.post("/me/form-imports", form);
      setJob(r.data);
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Dépôt impossible");
      setEtape("choix");
    }
  };

  const occupe = etape === "analyse";
  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4"
      onClick={() => !occupe && onClose()} data-testid="import-doc-modal">
      <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-display font-bold text-lg flex items-center gap-2">
            <FileUp className="h-5 w-5 text-sawali-blue" /> {t.titre}
          </h2>
          {!occupe && <button onClick={onClose} className="text-slate-400 hover:text-slate-900"><X className="h-4 w-4" /></button>}
        </div>

        {etape === "choix" && (<>
          <p className="text-sm text-slate-600">
            Déposez le questionnaire existant : <b>Word</b>, <b>Excel</b>, <b>PDF</b>, ou les <b>photos</b> des
            pages imprimées (plusieurs d'un coup, remises dans l'ordre des prises). L'IA en reprend les questions
            et crée {t.objet} en <b>brouillon</b>, à relire et modifier dans l'éditeur.
          </p>
          <div className="flex items-center gap-3 text-sm">
            <input ref={inputRef} type="file" multiple accept={ACCEPT} className="hidden" data-testid="import-doc-input"
              onChange={(e) => choisir(Array.from(e.target.files || []))} />
            <button type="button" onClick={() => inputRef.current?.click()} data-testid="import-doc-choisir"
              className="px-3 py-1.5 rounded-lg bg-slate-100 text-slate-700 hover:bg-slate-200">
              Choisir les fichiers
            </button>
            <span className="text-slate-500">{fichiers.length ? `${fichiers.length} fichier(s)` : "Aucun fichier choisi"}</span>
          </div>
          {cible === "formulaire" && (
            <label className="flex items-start gap-2 text-sm text-slate-700 bg-slate-50 ring-1 ring-slate-200 rounded-lg p-3">
              <input type="checkbox" className="mt-0.5" checked={avecDonnees} onChange={(e) => setAvecDonnees(e.target.checked)}
                data-testid="import-doc-avec-donnees" />
              <span>
                <b>Reprendre aussi les données des tableaux</b>
                <span className="block text-xs text-slate-500">
                  {avecDonnees
                    ? "Les lignes du document pré-rempliront les tableaux : il suffira de les confirmer ou de les corriger."
                    : "Décoché : seules les colonnes sont reprises, les tableaux sont vides et prêts à être remplis."}
                </span>
              </span>
            </label>
          )}
          {fichiers.length > 0 && (
            <ol className="text-xs text-slate-600 list-decimal pl-5 max-h-40 overflow-y-auto" data-testid="import-doc-liste">
              {fichiers.map((f) => <li key={f.name + f.size} className="truncate">{f.name}</li>)}
            </ol>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <button onClick={onClose} className="px-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-300 hover:bg-slate-50">Annuler</button>
            <button onClick={analyser} disabled={!fichiers.length} data-testid="import-doc-analyser"
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-sm font-semibold rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue-light disabled:opacity-50">
              <FileUp className="h-3.5 w-3.5" /> Analyser et créer
            </button>
          </div>
        </>)}

        {etape === "analyse" && (
          <p className="text-sm text-slate-600 flex items-center gap-2 py-6 justify-center" data-testid="import-doc-en-cours">
            <Loader2 className="h-4 w-4 animate-spin text-sawali-blue" />
            Lecture du document et création {cible === "formulaire" ? "du formulaire" : "du sondage"}… (jusqu'à une minute)
          </p>
        )}

        {etape === "termine" && job && (<>
          <p className="text-sm font-semibold text-emerald-700 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4" /> « {job.titre} » créé en brouillon
          </p>
          <div className="text-sm text-slate-700 whitespace-pre-line [overflow-wrap:anywhere] bg-slate-50 ring-1 ring-slate-200 rounded-lg p-3"
            data-testid="import-doc-compte-rendu">{job.compte_rendu}</div>
          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-300 hover:bg-slate-50">Fermer</button>
            <button onClick={() => navigate(lienEditeur(job.objet_id))} data-testid="import-doc-ouvrir"
              className="px-4 py-1.5 text-sm font-semibold rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue-light">
              Ouvrir dans l'éditeur
            </button>
          </div>
        </>)}

        {etape === "erreur" && job && (<>
          <p className="text-sm text-rose-700 bg-rose-50 ring-1 ring-rose-200 rounded-lg p-3" data-testid="import-doc-erreur">{job.erreur}</p>
          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="px-3 py-1.5 text-sm rounded-lg ring-1 ring-slate-300 hover:bg-slate-50">Fermer</button>
            <button onClick={() => { setJob(null); setEtape("choix"); }}
              className="px-4 py-1.5 text-sm font-semibold rounded-lg bg-sawali-blue text-white hover:bg-sawali-blue-light">
              Réessayer
            </button>
          </div>
        </>)}
      </div>
    </div>
  );
}
