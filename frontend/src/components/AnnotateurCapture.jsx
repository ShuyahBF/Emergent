// ============================================================================
// Lot 465 — Fenêtre d'ANNOTATION d'une capture d'écran collée dans un suivi (Ctrl + V), avant son insertion et l'enregistrement du suivi.
// Outils : crayon, flèche, cadre, ovale, surligneur, texte, masquer (cache une donnée sensible : nom, numéro, montant…). Couleurs, 3 épaisseurs,
// annuler / rétablir (Ctrl + Z / Ctrl + Y), « Effacer les annotations ». « Insérer dans le suivi » rend l'image (PNG) à l'écran appelant, qui la téléverse.
// Fonctionnement : l'image de départ est dessinée sur un canevas, puis chaque forme mémorisée dans une liste (`formes`) ; annuler = retirer la dernière forme
// de la liste et tout redessiner. Les calculs et le dessin sont dans `lib/annotationCapture.js`.
// Fenêtre un peu plus large qu'une modale ordinaire (max-w-3xl) : besoin réel (aperçu d'une image à annoter) ; hauteur 90 % de l'écran, défilement DANS la fenêtre.
// ============================================================================
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Check, Circle, Eraser, EyeOff, Highlighter, MoveUpRight, Pencil, Redo2, Square, Type, Undo2, X } from "lucide-react";
import { toast } from "sonner";
import { COULEURS, EPAISSEURS, dessinerFormes, tailleExport } from "@/lib/annotationCapture";

const OUTILS = [
  { cle: "fleche", nom: "Flèche", Icone: MoveUpRight, aide: "Glisser pour tracer une flèche vers l'élément à montrer" },
  { cle: "cadre", nom: "Cadre", Icone: Square, aide: "Glisser pour entourer une zone d'un cadre" },
  { cle: "ovale", nom: "Ovale", Icone: Circle, aide: "Glisser pour entourer une zone d'un ovale" },
  { cle: "crayon", nom: "Crayon", Icone: Pencil, aide: "Dessiner à main levée" },
  { cle: "surligneur", nom: "Surligner", Icone: Highlighter, aide: "Glisser pour surligner une zone (translucide)" },
  { cle: "texte", nom: "Texte", Icone: Type, aide: "Cliquer à l'endroit voulu puis écrire, Entrée pour valider" },
  { cle: "masquer", nom: "Masquer", Icone: EyeOff, aide: "Glisser pour cacher une donnée sensible (rectangle noir)" },
];

export default function AnnotateurCapture({ fichier, largeurMax, envoi = false, onInserer, onFermer }) {
  const canevasRef = useRef(null);
  const enveloppeRef = useRef(null);
  const imageRef = useRef(null);
  const [pret, setPret] = useState(false);
  const [formes, setFormes] = useState([]);              // formes validées (annulables)
  const [refaire, setRefaire] = useState([]);            // formes annulées (rétablissables)
  const [enCours, setEnCours] = useState(null);          // forme en train d'être tracée
  const [outil, setOutil] = useState("fleche");
  const [couleur, setCouleur] = useState(COULEURS[0].valeur);
  const [epaisseur, setEpaisseur] = useState(EPAISSEURS[1].valeur);
  const [saisie, setSaisie] = useState(null);            // { x, y (canevas), gauche, haut (écran), valeur } : zone de texte en cours

  // --- chargement de l'image collée, taille du canevas (réduite si trop large, jamais agrandie) ---
  useEffect(() => {
    const url = URL.createObjectURL(fichier);
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      const t = tailleExport(img.naturalWidth, img.naturalHeight, largeurMax);
      const c = canevasRef.current;
      if (c) { c.width = t.largeur; c.height = t.hauteur; }
      setPret(true);
    };
    img.onerror = () => { toast.error("Image illisible : collez une capture au format PNG ou JPEG."); onFermer(); };
    img.src = url;
    return () => URL.revokeObjectURL(url);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fichier]);

  // --- redessin complet : image de départ + formes validées + forme en cours ---
  const redessiner = useCallback(() => {
    const c = canevasRef.current;
    if (!c || !imageRef.current) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(imageRef.current, 0, 0, c.width, c.height);
    dessinerFormes(ctx, enCours ? [...formes, enCours] : formes);
  }, [formes, enCours]);
  useEffect(() => { if (pret) redessiner(); }, [pret, redessiner]);

  // --- point du canevas sous la souris / le doigt (le canevas est affiché réduit : on remet à l'échelle) ---
  const point = (e) => {
    const c = canevasRef.current, r = c.getBoundingClientRect();
    return { x: ((e.clientX - r.left) * c.width) / r.width, y: ((e.clientY - r.top) * c.height) / r.height };
  };
  const epaisseurReelle = () => epaisseur * Math.max(1, (canevasRef.current?.width || 900) / 900);   // trait proportionnel à la taille de l'image

  const valider = (forme) => { setFormes((l) => [...l, forme]); setRefaire([]); };
  const validerTexte = () => {
    if (saisie && saisie.valeur.trim()) valider({ type: "texte", couleur, epaisseur: epaisseurReelle(), x1: saisie.x, y1: saisie.y, texte: saisie.valeur.trim() });
    setSaisie(null);
  };

  const appui = (e) => {
    if (!pret || envoi) return;
    if (saisie) validerTexte();
    const p = point(e);
    if (outil === "texte") {
      const env = enveloppeRef.current.getBoundingClientRect();
      setSaisie({ x: p.x, y: p.y, gauche: e.clientX - env.left + enveloppeRef.current.scrollLeft, haut: e.clientY - env.top + enveloppeRef.current.scrollTop, valeur: "" });
      e.preventDefault();
      return;
    }
    e.currentTarget.setPointerCapture?.(e.pointerId);
    const base = { type: outil, couleur, epaisseur: epaisseurReelle() };
    setEnCours(outil === "crayon" ? { ...base, points: [p] } : { ...base, x1: p.x, y1: p.y, x2: p.x, y2: p.y });
  };
  const deplacement = (e) => {
    if (!enCours) return;
    const p = point(e);
    setEnCours((f) => (f.type === "crayon" ? { ...f, points: [...f.points, p] } : { ...f, x2: p.x, y2: p.y }));
  };
  const relache = () => {
    if (!enCours) return;
    const f = enCours;
    setEnCours(null);
    const trivial = f.type !== "crayon" && Math.hypot(f.x2 - f.x1, f.y2 - f.y1) < 4;          // simple clic sans glisser : rien à dessiner
    if (!trivial) valider(f);
  };

  // annuler = la dernière forme passe dans la pile « à rétablir » ; rétablir = l'inverse (on lit l'état courant : aucun effet de bord dans les fonctions de mise à jour)
  const annuler = () => { if (!formes.length) return; setRefaire([...refaire, formes[formes.length - 1]]); setFormes(formes.slice(0, -1)); };
  const retablir = () => { if (!refaire.length) return; setFormes([...formes, refaire[refaire.length - 1]]); setRefaire(refaire.slice(0, -1)); };
  const toutEffacer = () => { setFormes([]); setRefaire([]); setSaisie(null); };

  // --- clavier : Ctrl+Z, Ctrl+Y, Échap ---
  useEffect(() => {
    const touche = (e) => {
      if (saisie) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); annuler(); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); retablir(); }
      else if (e.key === "Escape" && !envoi) onFermer();
    };
    window.addEventListener("keydown", touche);
    return () => window.removeEventListener("keydown", touche);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formes, refaire, onFermer, saisie, envoi]);

  const inserer = () => {
    if (saisie) validerTexte();
    // le redessin est déjà à jour (aucune forme en cours) : on exporte le canevas tel quel
    canevasRef.current.toBlob((blob) => { if (blob) onInserer(blob); else toast.error("Export de la capture impossible"); }, "image/png");
  };

  const Bouton = ({ actif, onClick, titre, disabled, children, ...reste }) => (
    <button type="button" onClick={onClick} title={titre} disabled={disabled} aria-pressed={actif}
      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-semibold disabled:opacity-40 ${actif ? "border-sky-600 bg-sky-50 text-sky-800" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"}`} {...reste}>{children}</button>
  );

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-3" role="dialog" aria-modal="true" aria-label="Annoter la capture d'écran" data-testid="annotateur-capture">
      <div className="w-full max-w-3xl max-h-[90dvh] overflow-y-auto rounded-2xl bg-white p-4 space-y-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-bold">Annoter la capture d'écran</h2>
            <p className="text-xs text-slate-600">Entourez, montrez ou masquez ce qui compte, puis « Insérer dans le suivi » : la capture annotée est ajoutée au contenu, avant l'enregistrement.</p>
          </div>
          <button type="button" onClick={onFermer} disabled={envoi} aria-label="Fermer sans insérer" title="Fermer sans insérer" className="rounded-full p-1 text-slate-500 hover:bg-slate-100 disabled:opacity-40"><X className="h-5 w-5" /></button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5" data-testid="annotateur-outils">
          {OUTILS.map(({ cle, nom, Icone, aide }) => (
            <Bouton key={cle} actif={outil === cle} onClick={() => setOutil(cle)} titre={aide} data-testid={`outil-${cle}`}><Icone className="h-4 w-4" /> {nom}</Bouton>))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1" role="group" aria-label="Couleur">
            {COULEURS.map((c) => (
              <button key={c.valeur} type="button" onClick={() => setCouleur(c.valeur)} aria-label={c.nom} aria-pressed={couleur === c.valeur} title={c.nom} data-testid={`couleur-${c.nom}`}
                className={`h-6 w-6 rounded-full border-2 ${couleur === c.valeur ? "border-slate-900 ring-2 ring-sky-300" : "border-white ring-1 ring-slate-300"}`} style={{ background: c.valeur }} />))}
          </div>
          <div className="flex items-center gap-1" role="group" aria-label="Épaisseur">
            {EPAISSEURS.map((ep) => (
              <Bouton key={ep.nom} actif={epaisseur === ep.valeur} onClick={() => setEpaisseur(ep.valeur)} titre={`Trait ${ep.nom.toLowerCase()}`}>
                <span className="inline-block w-5 rounded bg-slate-800" style={{ height: Math.max(2, ep.valeur / 2) }} /> {ep.nom}</Bouton>))}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <Bouton onClick={annuler} disabled={!formes.length} titre="Annuler la dernière annotation (Ctrl + Z)" data-testid="annotateur-annuler"><Undo2 className="h-4 w-4" /> Annuler</Bouton>
            <Bouton onClick={retablir} disabled={!refaire.length} titre="Rétablir (Ctrl + Y)" data-testid="annotateur-retablir"><Redo2 className="h-4 w-4" /> Rétablir</Bouton>
            <Bouton onClick={toutEffacer} disabled={!formes.length && !refaire.length} titre="Effacer toutes les annotations" data-testid="annotateur-effacer"><Eraser className="h-4 w-4" /> Effacer les annotations</Bouton>
          </div>
        </div>

        <div ref={enveloppeRef} className="relative max-h-[55dvh] overflow-auto rounded-lg border border-slate-300 bg-slate-100">
          {!pret && <p className="p-6 text-sm text-slate-500">Patientez… chargement de la capture</p>}
          <canvas ref={canevasRef} onPointerDown={appui} onPointerMove={deplacement} onPointerUp={relache} onPointerCancel={relache} data-testid="annotateur-canevas"
            className={`block h-auto w-full ${outil === "texte" ? "cursor-text" : "cursor-crosshair"} ${pret ? "" : "hidden"}`} style={{ touchAction: "none" }} />
          {saisie && (
            <input autoFocus value={saisie.valeur} onChange={(e) => setSaisie({ ...saisie, valeur: e.target.value })} onBlur={validerTexte} data-testid="annotateur-texte"
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); validerTexte(); } else if (e.key === "Escape") { e.stopPropagation(); setSaisie(null); } }}
              placeholder="Écrire puis Entrée" className="absolute rounded border-2 px-1 text-sm font-bold shadow" style={{ left: saisie.gauche, top: saisie.haut, borderColor: couleur, color: couleur, minWidth: 140 }} />)}
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 boutons-distincts">
          <button type="button" onClick={onFermer} disabled={envoi} data-testid="annotateur-fermer" className="inline-flex items-center gap-1 rounded-full border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-50"><X className="h-4 w-4" /> Fermer sans insérer</button>
          <button type="button" onClick={inserer} disabled={!pret || envoi} data-testid="annotateur-inserer" className="inline-flex items-center gap-1 rounded-full bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"><Check className="h-4 w-4" /> {envoi ? "Patientez…" : "Insérer dans le suivi"}</button>
        </div>
      </div>
    </div>
  );
}
