// components/vidal/ChampDate.jsx
// ------------------------------------------------
// Champ de date des modules VIDAL (Analyse et Sécurisation) — demande du
// propriétaire : remonter jusqu'en 1960 avec le calendrier est fastidieux.
// Trois façons de renseigner une date, au choix :
//   1. SAISIE AU CLAVIER « JJ/MM/AAAA » : les « / » s'ajoutent tout seuls,
//      l'année peut aussi être tapée sur 2 chiffres (« 12/05/60 » → 1960) ;
//   2. bouton CALENDRIER à droite du champ (calendrier natif du navigateur) ;
//   3. option `avecAge` : petit champ « ou âge (ans) » qui calcule la date.
// La valeur échangée avec le parent reste au format ISO « AAAA-MM-JJ »
// (comme un <input type="date">), et `onChange` reçoit un objet
// { target: { value } } : le composant remplace donc un <input type="date">
// sans toucher au reste du code.
// ------------------------------------------------
import { useEffect, useRef, useState } from "react";
import { CalendarDays } from "lucide-react";

// ---------------------------------------------------------------------------
// Conversions de dates (fonctions pures, exportées pour être réutilisées)
// ---------------------------------------------------------------------------

// « AAAA-MM-JJ » → « JJ/MM/AAAA » (chaîne vide si la valeur est vide ou mal formée)
export function isoVersFr(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

// Vérifie qu'un jour / mois / année forme une vraie date (pas de 31/02)
function dateValide(j, m, a) {
  const d = new Date(Date.UTC(a, m - 1, j));
  return d.getUTCFullYear() === a && d.getUTCMonth() === m - 1 && d.getUTCDate() === j;
}

// Date du jour en ISO (heure locale du poste)
function aujourdhuiIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// « JJ/MM/AAAA » ou « JJ/MM/AA » → « AAAA-MM-JJ » ; null si la saisie n'est pas une date valide.
// Année sur 2 chiffres : au-delà de l'année en cours → 19xx, sinon 20xx (« 60 » → 1960, « 05 » → 2005).
export function frVersIso(texte) {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/.exec((texte || "").trim());
  if (!m) return null;
  const j = Number(m[1]);
  const mois = Number(m[2]);
  let a = Number(m[3]);
  if (m[3].length === 2) {
    const courant = new Date().getFullYear() % 100;
    a += a > courant ? 1900 : 2000;
  }
  if (!dateValide(j, mois, a)) return null;
  return `${a}-${String(mois).padStart(2, "0")}-${String(j).padStart(2, "0")}`;
}

// Met en forme la frappe : ne garde que les chiffres et insère les « / » (JJ/MM/AAAA)
function formaterFrappe(brut) {
  const chiffres = (brut || "").replace(/\D/g, "").slice(0, 8);
  if (chiffres.length <= 2) return chiffres;
  if (chiffres.length <= 4) return `${chiffres.slice(0, 2)}/${chiffres.slice(2)}`;
  return `${chiffres.slice(0, 2)}/${chiffres.slice(2, 4)}/${chiffres.slice(4)}`;
}

// Âge révolu (en années) à la date du jour ; null si pas de date
export function ageDepuisIso(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return null;
  const t = new Date();
  let age = t.getFullYear() - Number(m[1]);
  // Anniversaire pas encore passé cette année : un an de moins
  if (t.getMonth() + 1 < Number(m[2]) || (t.getMonth() + 1 === Number(m[2]) && t.getDate() < Number(m[3]))) age -= 1;
  return age;
}

// Âge (ans) → date de naissance ISO.
// Si une date existe déjà, on garde son jour et son mois et on ajuste seulement l'année
// pour que l'âge calculé soit exactement celui saisi ; sinon on prend le jour et le mois
// d'aujourd'hui (la personne a « pile » cet âge aujourd'hui).
export function dateDepuisAge(age, isoExistant) {
  const n = Number(age);
  if (!Number.isInteger(n) || n < 0 || n > 130) return null;
  const t = new Date();
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoExistant || "");
  const mois = m ? Number(m[2]) : t.getMonth() + 1;
  let jour = m ? Number(m[3]) : t.getDate();
  let annee = t.getFullYear() - n;
  // Anniversaire pas encore passé cette année : la naissance est un an plus tôt
  if (t.getMonth() + 1 < mois || (t.getMonth() + 1 === mois && t.getDate() < jour)) annee -= 1;
  // 29 février sur une année non bissextile : on recule au 28
  if (!dateValide(jour, mois, annee)) jour = 28;
  return `${annee}-${String(mois).padStart(2, "0")}-${String(jour).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Le composant
// ---------------------------------------------------------------------------
export default function ChampDate({
  value, onChange, min, max, disabled = false, className = "champ-saisie", style, avecAge = false, placeholder = "JJ/MM/AAAA", ...reste
}) {
  // Texte affiché dans le champ (« JJ/MM/AAAA »), indépendant tant que la saisie est incomplète
  const [texte, setTexte] = useState(isoVersFr(value));
  const [invalide, setInvalide] = useState(false);
  const refCalendrier = useRef(null);

  // La valeur change depuis l'extérieur (patient chargé, calendrier, âge…) : on réaligne le texte
  useEffect(() => {
    if (frVersIso(texte) !== (value || null)) {
      setTexte(isoVersFr(value));
      setInvalide(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  // Transmet une valeur ISO au parent, sous la forme d'un événement de champ
  const transmettre = (iso) => onChange && onChange({ target: { value: iso } });

  // Frappe au clavier : mise en forme, puis transmission dès que la date est complète et valide
  const changerTexte = (e) => {
    const brut = e.target.value;
    // Effacement d'un « / » : on laisse l'utilisateur effacer normalement
    const nouveau = brut.length < texte.length ? brut : formaterFrappe(brut);
    setTexte(nouveau);
    if (!nouveau) { setInvalide(false); transmettre(""); return; }
    const iso = nouveau.replace(/\D/g, "").length === 8 ? frVersIso(nouveau) : null;
    if (iso) { setInvalide(false); transmettre(iso); }
  };

  // En quittant le champ : on accepte aussi l'année sur 2 chiffres, sinon on signale l'erreur
  const quitterChamp = () => {
    if (!texte) return;
    const iso = frVersIso(texte);
    if (iso) {
      setInvalide(false);
      setTexte(isoVersFr(iso));
      if (iso !== value) transmettre(iso);
    } else {
      // Saisie invalide : signalée en rouge, et le parent ne garde pas l'ancienne date
      setInvalide(true);
      if (value) transmettre("");
    }
  };

  // Bouton calendrier : ouvre le calendrier natif du champ date caché
  const ouvrirCalendrier = () => {
    const champ = refCalendrier.current;
    if (!champ || disabled) return;
    try { champ.showPicker(); } catch { champ.focus(); champ.click(); }
  };

  // Hors bornes (min / max) : simple avertissement, le parent garde ses propres contrôles
  const horsBornes = value && ((min && value < min) || (max && value > max));
  const age = ageDepuisIso(value);

  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 8, flexWrap: "wrap" }}>
      <div style={{ position: "relative", flex: "1 1 120px", minWidth: 0 }}>
        {/* Saisie au clavier JJ/MM/AAAA (clavier numérique sur téléphone) */}
        <input
          {...reste}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          className={className}
          placeholder={placeholder}
          value={texte}
          disabled={disabled}
          onChange={changerTexte}
          onBlur={quitterChamp}
          style={{ ...style, paddingRight: 34, ...(invalide ? { borderColor: "#dc2626" } : {}) }}
        />
        {/* Bouton calendrier, à droite dans le champ */}
        <button
          type="button"
          onClick={ouvrirCalendrier}
          disabled={disabled}
          title="Choisir dans le calendrier"
          aria-label="Choisir dans le calendrier"
          style={{
            position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)", border: 0, background: "transparent",
            padding: 4, cursor: disabled ? "default" : "pointer", color: "inherit", opacity: disabled ? 0.4 : 0.75, display: "flex",
          }}
        >
          <CalendarDays size={16} />
        </button>
        {/* Champ date natif, invisible : il ne sert qu'à afficher le calendrier du navigateur */}
        <input
          ref={refCalendrier}
          type="date"
          tabIndex={-1}
          aria-hidden="true"
          value={value || ""}
          min={min}
          max={max}
          onChange={(e) => transmettre(e.target.value)}
          style={{ position: "absolute", right: 0, bottom: 0, width: 1, height: 1, opacity: 0, pointerEvents: "none", border: 0, padding: 0 }}
        />
        {/* Messages sous le champ */}
        {invalide && <div style={{ fontSize: 11, color: "#dc2626", marginTop: 2 }}>Date invalide — format JJ/MM/AAAA</div>}
        {!invalide && horsBornes && (
          <div style={{ fontSize: 11, color: "#b45309", marginTop: 2 }}>
            {max && value > max ? `Date postérieure au ${isoVersFr(max)}` : `Date antérieure au ${isoVersFr(min)}`}
          </div>
        )}
      </div>
      {/* Option : saisie de l'âge, la date de naissance s'y adapte */}
      {avecAge && (
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, whiteSpace: "nowrap" }}>
          ou âge
          <input
            type="number"
            min={0}
            max={130}
            className={className}
            style={{ ...style, width: 64 }}
            value={age == null ? "" : age}
            disabled={disabled}
            onChange={(e) => {
              if (e.target.value === "") { transmettre(""); return; }
              const iso = dateDepuisAge(e.target.value, value);
              if (iso) transmettre(iso);
            }}
          />
          ans
        </label>
      )}
    </div>
  );
}

// Date du jour ISO, utile aux parents pour la borne `max`
export { aujourdhuiIso };
