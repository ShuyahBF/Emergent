// ChoixParticipants.jsx — Lot 61 : choix des participants d'un rendez-vous par leur NOM.
//
// On tape le début d'un nom (ou d'une société, ou quelques chiffres) : la liste des contacts
// correspondants s'affiche ; Entrée (ou clic) ajoute le premier proposé, puis on continue avec
// le suivant. Les flèches ↑ ↓ choisissent une autre proposition, Retour arrière sur une zone
// vide retire le dernier participant. Si aucun contact ne correspond et que la saisie est un
// numéro (8 chiffres ou plus), on peut l'ajouter tel quel.
//
// Valeur : tableau d'objets {contact_id?, name, phone} (format attendu par /me/appointments).
import React, { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { apiClient } from "@/lib/api";

// Texte sans accents et en minuscules (recherche « kabore » = « Kaboré »)
const normaliser = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
// Chiffres seuls d'un numéro
const chiffres = (t) => String(t || "").replace(/\D/g, "");

export default function ChoixParticipants({ participants = [], onChange, clientId = null, testid = "rdv-participants" }) {
  const [contacts, setContacts] = useState([]);
  const [saisie, setSaisie] = useState("");
  const [indexActif, setIndexActif] = useState(0);
  const [ouvert, setOuvert] = useState(false);
  const zoneRef = useRef(null);

  // Carnet de contacts visibles par l'utilisateur (chargé une fois)
  useEffect(() => {
    apiClient.get("/me/contacts")
      .then((r) => setContacts(Array.isArray(r.data) ? r.data : (r.data?.items || [])))
      .catch(() => setContacts([]));
  }, []);

  // Propositions : contacts dont le nom, la société ou le numéro contient la saisie
  const propositions = useMemo(() => {
    const q = normaliser(saisie.trim());
    const qChiffres = chiffres(saisie);
    if (!q) return [];
    const dejaChoisis = new Set(participants.map((p) => p.contact_id).filter(Boolean));
    const telsChoisis = new Set(participants.map((p) => chiffres(p.phone).slice(-8)).filter(Boolean));
    return contacts
      .filter((c) => !clientId || !c.client_id || c.client_id === clientId)
      .filter((c) => !dejaChoisis.has(c.id) && !telsChoisis.has(chiffres(c.whatsapp || c.phone).slice(-8)))
      .filter((c) => {
        const nom = normaliser(c.name);
        // Correspondance sur le début d'un mot du nom, la société, ou les chiffres du numéro
        return nom.split(/\s+/).some((m) => m.startsWith(q)) || nom.includes(q)
          || normaliser(c.company).includes(q)
          || (qChiffres.length >= 3 && chiffres(`${c.whatsapp || ""} ${c.phone || ""}`).includes(qChiffres));
      })
      .sort((a, b) => {
        // Les noms qui COMMENCENT par la saisie d'abord
        const da = normaliser(a.name).startsWith(q) ? 0 : 1;
        const dbb = normaliser(b.name).startsWith(q) ? 0 : 1;
        return da - dbb || String(a.name || "").localeCompare(String(b.name || ""), "fr");
      })
      .slice(0, 8);
  }, [saisie, contacts, participants, clientId]);

  // Saisie d'un numéro sans contact correspondant : ajout possible tel quel
  const numeroLibre = chiffres(saisie).length >= 8 && propositions.length === 0 ? saisie.trim() : null;

  // Ajoute un contact du carnet
  const ajouterContact = (c) => {
    onChange([...participants, { contact_id: c.id, name: c.name || "", phone: c.whatsapp || c.phone || "" }]);
    setSaisie(""); setIndexActif(0); setOuvert(false);
    zoneRef.current?.focus();
  };

  // Ajoute un numéro saisi à la main
  const ajouterNumero = (numero) => {
    onChange([...participants, { name: numero, phone: numero }]);
    setSaisie(""); setIndexActif(0); setOuvert(false);
  };

  // Retire un participant
  const retirer = (idx) => onChange(participants.filter((_, i) => i !== idx));

  // Clavier : Entrée / Tab / virgule = ajouter, flèches = choisir, Retour arrière = retirer le dernier
  const surTouche = (e) => {
    if ((e.key === "Enter" || e.key === "," || (e.key === "Tab" && saisie.trim())) && (propositions.length || numeroLibre)) {
      e.preventDefault();
      if (propositions.length) ajouterContact(propositions[Math.min(indexActif, propositions.length - 1)]);
      else ajouterNumero(numeroLibre);
    } else if (e.key === "Enter") {
      e.preventDefault();                      // jamais d'envoi du formulaire depuis cette zone
    } else if (e.key === "ArrowDown") {
      e.preventDefault(); setIndexActif((i) => Math.min(i + 1, Math.max(propositions.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault(); setIndexActif((i) => Math.max(i - 1, 0));
    } else if (e.key === "Backspace" && !saisie && participants.length) {
      retirer(participants.length - 1);
    } else if (e.key === "Escape") {
      setOuvert(false);
    }
  };

  return (
    <div className="relative" data-testid={testid}>
      {/* Zone de saisie avec les participants déjà choisis (étiquettes) */}
      <div
        className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2 py-1.5 focus-within:ring-2 focus-within:ring-teal-300"
        onClick={() => zoneRef.current?.focus()}
      >
        {participants.map((p, idx) => (
          <span key={p.contact_id || `${p.phone}-${idx}`}
            className="inline-flex items-center gap-1 rounded-full border border-teal-300 bg-teal-50 px-2 py-0.5 text-xs"
            data-testid={`${testid}-chip-${idx}`}>
            <span className="font-medium text-teal-800">{p.name || p.phone}</span>
            {p.phone && p.name !== p.phone && <span className="font-mono text-[10px] text-slate-500">{p.phone}</span>}
            <button type="button" onClick={(e) => { e.stopPropagation(); retirer(idx); }}
              className="text-slate-400 hover:text-rose-600" title="Retirer">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          ref={zoneRef}
          type="text"
          value={saisie}
          onChange={(e) => { setSaisie(e.target.value); setIndexActif(0); setOuvert(true); }}
          onKeyDown={surTouche}
          onFocus={() => setOuvert(true)}
          onBlur={() => setTimeout(() => setOuvert(false), 150)}
          placeholder={participants.length ? "Ajouter un autre nom…" : "Tapez le nom d'un contact (ex. Kaboré)…"}
          className="min-w-[160px] flex-1 border-0 bg-transparent px-1 py-1 text-sm outline-none"
          data-testid={`${testid}-saisie`}
        />
      </div>

      {/* Propositions */}
      {ouvert && saisie.trim() && (propositions.length > 0 || numeroLibre) && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-56 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg"
          data-testid={`${testid}-propositions`}>
          {propositions.map((c, i) => (
            <button key={c.id} type="button"
              onMouseDown={(e) => { e.preventDefault(); ajouterContact(c); }}
              onMouseEnter={() => setIndexActif(i)}
              className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm ${i === indexActif ? "bg-teal-50" : "hover:bg-slate-50"}`}>
              <span>
                <span className="font-medium">{c.name}</span>
                {c.company && <span className="ml-1 text-xs text-slate-500">· {c.company}</span>}
              </span>
              <span className="font-mono text-xs text-slate-500">{c.whatsapp || c.phone || "—"}</span>
            </button>
          ))}
          {numeroLibre && (
            <button type="button" onMouseDown={(e) => { e.preventDefault(); ajouterNumero(numeroLibre); }}
              className="w-full bg-teal-50 px-3 py-2 text-left text-sm">
              ➕ Ajouter le numéro <span className="font-mono">{numeroLibre}</span> (absent du carnet)
            </button>
          )}
        </div>
      )}
      {ouvert && saisie.trim() && propositions.length === 0 && !numeroLibre && (
        <p className="mt-1 text-[11px] text-slate-500">Aucun contact ne correspond. Vous pouvez aussi saisir un numéro complet.</p>
      )}
    </div>
  );
}
