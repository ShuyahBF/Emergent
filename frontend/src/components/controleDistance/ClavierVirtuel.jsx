// =====================================================================
// Lot 135 — CLAVIER VIRTUEL de la visionneuse (item 5) : touches simples et touches de fonction envoyées au poste,
// même quand le clavier du technicien ne peut pas les produire (F1 à F12, Windows, Impr. écran, Alt+Tab…).
// Les touches « mortes » Ctrl, Alt, Maj et Windows restent ENFONCÉES (orange) jusqu'à la touche suivante : on compose
// ainsi n'importe quelle combinaison (ex. Ctrl puis Maj puis Échap = Gestionnaire des tâches).
// Codes envoyés : KeyboardEvent.code du navigateur, convertis en touches Windows par Loois.
// =====================================================================
import React, { useState } from "react";
import { X } from "lucide-react";

// Touches « mortes » (restent enfoncées jusqu'à la touche suivante)
const MODIFICATEURS = [
  ["ControlLeft", "Ctrl"], ["AltLeft", "Alt"], ["ShiftLeft", "Maj"], ["MetaLeft", "⊞ Win"],
];

// Rangées du clavier (code, libellé, largeur relative facultative)
const RANGEES = [
  [["Escape", "Échap"], ["F1"], ["F2"], ["F3"], ["F4"], ["F5"], ["F6"], ["F7"], ["F8"], ["F9"], ["F10"], ["F11"], ["F12"],
   ["PrintScreen", "Impr."], ["Pause", "Pause"]],
  [["Backquote", "²"], ["Digit1", "1"], ["Digit2", "2"], ["Digit3", "3"], ["Digit4", "4"], ["Digit5", "5"], ["Digit6", "6"],
   ["Digit7", "7"], ["Digit8", "8"], ["Digit9", "9"], ["Digit0", "0"], ["Minus", ")"], ["Equal", "="], ["Backspace", "⌫", 2]],
  [["Tab", "Tab ⇥", 1.5], ["KeyQ", "A"], ["KeyW", "Z"], ["KeyE", "E"], ["KeyR", "R"], ["KeyT", "T"], ["KeyY", "Y"], ["KeyU", "U"],
   ["KeyI", "I"], ["KeyO", "O"], ["KeyP", "P"], ["BracketLeft", "^"], ["BracketRight", "$"], ["Enter", "Entrée ↵", 1.5]],
  [["CapsLock", "Verr. Maj", 1.75], ["KeyA", "Q"], ["KeyS", "S"], ["KeyD", "D"], ["KeyF", "F"], ["KeyG", "G"], ["KeyH", "H"],
   ["KeyJ", "J"], ["KeyK", "K"], ["KeyL", "L"], ["Semicolon", "M"], ["Quote", "ù"], ["Backslash", "*"]],
  [["IntlBackslash", "<"], ["KeyZ", "W"], ["KeyX", "X"], ["KeyC", "C"], ["KeyV", "V"], ["KeyB", "B"], ["KeyN", "N"], ["KeyM", ","],
   ["Comma", ";"], ["Period", ":"], ["Slash", "!"], ["Space", "Espace", 3]],
  [["Insert", "Inser"], ["Delete", "Suppr"], ["Home", "Début"], ["End", "Fin"], ["PageUp", "Pg ↑"], ["PageDown", "Pg ↓"],
   ["ArrowLeft", "←"], ["ArrowUp", "↑"], ["ArrowDown", "↓"], ["ArrowRight", "→"], ["ContextMenu", "☰ Menu"], ["NumLock", "Verr. Num"]],
];

// Raccourcis usuels en un clic
const RACCOURCIS = [
  [["AltLeft", "Tab"], "Alt+Tab"], [["AltLeft", "F4"], "Alt+F4"], [["ControlLeft", "KeyC"], "Ctrl+C"], [["ControlLeft", "KeyV"], "Ctrl+V"],
  [["ControlLeft", "KeyZ"], "Ctrl+Z"], [["ControlLeft", "KeyA"], "Ctrl+A"], [["ControlLeft", "KeyS"], "Ctrl+S"], [["ControlLeft", "KeyP"], "Ctrl+P"],
  [["MetaLeft", "KeyD"], "Win+D (bureau)"], [["MetaLeft", "KeyE"], "Win+E (explorateur)"], [["MetaLeft", "KeyR"], "Win+R (exécuter)"],
  [["MetaLeft", "KeyL"], "Win+L (verrouiller)"], [["ControlLeft", "ShiftLeft", "Escape"], "Gestionnaire des tâches"],
];

export default function ClavierVirtuel({ envoyer, actif, onFermer }) {
  const [enfonces, setEnfonces] = useState([]);   // modificateurs actuellement enfoncés

  // Appui puis relâchement d'une touche, entourée des modificateurs enfoncés (qui sont ensuite relâchés)
  const taper = (code) => {
    if (!actif) return;
    enfonces.forEach((m) => envoyer({ type: "clavier", action: "bas", code: m }));
    envoyer({ type: "clavier", action: "bas", code });
    envoyer({ type: "clavier", action: "haut", code });
    [...enfonces].reverse().forEach((m) => envoyer({ type: "clavier", action: "haut", code: m }));
    setEnfonces([]);
  };

  // Combinaison complète en un geste
  const combinaison = (codes) => {
    if (!actif) return;
    codes.forEach((code) => envoyer({ type: "clavier", action: "bas", code }));
    [...codes].reverse().forEach((code) => envoyer({ type: "clavier", action: "haut", code }));
  };

  const basculer = (code) => setEnfonces((e) => (e.includes(code) ? e.filter((x) => x !== code) : [...e, code]));

  const touche = "h-8 rounded-md bg-slate-700 px-1.5 text-[11px] font-medium text-slate-100 shadow hover:bg-slate-600 active:translate-y-px disabled:opacity-40";

  return (
    <div className="mx-auto mb-2 w-full max-w-5xl rounded-2xl bg-slate-900/95 p-2 ring-1 ring-white/10 backdrop-blur" data-testid="controle-distance-clavier">
      <div className="mb-1.5 flex flex-wrap items-center gap-1">
        {MODIFICATEURS.map(([code, libelle]) => (
          <button key={code} type="button" disabled={!actif} onClick={() => basculer(code)}
                  className={`${touche} ${enfonces.includes(code) ? "!bg-orange-500 text-white" : ""}`}
                  title="Reste enfoncée jusqu'à la touche suivante">
            {libelle}
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-white/10" />
        {RACCOURCIS.map(([codes, libelle]) => (
          <button key={libelle} type="button" disabled={!actif} onClick={() => combinaison(codes)} className={`${touche} bg-indigo-700 hover:bg-indigo-600`}>
            {libelle}
          </button>
        ))}
        <button type="button" onClick={onFermer} title="Fermer le clavier virtuel"
                className="ml-auto grid h-7 w-7 place-items-center rounded-full bg-rose-600 text-white hover:bg-rose-500">
          <X className="h-4 w-4" />
        </button>
      </div>
      {RANGEES.map((rangee, i) => (
        <div key={i} className="mb-1 flex gap-1">
          {rangee.map(([code, libelle, largeur]) => (
            <button key={code} type="button" disabled={!actif} onClick={() => taper(code)} className={touche}
                    style={{ flex: largeur || 1 }} data-code={code}>
              {libelle || code}
            </button>
          ))}
        </div>
      ))}
      <p className="text-center text-[10px] text-slate-400">
        Disposition AZERTY affichée ; la touche envoyée est la touche physique (le poste applique sa propre disposition).
        Ctrl+Alt+Suppr : menu des actions système.
      </p>
    </div>
  );
}
