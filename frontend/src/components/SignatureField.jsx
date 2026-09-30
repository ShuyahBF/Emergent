/*
  Signature manuscrite via signature_pad (tracé au doigt, au stylet ou à la souris).
  Partagé par les formulaires (champ « signature », pages/portal/FormRunner.jsx) et, depuis
  le lot 47, par la signature du rapport d'intervention du parc informatique
  (pages/public/RapportParc.jsx). `onChange` reçoit l'image PNG (data URL) ou null.
*/
import React, { useEffect, useRef } from "react";
import SignaturePad from "signature_pad";

export default function SignatureField({ value, onChange }) {
  const canvasRef = useRef(null);
  const padRef = useRef(null);
  useEffect(() => {
    if (!canvasRef.current) return;
    // Ensure canvas backing store matches CSS size for crisp lines on HiDPI
    const canvas = canvasRef.current;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    canvas.getContext("2d").scale(ratio, ratio);
    padRef.current = new SignaturePad(canvas, { backgroundColor: "rgba(255,255,255,1)", penColor: "#0f172a" });
    padRef.current.addEventListener("endStroke", () => {
      onChange(padRef.current.toDataURL("image/png"));
    });
    if (value && typeof value === "string" && value.startsWith("data:image")) {
      padRef.current.fromDataURL(value);
    }
    return () => padRef.current?.off();
    // eslint-disable-next-line
  }, []);
  const clear = () => { padRef.current?.clear(); onChange(null); };
  return (
    <div className="space-y-2" data-testid="signature-field">
      <canvas ref={canvasRef} className="w-full h-40 bg-white rounded-lg ring-1 ring-slate-300 cursor-crosshair touch-none" />
      <div className="flex justify-between text-[11px]">
        <span className="text-slate-400 italic">Tracez votre signature ci-dessus</span>
        <button type="button" onClick={clear} className="text-rose-600 hover:underline" data-testid="signature-clear">
          Effacer la signature
        </button>
      </div>
    </div>
  );
}
