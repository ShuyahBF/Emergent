// Demandes à SAWALI : fenêtre MODALE de détails (règle 20 : les détails d'une ligne s'ouvrent en modale, jamais en allongeant la page).
// Une demande est souvent très longue : le tableau n'en montre que les 20 premiers caractères (`apercu`) ; ce bouton « Détails » ouvre la demande COMPLÈTE.
import React, { useState } from "react";
import { Eye, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** Les 20 premiers caractères d'une demande (espaces réduits), suivis de « … » si elle est plus longue. */
export const apercu = (texte, n = 20) => {
  const t = String(texte || "").replace(/\s+/g, " ").trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
};

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const fmtJour = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : "—");

/** Cellule « Demande » : aperçu de 20 caractères + bouton « Détails » (pictogramme œil + légende) qui ouvre la fenêtre. */
export default function DetailDemandeModal({ d }) {
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
