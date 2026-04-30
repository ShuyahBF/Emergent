import React, { useState, forwardRef } from "react";
import { Eye, EyeOff } from "lucide-react";

/**
 * Password / sensitive value input with show/hide eye toggle.
 * Drop-in replacement for `<input type="password" />` — same props pass-through.
 */
const PasswordInput = forwardRef(function PasswordInput(
  { className = "", testid, autoComplete = "current-password", icon = null, ...rest },
  ref,
) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="relative">
      {icon && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">{icon}</span>}
      <input
        {...rest}
        ref={ref}
        type={revealed ? "text" : "password"}
        autoComplete={autoComplete}
        data-testid={testid}
        className={`${className} pr-10 ${icon ? "pl-9" : ""}`.trim()}
      />
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setRevealed((v) => !v)}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-sawali-blue focus:outline-none"
        aria-label={revealed ? "Masquer" : "Afficher"}
        title={revealed ? "Masquer" : "Afficher"}
        data-testid={testid ? `${testid}-eye` : "password-eye"}
        tabIndex={-1}
      >
        {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
});

export default PasswordInput;
