// Demandes à SAWALI : fenêtre MODALE de détails (règle 20 : les détails d'une ligne s'ouvrent en modale, jamais en allongeant la page).
// Une demande est souvent très longue : le tableau n'en montre que les 20 premiers caractères (`apercu`) ; ce bouton « Détails » ouvre la demande COMPLÈTE.
import React, { useState } from "react";
import { Eye, FileText, Image as ImageIcone, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** Les 20 premiers caractères d'une demande (espaces réduits), suivis de « … » si elle est plus longue. */
export const apercu = (texte, n = 20) => {
  const t = String(texte || "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
};

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const fmtJour = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : "—");

const taille = (o) => (o < 1024 ? `${o} o` : `${Math.round(o / 1024)} Ko`);

/** Pièces jointes (lot 430) : chaque pièce se charge À LA DEMANDE (jamais toutes d'un coup) ; image affichée dans la fenêtre, PDF ouvert dans un nouvel onglet. */
export function PiecesLecture({ d, chargerPiece }) {
  const [images, setImages] = useState({});                   // id → adresse temporaire
  const [occupe, setOccupe] = useState(null);
  const ouvrir = async (p) => {
    setOccupe(p.id);
    try {
      const blob = await chargerPiece(d, p);
      const url = URL.createObjectURL(blob);
      if (p.type === "application/pdf") window.open(url, "_blank", "noopener"); else setImages((x) => ({ ...x, [p.id]: url }));
    } catch { /* l'erreur est montrée par le parent (toast) */ } finally { setOccupe(null); }
  };
  return (
    <div data-testid="pieces-lecture">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">Pièces jointes ({d.pieces.length})</p>
      <ul className="space-y-2">
        {d.pieces.map((p) => (
          <li key={p.id} className="rounded border p-2 text-sm">
            <div className="flex items-center gap-2">
              {p.type === "application/pdf" ? <FileText className="h-4 w-4 text-red-700" aria-hidden="true" /> : <ImageIcone className="h-4 w-4 text-sky-700" aria-hidden="true" />}
              <span className="min-w-0 flex-1 truncate" title={p.nom}>{p.nom}</span><span className="text-xs tabular-nums text-muted-foreground">{taille(p.taille)}</span>
              {!images[p.id] && <Button size="sm" variant="outline" disabled={occupe === p.id} onClick={() => ouvrir(p)}><Eye className="w-4 h-4 mr-1" aria-hidden="true" />{occupe === p.id ? "Chargement…" : p.type === "application/pdf" ? "Ouvrir" : "Voir"}</Button>}
            </div>
            {images[p.id] && <img src={images[p.id]} alt={p.nom} className="mt-2 max-h-80 w-full rounded object-contain" />}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Cellule « Demande » : aperçu de 20 caractères + bouton « Détails » (pictogramme œil + légende) qui ouvre la fenêtre. `chargerPiece(d, piece)` → Promise<Blob> (lot 430). */
export default function DetailDemandeModal({ d, chargerPiece }) {
  const [ouvert, setOuvert] = useState(false);
  return (
    <>
      <div className="flex items-center gap-2">
        <span className="break-words" data-testid={`apercu-${d.id}`}>{apercu(d.texte)}</span>
        <Button size="sm" variant="outline" className="shrink-0 border-sky-400 text-sky-800" onClick={() => setOuvert(true)} data-testid={`details-${d.id}`}>
          <Eye className="w-4 h-4 mr-1" /> Détails
        </Button>
      </div>
      <Dialog open={ouvert} onOpenChange={setOuvert}>
        <DialogContent className="max-w-xl max-h-[85dvh] overflow-y-auto" data-testid="modale-detail-demande">
          <DialogHeader><DialogTitle>Demande {d.numero_sawali || ""} {d.plateforme ? `· ${d.plateforme}` : ""}</DialogTitle></DialogHeader>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Type</dt><dd>{d.type_libelle || d.type || "—"}</dd>
            <dt className="text-muted-foreground">Demandée le</dt><dd>{fmt(d.demandee_le)}</dd>
            <dt className="text-muted-foreground">Statut</dt><dd className="font-medium">{d.statut_libelle || d.statut || "—"}</dd>
            {d.realisee_le && (<><dt className="text-muted-foreground">Réalisée le</dt><dd>{fmtJour(d.realisee_le)}</dd></>)}
            {d.prevue_le && !d.realisee_le && (<><dt className="text-muted-foreground">Prévue le</dt><dd>{fmtJour(d.prevue_le)}</dd></>)}
          </dl>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">Demande complète</p>
            <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm" data-testid="detail-demande-texte">{d.texte}</p>
          </div>
          {Array.isArray(d.pieces) && d.pieces.length > 0 && chargerPiece && <PiecesLecture d={d} chargerPiece={chargerPiece} />}
          {d.alerte_pieces && <p className="rounded bg-amber-50 p-2 text-sm text-amber-900">⚠ {d.alerte_pieces}</p>}
          {d.commentaire && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">Commentaire de SAWALI</p>
              <p className="whitespace-pre-wrap rounded-lg bg-sky-50 p-3 text-sm">{d.commentaire}</p>
            </div>
          )}
          <div className="flex justify-end"><Button variant="outline" onClick={() => setOuvert(false)}><X className="w-4 h-4 mr-1" /> Fermer</Button></div>
        </DialogContent>
      </Dialog>
    </>
  );
}
