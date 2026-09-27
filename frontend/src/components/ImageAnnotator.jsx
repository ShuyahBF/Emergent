/*
  ImageAnnotator — annoter une image AVANT de l'envoyer sur WhatsApp (lot 27).

  Ouvert depuis la conversation d'un contact (Centre de Messagerie), sur l'image
  jointe (trombone, capture collée avec Ctrl+V ou bouton « Coller »).

  Outils :
    - Flèche, Cercle (entourer une zone), Rectangle, Crayon (main levée),
      Surligneur (trait large transparent), Texte, Numéro (pastilles 1, 2, 3…
      pour indiquer des étapes) et Flouter (pixelise une zone : numéro de
      compte, visage, mot de passe…) ;
    - 6 couleurs, 3 épaisseurs ;
    - Annuler / Rétablir (Ctrl+Z / Ctrl+Y), Tout effacer.
  Les annotations sont gardées comme une liste de formes et l'image est
  redessinée à chaque changement : on peut donc annuler forme par forme.
  « Terminer » fusionne l'image et les annotations dans un nouveau fichier
  (JPEG, ou PNG si l'original était un PNG), qui remplace la pièce jointe.
  Fonctionne à la souris, au doigt et au stylet (événements « pointer »).
  Aucune dépendance : dessin sur <canvas> du navigateur.

  Props :
    file      — File/Blob de l'image à annoter
    onCancel  — () => void : fermeture sans rien changer
    onDone    — (File) => void : image annotée
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  MoveUpRight, Circle, Square, Pencil, Highlighter, Type, Hash, Grid3x3,
  Undo2, Redo2, Trash2, X, Check,
} from "lucide-react";

// Plus grand côté de l'image produite (au-delà, l'image est réduite :
// WhatsApp la recompresse de toute façon, et le fichier reste sous 16 Mo).
const MAX_SIDE = 2560;

// Outils : [clé, libellé, icône]
const TOOLS = [
  ["arrow", "Flèche", MoveUpRight],
  ["ellipse", "Cercle", Circle],
  ["rect", "Rectangle", Square],
  ["pen", "Crayon", Pencil],
  ["highlight", "Surligneur", Highlighter],
  ["text", "Texte", Type],
  ["number", "Numéro", Hash],
  ["blur", "Flouter", Grid3x3],
];

// Couleurs proposées (rouge par défaut : le plus visible sur une capture)
const COLORS = ["#ef4444", "#facc15", "#22c55e", "#3b82f6", "#111827", "#ffffff"];

// Dessine UNE forme sur le contexte `ctx`. `base` = canvas de l'image seule
// (sert à l'outil Flouter, qui pixelise l'image d'origine sous la zone).
function drawShape(ctx, s, base) {
  const w = s.width;
  ctx.save();
  ctx.strokeStyle = s.color;
  ctx.fillStyle = s.color;
  ctx.lineWidth = w;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (s.type === "pen" || s.type === "highlight") {
    // Trait à main levée ; le surligneur est large et transparent
    if (s.type === "highlight") {
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = w * 4;
      ctx.lineCap = "butt";
    }
    const pts = s.points || [];
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    if (pts.length === 1) ctx.lineTo(pts[0].x + 0.1, pts[0].y + 0.1);   // simple point
    ctx.stroke();
  } else if (s.type === "arrow") {
    // Trait + pointe triangulaire pleine au point d'arrivée
    const { x: x1, y: y1 } = s.p1;
    const { x: x2, y: y2 } = s.p2;
    const ang = Math.atan2(y2 - y1, x2 - x1);
    const head = Math.max(w * 4, 14);
    const bx = x2 - head * 0.8 * Math.cos(ang);
    const by = y2 - head * 0.8 * Math.sin(ang);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(bx, by);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - head * Math.cos(ang - Math.PI / 7), y2 - head * Math.sin(ang - Math.PI / 7));
    ctx.lineTo(x2 - head * Math.cos(ang + Math.PI / 7), y2 - head * Math.sin(ang + Math.PI / 7));
    ctx.closePath();
    ctx.fill();
  } else if (s.type === "rect") {
    ctx.strokeRect(Math.min(s.p1.x, s.p2.x), Math.min(s.p1.y, s.p2.y),
      Math.abs(s.p2.x - s.p1.x), Math.abs(s.p2.y - s.p1.y));
  } else if (s.type === "ellipse") {
    // Ellipse inscrite dans le rectangle tracé (entourer une zone)
    ctx.beginPath();
    ctx.ellipse((s.p1.x + s.p2.x) / 2, (s.p1.y + s.p2.y) / 2,
      Math.abs(s.p2.x - s.p1.x) / 2, Math.abs(s.p2.y - s.p1.y) / 2, 0, 0, Math.PI * 2);
    ctx.stroke();
  } else if (s.type === "text") {
    // Texte gras avec un contour contrasté : lisible sur fond clair ou sombre
    const size = Math.max(14, w * 7);
    ctx.font = `bold ${size}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.textBaseline = "top";
    ctx.lineWidth = Math.max(2, size / 7);
    ctx.strokeStyle = s.color === "#111827" ? "#ffffff" : "rgba(0,0,0,0.75)";
    ctx.strokeText(s.text, s.p1.x, s.p1.y);
    ctx.fillText(s.text, s.p1.x, s.p1.y);
  } else if (s.type === "number") {
    // Pastille ronde numérotée (étapes 1, 2, 3…)
    const r = Math.max(12, w * 5);
    ctx.beginPath();
    ctx.arc(s.p1.x, s.p1.y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.lineWidth = Math.max(2, r / 6);
    ctx.strokeStyle = "#ffffff";
    ctx.stroke();
    ctx.fillStyle = s.color === "#ffffff" || s.color === "#facc15" ? "#111827" : "#ffffff";
    ctx.font = `bold ${Math.round(r * 1.1)}px system-ui, -apple-system, "Segoe UI", sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(s.n), s.p1.x, s.p1.y + r * 0.05);
  } else if (s.type === "blur" && base) {
    // Pixelisation : la zone de l'image d'origine est réduite puis agrandie
    // sans lissage (gros carrés) — le contenu devient illisible.
    const x = Math.max(0, Math.round(Math.min(s.p1.x, s.p2.x)));
    const y = Math.max(0, Math.round(Math.min(s.p1.y, s.p2.y)));
    const rw = Math.min(base.width - x, Math.round(Math.abs(s.p2.x - s.p1.x)));
    const rh = Math.min(base.height - y, Math.round(Math.abs(s.p2.y - s.p1.y)));
    if (rw > 1 && rh > 1) {
      const block = Math.max(8, Math.round(Math.max(base.width, base.height) / 80));
      const tiny = document.createElement("canvas");
      tiny.width = Math.max(1, Math.ceil(rw / block));
      tiny.height = Math.max(1, Math.ceil(rh / block));
      tiny.getContext("2d").drawImage(base, x, y, rw, rh, 0, 0, tiny.width, tiny.height);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(tiny, 0, 0, tiny.width, tiny.height, x, y, rw, rh);
    }
  }
  ctx.restore();
}

export default function ImageAnnotator({ file, onCancel, onDone }) {
  const canvasRef = useRef(null);
  const baseRef = useRef(null);            // canvas hors écran : l'image seule
  const textInputRef = useRef(null);
  const [size, setSize] = useState(null);  // { w, h } de l'image produite
  const [loadError, setLoadError] = useState("");
  const [tool, setTool] = useState("arrow");
  const [color, setColor] = useState(COLORS[0]);
  const [thick, setThick] = useState(2);   // 1 fin, 2 moyen, 3 épais
  const [shapes, setShapes] = useState([]);
  const [redoStack, setRedoStack] = useState([]);
  const [draft, setDraft] = useState(null);          // forme en cours de tracé
  const [textBox, setTextBox] = useState(null);      // { p1, left, top } saisie de texte
  const [textValue, setTextValue] = useState("");
  const [saving, setSaving] = useState(false);

  // 1) Chargement de l'image dans le canvas « base » (réduite si très grande)
  useEffect(() => {
    if (!file) return undefined;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
      const w = Math.max(1, Math.round(img.naturalWidth * scale));
      const h = Math.max(1, Math.round(img.naturalHeight * scale));
      const base = document.createElement("canvas");
      base.width = w;
      base.height = h;
      base.getContext("2d").drawImage(img, 0, 0, w, h);
      baseRef.current = base;
      setSize({ w, h });
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      // Ex. photo HEIC d'iPhone : le navigateur ne sait pas l'afficher
      setLoadError("Ce format d'image ne peut pas être annoté dans le navigateur (ex. HEIC). Envoyez-la telle quelle ou convertissez-la en JPEG.");
      URL.revokeObjectURL(url);
    };
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Épaisseur du trait proportionnelle à la taille de l'image (même rendu
  // visuel sur une petite capture et sur une grande photo)
  const unit = size ? Math.max(2, Math.round(Math.max(size.w, size.h) / 400)) : 3;
  const strokeWidth = thick === 1 ? unit : thick === 2 ? unit * 2 : Math.round(unit * 3.5);

  // 2) Redessin complet : image + formes validées + forme en cours
  useEffect(() => {
    const cv = canvasRef.current;
    const base = baseRef.current;
    if (!cv || !base || !size) return;
    const ctx = cv.getContext("2d");
    ctx.clearRect(0, 0, size.w, size.h);
    ctx.drawImage(base, 0, 0);
    // Les zones floutées d'abord (elles masquent l'image), puis les autres
    // annotations par-dessus : une flèche ou un cercle n'est jamais effacé par un flou
    const all = draft ? [...shapes, draft] : shapes;
    all.filter((s) => s.type === "blur").forEach((s) => drawShape(ctx, s, base));
    all.filter((s) => s.type !== "blur").forEach((s) => drawShape(ctx, s, base));
  }, [shapes, draft, size]);

  // Position du pointeur convertie en coordonnées de l'image (le canvas est
  // affiché réduit à l'écran)
  const toImg = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) * size.w) / r.width,
      y: ((e.clientY - r.top) * size.h) / r.height,
    };
  };

  // Ajoute une forme validée (et vide la pile « Rétablir »)
  const commit = useCallback((s) => {
    setShapes((prev) => [...prev, s]);
    setRedoStack([]);
  }, []);

  // Valide le texte en cours de saisie (Entrée, clic ailleurs)
  const commitText = useCallback(() => {
    if (textBox && textValue.trim()) {
      commit({ type: "text", color, width: strokeWidth, p1: textBox.p1, text: textValue.trim() });
    }
    setTextBox(null);
    setTextValue("");
  }, [textBox, textValue, color, strokeWidth, commit]);

  const onPointerDown = (e) => {
    if (!size || saving) return;
    e.preventDefault();
    const p = toImg(e);
    if (tool === "text") {
      // Petite zone de saisie posée à l'endroit cliqué
      if (textBox) commitText();
      const r = canvasRef.current.getBoundingClientRect();
      setTextBox({ p1: p, left: e.clientX - r.left, top: e.clientY - r.top });
      setTextValue("");
      setTimeout(() => textInputRef.current?.focus(), 0);
      return;
    }
    if (tool === "number") {
      const n = shapes.filter((s) => s.type === "number").length + 1;
      commit({ type: "number", color, width: strokeWidth, p1: p, n });
      return;
    }
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* ancien navigateur */ }
    setDraft({ type: tool, color, width: strokeWidth, p1: p, p2: p, points: [p] });
  };

  const onPointerMove = (e) => {
    if (!draft) return;
    const p = toImg(e);
    setDraft((d) => {
      if (!d) return d;
      if (d.type === "pen" || d.type === "highlight") return { ...d, points: [...d.points, p] };
      return { ...d, p2: p };
    });
  };

  const onPointerUp = () => {
    if (!draft) return;
    const d = draft;
    setDraft(null);
    if (d.type === "pen" || d.type === "highlight") {
      commit(d);
      return;
    }
    // Forme trop petite (simple clic) : ignorée
    if (Math.hypot(d.p2.x - d.p1.x, d.p2.y - d.p1.y) < unit * 2) return;
    commit(d);
  };

  // Annuler / Rétablir : la dernière forme passe d'une pile à l'autre
  const undo = useCallback(() => {
    if (!shapes.length) return;
    setRedoStack((r) => [...r, shapes[shapes.length - 1]]);
    setShapes(shapes.slice(0, -1));
  }, [shapes]);

  const redo = useCallback(() => {
    if (!redoStack.length) return;
    setShapes((prev) => [...prev, redoStack[redoStack.length - 1]]);
    setRedoStack(redoStack.slice(0, -1));
  }, [redoStack]);

  // Raccourcis clavier : Ctrl+Z annuler, Ctrl+Y / Ctrl+Maj+Z rétablir, Échap fermer
  useEffect(() => {
    const onKey = (e) => {
      if (textBox) return;                   // la saisie de texte gère ses touches
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      else if ((e.ctrlKey || e.metaKey) && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); redo(); }
      else if (k === "escape") onCancel?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [textBox, undo, redo, onCancel]);

  // 3) « Terminer » : image + annotations fusionnées dans un nouveau fichier
  const finish = () => {
    const cv = canvasRef.current;
    if (!cv || saving) return;
    if (textBox) commitText();
    setSaving(true);
    // Laisse React redessiner le texte validé juste avant l'export
    setTimeout(() => {
      const keepPng = (file.type || "").toLowerCase() === "image/png";
      const type = keepPng ? "image/png" : "image/jpeg";
      const baseName = (file.name || "image").replace(/\.[^.]+$/, "");
      const done = (blob, t) => {
        const ext = t === "image/png" ? "png" : "jpg";
        onDone?.(new File([blob], `${baseName}-annotee.${ext}`, { type: t }));
      };
      cv.toBlob((blob) => {
        if (!blob) { setSaving(false); return; }
        if (blob.size > 15.5 * 1024 * 1024 && keepPng) {
          // PNG trop lourd pour WhatsApp (16 Mo) : on repasse en JPEG
          cv.toBlob((jpg) => (jpg ? done(jpg, "image/jpeg") : setSaving(false)), "image/jpeg", 0.9);
          return;
        }
        done(blob, type);
      }, type, 0.92);
    }, 30);
  };

  const iconBtn = "inline-flex items-center justify-center rounded-lg h-9 w-9 text-slate-200 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed";

  // Affiché au niveau de la page (portail) : au-dessus de la fenêtre de conversation
  return createPortal(
    <div className="fixed inset-0 z-[80] flex flex-col bg-slate-900/95" data-testid="image-annotator"
      role="dialog" aria-label="Annoter l'image">
      {/* Barre d'outils */}
      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 border-b border-white/10">
        <div className="flex flex-wrap items-center gap-1" role="toolbar" aria-label="Outils">
          {TOOLS.map(([key, label, Icon]) => (
            <button key={key} type="button" onClick={() => setTool(key)} title={label}
              data-testid={`annot-tool-${key}`}
              className={`inline-flex items-center gap-1 rounded-lg px-2 h-9 text-xs font-medium ${tool === key ? "bg-emerald-500 text-white" : "text-slate-200 hover:bg-white/10"}`}>
              <Icon className="h-4 w-4" /><span className="hidden md:inline">{label}</span>
            </button>
          ))}
        </div>
        <span className="mx-1 h-6 w-px bg-white/15" />
        {/* Couleurs */}
        <div className="flex items-center gap-1" aria-label="Couleur">
          {COLORS.map((c) => (
            <button key={c} type="button" onClick={() => setColor(c)} title="Couleur"
              data-testid={`annot-color-${c.slice(1)}`}
              className={`h-7 w-7 rounded-full ring-2 ${color === c ? "ring-emerald-400 scale-110" : "ring-white/20"}`}
              style={{ background: c }} />
          ))}
        </div>
        <span className="mx-1 h-6 w-px bg-white/15" />
        {/* Épaisseur */}
        <div className="flex items-center gap-1" aria-label="Épaisseur">
          {[1, 2, 3].map((t) => (
            <button key={t} type="button" onClick={() => setThick(t)}
              title={t === 1 ? "Fin" : t === 2 ? "Moyen" : "Épais"} data-testid={`annot-thick-${t}`}
              className={`inline-flex items-center justify-center h-9 w-9 rounded-lg ${thick === t ? "bg-white/15" : "hover:bg-white/10"}`}>
              <span className="rounded-full bg-slate-100" style={{ width: 4 + t * 4, height: 4 + t * 4 }} />
            </button>
          ))}
        </div>
        <span className="mx-1 h-6 w-px bg-white/15" />
        <button type="button" className={iconBtn} onClick={undo} disabled={!shapes.length} title="Annuler (Ctrl+Z)" data-testid="annot-undo">
          <Undo2 className="h-4 w-4" />
        </button>
        <button type="button" className={iconBtn} onClick={redo} disabled={!redoStack.length} title="Rétablir (Ctrl+Y)" data-testid="annot-redo">
          <Redo2 className="h-4 w-4" />
        </button>
        <button type="button" className={iconBtn} disabled={!shapes.length} title="Tout effacer" data-testid="annot-clear"
          onClick={() => { if (window.confirm("Effacer toutes les annotations ?")) { setShapes([]); setRedoStack([]); } }}>
          <Trash2 className="h-4 w-4" />
        </button>
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={onCancel} data-testid="annot-cancel"
            className="inline-flex items-center gap-1 rounded-lg px-3 h-9 text-sm text-slate-200 hover:bg-white/10">
            <X className="h-4 w-4" /> Annuler
          </button>
          <button type="button" onClick={finish} disabled={!size || saving} data-testid="annot-done"
            className="inline-flex items-center gap-1 rounded-lg px-3 h-9 text-sm font-semibold bg-emerald-500 hover:bg-emerald-600 text-white disabled:opacity-50">
            <Check className="h-4 w-4" /> {saving ? "Préparation…" : "Terminer"}
          </button>
        </div>
      </div>

      {/* Zone de dessin : l'image est affichée en entier, réduite si besoin */}
      <div className="flex-1 min-h-0 overflow-auto flex items-center justify-center p-3">
        {loadError ? (
          <p className="max-w-md text-center text-sm text-amber-200" data-testid="annot-error">{loadError}</p>
        ) : !size ? (
          <p className="text-sm text-slate-300">Chargement de l'image…</p>
        ) : (
          <div className="relative inline-block">
            <canvas
              ref={canvasRef}
              width={size.w}
              height={size.h}
              data-testid="annot-canvas"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              className="block rounded shadow-2xl bg-white"
              style={{
                maxWidth: "100%",
                maxHeight: "calc(100vh - 150px)",
                touchAction: "none",                     // le doigt dessine au lieu de faire défiler
                cursor: tool === "text" ? "text" : "crosshair",
              }}
            />
            {textBox && (
              <input
                ref={textInputRef}
                value={textValue}
                onChange={(e) => setTextValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); commitText(); }
                  if (e.key === "Escape") { e.preventDefault(); setTextBox(null); setTextValue(""); }
                }}
                onBlur={commitText}
                maxLength={120}
                placeholder="Votre texte, puis Entrée"
                data-testid="annot-text-input"
                className="absolute min-w-[12rem] rounded border-2 border-emerald-400 bg-white/95 px-2 py-1 text-sm font-semibold shadow-lg outline-none"
                style={{ left: textBox.left, top: textBox.top, color: color === "#ffffff" ? "#111827" : color }}
              />
            )}
          </div>
        )}
      </div>
      <p className="px-3 pb-2 text-center text-[11px] text-slate-400">
        Glissez sur l'image pour tracer · Texte et Numéro : cliquez à l'endroit voulu · Flouter : encadrez la zone à masquer
      </p>
    </div>,
    document.body,
  );
}
