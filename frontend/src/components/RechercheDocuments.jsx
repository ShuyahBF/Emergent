// RechercheDocuments.jsx — Lot 451 : RECHERCHE PLEIN TEXTE dans les rapports, suivis, notes et tâches, depuis le tableau de bord du portail.
// On tape un mot ou une expression : la liste montre chaque document où il apparaît (type, date et heure, extrait, auteur).
// Un clic sur une ligne ouvre le document dans une fenêtre de LECTURE SEULE (rien n'y est modifiable).
// Pour un développeur WinDev : un champ de recherche + une table mémoire remplie par le serveur + une fenêtre fille en consultation.
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import { Search, X, Loader2, FileText, ClipboardList, StickyNote, ListChecks, Eye, CheckSquare, Square, Lock } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useTri } from "@/lib/tri";
import ThTri from "@/components/ThTri";
import { nettoyerHtml } from "@/lib/htmlLectureSeule";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";

// Un pictogramme et une couleur par type de document (jamais la couleur seule : le libellé est toujours écrit)
const TYPES = {
  reports: { libelle: "Rapport", Icone: FileText, classe: "bg-blue-50 text-blue-800 ring-blue-200" },
  suivis: { libelle: "Suivi", Icone: ClipboardList, classe: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
  notes: { libelle: "Note", Icone: StickyNote, classe: "bg-purple-50 text-purple-800 ring-purple-200" },
  tasks: { libelle: "Tâche", Icone: ListChecks, classe: "bg-amber-50 text-amber-900 ring-amber-200" },
};

/** « 19/11/2026 14:05 » (date et heure courtes, en français) ; « — » si la date manque. */
export function dateHeure(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

function Pastille({ kind }) {
  const t = TYPES[kind] || { libelle: kind, Icone: FileText, classe: "bg-slate-50 text-slate-700 ring-slate-200" };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${t.classe}`}>
      <t.Icone className="h-3.5 w-3.5" aria-hidden="true" /> {t.libelle}
    </span>
  );
}

/**
 * typesVisibles : types de documents proposés sur ce tableau de bord (les rapports et les suivis peuvent y être masqués par le réglage du portail).
 */
export default function RechercheDocuments({ typesVisibles = ["reports", "suivis", "notes", "tasks"] }) {
  const [saisie, setSaisie] = useState("");
  const [enCours, setEnCours] = useState(false);
  const [reponse, setReponse] = useState(null);          // dernière réponse du serveur (null = aucune recherche faite)
  const [ouvert, setOuvert] = useState(null);            // ligne dont on lit le contenu
  const [document, setDocument] = useState(null);        // contenu complet lu à l'ouverture
  const [lecture, setLecture] = useState(false);

  // Tri des colonnes (règle 19) : texte sans accents, date dans l'ordre du temps
  const resultats = reponse?.resultats || [];
  const { lignes, tri, basculer } = useTri(resultats, {
    type: (l) => l.type,
    date: (l) => l.cree_le || "",
    extrait: (l) => `${l.titre} ${l.extrait.avant}${l.extrait.trouve}${l.extrait.apres}`,
    auteur: (l) => l.auteur,
  });

  const chercher = async () => {
    const texte = saisie.trim();
    if (texte.length < 2) { toast.error("Saisissez au moins 2 caractères à chercher."); return; }
    if (enCours) { toast("Recherche déjà en cours… patientez."); return; }        // un second clic ne relance pas la recherche
    setEnCours(true);
    const attente = toast.loading(`Recherche de « ${texte} » en cours…`);
    try {
      const { data } = await apiClient.get("/me/recherche-documents", { params: { q: texte, types: typesVisibles.join(",") } });
      setReponse(data);
      const coupe = data.tronque?.length ? ` (liste limitée aux 50 plus récents pour : ${data.tronque.join(", ")})` : "";
      toast.success(data.total ? `${data.total} document(s) trouvé(s) pour « ${data.q} »${coupe}.` : `Aucun document ne contient « ${data.q} ».`, { id: attente });
    } catch (e) {
      toast.error(e?.response?.data?.detail || "La recherche n'a pas abouti. Réessayez.", { id: attente });
    } finally {
      setEnCours(false);
    }
  };

  const effacer = () => { setSaisie(""); setReponse(null); };

  // Ouvre un résultat : le contenu complet est lu à ce moment-là (la liste ne transporte que des extraits)
  const ouvrir = async (ligne) => {
    setOuvert(ligne); setDocument(null); setLecture(true);
    try {
      const { data } = await apiClient.get(`/me/recherche-documents/${ligne.kind}/${ligne.id}`);
      setDocument(data);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Ce document n'a pas pu être ouvert.");
      setOuvert(null);
    } finally {
      setLecture(false);
    }
  };

  const contenuPropre = useMemo(() => nettoyerHtml(document?.content_html), [document]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5 space-y-3" data-testid="recherche-documents">
      <h2 className="font-display font-semibold flex items-center gap-2 text-slate-900">
        <Search className="h-4 w-4 text-sawali-blue" /> Rechercher dans mes rapports, suivis, notes et tâches
      </h2>
      {/* Champ + actions (chacune avec son pictogramme et sa légende) */}
      <form className="flex flex-wrap items-center gap-2 boutons-distincts" onSubmit={(e) => { e.preventDefault(); chercher(); }}>
        <div className="relative flex-1 min-w-[14rem]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
          <input
            type="search" value={saisie} onChange={(e) => setSaisie(e.target.value)} maxLength={80}
            placeholder="groupe électrogène" aria-label="Texte à chercher"
            className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm focus:border-sawali-blue focus:outline-none focus:ring-2 focus:ring-sawali-blue/30"
            data-testid="recherche-documents-champ"
          />
        </div>
        <button type="submit" disabled={enCours}
                className="inline-flex items-center gap-2 rounded-lg bg-sawali-blue px-4 py-2 text-sm font-semibold text-white hover:bg-sawali-blue-light disabled:opacity-60"
                data-testid="recherche-documents-lancer">
          {enCours ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} {enCours ? "Recherche…" : "Rechercher"}
        </button>
        <button type="button" onClick={effacer} disabled={enCours || (!saisie && !reponse)}
                className="inline-flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50"
                data-testid="recherche-documents-effacer">
          <X className="h-4 w-4" /> Effacer
        </button>
      </form>
      <p className="text-xs text-slate-500">La recherche ne tient compte ni des majuscules ni des accents. Elle porte sur le titre, le contenu, la liste des tâches, les étiquettes et le numéro, parmi les documents que vous avez le droit de voir.</p>

      {reponse && reponse.total === 0 && (
        <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600" data-testid="recherche-documents-vide">Aucun document ne contient « {reponse.q} ».</p>
      )}

      {reponse && reponse.total > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-slate-700">
            <b className="text-sawali-blue">{reponse.total}</b> document(s) pour « <b>{reponse.q}</b> ».
            {reponse.tronque?.length > 0 && <span className="ml-1 text-amber-700">⚠ Liste limitée aux 50 plus récents pour : {reponse.tronque.join(", ")}. Précisez votre recherche.</span>}
          </p>
          <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
            <table className="w-full text-sm" data-testid="recherche-documents-tableau">
              <thead className="bg-slate-50 text-left text-slate-700">
                <tr>
                  <ThTri cle="type" tri={tri} onTri={basculer}>Type</ThTri>
                  <ThTri cle="date" tri={tri} onTri={basculer}>Date / Heure</ThTri>
                  <ThTri cle="extrait" tri={tri} onTri={basculer}>Document et extrait</ThTri>
                  <ThTri cle="auteur" tri={tri} onTri={basculer}>Créé par</ThTri>
                  <th className="p-2"><span className="sr-only">Ouvrir</span></th>
                </tr>
              </thead>
              <tbody>
                {lignes.map((l) => (
                  <tr key={`${l.kind}-${l.id}`} onClick={() => ouvrir(l)} className="cursor-pointer border-t border-slate-100 align-top"
                      data-testid={`recherche-documents-ligne-${l.id}`}>
                    <td className="p-2 whitespace-nowrap"><Pastille kind={l.kind} /></td>
                    <td className="p-2 whitespace-nowrap text-orange-700">{dateHeure(l.cree_le)}</td>
                    <td className="p-2 min-w-[16rem]">
                      <div className="font-semibold text-slate-900">
                        {l.numero && <span className="mr-1 text-sawali-blue">{l.numero}</span>}{l.titre || "(sans titre)"}
                        {l.occurrences > 1 && <span className="ml-2 whitespace-nowrap rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-normal text-slate-600">{l.occurrences} occurrences</span>}
                      </div>
                      <div className="text-slate-600">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">{l.champ} : </span>
                        {l.extrait.avant}<mark className="rounded bg-yellow-200 px-0.5 font-semibold text-slate-900">{l.extrait.trouve}</mark>{l.extrait.apres}
                      </div>
                    </td>
                    <td className="p-2 whitespace-nowrap text-slate-700">{l.auteur || "—"}</td>
                    <td className="p-2 text-right">
                      <button type="button" onClick={(e) => { e.stopPropagation(); ouvrir(l); }} title="Lire ce document" aria-label={`Lire ${l.type} ${l.titre}`}
                              className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-sawali-blue text-white hover:bg-sawali-blue-light">
                        <Eye className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Fenêtre de LECTURE SEULE : dimensions de la règle 11, défilement dans la fenêtre, aucun champ modifiable */}
      <Dialog open={!!ouvert} onOpenChange={(o) => { if (!o) { setOuvert(null); setDocument(null); } }}>
        <DialogContent className="max-w-xl max-h-[85dvh] overflow-y-auto" data-testid="recherche-documents-lecture">
          <DialogHeader>
            <DialogTitle className="flex flex-wrap items-center gap-2 pr-6 text-left">
              {ouvert && <Pastille kind={ouvert.kind} />}
              <span>{ouvert?.numero && <span className="mr-1 text-sawali-blue">{ouvert.numero}</span>}{ouvert?.titre || "(sans titre)"}</span>
            </DialogTitle>
            <DialogDescription className="text-left">
              Créé le <b className="text-orange-700">{dateHeure(ouvert?.cree_le)}</b> par <b className="text-slate-800">{ouvert?.auteur || "—"}</b>
              <span className="ml-2 inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600"><Lock className="h-3 w-3" /> lecture seule</span>
            </DialogDescription>
          </DialogHeader>
          {lecture && <p className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Patientez… lecture du document</p>}
          {document && (
            <div className="space-y-3 text-sm">
              {document.event_date && <p className="text-slate-700">Date de l'événement : <b>{document.event_date}</b></p>}
              {contenuPropre
                ? <div className="prose prose-sm prose-sawali max-w-none" dangerouslySetInnerHTML={{ __html: contenuPropre }} />
                : <p className="italic text-slate-400">Aucun contenu rédigé.</p>}
              {Array.isArray(document.task_items) && document.task_items.length > 0 && (
                <ul className="space-y-1" data-testid="recherche-documents-liste-tache">
                  {document.task_items.map((it, i) => (
                    <li key={it.id || i} className="flex items-start gap-2">
                      {it.done ? <CheckSquare className="mt-0.5 h-4 w-4 text-emerald-600" aria-label="fait" /> : <Square className="mt-0.5 h-4 w-4 text-slate-400" aria-label="à faire" />}
                      <span className={it.done ? "text-slate-500 line-through" : "text-slate-800"}>{it.text}</span>
                    </li>
                  ))}
                </ul>
              )}
              {document.voice_note_transcript && (
                <p className="rounded-lg bg-slate-50 p-2 text-slate-700"><b>Note vocale (transcription) :</b> {document.voice_note_transcript}</p>
              )}
              {Array.isArray(document.tags) && document.tags.length > 0 && (
                <p className="flex flex-wrap gap-1">{document.tags.map((t) => <span key={t} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">#{t}</span>)}</p>
              )}
              {document.nb_images > 0 && <p className="text-xs text-slate-500">{document.nb_images} image(s) jointe(s) : visibles dans la page du document.</p>}
            </div>
          )}
          <DialogFooter>
            <button type="button" onClick={() => { setOuvert(null); setDocument(null); }}
                    className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700"
                    data-testid="recherche-documents-fermer">
              <X className="h-4 w-4" /> Fermer
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
