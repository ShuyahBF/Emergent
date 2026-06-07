// Iter42c (2026-02) — Composant Scanner code-barres pour les officines.
//
// Supporte les formats principaux des boîtes de médicaments en France :
//   - EAN-13 (le CIP-13 est encodé directement comme EAN-13)
//   - Data Matrix 2D (depuis 2011 — contient AI 01 = GTIN/CIP-13)
//   - Code 128 (étiquettes lot/N° de série)
//
// Le composant ouvre la caméra, scanne en continu et retourne le code détecté
// dès la première lecture stable.
import React from "react";
import { BrowserMultiFormatReader } from "@zxing/browser";
import { BarcodeFormat, DecodeHintType } from "@zxing/library";
import { X, Camera, AlertTriangle, ScanLine } from "lucide-react";

const TARGET_FORMATS = [
  BarcodeFormat.EAN_13,
  BarcodeFormat.EAN_8,
  BarcodeFormat.UPC_A,
  BarcodeFormat.DATA_MATRIX,
  BarcodeFormat.CODE_128,
  BarcodeFormat.QR_CODE,
];

/**
 * Extrait le CIP/GTIN d'un code Data Matrix GS1 (préfixe AI 01 + 14 digits).
 * Pour un EAN-13, on retourne tel quel (le CIP-13 = EAN-13 sans préfixe).
 */
function extractCip(text, format) {
  if (!text) return null;
  // Data Matrix GS1 : (01)03400930000000(17)YYMMDD(10)LOT...
  // Le séparateur FNC1 est rendu comme caractère ASCII 29 (GS) ou rien.
  const cleaned = String(text).replace(/[\u001d]/g, "|"); // GS → |
  const m = cleaned.match(/(?:^|\|)01(\d{14})/);
  if (m) {
    // GTIN-14 → on retourne les 13 derniers chiffres (= CIP-13 si stocké en EAN-13)
    return m[1].slice(-13);
  }
  // EAN-13 directement
  if (format === BarcodeFormat.EAN_13 && /^\d{13}$/.test(text)) {
    return text;
  }
  // Fallback : si c'est purement numérique 8-14 chiffres, on retourne
  if (/^\d{8,14}$/.test(text.trim())) return text.trim();
  // Sinon retour brut
  return text;
}

export default function BarcodeScannerModal({ onClose, onDetected }) {
  const videoRef = React.useRef(null);
  const controlsRef = React.useRef(null);
  const [error, setError] = React.useState(null);
  const [permissionAsked, setPermissionAsked] = React.useState(false);
  const [lastDetected, setLastDetected] = React.useState(null);

  React.useEffect(() => {
    let alive = true;
    const hints = new Map();
    hints.set(DecodeHintType.POSSIBLE_FORMATS, TARGET_FORMATS);
    hints.set(DecodeHintType.TRY_HARDER, true);
    const reader = new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: 200 });

    async function start() {
      try {
        setPermissionAsked(true);
        const devices = await BrowserMultiFormatReader.listVideoInputDevices();
        if (!alive) return;
        if (!devices || devices.length === 0) {
          setError("Aucune caméra détectée sur l'appareil.");
          return;
        }
        // Prioriser la caméra arrière sur mobile
        const back = devices.find((d) => /back|rear|environment/i.test(d.label));
        const deviceId = (back || devices[devices.length - 1]).deviceId;
        const controls = await reader.decodeFromVideoDevice(
          deviceId,
          videoRef.current,
          (result, err) => {
            if (!alive) return;
            if (result) {
              const raw = result.getText();
              const fmt = result.getBarcodeFormat();
              const cip = extractCip(raw, fmt);
              setLastDetected({ raw, cip, format: fmt });
              if (cip) {
                // Petite pause avant fermeture pour feedback visuel
                setTimeout(() => {
                  if (alive) {
                    onDetected({ cip, raw, format: fmt });
                  }
                }, 400);
              }
            }
            // err is thrown for every "not found" frame — ignore
          }
        );
        controlsRef.current = controls;
      } catch (e) {
        if (!alive) return;
        const msg = e?.name === "NotAllowedError"
          ? "Permission caméra refusée. Activez-la dans les réglages de votre navigateur."
          : e?.message || "Erreur d'initialisation du scanner.";
        setError(msg);
      }
    }
    start();
    return () => {
      alive = false;
      try { controlsRef.current?.stop(); } catch { /* noop */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="fixed inset-0 z-[60] bg-black/90 flex items-center justify-center p-4" data-testid="barcode-scanner-modal">
      <div className="bg-slate-900 rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <div className="flex items-center gap-2 text-white">
            <Camera className="h-5 w-5 text-emerald-400" />
            <h3 className="font-display font-semibold">Scanner un code-barres</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1" data-testid="scanner-close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="relative bg-black aspect-square">
          {error ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-white p-6 text-center" data-testid="scanner-error">
              <AlertTriangle className="h-10 w-10 text-amber-400" />
              <p className="mt-3 text-sm">{error}</p>
            </div>
          ) : (
            <>
              <video
                ref={videoRef}
                className="absolute inset-0 w-full h-full object-cover"
                muted
                playsInline
                data-testid="scanner-video"
              />
              {/* Overlay : visualisation */}
              <div className="absolute inset-0 pointer-events-none flex items-center justify-center">
                <div className="w-3/4 h-1/2 border-2 border-emerald-400/80 rounded-lg shadow-[0_0_20px_rgba(16,185,129,0.5)]">
                  <ScanLine className="h-8 w-8 text-emerald-400 mx-auto mt-2 animate-pulse" />
                </div>
              </div>
              {!permissionAsked && (
                <div className="absolute bottom-4 left-4 right-4 bg-black/70 rounded-lg p-3 text-center text-white text-xs">
                  Demande d&apos;accès à la caméra…
                </div>
              )}
            </>
          )}
        </div>
        <div className="p-4 text-xs text-slate-300 space-y-2">
          <p>Pointez la caméra vers le code-barres ou le Data Matrix de la boîte de médicament.</p>
          {lastDetected && (
            <div className="bg-emerald-900/30 ring-1 ring-emerald-700 rounded p-2" data-testid="scanner-last">
              <p className="text-emerald-300 font-medium">✓ Code détecté</p>
              {lastDetected.cip && <p className="font-mono text-emerald-100">CIP : {lastDetected.cip}</p>}
              <p className="text-[10px] text-slate-400 mt-0.5 break-all">Raw : {lastDetected.raw}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
