// ocr-core (module commun, source unique : dépôt ShuyahBF/Claude, dossier ocr-core/).
// Ne pas modifier dans un site : corriger dans ocr-core puis resynchroniser.
//
// Note de 1 à 5 étoiles. Cliquable si `onChange` est fourni, sinon simple
// affichage (ex. note moyenne dans un tableau).
import React from "react";
import { Star } from "lucide-react";

export default function StarRating({ value = 0, onChange, size = 20 }) {
  const readOnly = !onChange;
  return (
    <div className="inline-flex items-center gap-0.5" role={readOnly ? "img" : "radiogroup"}
      aria-label={`${value || 0} sur 5 étoiles`}>
      {[1, 2, 3, 4, 5].map((n) => {
        const filled = n <= Math.round(value || 0);
        const star = (
          <Star width={size} height={size}
            className={filled ? "fill-amber-400 text-amber-400" : "text-slate-300"} />
        );
        return readOnly ? (
          <span key={n}>{star}</span>
        ) : (
          <button key={n} type="button" role="radio" aria-checked={n === value}
            aria-label={`${n} étoile${n > 1 ? "s" : ""}`} onClick={() => onChange(n)}
            className="p-0.5 rounded hover:scale-110 transition-transform" data-testid={`ocr-star-${n}`}>
            {star}
          </button>
        );
      })}
    </div>
  );
}
